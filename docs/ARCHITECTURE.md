# paRY — four surfaces, one core

The plan is four places a developer meets paRY:

1. **Chat app, web and Android** — describe what you want, get eTamil back
2. **VS Code extension** — Copilot-shaped, writes into the active editor
3. **Desktop eTamil IDE**, Windows and Linux, with paRY inside it
4. **Android IDE** — write a comment, paRY writes the code under it

They differ in how they collect context and where they put the answer. They do
not differ in what generates the code. So there is one core and four thin
clients, and the fourth surface is mostly interface work.

## The core

```
corpus  →  model  →  server  →  protocol  →  clients
  ↑                     ↓
  └──────  compiler  ───┘
```

The compiler appears twice on purpose, and this is the design decision the rest
follows from:

**Nothing leaves the server that does not compile.** The verify loop is not
only a training-data filter — it runs at inference time too. Every candidate
answer that contains eTamil goes through `etamil --check` before it is
returned, and a candidate that fails is retried or degraded to an answer that
says so. A model this small will be wrong sometimes; the language has a free
oracle that says when. Using it is what makes a 45M-parameter assistant
defensible where a hosted 400B one would not be allowed in the building.

It is also what protects the thing most worth protecting: a new language's
credibility. An assistant that confidently invents a keyword teaches the
keyword, and the developer blames the language.

## Where the model runs

**Self-hosted server first; on-device later.** All four clients speak HTTP to a
paRY server the institution runs. One protocol, written once; one place to fix
a bad model. RBI data localisation is satisfied because the bank hosts it — the
code never leaves their network either way.

On-device comes later and only where it fits: the Phase A completion model is
~45M parameters and runs on a CPU at 90–170 tok/s, which is a plausible thing
to put inside the Android app and the desktop IDE for offline use. The chat
model is not. Building the HTTP path first means on-device becomes an
alternative transport behind the same protocol, not a second product.

## Which model each surface needs

This is the part that decides the build order, and it does not match the order
the surfaces are listed in.

| Surface | Needs | Cost of that model |
|---|---|---|
| 2. VS Code completion | **Phase A** — 45M, fill-in-the-middle | ~15 min, **$0.40** a run |
| 3. Desktop IDE completion | Phase A | same model |
| 1. Chat app | **Phase B** — instruction-following, 300M–1B | ~$1,000–1,500, months of data curation |
| 4. Comment → code | Phase B, or Phase A with a prompt convention | — |

"Generate code from a request" and "generate code from a comment" are
instruction-following. Inline completion is not — it is the cheap one.

## The build order

Each step is useful on its own, and each one is a prerequisite for the next
rather than a parallel track.

**Now — the chat app with no model at all.** Two model-free sources answer most
real questions, and both are exact where a small model would guess:

- **Retrieval** over the corpus — 132 documents, 151 documented examples, and
  every keyword, builtin and nUlakam function read out of the compiler.
- **Compiler-driven answers.** "Why doesn't this compile" is answered exactly
  by `diagnostics()`. "What is in scope here" by `symbols_at()`. "What does
  this do" by walking the AST. These cannot invent a keyword that does not
  exist, which is the failure mode that would most damage trust.

Intent routing is rules over the question text and the editor state. Not ML.
This is a real product for a developer learning eTamil, and it is the same
plumbing the model needs later — so none of it is thrown away.

**Then — the eval set and the synthetic corpus.** 200 held-out completion cases
scored against the compiler; then generated eTamil, verified by compiling every
sample. The corpus is 68,163 tokens of real source, which is 500–5,000x too
little; generation is the only way there is a corpus at all.

**Then — Phase A**, and surfaces 2 and 3 become genuinely generative for the
price of a coffee.

**Then — Phase B**, and the chat app stops retrieving and starts writing.

## What the clients share

One protocol, so a client is a UI and a context collector and nothing else.

```
POST /ask        {question, context?, locale}      → answer, citations, code?
POST /complete   {prefix, suffix, path}            → completion (compiled)
POST /diagnose   {source}                          → diagnostics, bilingual
GET  /search     ?q=                               → ranked corpus hits
```

No server exists yet — these are the four shapes it will have. What is built is
what sits behind two of them: `paRY.index.search` answers `/search` and
`paRY.verify.oracle` answers `/diagnose`, both as libraries with command-line
entry points. `/ask` can be built on those two today and improves without
changing shape when a model arrives behind it. `/complete` waits for Phase A.

The existing browser IDE at `eTamil_site/ide/` already runs the compiler front
end as wasm, so `/diagnose` has a zero-latency local implementation on the web
and desktop surfaces. Same protocol, different transport.

## Reuse across the four clients

- **Web chat and desktop IDE**: the desktop IDE is the browser IDE in a Tauri
  or Electron shell. `eTamil_site/ide/` is CodeMirror 6 with a deliberately
  CodeMirror-free compiler bridge, which is what makes this cheap.
- **Android chat and Android IDE**: one app, two screens, or one app with a
  chat panel. The same argument applies.
- **VS Code**: the odd one out. `eTamil_Code/` already exists with generated
  language data, so the extension inherits keywords, hovers and completions
  that cannot drift from the compiler.
