/**
 * The paRY protocol, typed once.
 *
 * These are the shapes the server declares in `paRY/serve/app.py`. Every
 * client — web, Android, this — speaks the same four endpoints, which is the
 * reason the protocol was settled before any of them were written.
 *
 * All HTTP happens in the extension host rather than in the webview. That is
 * not incidental: the webview then never talks to the network, so there is no
 * origin to allow and no CORS to configure, and the panel cannot reach anything
 * the extension has not decided to fetch.
 */

import * as vscode from "vscode";

export interface Citation {
  title: string;
  path: string | null;
  line: number | null;
  kind: string;
}

export interface Answer {
  intent: string;
  locale: string;
  text: string;
  code: string | null;
  code_compiles: boolean;
  citations: Citation[];
  confidence: string;
}

export interface Diagnostic {
  line: number | null;
  column: number | null;
  message: string;
  raw: string;
}

export interface DiagnoseResult {
  ok: boolean;
  timed_out: boolean;
  diagnostics: Diagnostic[];
}

export interface Health {
  version: string;
  compiler: string | null;
  index: string | null;
  chunks: number | null;
  model: string | null;
}

/** A refusal the caller is expected to handle rather than report as a fault. */
export class NotImplemented extends Error {}

export class ParyClient {
  private get base(): string {
    const configured = vscode.workspace
      .getConfiguration("pary")
      .get<string>("server", "http://127.0.0.1:8900");
    return configured.replace(/\/+$/, "");
  }

  /** The configured locale, or undefined to let the server match the question. */
  private get locale(): "en" | "ta" | undefined {
    const setting = vscode.workspace.getConfiguration("pary").get<string>("locale", "auto");
    return setting === "en" || setting === "ta" ? setting : undefined;
  }

  async health(): Promise<Health> {
    return this.request<Health>("GET", "/health");
  }

  async ask(question: string, source?: string): Promise<Answer> {
    return this.request<Answer>("POST", "/ask", {
      question,
      source: source ?? null,
      locale: this.locale ?? null,
    });
  }

  async diagnose(source: string): Promise<DiagnoseResult> {
    return this.request<DiagnoseResult>("POST", "/diagnose", { source });
  }

  /**
   * Fill in the middle. Throws {@link NotImplemented} until the Phase A model
   * exists — the server says 501 rather than returning a guess, because an
   * editor that inserts a wrong line teaches the wrong line.
   */
  async complete(prefix: string, suffix: string, path?: string): Promise<{ completion: string }> {
    return this.request("POST", "/complete", { prefix, suffix, path: path ?? null });
  }

  private async request<T>(method: "GET" | "POST", path: string, body?: unknown): Promise<T> {
    // Built up rather than declared in one literal: under
    // `exactOptionalPropertyTypes`, a `body` that is explicitly `undefined` is
    // not the same as an absent one, and `RequestInit` will not take it.
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.headers = { "Content-Type": "application/json" };
      init.body = JSON.stringify(body);
    }

    let response: Response;
    try {
      response = await fetch(`${this.base}${path}`, init);
    } catch (cause) {
      throw new Error(
        `paRY is not answering at ${this.base}. Start one with \`python -m paRY.serve\`. (${String(cause)})`,
      );
    }

    if (response.status === 501) {
      throw new NotImplemented(await detail(response));
    }
    if (!response.ok) {
      throw new Error(await detail(response));
    }
    return (await response.json()) as T;
  }
}

async function detail(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: string };
    if (body.detail) {
      return body.detail;
    }
  } catch {
    // A body that is not JSON tells us nothing the status line does not.
  }
  return `${response.status} ${response.statusText}`;
}
