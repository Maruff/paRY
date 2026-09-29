"""A small local model, kept on a short leash.

Phase A, and the leash is the point. Measured on a 4 GB box, free-form
generation of eTamil scored 2/6: a model this size cannot be the author of a
program in a language it has barely seen. What it can do is read the chunks
retrieval already found and say, in the user's own words, which one answers the
question and how to adapt it — and that is what it is asked to do here.

Three rules the rest of paRY already lives by, applied to the model:

  * It writes nothing the compiler has not accepted. `answer()` puts every
    program it produces through `etamil --check`, gives it one chance to fix
    what the compiler complained about, and drops the code entirely if the
    second attempt fails. The prose survives; the program does not. The editor
    will not offer an Insert button for code without a compile verdict, so a
    hallucinated program can be read and never inserted.

  * It is given the retrieved chunks and told to use them. It is not asked to
    recall eTamil, because it does not know eTamil.

  * It is optional. No Ollama, no model pulled, or a request that fails, and
    every function here returns None. paRY then answers exactly as it did
    before this module existed, which is the state it is developed in on a
    machine with no Ollama at all.

Nothing is sent anywhere. The same constraint that rules out a hosted model
rules out a hosted anything: `granite3.3:2b` is 1.5 GB on the same box that
serves the answer.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MODEL_URL = os.environ.get("PARY_MODEL_URL", "http://127.0.0.1:11434")
MODEL_NAME = os.environ.get("PARY_MODEL", "granite3.3:2b")

#: A key, when the endpoint is one that wants it.
#:
#: The default needs none and never will: it is Ollama on this machine, open
#: weights on hardware the project controls, and that is the point rather than
#: a stage on the way to something else. A key here is the user's own, for
#: their own endpoint, and paRY works fully without one.
MODEL_KEY = os.environ.get("PARY_MODEL_KEY", "")

#: What is in use now, which the environment only seeds.
#:
#: Mutable because the point is choosing: the editor asks for a different
#: model and the next answer uses it, rather than the server being restarted
#: with a different environment. One process serving one developer, so a
#: module-level choice is the whole of the state it needs -- if paRY ever
#: serves several people this has to become per-request instead.
_chosen: dict[str, str] = {"name": MODEL_NAME, "url": MODEL_URL, "key": MODEL_KEY}


def current() -> str:
    """The model answering questions right now."""
    return _chosen["name"]


def endpoint() -> str:
    """Where it is served from."""
    return _chosen["url"]


def choose(name: str, *, url: str | None = None, key: str | None = None) -> str:
    """Answer with a different model from the next question onward."""
    _chosen["name"] = name
    if url is not None:
        _chosen["url"] = url
    if key is not None:
        _chosen["key"] = key
    return _chosen["name"]


def catalogue() -> list[str]:
    """Every model the endpoint serves that can answer a question.

    The endpoint serves embedders too -- paRY uses one itself, for the index --
    and an embedder cannot answer anything. Offering one in a chooser is
    offering a choice that fails later and elsewhere, so they are filtered out
    here rather than explained afterwards.

    Ollama says which is which: /api/show reports capabilities, ['completion']
    against ['embedding']. An endpoint that will not answer /api/show is not
    assumed to be hiding embedders -- its models are all offered, because a
    chooser that lists nothing is worse than one that lists too much.

    Nothing at all is not an error either: an endpoint with no /api/tags is
    still usable, it just cannot offer a list.
    """
    try:
        request = urllib.request.Request(f"{endpoint()}/api/tags", headers=_headers())
        with urllib.request.urlopen(request, timeout=5) as response:
            tags = json.load(response)
    except Exception:
        return []

    names = sorted(e.get("name", "") for e in tags.get("models", []) if e.get("name"))
    return [name for name in names if _can_answer(name)]


def _can_answer(name: str) -> bool:
    """Can this model complete text, or does it only embed it?"""
    try:
        request = urllib.request.Request(
            f"{endpoint()}/api/show",
            data=json.dumps({"model": name}).encode("utf-8"),
            headers=_headers(),
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            shown = json.load(response)
    except Exception:
        # Asked and not told. Offer it: the endpoint may not be Ollama at all.
        return True
    capabilities = shown.get("capabilities")
    if not capabilities:
        return True
    return "completion" in capabilities


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if _chosen["key"]:
        headers["Authorization"] = f"Bearer {_chosen['key']}"
    return headers

#: Off unless asked for. A box that has not got the memory for a model should
#: not discover that fact by an editor request timing out.
ENABLED = os.environ.get("PARY_MODEL_ENABLED", "1") not in ("0", "false", "no")

#: Long enough for 2b on two shared vCPU, short enough that an editor waiting
#: on it gives up before the person does. A request that exceeds this is not an
#: error: the caller falls back to the retrieved answer, which is instant.
TIMEOUT = float(os.environ.get("PARY_MODEL_TIMEOUT", "90"))

#: An answer, not an essay — and on a CPU box the length *is* the wait.
#: Measured on the 4 GB droplet, granite3.3:2b at 11 tok/s reading its prompt
#: and 2.4 tok/s writing:
#:
#:   4 chunks x 1200 chars, 400 out   2057 prompt tokens   244 s
#:   2 chunks x  400 chars, 150 out    387 prompt tokens    35 s
#:   1 chunk  x  300 chars, 100 out    182 prompt tokens    22 s
#:
#: Reading the reference costs more than writing the answer, which is why the
#: generous version of this — hand it everything retrieval found and let it
#: choose — is the one that cannot be shipped. Two chunks is the compromise:
#: enough for the model to have something to adapt, small enough to answer
#: before the reader gives up.
MAX_TOKENS = 160

#: How many retrieved chunks the model is shown, and how much of each.
REFERENCE_CHUNKS = 2
REFERENCE_CHARS = 500

SYSTEM = """You are helping someone write eTamil, a programming language whose \
keywords are Tamil words. You do not know eTamil from memory and must not \
guess at it.

