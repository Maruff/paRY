"""Embed the index, so a question can be matched by meaning and not only by words.

    python -m paRY.index.embed            # embed what is not embedded yet
    python -m paRY.index.embed --all      # re-embed everything

bm25 answers "which chunk shares the most rare words with this question", which
is the right question when the words match and useless when they do not. "How
do I connect to postgres" shares no rare word with `qaLam_iNY`, so the search
returns whatever prose happened to use the words "how", "do" and "to" most
densely. Measured before this existed: all eight top hits for that question were
recipes, while forty-seven chunks that mention postgres never surfaced.

The model is `all-minilm` on a local Ollama — 45 MB, 384 dimensions, and about
36 seconds for the whole index on two vCPU. Nothing is sent anywhere: the same
constraint that rules out a hosted model rules out a hosted embedder.

Vectors live beside the chunks in the same SQLite file, so an index is one file
to copy and can never be half a version out of step with its embeddings. They
are stored normalised, which makes cosine similarity a plain dot product at
query time and saves recomputing a norm per chunk per question.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path

from .. import config

EMBED_URL = os.environ.get("PARY_EMBED_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("PARY_EMBED_MODEL", "all-minilm")

#: Ollama takes a list; this is how many at once. Large enough that the request
#: overhead disappears, small enough that one failure does not cost minutes.
BATCH = 64

#: The body is truncated before embedding. all-minilm has a 256-token window
#: and silently drops the rest, so sending a whole document section wastes the
#: request and buries the part that identifies it. The title carries most of
#: the signal anyway, which is why it is prepended rather than embedded alone.
BODY_LIMIT = 900


def schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS chunk_vectors ("
        "  chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,"
        "  dims INTEGER NOT NULL,"
        "  vector BLOB NOT NULL"
        ")"
    )
    connection.commit()


def embed_texts(texts: list[str]) -> list[list[float]]:
    """One Ollama call. Raises rather than returning something half-embedded."""
    payload = json.dumps({"model": EMBED_MODEL, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{EMBED_URL}/api/embed",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        body = json.load(response)
    vectors = body.get("embeddings")
    if not vectors or len(vectors) != len(texts):
        raise RuntimeError(
            f"{EMBED_MODEL} returned {len(vectors or [])} vectors for {len(texts)} texts"
        )
    return vectors


def normalise(vector: list[float]) -> bytes:
    """Store unit vectors, so similarity is a dot product and nothing else."""
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0.0:
        length = 1.0
    return struct.pack(f"<{len(vector)}f", *(value / length for value in vector))


def text_for(title: str, body: str) -> str:
    return f"{title}\n\n{body[:BODY_LIMIT]}"


def run(connection: sqlite3.Connection, *, everything: bool = False) -> int:
    schema(connection)
    if everything:
        connection.execute("DELETE FROM chunk_vectors")
        connection.commit()

    rows = connection.execute(
        "SELECT c.id, c.title, c.body FROM chunks c "
        "LEFT JOIN chunk_vectors v ON v.chunk_id = c.id "
        "WHERE v.chunk_id IS NULL"
    ).fetchall()
    if not rows:
        print("  every chunk already has a vector")
        return 0

    print(f"  embedding {len(rows)} chunks with {EMBED_MODEL}", flush=True)
    done = 0
    for start in range(0, len(rows), BATCH):
        batch = rows[start : start + BATCH]
        vectors = embed_texts([text_for(row[1] or "", row[2] or "") for row in batch])
        connection.executemany(
            "INSERT OR REPLACE INTO chunk_vectors (chunk_id, dims, vector) VALUES (?,?,?)",
            [
                (row[0], len(vector), normalise(vector))
                for row, vector in zip(batch, vectors)
            ],
        )
        connection.commit()
        done += len(batch)
        print(f"    {done}/{len(rows)}", flush=True)
    return done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Embed the paRY index.")
    parser.add_argument("--all", action="store_true", help="re-embed every chunk")
    parser.add_argument("--index", type=Path, help="path to paRY.db")
    args = parser.parse_args(argv)

    path = args.index or config.DATA_DIR / "index" / "paRY.db"
    if not path.exists():
        print(f"no index at {path} — run `python -m paRY.index.build` first", file=sys.stderr)
        return 1

    connection = sqlite3.connect(path)
    try:
        run(connection, everything=args.all)
    except (urllib.error.URLError, RuntimeError) as failure:
        # Worth naming: the usual cause is a stopped Ollama, and "connection
        # refused" on its own sends people to look at paRY.
        print(
            f"embedding failed: {failure}\n"
            f"  {EMBED_MODEL} is served by Ollama at {EMBED_URL}. "
            f"Check `systemctl is-active ollama` and `ollama list`.",
            file=sys.stderr,
        )
        return 1
    finally:
        connection.close()

    total = sqlite3.connect(path).execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]
    print(f"  {total} chunks embedded in {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
