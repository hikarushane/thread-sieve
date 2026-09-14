// Regression test for the "merged post text" scrape bug.
// Runs Parser.extractExpandedContent from the userscript against a fake DOM chain.
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

const extractExpandedContent = extractMethod("extractExpandedContent");
const isBetterContentCandidate = extractMethod("isBetterContentCandidate");

function makeChain(levels) {
  // levels: bottom (article) first. Each: { links: [...hrefs], text }
  const body = { tag: "BODY" };
  globalThis.document = { body };
  const nodes = levels.map((level) => ({ ...level }));
  nodes.forEach((node, index) => {
    node.parentElement = nodes[index + 1] || body;
  });
  return nodes[0];
}

function makeParser() {
  return {
    normalizePostHref: (href) => href || "",
    getPostLinkNodes: (element) => (element.links || []).map((href) => ({ getAttribute: () => href })),
    extractContentFromContainer: (element) => element.text || "",
    isBetterContentCandidate,
    extractExpandedContent
  };
}

const TARGET = "/@alice/post/AAA";
const postLink = { getAttribute: () => TARGET };
const OWN_TEXT = "搬去歐洲前，怎麼判斷哪個街區真的好住？\n推薦一個數據化工具";
const PAGE_BLOB = [OWN_TEXT, "今日份的ORM 她一定沒想到會被調侃成這樣", "我每天讓 claude 用的瀏覽器", "© 2026 《Threads 使用條款》"].join("\n");

test("weak own text expands only into the single-post wrapper, never the page", () => {
  const article = makeChain([
    { links: [TARGET], text: "" },                                   // article: text not rendered / media-only
    { links: [TARGET], text: OWN_TEXT },                             // post wrapper (single post)
    { links: [TARGET, "/@bob/post/BBB", "/@c/post/CCC"], text: PAGE_BLOB.slice(0, 120) }, // feed chunk
    { links: [TARGET, "/@bob/post/BBB", "/@c/post/CCC", "/@d/post/DDD", "/@e/post/EEE"], text: PAGE_BLOB } // layout root (<=12 posts, has footer)
  ]);
  const result = makeParser().extractExpandedContent(article, postLink, "", "", "");
  assert.equal(result, OWN_TEXT);
  assert.ok(!result.includes("© 2026"), "must not swallow the page footer");
});

test("keeps current text when every ancestor holds other posts too", () => {
  const article = makeChain([
    { links: [TARGET], text: "" },
    { links: [TARGET, "/@bob/post/BBB"], text: "quoted-neighbour blob\nline2" },
    { links: [TARGET, "/@bob/post/BBB", "/@c/post/CCC"], text: PAGE_BLOB }
  ]);
  const result = makeParser().extractExpandedContent(article, postLink, "", "", "short");
  assert.equal(result, "short");
});
