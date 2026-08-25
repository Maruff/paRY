"""The entry point for the packaged paRY server.

Frozen into `pary-server.exe`, this is what the Start Menu shortcut runs. It
differs from `python -m paRY.serve` in one way that matters: an installed copy
has no eTamil repository next door, so the compiler, the standard library and
the data all have to be found relative to the installation instead.

Layout it expects, which is what `build.py` produces:

    eTamil/                      <- installation root
      compiler/etamil.exe
      compiler/nUlakam/
      pary/pary-server.exe       <- this
      pary/data/index/paRY.db
      pary/data/lexicon.json
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def installation_root() -> Path:
    """The install directory, whether frozen or run from source."""
    if getattr(sys, "frozen", False):
        # pary/pary-server.exe -> pary -> the root
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent.parent


def main() -> int:
    root = installation_root()
    compiler = root / "compiler" / ("etamil.exe" if sys.platform == "win32" else "etamil")

    # Set before paRY is imported: config reads these at module level.
    os.environ.setdefault("ETAMIL_BIN", str(compiler))
    os.environ.setdefault("ETAMIL_ROOT", str(root / "compiler"))
    os.environ.setdefault("PARY_DATA", str(root / "pary" / "data"))
    os.environ.setdefault("PARY_WEB", str(root / "pary" / "web"))

    import uvicorn

    from paRY.serve.app import create_app

    host = os.environ.get("PARY_HOST", "127.0.0.1")
    port = int(os.environ.get("PARY_PORT", "8900"))

    # Report the compiler actually in use, which is the environment variable —
    # setdefault means an explicit ETAMIL_BIN wins over the bundled path.
    in_use = Path(os.environ["ETAMIL_BIN"])
    if not in_use.exists():
        print(f"warning: no compiler at {in_use} - /diagnose will answer 503", file=sys.stderr)

    print(f"paRY on http://{host}:{port}  (compiler: {in_use})")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
