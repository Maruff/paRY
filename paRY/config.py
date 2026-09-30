"""Where everything paRY reads and writes lives.

The two source repositories are siblings of this one. Every path can be
overridden by an environment variable so a training box can lay them out
differently:

    ETAMIL_ROOT        the compiler repository        (default ../eTamil)
    ETAMIL_SITE_ROOT   the site and IDE repository    (default ../eTamil.in)
    ETAMIL_BIN         the compiler binary            (default: the release
                       build inside ETAMIL_ROOT, then the packaged one)
    PARY_DATA          generated corpora and models   (default ./data)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


ETAMIL_ROOT = _env_path("ETAMIL_ROOT", (REPO_ROOT.parent / "eTamil").resolve())
ETAMIL_SITE_ROOT = _env_path("ETAMIL_SITE_ROOT", (REPO_ROOT.parent / "eTamil.in").resolve())
DATA_DIR = _env_path("PARY_DATA", REPO_ROOT / "data")

CORPUS_DIR = DATA_DIR / "corpus"
TOKENIZER_DIR = DATA_DIR / "tokenizer"
REPORT_DIR = DATA_DIR / "reports"

REPOS: dict[str, Path] = {
    "eTamil": ETAMIL_ROOT,
    "eTamil_site": ETAMIL_SITE_ROOT,
}


def etamil_bin() -> Path | None:
    """The compiler binary, or None if it has not been built.

    Every generated sample is checked by running this, so a missing binary is a
    reason to stop rather than to guess.
    """
    override = os.environ.get("ETAMIL_BIN")
    if override:
        path = Path(override).expanduser()
        return path if path.exists() else None

    exe = ".exe" if sys.platform == "win32" else ""
    candidates = [
        ETAMIL_ROOT / "etamil_compiler" / "target" / "release" / f"etamil{exe}",
        ETAMIL_ROOT / "etamil_compiler" / "target" / "debug" / f"etamil{exe}",
        ETAMIL_ROOT / "dist" / "etamil-windows-x64" / f"etamil{exe}",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def require(path: Path, what: str) -> Path:
    if not path.exists():
        raise SystemExit(f"{what} not found at {path} — set the matching environment variable")
    return path
