"""How a completion is judged.

Four numbers, and they disagree with each other on purpose:

    exact       the prediction is the removed lines, character for character
    similarity  how close it came when it was not exact (0–1)
    compiles    prefix + prediction + suffix builds
    empty       the model declined to answer

Exact match alone is too harsh — a different variable name is not a wrong
answer. Similarity alone is too kind — text that looks right and does not
compile is worse than nothing, because an editor inserts it. Compiling alone is
too kind in the other direction: predicting `}` compiles surprisingly often.

Reading them together is the point. A completer that scores well on compiling
and badly on similarity has learnt to close braces, not to write eTamil.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .cases import Case
from .sandbox import Sandbox


def normalise(text: str) -> str:
    """Trailing whitespace is not a difference anyone cares about."""
    return "\n".join(line.rstrip() for line in text.strip("\n").split("\n"))


@dataclass(frozen=True)
class Score:
    case_id: str
    predicted: str
    exact: bool
    similarity: float
    compiles: bool
    empty: bool


def score(case: Case, prediction: str, box: Sandbox) -> Score:
    expected = normalise(case.middle)
    got = normalise(prediction)

    candidate = case.prefix + (prediction if prediction.endswith("\n") or not prediction
                               else prediction + "\n") + case.suffix

    return Score(
        case_id=case.id,
        predicted=got,
        exact=got == expected,
        similarity=round(SequenceMatcher(None, expected, got).ratio(), 4),
        compiles=box.compiles(case.path, candidate),
        empty=got == "",
    )


def summarise(scores: list[Score]) -> dict:
    if not scores:
        return {"cases": 0}
    total = len(scores)
    return {
        "cases": total,
        "exact": round(sum(s.exact for s in scores) / total, 4),
        "similarity": round(sum(s.similarity for s in scores) / total, 4),
        "compiles": round(sum(s.compiles for s in scores) / total, 4),
        "empty": round(sum(s.empty for s in scores) / total, 4),
    }
