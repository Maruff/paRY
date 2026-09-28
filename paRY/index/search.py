"""Ask the index a question in Tamil or English.

Three passes, narrowest first, because a question is usually more specific than
its best match and only sometimes less:

    all terms      → the answer is a document about exactly this
    any term       → the question used a word the corpus spells differently
    prefix         → the developer stopped typing halfway

Ranking is BM25 with the name column weighted far above the body, so asking
about `நீளம்` finds the builtin itself before a tutorial that happens to use
it. A question is never passed to FTS5 as written: every word is extracted and
quoted, so `இறக்கு "nUlakam/paNam.qmz"; -- why?` is a query and not a syntax
error.

    python -m paRY.index.search "how do I read a file"
"""

from __future__ import annotations

import argparse
import struct
import math
import sqlite3
import unicodedata
from functools import lru_cache
from dataclasses import dataclass, replace
from pathlib import Path

from .. import config

# Weights per FTS5 column: names, title, body. A name is what a question is
# usually about; prose that mentions it is the fallback.
WEIGHTS = (12.0, 3.0, 1.0)

#: Words too common to carry meaning. The same list as
#: nUlakam/nuNNaRivu/coRpiri.qmz, and the two are meant to agree: the
#: tokenizers disagreeing made a different pass of the query cascade fire on
#: each side for the same question, which looked like a ranking difference and
#: was not one.
#:
#: Deliberately short, and deliberately not question words. "how do I" is noise
#: in a document but is most of what distinguishes one question from another.
#: Over paRY.eval.lookup this list moved recall@3 from 11 to 12, recall@10 from
#: 14 to 15 and MRR from 0.489 to 0.510; adding question words on top was a
#: wash, one better at rank 1 and one worse at rank 10.
STOP_WORDS = frozenset({
    "a", "an", "the", "of", "to", "in", "on", "at", "for",
    "is", "are", "was", "were", "be", "and", "or",
    "this", "that", "it", "its", "as", "by", "with",
})

# Kinds that may be quoted back as working eTamil, best first.
# A recipe first: it was written to answer a question, and it compiles.
CODE_KINDS = ("recipe", "example", "doc_block")


@dataclass(frozen=True)
class Hit:
    kind: str
    title: str
    path: str | None
    line: int | None
    compiles: bool | None
    score: float
    snippet: str
    body: str
    #: The bm25 score on its own, 0.0 for a hit only the embeddings found.
    #: `score` may be a fused rank once semantic search is in play, and callers
    #: that calibrated a threshold against bm25 need the number they calibrated
    #: against, not a rank that happens to share its name.
    lexical: float = 0.0

    @property
    def code(self) -> str:
        """The part of this hit that is actually a program.

        A recipe's body is its explanation, a blank line, then the code — the
        explanation is indexed because that is what a question matches on, and
        it is prose, so it has to come off before the rest is quoted as eTamil.
        """
        if self.kind == "recipe":
            _, _, body = self.body.partition("\n\n")
            return body.strip() + "\n"
        return self.body

    @property
    def is_usable_code(self) -> bool:
        """Code that has been through the compiler and passed.

        `None` means the oracle has not been run over it, which is not the same
        as passing and is not treated as passing.
        """
        return self.kind in CODE_KINDS and self.compiles is True


def terms(question: str) -> list[str]:
    """The words in a question, with Tamil combining marks kept attached."""
    words: list[str] = []
    current: list[str] = []
    for char in unicodedata.normalize("NFC", question):
        if char.isalnum() or char == "_" or unicodedata.category(char) in {"Mn", "Mc"}:
            current.append(char)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    # Single ASCII letters carry nothing; a single Tamil letter can be a word.
    kept = [word for word in words if len(word) > 1 or not word.isascii()]
    return [word for word in kept if word.lower() not in STOP_WORDS]


def _quoted(word: str) -> str:
    """One FTS5 string literal. Doubling the quote is the whole escape."""
    return '"' + word.replace('"', '""') + '"'


@lru_cache(maxsize=1)
def _spellings() -> dict[str, tuple[str, ...]]:
    """Every accepted spelling to all the others it means.

    eTamil takes three spellings of each name — Tamil script, romanized, and an
    English alias — and a question can be asked in any of them. `accu`, `_print`
    and `அச்சு` are the same word, so a question that uses one has to find a
    document that uses another. The compiler's own tables say which are which,
    so this needs no transliteration and cannot disagree with the language.
    """
    from .. import lexicon

    names = lexicon.load()
    table: dict[str, tuple[str, ...]] = {}
    groups = [entry["forms"] for entry in names.keywords]
    groups += [entry["forms"] for entry in names.builtins]
    groups += [entry["forms"] for entry in names.stdlib]
    for forms in groups:
        for form in forms:
            table.setdefault(form, tuple(forms))
    return table


