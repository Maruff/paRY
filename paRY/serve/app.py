"""The paRY server — the one protocol all four clients speak.

Four endpoints, and they are the shapes from `docs/ARCHITECTURE.md` rather than
whatever each client happened to need:

    POST /ask        a question, and optionally the source the editor is showing
    POST /diagnose   source in, the compiler's diagnostics out, bilingually
    GET  /search     ranked corpus hits
    POST /complete   fill-in-the-middle — 501 until Phase A exists

`/complete` is declared and refuses rather than being absent, so a client can be
written against the whole protocol today and the editor integration does not
change shape when the model arrives.

**The handlers are synchronous on purpose.** Every one of them either spawns
the compiler or hits SQLite, both of which block; FastAPI runs a `def` handler
in a threadpool, which is the right place for blocking work. Declaring them
`async def` would run blocking calls on the event loop and stall every other
request behind the slowest compile.

This is meant to run inside the network that owns the code. It compiles what it
is sent — `--check` never executes a program, but it does read the modules an
import names — so it belongs behind the institution's own authentication, not
on the open internet.

    python -m paRY.serve --port 8900
"""

from __future__ import annotations

import os
import subprocess
from contextlib import closing
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__, config
from ..answer import engine, model as answer_model
from ..index import search
from ..verify import oracle

# A program bigger than this is not a question about a program. The compiler
# would cope; the point is to bound what one request can cost.
MAX_SOURCE_BYTES = 256 * 1024

# The web client, served by the server it talks to, so `python -m paRY.serve` is
# the whole install. Mounted last: it answers everything the API did not claim.
#
# PARY_WEB overrides the location because an installed copy is not laid out like
# the repository — the packaged server sets it to its own bundled `web/`.
WEB_ROOT = Path(os.environ["PARY_WEB"]) if os.environ.get("PARY_WEB") else config.REPO_ROOT / "web"


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)
    source: str | None = Field(default=None, description="what the editor is showing")
    locale: Literal["en", "ta"] | None = None


class CitationModel(BaseModel):
    title: str
    path: str | None
    line: int | None
    kind: str


class AnswerModel(BaseModel):
    intent: str
    locale: str
    text: str
    code: str | None
    code_compiles: bool
    citations: list[CitationModel]
    confidence: str


class DiagnoseRequest(BaseModel):
    source: str = Field(min_length=1)


class DiagnosticModel(BaseModel):
    line: int | None
    column: int | None
    message: str
    raw: str


class DiagnoseResponse(BaseModel):
    ok: bool
    timed_out: bool
    diagnostics: list[DiagnosticModel]


class HitModel(BaseModel):
    kind: str
    title: str
    path: str | None
    line: int | None
    compiles: bool | None
    score: float
    snippet: str


class CompleteRequest(BaseModel):
    prefix: str
    suffix: str = ""
    path: str | None = None


class Models(BaseModel):
    """What can answer, and what is answering."""

    current: str
    available: list[str]
    endpoint: str
    keyed: bool
    reachable: bool


class ChooseModel(BaseModel):
    name: str


class Health(BaseModel):
    version: str
    compiler: str | None
    index: str | None
    chunks: int | None
    model: str | None


def _models(available: list[str]) -> Models:
    """The model picture, built the same way wherever it is asked for."""
    return Models(
        current=answer_model.current(),
        available=available,
        endpoint=answer_model.endpoint(),
        keyed=bool(answer_model.MODEL_KEY),
        reachable=answer_model.available(),
    )


