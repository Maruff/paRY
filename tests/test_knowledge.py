"""What paRY has been taught — and the promise that it compiles."""

import json

import pytest

from paRY import config, knowledge
from paRY.answer import engine
from paRY.index import search
from paRY.verify import oracle

INDEX = config.DATA_DIR / "index" / "paRY.db"

needs_compiler = pytest.mark.skipif(
    config.etamil_bin() is None, reason="the eTamil compiler is not built"
)
needs_index = pytest.mark.skipif(
    not INDEX.exists() or config.etamil_bin() is None, reason="run python -m paRY.index.build"
)


@pytest.fixture(scope="module")
def connection():
    return search.connect(INDEX)


def test_there_are_recipes_and_rules():
    assert len(knowledge.load_recipes()) >= 10
    assert len(knowledge.load_guidance()) >= 5


@needs_compiler
@pytest.mark.parametrize("recipe", knowledge.load_recipes(), ids=lambda r: r.id)
def test_every_recipe_compiles(recipe):
    """A recipe that does not compile is not knowledge, it is a rumour."""
    result = oracle.check(recipe.code)
    assert result.ok, f"{recipe.id}: {result.first_error}"


@pytest.mark.parametrize("recipe", knowledge.load_recipes(), ids=lambda r: r.id)
def test_every_recipe_is_askable_in_more_than_one_language(recipe):
    """The point of a recipe is the wording, so one phrasing is not enough."""
    assert len(recipe.asks) >= 3
    assert any(not ask.isascii() for ask in recipe.asks), "no Tamil phrasing"
    assert any(ask.isascii() for ask in recipe.asks), "no English phrasing"
    assert recipe.explain, "a recipe with no explanation is just a file"


def test_a_rule_with_no_condition_is_refused(tmp_path):
    """It would fire on every question ever asked."""
    path = tmp_path / "guidance.json"
    path.write_text(json.dumps([{"id": "always", "when": {}, "en": "x"}]), encoding="utf-8")
    with pytest.raises(SystemExit):
        knowledge.load_guidance(path)


def test_a_rule_needs_both_halves_when_it_states_both():
    (rule,) = [r for r in knowledge.load_guidance() if r.id == "declaration-prefix"]
    assert rule.matches("expected '=', found 'x'", "மாறி x = 5;")
    assert not rule.matches("expected '=', found 'x'", "செயல் f() {}")


def test_spellings_expand_across_the_three_scripts():
    """`accu` and `அச்சு` are one word to the compiler, so one question finds
    documents written in the other."""
    assert "அச்சு" in search.expand(["accu"])
    assert "accu" in search.expand(["அச்சு"])
    # A name with an English alias expands to all three.
    assert set(search.expand(["_length"])) >= {"_length", "nILam", "நீளம்"}


def test_expansion_leaves_ordinary_words_alone():
    assert search.expand(["csv", "file"]) == ["csv", "file"]


@needs_index
@pytest.mark.parametrize(
    "question",
    [
        "how do I write a row to a CSV file",
        "CSV கோப்பில் எழுது",
        "how do I return json",
        "how do I define a function",
    ],
)
def test_a_task_question_is_answered_by_a_recipe(connection, question):
    reply = engine.answer(question, connection=connection)
    assert reply.intent == "recipe"
    assert reply.code_compiles
    assert oracle.check(reply.code).ok


@needs_index
def test_naming_a_symbol_still_answers_with_the_symbol(connection):
    """A task question routes to a recipe; a name still routes to the name."""
    assert engine.answer("நீளம்", connection=connection).intent == "symbol"
    assert engine.answer("nILam", connection=connection).intent == "symbol"


@needs_index
def test_a_keyword_used_as_a_name_is_explained(connection):
    """`உடல்` is the Body keyword. The compiler says "found 'உடல்'" and stops."""
    reply = engine.answer(
        "why does this fail",
        source='வழி பெறு, "/x" {\n    உடல் = 1;\n}\n',
        connection=connection,
    )
    assert reply.intent == "diagnose"
    assert "உடல்" in reply.text
    assert "keyword" in reply.text or "cannot be used as a name" in reply.text