def expand(words: list[str]) -> list[str]:
    """The words asked for, plus the other spellings of any that are names."""
    table = _spellings()
    out: list[str] = []
    for word in words:
        out.append(word)
        for sibling in table.get(word, ()):
            if sibling != word and sibling not in out:
                out.append(sibling)
    return out


def queries(question: str) -> list[str]:
    """The passes to try, narrowest first. Empty if there is nothing to search."""
    words = terms(question)
    if not words:
        return []

    # AND over what was asked; OR over every spelling of it, so a romanized
    # question reaches Tamil-script documents and the other way round.
    quoted = [_quoted(word) for word in words]
    widened = [_quoted(word) for word in expand(words)]
    passes = []
    if len(quoted) > 1:
        passes.append(" AND ".join(quoted))
    passes.append(" OR ".join(widened))
    # Last resort: the longest word as a prefix, for someone who stopped typing
    # halfway. FTS5 spells this `"word" *` — the star sits outside the quotes.
    passes.append(f"{_quoted(max(words, key=len))} *")
    return passes


def connect(index_path: Path | None = None) -> sqlite3.Connection:
    path = index_path or config.DATA_DIR / "index" / "paRY.db"
    if not path.exists():
        raise SystemExit(f"no index at {path} — run python -m paRY.index.build")
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def lexical_search(
    connection: sqlite3.Connection,
    question: str,
    *,
    limit: int = 8,
    kinds: tuple[str, ...] | None = None,
) -> list[Hit]:
    filter_sql = ""
    parameters: list[object] = []
    if kinds:
        filter_sql = f" AND c.kind IN ({','.join('?' * len(kinds))})"
        parameters = list(kinds)

    for query in queries(question):
        sql = (
            "SELECT c.kind, c.title, c.path, c.line, c.compiles, c.body, "
            "  bm25(chunks_fts, ?, ?, ?) AS score, "
            "  snippet(chunks_fts, 2, '', '', ' … ', 24) AS snippet "
            "FROM chunks_fts f JOIN chunks c ON c.id = f.rowid "
            f"WHERE chunks_fts MATCH ?{filter_sql} "
            "ORDER BY score LIMIT ?"
        )
        try:
            rows = connection.execute(
                sql, [*WEIGHTS, query, *parameters, limit]
            ).fetchall()
        except sqlite3.OperationalError:
            continue  # a pass that FTS5 will not parse is a pass we skip
        if rows:
            return [
                Hit(
                    kind=row["kind"],
                    title=row["title"],
                    path=row["path"],
                    line=row["line"],
                    compiles=None if row["compiles"] is None else bool(row["compiles"]),
                    # bm25 returns a negative number, best first. Flip it so a
                    # bigger score is a better hit, which is what a caller expects.
                    score=round(-row["score"], 3),
                    snippet=row["snippet"],
                    body=row["body"],
                    lexical=round(-row["score"], 3),
                )
                for row in rows
            ]
    return []


