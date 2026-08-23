# eTamil_AI — starting brief

Context for a fresh thread. Nothing here is code yet; this records the
decisions already made so they do not have to be re-argued.

## What this is

A code assistant for eTamil — the Tamil-script FinTech DSL in `../eTamil`
(compiler) served from `../eTamil_site` (etamil.in). It must help a developer
write and debug eTamil.

## Hard constraint

**No external AI APIs.** Not Claude, not GPT, not any hosted model. Everything
runs on infrastructure the project controls, or in the user's browser. This is
a requirement, not a cost preference — the users are Indian financial
institutions under RBI data-localisation rules, so "your code never leaves your
network" is plausibly a selling point rather than a compromise.

Built from scratch with Python libraries: PyTorch, `tokenizers`,
`sentencepiece`. Training runs are rented by the hour and destroyed.

## Measured facts about the corpus

| | |
|---|---|
| eTamil source (`.qmz`) | 100 files, 7,783 lines, **450 kB ≈ 185k tokens** |
| Documentation (`.md`/`.mdx`) | 660 files, 96,925 lines, **3.5 MB** |
| Keywords | **202**, in **505 spellings** (Tamil script / romanized / `_GST`-style) |
| Syntax | full Tamil script; `செயல்` `திரும்பு` `எனில்` `சுற்று` |
| Domain | Indian finance, tax, accounting; exact decimal money |

**185k tokens is 500–5,000x too little to fine-tune on.** The corpus problem is
solved by *generating* eTamil rather than collecting it: fuzz the grammar,
enumerate the `nUlakam` stdlib into usage sites, expand every doc code block,
and **verify every sample by compiling it** — the compiler is a free oracle at
scale. That turns 185k tokens into 50–500M of verified-correct eTamil.
Diversity, not volume, is the binding constraint.

## Model plan

- **Own tokenizer first.** Train BPE on the corpus. Tamil script costs 3–6x the
  tokens under a general tokenizer; a 16k vocab built for eTamil makes `செயல்`
  one token and inverts that penalty. This measurement sizes everything
  downstream, so do it before anything else.
- **Phase A — completion.** ~45M params (12 layers, d_model 512), FIM objective
  from day one, 200–500M synthetic tokens. Compute is 6ND ≈ 8×10^16 FLOPs:
  **~15 minutes on a rented L40S, about $0.40 a run.** Runs on CPU at 90–170
  tok/s; no GPU at inference. Give it a **Llama-shaped** architecture (RMSNorm,
  SwiGLU, RoPE) so `llama.cpp` serves it — prefix caching and an
  OpenAI-compatible server for free.
- **Phase B — chat.** 300M–1B with general Tamil/English pretraining, ~$1,000–
  1,500 rented GPU. Data curation is months. Do not start here.

**Build the eval set before training anything.** 200 held-out completion cases
from real `.qmz` with a scoring script (exact match, edit distance, does it
parse, does it pass its test). Without it, Phase A is expensive guessing.

## What already exists to integrate with

`../eTamil_site/ide/` is a working CodeMirror 6 editor at etamil.in/ide:

- Highlighting generated from `lexer.rs` (`tools/gen_tokens.py`) — never drifts
- **The compiler front end runs in the browser as wasm**: `diagnostics(src)`,
  `symbols(src)`, `symbols_at(src, line, col)`, bilingual error messages
- Mobile key row for Tamil-script typing
- 136 kB + 82 kB gzipped, static hosting, $0/month

The bridge in `ide/src/etamil-compiler.js` is deliberately CodeMirror-free.

## Chat, before any model exists

Two model-free sources answer most real questions, and the plumbing is the same
plumbing a model would need later:

1. **Retrieval** over the 660 doc files and 100 examples (SQLite FTS5 server-
   side, `minisearch` client-side — not `rank_bm25`, which is memory-hungry).
2. **Compiler-driven answers.** "Why doesn't this compile" is already answered
   exactly by `diagnostics()`; "what's in scope" by `symbols_at()`; "what does
   this do" by walking the AST. Deterministic, instant, and structurally
   incapable of inventing a keyword that does not exist — which is the failure
   mode that would most damage trust in a new language.

Intent routing is rules over question text plus editor state. Not ML.

## Gotchas already paid for

- **`மாறி`/`நிலை` are tokens but not statement prefixes.** `மாறி x = 5;` is a
  parse error; eTamil assigns with a bare `x = 5;`. Easy to get wrong from
  reading `keywords.md`.
- **Embeddings must be multilingual** (`bge-m3`, `multilingual-e5`). `bge-small-en`
  is useless on Tamil.
- **`wasm-opt` makes the download bigger**, not smaller — it removes the
  repetition gzip exploits. Measured; see `../eTamil_site/ide/README.md`.
- **CPU-only inference cannot do ghost text.** Prefill is the wall, not decode.
- The `eTamil` repo has another session active in it. Check `git log` before
  assuming the tree is yours.
