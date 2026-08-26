"""Build the held-out completion cases, before anything is trained.

A case is a program cut in two: what comes before the cursor, what should come
next, and what follows. That is the shape fill-in-the-middle is asked for in an
editor, so it is the shape the model is measured on.

Three rules this obeys, and each of them is the difference between a benchmark
and a comforting number:

* **Held out means held out.** The ids of every source used here are written to
  `holdout.json`, and corpus generation must skip them. A model scored on text
  it was trained on tells you nothing.
* **Cuts are deterministic**, at fixed fractions through the file. Re-running
  this produces the same cases, so two runs are comparable.
* **Only sources that compile** become cases. If the whole program does not
  compile, "did the completion parse" cannot be answered.

    python -m paRY.eval.build
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config, knowledge
from ..corpus.collect import read_jsonl
from ..verify import oracle

# Where in the file to cut. Early, middle and late: completing the first line of
# a function is a different problem from completing its last.
CUTS = (0.30, 0.55, 0.78)

# How many lines the model is asked to produce. One line is what an editor
# actually shows; two catches whether it can finish a block.
MIDDLE_LINES = (1, 2)


@dataclass(frozen=True)
class Case:
    id: str
    kind: str
    source: str
    prefix: str
    middle: str
    suffix: str
    cut_line: int


def _cut_points(lines: list[str]) -> list[int]:
    """Line indexes to cut at, skipping blank lines and comment-only lines."""
    points: list[int] = []
    for fraction in CUTS:
        index = int(len(lines) * fraction)
        # Walk forward to a line worth predicting: blank lines and comments are
        # free to guess and would flatter the score.
        while index < len(lines) - 1:
            candidate = lines[index].strip()
            if candidate and not candidate.startswith("//"):
                break
            index += 1
        if 0 < index < len(lines) - 1 and index not in points:
            points.append(index)
    return points


def cases_from(identifier: str, kind: str, text: str) -> list[Case]:
    lines = text.split("\n")
    if len(lines) < 6:
        return []  # nothing to hold back in a five-line program

    cases: list[Case] = []
    for index in _cut_points(lines):
        for span in MIDDLE_LINES:
            if index + span >= len(lines):
                continue
            middle = "\n".join(lines[index : index + span])
            if not middle.strip():
                continue
            cases.append(
                Case(
                    id=f"{identifier}@{index}+{span}",
                    kind=kind,
                    source=identifier,
                    prefix="\n".join(lines[:index]) + "\n",
                    middle=middle + "\n",
                    suffix="\n".join(lines[index + span :]),
                    cut_line=index + 1,
                )
            )
    return cases


def collect_sources(corpus_dir: Path) -> list[tuple[str, str, str]]:
    """Everything that could become a case: id, kind, text."""
    sources: list[tuple[str, str, str]] = []

    for record in read_jsonl(corpus_dir / "documents.jsonl"):
        if record["kind"] in {"stdlib", "example", "bench"}:
            sources.append((record["id"], "example", record["text"]))

    for block in read_jsonl(corpus_dir / "blocks.jsonl"):
        if block["is_etamil"]:
            sources.append((block["id"], "doc_block", block["text"]))

    for recipe in knowledge.load_recipes():
        sources.append((f"recipe/{recipe.id}", "recipe", recipe.code))

    return sources


def build(corpus_dir: Path, out_dir: Path, limit: int) -> dict:
    sources = collect_sources(corpus_dir)
    print(f"  {len(sources)} candidate sources; compiling them")

    verdicts = oracle.check_many([text for _, _, text in sources])
    usable = [
        (identifier, kind, text)
        for (identifier, kind, text), outcome in zip(sources, verdicts)
        if outcome.ok
    ]
    print(f"  {len(usable)} compile and can be cut into cases")

    cases: list[Case] = []
    for identifier, kind, text in usable:
        cases.extend(cases_from(identifier, kind, text))

    # Deterministic order, then a cap — so the set is stable and comparable.
    cases.sort(key=lambda case: case.id)
    if limit and len(cases) > limit:
        # Spread the cap across sources rather than taking the alphabetical
        # first N, which would be every case from a handful of files.
        step = len(cases) / limit
        cases = [cases[int(index * step)] for index in range(limit)]

    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "cases.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")

    holdout = sorted({case.source for case in cases})
    (out_dir / "holdout.json").write_text(
        json.dumps(
            {
                "note": "Corpus generation must skip these. A model scored on what "
                        "it was trained on tells you nothing.",
                "sources": holdout,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    by_kind: dict[str, int] = {}
    for case in cases:
        by_kind[case.kind] = by_kind.get(case.kind, 0) + 1

    return {"cases": len(cases), "sources": len(holdout), "by_kind": by_kind}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the completion eval set.")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "eval")
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args(argv)

    summary = build(args.corpus, args.out, args.limit)
    print(f"{summary['cases']} cases from {summary['sources']} held-out sources")
    for kind, count in sorted(summary["by_kind"].items()):
        print(f"    {kind:<12} {count:>4}")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
