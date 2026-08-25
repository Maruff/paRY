/**
 * The IDE's extension list, which is a fixed list.
 *
 * The branded build has no marketplace: nothing is discoverable, nothing
 * updates itself, and nothing arrives that the institution did not put in the
 * package. That is the point — an editor that can install anything is an
 * editor that can install anything, and this one is meant to be deployable
 * where that sentence is a problem.
 *
 * So the four optional extensions ship as .vsix files beside the install and
 * are turned on from here. `pary.extensionsPath` is written by the installer;
 * without it this command says so rather than pretending to offer something.
 */

import * as vscode from "vscode";

interface Catalogued {
  id: string;
  title: string;
  role: string;
  why?: string;
  version?: string;
  license?: string;
  source: string;
}

interface Catalogue {
  installed: Catalogued[];
  optional: Catalogued[];
}

async function readCatalogue(folder: vscode.Uri): Promise<Catalogue | undefined> {
  try {
    const raw = await vscode.workspace.fs.readFile(vscode.Uri.joinPath(folder, "extensions.json"));
    return JSON.parse(new TextDecoder().decode(raw)) as Catalogue;
  } catch {
    return undefined;
  }
}

/** The .vsix for one entry, matched on the file name the fetcher writes. */
async function packageFor(folder: vscode.Uri, entry: Catalogued): Promise<vscode.Uri | undefined> {
  try {
    const files = await vscode.workspace.fs.readDirectory(folder);
    const wanted = `${entry.id}-`.toLowerCase();
    const match = files.find(
      ([name, kind]) =>
        kind === vscode.FileType.File &&
        name.toLowerCase().startsWith(wanted) &&
        name.toLowerCase().endsWith(".vsix"),
    );
    return match ? vscode.Uri.joinPath(folder, match[0]) : undefined;
  } catch {
    return undefined;
  }
}

export async function showExtensions(): Promise<void> {
  const configured = vscode.workspace.getConfiguration("pary").get<string>("extensionsPath", "");
  if (!configured) {
    void vscode.window.showInformationMessage(
      "This build has no extension folder configured, so there is nothing to add. " +
        "`pary.extensionsPath` is normally set by the installer.",
    );
    return;
  }

  const folder = vscode.Uri.file(configured);
  const catalogue = await readCatalogue(folder);
  if (!catalogue) {
    void vscode.window.showWarningMessage(`No extension catalogue in ${configured}.`);
    return;
  }

  const items: (vscode.QuickPickItem & { entry?: Catalogued; file?: vscode.Uri })[] = [];
  for (const entry of catalogue.optional) {
    const already = vscode.extensions.getExtension(entry.id) !== undefined;
    const file = await packageFor(folder, entry);
    items.push({
      label: already ? `$(check) ${entry.title}` : `$(add) ${entry.title}`,
      description: already ? "installed" : entry.version ? `v${entry.version} · ${entry.license}` : "",
      detail: entry.why ?? "",
      entry,
      ...(file ? { file } : {}),
    });
  }

  const chosen = await vscode.window.showQuickPick(items, {
    title: "eTamil — languages you can turn on",
    placeHolder: "Everything here ships with the IDE. Nothing is downloaded.",
  });
  if (!chosen?.entry) {
    return;
  }

  if (vscode.extensions.getExtension(chosen.entry.id)) {
    void vscode.window.showInformationMessage(`${chosen.entry.title} is already installed.`);
    return;
  }
  if (!chosen.file) {
    void vscode.window.showWarningMessage(
      `${chosen.entry.title} is listed but its .vsix is not in ${configured}.`,
    );
    return;
  }

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `Installing ${chosen.entry.title}…` },
    async () => {
      await vscode.commands.executeCommand("workbench.extensions.installExtension", chosen.file);
    },
  );
  void vscode.window.showInformationMessage(
    `${chosen.entry.title} installed. Reload the window to start using it.`,
  );
}
