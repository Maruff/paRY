# paRY for VS Code

An eTamil assistant in the editor. No hosted model is called at any point:
answers come from the eTamil compiler and from paRY's index of the corpus.

## Status

**Typechecks and compiles; never run in an extension host.** `tsc --noEmit`
passes under `strict` and `exactOptionalPropertyTypes`, and `npm run compile`
produces `out/`. What has not happened is F5 in VS Code — no editor was
available on the machine that wrote it.

The layer between this extension and the server *is* checked: a script drove a
live paRY server through every call `src/client.ts` makes and confirmed all 26
field shapes it depends on, including that `/complete` answers 501 with a
`detail` string, that diagnostics arrive 1-based and bilingual with a leading
`✗`, and that no answer ever carries code the server has not compiled.

## What it gives you

**Diagnostics.** The compiler's errors in the editor as you type, debounced.
Bilingual, with the line and column the compiler reported. This is not a
prediction — `etamil --check` said it — and it will never need a model.

**A chat panel** in the activity bar. The same answer engine the web client
uses: symbol lookups read out of the compiler's own tables, retrieval over 1,721
corpus chunks, and named fixes for the mistakes worth recognising by name. Code
in an answer carries the server's ✓ compiles verdict; the panel cannot mark
something as compiling by itself.

**Inline completion**, registered and refusing. The server answers `501` because
the Phase A model is not trained, so paRY says so once and stops asking. It does
not fall back to retrieval: a plausible line pulled from a similar example is
worse than no line, because an editor that inserts a wrong keyword teaches the
wrong keyword and the developer blames the language.

## What it does not do

It contributes no grammar, no keywords, no hovers. The `etamil-support`
extension in the eTamil repository already generates those from `lexer.rs`, so
they cannot drift from the compiler. Duplicating them here would be the exact
mistake that extension exists to correct — install both.

## Running it

```bash
cd vscode
npm install
npm run compile
```

Then F5 in VS Code to open an extension development host. You also need a paRY
server:

```bash
python -m paRY.serve
```

`pary.server` points at it; everything else is optional.

| Setting | Default | |
|---|---|---|
| `pary.server` | `http://127.0.0.1:8900` | where the server is |
| `pary.diagnostics.enabled` | `true` | compile as you type |
| `pary.diagnostics.delay` | `600` | ms to wait after a keystroke |
| `pary.inlineCompletion.enabled` | `true` | ask `/complete` (501 until Phase A) |
| `pary.locale` | `auto` | answer in English, Tamil, or match the question |

Commands: **Ask a question**, **Explain this**, **Why does this not compile?**,
**Check the server**. The last two are also on the editor context menu for
`.qmz` files.

## Two decisions worth knowing

**All HTTP happens in the extension host, never in the webview.** The panel
posts a question to the host and renders what comes back, so there is no origin
to allow, no CORS to configure, and the panel cannot reach anything the
extension has not decided to fetch. Its content security policy admits only this
extension's own scripts, under a nonce.

**The status bar states what is answering.** `no model — compiler and corpus
only`, in words. Someone reading an answer should never have to work out whether
a model wrote it.
