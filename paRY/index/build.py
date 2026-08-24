"""Build the retrieval index paRY answers questions from.

SQLite FTS5, one file, no server and no dependency. Four kinds of chunk go in,
and the kind matters as much as the text:

    symbol        a keyword, builtin or nUlakam function, read out of the
                  compiler — every spelling of it, its parameters and its doc
    example       a whole .qmz file
    doc_block     an eTamil block from the documentation, carrying whether it
                  actually compiles
    doc_section   a run of prose under one heading, with the heading path

A symbol chunk is the highest-precision thing here: "what does நீளம் do" has an
exact answer that came from `interpreter.rs`, not a paragraph that mentions it.
A doc_block that fails to compile is still worth retrieving and must never be
offered as an answer, which is why the verdict is stored rather than filtered.

    python -m paRY.index.build
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from .. import config, lexicon
from ..corpus.collect import read_jsonl

# SQLite's default tokenizer decides what counts as part of a word by Unicode
# category, and it takes only letters and numbers. Tamil vowel signs and the
# pulli are combining marks — category Mn and Mc — so `செயல்` is indexed as
# `ச` + `யல`, and every Tamil word collides with every other one that happens
# to share a bare consonant. Naming Mn and Mc keeps a word whole.
#
# The same mistake, in a different library, cost the tokenizer every keyword it
# had. It is worth assuming any text tool is wrong about Tamil until shown.
TOKENIZE = "unicode61 categories 'L* N* Mn Mc'"

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
MAX_CHUNK_CHARS = 1_500

SCHEMA = f"""
CREATE TABLE chunks (
    id       INTEGER PRIMARY KEY,
    kind     TEXT NOT NULL,
    title    TEXT NOT NULL,
    repo     TEXT,
    path     TEXT,
    line     INTEGER,
    compiles INTEGER,
    body     TEXT NOT NULL,
    extra    TEXT
);
CREATE INDEX chunks_kind ON chunks(kind);

