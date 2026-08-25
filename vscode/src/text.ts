/**
 * Text shaping that has nothing to do with VS Code, kept apart so it can be
 * tested without an extension host — which is the only kind of test this
 * extension can actually run.
 */

/** The leading whitespace of a line, which is where inserted code has to land. */
export function indentOf(line: string): string {
  return /^[ \t]*/.exec(line)?.[0] ?? "";
}

/**
 * Re-indent a block so it sits where the cursor is.
 *
 * The first line is left alone — the cursor is already at the right column —
 * and every line after it gets the same indent. Without this, code dropped
 * inside a `எனில்` block lands hard against column zero and the developer's
 * first act is to fix the whitespace, which is not what an assistant is for.
 *
 * Blank lines stay blank rather than becoming lines of spaces.
 */
export function indentBlock(code: string, indent: string): string {
  if (indent === "") {
    return code;
  }
  const [first, ...rest] = code.split("\n");
  return [first, ...rest.map((line) => (line.trim() === "" ? line : indent + line))].join("\n");
}

/**
 * Trim a trailing newline from a block about to be inserted.
 *
 * A snippet from the corpus ends with one; the line the cursor is on does not
 * want it, or the insertion leaves a stray blank line behind every time.
 */
export function forInsertion(code: string): string {
  return code.replace(/\n+$/, "");
}
