/**
 * Which editor is code going into?
 *
 * `vscode.window.activeTextEditor` is undefined while a webview has focus, and
 * the whole point of this panel is that you click a button in it. So the last
 * text editor to be active is remembered, and that is the one an insertion
 * targets — the same thing Copilot's chat does, and for the same reason.
 */

import * as vscode from "vscode";
import { forInsertion, indentBlock, indentOf } from "./text";

let remembered: vscode.TextEditor | undefined;

export function trackEditors(context: vscode.ExtensionContext): void {
  remembered = vscode.window.activeTextEditor;
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor((editor) => {
      // Undefined means focus moved to a webview or a settings tab. That is
      // not a reason to forget where the code was going.
      if (editor) {
        remembered = editor;
      }
    }),
  );
}

/** The editor an insertion should target, if there is still one open. */
export function targetEditor(): vscode.TextEditor | undefined {
  if (remembered && !remembered.document.isClosed) {
    return remembered;
  }
  return vscode.window.activeTextEditor;
}

export type Placement = "insert" | "replace";

/**
 * Put code in the editor: at the cursor, or over the selection.
 *
 * Returns what happened, so the caller can say so rather than failing silently
 * — an assistant that appears to do nothing is worse than one that refuses.
 */
export async function place(code: string, how: Placement): Promise<string> {
  const editor = targetEditor();
  if (!editor) {
    return "no editor is open to put that in";
  }

  const selection = editor.selection;
  if (how === "replace" && selection.isEmpty) {
    how = "insert";
  }

  const anchor = how === "replace" ? selection.start : selection.active;
  const indent = indentOf(editor.document.lineAt(anchor.line).text);
  const body = indentBlock(forInsertion(code), indent);

  const applied = await editor.edit((builder) => {
    if (how === "replace") {
      builder.replace(selection, body);
    } else {
      builder.insert(anchor, body);
    }
  });

  if (!applied) {
    return "the editor refused the edit";
  }

  await vscode.window.showTextDocument(editor.document, editor.viewColumn);
  editor.revealRange(new vscode.Range(anchor, anchor), vscode.TextEditorRevealType.InCenterIfOutsideViewport);
  const lines = body.split("\n").length;
  return `${how === "replace" ? "replaced the selection with" : "inserted"} ${lines} line${
    lines === 1 ? "" : "s"
  } in ${vscode.workspace.asRelativePath(editor.document.uri)}`;
}
