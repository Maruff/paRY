# Making it the eTamil IDE, and not VS Code

Three layers, and they are worth separating because only the third one is
expensive.

| Layer | Removes | Cost | Built here? |
|---|---|---|---|
| Theme and icons | the *look* of VS Code | minutes | ✅ done |
| Extension policy | the marketplace, and every extension you did not choose | minutes | ✅ done |
| A branded build | the name, the logo, the window title, the About box | a source build, 1–2 hours | ✍️ scripted, **never run here** |

## What is done

**The mark.** `brand.py` draws the logo in code and generates every size from
it — `etamil.ico` for Windows, PNGs for the editor, transparent versions for
anywhere the app paints its own background. One definition, so the icon and the
palette cannot drift apart. Adjust the drawing, re-run, everything regenerates.

**The palette**, read off the logo and written to `icons/palette.json`:

| | | |
|---|---|---|
| `#0A2240` | navy | the field the mark sits on, and the editor background |
| `#071A31` | deep navy | side bar, panels, title bar |
| `#3B82F6` | blue | the bar in the mark; buttons, cursor, status bar |
| `#1E9BE9` | bright blue | the wordmark's blue; keywords and links |
| `#FFFFFF` | white | the rings |

**The theme.** `theme/` is a real extension contributing *eTamil Dark* — 129
colour keys, so the whole window is the brand rather than the editor's default
with a different accent. Keywords take the wordmark blue, because in eTamil the
keywords are the Tamil.

**The extension policy.** `extensions.json` is the whole list: three installed
with the IDE, four the developer turns on. Everything is fetched from Open VSX
with pinned versions — Microsoft's gallery terms do not cover non-Microsoft
builds, and an air-gapped bank could not reach it anyway.

| | Extension | |
|---|---|---|
| installed | eTamil | the language, generated from `lexer.rs` |
| installed | paRY | the assistant; its chat opens on the right |
| installed | GitHub | `GitHub.vscode-pull-request-github`, MIT |
| optional | Rust | `rust-lang.rust-analyzer` |
| optional | Python | `ms-python.python`, MIT on Open VSX |
| optional | Node.js | `dbaeumer.vscode-eslint` — debugging is already built in, so the linter is the useful addition |
| optional | React | `dsznajder.es7-react-js-snippets` |

The four optional ones ship as `.vsix` inside the package and are turned on
from **eTamil: Languages you can turn on**. Nothing is downloaded, nothing is
discoverable, and nothing arrives that was not in the package.

## What is scripted but unbuilt

Everything above still runs *inside* VSCodium, which says VSCodium in its title
bar and its About box. Removing that means building the editor from source with
our own `product.json` — which is exactly what VSCodium itself is, so the path
is well travelled rather than novel.

`product.json` in this folder is that overlay. The parts that matter:

- `nameShort` / `nameLong` — "eTamil" and "eTamil IDE", which set the window
  title, the About box and the installer
- `applicationName`, `dataFolderName`, `serverApplicationName` — so the CLI is
  `etamil-ide` and settings live in `.etamil-ide` rather than `.vscode`
- `win32*` identifiers, `win32ShellNameShort`, and the icon paths — the Start
  Menu entry, the file associations and the executable's icon
- **`extensionsGallery` removed entirely** — with no gallery there is no
  Extensions marketplace to browse, which is what makes the list above the
  whole list
- `extensionAllowedProposedApi`, `builtInExtensions` — the eTamil, paRY and
  theme extensions ship as built-ins, so they do not appear as things someone
  installed and cannot be uninstalled by accident

`build-branded.md` is the sequence. It needs Node, Python, and Visual Studio
Build Tools, downloads several gigabytes, and takes an hour or two. **None of it
has been run**, because this machine has no VS Build Tools — so treat that
document as a recipe that has been written carefully rather than one that has
been followed.

## The honest summary

Someone opening the IDE today sees eTamil's colours, eTamil's icon on the
taskbar, four extensions and no marketplace. They also see "VSCodium" if they
open the About box or look closely at the window title. The build recipe closes
that last gap and is the only part still owed.
