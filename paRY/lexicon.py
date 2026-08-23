"""What the language actually contains, read out of the compiler.

Every keyword spelling, every host builtin and every nUlakam function, taken
from `lexer.rs`, `interpreter.rs` and `nUlakam/*.qmz` — by importing the
generator the eTamil repository already keeps green in CI
(`scripts/generate_editor_support.py`), not by re-parsing the Rust here.

The point is drift. A second hand-kept keyword list is exactly what went wrong
in the VS Code extension, where 67 of 201 keywords were missing and 28 romanized
spellings were from a scheme the compiler had stopped accepting. A tokenizer or
a retrieval index built on a stale list makes the same mistake more quietly.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType

from . import config


@dataclass(frozen=True)
class Lexicon:
    """Every name the language answers to."""

    keywords: list[dict] = field(default_factory=list)
    builtins: list[dict] = field(default_factory=list)
    stdlib: list[dict] = field(default_factory=list)

    @property
    def keyword_spellings(self) -> list[str]:
        """All spellings of all keywords — Tamil script, romanized and English."""
        return sorted({form for entry in self.keywords for form in entry["forms"]})

    @property
    def builtin_names(self) -> list[str]:
        return sorted({form for entry in self.builtins for form in entry["forms"]})

    @property
    def stdlib_names(self) -> list[str]:
        return sorted({entry["name"] for entry in self.stdlib})

    @property
    def vocabulary(self) -> list[str]:
        """Everything a completion could legitimately emit as a bare word."""
        return sorted(set(self.keyword_spellings) | set(self.builtin_names) | set(self.stdlib_names))


def _load_generator() -> ModuleType:
    path = config.require(
        config.ETAMIL_ROOT / "scripts" / "generate_editor_support.py",
        "the eTamil editor-support generator",
    )
    spec = importlib.util.spec_from_file_location("etamil_editor_support", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=1)
def load() -> Lexicon:
    generator = _load_generator()
    return Lexicon(
        keywords=generator.read_tokens(),
        builtins=generator.read_builtins(),
        stdlib=generator.read_stdlib(),
    )


def main() -> int:
    lexicon = load()
    print(f"keywords  {len(lexicon.keywords):>4} tokens in {len(lexicon.keyword_spellings)} spellings")
    print(f"builtins  {len(lexicon.builtins):>4} host functions")
    print(f"nUlakam   {len(lexicon.stdlib):>4} செயல் definitions")
    print(f"vocabulary{len(lexicon.vocabulary):>4} distinct names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
