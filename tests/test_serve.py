"""The protocol, exercised over HTTP — including the parts that refuse."""

import pytest
from fastapi.testclient import TestClient

from paRY import config
from paRY.serve.app import MAX_SOURCE_BYTES, create_app

INDEX = config.DATA_DIR / "index" / "paRY.db"

needs_index = pytest.mark.skipif(
    not INDEX.exists() or config.etamil_bin() is None,
    reason="run python -m paRY.index.build, and build the compiler",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


@needs_index
def test_health_names_the_compiler_grading_the_answers(client):
    body = client.get("/health").json()
    assert body["compiler"].startswith("etamil")
    assert body["chunks"] > 1_000
    # Stated, not omitted: there is no model behind this yet.
    assert body["model"] is None


@needs_index
def test_ask_answers_a_tamil_question_in_tamil(client):
    body = client.post("/ask", json={"question": "நீளம்"}).json()
    assert body["intent"] == "symbol"
    assert body["locale"] == "ta"
    assert body["confidence"] == "exact"


@needs_index
def test_ask_honours_an_explicit_locale(client):
    body = client.post("/ask", json={"question": "நீளம்", "locale": "en"}).json()
    assert body["locale"] == "en"


@needs_index
def test_ask_diagnoses_the_source_it_is_given(client):
    body = client.post(
        "/ask", json={"question": "why does this fail", "source": "மாறி x = 5;\n"}
    ).json()
    assert body["intent"] == "diagnose"
    assert "not statement prefixes" in body["text"]


@needs_index
def test_no_answer_over_http_carries_code_that_does_not_compile(client):
    for question in ["நீளம்", "how do I write a row to a CSV file", "வரி"]:
        body = client.post("/ask", json={"question": question}).json()
        assert body["code"] is None or body["code_compiles"]


@needs_index
def test_diagnose_reports_the_position(client):
    body = client.post("/diagnose", json={"source": "மாறி x = 5;\n"}).json()
    assert body["ok"] is False
    assert body["diagnostics"][0]["line"] == 1
    assert body["diagnostics"][0]["column"] == 6


@needs_index
def test_diagnose_accepts_a_correct_program(client):
    body = client.post("/diagnose", json={"source": 'அச்சு "hi";\n'}).json()
    assert body["ok"] is True
    assert body["diagnostics"] == []


@needs_index
def test_search_ranks_the_symbol_above_prose(client):
    hits = client.get("/search", params={"q": "நீளம்", "limit": 3}).json()
    assert hits[0]["kind"] == "symbol"


@needs_index
def test_search_can_be_restricted_to_one_kind(client):
    hits = client.get("/search", params={"q": "வரி", "kind": ["example"]}).json()
    assert {hit["kind"] for hit in hits} <= {"example"}


def test_completion_refuses_rather_than_guessing(client):
    """An editor that inserts a wrong line teaches the wrong line."""
    response = client.post("/complete", json={"prefix": "செயல் f() {", "suffix": "}"})
    assert response.status_code == 501
    assert "Phase A" in response.json()["detail"]


def test_an_oversized_program_is_refused(client):
    response = client.post("/diagnose", json={"source": "அ" * MAX_SOURCE_BYTES})
    assert response.status_code == 413


def test_an_empty_question_is_a_validation_error(client):
    assert client.post("/ask", json={"question": ""}).status_code == 422


def test_the_web_client_is_served_by_the_server_it_talks_to(client):
    """`python -m paRY.serve` is the whole install — no npm, no second host."""
    page = client.get("/")
    assert page.status_code == 200
    assert "பறை" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_mounting_the_client_did_not_shadow_the_api(client):
    """The static mount is last and catches only what the API did not claim."""
    assert client.get("/health").status_code == 200
    assert client.get("/nope.js").status_code == 404
