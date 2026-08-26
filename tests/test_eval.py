"""The eval harness, which is only worth anything if it is honest."""

import pytest

from paRY import config
from paRY.eval import cases as eval_cases
from paRY.eval import run as eval_run
from paRY.eval.sandbox import Sandbox
from paRY.eval.score import normalise, score, summarise

CASES = config.DATA_DIR / "eval" / "completion.jsonl"

needs_cases = pytest.mark.skipif(
    not CASES.exists() or config.etamil_bin() is None,
    reason="run python -m paRY.eval.cases",
)


def test_the_split_is_the_same_on_every_machine():
    """It is a hash of the path, so two machines hold out the same files."""
    assert eval_cases.is_held_out("nUlakam/paNam.qmz") in (True, False)
    assert eval_cases.is_held_out("a.qmz") == eval_cases.is_held_out("a.qmz")
    held = [eval_cases.is_held_out(f"file{n}.qmz") for n in range(200)]
    # Roughly one in five, and certainly not all or nothing.
    assert 0.10 < sum(held) / len(held) < 0.35


def test_a_hole_of_blank_lines_is_not_worth_predicting():
    assert not eval_cases._worth_predicting(["", "   ", ""])
    assert not eval_cases._worth_predicting(["// just a comment"])
    assert eval_cases._worth_predicting(["அச்சு 1;"])


def test_trailing_whitespace_is_not_a_difference():
    assert normalise("அச்சு 1;   \n") == normalise("அச்சு 1;")


@needs_cases
def test_the_cases_reconstruct_the_original_file():
    """prefix + middle + suffix has to be the file it was cut from."""
    for case in eval_cases.load(CASES)[:40]:
        assert case.middle.strip(), f"{case.id} has an empty hole"
        # Every removed line keeps its newline, so counting those counts lines.
        # Splitting after an rstrip would lose a hole that ends in a blank line.
        assert case.middle.count("\n") == case.hole


@needs_cases
def test_the_truth_completer_scores_perfectly():
    """The ceiling, and the harness's own check.

    Anything below 100% here means the eval is broken, not that a completer is
    bad — a case whose own answer does not compile would quietly punish every
    model measured against it.
    """
    sample = eval_cases.load(CASES)[:25]
    with Sandbox() as box:
        scores = [score(case, eval_run.complete_truth(case), box) for case in sample]
    summary = summarise(scores)
    assert summary["exact"] == 1.0
    assert summary["compiles"] == 1.0


@needs_cases
def test_predicting_nothing_is_not_scored_as_success():
    sample = eval_cases.load(CASES)[:15]
    with Sandbox() as box:
        scores = [score(case, "", box) for case in sample]
    summary = summarise(scores)
    assert summary["exact"] == 0.0
    assert summary["empty"] == 1.0
    # It still compiles sometimes, which is why `compiles` alone means little.
    assert 0.0 <= summary["compiles"] <= 1.0


@needs_cases
def test_retrieval_never_reads_the_file_it_is_completing():
    """Leaving that out took it from 66.7% exact to 1.3%.

    The held-out files are held out of training, not out of the index, so
    without this the completer finds the very file the hole was cut from.
    """
    from paRY.index import search
    from paRY.eval.score import normalise

    connection = search.connect()
    try:
        completer = eval_run._retrieval_completer(connection)
        sample = eval_cases.load(CASES)[:60]
        exact = sum(
            normalise(completer(case)) == normalise(case.middle) for case in sample
        )
        # One line of eTamil can legitimately match another file's, so this is a
        # rate rather than a rule: with the answer file in scope it was 67%.
        assert exact / len(sample) < 0.20, f"{exact}/{len(sample)} exact — leakage is back"
    finally:
        connection.close()
