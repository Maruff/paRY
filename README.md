# paRY — பறை

A code assistant for [eTamil](../eTamil), built on infrastructure the project
controls. `பறை` is the drum an announcement was made on, and the verb for
making one; `paRY` is how the compiler's own romanization spells it.

**No hosted model is called, at any stage.** The corpus comes from the eTamil
repositories, the tokenizer is trained here, and the compiler decides what is
correct. The users are Indian financial institutions under RBI data
localisation, so "your code never leaves your network" is the feature, not the
compromise. [`BRIEF.md`](BRIEF.md) records the decisions this rests on.

## What works today

Phase 0 — everything the model plan needs measured before a model is worth
training. Three commands, each writing its numbers to `data/`:

```bash
python -m paRY.corpus.collect      # gather the corpus
python -m paRY.verify.oracle --blocks   # grade the documented examples
python -m paRY.tokenizer.train && python -m paRY.tokenizer.measure
```

### The corpus is small, and now exactly known

| | files | size | tokens |
|---|---:|---:|---:|
| eTamil source (`.qmz`) | 73 | 432 kB | 66,848 |
| Documentation (`.md`, both languages) | 55 | 665 kB | 140,213 |
| eTamil blocks inside the documentation | 149 | 34 kB | 6,936 |
| **Everything** | **128** | **1,096 kB** | **207,061** |

The brief estimated 185k tokens of source and called that 500–5,000x too little
to fine-tune on. Measured under paRY's own tokenizer it is **66,848** — the
estimate was made with a general tokenizer, which spends three times as many
tokens on the same Tamil. The conclusion does not change; it gets sharper.
Generating verified eTamil is not one option among several, it is the only way
there is a corpus at all.

### The compiler already grades samples

`etamil --check` lexes, parses and type checks without running anything, so a
candidate can be judged without executing code that would write a file or open
a socket. Pointed at the documentation:

**126 of 149 documented eTamil examples compile (85%).**

The 23 that do not are mostly deliberate fragments — a `.field` continuation, a
line of pseudo-code — and are worth knowing about either way, because a
documented example that does not compile is both a documentation bug and a
sample that must not be trained on. One is a real bug:
`docs/backend/HTTP_SERVER_QUICKREF.md` has an example written in Ethiopic
script rather than Tamil.

Two limits, measured rather than assumed, both in `paRY/verify/oracle.py`:
`--check` stops before name resolution, so `அச்சு y;` with `y` never assigned
passes; and it is one process per sample, which is fine for hundreds and far
too slow for the hundreds of millions of tokens the plan calls for. That scale
needs a batch mode inside the compiler.

### The tokenizer

16,384 byte-level BPE tokens, trained in about two seconds, at
`data/tokenizer/paRY-16k.json`.

| | chars/token | bytes/token |
|---|---:|---:|
| eTamil source | 4.07 | 6.61 |
| Documentation | 3.79 | 4.85 |

Bytes per token is the number that matters for Tamil. An untrained byte-level
tokenizer spends about one token per byte, and Tamil costs three bytes a
character — so this is roughly **6.6x** less context spent on the same program.

Every name the compiler accepts is a single token: **523 keyword spellings,
177 builtin spellings, 253 nUlakam functions — 100% of each.** A keyword split
across four tokens is four chances to emit a keyword that does not exist, which
is the failure mode that would most damage trust in a new language. The
romanized and English spellings are in there too, primed from the compiler's
own tables (`paRY/lexicon.py`), because the corpus is written almost entirely
in Tamil script and a developer writing `eN varuvAy = 100000;` should not get
the worse assistant.

FIM tokens are reserved from the start — completion in an editor means filling
a hole with text on both sides, and adding those tokens later means retraining.

**Two bugs, both worth keeping in mind for anything else that tokenizes Tamil:**

1. The default GPT-2 byte-level regex cuts `செயல்` into `ச | ெ | யல | ்`,
   because Tamil vowel signs and the pulli are combining marks and `\p{L}` does
   not match them. BPE cannot merge across those boundaries, so no amount of
   training recovers the word. The first tokenizer trained here had **zero** of
   523 keyword spellings as a token. Fixing the splitter cut the corpus from
   389k tokens to 204k — the same text, 1.9x cheaper.
2. Priming the vocabulary on two lines (`name\n name\n`) taught the
   space-prefixed form nothing, because a newline followed by a space is one
   whitespace run to the splitter. On one line it works, and coverage went from
   42% to 100%.

## Next

1. **The eval set, before any training.** 200 held-out completion cases from
   real `.qmz`, scored on exact match, edit distance, does it parse, does it
   pass its test. The oracle here is most of the scoring; what is missing is
   the held-out split and the harness.
2. **Corpus generation.** Fuzz the grammar, enumerate nUlakam into usage sites,
   expand the documented blocks — and verify every sample by compiling it.
   Needs the compiler batch mode above to be affordable.
3. **Phase A completion model.** ~45M parameters, Llama-shaped so `llama.cpp`
   serves it. Not before 1 and 2.

Retrieval and compiler-driven answers — the model-free half of the assistant,
which answers most real questions today — are a parallel track and share this
corpus.

## Layout

```
paRY/config.py         where the repositories are; every path has an env override
paRY/lexicon.py        keywords, builtins and nUlakam, read out of the compiler
paRY/corpus/collect.py the corpus, with provenance and content hashes
paRY/verify/oracle.py  the compiler as a judge
paRY/tokenizer/        training and measurement
data/                  everything generated — reproducible, and not committed
```

## Setup

```bash
py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
```

The eTamil repositories are expected as siblings of this one, and the compiler
built (`cargo build --release` in `etamil_compiler/`). Both are overridable —
`ETAMIL_ROOT`, `ETAMIL_SITE_ROOT`, `ETAMIL_BIN`, `PARY_DATA`.

```bash
python -m pytest
```
