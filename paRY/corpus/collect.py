"""Gather every eTamil source file and document into one addressable corpus.

Two outputs land in `data/corpus/`:

    documents.jsonl   one record per file, with provenance and a content hash
    blocks.jsonl      one record per fenced code block found inside a document

Blocks are separated from the documents that contain them because they are
different material. A `.qmz` file in `nUlakam/` compiles; a fenced block in a
tutorial is usually a fragment, and whether it compiles is a question worth
asking of each one (`paRY.verify.oracle`) rather than assuming either way.

Nothing is filtered on quality here. Vendored directories are skipped —
`node_modules`, Cargo's `target`, the packaged copy under `dist/` that
duplicates `nUlakam/` byte for byte — and everything else is kept with its
`kind` recorded, so a downstream consumer that does not want, say, archived
documentation can drop it by tag instead of re-walking the tree.

    python -m paRY.corpus.collect
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .. import config

# Directories that are never corpus: dependencies, build output, editor state,
# and the release bundle, which is a copy of nUlakam/ and examples/.
EXCLUDED_DIRS = {
    ".git",
    ".claude",
    ".vs",
    ".venv",
    "node_modules",
    "target",
    "dist",
    "_site_preview",
    "_site",
    "__pycache__",
    # nUlakam/*/uqavi holds a worked example per library function -- 900-odd
    # short programs, excellent documentation for a person and poor material
    # for a machine. Measured twice and left out on both counts:
    #
    #   indexed as chunks, they outnumbered the symbols they explain and a
    #   question matched the example instead of the function. Diagnostic MRR
    #   0.510 -> 0.352.
    #
    #   trained on, their repetition bought merges that do not generalise and
    #   the documentation paid for it. chars/token 3.54 -> 3.43 on prose.
    #
    # Left out here rather than filtered downstream, so the corpus manifest
    # says what was actually collected.
    "uqavi",
}

FENCE = re.compile(r"^(?P<indent>[ \t]*)```(?P<lang>[A-Za-z0-9_+-]*)\s*$")
TAMIL = re.compile(r"[஀-௿]")

# Fence tags that mean "this is eTamil", spelled as the docs actually spell them.
ETAMIL_FENCES = {"etamil", "qmz", "tamil"}


@dataclass(frozen=True)
class Source:
    """One place to read from, and what to call what is found there."""

    repo: str
    subdir: str
    patterns: tuple[str, ...]
    kind: str
    recursive: bool = True


SOURCES: tuple[Source, ...] = (
    # Code. The standard library is written in eTamil and is the densest,
    # most idiomatic material the project has.
    Source("eTamil", "nUlakam", ("*.qmz",), "stdlib"),
    Source("eTamil", "examples", ("*.qmz",), "example"),
    Source("eTamil", "scripts/bench", ("*.qmz",), "bench"),
    # Documentation.
    Source("eTamil", "docs", ("*.md",), "doc"),
    Source("eTamil", ".", ("*.md",), "doc", recursive=False),
    Source("eTamil_site", "docs", ("*.md", "*.mdx"), "doc"),
    Source("eTamil_site", ".", ("*.md",), "doc", recursive=False),
    Source("eTamil_site", "ta", ("*.md",), "doc_ta"),
)

# Paths whose kind is narrowed after the fact, by prefix of the repo-relative path.
RETAGGED: tuple[tuple[str, str, str], ...] = (
    ("eTamil", "docs/archive/", "doc_archive"),
    ("eTamil_site", "redirects/", "doc_redirect"),
)


def _excluded(path: Path, root: Path) -> bool:
    return any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts)


def _walk(source: Source) -> Iterator[Path]:
    root = config.REPOS[source.repo]
    base = root / source.subdir if source.subdir != "." else root
    if not base.exists():
        return
    for pattern in source.patterns:
        globber = base.rglob if source.recursive else base.glob
        for path in globber(pattern):
            if path.is_file() and not _excluded(path, root):
                yield path


def _kind_for(repo: str, relative: str, default: str) -> str:
    for tagged_repo, prefix, kind in RETAGGED:
        if repo == tagged_repo and relative.startswith(prefix):
            return kind
    return default


def _read(path: Path) -> str | None:
    """Text with newlines and any BOM normalised, or None if it is not text."""
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _measure(text: str) -> dict:
    return {
        "bytes": len(text.encode("utf-8")),
        "chars": len(text),
        "lines": text.count("\n") + (1 if text and not text.endswith("\n") else 0),
        "tamil_chars": len(TAMIL.findall(text)),
    }


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_blocks(text: str) -> list[dict]:
    """Fenced code blocks, with the line they start on and their fence tag.

    A nested fence inside a block ends the block early — the same reading every
    Markdown renderer gives a same-length fence, and so the reading the
    documents were written against.
    """
    blocks: list[dict] = []
    lines = text.split("\n")
    index = 0
    while index < len(lines):
        opening = FENCE.match(lines[index])
        if not opening:
            index += 1
            continue
        indent = opening.group("indent")
        lang = (opening.group("lang") or "").lower()
        body: list[str] = []
        cursor = index + 1
        closed = False
        while cursor < len(lines):
            candidate = lines[cursor]
            if candidate.strip().startswith("```"):
                closed = True
                break
            body.append(candidate[len(indent):] if candidate.startswith(indent) else candidate)
            cursor += 1
        if closed and body:
            blocks.append({"lang": lang, "line": index + 1, "text": "\n".join(body) + "\n"})
        index = cursor + 1
    return blocks


def collect(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    seen: dict[str, str] = {}
    duplicates: list[dict] = []
    documents: list[dict] = []
    blocks: list[dict] = []

    for source in SOURCES:
        root = config.REPOS[source.repo]
        for path in sorted(_walk(source)):
            text = _read(path)
            if text is None or not text.strip():
                continue
            relative = path.relative_to(root).as_posix()
            digest = _digest(text)
            if digest in seen:
                duplicates.append({"path": relative, "repo": source.repo, "same_as": seen[digest]})
                continue
            seen[digest] = f"{source.repo}/{relative}"

            kind = _kind_for(source.repo, relative, source.kind)
            record = {
                "id": f"{source.repo}/{relative}",
                "repo": source.repo,
                "path": relative,
                "kind": kind,
                "ext": path.suffix.lstrip("."),
                "sha256": digest,
                **_measure(text),
                "text": unicodedata.normalize("NFC", text),
            }
            documents.append(record)

            if kind.startswith("doc"):
                for ordinal, block in enumerate(extract_blocks(text)):
                    body = unicodedata.normalize("NFC", block["text"])
                    blocks.append(
                        {
                            "id": f"{record['id']}#{ordinal}",
                            "repo": source.repo,
                            "path": relative,
                            "doc_kind": kind,
                            "line": block["line"],
                            "lang": block["lang"],
                            "is_etamil": block["lang"] in ETAMIL_FENCES,
                            "sha256": _digest(body),
                            **_measure(body),
                            "text": body,
                        }
                    )

    _write_jsonl(out_dir / "documents.jsonl", documents)
    _write_jsonl(out_dir / "blocks.jsonl", blocks)

    manifest = summarise(documents, blocks, duplicates)
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def _write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _totals(records: list[dict]) -> dict:
    return {
        "files": len(records),
        "bytes": sum(record["bytes"] for record in records),
        "lines": sum(record["lines"] for record in records),
        "chars": sum(record["chars"] for record in records),
        "tamil_chars": sum(record["tamil_chars"] for record in records),
    }


def summarise(documents: list[dict], blocks: list[dict], duplicates: list[dict]) -> dict:
    by_kind: dict[str, list[dict]] = {}
    for record in documents:
        by_kind.setdefault(record["kind"], []).append(record)

    fence_languages: dict[str, int] = {}
    for block in blocks:
        tag = block["lang"] or "(none)"
        fence_languages[tag] = fence_languages.get(tag, 0) + 1

    etamil_blocks = [block for block in blocks if block["is_etamil"]]
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "roots": {name: str(path) for name, path in config.REPOS.items()},
        "documents": _totals(documents),
        "by_kind": {kind: _totals(records) for kind, records in sorted(by_kind.items())},
        "blocks": {
            "total": len(blocks),
            "etamil": _totals(etamil_blocks),
            "by_language": dict(sorted(fence_languages.items(), key=lambda item: -item[1])),
        },
        "duplicates_skipped": duplicates,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect the eTamil corpus.")
    parser.add_argument("--out", type=Path, default=config.CORPUS_DIR)
    args = parser.parse_args(argv)

    manifest = collect(args.out)
    documents = manifest["documents"]
    print(f"corpus written to {args.out}")
    print(
        f"  {documents['files']} files, {documents['lines']:,} lines, "
        f"{documents['bytes'] / 1024:,.0f} kB, {documents['tamil_chars']:,} Tamil characters"
    )
    for kind, totals in manifest["by_kind"].items():
        print(f"    {kind:<13} {totals['files']:>4} files  {totals['bytes'] / 1024:>8,.0f} kB")
    blocks = manifest["blocks"]
    print(f"  {blocks['total']} fenced blocks, {blocks['etamil']['files']} tagged eTamil")
    if manifest["duplicates_skipped"]:
        print(f"  {len(manifest['duplicates_skipped'])} duplicate files skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
