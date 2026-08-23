"""Train paRY's own tokenizer on the eTamil corpus.

This comes before the model because it sizes everything after it. Tamil script
costs three UTF-8 bytes a character, and a tokenizer that never saw Tamil pays
close to a token per byte for it — so the same program costs several times more
tokens than its English equivalent, and every one of those tokens is context
the model does not get to spend on the problem. A vocabulary built here makes
`செயல்` a single token and inverts that.

Choices, and why:

* **Byte-level BPE.** Every possible input has a representation, so no
  `<unk>` can appear on a Tamil identifier the training set never contained.
* **Digits split individually.** This is a language for money. `18` and `180`
  sharing no token would let a completion confuse them.
* **FIM tokens reserved from the start.** Completion in an editor means filling
  a hole with text on both sides. Adding those tokens later means retraining.
* **Code weighted up.** The documentation outweighs the code by bytes, and a
  vocabulary chosen mostly by prose spends its merges on prose.

    python -m paRY.tokenizer.train
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Iterator

from tokenizers import Regex, Tokenizer, decoders, models, pre_tokenizers, trainers

from .. import config, lexicon
from ..corpus.collect import read_jsonl

VOCAB_SIZE = 16_384

# Reserved first, in this order, so the ids stay stable as the vocabulary grows.
SPECIAL_TOKENS = [
    "<|pad|>",
    "<|bos|>",
    "<|eos|>",
    "<|fim_prefix|>",
    "<|fim_middle|>",
    "<|fim_suffix|>",
    "<|file_sep|>",
]

CODE_KINDS = {"stdlib", "example", "bench"}

# A word, optionally with the space in front of it; then a digit; then a run of
# punctuation; then whitespace. A word may start with an underscore, because the
# English aliases the lexer accepts are spelled `_fn`, `_if`, `_GST`.
#
# `\p{M}` is the reason this is written out rather than left to ByteLevel's own
# GPT-2 regex. Tamil vowel signs and the pulli are combining marks, category Mn,
# and `\p{L}` does not match them — so that regex cuts செயல் into ச | ெ | யல | ்,
# putting the pieces of one word in three different classes. BPE cannot merge
# across pre-token boundaries, so no amount of training recovers the word. The
# first tokenizer trained here did exactly that and gave zero of 523 keyword
# spellings a token of their own.
SPLIT_PATTERN = r" ?[\p{L}\p{M}_][\p{L}\p{M}\p{N}_]*| ?\p{N}| ?[^\s\p{L}\p{M}\p{N}]+|\s+"


def build_tokenizer() -> Tokenizer:
    tokenizer = Tokenizer(models.BPE(unk_token=None))
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence(
        [
            pre_tokenizers.Split(Regex(SPLIT_PATTERN), behavior="isolated"),
            pre_tokenizers.Digits(individual_digits=True),
            # Byte mapping only — the splitting is done above.
            pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
        ]
    )
    tokenizer.decoder = decoders.ByteLevel()
    return tokenizer


def primer(repeats: int) -> tuple[list[str], int]:
    """Every name the compiler accepts, whether or not the corpus uses it.

    eTamil takes three spellings of each keyword — Tamil script, romanized and
    an English alias — and the corpus is written almost entirely in the first.
    Left to the corpus alone, `ceyal` and `_fn` cost four tokens each while
    `செயல்` costs one, and a developer writing in the romanized style the
    language advertises gets the worse assistant.

    So the accepted vocabulary is put in front of the trainer directly. BPE
    chooses merges by frequency; this makes these names frequent enough to earn
    one, at a cost of at most one merge each out of sixteen thousand.
    """
    names = lexicon.load().vocabulary
    # Twice on one line, because the pre-tokenizer keeps a leading space
    # attached and ` ceyal` and `ceyal` are two different strings to BPE. Both
    # on one line and not on two: a newline followed by a space is a single
    # whitespace run to the splitter, which would leave the second copy bare as
    # well and teach the space-prefixed form nothing.
    lines = [f"{name} {name}\n" for name in names]
    return lines * repeats, len(names)


def training_texts(corpus_dir: Path, code_share: float) -> tuple[list[str], dict]:
    """The corpus as a list of texts, with code repeated to reach `code_share`.

    Repetition is how BPE is told what matters: the merges are chosen by
    frequency, so a document counted twice votes twice.
    """
    documents = read_jsonl(corpus_dir / "documents.jsonl")
    blocks = [block for block in read_jsonl(corpus_dir / "blocks.jsonl") if block["is_etamil"]]

    code = [record for record in documents if record["kind"] in CODE_KINDS]
    prose = [record for record in documents if record["kind"] not in CODE_KINDS]

    code_bytes = sum(record["bytes"] for record in code) + sum(block["bytes"] for block in blocks)
    prose_bytes = sum(record["bytes"] for record in prose)

    if code_bytes == 0:
        raise SystemExit("no eTamil source in the corpus — run paRY.corpus.collect first")

    # code_bytes * repeats / (code_bytes * repeats + prose_bytes) == code_share
    wanted = code_share / (1 - code_share) * prose_bytes / code_bytes if code_share < 1 else 1
    repeats = max(1, round(wanted))

    texts = [record["text"] for record in prose]
    for _ in range(repeats):
        texts.extend(record["text"] for record in code)
        texts.extend(block["text"] for block in blocks)

    weighted_code = code_bytes * repeats
    return texts, {
        "code_files": len(code),
        "etamil_blocks": len(blocks),
        "prose_files": len(prose),
        "code_bytes": code_bytes,
        "prose_bytes": prose_bytes,
        "code_repeats": repeats,
        "effective_code_share": round(weighted_code / (weighted_code + prose_bytes), 3),
    }


def train(
    corpus_dir: Path,
    out_path: Path,
    vocab_size: int,
    code_share: float,
    primer_repeats: int,
) -> dict:
    texts, mix = training_texts(corpus_dir, code_share)
    primer_lines, primer_names = primer(primer_repeats)
    texts = primer_lines + texts
    mix |= {"primer_names": primer_names, "primer_repeats": primer_repeats}

    tokenizer = build_tokenizer()
    trainer = trainers.BpeTrainer(
        vocab_size=vocab_size,
        special_tokens=SPECIAL_TOKENS,
        initial_alphabet=pre_tokenizers.ByteLevel.alphabet(),
        show_progress=False,
    )

    started = time.perf_counter()
    tokenizer.train_from_iterator(_chunks(texts), trainer=trainer, length=len(texts))
    elapsed = time.perf_counter() - started

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tokenizer.save(str(out_path), pretty=False)

    report = {
        "tokenizer": str(out_path),
        "vocab_size": tokenizer.get_vocab_size(),
        "requested_vocab_size": vocab_size,
        "special_tokens": SPECIAL_TOKENS,
        "training_seconds": round(elapsed, 2),
        "mix": mix,
    }
    out_path.with_suffix(".train.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _chunks(texts: list[str]) -> Iterator[str]:
    yield from texts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train the paRY tokenizer.")
    parser.add_argument("--corpus", type=Path, default=config.CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=config.TOKENIZER_DIR / "paRY-16k.json")
    parser.add_argument("--vocab-size", type=int, default=VOCAB_SIZE)
    parser.add_argument(
        "--code-share",
        type=float,
        default=0.5,
        help="share of training bytes that should be eTamil source (default 0.5)",
    )
    parser.add_argument(
        "--primer-repeats",
        type=int,
        default=25,
        help="how many times to show the trainer every accepted name (0 to disable); "
             "25 and 400 measured identically, so this is the floor, not a dial",
    )
    args = parser.parse_args(argv)

    report = train(args.corpus, args.out, args.vocab_size, args.code_share, args.primer_repeats)
    mix = report["mix"]
    print(f"trained {report['vocab_size']} tokens in {report['training_seconds']}s")
    print(
        f"  {mix['code_files']} source files and {mix['etamil_blocks']} documented blocks "
        f"repeated {mix['code_repeats']}x against {mix['prose_files']} documents"
    )
    print(f"  eTamil source is {mix['effective_code_share']:.0%} of the training bytes")
    print(f"  {mix['primer_names']} accepted names primed {mix['primer_repeats']}x")
    print(f"  written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
