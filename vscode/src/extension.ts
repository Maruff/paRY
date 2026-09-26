/**
 * paRY in VS Code.
 *
 * Three things, in the order they are worth having:
 *
 * 1. **Diagnostics.** The compiler's own errors, in the editor, as you type.
 *    Not a prediction — `etamil --check` said it, bilingually, with a line and
 *    a column. This needs no model and never will.
 * 2. **A chat panel.** The same answer engine the web client uses: symbol
 *    lookups out of the compiler's tables, retrieval over the corpus, and a
 *    named fix for the mistakes that are worth recognising by name.
 * 3. **Inline completion**, registered and refusing, until Phase A exists.
 *
 * It does not contribute a grammar, keywords or hovers. The `etamil-support`
 * extension already generates those from `lexer.rs`, so they cannot drift;
 * duplicating them here would be the exact mistake that extension was written
 * to fix.
 */

import * as vscode from "vscode";
import { ParyClient } from "./client";
import { InlineCompletions } from "./completion";
import { DiagnosticRunner, ETAMIL, isEtamil } from "./diagnostics";
import { showExtensions } from "./extensions";
import { trackEditors } from "./editors";
import { ChatPanel, activeSource } from "./panel";

/**
 * The language extension, which already compiles on type using the local
 * binary. Two extensions publishing the same compiler's errors would paint
 * every mistake twice.
 */
const LANGUAGE_EXTENSION = "etamil.etamil-support";

export function activate(context: vscode.ExtensionContext): void {
  const client = new ParyClient();
  const panel = new ChatPanel(context.extensionUri, client);
  const diagnostics = new DiagnosticRunner(client);

  if (shouldRunDiagnostics()) {
    diagnostics.register(context);
  }

  // Which file an insertion targets has to be remembered before the panel
  // takes focus, because that is when activeTextEditor becomes undefined.
  trackEditors(context);

  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  status.command = "pary.checkServer";
  context.subscriptions.push(status);
  void refreshStatus(client, status);

  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatPanel.viewId, panel),

    vscode.languages.registerInlineCompletionItemProvider(ETAMIL, new InlineCompletions(client)),

    vscode.commands.registerCommand("pary.ask", async () => {
      const question = await vscode.window.showInputBox({
        prompt: "Ask paRY",
        placeHolder: "how do I write a row to a CSV file  /  நீளம்",
      });
      if (question) {
        await panel.ask(question, activeSource());
      }
    }),

    vscode.commands.registerCommand("pary.generate", async () => {
      const request = await vscode.window.showInputBox({
        prompt: "What should paRY write?",
        placeHolder: "a function that totals an array  /  ஒரு CSV வரியை எழுது",
      });
      if (request) {
        await panel.generate(request, activeSource());
      }
    }),

    vscode.commands.registerCommand("pary.explain", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !isEtamil(editor.document)) {
        void vscode.window.showInformationMessage("paRY: open an eTamil file first.");
        return;
      }
      const selection = editor.document.getText(editor.selection);
      await panel.ask("what does this do", selection.trim() || editor.document.getText());
    }),

    vscode.commands.registerCommand("pary.diagnose", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor || !isEtamil(editor.document)) {
        void vscode.window.showInformationMessage("paRY: open an eTamil file first.");
        return;
      }
      // Through /ask rather than /diagnose, because the answer engine adds the
      // named fix — "மாறி is a token but not a statement prefix" — on top of
      // the compiler's message. The squiggles come from the runner separately.
      await Promise.all([
        panel.ask("why does this fail", editor.document.getText()),
        diagnostics.run(editor.document),
      ]);
    }),

    vscode.commands.registerCommand("pary.extensions", showExtensions),

    vscode.commands.registerCommand("pary.checkServer", async () => {
      try {
        const health = await client.health();
        // Both versions, each labelled. They are different things and they
        // move independently: the server is the Python package, this is the
        // extension. One unlabelled number here read as the other cost a
        // reinstall that had already worked.
        void vscode.window.showInformationMessage(
          `paRY server ${health.version} · extension ${extensionVersion(context)} · ` +
            `${health.compiler ?? "no compiler"} · ` +
            `${health.chunks ?? 0} chunks · ` +
            `${health.model ?? "no model — compiler and corpus only"}`,
        );
      } catch (cause) {
        void vscode.window.showErrorMessage(String(cause));
      }
      await refreshStatus(client, status);
    }),

    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("pary.server")) {
        void refreshStatus(client, status);
      }
    }),
  );
}

export function deactivate(): void {
  // The diagnostic collection and every listener are disposed by the context.
}

/**
 * Stand down when the language extension is already doing this.
 *
 * `etamil-support` runs the compiler locally on type and publishes the same
 * errors. Both of us reporting them means two squiggles and two hovers saying
 * the same thing, and the person seeing it has no way to know why. Its version
 * is the better one to keep, too: it does not need a server running.
 *
 * A setting the user has actually written down wins over this — `inspect`
 * distinguishes a value someone chose from the manifest default.
 */
/** This extension's own version, for the status message that reports both. */
function extensionVersion(context: vscode.ExtensionContext): string {
  const version: unknown = context.extension.packageJSON?.version;
  return typeof version === "string" ? version : "unknown";
}

function shouldRunDiagnostics(): boolean {
  const setting = vscode.workspace.getConfiguration("pary").inspect<boolean>("diagnostics.enabled");
  const chosen =
    setting?.globalValue ?? setting?.workspaceValue ?? setting?.workspaceFolderValue;
  if (chosen !== undefined) {
    return chosen;
  }
  return vscode.extensions.getExtension(LANGUAGE_EXTENSION) === undefined;
}

/**
 * The status bar says what is answering, and it says when nothing is.
 *
 * `model: null` is shown as words rather than hidden: someone reading an
 * answer should never have to work out whether a model wrote it.
 */
async function refreshStatus(client: ParyClient, status: vscode.StatusBarItem): Promise<void> {
  try {
    const health = await client.health();
    status.text = health.model ? "$(circuit-board) paRY" : "$(book) paRY";
    status.tooltip = `${health.compiler ?? "no compiler"} · ${health.chunks ?? 0} chunks · ${
      health.model ?? "no model — compiler and corpus only"
    }`;
    status.backgroundColor = undefined;
  } catch {
    status.text = "$(warning) paRY";
    status.tooltip = "No paRY server. Start one with `python -m paRY.serve`.";
    status.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }
  status.show();
}
