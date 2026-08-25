"""Assemble the Windows package for the eTamil IDE.

Produces a folder and a zip containing everything except the editor itself:

    eTamil-IDE-<version>-win-x64/
      Install.ps1
      README.txt
      compiler/     etamil.exe, nUlakam, examples
      pary/         pary-server.exe and everything it needs
      extensions/   the two .vsix
      profile/      settings and keybindings

The editor is not in there. VSCodium is a hundred megabytes that Microsoft's
own source builds and its maintainers ship; re-hosting a copy inside this zip
would mean shipping an editor nobody updates. `Install.ps1` finds an installed
one, or offers to fetch it with winget.

    python packaging/windows/build.py
    python packaging/windows/build.py --skip-freeze   # reuse the last exe

Every step it takes is a step that has to have happened for the package to
work, so it refuses rather than producing a zip with a hole in it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

from paRY import __version__, config  # noqa: E402
from paRY import lexicon  # noqa: E402

TARGET = "win-x64"
FROZEN = REPO / "build" / "pyinstaller" / "dist" / "pary-server"

# What the runtime actually needs. The tokenizer and the raw corpus are build
# inputs, not runtime ones — an installed paRY answers from the index.
RUNTIME_DATA = ("index/paRY.db", "lexicon.json")


def say(step: str) -> None:
    print(f"  {step}")


def freeze(skip: bool) -> Path:
    """Build pary-server.exe, so the package needs no Python on the machine."""
    if skip:
        if not (FROZEN / "pary-server.exe").exists():
            raise SystemExit(f"--skip-freeze, but nothing at {FROZEN}")
        say(f"reusing {FROZEN.name}")
        return FROZEN

    say("freezing the server (PyInstaller)")
    completed = subprocess.run(
        [
            sys.executable, "-m", "PyInstaller",
            "--onedir", "--name", "pary-server", "--noconfirm", "--clean",
            "--distpath", str(REPO / "build" / "pyinstaller" / "dist"),
            "--workpath", str(REPO / "build" / "pyinstaller" / "work"),
            "--specpath", str(REPO / "build" / "pyinstaller"),
            "--collect-submodules", "uvicorn",
            "--collect-submodules", "fastapi",
            str(REPO / "packaging" / "windows" / "pary_server.py"),
        ],
        capture_output=True,
    )
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr.decode("utf-8", errors="replace")[-4000:])
        raise SystemExit("PyInstaller failed")
    return FROZEN


def compiler_source() -> Path:
    """Where to take etamil.exe and the standard library from.

    The release build first, then the packaged one the eTamil repository
    produces. A debug build is not shipped: it is several times slower, and the
    difference would be blamed on the language.
    """
    release = config.ETAMIL_ROOT / "etamil_compiler" / "target" / "release" / "etamil.exe"
    if release.exists():
        return release
    packaged = config.ETAMIL_ROOT / "dist" / "etamil-windows-x64" / "etamil.exe"
    if packaged.exists():
        return packaged
    raise SystemExit(
        "no etamil.exe — run `cargo build --release` in etamil_compiler/ first"
    )


def vsix(directory: Path, stem: str) -> Path:
    packages = sorted(directory.glob(f"{stem}-*.vsix"))
    if not packages:
        raise SystemExit(
            f"no {stem}-*.vsix in {directory} — run `npx @vscode/vsce package` there"
        )
    return packages[-1]


def build(out_root: Path, skip_freeze: bool) -> Path:
    frozen = freeze(skip_freeze)

    name = f"eTamil-IDE-{__version__}-{TARGET}"
    stage = out_root / name
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # --- the compiler and the standard library it needs to resolve imports ---
    say("compiler")
    compiler_dir = stage / "compiler"
    compiler_dir.mkdir()
    shutil.copy2(compiler_source(), compiler_dir / "etamil.exe")
    for folder in ("nUlakam", "examples"):
        shutil.copytree(
            config.ETAMIL_ROOT / folder,
            compiler_dir / folder,
            ignore=shutil.ignore_patterns("__pycache__", ".git"),
        )

    # --- the server, frozen, plus the data and client it serves --------------
    say("paRY server")
    pary_dir = stage / "pary"
    shutil.copytree(frozen, pary_dir)

    lexicon.export()  # refresh the snapshot from the compiler before shipping it
    for relative in RUNTIME_DATA:
        source = config.DATA_DIR / relative
        if not source.exists():
            raise SystemExit(
                f"{source} is missing — run paRY.corpus.collect, paRY.index.build first"
            )
        destination = pary_dir / "data" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copytree(REPO / "web", pary_dir / "web")

    # --- the editor's half ---------------------------------------------------
    say("extensions and profile")
    extensions = stage / "extensions"
    extensions.mkdir()
    shutil.copy2(vsix(config.ETAMIL_ROOT / "eTamil_Code", "etamil-support"), extensions)
    shutil.copy2(vsix(REPO / "vscode", "pary"), extensions)
    shutil.copytree(REPO / "desktop" / "profile", stage / "profile")

    shutil.copy2(REPO / "packaging" / "windows" / "Install.ps1", stage / "Install.ps1")
    (stage / "README.txt").write_text(readme(), encoding="utf-8")

    manifest = {
        "name": name,
        "version": __version__,
        "target": TARGET,
        "compiler": subprocess.run(
            [str(compiler_dir / "etamil.exe"), "-V"], capture_output=True
        ).stdout.decode("utf-8", errors="replace").strip(),
        "extensions": sorted(path.name for path in extensions.iterdir()),
        "index_chunks": chunk_count(pary_dir / "data" / "index" / "paRY.db"),
    }
    (stage / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    say("zipping")
    archive = out_root / f"{name}.zip"
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                bundle.write(path, Path(name) / path.relative_to(stage))

    return archive


def chunk_count(database: Path) -> int:
    import sqlite3

    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        return connection.execute("SELECT count(*) FROM chunks").fetchone()[0]


def readme() -> str:
    return f"""eTamil IDE {__version__} ({TARGET})

  The eTamil compiler, the paRY assistant, and the two editor extensions.

