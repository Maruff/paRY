/**
 * Inline completion — the Copilot-shaped part, and the part that is not ready.
 *
 * The provider is registered anyway and asks the server once. The server
 * answers 501 because the Phase A model is not trained, so this stops asking
 * and says so once. When the model exists, nothing here changes: the same call
 * starts returning completions.
 *
 * What it deliberately does not do is fall back to retrieval. A plausible line
 * pulled from a similar example is worse than no line at all — an editor that
 * inserts a wrong keyword teaches the wrong keyword, and the developer blames
 * the language rather than the assistant.
 */

import * as vscode from "vscode";
import { NotImplemented, ParyClient } from "./client";

export class InlineCompletions implements vscode.InlineCompletionItemProvider {
  private unavailable = false;
  /**
   * One request outstanding at a time.
   *
   * Without this, "ask once and stop" is a race rather than a rule: VS Code
   * fires the provider on consecutive keystrokes, and every request dispatched
   * before the first 501 comes back is another 501 and another popup. The
   * server log showed exactly two on a single file open.
   */
  private outstanding = false;

  constructor(private readonly client: ParyClient) {}

  async provideInlineCompletionItems(
    document: vscode.TextDocument,
    position: vscode.Position,
    _context: vscode.InlineCompletionContext,
    token: vscode.CancellationToken,
  ): Promise<vscode.InlineCompletionItem[]> {
    const enabled = vscode.workspace
      .getConfiguration("pary")
      .get<boolean>("inlineCompletion.enabled", true);
    if (this.unavailable || !enabled || this.outstanding) {
      return [];
    }

    const prefix = document.getText(new vscode.Range(document.positionAt(0), position));
    const suffix = document.getText(
      new vscode.Range(position, document.lineAt(document.lineCount - 1).range.end),
    );

    this.outstanding = true;
    try {
      const result = await this.client.complete(prefix, suffix, document.uri.fsPath);
      if (token.isCancellationRequested || !result.completion) {
        return [];
      }
      return [new vscode.InlineCompletionItem(result.completion, new vscode.Range(position, position))];
    } catch (cause) {
      if (cause instanceof NotImplemented) {
        this.unavailable = true;
        void vscode.window.showInformationMessage(`paRY: ${cause.message}`);
      }
      // Any other failure — server down, timeout — is silent. A completion
      // provider that pops a dialog while someone is typing is unusable.
      return [];
    } finally {
      this.outstanding = false;
    }
  }
}
