"""Turn VSCodium into an eTamil IDE.

Builds both extensions, installs them, and adds the settings and keybindings
that make the editor an eTamil environment rather than a text editor that
happens to open `.qmz`.

    python desktop/provision.py --dry-run     # say what would happen
    python desktop/provision.py               # do it
    python desktop/provision.py --editor code # into VS Code instead

Nothing here overwrites a setting that already has a value. Existing settings
are backed up first and then only *missing* keys are added, so running this
against an editor someone already uses cannot take their configuration away.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "desktop" / "profile"

# VSCodium first: it is the same editor without the telemetry or the marketplace
# terms, which is what makes it installable inside an institution that has to
# account for everything leaving its network.
EDITORS = ("codium", "code", "code-insiders")

# Where each editor keeps the settings a user edits.
USER_DIRS = {
    "codium": {"win32": "VSCodium", "posix": "VSCodium"},
    "code": {"win32": "Code", "posix": "Code"},
    "code-insiders": {"win32": "Code - Insiders", "posix": "Code - Insiders"},
}

EXTENSIONS = (
    # (directory, vsix stem) — the language extension lives in the eTamil repo.
    (REPO.parent / "eTamil" / "eTamil_Code", "etamil-support"),
    (REPO / "vscode", "pary"),
)


def find_editor(preferred: str | None) -> str:
    if preferred:
        if shutil.which(preferred) is None:
            raise SystemExit(f"{preferred} is not on PATH")
        return preferred
    for candidate in EDITORS:
        if shutil.which(candidate):
            return candidate
    raise SystemExit(
        "No editor found. Install VSCodium (https://vscodium.com) and make sure "
        "`codium` is on PATH, or pass --editor."
    )


def user_dir(editor: str) -> Path:
    name = USER_DIRS[editor]["win32" if sys.platform == "win32" else "posix"]
    if sys.platform == "win32":
        base = Path(os.environ["APPDATA"])
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / name / "User"


def run(command: list[str], cwd: Path, dry_run: bool) -> None:
    printable = " ".join(command)
    if dry_run:
        print(f"    would run: {printable}   (in {cwd})")
        return
    print(f"    {printable}")
    completed = subprocess.run(command, cwd=cwd, shell=sys.platform == "win32")
    if completed.returncode != 0:
        raise SystemExit(f"failed: {printable}")


def build(directory: Path, stem: str, dry_run: bool) -> Path:
    """npm install, compile, and package one extension."""
    if not directory.is_dir():
        raise SystemExit(f"{directory} is missing — is the eTamil repository beside this one?")
    print(f"  building {stem}")
    run(["npm", "install", "--no-fund", "--no-audit"], directory, dry_run)
    run(["npm", "run", "compile"], directory, dry_run)
    run(
        ["npx", "--yes", "@vscode/vsce", "package", "--allow-missing-repository", "--skip-license"],
        directory,
        dry_run,
    )
    packages = sorted(directory.glob(f"{stem}-*.vsix"))
    if not packages and dry_run:
        return directory / f"{stem}-<version>.vsix"
    if not packages:
        raise SystemExit(f"no {stem}-*.vsix appeared in {directory}")
    return packages[-1]


def merge_json(target: Path, additions: dict, dry_run: bool) -> list[str]:
    """Add the keys that are missing, and never touch the ones that are not.

    Returns the keys it added. A settings file someone has edited by hand is
    their file; this is a guest in it.
    """
    existing: dict = {}
    if target.exists():
        text = target.read_text(encoding="utf-8").strip()
        if text:
            try:
                existing = json.loads(text)
            except json.JSONDecodeError:
                # VS Code allows comments in settings.json. Rather than write a
                # JSONC parser, refuse and let the person merge by hand.
                raise SystemExit(
                    f"{target} is not plain JSON (comments?). Merge {PROFILE.name} by hand."
                )

    added = [key for key in additions if key not in existing]
    if not added:
        return []

    if dry_run:
        return added

    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = target.with_suffix(f".json.backup-{stamp}")
        shutil.copy2(target, backup)
        print(f"    backed up {target.name} -> {backup.name}")

    merged = {**existing, **{key: additions[key] for key in added}}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return added


def merge_keybindings(target: Path, additions: list[dict], dry_run: bool) -> list[str]:
    existing: list[dict] = []
    if target.exists():
        text = target.read_text(encoding="utf-8").strip()
        if text:
            try:
                existing = json.loads(text)
            except json.JSONDecodeError:
                raise SystemExit(f"{target} is not plain JSON. Merge by hand.")

    taken = {(item.get("key"), item.get("command")) for item in existing}
    fresh = [item for item in additions if (item["key"], item["command"]) not in taken]
    if not fresh or dry_run:
        return [f"{item['key']} → {item['command']}" for item in fresh]

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(existing + fresh, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return [f"{item['key']} → {item['command']}" for item in fresh]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--editor", choices=EDITORS, help="which editor to provision")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen")
    parser.add_argument("--skip-build", action="store_true", help="install the .vsix already built")
    parser.add_argument("--no-settings", action="store_true", help="install extensions only")
    args = parser.parse_args(argv)

    editor = find_editor(args.editor)
    print(f"editor: {editor}")
    print(f"profile: {user_dir(editor)}")

    for directory, stem in EXTENSIONS:
        if args.skip_build:
            packages = sorted(directory.glob(f"{stem}-*.vsix"))
            if not packages:
                raise SystemExit(f"--skip-build, but no {stem}-*.vsix in {directory}")
            package = packages[-1]
        else:
            package = build(directory, stem, args.dry_run)
        print(f"  installing {package.name}")
        run([editor, "--install-extension", str(package)], REPO, args.dry_run)

    if args.no_settings:
        print("settings left alone (--no-settings)")
        return 0

    settings = json.loads((PROFILE / "settings.json").read_text(encoding="utf-8"))
    if editor == "codium":
        # Turning telemetry off and pinning updates is right for an IDE handed
        # to a team; it is not something to do to someone's daily VS Code
        # behind their back, so it only applies to the dedicated install.
        settings |= json.loads((PROFILE / "settings.codium.json").read_text(encoding="utf-8"))
    keybindings = json.loads((PROFILE / "keybindings.json").read_text(encoding="utf-8"))

    added = merge_json(user_dir(editor) / "settings.json", settings, args.dry_run)
    bound = merge_keybindings(user_dir(editor) / "keybindings.json", keybindings, args.dry_run)

    verb = "would add" if args.dry_run else "added"
    print(f"settings {verb}: {len(added)}")
    for key in added:
        print(f"    {key} = {json.dumps(settings[key], ensure_ascii=False)}")
    print(f"keybindings {verb}: {len(bound)}")
    for binding in bound:
        print(f"    {binding}")
    if not added and not bound:
        print("    (everything was already set — nothing overwritten)")

    print()
    print("Start the assistant with:  python -m paRY.serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
