"""Can retrieval find the function that answers a plain English question?

    python -m paRY.eval.lookup

The other eval in this package measures completion: given code with a hole,
does a completer fill it. This measures the question the chat panel actually
receives — somebody describes what they want in words and expects the name of
the thing that does it.

Each case is a question and the one nUlakam function that answers it. The
expectations are taken from the functions' own documentation rather than from
what the index happens to return, and they include cases that were failing
when this was written: a set every entry of which already passes measures
nothing.

Reported as recall@k and MRR over the symbol chunks. Rank matters and not just
presence: an answer at position eleven is an answer nobody scrolls to.
"""

from __future__ import annotations

import argparse
import sys

from ..index import search

#: question -> the nUlakam function that answers it.
CASES: list[tuple[str, str]] = [
    ("cost per unit", "அலகுக்குச்_செலவு"),
    ("how do I compute break-even", "சமநிலை_அலகுகள்"),
    ("what is the square root function", "வர்க்கமூலம்"),
    ("how do I reverse an array", "தலைகீழ்"),
    ("is this array empty", "காலியா"),
    ("does this array contain a value", "உள்ளதா"),
    ("the last day of the month", "மாத_இறுதி"),
    ("is it a leap year", "நெட்டாண்டா"),
    ("encode text as base64", "அறுபத்துநான்கு_ஆக்கு"),
    ("parse JSON text", "ஜேசான்_படி"),
    ("format an amount in rupees", "ரூபாய்"),
    ("show an amount in crore", "கோடி"),
    ("does a string start with a prefix", "தொடங்குகிறதா"),
    ("the average of some numbers", "சராசரி"),
    ("the larger of two numbers", "பெரியது"),
    ("produce a trial balance", "இருப்பாய்வு"),
    ("a reducing balance depreciation schedule", "குறையும்_அட்டவணை"),
    ("the labour rate variance", "ஊதிய_வீத_வேறுபாடு"),
    ("earned value cost variance", "செலவு_வேறுபாடு"),
    ("how much GST on an amount", "வரி_தொகை"),
]

DEPTH = 20


def rank_of(hits, wanted: str) -> int | None:
    """Where the wanted function's own symbol chunk landed, 1-based."""
    for position, hit in enumerate(hits, start=1):
        # The symbol chunk's title is "name(params) — nUlakam"; matching the
        # title alone avoids counting a doc section that merely mentions it.
        if hit.kind == "symbol" and hit.title.startswith(f"{wanted}("):
            return position
    return None


def measure(connection, retriever, depth: int = DEPTH) -> dict:
    ranks: list[int | None] = []
    for question, wanted in CASES:
        ranks.append(rank_of(retriever(connection, question, limit=depth), wanted))
    found = [r for r in ranks if r is not None]
    return {
        "ranks": ranks,
        "at1": sum(1 for r in found if r == 1),
        "at3": sum(1 for r in found if r <= 3),
        "at10": sum(1 for r in found if r <= 10),
        "mrr": sum(1.0 / r for r in found) / len(CASES),
    }


def report(label: str, result: dict) -> None:
    n = len(CASES)
    print(
        f"  {label:<10} recall@1 {result['at1']:>2}/{n}   "
        f"@3 {result['at3']:>2}/{n}   @10 {result['at10']:>2}/{n}   "
        f"MRR {result['mrr']:.3f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure question-to-function lookup.")
    parser.add_argument("--detail", action="store_true", help="print every case")
    args = parser.parse_args(argv)

    connection = search.connect()
    results = {
        "lexical": measure(connection, search.lexical_search),
        "semantic": measure(connection, search.semantic_search),
        "fused": measure(connection, search.search),
    }
    print(f"  {len(CASES)} questions, looking for the function's own symbol chunk\n")
    for label, result in results.items():
        report(label, result)

    if args.detail:
        print()
        for (question, wanted), rank in zip(CASES, results["fused"]["ranks"]):
            mark = "ok  " if rank == 1 else ("    " if rank else "MISS")
            print(f"  {mark} {str(rank or '-'):>3}  {question[:38]:<40} {wanted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
