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

#: The same twenty functions, asked differently.
#:
#: CASES above was written while diagnosing why retrieval failed, so the docs
#: were then edited knowing those questions — and scoring that edit against
#: them would prove only that the words had been copied across. These
#: phrasings avoid the wording that went into the docs: the doc now says
#: "reverse an array", so this asks to flip the order of a list.
#:
#: When the two sets disagree, believe this one.
HELD_OUT: list[tuple[str, str]] = [
    ("what does each item cost me to make", "அலகுக்குச்_செலவு"),
    ("how many must I sell before I stop losing money", "சமநிலை_அலகுகள்"),
    ("find the root of a number", "வர்க்கமூலம்"),
    ("flip the order of a list", "தலைகீழ்"),
    ("check whether a list has nothing in it", "காலியா"),
    ("see if an item is in a list", "உள்ளதா"),
    ("when does this month end", "மாத_இறுதி"),
    ("does February have 29 days this year", "நெட்டாண்டா"),
    ("turn a string into base64", "அறுபத்துநான்கு_ஆக்கு"),
    ("read a JSON string into data", "ஜேசான்_படி"),
    ("print money with the rupee symbol", "ரூபாய்"),
    ("display a big number the Indian way", "கோடி"),
    ("test whether text begins with something", "தொடங்குகிறதா"),
    ("the mean of a set of values", "சராசரி"),
    ("pick whichever number is bigger", "பெரியது"),
    ("list every account balance to check the books", "இருப்பாய்வு"),
    ("write off an asset a bit each year", "குறையும்_அட்டவணை"),
    ("why did wages cost more per hour than planned", "ஊதிய_வீத_வேறுபாடு"),
    ("is the project spending more than the work is worth", "செலவு_வேறுபாடு"),
    ("how much tax do I add to a sale", "வரி_தொகை"),
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


def measure(connection, retriever, depth: int = DEPTH, cases=None) -> dict:
    cases = CASES if cases is None else cases
    ranks: list[int | None] = []
    for question, wanted in cases:
        ranks.append(rank_of(retriever(connection, question, limit=depth), wanted))
    found = [r for r in ranks if r is not None]
    return {
        "ranks": ranks,
        "at1": sum(1 for r in found if r == 1),
        "at3": sum(1 for r in found if r <= 3),
        "at10": sum(1 for r in found if r <= 10),
        "mrr": sum(1.0 / r for r in found) / len(cases),
    }


def report(label: str, result: dict) -> None:
    n = len(result["ranks"])
    print(
        f"  {label:<10} recall@1 {result['at1']:>2}/{n}   "
        f"@3 {result['at3']:>2}/{n}   @10 {result['at10']:>2}/{n}   "
        f"MRR {result['mrr']:.3f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure question-to-function lookup.")
    parser.add_argument("--detail", action="store_true", help="print every held-out case")
    args = parser.parse_args(argv)

    connection = search.connect()
    held = None
    for name, cases in (("diagnostic", CASES), ("held out", HELD_OUT)):
        print(f"  {name}: {len(cases)} questions")
        for label, retriever in (
            ("lexical", search.lexical_search),
            ("semantic", search.semantic_search),
            ("fused", search.search),
            ("expanded", lambda c, q, limit: search.search(c, q, limit=limit, expand=True)),
        ):
            result = measure(connection, retriever, cases=cases)
            report(label, result)
            if name == "held out" and label == "fused":
                held = result
        print()

    if args.detail and held:
        for (question, wanted), rank in zip(HELD_OUT, held["ranks"]):
            mark = "ok  " if rank == 1 else ("    " if rank else "MISS")
            print(f"  {mark} {str(rank or '-'):>3}  {question[:44]:<46} {wanted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