Everything you say about the language must come from the REFERENCE below. Use \
the function and keyword names exactly as they are spelled there. Never invent \
a name, and never translate one into English.

Answer in two parts:

1. Two or three sentences saying which reference entry answers the question \
and what to change in it. Plain prose, no code.
2. If, and only if, the reference contains a program you can adapt, a single \
fenced code block containing the whole adapted program. No comments, no \
ellipses, no placeholder names. If the reference has no program to adapt, \
write no code block at all.

Answer in English."""


def _post(path: str, payload: dict, timeout: float) -> dict | None:
    request = urllib.request.Request(
        f"{endpoint()}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        # Every failure here is the same failure as far as a caller is
        # concerned: there is no model, so answer without one.
        return None


def available() -> bool:
    """Is the configured model actually pulled and being served?"""
    if not ENABLED:
        return False
    try:
        request = urllib.request.Request(f"{endpoint()}/api/tags", headers=_headers())
        with urllib.request.urlopen(request, timeout=5) as response:
            tags = json.load(response)
    except Exception:
        return False
    names = {entry.get("name", "") for entry in tags.get("models", [])}
    # Ollama answers to `granite3.3:2b` whether or not the tag carries `:latest`.
    chosen = current()
    return any(name == chosen or name.startswith(f"{chosen}:") for name in names)


def reference(hits, limit: int = REFERENCE_CHUNKS) -> str:
    """The retrieved chunks, as the only thing the model is allowed to use."""
    parts = []
    for hit in hits[:limit]:
        where = f" ({hit.path})" if getattr(hit, "path", None) else ""
        parts.append(f"--- {hit.title}{where}\n{(hit.body or '').strip()[:1200]}")
    return "\n\n".join(parts)


def compose(question: str, hits, *, repair: str | None = None, previous: str | None = None, budget: float | None = None):
    """Ask for prose and, if the reference supports one, a program.

    Returns (text, code) with either part possibly None, or None if there is no
    model to ask. `repair` carries the compiler's complaint about `previous`,
    which is the second and last attempt.
    """
    body = f"REFERENCE:\n{reference(hits)}\n\nQUESTION: {question}"
    if repair and previous:
        body += (
            f"\n\nYour previous program did not compile. The eTamil compiler said:\n"
            f"{repair}\n\nHere is what you wrote:\n{previous}\n\n"
            f"Fix exactly that, using only names from the REFERENCE. "
            f"Reply with the corrected program in one fenced block."
        )

    reply = _post(
        "/api/chat",
        {
            "model": current(),
            "stream": False,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": body},
            ],
            "options": {"temperature": 0.1, "num_predict": MAX_TOKENS},
        },
        TIMEOUT if budget is None else max(1.0, min(TIMEOUT, budget)),
    )
    if reply is None:
        return None

    content = (reply.get("message") or {}).get("content", "").strip()
    if not content:
        return None
    return split_code(content)


def split_code(content: str) -> tuple[str, str | None]:
    """Separate the prose from the one fenced block, if there is one.

    Deliberately tolerant about the fence's language tag: the model is told to
    write ```, and writes ```etamil, ```qmz or ```tamil about as often.
    """
    if "```" not in content:
        return content.strip(), None

    before, _, rest = content.partition("```")
    block, _, after = rest.partition("```")
    if "\n" in block:
        first, _, remainder = block.partition("\n")
        # A language tag is one word; a first line with spaces is code.
        block = remainder if first.strip() and " " not in first.strip() else block

    code = block.strip()
    prose = f"{before.strip()}\n\n{after.strip()}".strip()
    return prose, (code or None)


# --------------------------------------------------------------- expansion --

EXPAND_SYSTEM = (
    "You turn a plain question into the technical terms a programmer or an "
    "accountant would use for it. Reply with three to six comma-separated "
    "terms and nothing else. No sentences, no explanation."
)

#: Short prompt, short answer, so this costs seconds rather than the minute a
#: composed answer takes. Measured on the 4 GB box: 2.4 to 3.7 seconds warm.
EXPAND_TOKENS = 40
EXPAND_TIMEOUT = 25.0

_expansions: dict[str, str | None] = {}


def expand_query(question: str) -> str | None:
    """The domain terms for a question, or None if there is no model.

    bm25 and a 384-dimension embedding both need the question and the document
    to share vocabulary. "How many must I sell before I stop losing money"
    shares none with சமநிலை_அலகுகள், whose doc says "break-even, in units", and
    no amount of documentation fixes a question phrased in different words.

    Expanding through the corpus was tried first and does not work here: only
    178 of 1,272 documentation chunks mention any stdlib name at all, and the
    prose and the library therefore cannot bridge to each other. The model is
    the only source of the connection that is not simply a list of answers
    written out by hand.

    Cached per process. The same question asked twice is common — a user
    rephrasing, a test suite — and the second one should be free.
    """
    if question in _expansions:
        return _expansions[question]

    reply = None
    if available():
        answer = _post(
            "/api/chat",
            {
                "model": current(),
                "stream": False,
                "messages": [
                    {"role": "system", "content": EXPAND_SYSTEM},
                    {"role": "user", "content": question},
                ],
                "options": {"temperature": 0.0, "num_predict": EXPAND_TOKENS},
            },
            EXPAND_TIMEOUT,
        )
        if answer is not None:
            content = (answer.get("message") or {}).get("content", "").strip()
            # A model that ignored the instruction and wrote a sentence is
            # worse than no expansion: it would flood the query with stopwords.
            if content and len(content) < 200 and chr(10) not in content:
                reply = content

    _expansions[question] = reply
    return reply