@lru_cache(maxsize=1)
def compiler_version() -> str | None:
    """Which compiler is grading answers, asked once."""
    binary = config.etamil_bin()
    if binary is None:
        return None
    try:
        completed = subprocess.run([str(binary), "-V"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return completed.stdout.decode("utf-8", errors="replace").strip() or None


def _check_size(source: str) -> None:
    if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail="source is larger than 256 kB")


def create_app(*, origins: tuple[str, ...] = ("http://localhost:5173",)) -> FastAPI:
    app = FastAPI(
        title="paRY",
        version=__version__,
        summary="பறை — an eTamil code assistant that never calls a hosted model",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins),
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.get("/health", response_model=Health)
    def health() -> Health:
        index_path = config.DATA_DIR / "index" / "paRY.db"
        chunks = None
        if index_path.exists():
            with closing(search.connect(index_path)) as connection:
                chunks = connection.execute("SELECT count(*) FROM chunks").fetchone()[0]
        return Health(
            version=__version__,
            compiler=compiler_version(),
            index=str(index_path) if index_path.exists() else None,
            chunks=chunks,
            # The model that would answer, when one is reachable. None says
            # there is none, which is a real answer rather than a silence:
            # every reply then comes from the compiler and the corpus alone.
            model=answer_model.current() if answer_model.available() else None,
        )

    @app.get("/models", response_model=Models)
    def models() -> Models:
        """What this endpoint serves, so an editor can offer a choice.

        `available` holds only models that can answer. The endpoint serves
        embedders too -- paRY uses one for the index -- and choosing one of
        those is choosing a failure that surfaces later, somewhere else.
        """
        return _models(answer_model.catalogue())

    @app.post("/models", response_model=Models)
    def choose_model(request: ChooseModel) -> Models:
        """Answer with a different model from the next question onward.

        A name this endpoint does not serve is refused here rather than
        accepted and discovered at the next question, by which time the editor
        has moved on and the failure looks like it came from nowhere.
        """
        offered = answer_model.catalogue()
        if offered and request.name not in offered:
            raise HTTPException(
                status_code=404,
                detail=f"{request.name} is not served here; {', '.join(offered)} are",
            )
        answer_model.choose(request.name)
        return _models(offered)

    @app.post("/ask", response_model=AnswerModel)
    def ask(request: AskRequest) -> AnswerModel:
        if request.source:
            _check_size(request.source)
        with closing(search.connect()) as connection:
            reply = engine.answer(
                request.question,
                source=request.source,
                locale=request.locale,
                connection=connection,
            )
        return AnswerModel(**reply.as_dict())

    @app.post("/diagnose", response_model=DiagnoseResponse)
    def diagnose(request: DiagnoseRequest) -> DiagnoseResponse:
        _check_size(request.source)
        if config.etamil_bin() is None:
            raise HTTPException(status_code=503, detail="the eTamil compiler is not built")
        result = oracle.check(request.source)
        return DiagnoseResponse(
            ok=result.ok,
            timed_out=result.timed_out,
            diagnostics=[DiagnosticModel(**vars(item)) for item in result.diagnostics],
        )

    @app.get("/search", response_model=list[HitModel])
    def search_corpus(
        q: str = Query(min_length=1, max_length=1_000),
        limit: int = Query(default=8, ge=1, le=50),
        kind: list[str] | None = Query(default=None),
    ) -> list[HitModel]:
        with closing(search.connect()) as connection:
            hits = search.search(connection, q, limit=limit, kinds=tuple(kind) if kind else None)
        return [
            HitModel(
                kind=hit.kind,
                title=hit.title,
                path=hit.path,
                line=hit.line,
                compiles=hit.compiles,
                score=hit.score,
                snippet=hit.snippet,
            )
            for hit in hits
        ]

    @app.post("/complete", status_code=501)
    def complete(request: CompleteRequest = Body()) -> dict:
        """Declared, and honest about not existing yet.

        Fill-in-the-middle needs the Phase A model. Answering with a plausible
        completion from retrieval would be worse than answering with nothing:
        an editor that inserts a wrong line teaches it.
        """
        raise HTTPException(
            status_code=501,
            detail="completion needs the Phase A model, which is not trained yet — "
                   "use /ask for questions and /diagnose for errors",
        )

    if WEB_ROOT.is_dir():
        app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="web")

    return app


app = create_app()
