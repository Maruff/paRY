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

from .. import lexicon
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


@dataclass(frozen=True)
class Guidance:
    """A mistake worth recognising by name, rather than only quoting the compiler."""

    error: re.Pattern | None
    source: re.Pattern | None
    en: str
    ta: str


# Three, each one paid for. The first is the mistake the brief singles out as
# easiest to make from reading the keyword list; the second cost a quarter of
# the documented examples in this repository's own first oracle run; the third
# is a statement the parser accepts and the VM refuses, so the compiler's own
# message arrives later than the question does.
GUIDANCE: tuple[Guidance, ...] = (
    Guidance(
        error=re.compile(r"expected '='"),
        source=re.compile(r"\b(மாறி|நிலை|mARi|nilY)\s"),
        en="`மாறி` and `நிலை` are tokens, but they are not statement prefixes. "
           "eTamil assigns with a bare name: `x = 5;`, not `மாறி x = 5;`.",
        ta="`மாறி`, `நிலை` ஆகியவை சொற்கள்தான், ஆனால் அறிவிப்பின் தொடக்கம் அல்ல. "
           "eTamil இல் பெயரை நேரடியாகவே எழுதுங்கள்: `x = 5;`, `மாறி x = 5;` அல்ல.",
    ),
    Guidance(
        error=re.compile(r"cannot open module"),
        source=None,
        en="An import resolves beside the importing file first, then along "
           "`ETAMIL_PATH`, then next to the compiler. Source typed into a chat "
           "has no file to sit beside, so give the path as it is written from "
           "the eTamil root and put that root on `ETAMIL_PATH`.",
        ta="`இறக்கு` முதலில் கோப்புக்கு அருகில், பிறகு `ETAMIL_PATH` வழியில், "
           "பிறகு தொகுப்பிக்கு அருகில் தேடும். உரையாடலில் எழுதிய நிரலுக்கு அருகில் "
           "கோப்பு இல்லை — எனவே eTamil வேரிலிருந்து பாதையைத் தந்து, அந்த வேரை "
           "`ETAMIL_PATH` இல் வையுங்கள்.",
    ),
    Guidance(
        error=None,
        source=re.compile(r"ஜேசான்_உரை"),
        en="`ஜேசான்_உரை` parses but the VM refuses it. Build the body with "
           "`ஜேசான்_ஆக்கு` and send it with `பதில்`.",
        ta="`ஜேசான்_உரை` பாகுபடும், ஆனால் VM அதை ஏற்காது. `ஜேசான்_ஆக்கு` கொண்டு "
           "உடலை உருவாக்கி, `பதில்` கொண்டு அனுப்புங்கள்.",
    ),
)


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


def _guidance(error: str, source: str, locale: str) -> list[str]:
    notes = []
    for rule in GUIDANCE:
        if rule.error and not rule.error.search(error):
            continue
        if rule.source and not rule.source.search(source):
            continue
        if rule.error is None and rule.source is None:
            continue
        notes.append(rule.ta if locale == "ta" else rule.en)
    return notes


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
    notes = _guidance(result.first_error, source, locale)
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
        code = usable.body
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


def _howto(question: str, connection: sqlite3.Connection, locale: str) -> Answer:
    hits = search.search(connection, question, limit=8)
    if not hits:
        return Answer(intent="howto", locale=locale, text=say("nothing", locale))

    lines: list[str] = []
    prose = [hit for hit in hits if hit.kind in ("doc_section", "symbol")]
    if prose:
        best = prose[0]
        lines += [f"### {say('from_docs', locale)}", "", f"**{best.title}**", "", best.body.strip()]

    usable = _usable_code(hits)
    code = None
    if usable:
        code = usable.body
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

    named = _named_symbol(question, table)
    if named:
        return _symbol(named, connection, locale)

    return _howto(question, connection, locale)


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
