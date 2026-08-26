"""What paRY has been taught, as files rather than code.

Two kinds, and between them they are how paRY is educated without training
anything:

**Recipes** (`knowledge/recipes/*.toml`) are task-shaped. The corpus has 77
programs with names like `vatti.qmz`, and not one document that says "how do I
write a row to a CSV file" — so that question found nothing, because retrieval
can only match words that are present. A recipe carries the question in the
words a developer would use, in both languages, next to a program that answers
it. Every recipe is compiled before it is indexed.

**Guidance** (`knowledge/guidance.json`) is mistake-shaped: a compiler message
and a shape in the source, and the sentence that explains what to do. The
compiler says `expected '='`; the guidance says `மாறி` is a token but not a
statement prefix. That is the difference between a diagnostic and an answer.

Adding either is editing a file. Nothing needs to be rebuilt except the index.

    python -m paRY.knowledge            # list, and compile every recipe
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from . import config

KNOWLEDGE = config.REPO_ROOT / "knowledge"
RECIPES = KNOWLEDGE / "recipes"
GUIDANCE = KNOWLEDGE / "guidance.json"


@dataclass(frozen=True)
class Recipe:
    """One task, in the words someone would ask for it, and code that does it."""

    id: str
    title: str
    tamil: str
    tags: list[str]
    asks: list[str]
    explain: str
    code: str

    @property
    def searchable(self) -> str:
        """Everything a question might match on, for the index's name column."""
        return " ".join([self.title, self.tamil, *self.asks, *self.tags])


@dataclass(frozen=True)
class Rule:
    """A mistake worth recognising by name."""

    id: str
    error: re.Pattern | None
    source: re.Pattern | None
    en: str
    ta: str

    def matches(self, error: str, source: str) -> bool:
        # A rule with neither condition would fire on everything; refuse it at
        # load time rather than let it answer every question.
        if self.error and not self.error.search(error):
            return False
        if self.source and not self.source.search(source):
            return False
        return True

    def text(self, locale: str) -> str:
        return self.ta if locale == "ta" else self.en


def load_recipes(folder: Path | None = None) -> list[Recipe]:
    directory = folder or RECIPES
    if not directory.is_dir():
        return []

    recipes: list[Recipe] = []
    for path in sorted(directory.glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        missing = {"title", "asks", "code"} - set(data)
        if missing:
            raise SystemExit(f"{path.name}: missing {', '.join(sorted(missing))}")
        recipes.append(
            Recipe(
                id=path.stem,
                title=data["title"],
                tamil=data.get("tamil", ""),
                tags=list(data.get("tags", [])),
                asks=list(data["asks"]),
                explain=data.get("explain", "").strip(),
                code=data["code"].strip() + "\n",
            )
        )
    return recipes


def load_guidance(path: Path | None = None) -> list[Rule]:
    source = path or GUIDANCE
    if not source.exists():
        return []

    rules: list[Rule] = []
    for entry in json.loads(source.read_text(encoding="utf-8")):
        when = entry.get("when", {})
        if not when.get("error") and not when.get("source"):
            raise SystemExit(
                f"guidance '{entry.get('id')}' has no condition — it would answer everything"
            )
        rules.append(
            Rule(
                id=entry["id"],
                error=re.compile(when["error"]) if when.get("error") else None,
                source=re.compile(when["source"]) if when.get("source") else None,
                en=entry["en"],
                ta=entry.get("ta", entry["en"]),
            )
        )
    return rules


def verify(recipes: list[Recipe] | None = None) -> list[tuple[Recipe, bool, str]]:
    """Compile every recipe. A recipe that does not compile is not knowledge."""
    from .verify import oracle

    results = []
    for recipe in recipes if recipes is not None else load_recipes():
        outcome = oracle.check(recipe.code)
        results.append((recipe, outcome.ok, outcome.first_error))
    return results


def main() -> int:
    recipes = load_recipes()
    rules = load_guidance()
    print(f"{len(recipes)} recipes, {len(rules)} guidance rules")

    if not recipes:
        return 0

    failures = 0
    for recipe, ok, error in verify(recipes):
        mark = "ok  " if ok else "FAIL"
        print(f"  {mark} {recipe.id:<24} {recipe.title}")
        if not ok:
            failures += 1
            print(f"       {error}")

    if failures:
        print(f"\n{failures} recipe(s) do not compile — they must not be indexed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
