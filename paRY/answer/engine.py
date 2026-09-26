"""Answering a question without a model.

Four intents, decided by rules over the question text and whatever source the
editor sent along. Each one is exact where a small model would guess:

    diagnose   there is source and it does not compile — the compiler says why,
               in both languages, with the line and column
    symbol     the question names a keyword, builtin or nUlakam function — the
               answer comes from the compiler's own tables
    explain    there is source and the question asks what it does — every name
               it uses, with what each one is
    howto      everything else — retrieval over the documentation and the
               verified examples

The rule this module is built around: **no code goes out that has not been
compiled.** An example is quoted only when the oracle has said it compiles, and
a long one is cited rather than pasted, because a truncated program that no
longer compiles is exactly the thing that must not happen. When nothing
answers, paRY says so instead of composing something plausible.

    python -m paRY.answer "how do I read a file"
    python -m paRY.answer "why does this fail" --source broken.qmz
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import knowledge, lexicon
from ..index import search
from ..verify import oracle
from .phrases import detect_locale, say

# Inline a program only if it is short enough to read in an answer. Anything
# longer is cited: cutting a program in half produces something that does not
# compile, which is the one thing an answer must never contain.
MAX_INLINE_LINES = 40

ASKS_WHY = re.compile(
    r"\b(why|error|fail|broken|wrong|fix)\b|ஏன்|பிழை|தவற|சரிசெய்", re.IGNORECASE
)
ASKS_EXPLAIN = re.compile(
    r"\b(explain|what does|what is this|walk me)\b|என்ன செய்|விளக்க", re.IGNORECASE
)


@dataclass(frozen=True)
class Citation:
    title: str
    path: str | None
    line: int | None
    kind: str


@dataclass(frozen=True)
class Answer:
    intent: str
    locale: str
    text: str
    code: str | None = None
    code_compiles: bool = False
    citations: list[Citation] = field(default_factory=list)
    confidence: str = "none"

    def as_dict(self) -> dict:
        return asdict(self)


def _guidance(error: str, source: str, locale: str, table: dict[str, dict]) -> list[str]:
    """Named mistakes, plus one paRY works out for itself.

    The rules come from `knowledge/guidance.json` — adding one is editing a
    file. The computed one is worth more than any of them: when the parser
    refuses a name, ask the compiler's own tables whether that name is a
    keyword, because "expected a statement, found 'உடல்'" means nothing until
    you know உடல் is the Body keyword and cannot be a variable.
    """
    notes = [rule.text(locale) for rule in knowledge.load_guidance() if rule.matches(error, source)]

    refused = re.search(r"found '([^']+)'", error)
    if refused:
        entry = table.get(refused.group(1))
        if entry:
            name = refused.group(1)
            sort = entry["sort"]
            where = entry.get("section") or entry.get("module") or ""
            notes.append(
                f"`{name}` is a {sort}{f' in the {where} group' if where else ''}, "
                "so it cannot be used as a name. Choose another."
                if locale != "ta"
                else f"`{name}` என்பது ஒரு {sort} — எனவே அதைப் பெயராகப் "
                "பயன்படுத்த முடியாது. வேறு பெயரைத் தேர்வு செய்யுங்கள்."
            )
    return notes


def _symbol_table() -> dict[str, dict]:
    """Every accepted spelling to the thing it names."""
    names = lexicon.load()
    table: dict[str, dict] = {}
    for entry in names.keywords:
        for form in entry["forms"]:
            table.setdefault(form, {"sort": "keyword", **entry})
    for entry in names.builtins:
        for form in entry["forms"]:
            table.setdefault(form, {"sort": "builtin", **entry})
    for entry in names.stdlib:
        for form in entry["forms"]:
            table.setdefault(form, {"sort": "nUlakam", **entry})
    return table


def _named_symbol(question: str, table: dict[str, dict]) -> dict | None:
    """The longest accepted name the question mentions, if any."""
    found = [word for word in search.terms(question) if word in table]
    if not found:
        return None
    return table[max(found, key=len)]


def _usable_code(hits: list[search.Hit]) -> search.Hit | None:
    """The best hit that is code, compiles, and is short enough to quote."""
    for hit in hits:
        if hit.is_usable_code and hit.body.count("\n") <= MAX_INLINE_LINES:
            return hit
    return None


def _cite(hit: search.Hit) -> Citation:
    return Citation(title=hit.title, path=hit.path, line=hit.line, kind=hit.kind)


def _diagnose(source: str, locale: str) -> Answer:
    result = oracle.check(source)
    if result.ok:
        return Answer(
            intent="diagnose",
            locale=locale,
            text=say("it_compiles", locale),
            code=source,
            code_compiles=True,
            confidence="exact",
        )

    lines = [f"### {say('why_not_compile', locale)}", ""]
    for diagnostic in result.diagnostics:
        lines.append(f"- {diagnostic.raw}")
    notes = _guidance(result.first_error, source, locale, _symbol_table())
    if notes:
        lines += ["", f"### {say('the_fix', locale)}", ""]
        lines += [f"- {note}" for note in notes]

    return Answer(
        intent="diagnose",
        locale=locale,
        text="\n".join(lines),
        confidence="exact",
    )


def _symbol(entry: dict, connection: sqlite3.Connection, locale: str) -> Answer:
    name = entry.get("name") or entry["forms"][0]
    lines = [f"### {name} — {entry['sort']}", ""]

    if entry.get("doc"):
        lines.append(entry["doc"])
    elif entry["sort"] == "keyword":
        lines.append(f"{say('definition', locale)}: {entry['section']}.")
    if entry.get("params"):
        lines.append("")
        lines.append(f"`{name}({', '.join(entry['params'])})`")
    if entry.get("module"):
        lines.append("")
        lines.append(f'{say("defined_in", locale)}: `{entry["module"]}` — '
                     f'`இறக்கு "{entry["module"]}";`')
    lines.append("")
    lines.append(f"{say('spellings', locale)}: {', '.join(f'`{form}`' for form in entry['forms'])}")

    hits = search.search(connection, name, limit=6, kinds=("example", "doc_block"))
    citations = [_cite(hit) for hit in hits[:3]]
    usable = _usable_code(hits)
    code = None
    if usable:
        code = usable.code
        lines += ["", f"### {say('used_in', locale)}", "", f"`{usable.title}` ✓ {say('compiles', locale)}"]

    return Answer(
        intent="symbol",
        locale=locale,
        text="\n".join(lines),
        code=code,
        code_compiles=bool(usable),
        citations=citations,
        confidence="exact",
    )


STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
COMMENT = re.compile(r"//[^\n]*")


def code_only(source: str) -> str:
    """Source with string literals and comments blanked out.

    `இறக்கு "nUlakam/paNam.qmz";` contains `paNam`, which is a real spelling of
    the keyword `பணம்` — but it is a filename here, not a use of the keyword.
    """
    return COMMENT.sub(" ", STRING.sub(' "" ', source))


def _explain(source: str, table: dict[str, dict], locale: str) -> Answer:
    used: list[dict] = []
    seen: set[str] = set()
    for word in search.terms(code_only(source)):
        entry = table.get(word)
        if entry and word not in seen:
            seen.add(word)
            used.append(entry)

    result = oracle.check(source)
    lines = [f"### {say('uses', locale)}", ""]
    for entry in used[:20]:
        name = entry.get("name") or entry["forms"][0]
        doc = entry.get("doc") or entry.get("section", "")
        lines.append(f"- `{name}` — {doc}")
    if not used:
        return Answer(intent="explain", locale=locale, text=say("nothing", locale))

    return Answer(
        intent="explain",
        locale=locale,
        text="\n".join(lines),
        code=source if result.ok else None,
        code_compiles=result.ok,
        confidence="exact",
    )


def _recipe(hit: search.Hit, locale: str) -> Answer:
    """A taught task: the explanation, then the program, which compiles.

    The chunk's body is the explanation and the code separated by a blank line,
    which is how the index stored it. `code_compiles` is not a guess: a recipe
    that stops compiling is refused at index time and never becomes a chunk.
    """
    explanation, _, code = hit.body.partition("\n\n")
    return Answer(
        intent="recipe",
        locale=locale,
        text=f"### {hit.title}\n\n{explanation.strip()}",
        code=code.strip() + "\n" if code.strip() else None,
        code_compiles=bool(code.strip()),
        citations=[_cite(hit)],
        confidence="exact",
    )



# A recipe answers one taught task, so returning it as `confidence="exact"` is
# only honest when the question really is that task.
#
# Ten short recipes compete against thousands of longer chunks under bm25,
# which normalises by document length, so a recipe reaching rank one says
# little by itself. What separates a real match is that nothing else comes
# close. Measured against the real index, with the four questions the test
# suite fixes as recipe questions and four that are not:
#
#   CSV கோப்பில் எழுது                 30.07   next  0.00
#   how do I return json               28.42   next  0.00
#   how do I define a function         35.46   next  0.00
#   how do I write a row to a CSV file 42.98   next  0.00
#
#   how do I read a file line by line  30.06   next 25.88
#   how do I reverse an array          22.73   next 19.39
#   how do I connect to postgres       15.09   next 13.12
#
# Note that the absolute scores overlap — a true match at 28.42 scores below a
# false one at 30.06 — so an absolute floor cannot separate them, and one tried
# here rejected two questions the suite requires. bm25 sums over the query's
# terms, so its scale moves with the question and only the *ratio* is
# comparable between questions. A true match has no runner-up at all; a false
# one is never more than 1.3x ahead.
#
# A recipe that fails this is not discarded: the question falls through to the
# retrieved answer, which says `retrieved` and cites what it found. A wrong
# answer admitting uncertainty can be recovered from; a wrong answer claiming
# certainty cannot.
RECIPE_LEAD = 2.0


def _recipe_is_the_question(hits: list[search.Hit]) -> bool:
    """Is the top recipe convincingly what was asked, rather than merely first?

    Compares bm25 scores specifically, not `score`, which becomes a fused rank
    once semantic retrieval is in play. The ratio below was calibrated against
    bm25 and means nothing on any other scale; and a chunk the embeddings alone
    found has no bm25 score at all, so counting it as a runner-up of zero would
    read as "nothing else came close" — the exact opposite of the truth.
    """
    top = hits[0]
    rivals = [hit.lexical for hit in hits[1:] if hit.lexical > 0.0]
    runner_up = max(rivals) if rivals else 0.0
    return runner_up <= 0.0 or top.lexical >= RECIPE_LEAD * runner_up


def _howto(
    question: str,
    connection: sqlite3.Connection,
    locale: str,
    hits: list[search.Hit] | None = None,
) -> Answer:
    hits = hits if hits is not None else search.search(connection, question, limit=8)
    if not hits:
        return Answer(intent="howto", locale=locale, text=say("nothing", locale))

    if hits[0].kind == "recipe" and _recipe_is_the_question(hits):
        return _recipe(hits[0], locale)

    lines: list[str] = []
    # Reaching here with a recipe on top means the dominance test just decided
    # that recipe is not what was asked. Quoting it anyway as the best thing
    # found contradicts the decision in the same breath — "how do I connect to
    # postgres" answered with the CSV recipe, only now labelled `retrieved`.
    # Prefer anything else; fall back to it only when there is nothing else.
    kinds = ("doc_section", "symbol", "recipe")
    prose = [hit for hit in hits if hit.kind in kinds and hit.kind != "recipe"]
    if not prose:
        prose = [hit for hit in hits if hit.kind in kinds]
    if prose:
        best = prose[0]
        lines += [f"### {say('from_docs', locale)}", "", f"**{best.title}**", "", best.body.strip()]

    usable = _usable_code(hits)
    code = None
    if usable:
        code = usable.code
        lines += ["", f"### {say('example', locale)}", "", f"`{usable.title}` ✓ {say('compiles', locale)}"]

    return Answer(
        intent="howto",
        locale=locale,
        text="\n".join(lines) if lines else say("nothing", locale),
        code=code,
        code_compiles=bool(usable),
        citations=[_cite(hit) for hit in hits[:4]],
        confidence="retrieved",
    )


def answer(
    question: str,
    *,
    source: str | None = None,
    locale: str | None = None,
    connection: sqlite3.Connection | None = None,
) -> Answer:
    """Route a question to the thing that can answer it exactly, then retrieval."""
    locale = locale or detect_locale(question)
    connection = connection or search.connect()
    table = _symbol_table()

    if source and source.strip():
        if ASKS_WHY.search(question) or not oracle.check(source).ok:
            return _diagnose(source, locale)
        if ASKS_EXPLAIN.search(question):
            return _explain(source, table, locale)

    # One search, then routing on what actually came back. A recipe was written
    # to answer a question in the words someone asks it, so when one is the best
    # hit it beats naming a keyword: "CSV கோப்பில் எழுது" mentions எழுது, but
    # the person is asking how to write a row, not what a keyword is.
    hits = search.search(connection, question, limit=8)
    if hits and hits[0].kind == "recipe" and _recipe_is_the_question(hits):
        return _recipe(hits[0], locale)

    named = _named_symbol(question, table)
    if named:
        return _symbol(named, connection, locale)

    return _howto(question, connection, locale, hits)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ask paRY a question.")
    parser.add_argument("question", nargs="+")
    parser.add_argument("--source", type=Path, help="the file the editor is showing")
    parser.add_argument("--locale", choices=("en", "ta"))
    args = parser.parse_args(argv)

    reply = answer(
        " ".join(args.question),
        source=args.source.read_text(encoding="utf-8") if args.source else None,
        locale=args.locale,
    )

    print(f"[{reply.intent} · {reply.confidence} · {reply.locale}]\n")
    print(reply.text)
    if reply.code:
        print(f"\n```etamil\n{reply.code.rstrip()}\n```")
    if reply.citations:
        print()
        for citation in reply.citations:
            where = f"{citation.path}:{citation.line}" if citation.path else citation.title
            print(f"  — {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
