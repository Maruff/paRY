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
training, plus the retrieval it feeds. Each command writes its numbers to
`data/`:

```bash
python -m paRY.corpus.collect             # gather the corpus
python -m paRY.verify.oracle --blocks     # grade the documented examples
python -m paRY.tokenizer.train && python -m paRY.tokenizer.measure
python -m paRY.index.build                # build the retrieval index
python -m paRY.index.search "how do I read a file"
python -m paRY.answer "how do I write a row to a CSV file"
python -m paRY.serve                      # API and web client on :8900
```

Where this is going — four surfaces over one core, and which model each of them
needs — is [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

### The corpus is small, and now exactly known

| | files | size | tokens |
|---|---:|---:|---:|
| eTamil source (`.qmz`) | 77 | 438 kB | 68,163 |
| Documentation (`.md`, both languages) | 55 | 672 kB | 141,369 |
| eTamil blocks inside the documentation | 151 | 34 kB | 6,949 |
| **Everything** | **132** | **1,110 kB** | **209,532** |

The brief estimated 185k tokens of source and called that 500–5,000x too little
to fine-tune on. Measured under paRY's own tokenizer it is **68,163** — the
estimate was made with a general tokenizer, which spends three times as many
tokens on the same Tamil. The conclusion does not change; it gets sharper.
Generating verified eTamil is not one option among several, it is the only way
there is a corpus at all.

### The compiler already grades samples

`etamil --check` lexes, parses and type checks without running anything, so a
candidate can be judged without executing code that would write a file or open
a socket. Pointed at the documentation:

**128 of 151 documented eTamil examples compile (85%).**

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
| eTamil source | 4.06 | 6.58 |
| Documentation | 3.79 | 4.87 |

Bytes per token is the number that matters for Tamil. An untrained byte-level
tokenizer spends about one token per byte, and Tamil costs three bytes a
character — so this is roughly **6.6x** less context spent on the same program.

Every name the compiler accepts is a single token: **524 keyword spellings,
186 builtin spellings, 253 nUlakam functions — 100% of each.** A keyword split
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
   524 keyword spellings as a token. Fixing the splitter cut the corpus from
   389k tokens to 204k — the same text, 1.9x cheaper.
2. Priming the vocabulary on two lines (`name\n name\n`) taught the
   space-prefixed form nothing, because a newline followed by a space is one
   whitespace run to the splitter. On one line it works, and coverage went from
   42% to 100%.

### Retrieval

1,721 chunks in one SQLite FTS5 file — 518 symbols, 975 documentation sections,
151 documented examples with their compile verdict attached, 77 source files.
No server, no dependency, and it answers in milliseconds.

A symbol chunk is the highest-precision thing in there: "what does நீளம் do"
is answered from `interpreter.rs`, not from a paragraph that mentions it. An
example that does not compile is still indexed, and marked — it is useful
context and must never be handed back as an answer.

**The tokenizer trap again, in a different library.** SQLite's default
tokenizer takes only letters and numbers as part of a word, and Tamil vowel
signs are combining marks — so `செயல் வருவாய்` indexes as `ச`, `யல`, `வ`,
`வர`, and every Tamil word collides with every other one sharing a bare
consonant. Naming the mark categories fixes it:

```sql
tokenize="unicode61 categories 'L* N* Mn Mc'"
```

Two libraries, same mistake. It is worth assuming any text tool is wrong about
Tamil until it has been shown otherwise.

### Answers, with no model

`python -m paRY.answer "…"` routes a question by rules to whichever source can
answer it exactly, and falls back to retrieval:

| Intent | When | Answered from |
|---|---|---|
| `diagnose` | there is source, and it does not compile | the compiler, bilingually, with line and column |
| `symbol` | the question names a keyword, builtin or nUlakam function | the compiler's own tables |
| `explain` | there is source and the question asks what it does | every name it uses |
| `howto` | everything else | documentation and verified examples |

A Tamil question is answered with a Tamil frame. Three known mistakes are
recognised by name rather than only quoted — the one the brief singles out as
easiest to make gets the real fix, not just the parse error:

```
$ python -m paRY.answer "why does this fail" --source broken.qmz
### Why this does not compile
- ✗ வரி 1, நெடுவரிசை 6: '=' எதிர்பார்க்கப்பட்டது, 'x' கிடைத்தது
  (line 1, column 6: expected '=', found 'x')

### The fix
- `மாறி` and `நிலை` are tokens, but they are not statement prefixes.
  eTamil assigns with a bare name: `x = 5;`, not `மாறி x = 5;`.
```

**No answer carries code that has not been compiled.** An example is quoted
only when the oracle has said it compiles, and one longer than 40 lines is
cited rather than pasted, because half a program does not compile. When nothing
answers, paRY says so instead of composing something plausible — that invariant
is a test, run over every intent.

### The server

The one protocol all four surfaces speak. `pip install -e ".[serve]"`, then
`python -m paRY.serve`.

| | | |
|---|---|---|
| `POST /ask` | question, optional source, optional locale | the answer above, as JSON |
| `POST /diagnose` | source | the compiler's diagnostics, bilingual, with line and column |
| `GET /search` | `?q=&limit=&kind=` | ranked corpus hits |
| `POST /complete` | prefix, suffix | **501** until Phase A is trained |
| `GET /health` | | compiler version, index size, and `model: null` |

```console
$ curl -s localhost:8900/health
{"version":"0.1.0","compiler":"etamil 0.4.0","index":"…/paRY.db","chunks":1721,"model":null}
```

`/complete` is declared and refuses rather than being absent, so a client can be
written against the whole protocol today. Answering it from retrieval would be
worse than answering nothing: an editor that inserts a wrong line teaches it.
`/health` reports `model: null` for the same reason — what is behind an answer
should not have to be inferred.

The handlers are synchronous on purpose. Each one spawns the compiler or hits
SQLite, and FastAPI runs a `def` handler in a threadpool; `async def` would put
blocking work on the event loop and stall every request behind the slowest
compile.

The default bind is loopback. This server compiles what it is sent, so it
belongs inside the network that owns the code, behind that network's own
authentication — `--host 0.0.0.0` is a decision you have to type.

### The web client

`python -m paRY.serve`, then open <http://127.0.0.1:8900>. That is the whole
install — the server serves the client it talks to.

No framework, no bundler, no npm, no web fonts. That is not minimalism for its
own sake: an institution running this inside its own network should not need a
route out to install a chat window, and a build step is one more thing that has
to be allowed through. Three files in `web/`.

- Ask in Tamil or English; a Tamil question comes back with a Tamil frame
- Paste code and it is compiled before anything is said about it
- Every answer shows its intent, its confidence, and where it came from
- Code carries the server's ✓ compiles verdict, never the client's guess
- The header says `no model — compiler and corpus only`, because a user should
  never have to guess whether a model wrote what they are reading

Two things it taught, both fixed: a sticky composer hides the newest answer the
moment the code pane opens, so the transcript is its own scroll region rather
than the page scrolling underneath; and `scrollIntoView({behavior: "smooth"})`
silently does nothing in some embedded webviews, which leaves a chat that does
not follow its own output.

### Android

`android/` is the same client in a WebView, pointed at a paRY server —
[`android/README.md`](android/README.md) has the detail.

**Written, never built.** There is no JDK, Gradle or Android SDK on the machine
that wrote it, so nothing there has been compiled or run. What was checked is
what can be checked without a toolchain: every XML parses, every `@string`,
`@color`, `@drawable`, `@xml` and `@id` reference resolves, every `R.*` in the
Kotlin resolves, and the Tamil strings carry the same format arguments as the
English. Expect the first `assembleDebug` to still find something.

What *is* verified is the half that runs here: `python -m paRY.serve --host
0.0.0.0` serves both the API and the client on the machine's LAN addresses, so
a phone on the same network reaches it at `192.168.x.x:8900` — subject to the
host firewall allowing the port.

The APK carries no copy of `web/`. Answers come from the server, so a bundled
client would gain nothing offline and could drift out of step with the protocol
it speaks; loading it from the server keeps one chat window across all three
surfaces. That changes when Phase A is small enough to run on the phone — and
the protocol will not, which is the reason for settling it first.

### VS Code

`vscode/` is the editor extension — [`vscode/README.md`](vscode/README.md) has
the detail. Three things, in the order they are worth having:

1. **Diagnostics** — the compiler's own errors in the editor as you type,
   bilingual, with line and column. Needs no model and never will.
2. **A chat panel** — the same answer engine, in the activity bar.
3. **Inline completion** — registered, and refusing with 501 until Phase A.

**Typechecks and compiles; never run in an extension host**, because no editor
was available where it was written. The layer that *could* be checked was: a
script drove a live server through every call the extension makes and confirmed
all 26 field shapes it depends on — diagnostics 1-based and bilingual,
`/complete` refusing with a readable `detail`, and no answer carrying code the
server had not compiled.

It contributes no grammar, keywords or hovers. `etamil-support` already
generates those from `lexer.rs` so they cannot drift; duplicating them here
would be the mistake that extension exists to correct.

paRY also stands down from publishing diagnostics when `etamil-support` is
installed, because that extension already compiles on type with the local
binary — two extensions reporting the same compiler's errors means two
squiggles on every mistake.

**Installed and running here.** Both extensions are packaged and installed into
VS Code (`etamil.etamil-support@0.4.0`, `etamil.pary@0.1.0`), and the server log
shows the extension reaching `/health` on activation — and no `/diagnose`,
which is the stand-down working.

### Desktop IDE

`desktop/` is **VSCodium** plus those two extensions plus a profile —
[`desktop/README.md`](desktop/README.md) has the reasoning.

```bash
python desktop/provision.py --dry-run   # say what it would do
python desktop/provision.py             # build, install, configure
```

The tempting alternative was a Tauri shell around the browser IDE. It would have
meant writing a file tree, tab bar, search, source control, terminal, settings
and an extension host to arrive at a worse version of something that exists.
VSCodium has the same extension API — so the extension already written *is* the
IDE's intelligence — and no telemetry or marketplace terms, which is what makes
it installable somewhere that has to account for everything leaving its network.

The provisioner is a guest in an existing configuration: it backs up
`settings.json`, adds only the keys that are missing, never overwrites a value
someone chose, and prints exactly what it did. Telemetry and update settings are
applied to VSCodium only, never to the VS Code someone uses every day.

## Next

The plan is four surfaces — web and Android chat, a VS Code extension, a
desktop IDE, an Android IDE — over one core, with the chat app first and
answers that need no model yet. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
has the reasoning, including which model each surface actually needs and why
that does not match the order they are listed in.

Immediately:

1. **Better code for a how-to.** Three questions in six currently get a
   citation and no snippet, because the example that answers them is a whole
   file longer than 40 lines. Extracting the one function that answers the
   question, and compiling the extract, is what closes that.
3. **The eval set**, before any training: 200 held-out completion cases scored
   on exact match, edit distance, does it parse, does it pass its test.
4. **Corpus generation**, verified by compiling every sample — which needs a
   batch check mode in the compiler to be affordable.
5. **Phase A**, and surfaces 2 and 3 become genuinely generative.

## Layout

```
paRY/config.py         where the repositories are; every path has an env override
paRY/lexicon.py        keywords, builtins and nUlakam, read out of the compiler
paRY/corpus/collect.py the corpus, with provenance and content hashes
paRY/verify/oracle.py  the compiler as a judge
paRY/tokenizer/        training and measurement
paRY/index/            the FTS5 retrieval index, and asking it questions
paRY/answer/           intent routing, and the answer itself
paRY/serve/            the HTTP protocol every client shares
web/                   the chat client, served by that server
android/               the same client in a WebView — unbuilt, see its README
vscode/                the editor extension — installed and activating
desktop/               VSCodium provisioning: the IDE surface
docs/ARCHITECTURE.md   four surfaces, one core, and the build order
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
