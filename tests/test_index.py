"""Chunking, query building, and the tokenizer trap — none of which need the
eTamil tree to be readable."""

import sqlite3

import pytest

from paRY.index import search
from paRY.index.build import SCHEMA, TOKENIZE, _section_chunks


@pytest.fixture
def index() -> sqlite3.Connection:
    """A small index, built without going near the compiler."""
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    rows = [
        ("symbol", "நீளம் — builtin", None, None, None, "நீளம் — length of an array", "நீளம் nILam _length"),
        ("example", "nUlakam/paNam.qmz", "nUlakam/paNam.qmz", 1, 1, "செயல் வட்டி(எண் அசல்) { திரும்பு அசல்; }", "paNam"),
        ("doc_block", "manual.md:12", "manual.md", 12, 0, "மாறி x = 5;", ""),
        ("doc_section", "Server › Routes", "server.md", 40, None, "வழி routes take a :id path parameter", ""),
    ]
    for kind, title, path, line, compiles, body, names in rows:
        cursor = connection.execute(
            "INSERT INTO chunks (kind, title, repo, path, line, compiles, body, extra) "
            "VALUES (?, ?, 'eTamil', ?, ?, ?, ?, '{}')",
            (kind, title, path, line, compiles, body),
        )
        connection.execute(
            "INSERT INTO chunks_fts (rowid, names, title, body) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, names, title, body),
        )
    connection.commit()
    return connection


def test_the_index_tokenizer_keeps_a_tamil_word_whole():
    """SQLite's default splits செயல் into ச and யல, and then every Tamil word
    collides with every other one sharing a bare consonant."""
    connection = sqlite3.connect(":memory:")
    connection.execute(f'CREATE VIRTUAL TABLE t USING fts5(body, tokenize="{TOKENIZE}")')
    connection.execute("INSERT INTO t VALUES ('செயல் வருவாய்')")
    connection.execute("CREATE VIRTUAL TABLE v USING fts5vocab(t, row)")
    assert sorted(row[0] for row in connection.execute("SELECT term FROM v")) == [
        "செயல்",
        "வருவாய்",
    ]


def test_terms_keep_combining_marks_attached():
    # "of" and "an" are stop words now, matching coRpiri.qmz. What this test is
    # about survives that: நீளம் comes back whole, its combining marks still
    # attached, rather than split into நீ + ள + ம.
    assert search.terms("நீளம் of an array?") == ["நீளம்", "array"]


def test_a_lone_ascii_letter_is_not_a_term():
    assert search.terms("x = 5") == []


def test_a_lone_tamil_letter_is_a_term():
    assert search.terms("ஐ") == ["ஐ"]


def test_queries_narrow_before_they_widen():
    passes = search.queries("வரி கணக்கு")
    assert " AND " in passes[0]
    assert " OR " in passes[1]
    assert passes[-1].endswith(" *")


def test_a_quote_in_the_question_does_not_become_syntax(index):
    """The whole point of quoting: this is a question, not an FTS5 expression."""
    hits = search.search(index, 'இறக்கு "nUlakam/paNam.qmz"; AND OR NEAR(')
    assert isinstance(hits, list)


def test_an_empty_question_finds_nothing(index):
    assert search.search(index, "?! ...") == []


def test_a_name_outranks_prose_that_mentions_it(index):
    assert search.search(index, "நீளம்")[0].kind == "symbol"


def test_a_failing_example_is_retrieved_but_not_usable(index):
    (hit,) = [h for h in search.search(index, "மாறி") if h.kind == "doc_block"]
    assert hit.compiles is False
    assert not hit.is_usable_code


def test_code_with_no_verdict_is_not_treated_as_passing(index):
    hit = search.Hit("example", "t", None, None, None, 1.0, "", "")
    assert not hit.is_usable_code


def test_a_heading_path_travels_with_its_prose():
    chunks = _section_chunks("# Guide\n\nintro\n\n## Routes\n\nvழி takes :id\n")
    titles = [chunk["title"] for chunk in chunks]
    assert titles == ["Guide", "Guide › Routes"]


def test_a_long_section_is_split_but_keeps_its_title():
    body = "\n\n".join(["paragraph " * 40] * 6)
    chunks = _section_chunks(f"## Long\n\n{body}\n")
    assert len(chunks) > 1
    assert {chunk["title"] for chunk in chunks} == {"Long"}
