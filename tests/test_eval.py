"""The eval set, which is what stops Phase A being expensive guessing."""

import json

import pytest

from paRY import config
from paRY.eval import build, score

CASES = config.DATA_DIR / "eval" / "cases.jsonl"

needs_cases = pytest.mark.skipif(
    not CASES.exists() or config.etamil_bin() is None,
    reason="run python -m paRY.eval.build",
)

PROGRAM = "\n".join(
    [
        "// a small program",
        "எண் வருவாய்;",
        "வருவாய் = 100;",
        "அச்சு வருவாய்;",
        "அச்சு வருவாய் * 2;",
        "அச்சு வருவாய் * 3;",
        "அச்சு வருவாய் * 4;",
        "அச்சு \"done\";",
    ]
)


def test_a_case_reassembles_into_the_original():
    """prefix + middle + suffix is the program it was cut from, exactly."""
    for case in build.cases_from("x", "example", PROGRAM):
        assert case.prefix + case.middle + case.suffix == PROGRAM


def test_cuts_avoid_blank_lines_and_comments():
    """Completing a comment is free, and would flatter every score."""
    for case in build.cases_from("x", "example", PROGRAM):
        first = case.middle.split("\n")[0].strip()
        assert first and not first.startswith("//")


def test_a_program_too_short_to_hold_anything_back_yields_nothing():
    assert build.cases_from("x", "example", "அச்சு 1;\nஅச்சு 2;") == []


def test_building_is_deterministic():
    once = [case.id for case in build.cases_from("x", "example", PROGRAM)]
    twice = [case.id for case in build.cases_from("x", "example", PROGRAM)]
    assert once == twice and once


def test_an_invented_tamil_name_is_caught():
    """The failure that matters: a keyword that does not exist."""
    accepted = {"அச்சு"}
    assert score.invented_names("அச்சு 1;", accepted) == []
    assert score.invented_names("அச்சுபோடு 1;", accepted) == ["அச்சுபோடு"]


def test_a_romanized_word_is_not_judged():
    """It could be a variable someone made up, and that is allowed."""
    assert score.invented_names("varuvAy = 1;", set()) == []


def test_normalise_ignores_trailing_whitespace():
    assert score.normalise("அச்சு 1;   \n") == score.normalise("அச்சு 1;")


@needs_cases
def test_the_holdout_list_covers_every_case():
    """Corpus generation reads this file to know what not to train on."""
    cases = score.load_cases(CASES)
    holdout = json.loads((config.DATA_DIR / "eval" / "holdout.json").read_text(encoding="utf-8"))
    assert {case["source"] for case in cases} <= set(holdout["sources"])


@needs_cases
def test_the_empty_baseline_scores_zero_on_what_matters():
    """It compiles often — which is exactly why `compiles` alone means little."""
    report = score.score(score.load_cases(CASES)[:20], score.predict_empty)
    assert report["exact"] == 0.0
    assert report["invented_any"] == 0.0
    assert report["empty"] == 1.0
