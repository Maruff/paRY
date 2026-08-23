"""The compiler, used as a judge.

`etamil --check` lexes, parses and type checks without running anything, so a
candidate sample can be graded without executing code that might write a file
or open a socket. It answers on the exit code and prints its diagnostics
bilingually:

    ✗ வரி 1, நெடுவரிசை 6: '=' எதிர்பார்க்கப்பட்டது, 'x' கிடைத்தது
      (line 1, column 6: expected '=', found 'x')

This is the free oracle the corpus plan depends on. Generated eTamil is worth
nothing unless something says it is correct, and nothing else can say so.

Two limits, both measured rather than assumed:

* `--check` stops after type checking. `அச்சு y;` with `y` never assigned
  passes. Compiling is a floor on correctness, not a ceiling — a sample that
  must also produce a particular answer has to be run.
* One process per sample. That is fine for the hundreds of documented examples
  here and much too slow for the hundreds of millions of synthetic tokens the
  plan calls for; that scale needs a batch mode inside the compiler.

    python -m paRY.verify.oracle --blocks
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .. import config
from ..corpus.collect import read_jsonl

# The English half of a diagnostic, which is the half that carries the position.
POSITION = re.compile(r"\(line (?P<line>\d+), column (?P<column>\d+): (?P<message>.+?)\)\s*$")


@dataclass(frozen=True)
class Diagnostic:
    line: int | None
    column: int | None
    message: str
    raw: str


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    exit_code: int
    diagnostics: list[Diagnostic] = field(default_factory=list)
    timed_out: bool = False

    @property
    def first_error(self) -> str:
        return self.diagnostics[0].message if self.diagnostics else ""


def parse_diagnostics(output: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith(("✗", "error", "Error")):
            continue
        position = POSITION.search(stripped)
        if position:
            diagnostics.append(
                Diagnostic(
                    line=int(position.group("line")),
                    column=int(position.group("column")),
                    message=position.group("message"),
                    raw=stripped,
                )
            )
        else:
            diagnostics.append(Diagnostic(line=None, column=None, message=stripped, raw=stripped))
    return diagnostics


def _environment() -> dict[str, str]:
    """The compiler's environment, with the standard library reachable.

    A sample arriving on stdin has no file to be beside, so `இறக்கு
    "nUlakam/paNam.qmz";` cannot resolve the way it would in the repository.
    Putting the eTamil root on `ETAMIL_PATH` restores that, and without it a
    quarter of the documented examples fail for a reason that has nothing to do
    with the code being wrong.
    """
    environment = dict(os.environ)
    existing = environment.get("ETAMIL_PATH")
    root = str(config.ETAMIL_ROOT)
    environment["ETAMIL_PATH"] = f"{root}{os.pathsep}{existing}" if existing else root
    return environment


def check(source: str, *, timeout: float = 15.0, binary: Path | None = None) -> CheckResult:
    """Lex, parse and type check one program. Nothing is executed."""
    exe = binary or config.etamil_bin()
    if exe is None:
        raise SystemExit(
            "the eTamil compiler is not built — run `cargo build --release` in "
            "etamil_compiler/, or set ETAMIL_BIN"
        )
    try:
        completed = subprocess.run(
            [str(exe), "--check"],
            input=source.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=_environment(),
        )
    except subprocess.TimeoutExpired:
        return CheckResult(ok=False, exit_code=-1, timed_out=True)

    output = (completed.stdout + completed.stderr).decode("utf-8", errors="replace")
    return CheckResult(
        ok=completed.returncode == 0,
        exit_code=completed.returncode,
        diagnostics=parse_diagnostics(output),
    )


def check_many(sources: list[str], *, workers: int | None = None, timeout: float = 15.0) -> list[CheckResult]:
    """The same check over many samples, one process each, run in parallel."""
    exe = config.etamil_bin()
    count = workers or min(8, (os.cpu_count() or 2))
    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(lambda source: check(source, timeout=timeout, binary=exe), sources))


def check_blocks(corpus_dir: Path) -> dict:
    """Every fenced block the documentation tags as eTamil, against the compiler.

    A documented example that no longer compiles is both a documentation bug and
    a sample that must not be trained on, so this is worth knowing before either
    use of the corpus.
    """
    blocks = [block for block in read_jsonl(corpus_dir / "blocks.jsonl") if block["is_etamil"]]
    results = check_many([block["text"] for block in blocks])

    graded = [
        {
            "id": block["id"],
            "path": block["path"],
            "line": block["line"],
            "lines": block["lines"],
            "ok": result.ok,
            "timed_out": result.timed_out,
            "error": result.first_error,
            "error_line": result.diagnostics[0].line if result.diagnostics else None,
        }
        for block, result in zip(blocks, results)
    ]
    passing = [entry for entry in graded if entry["ok"]]

    reasons: dict[str, int] = {}
    for entry in graded:
        if not entry["ok"]:
            reasons[entry["error"] or "(no diagnostic)"] = reasons.get(entry["error"] or "(no diagnostic)", 0) + 1

    return {
        "checked": len(graded),
        "compiles": len(passing),
        "rate": round(len(passing) / len(graded), 4) if graded else 0.0,
        "failures_by_message": dict(sorted(reasons.items(), key=lambda item: -item[1])),
        "blocks": graded,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check eTamil samples with the compiler.")
    parser.add_argument("--blocks", action="store_true", help="check every eTamil block in the corpus")
    parser.add_argument("--file", type=Path, help="check one file")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=config.REPORT_DIR / "documented_blocks.json")
    args = parser.parse_args(argv)

    if args.file:
        result = check(args.file.read_text(encoding="utf-8"))
        for diagnostic in result.diagnostics:
            print(diagnostic.raw)
        print("compiles" if result.ok else "does not compile")
        return 0 if result.ok else 1

    if not args.blocks:
        parser.error("give --blocks or --file")

    report = check_blocks(args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"{report['compiles']}/{report['checked']} documented eTamil blocks compile "
          f"({report['rate']:.0%})")
    for message, count in list(report["failures_by_message"].items())[:8]:
        print(f"  {count:>3}  {message}")
    print(f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
