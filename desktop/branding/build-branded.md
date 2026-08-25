# Building the eTamil IDE from source

**This has not been run.** The machine it was written on has no Visual Studio
Build Tools, so every command below is reasoned from the vscode build
documentation and VSCodium's own build scripts rather than from a build that
completed. Expect to fix something.

It is the only way to remove the last of the VS Code identity — the window
title, the About box, the executable name, the marketplace. Everything cheaper
is already done in `README.md`.

## What you need

| | |
|---|---|
| Node.js | the version in the source's `.nvmrc` — not the newest |
| Python 3 | for `node-gyp` |
| Visual Studio Build Tools | "Desktop development with C++", including the Windows SDK |
| Disk | ~15 GB, and an hour or two |

## The sequence

```powershell
git clone --depth 1 https://github.com/microsoft/vscode.git etamil-ide-src
cd etamil-ide-src
npm ci
```

Merge the overlay over the source's product.json. It is an overlay rather than
a replacement because the source file carries build metadata that changes
between releases and should not be pinned by us:

```powershell
python ..\paRY\desktop\branding\apply_branding.py --source .
```

That script — which does not exist yet, and is the next thing to write — does
four things:

1. Merges `product.json` over `product.json`, dropping `extensionsGallery`.
2. Copies `icons/etamil.ico` over `resources/win32/code.ico` and the PNGs over
   the other `resources/win32/*` assets, including the file-type icons.
3. Copies `etamil-support`, `pary` and `etamil-theme` into `extensions/` so
   they build in as built-ins.
4. Writes the default settings — `workbench.colorTheme: "eTamil Dark"`,
   `pary.server`, the Tamil font stack — into
   `src/vs/platform/configuration/common/configurationRegistry` defaults, so a
   fresh profile is already the IDE rather than something the installer has to
   patch afterwards.

Then:

```powershell
npm run gulp vscode-win32-x64
npm run gulp vscode-win32-x64-inno-updater
npm run gulp vscode-win32-x64-user-setup   # the installer
```

The result is `..\VSCode-win32-x64\` and a setup `.exe` beside it. That `.exe`
is what replaces the ZIP and `Install.ps1` in `packaging/windows` — at which
point the IDE installs like any other Windows application, with its own entry
in Apps & Features and its own icon, and nothing in it says VS Code.

## What to check when it finishes

- The window title says **eTamil IDE**, not Code or VSCodium
- Help → About names eTamil IDE and does not offer to report an issue to Microsoft
- The Extensions view has **no marketplace** — only Installed and Built-in
- eTamil, paRY and eTamil Dark are listed under Built-in, and cannot be uninstalled
- `%APPDATA%\eTamil IDE\` and `%USERPROFILE%\.etamil-ide\` are where state goes,
  so it does not collide with an existing VS Code install
- The taskbar icon is the mark

## The licensing position, stated once

The vscode source is MIT, and building it yourself is the arrangement VSCodium
already relies on. Two things are **not** MIT and must not be carried across:
Microsoft's trademarks and icons, which is why `resources/win32/*` is replaced
rather than kept; and Microsoft's marketplace, whose terms permit its use only
from Microsoft's own products, which is why `extensionsGallery` is dropped and
every third-party extension in the package comes from Open VSX.
