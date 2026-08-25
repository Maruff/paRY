"""Download the third-party extensions the IDE is allowed to have.

From Open VSX, not Microsoft's gallery: the gallery's terms do not cover
non-Microsoft builds, and a bank that cannot reach the internet could not use
it regardless. Every version is pinned in `extensions.json` so two builds of
the same commit contain the same bytes.

    python desktop/branding/fetch_extensions.py            # the pinned versions
    python desktop/branding/fetch_extensions.py --latest   # and update the pins

The downloaded files are build output and are not committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "extensions.json"
REGISTRY = "https://open-vsx.org/api"


def metadata(identifier: str) -> dict:
    publisher, name = identifier.split(".", 1)
    with urllib.request.urlopen(f"{REGISTRY}/{publisher}/{name}", timeout=30) as response:
        return json.load(response)


def download(identifier: str, version: str, into: Path) -> Path:
    publisher, name = identifier.split(".", 1)
    target = into / f"{publisher}.{name}-{version}.vsix"
    if target.exists():
        return target

    url = f"{REGISTRY}/{publisher}/{name}/{version}/file/{publisher}.{name}-{version}.vsix"
    into.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=180) as response:
            payload = response.read()
    except urllib.error.HTTPError as failure:
        raise SystemExit(f"{identifier} {version}: {failure.code} from Open VSX") from failure

    # A .vsix is a zip. Anything else means a redirect page or an error body,
    # and installing it would fail later with a far less obvious message.
    if not payload.startswith(b"PK"):
        raise SystemExit(f"{identifier} {version}: what came back is not a .vsix")

    target.write_bytes(payload)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=HERE.parent.parent / "build" / "extensions")
    parser.add_argument("--latest", action="store_true", help="update the pinned versions first")
    args = parser.parse_args(argv)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = [
        entry
        for group in ("installed", "optional")
        for entry in manifest[group]
        if entry["source"] == "openvsx"
    ]

    if args.latest:
        for entry in entries:
            live = metadata(entry["id"])
            if live["version"] != entry["version"]:
                print(f"  {entry['id']}: {entry['version']} -> {live['version']}")
                entry["version"] = live["version"]
                entry["license"] = live.get("license") or entry.get("license", "?")
        MANIFEST.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"fetching {len(entries)} extensions into {args.out}")
    total = 0
    for entry in entries:
        path = download(entry["id"], entry["version"], args.out)
        size = path.stat().st_size
        total += size
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        print(f"  {entry['title']:<10} {entry['id']:<40} {size / 1024:>8,.0f} kB  {digest}")

    print(f"{total / (1024 * 1024):,.1f} MB total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
