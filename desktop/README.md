# The eTamil desktop IDE

An eTamil IDE for Windows and Linux: **VSCodium**, plus the two extensions that
already exist, plus a profile that makes it an eTamil environment rather than a
text editor that happens to open `.qmz`.

```bash
python desktop/provision.py --dry-run   # say what it would do
python desktop/provision.py             # build, install, configure
```

## Why VSCodium rather than an IDE of our own

The tempting answer was a Tauri shell around the browser IDE at
`eTamil_site/ide/`. It would have been ours, and small. It would also have meant
writing, and then maintaining, a file tree, a tab bar, search, source control, a
terminal, a settings system and an extension host — to arrive at a worse version
of something that already exists.

VSCodium is that something, with the three properties this project actually
needs:

- **The same extension API**, so the VS Code extension already written *is* the
  IDE's intelligence. Nothing is built twice, and a fix to `vscode/` is a fix to
  the desktop IDE.
- **No telemetry and no marketplace terms.** VSCodium is the Microsoft source
  built without the Microsoft branding, telemetry and gallery. For an
  institution under RBI data localisation that has to account for everything
  leaving its network, "the editor phones home" is not a footnote. It is also
  why the extensions here ship as `.vsix` files rather than from a marketplace:
  Microsoft's gallery is not licensed for non-Microsoft builds, and an
  air-gapped bank could not reach it anyway.
- **Windows and Linux from one build**, which is what was asked for.

The whole desktop surface is therefore a provisioning script and a profile.
That is the honest size of the job once the extension exists.

## What the profile does

`profile/settings.json` — applied to any editor:

| | |
|---|---|
| `files.associations` | `.qmz` is eTamil even without the language extension |
| `[etamil]` | four-space indent, wrap on, ligatures off |
| `editor.fontFamily` | a Tamil face after the monospace ones, so Tamil in code is not tofu |
| `editor.unicodeHighlight.allowedLocales` | stop VS Code flagging Tamil letters as suspicious |
| `pary.server`, `pary.locale` | where the assistant is |
| `etamil.checkOnType` | the language extension compiles as you type |

`profile/settings.codium.json` — **only** when provisioning VSCodium: telemetry
off, updates manual, no automatic extension update checks. Those are right for
an IDE handed to a team and wrong to do behind someone's back to the VS Code
they use every day, so they are not applied to `code`.

`profile/keybindings.json`:

| | |
|---|---|
| <kbd>F5</kbd> | run this file (`etamil.run`) |
| <kbd>Ctrl</kbd>+<kbd>F5</kbd> | serve this file (`etamil.serve`) |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>P</kbd> | ask paRY |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>E</kbd> | explain the selection |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>D</kbd> | why does this not compile |

## It is a guest in an existing configuration

The provisioner **never overwrites a setting that already has a value.** It
backs up `settings.json` first, then adds only the keys that are missing, and
prints exactly what it added. Run it against an editor someone already uses and
the worst case is that it adds nothing.

It refuses rather than guessing if `settings.json` contains comments — VS Code
allows them, `json` does not parse them, and silently rewriting someone's
commented settings file would be worse than stopping.

## The three parts, and who owns them

| | Lives in | Provides |
|---|---|---|
| `etamil-support` | `eTamil/eTamil_Code` | grammar, snippets, hovers, run/serve, compile-on-type — all generated from `lexer.rs`, so they cannot drift |
| `pary` | `paRY/vscode` | the chat panel, named fixes, and completion when Phase A exists |
| the profile | here | the settings and keys that join them |

paRY stands down from publishing diagnostics when `etamil-support` is
installed, because that extension already compiles on type using the local
binary and two extensions reporting the same compiler's errors means two
squiggles on every mistake.

## What still needs a person

The compiler itself. `etamil.compilerPath` points the language extension at
`etamil`, and `python -m paRY.serve` needs the compiler on the machine running
it. Neither is bundled here — building the compiler is the eTamil repository's
job, and pretending otherwise would put two copies of that decision in the
world.