CREATE VIRTUAL TABLE chunks_fts USING fts5(
    names, title, body,
    tokenize="{TOKENIZE}"
);
"""


def _section_chunks(text: str) -> list[dict]:
    """Markdown split at headings, with the heading path kept as the title.

    A section longer than `MAX_CHUNK_CHARS` is split again at blank lines. The
    title travels with every piece, because "Response headers" is most of what
    makes a paragraph findable and the third paragraph under it does not repeat
    the words.
    """
    sections: list[dict] = []
    path: list[str] = []
    title = ""
    body: list[str] = []
    line_no = 1

    def flush(start: int) -> None:
        joined = "\n".join(body).strip()
        if joined:
            sections.append({"title": title, "line": start, "text": joined})

    start_line = 1
    for index, line in enumerate(text.split("\n"), start=1):
        heading = HEADING.match(line)
        if not heading:
            body.append(line)
            continue
        flush(start_line)
        depth = len(heading.group(1))
        path = path[: depth - 1] + [heading.group(2)]
        title = " › ".join(path)
        body = []
        start_line = index
        line_no = index
    flush(start_line)

    out: list[dict] = []
    for section in sections:
        if len(section["text"]) <= MAX_CHUNK_CHARS:
            out.append(section)
            continue
        piece: list[str] = []
        size = 0
        for paragraph in section["text"].split("\n\n"):
            if size + len(paragraph) > MAX_CHUNK_CHARS and piece:
                out.append({**section, "text": "\n\n".join(piece)})
                piece, size = [], 0
            piece.append(paragraph)
            size += len(paragraph) + 2
        if piece:
            out.append({**section, "text": "\n\n".join(piece)})
    return out


def _symbol_chunks() -> list[dict]:
    """Every name the compiler accepts, as its own answerable unit."""
    names = lexicon.load()
    chunks: list[dict] = []

    for entry in names.keywords:
        forms = entry["forms"]
        chunks.append(
            {
                "kind": "symbol",
                "title": f"{forms[0]} — keyword",
                "names": " ".join(forms),
                "body": (
                    f"{forms[0]} is an eTamil keyword in the {entry['section']} group. "
                    f"Spellings: {', '.join(forms)}."
                ),
                "extra": {"token": entry["token"], "section": entry["section"], "forms": forms},
            }
        )

    for entry in names.builtins:
        chunks.append(
            {
                "kind": "symbol",
                "title": f"{entry['name']} — builtin",
                "names": " ".join(entry["forms"]),
                "body": (
                    f"{entry['doc']}\nTakes {entry['arity']} argument(s). "
                    f"Spellings: {', '.join(entry['forms'])}."
                ),
                "extra": {"arity": entry["arity"], "forms": entry["forms"]},
            }
        )

    for entry in names.stdlib:
        params = ", ".join(entry["params"])
        chunks.append(
            {
                "kind": "symbol",
                "title": f"{entry['name']}({params}) — nUlakam",
                "names": " ".join(entry["forms"]),
                "path": entry["module"],
                "line": entry["line"],
                "body": (
                    f"{entry['doc']}\nDefined in {entry['module']}. "
                    f"Call it as {entry['name']}({params}). "
                    f'Import with இறக்கு "{entry["module"]}";'
                ),
                "extra": {"module": entry["module"], "params": entry["params"]},
            }
        )
    return chunks


def _corpus_chunks(corpus_dir: Path, verdicts: dict[str, bool]) -> list[dict]:
    documents = read_jsonl(corpus_dir / "documents.jsonl")
    blocks = read_jsonl(corpus_dir / "blocks.jsonl")
    chunks: list[dict] = []

    for record in documents:
        if record["kind"] in {"stdlib", "example", "bench"}:
            chunks.append(
                {
                    "kind": "example",
                    "title": record["path"],
                    "names": Path(record["path"]).stem,
                    "repo": record["repo"],
                    "path": record["path"],
                    "line": 1,
                    "compiles": True,
                    "body": record["text"],
                    "extra": {"lines": record["lines"], "source_kind": record["kind"]},
                }
            )
            continue

        for section in _section_chunks(record["text"]):
            chunks.append(
                {
                    "kind": "doc_section",
                    "title": section["title"] or record["path"],
                    "names": "",
                    "repo": record["repo"],
                    "path": record["path"],
                    "line": section["line"],
                    "body": section["text"],
                    "extra": {"doc_kind": record["kind"]},
                }
            )

    for block in blocks:
        if not block["is_etamil"]:
            continue
        chunks.append(
            {
                "kind": "doc_block",
                "title": f"{block['path']}:{block['line']}",
                "names": "",
                "repo": block["repo"],
                "path": block["path"],
                "line": block["line"],
                "compiles": verdicts.get(block["id"]),
                "body": block["text"],
                "extra": {"id": block["id"]},
            }
        )
    return chunks


def _verdicts(report_path: Path) -> dict[str, bool]:
    """Which documented blocks compile, if the oracle has been run.

    Absent, every block is indexed with an unknown verdict rather than a
    hopeful one — an example that does not compile must never be handed to
    someone as an answer.
    """
    if not report_path.exists():
        return {}
    report = json.loads(report_path.read_text(encoding="utf-8"))
    return {entry["id"]: entry["ok"] for entry in report["blocks"]}


def build(corpus_dir: Path, out_path: Path, report_path: Path) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()

    connection = sqlite3.connect(out_path)
    connection.executescript(SCHEMA)

    chunks = _symbol_chunks() + _corpus_chunks(corpus_dir, _verdicts(report_path))

    for chunk in chunks:
        body = unicodedata.normalize("NFC", chunk["body"])
        cursor = connection.execute(
            "INSERT INTO chunks (kind, title, repo, path, line, compiles, body, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk["kind"],
                chunk["title"],
                chunk.get("repo"),
                chunk.get("path"),
                chunk.get("line"),
                None if chunk.get("compiles") is None else int(chunk["compiles"]),
                body,
                json.dumps(chunk.get("extra", {}), ensure_ascii=False),
            ),
        )
        connection.execute(
            "INSERT INTO chunks_fts (rowid, names, title, body) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, chunk.get("names", ""), chunk["title"], body),
        )

    connection.commit()
    counts = dict(connection.execute("SELECT kind, count(*) FROM chunks GROUP BY kind").fetchall())
    terms = connection.execute("SELECT count(*) FROM chunks_fts").fetchone()[0]
    connection.close()

    summary = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "index": str(out_path),
        "chunks": len(chunks),
        "by_kind": counts,
        "indexed_rows": terms,
        "tokenizer": TOKENIZE,
    }
    out_path.with_suffix(".json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the paRY retrieval index.")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "index" / "paRY.db")
    parser.add_argument(
        "--verdicts", type=Path, default=config.REPORT_DIR / "documented_blocks.json"
    )
    args = parser.parse_args(argv)

    summary = build(args.corpus, args.out, args.verdicts)
    print(f"indexed {summary['chunks']} chunks into {args.out}")
    for kind, count in sorted(summary["by_kind"].items()):
        print(f"    {kind:<13} {count:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