INSTALL

  Right-click Install.ps1 and choose "Run with PowerShell", or:

      powershell -ExecutionPolicy Bypass -File Install.ps1

  It installs for the current user only. No administrator rights are needed
  and nothing is written outside your own profile.

WHAT IT PUTS WHERE

  %LOCALAPPDATA%\\Programs\\eTamil    the compiler, the standard library, paRY
  PATH                              gains the compiler, so `etamil` works
  ETAMIL_PATH                       set, so `இறக்கு "nUlakam/..."` resolves
  your editor                       the two extensions, plus settings and keys

THE EDITOR IS NOT IN THIS PACKAGE

  VSCodium is a hundred megabytes maintained by other people; a copy frozen
  inside this zip would be a copy nobody updates. Install.ps1 finds VSCodium
  or VS Code if you have one, and can fetch VSCodium with winget if you pass
  -InstallEditor.

AFTER INSTALLING

  Start Menu -> "paRY server" starts the assistant, then open a .qmz file.
  Ctrl+Alt+I asks paRY to write code into the editor; F5 runs the file.

  paRY answers from the eTamil compiler and an index of the documentation.
  No hosted model is called, and nothing you type leaves the machine.
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Windows package.")
    parser.add_argument("--out", type=Path, default=REPO / "build" / "windows")
    parser.add_argument("--skip-freeze", action="store_true")
    args = parser.parse_args(argv)

    print(f"building eTamil IDE {__version__} for {TARGET}")
    archive = build(args.out, args.skip_freeze)
    size = archive.stat().st_size / (1024 * 1024)
    print(f"\n{archive}")
    print(f"{size:,.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
