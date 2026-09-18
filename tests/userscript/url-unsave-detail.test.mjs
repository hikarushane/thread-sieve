// Regression test: empty worker detail ("") must not be mislabeled as "timeout".
// Only a null result (real timeout) should produce detail "timeout".
//   node --test tests/userscript/
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(dirname(dirname(fileURLToPath(import.meta.url))));
const source = readFileSync(join(root, "userscripts/threads-scriber-auto.user.js"), "utf8");

function extractMethod(name) {
  const start = source.indexOf(`\n    ${name}(`);
  assert.ok(start > 0, `${name} not found in userscript`);
  const end = source.indexOf("\n    },\n", start);
  const text = source.slice(start + 1, end + "\n    }".length);
  // "name(args) { body }" -> Function
  return new Function(`return function ${text.trim()};`)();
}

const normalizeWorkerResult = extractMethod("normalizeWorkerResult");

test("null result (real timeout) normalizes to failed/timeout", () => {
  assert.deepEqual(normalizeWorkerResult(null), { outcome: "failed", detail: "timeout" });
});

test("successful worker result with empty detail keeps empty detail", () => {
  assert.deepEqual(normalizeWorkerResult({ outcome: "unsaved", detail: "" }), { outcome: "unsaved", detail: "" });
});

test("skipped result with a real detail passes through unchanged", () => {
  assert.deepEqual(
    normalizeWorkerResult({ outcome: "skipped", detail: "already_unsaved" }),
    { outcome: "skipped", detail: "already_unsaved" }
  );
});
