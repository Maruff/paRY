"""Held-out completion cases, cut out of programs that actually compile.

A case is a real file with a hole in it: the text before the hole, the text
after it, and the lines that were removed. That is the shape a fill-in-the-middle
model is asked for in an editor, so it is the shape the eval has to be.

Two rules decide whether a case is worth keeping, and both are checked rather
than assumed:

* **The whole file must compile.** Otherwise "does the completion compile" is
  measuring the file's pre-existing breakage.
* **The hole must contain something.** A hole made of blank lines is scored
  perfectly by predicting nothing, which flatters every model equally.

The split is by file and deterministic — `sha256(path) % 5 == 0` — so the same
files are held out on every machine, and the corpus generator can be told to
exclude them without a second list to keep in step.

    python -m paRY.eval.cases            # build them
    python -m paRY.eval.cases --list     # what is held out
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .. import config
from ..corpus.collect import read_jsonl
from . import sandbox

# One file in five is never trained on. Twenty per cent of 77 files is fifteen,
# which is enough for a few hundred cases without starving the training set.
HELD_OUT_IN = 5

# Holes of one, two and three lines: an editor asks for all three, and a model
# that only ever gets the next line right is not much use.
HOLE_SIZES = (1, 2, 3)

# At most this many cases from one file, so a long program cannot dominate.
CASES_PER_FILE = 6

SOURCE_KINDS = {"stdlib", "example", "bench"}


@dataclass(frozen=True)
class Case:
    id: str
    path: str
    line: int          # 1-based line the hole starts at
    hole: int          # how many lines were removed
    prefix: str
    middle: str
    suffix: str


def is_held_out(path: str) -> bool:
    """Deterministic, and the same everywhere, because it is a hash of the name."""
    digest = hashlib.sha256(path.encode("utf-8")).digest()
    return digest[0] % HELD_OUT_IN == 0


def _worth_predicting(lines: list[str]) -> bool:
    """A hole has to contain code, not blank lines and a comment."""
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            return True
    return False


def _cut_points(lines: list[str], hole: int) -> list[int]:
    """Where to cut, spread through the file rather than clustered at the top."""
    usable = [
        index
        for index in range(1, len(lines) - hole)
        if _worth_predicting(lines[index : index + hole])
    ]
    if not usable:
        return []
    # Evenly spaced, so a case set is not all imports and all closing braces.
    wanted = min(CASES_PER_FILE, len(usable))
    step = max(1, len(usable) // wanted)
    return usable[::step][:wanted]


def build(out_path: Path) -> dict:
    documents = [
        record
        for record in read_jsonl(config.CORPUS_DIR / "documents.jsonl")
        if record["kind"] in SOURCE_KINDS
    ]
    held_out = [record for record in documents if is_held_out(record["path"])]

    with sandbox.Sandbox() as box:
        compiling = [record for record in held_out if box.compiles(record["path"], record["text"])]

        cases: list[Case] = []
        for record in compiling:
            lines = record["text"].split("\n")
            for hole in HOLE_SIZES:
                for start in _cut_points(lines, hole):
                    middle = "\n".join(lines[start : start + hole])
                    cases.append(
                        Case(
                            id=f"{record['path']}#{start + 1}+{hole}",
                            path=record["path"],
                            line=start + 1,
                            hole=hole,
                            prefix="\n".join(lines[:start]) + "\n",
                            middle=middle + "\n",
                            suffix="\n".join(lines[start + hole :]),
                        )
                    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(asdict(case), ensure_ascii=False) + "\n")

    summary = {
        "cases": len(cases),
        "files_held_out": len(held_out),
        "files_compiling": len(compiling),
        "files_total": len(documents),
        "by_hole": {hole: sum(1 for case in cases if case.hole == hole) for hole in HOLE_SIZES},
        "held_out_paths": sorted(record["path"] for record in held_out),
    }
    out_path.with_suffix(".summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def load(path: Path | None = None) -> list[Case]:
    source = path or config.DATA_DIR / "eval" / "completion.jsonl"
    if not source.exists():
        raise SystemExit(f"no eval set at {source} — run python -m paRY.eval.cases")
    return [Case(**record) for record in read_jsonl(source)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the held-out completion cases.")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "eval" / "completion.jsonl")
    parser.add_argument("--list", action="store_true", help="just show what is held out")
    args = parser.parse_args(argv)

    if args.list:
        documents = [
            record
            for record in read_jsonl(config.CORPUS_DIR / "documents.jsonl")
            if record["kind"] in SOURCE_KINDS
        ]
        for record in sorted(documents, key=lambda r: r["path"]):
            if is_held_out(record["path"]):
                print(f"  held out  {record['path']}")
        return 0

    summary = build(args.out)
    print(f"{summary['cases']} cases from {summary['files_compiling']} files")
    print(
        f"  {summary['files_held_out']} of {summary['files_total']} files held out; "
        f"{summary['files_held_out'] - summary['files_compiling']} dropped for not compiling"
    )
    for hole, count in summary["by_hole"].items():
        print(f"  {hole}-line holes: {count}")
    print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
