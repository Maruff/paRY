"""The snapshot, which is what a packaged paRY reads instead of `lexer.rs`."""

import json

import pytest

from paRY import config, lexicon

SAMPLE = {
    "generated": "2026-08-25T00:00:00+00:00",
    "source": "somewhere else",
    "keywords": [{"token": "Print", "forms": ["அச்சு", "accu", "_print"], "section": "Control Flow"}],
    "builtins": [{"name": "நீளம்", "forms": ["நீளம்", "nILam"], "doc": "length", "arity": 1}],
    "stdlib": [
        {
            "name": "உள்ளதா",
            "forms": ["உள்ளதா"],
            "params": ["அணி", "மதிப்பு"],
            "doc": "membership",
            "module": "nUlakam/aNi.qmz",
            "line": 7,
        }
    ],
}


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "lexicon.json"
    path.write_text(json.dumps(SAMPLE, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(lexicon, "snapshot_path", lambda: path)
    lexicon.load.cache_clear()
    yield path
    lexicon.load.cache_clear()


def test_the_snapshot_answers_when_there_is_no_source_tree(snapshot, tmp_path, monkeypatch):
    """The packaged case: an installed paRY has a compiler but no repository."""
    monkeypatch.setattr(config, "ETAMIL_ROOT", tmp_path / "no-such-tree")

    names = lexicon.load()
    assert names.keyword_spellings == ["_print", "accu", "அச்சு"]
    assert names.builtin_names == ["nILam", "நீளம்"]
    assert names.stdlib_names == ["உள்ளதா"]


def test_a_readable_tree_beats_the_snapshot(snapshot):
    """On a development machine the compiler is the truth.

    A stale snapshot quietly answering for a compiler that has moved on is the
    drift this whole module exists to prevent, so the snapshot is a fallback
    and never a cache.
    """
    if not (config.ETAMIL_ROOT / "etamil_compiler" / "src" / "lexer.rs").exists():
        pytest.skip("no eTamil source tree here")

    names = lexicon.load()
    assert len(names.keywords) > 100  # the real thing, not the one-entry sample


def test_export_writes_what_load_reads(tmp_path, monkeypatch):
    if not (config.ETAMIL_ROOT / "etamil_compiler" / "src" / "lexer.rs").exists():
        pytest.skip("no eTamil source tree here")

    target = tmp_path / "exported.json"
    lexicon.export(target)
    stored = json.loads(target.read_text(encoding="utf-8"))

    assert set(stored) == {"generated", "source", "keywords", "builtins", "stdlib"}
    live = lexicon.load()
    assert len(stored["keywords"]) == len(live.keywords)
    assert len(stored["builtins"]) == len(live.builtins)
    assert len(stored["stdlib"]) == len(live.stdlib)
