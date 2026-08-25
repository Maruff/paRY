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
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
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


def snapshot_path() -> Path:
    """Where the derived lexicon is kept for machines without the source tree."""
    return config.DATA_DIR / "lexicon.json"


def export(path: Path | None = None) -> Path:
    """Write the lexicon out, so a packaged paRY does not need `lexer.rs`.

    Derivation still happens here, from the compiler, at build time. What ships
    is the result — an installed copy on a developer's laptop has no eTamil
    repository to read, and the alternative would be a hand-kept list, which is
    the thing this module exists to avoid.
    """
    target = path or snapshot_path()
    names = load()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "source": str(config.ETAMIL_ROOT),
                "keywords": names.keywords,
                "builtins": names.builtins,
                "stdlib": names.stdlib,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


@lru_cache(maxsize=1)
def load() -> Lexicon:
    # A snapshot wins when the source tree is not there. It never wins over a
    # readable tree: on a development machine the compiler is the truth, and a
    # stale snapshot silently answering for it is exactly the drift this guards.
    lexer = config.ETAMIL_ROOT / "etamil_compiler" / "src" / "lexer.rs"
    if not lexer.exists() and snapshot_path().exists():
        stored = json.loads(snapshot_path().read_text(encoding="utf-8"))
        return Lexicon(
            keywords=stored["keywords"],
            builtins=stored["builtins"],
            stdlib=stored["stdlib"],
        )

    generator = _load_generator()
    try:
        keywords = generator.read_tokens()
        builtins = generator.read_builtins()
        stdlib = generator.read_stdlib()
    except SystemExit as failure:
        raise SystemExit(
            f"{failure}\n\n"
            "paRY reads the language out of the eTamil working tree, so a tree that is "
            "mid-edit stops it. `read_tokens` wants `#[regex(\"…\")] Variant,` on one "
            "line; rustfmt puts the attribute on its own line and the generator then "
            "finds nothing — which fails eTamil's own CI gate too, not just this. "
            "Check `git -C <eTamil> status` before assuming paRY is at fault."
        ) from failure

    return Lexicon(keywords=keywords, builtins=builtins, stdlib=stdlib)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Read the language out of the compiler.")
    parser.add_argument("--export", action="store_true", help="write data/lexicon.json for packaging")
    args = parser.parse_args()

    lexicon = load()
    print(f"keywords  {len(lexicon.keywords):>4} tokens in {len(lexicon.keyword_spellings)} spellings")
    print(f"builtins  {len(lexicon.builtins):>4} host functions")
    print(f"nUlakam   {len(lexicon.stdlib):>4} செயல் definitions")
    print(f"vocabulary{len(lexicon.vocabulary):>4} distinct names")
    if args.export:
        print(f"exported to {export()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
