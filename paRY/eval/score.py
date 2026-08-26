"""Score a predictor against the held-out cases.

Four measures, because one number would hide the thing that matters most.

    exact        the completion is character-for-character what was there
    similarity   how close it came, when it was not exact
    compiles     prefix + completion + suffix goes through the compiler
    invented     did it use a name the compiler does not have

`invented` is the one to watch. A completion that does not compile costs a
developer ten seconds; a completion that invents a plausible keyword teaches
them a keyword that does not exist, and they blame the language. A model that
scores worse on `exact` but zero on `invented` is the better model.

Two baselines are built in, and they exist to stop a number being read as good
on its own: `empty` predicts nothing, `previous` repeats the line above. Any
model has to beat both to have earned its forty cents.

    python -m paRY.eval.score --baseline previous
    python -m paRY.eval.score --predictions runs/phase-a/predictions.jsonl
"""

from __future__ import annotations

import argparse
import json
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from .. import config, lexicon
from ..index import search
from ..verify import oracle

Predictor = Callable[[dict], str]


def load_cases(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def normalise(text: str) -> str:
    """Trailing whitespace is not a difference anyone cares about."""
    return "\n".join(line.rstrip() for line in text.strip().split("\n"))


def invented_names(prediction: str, accepted: set[str]) -> list[str]:
    """Words in the completion that look like eTamil names but are not any.

    Only Tamil-script words are judged. A romanized word could be a variable
    someone made up, and inventing a variable is allowed — inventing a keyword
    is not.
    """
    suspicious = []
    for word in search.terms(prediction):
        if word.isascii() or word in accepted:
            continue
        if any(character.isdigit() for character in word):
            continue
        suspicious.append(word)
    return suspicious


def score(cases: list[dict], predict: Predictor, *, workers: int | None = None) -> dict:
    accepted = set(lexicon.load().vocabulary)
    predictions = [predict(case) for case in cases]

    # One compile per case, pooled — the slowest part of scoring by far.
    completed = [
        case["prefix"] + prediction + case["suffix"]
        for case, prediction in zip(cases, predictions)
    ]
    outcomes = oracle.check_many(completed, workers=workers)

    rows = []
    for case, prediction, outcome in zip(cases, predictions, outcomes):
        expected = normalise(case["middle"])
        got = normalise(prediction)
        # Identifiers a case's own prefix introduced are legitimate to repeat.
        local = {word for word in search.terms(case["prefix"]) if not word.isascii()}
        rows.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "exact": got == expected,
                "similarity": round(SequenceMatcher(None, expected, got).ratio(), 4),
                "compiles": outcome.ok,
                "invented": invented_names(prediction, accepted | local),
                "empty": not got,
            }
        )

    return summarise(rows)


def summarise(rows: list[dict]) -> dict:
    def share(predicate) -> float:
        return round(sum(1 for row in rows if predicate(row)) / len(rows), 4) if rows else 0.0

    by_kind: dict[str, list[dict]] = {}
    for row in rows:
        by_kind.setdefault(row["kind"], []).append(row)

    return {
        "cases": len(rows),
        "exact": share(lambda row: row["exact"]),
        "similarity": round(sum(row["similarity"] for row in rows) / len(rows), 4) if rows else 0.0,
        "compiles": share(lambda row: row["compiles"]),
        "invented_any": share(lambda row: bool(row["invented"])),
        "empty": share(lambda row: row["empty"]),
        "by_kind": {
            kind: {
                "cases": len(group),
                "exact": round(sum(1 for row in group if row["exact"]) / len(group), 4),
                "compiles": round(sum(1 for row in group if row["compiles"]) / len(group), 4),
            }
            for kind, group in sorted(by_kind.items())
        },
        "rows": rows,
    }


# --- baselines ---------------------------------------------------------------

def predict_empty(_case: dict) -> str:
    """Predict nothing. The floor: whatever this scores is worth zero."""
    return ""


def predict_previous(case: dict) -> str:
    """Repeat the line above the cursor. Surprisingly hard to beat on `compiles`."""
    lines = [line for line in case["prefix"].split("\n") if line.strip()]
    return (lines[-1] + "\n") if lines else ""


BASELINES = {"empty": predict_empty, "previous": predict_previous}


def from_file(path: Path) -> Predictor:
    """Predictions produced elsewhere — by a model on a rented box, usually."""
    with path.open("r", encoding="utf-8") as handle:
        table = {
            record["id"]: record.get("prediction", "")
            for record in (json.loads(line) for line in handle if line.strip())
        }
    missing = object()

    def predict(case: dict) -> str:
        value = table.get(case["id"], missing)
        if value is missing:
            raise SystemExit(f"no prediction for case {case['id']}")
        return str(value)

    return predict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score a predictor on the eval set.")
    parser.add_argument("--cases", type=Path, default=config.DATA_DIR / "eval" / "cases.jsonl")
    parser.add_argument("--baseline", choices=sorted(BASELINES))
    parser.add_argument("--predictions", type=Path, help="JSONL of {id, prediction}")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if not args.cases.exists():
        raise SystemExit(f"no cases at {args.cases} — run python -m paRY.eval.build")
    if bool(args.baseline) == bool(args.predictions):
        parser.error("give exactly one of --baseline or --predictions")

    cases = load_cases(args.cases)
    predict = BASELINES[args.baseline] if args.baseline else from_file(args.predictions)
    label = args.baseline or args.predictions.name

    report = score(cases, predict)
    report["predictor"] = label

    print(f"{label} — {report['cases']} cases")
    print(f"  exact       {report['exact']:>7.1%}")
    print(f"  similarity  {report['similarity']:>7.1%}")
    print(f"  compiles    {report['compiles']:>7.1%}")
    print(f"  invented    {report['invented_any']:>7.1%}   (lower is better)")
    for kind, group in report["by_kind"].items():
        print(f"    {kind:<12} {group['cases']:>4} cases  exact {group['exact']:>6.1%}"
              f"  compiles {group['compiles']:>6.1%}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
