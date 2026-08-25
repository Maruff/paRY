/**
 * The compiler's own errors, in the editor, as you type.
 *
 * This is the part of paRY that does not need a model and never will: the
 * answer to "why does this not compile" is not a prediction, it is what
 * `etamil --check` says. The messages arrive bilingual from the compiler and
 * are shown that way, because that is how the language reports them.
 */

import * as vscode from "vscode";
import { ParyClient } from "./client";

/** eTamil files, whether or not the language extension is installed. */
export const ETAMIL: vscode.DocumentSelector = [
  { language: "etamil" },
  { scheme: "file", pattern: "**/*.qmz" },
];

export function isEtamil(document: vscode.TextDocument): boolean {
  return document.languageId === "etamil" || document.uri.fsPath.endsWith(".qmz");
}

export class DiagnosticRunner {
  private readonly collection = vscode.languages.createDiagnosticCollection("paRY");
  private readonly pending = new Map<string, NodeJS.Timeout>();
  /** Stop reporting the same unreachable server on every keystroke. */
  private complainedAbout: string | null = null;

  constructor(private readonly client: ParyClient) {}

  register(context: vscode.ExtensionContext): void {
    context.subscriptions.push(
      this.collection,
      vscode.workspace.onDidChangeTextDocument((event) => this.schedule(event.document)),
      vscode.workspace.onDidOpenTextDocument((document) => this.schedule(document)),
      vscode.workspace.onDidCloseTextDocument((document) => {
        this.cancel(document);
        this.collection.delete(document.uri);
      }),
      { dispose: () => this.pending.forEach(clearTimeout) },
    );
    vscode.workspace.textDocuments.forEach((document) => this.schedule(document));
  }

  private enabled(): boolean {
    return vscode.workspace.getConfiguration("pary").get<boolean>("diagnostics.enabled", true);
  }

  private delay(): number {
    return vscode.workspace.getConfiguration("pary").get<number>("diagnostics.delay", 600);
  }

  private cancel(document: vscode.TextDocument): void {
    const key = document.uri.toString();
    const timer = this.pending.get(key);
    if (timer) {
      clearTimeout(timer);
      this.pending.delete(key);
    }
  }

  /** Debounced: one compile per pause, not one per keystroke. */
  schedule(document: vscode.TextDocument): void {
    if (!isEtamil(document) || !this.enabled()) {
      return;
    }
    this.cancel(document);
    const key = document.uri.toString();
    this.pending.set(
      key,
      setTimeout(() => {
        this.pending.delete(key);
        void this.run(document);
      }, this.delay()),
    );
  }

  async run(document: vscode.TextDocument): Promise<void> {
    const source = document.getText();
    if (source.trim() === "") {
      this.collection.delete(document.uri);
      return;
    }

    try {
      const result = await this.client.diagnose(source);
      this.complainedAbout = null;
      this.collection.set(document.uri, result.diagnostics.map((item) => toDiagnostic(document, item)));
    } catch (cause) {
      // A server that is down should not paint the file with fake errors, and
      // should not shout once per keystroke either.
      this.collection.delete(document.uri);
      const message = String(cause);
      if (this.complainedAbout !== message) {
        this.complainedAbout = message;
        void vscode.window.showWarningMessage(message);
      }
    }
  }
}

/**
 * The compiler counts lines and columns from one; VS Code counts from zero.
 *
 * A diagnostic with no position — the compiler could not place it — is put on
 * the first line rather than dropped, because an error nobody can see is worse
 * than an error in the wrong place.
 */
export function toDiagnostic(
  document: vscode.TextDocument,
  item: { line: number | null; column: number | null; raw: string; message: string },
): vscode.Diagnostic {
  const line = Math.min(Math.max((item.line ?? 1) - 1, 0), Math.max(document.lineCount - 1, 0));
  const text = document.lineAt(line);
  const column = Math.min(Math.max((item.column ?? 1) - 1, 0), text.range.end.character);
  const range = new vscode.Range(
    new vscode.Position(line, column),
    text.range.end.character > column ? text.range.end : new vscode.Position(line, column + 1),
  );

  const diagnostic = new vscode.Diagnostic(
    range,
    item.raw.replace(/^✗\s*/, ""),
    vscode.DiagnosticSeverity.Error,
  );
  diagnostic.source = "paRY · etamil --check";
  return diagnostic;
}
