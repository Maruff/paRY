/* The panel's own script.
 *
 * It never touches the network: it posts a question to the extension host, and
 * the host talks to the paRY server. The markdown renderer is a near-copy of
 * the one in `web/app.js` — the same forty lines, duplicated deliberately,
 * because a build step to share one module between two very different hosts
 * costs more than the copy does.
 */

const vscode = acquireVsCodeApi();

const transcript = document.getElementById("transcript");
const composer = document.getElementById("composer");
const questionField = document.getElementById("question");
const includeSource = document.getElementById("include-source");
const askButton = composer.querySelector("button");
const healthBox = document.getElementById("health");

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[char]);
}

function inline(text) {
  return escapeHtml(text)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
}

function renderMarkdown(markdown) {
  const out = [];
  let list = null;
  const closeList = () => {
    if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
  };

  markdown.split(/```/).forEach((segment, index) => {
    if (index % 2 === 1) {
      closeList();
      const body = segment.replace(/^[a-zA-Z]*\n/, "").replace(/\n$/, "");
      out.push(`<pre><code>${escapeHtml(body)}</code></pre>`);
      return;
    }
    for (const line of segment.split("\n")) {
      const heading = line.match(/^(#{2,3})\s+(.*)$/);
      const bullet = line.match(/^[-*]\s+(.*)$/);
      if (heading) {
        closeList();
        const level = heading[1].length;
        out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      } else if (bullet) {
        (list ??= []).push(`<li>${inline(bullet[1])}</li>`);
      } else if (line.trim() === "") {
        closeList();
      } else {
        closeList();
        out.push(`<p>${inline(line)}</p>`);
      }
    }
  });
  closeList();
  return out.join("");
}

/* Set scrollTop rather than scrollIntoView({behavior:"smooth"}): the smooth
 * form silently does nothing in some embedded webviews, and this is one. */
function scrollToLatest() {
  transcript.scrollTop = transcript.scrollHeight;
}

function add(className, html) {
  const node = document.createElement("div");
  node.className = className;
  node.innerHTML = html;
  transcript.append(node);
  scrollToLatest();
  return node;
}

let pending = null;

function renderAnswer(answer) {
  const node = pending ?? add("message assistant", "");
  pending = null;

  let html =
    `<div class="meta"><span>${escapeHtml(answer.intent)}</span>` +
    `<span class="${escapeHtml(answer.confidence)}">${escapeHtml(answer.confidence)}</span></div>` +
    renderMarkdown(answer.text);

  if (answer.code) {
    html += `<pre><code>${escapeHtml(answer.code.replace(/\n$/, ""))}</code></pre>`;
    // The server's verdict, never the panel's guess — and the buttons that put
    // it in the file appear only when that verdict is good. Code paRY has not
    // compiled can be read and copied, never inserted.
    html += answer.code_compiles
      ? '<div class="actions"><span class="verdict">✓ compiles</span>' +
        '<button data-place="insert">Insert at cursor</button>' +
        '<button data-place="replace">Replace selection</button>' +
        '<button data-copy>Copy</button></div>'
      : '<div class="actions"><span class="verdict bad">✗ not verified</span>' +
        '<button data-copy>Copy</button></div>';
  }

  if (answer.citations && answer.citations.length) {
    const items = answer.citations
      .map((citation) => {
        const where = citation.path
          ? `${citation.path}${citation.line ? `:${citation.line}` : ""}`
          : citation.title;
        return `<li>${escapeHtml(where)}</li>`;
      })
      .join("");
    html += `<div class="citations">from<ul>${items}</ul></div>`;
  }

  node.innerHTML = html;
  // The buttons need the code, and the code is not what is displayed: the
  // displayed version is escaped. Keep the original on the message.
  if (answer.code) {
    node.dataset.code = answer.code;
  }
  scrollToLatest();
}

window.addEventListener("message", (event) => {
  const message = event.data;
  if (message.type === "health") {
    const health = message.health;
    healthBox.innerHTML =
      `${escapeHtml(health.compiler ?? "no compiler")} · ${health.chunks ?? 0} chunks<br>` +
      `<span class="no-model">${
        health.model ? escapeHtml(health.model) : "no model — compiler and corpus only"
      }</span>`;
  } else if (message.type === "asked") {
    const note = message.withSource ? '<div class="meta">with the open file</div>' : "";
    add("message user", escapeHtml(message.question) + note);
    pending = add("message assistant", '<div class="meta">asking…</div>');
    askButton.disabled = true;
  } else if (message.type === "answer") {
    renderAnswer(message.answer);
    askButton.disabled = false;
  } else if (message.type === "note") {
    // What happened in the editor, said in the chat. This is the half of the
    // split that would otherwise be invisible: the code went to the file, and
    // the sentence about it stays here.
    add("note", escapeHtml(message.message));
  } else if (message.type === "error") {
    const node = pending ?? add("message assistant", "");
    node.innerHTML = `<div class="verdict bad">${escapeHtml(message.message)}</div>`;
    pending = null;
    askButton.disabled = false;
    scrollToLatest();
  }
});

/* One listener for the whole transcript rather than one per code block: the
 * transcript only grows, and every answer added later is covered by this. */
transcript.addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (!button) {
    return;
  }
  const code = button.closest("[data-code]")?.dataset.code;
  if (!code) {
    return;
  }
  if (button.hasAttribute("data-copy")) {
    vscode.postMessage({ type: "copy", code });
  } else {
    vscode.postMessage({ type: "place", how: button.dataset.place, code });
  }
});

composer.addEventListener("submit", (event) => {
  event.preventDefault();
  const question = questionField.value.trim();
  if (!question) {
    return;
  }
  questionField.value = "";
  vscode.postMessage({ type: "ask", question, includeSource: includeSource.checked });
});

questionField.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

vscode.postMessage({ type: "ready" });
