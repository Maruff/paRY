"""The routing rules, and the one invariant that matters."""

import pytest

from paRY import config
from paRY.answer import engine
from paRY.answer.phrases import detect_locale
from paRY.index import search
from paRY.verify import oracle

INDEX = config.DATA_DIR / "index" / "paRY.db"

needs_index = pytest.mark.skipif(
    not INDEX.exists() or config.etamil_bin() is None,
    reason="run python -m paRY.index.build, and build the compiler",
)


@pytest.fixture(scope="module")
def connection():
    return search.connect(INDEX)


def test_a_tamil_question_is_answered_in_tamil():
    assert detect_locale("நீளம் என்றால் என்ன?") == "ta"
    assert detect_locale("what is nILam?") == "en"


def test_a_name_inside_a_string_is_not_a_use_of_it():
    stripped = engine.code_only('இறக்கு "nUlakam/paNam.qmz"; // பணம்\n')
    assert "paNam" not in stripped
    assert "இறக்கு" in stripped


def test_the_declaration_mistake_is_recognised_by_name():
    notes = engine._guidance("expected '=', found 'x'", "மாறி x = 5;", "en")
    assert any("not statement prefixes" in note for note in notes)


def test_guidance_needs_both_halves_to_match():
    """The same parse error without மாறி is a different mistake."""
    assert engine._guidance("expected '=', found 'x'", "செயல் f() {}", "en") == []


def test_guidance_speaks_the_answer_language():
    (note,) = engine._guidance("cannot open module 'x'", "", "ta")
    assert "ETAMIL_PATH" in note and "இறக்கு" in note


@needs_index
def test_a_named_symbol_is_answered_exactly(connection):
    reply = engine.answer("நீளம்", connection=connection)
    assert reply.intent == "symbol"
    assert reply.confidence == "exact"
    assert "length" in reply.text


@needs_index
def test_a_question_with_no_answer_says_so(connection):
    reply = engine.answer("zzzz qqqq wwww", connection=connection)
    assert reply.confidence == "none"
    assert reply.code is None


@needs_index
def test_broken_source_is_diagnosed_and_the_fix_named(connection):
    reply = engine.answer("why does this fail", source="மாறி x = 5;\n", connection=connection)
    assert reply.intent == "diagnose"
    assert "line 1, column 6" in reply.text
    assert "not statement prefixes" in reply.text


@needs_index
def test_source_that_compiles_is_not_reported_as_broken(connection):
    reply = engine.answer("why does this fail", source='அச்சு "hi";\n', connection=connection)
    assert reply.code_compiles


@needs_index
@pytest.mark.parametrize(
    "question",
    [
        "நீளம்",
        "how do I write a row to a CSV file",
        "how do I read a file",
        "வரி",
        "route with a path parameter",
        "how do I hash a password",
    ],
)
def test_no_answer_ever_carries_code_that_does_not_compile(connection, question):
    """The rule the whole design rests on.

    An assistant for a new language that emits code which does not compile
    teaches the mistake, and the developer blames the language.
    """
    reply = engine.answer(question, connection=connection)
    if reply.code is None:
        return
    assert reply.code_compiles
    assert oracle.check(reply.code).ok
