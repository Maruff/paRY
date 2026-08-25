/* The only part of this extension that can be tested without an editor.
 *
 * Indentation is worth testing rather than eyeballing: code dropped into a
 * `எனில்` block at column zero is the difference between an assistant and a
 * paste buffer, and nobody notices the bug until they are inside a block.
 *
 *     npm test
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { forInsertion, indentBlock, indentOf } from "../out/text.js";

test("indentOf reads the whitespace a line starts with", () => {
  assert.equal(indentOf("    அச்சு 1;"), "    ");
  assert.equal(indentOf("\t\tஅச்சு 1;"), "\t\t");
  assert.equal(indentOf("அச்சு 1;"), "");
  assert.equal(indentOf(""), "");
});

test("the first line is left alone — the cursor is already there", () => {
  const block = indentBlock("first\nsecond", "    ");
  assert.equal(block, "first\n    second");
});

test("every following line is indented to the cursor", () => {
  const block = indentBlock("செயல் f() {\n    திரும்பு 1;\n}", "  ");
  assert.equal(block, "செயல் f() {\n      திரும்பு 1;\n  }");
});

test("blank lines stay blank rather than becoming spaces", () => {
  assert.equal(indentBlock("a\n\nb", "    "), "a\n\n    b");
});

test("no indent means nothing is touched", () => {
  const code = "a\n  b\n";
  assert.equal(indentBlock(code, ""), code);
});

test("a trailing newline is dropped before insertion", () => {
  assert.equal(forInsertion("அச்சு 1;\n"), "அச்சு 1;");
  assert.equal(forInsertion("அச்சு 1;\n\n\n"), "அச்சு 1;");
  assert.equal(forInsertion("அச்சு 1;"), "அச்சு 1;");
});

test("interior blank lines survive — only the tail is trimmed", () => {
  assert.equal(forInsertion("a\n\nb\n"), "a\n\nb");
});
