/* The paRY web client.
 *
 * No framework and no build step: this is served by the paRY server itself, so
 * `python -m paRY.serve` is the whole install. That is not minimalism for its
 * own sake — the institutions this is for run it inside their own network, and
 * a client that needs npm at install time is a client that needs a route out.
 *
 * The API is same-origin when served this way. `?api=` points it somewhere
 * else for development, which is what the server's CORS list is for.
 */

const API = new URLSearchParams(location.search).get("api") ?? "";

const transcript = document.getElementById("transcript");
const composer = document.getElementById("composer");
const questionField = document.getElementById("question");
const sourceField = document.getElementById("source");
const localeField = document.getElementById("locale");
const askButton = document.getElementById("ask");
const checkButton = document.getElementById("check");
const toggleSource = document.getElementById("toggle-source");
const healthBox = document.getElementById("health");

/* ---------- markdown ------------------------------------------------------
 * The answer text is markdown from the server, and the only markdown it ever
 * contains is headings, bullets, fences, inline code and bold. Everything is
 * escaped before any tag is added, so this cannot be an injection route even
 * if the corpus one day contains a document that looks like HTML.
 */

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, (char) => ({
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

  const segments = markdown.split(/```/);
  segments.forEach((segment, index) => {
    if (index % 2 === 1) {
      closeList();
      const body = segment.replace(/^[a-zA-Z]*\n/, "");
      out.push(`<pre><code>${escapeHtml(body.replace(/\n$/, ""))}</code></pre>`);
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

/* ---------- transcript ---------------------------------------------------- */

/* Set scrollTop rather than calling scrollIntoView({behavior:"smooth"}): the
 * smooth form silently does nothing in some embedded webviews, and a chat that
 * does not follow its own newest message is broken in the one place it shows. */
function scrollToLatest() {
  transcript.scrollTop = transcript.scrollHeight;
}

function element(tag, className, html) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (html !== undefined) node.innerHTML = html;
  return node;
}

function addMessage(role, buildBody) {
  const message = element("div", `message ${role}`);
  const body = element("div", "body");
  buildBody(body, message);
  message.append(body);
  transcript.append(message);
  scrollToLatest();
  return message;
}

function addUser(question, source) {
  addMessage("user", (body) => {
    body.textContent = question;
    if (source.trim()) {
      body.append(element("div", "meta", "with code"));
    }
  });
}

function addPending(label) {
  return addMessage("assistant", (body) => {
    body.append(element("p", "meta", label));
  });
}

/* An answer, as the protocol defines it: what it is, how sure it is, the text,
 * code only if the server says it compiled, and where it came from. */
function renderAnswer(message, answer) {
  message.replaceChildren();
  const meta = element("div", "meta");
  meta.append(element("span", "badge", escapeHtml(answer.intent)));
  meta.append(element("span", `badge ${answer.confidence}`, escapeHtml(answer.confidence)));
  message.append(meta);

  const body = element("div", "body", renderMarkdown(answer.text));

  if (answer.code) {
    body.append(element("pre", null, `<code>${escapeHtml(answer.code.replace(/\n$/, ""))}</code>`));
    // The badge is the server's verdict, not a guess made here. paRY is not
    // supposed to be able to show code it has not compiled — if this ever says
    // otherwise, that is the bug worth chasing.
    body.append(element(
      "div",
      answer.code_compiles ? "verdict" : "verdict bad",
      answer.code_compiles ? "✓ compiles" : "✗ not verified",
    ));
  }

  if (answer.citations?.length) {
    const items = answer.citations
      .map((citation) => {
        const where = citation.path
          ? `${citation.path}${citation.line ? `:${citation.line}` : ""}`
          : citation.title;
        return `<li>${escapeHtml(where)}</li>`;
      })
      .join("");
    body.append(element("div", "citations", `from<ul>${items}</ul>`));
  }

  message.append(body);
  scrollToLatest();
}

function renderFailure(message, error) {
  message.replaceChildren(element(
    "div",
    "body",
    `<p class="verdict bad">${escapeHtml(String(error))}</p>
     <p>Is the server running? <code>python -m paRY.serve</code></p>`,
  ));
  scrollToLatest();
}

/* ---------- api ----------------------------------------------------------- */

async function post(path, payload) {
  const response = await fetch(`${API}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail ?? `${response.status} ${response.statusText}`);
  }
  return body;
}

async function ask(question, source, locale) {
  addUser(question, source);
  const pending = addPending("asking the compiler and the corpus…");
  try {
    renderAnswer(pending, await post("/ask", {
      question,
      source: source.trim() || null,
      locale: locale || null,
    }));
  } catch (error) {
    renderFailure(pending, error);
  }
}

async function check(source) {
  const pending = addPending("compiling…");
  try {
    const result = await post("/diagnose", { source });
    const lines = result.ok
      ? ["### It compiles", "", "`--check` stops before name resolution, so an undefined name still passes."]
      : ["### It does not compile", "", ...result.diagnostics.map((d) => `- ${d.raw}`)];
    renderAnswer(pending, {
      intent: "diagnose",
      confidence: "exact",
      text: lines.join("\n"),
      code: result.ok ? source : null,
      code_compiles: result.ok,
      citations: [],
    });
  } catch (error) {
    renderFailure(pending, error);
  }
}

/* ---------- wiring -------------------------------------------------------- */

composer.addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = questionField.value.trim();
  if (!question) return;
  askButton.disabled = true;
  questionField.value = "";
  autoGrow();
  await ask(question, sourceField.value, localeField.value);
  askButton.disabled = false;
  questionField.focus();
});

checkButton.addEventListener("click", () => {
  const source = sourceField.value.trim();
  if (source) check(sourceField.value);
});

toggleSource.addEventListener("click", () => {
  const showing = sourceField.hidden;
  sourceField.hidden = !showing;
  checkButton.hidden = !showing;
  toggleSource.setAttribute("aria-expanded", String(showing));
  toggleSource.textContent = showing ? "− code" : "+ code";
  if (showing) sourceField.focus();
});

transcript.addEventListener("click", (event) => {
  const chip = event.target.closest("[data-ask]");
  if (!chip) return;
  questionField.value = chip.dataset.ask;
  composer.requestSubmit();
});

/* Enter sends, Shift+Enter is a newline — and the box grows with the question,
 * which matters because Tamil script wraps sooner than the Latin equivalent. */
function autoGrow() {
  questionField.style.height = "auto";
  questionField.style.height = `${Math.min(questionField.scrollHeight, 192)}px`;
}

questionField.addEventListener("input", autoGrow);
questionField.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    composer.requestSubmit();
  }
});

/* The health strip says what is answering. `model: null` is shown rather than
 * hidden: a user should never have to guess whether a model wrote this. */
(async function health() {
  try {
    const response = await fetch(`${API}/health`);
    const body = await response.json();
    healthBox.innerHTML =
      `${escapeHtml(body.compiler ?? "no compiler")} · ${body.chunks ?? 0} chunks` +
      `<br><span class="no-model">${body.model ? escapeHtml(body.model) : "no model — compiler and corpus only"}</span>`;
  } catch {
    healthBox.textContent = "server unreachable";
  }
})();

questionField.focus();
