"""What the tokenizer is worth, in numbers.

Four questions, because each one decides something downstream:

1. **How big is the corpus in tokens?** This is the number that says whether
   there is enough material to train on. It is measured, not estimated.
2. **How many characters does a token buy?** Reported separately for Tamil
   script and for everything else, against the byte count — an untrained
   byte-level tokenizer spends about one token per byte, and Tamil is three
   bytes a character, so that is the ceiling this is beating.
3. **Is a keyword one token?** `செயல்` split into four pieces is four chances
   to emit a keyword that does not exist. Measured across every spelling the
   compiler accepts, every builtin, and every nUlakam function.
4. **Does text survive a round trip?** Byte-level BPE should be lossless on any
   input. Should is not measured; this is.

    python -m paRY.tokenizer.measure
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from tokenizers import Tokenizer

from .. import config, lexicon
from ..corpus.collect import read_jsonl

TAMIL = re.compile(r"[஀-௿]")

SAMPLE = """செயல் வரி_கணக்கு(எண் வருவாய்) {
    (வருவாய் > 800000) எனில் {
        திரும்பு (வருவாய் - 800000) * 20%;
    }
    திரும்பு 0;
}
"""


def _tamil_chars(text: str) -> int:
    return len(TAMIL.findall(text))


def _count(tokenizer: Tokenizer, texts: list[str]) -> dict:
    tokens = 0
    chars = 0
    tamil = 0
    utf8_bytes = 0
    for text in texts:
        tokens += len(tokenizer.encode(text, add_special_tokens=False).ids)
        chars += len(text)
        tamil += _tamil_chars(text)
        utf8_bytes += len(text.encode("utf-8"))
    return {
        "texts": len(texts),
        "tokens": tokens,
        "chars": chars,
        "tamil_chars": tamil,
        "bytes": utf8_bytes,
        "chars_per_token": round(chars / tokens, 3) if tokens else 0.0,
        "bytes_per_token": round(utf8_bytes / tokens, 3) if tokens else 0.0,
    }


def single_token_coverage(tokenizer: Tokenizer, names: list[str]) -> dict:
    """How many of these names encode to exactly one token.

    A name is measured with a leading space, which is how it almost always
    appears in a program, and byte-level BPE treats ` செயல்` and `செயல்` as
    different strings.
    """
    single = []
    split = []
    for name in names:
        ids = tokenizer.encode(" " + name, add_special_tokens=False).ids
        (single if len(ids) == 1 else split).append(name)
    worst = sorted(split, key=lambda name: -len(tokenizer.encode(" " + name, add_special_tokens=False).ids))
    return {
        "total": len(names),
        "single_token": len(single),
        "rate": round(len(single) / len(names), 4) if names else 0.0,
        "most_split": [
            {"name": name, "tokens": len(tokenizer.encode(" " + name, add_special_tokens=False).ids)}
            for name in worst[:10]
        ],
    }


def round_trip(tokenizer: Tokenizer, texts: list[str]) -> dict:
    """Encode, decode, compare. Anything that does not come back is a bug."""
    failures = []
    for index, text in enumerate(texts):
        encoded = tokenizer.encode(text, add_special_tokens=False)
        if tokenizer.decode(encoded.ids) != text:
            failures.append(index)
    return {"checked": len(texts), "lossless": len(failures) == 0, "failures": failures[:5]}


def measure(tokenizer_path: Path, corpus_dir: Path) -> dict:
    tokenizer = Tokenizer.from_file(str(tokenizer_path))
    documents = read_jsonl(corpus_dir / "documents.jsonl")
    blocks = [block for block in read_jsonl(corpus_dir / "blocks.jsonl") if block["is_etamil"]]

    by_kind: dict[str, list[str]] = {}
    for record in documents:
        by_kind.setdefault(record["kind"], []).append(record["text"])

    code_kinds = {"stdlib", "example", "bench"}
    code_texts = [text for kind, texts in by_kind.items() if kind in code_kinds for text in texts]
    prose_texts = [text for kind, texts in by_kind.items() if kind not in code_kinds for text in texts]

    names = lexicon.load()
    return {
        "tokenizer": str(tokenizer_path),
        "vocab_size": tokenizer.get_vocab_size(),
        "corpus": {
            "all": _count(tokenizer, [record["text"] for record in documents]),
            "etamil_source": _count(tokenizer, code_texts),
            "documentation": _count(tokenizer, prose_texts),
            "documented_blocks": _count(tokenizer, [block["text"] for block in blocks]),
            "by_kind": {kind: _count(tokenizer, texts) for kind, texts in sorted(by_kind.items())},
        },
        "vocabulary_coverage": {
            "keyword_spellings": single_token_coverage(tokenizer, names.keyword_spellings),
            "builtins": single_token_coverage(tokenizer, names.builtin_names),
            "nUlakam_functions": single_token_coverage(tokenizer, names.stdlib_names),
        },
        "round_trip": round_trip(tokenizer, [record["text"] for record in documents]),
        "sample": {
            "text": SAMPLE,
            "tokens": tokenizer.encode(SAMPLE, add_special_tokens=False).tokens,
            "count": len(tokenizer.encode(SAMPLE, add_special_tokens=False).ids),
            "bytes": len(SAMPLE.encode("utf-8")),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure the paRY tokenizer.")
    parser.add_argument("--tokenizer", type=Path, default=config.TOKENIZER_DIR / "paRY-16k.json")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=config.REPORT_DIR / "tokenizer.json")
    args = parser.parse_args(argv)

    report = measure(args.tokenizer, args.corpus)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    corpus = report["corpus"]
    print(f"vocabulary {report['vocab_size']} tokens")
    print()
    print(f"{'':<20}{'tokens':>10}{'chars/tok':>11}{'bytes/tok':>11}")
    for label in ("all", "etamil_source", "documentation", "documented_blocks"):
        entry = corpus[label]
        print(
            f"{label:<20}{entry['tokens']:>10,}{entry['chars_per_token']:>11.2f}"
            f"{entry['bytes_per_token']:>11.2f}"
        )
    print()
    for label, entry in report["vocabulary_coverage"].items():
        print(f"{label:<20}{entry['single_token']:>5}/{entry['total']:<5} are one token "
              f"({entry['rate']:.0%})")
    print()
    trip = report["round_trip"]
    print(f"round trip {'lossless' if trip['lossless'] else 'LOSSY'} over {trip['checked']} documents")
    sample = report["sample"]
    print(f"sample function: {sample['count']} tokens for {sample['bytes']} bytes")
    print(f"report written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