def _has_vectors(connection: sqlite3.Connection) -> bool:
    try:
        return connection.execute("SELECT 1 FROM chunk_vectors LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False  # an index built before embeddings existed


def semantic_search(
    connection: sqlite3.Connection,
    question: str,
    *,
    limit: int = 30,
    kinds: tuple[str, ...] | None = None,
) -> list[Hit]:
    """Nearest chunks by meaning, or nothing at all if that is not available.

    Returns [] rather than raising when there are no vectors or no embedder:
    semantic search is an improvement to retrieval, not a dependency of it, and
    paRY has to keep working on a machine that has neither.
    """
    if not _has_vectors(connection):
        return []
    try:
        from . import embed

        query = embed.embed_texts([question])[0]
    except Exception:
        # A stopped Ollama must not take the search down with it.
        return []

    length = math.sqrt(sum(value * value for value in query)) or 1.0
    probe = [value / length for value in query]
    width = len(probe)

    sql = (
        "SELECT c.kind, c.title, c.path, c.line, c.compiles, c.body, v.dims, v.vector "
        "FROM chunk_vectors v JOIN chunks c ON c.id = v.chunk_id"
    )
    parameters: list[object] = []
    if kinds:
        sql += f" WHERE c.kind IN ({','.join('?' * len(kinds))})"
        parameters = list(kinds)

    scored: list[tuple[float, sqlite3.Row]] = []
    for row in connection.execute(sql, parameters):
        if row["dims"] != width:
            continue  # a vector from a different model; ignore rather than guess
        stored = struct.unpack(f"<{width}f", row["vector"])
        # Both sides are unit vectors, so the dot product is the cosine.
        scored.append((sum(a * b for a, b in zip(probe, stored)), row))

    scored.sort(key=lambda pair: -pair[0])
    return [
        Hit(
            kind=row["kind"],
            title=row["title"],
            path=row["path"],
            line=row["line"],
            compiles=None if row["compiles"] is None else bool(row["compiles"]),
            score=round(similarity, 4),
            snippet=(row["body"] or "")[:160],
            body=row["body"],
            lexical=0.0,
        )
        for similarity, row in scored[:limit]
    ]


# Reciprocal rank fusion. bm25 scores and cosine similarities are not on the
# same scale and normalising them against each other needs a constant nobody
# can justify, so neither number is used: only the position each retriever put
# a chunk in. A chunk both agree on rises; a chunk only one found still gets a
# hearing. K dampens the top of each list so rank one is not overwhelming.
RRF_K = 60

#: How far an expansion's opinion outweighs the original question's. Swept
#: below; see the commit that introduced it.
EXPANSION_TRUST = 1.0

# The index holds two different things and reciprocal rank fusion treats them
# as interchangeable, which they are not. `symbol` chunks are the API itself —
# a name you can call. `doc_section` chunks are prose *about* eTamil. For "how
# do I do X", the function is the answer and the documentation is background,
# so a section that merely mentions the topic should not outrank the function
# that performs it.
#
# The weights multiply each retriever's contribution. They are not a statement
# that documentation is worth less: a question about a concept still reaches
# it, because the weight tilts a close contest rather than filtering anything
# out. Measured over paRY/eval/lookup.py, twenty questions whose answer is a
# known function.
KIND_WEIGHT = {
    "symbol": 1.0,
    "recipe": 1.0,
    "example": 0.9,
    "doc_block": 0.7,
    "doc_section": 0.55,
}
DEFAULT_KIND_WEIGHT = 0.8

#: How deep to look in each retriever before fusing. Wider than the answer, so
#: a chunk ranked tenth lexically and second semantically can still win.
FUSION_DEPTH = 30


def search(
    connection: sqlite3.Connection,
    question: str,
    *,
    limit: int = 8,
    kinds: tuple[str, ...] | None = None,
    expand: bool = False,
) -> list[Hit]:
    """Lexical and semantic retrieval, fused.

    Degrades to lexical alone, silently and on purpose: an index with no
    vectors is the normal state on a machine with no Ollama, and a search that
    refused to run there would make paRY undevelopable on the machine that
    builds its corpus.
    """
    # Both retrievers need the question and the document to share words, and
    # a question asked in ordinary English often shares none with a library
    # written in Tamil. `expand` asks the local model for the domain terms and
    # searches for those as well as the original — never instead of it, so an
    # expansion that goes wrong can only add noise, not remove the right hit.
    lexical = lexical_search(connection, question, limit=FUSION_DEPTH, kinds=kinds)
    semantic = semantic_search(connection, question, limit=FUSION_DEPTH, kinds=kinds)

    # Expansion is a *second opinion*, not a rewrite. Appending the model's
    # terms to the question was tried and scored worse than not expanding at
    # all — the added words dilute the original in the embedding and pull
    # long prose up the lexical list. Searching the expansion separately and
    # fusing the two leaves the original's own ranking intact.
    extra: list[list[Hit]] = []
    if expand:
        from ..answer import model

        terms = model.expand_query(question)
        if terms:
            extra.append(lexical_search(connection, terms, limit=FUSION_DEPTH, kinds=kinds))
            found = semantic_search(connection, terms, limit=FUSION_DEPTH, kinds=kinds)
            if found:
                extra.append(found)

    if not semantic and not extra:
        return lexical[:limit]

    ranked: dict[tuple[str, str], tuple[float, Hit]] = {}
    lists = [(1.0, lexical), (1.0, semantic)] + [(EXPANSION_TRUST, e) for e in extra]
    for list_weight, hits in lists:
        for position, hit in enumerate(hits):
            key = (hit.title, hit.path or "")
            weight = KIND_WEIGHT.get(hit.kind, DEFAULT_KIND_WEIGHT)
            contribution = list_weight * weight / (RRF_K + position + 1)
            if key in ranked:
                previous, kept = ranked[key]
                # Keep whichever copy carries the lexical score, so the
                # calibrated thresholds downstream still see a real bm25 number.
                better = kept if kept.lexical >= hit.lexical else hit
                ranked[key] = (previous + contribution, better)
            else:
                ranked[key] = (contribution, hit)

    fused = sorted(ranked.values(), key=lambda pair: -pair[0])
    return [
        replace(hit, score=round(total, 6))
        for total, hit in fused[:limit]
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the paRY index.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--kind", action="append", dest="kinds")
    parser.add_argument("--index", type=Path, default=None)
    args = parser.parse_args(argv)

    question = " ".join(args.question)
    connection = connect(args.index)
    hits = search(
        connection, question, limit=args.limit, kinds=tuple(args.kinds) if args.kinds else None
    )
    if not hits:
        print(f"nothing found for {question!r}")
        return 1

    for hit in hits:
        where = f"{hit.path}:{hit.line}" if hit.path else ""
        mark = {True: " ✓compiles", False: " ✗does not compile", None: ""}[hit.compiles]
        print(f"[{hit.score:>7.2f}] {hit.kind:<12} {hit.title}{mark}")
        if where:
            print(f"          {where}")
        print(f"          {hit.snippet.strip()[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
