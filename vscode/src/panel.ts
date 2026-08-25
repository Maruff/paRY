/**
 * The chat side panel.
 *
 * The webview holds no network access and no secrets: it posts a question to
 * the extension host, the host talks to the paRY server and posts the answer
 * back. Content security policy allows only this extension's own scripts, with
 * a nonce.
 */

import * as vscode from "vscode";
import { Answer, ParyClient } from "./client";

type Incoming =
  | { type: "ready" }
  | { type: "ask"; question: string; includeSource: boolean };

export class ChatPanel implements vscode.WebviewViewProvider {
  public static readonly viewId = "pary.chat";

  private view: vscode.WebviewView | undefined;

  constructor(
    private readonly extensionUri: vscode.Uri,
    private readonly client: ParyClient,
  ) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.extensionUri, "media")],
    };
    view.webview.html = this.html(view.webview);
    view.webview.onDidReceiveMessage((message: Incoming) => {
      if (message.type === "ready") {
        void this.reportHealth();
      } else if (message.type === "ask") {
        void this.ask(message.question, message.includeSource ? activeSource() : undefined);
      }
    });
  }

  /** Put a question to paRY, opening the panel if it is not showing. */
  async ask(question: string, source?: string): Promise<void> {
    await vscode.commands.executeCommand(`${ChatPanel.viewId}.focus`);
    this.post({ type: "asked", question, withSource: source !== undefined });
    try {
      const answer: Answer = await this.client.ask(question, source);
      this.post({ type: "answer", answer });
    } catch (cause) {
      this.post({ type: "error", message: String(cause) });
    }
  }

  private async reportHealth(): Promise<void> {
    try {
      this.post({ type: "health", health: await this.client.health() });
    } catch (cause) {
      this.post({ type: "error", message: String(cause) });
    }
  }

  private post(message: unknown): void {
    void this.view?.webview.postMessage(message);
  }

  private html(webview: vscode.Webview): string {
    const nonce = randomNonce();
    const asset = (name: string): vscode.Uri =>
      webview.asWebviewUri(vscode.Uri.joinPath(this.extensionUri, "media", name));

    return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none';
  style-src ${webview.cspSource}; script-src 'nonce-${nonce}'; font-src ${webview.cspSource};">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="${asset("panel.css")}">
</head>
<body>
<div id="health" class="health">…</div>
<div id="transcript"></div>
<form id="composer">
  <textarea id="question" rows="2" placeholder="Ask paRY…  /  paRY இடம் கேளுங்கள்…"
            aria-label="Your question"></textarea>
  <label class="include">
    <input type="checkbox" id="include-source" checked>
    send the open file
  </label>
  <button type="submit">Ask</button>
</form>
<script nonce="${nonce}" src="${asset("panel.js")}"></script>
</body>
</html>`;
  }
}

/** The file the developer is looking at, if it is eTamil. */
export function activeSource(): string | undefined {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    return undefined;
  }
  const document = editor.document;
  if (document.languageId !== "etamil" && !document.uri.fsPath.endsWith(".qmz")) {
    return undefined;
  }
  return document.getText();
}

function randomNonce(): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  let nonce = "";
  for (let index = 0; index < 32; index += 1) {
    nonce += alphabet.charAt(Math.floor(Math.random() * alphabet.length));
  }
  return nonce;
}
