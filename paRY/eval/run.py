"""Run a completer over the held-out cases and report what it scored.

The baselines here exist to make Phase A judgeable. A model is not good because
its output looks like eTamil; it is good if it beats what you already had for
free. Four things you already have:

    nothing    predict nothing at all — the floor, and it compiles more often
               than you would like, which is the point of measuring it
    previous   repeat the line before the hole
    retrieval  find the nearest code in the index and take the lines that
               followed it there — this is paRY today, with no model
    truth      the removed lines themselves — the ceiling, and a check on the
               harness: anything below 100% here is a bug in the eval, not a
               result

When the Phase A model exists it becomes a fifth completer against the same
cases, and the comparison is the whole argument for or against it.

    python -m paRY.eval.run                    # every baseline
    python -m paRY.eval.run --completer truth  # just one
"""

from __future__ import annotations

import argparse
import json
from contextlib import closing
from pathlib import Path
from typing import Callable

from .. import config
from ..index import search
from .cases import Case, load
from .sandbox import Sandbox
from .score import Score, score, summarise

Completer = Callable[[Case], str]


def complete_nothing(case: Case) -> str:
    return ""


def complete_previous(case: Case) -> str:
    """Repeat the last line before the hole, once per missing line.

    Weak, but not silly: code repeats, and in a block of assignments the next
    line really does look like the last one.
    """
    lines = [line for line in case.prefix.split("\n") if line.strip()]
    if not lines:
        return ""
    return "\n".join([lines[-1]] * case.hole) + "\n"


def _retrieval_completer(connection) -> Completer:
    """Nearest code in the index, leaving out the file the case came from.

    Without that exclusion this scores 66.7% exact, and the number is worthless:
    the held-out files are held out of *training*, but they are still in the
    retrieval index, so the completer finds the very file the hole was cut from
    and copies the missing lines back. That is not retrieval working, it is the
    answer being in the room. Leave-one-out is the honest version.
    """

    def complete(case: Case) -> str:
        anchor = next(
            (line for line in reversed(case.prefix.split("\n")) if line.strip()), ""
        )
        if not anchor.strip():
            return ""

        for hit in search.search(connection, anchor, limit=6, kinds=search.CODE_KINDS):
            if hit.path == case.path:
                continue
            lines = hit.code.split("\n")
            for index, line in enumerate(lines):
                if line.strip() == anchor.strip() and index + 1 + case.hole <= len(lines):
                    return "\n".join(lines[index + 1 : index + 1 + case.hole]) + "\n"
        return ""

    return complete


def complete_truth(case: Case) -> str:
    return case.middle


def run(completer: Completer, cases: list[Case]) -> list[Score]:
    with Sandbox() as box:
        return [score(case, completer(case), box) for case in cases]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score completers on the held-out cases.")
    parser.add_argument("--cases", type=Path, default=None)
    parser.add_argument(
        "--completer",
        action="append",
        choices=("nothing", "previous", "retrieval", "truth"),
        help="which to run (default: all)",
    )
    parser.add_argument("--out", type=Path, default=config.REPORT_DIR / "eval.json")
    args = parser.parse_args(argv)

    cases = load(args.cases)
    wanted = args.completer or ["nothing", "previous", "retrieval", "truth"]

    connection = None
    results: dict[str, dict] = {}
    try:
        for name in wanted:
            if name == "retrieval":
                connection = connection or search.connect()
                completer: Completer = _retrieval_completer(connection)
            else:
                completer = {
                    "nothing": complete_nothing,
                    "previous": complete_previous,
                    "truth": complete_truth,
                }[name]

            print(f"running {name} over {len(cases)} cases…")
            results[name] = summarise(run(completer, cases))
    finally:
        if connection is not None:
            connection.close()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"cases": len(cases), "results": results}, indent=2) + "\n", encoding="utf-8"
    )

    print()
    print(f"{'completer':<12}{'exact':>9}{'similar':>9}{'compiles':>10}{'empty':>8}")
    for name, summary in results.items():
        print(
            f"{name:<12}{summary['exact']:>8.1%}{summary['similarity']:>9.3f}"
            f"{summary['compiles']:>10.1%}{summary['empty']:>8.1%}"
        )

    if "truth" in results and results["truth"]["exact"] < 1.0:
        print("\nthe truth completer is not scoring 100% — that is a bug in the eval")
    print(f"\nreport written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
