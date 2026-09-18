// Regression test for the permalink post-page "..." menu button selector.
// Threads removed the aria-label from the main post's "..." icon; the old
// selector (svg[aria-label="更多"] inside [data-pressable-container]) now
// matches the sort button's arrow icon instead and opens the wrong menu.
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
  return new Function(`return function ${text.trim()};`)();
}

const isSortButtonElement = extractMethod("isSortButtonElement");
const listPermalinkPostMenuButtons = extractMethod("listPermalinkPostMenuButtons");
const findPermalinkPostMenuButton = extractMethod("findPermalinkPostMenuButton");

function makeUtils() {
  return {
    isSortButtonElement,
    listPermalinkPostMenuButtons,
    findPermalinkPostMenuButton
  };
}

// ---- minimal fake DOM ----------------------------------------------------
// Supports just enough CSS to exercise the selectors used by the userscript:
// tag/attr compound selectors, comma lists, and single-level descendant
// combinators (`[data-pressable-container] [aria-haspopup="menu"]`).

class El {
  constructor(tag, attrs = {}, { text = "", connected = true } = {}) {
    this.tagName = tag.toUpperCase();
    this.attributes = attrs;
    this.children = [];
    this.parentElement = null;
    this._text = text;
    this.isConnected = connected;
  }

  append(...children) {
    for (const child of children) {
      child.parentElement = this;
      this.children.push(child);
    }
    return this;
  }

  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null;
  }

  hasAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name);
  }

  get textContent() {
    if (this._text) {
      return this._text;
    }
    return this.children.map((child) => child.textContent).join("");
  }

  get innerText() {
    return this.textContent;
  }

  querySelectorAll(selector) {
    return queryAll(this, selector);
  }

  querySelector(selector) {
    return queryAll(this, selector)[0] || null;
  }

  closest(selector) {
    let current = this;
    while (current) {
      if (matchesSelector(current, selector)) {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }
}

function parseCompound(token) {
  const tagMatch = token.match(/^[a-zA-Z0-9-]+/);
  let tag = null;
  let rest = token;
  if (tagMatch) {
    tag = tagMatch[0].toLowerCase();
    rest = token.slice(tag.length);
  }
  const attrs = [];
  const attrRe = /\[([a-zA-Z0-9-]+)(?:=(["'])(.*?)\2)?\]/g;
  let m;
  while ((m = attrRe.exec(rest))) {
    attrs.push({ name: m[1], value: m[3] !== undefined ? m[3] : null });
  }
  return { tag, attrs };
}

function matchesCompound(el, compound) {
  if (!el || !el.tagName) {
    return false;
  }
  if (compound.tag && el.tagName.toLowerCase() !== compound.tag) {
    return false;
  }
  for (const attr of compound.attrs) {
    if (!el.hasAttribute(attr.name)) {
      return false;
    }
    if (attr.value !== null && el.getAttribute(attr.name) !== attr.value) {
      return false;
    }
  }
  return true;
}

function matchesSelector(el, selector) {
  return selector.split(",").some((part) => {
    const tokens = part.trim().split(/\s+/).filter(Boolean);
    if (tokens.length === 0) {
      return false;
    }
    const last = parseCompound(tokens[tokens.length - 1]);
    if (!matchesCompound(el, last)) {
      return false;
    }
    let current = el.parentElement;
    for (let i = tokens.length - 2; i >= 0; i -= 1) {
      const compound = parseCompound(tokens[i]);
      let found = false;
      while (current) {
        if (matchesCompound(current, compound)) {
          found = true;
          break;
        }
        current = current.parentElement;
      }
      if (!found) {
        return false;
      }
      current = current.parentElement;
    }
    return true;
  });
}

function queryAll(root, selector) {
  const results = [];
  const walk = (el) => {
    for (const child of el.children) {
      if (matchesSelector(child, selector)) {
        results.push(child);
      }
      walk(child);
    }
  };
  walk(root);
  return results;
}

// ---- fixtures -------------------------------------------------------------

function svg(ariaLabel) {
  return new El("svg", { "aria-label": ariaLabel });
}

function realisticPageDom() {
  const documentRoot = new El("html");

  const nav = new El("nav").append(
    new El("div", { role: "button", "aria-haspopup": "menu" }).append(svg("更多"))
  );

  const columnHeader = new El("div").append(
    new El("div", { role: "button", "aria-haspopup": "menu" }).append(svg("更多"))
  );

  const sortContainer = new El("div", { "data-pressable-container": "true" });
  const sortButton = new El("div", { role: "button", "aria-haspopup": "menu" }, { text: "熱門" });
  sortButton.append(svg("排序"), svg("更多"));
  sortContainer.append(sortButton);

  const mainPostContainer = new El("div", { "data-pressable-container": "true" });
  const mainPostMenuButton = new El("div", { role: "button", "aria-haspopup": "menu" });
  mainPostContainer.append(mainPostMenuButton);

  const replyContainer = new El("div", { "data-pressable-container": "true" });
  const replyMenuButton = new El("div", { role: "button", "aria-haspopup": "menu" });
  replyContainer.append(replyMenuButton);

  documentRoot.append(nav, columnHeader, sortContainer, mainPostContainer, replyContainer);

  return { documentRoot, mainPostMenuButton, replyMenuButton, sortButton, columnHeader };
}

// ---- tests ------------------------------------------------------------

test("picks the main post's unlabeled menu button, not the sort button or header more", () => {
  const { documentRoot, mainPostMenuButton } = realisticPageDom();
  const found = makeUtils().findPermalinkPostMenuButton(documentRoot);
  assert.equal(found, mainPostMenuButton);
});

test("falls back to the legacy 更多-label selector when no aria-haspopup candidate qualifies", () => {
  const documentRoot = new El("html");
  const postContainer = new El("div", { "data-pressable-container": "true" });
  const postMenuButton = new El("div", { role: "button" }).append(svg("更多"));
  postContainer.append(postMenuButton);
  documentRoot.append(postContainer);

  const found = makeUtils().findPermalinkPostMenuButton(documentRoot);
  assert.equal(found, postMenuButton);
});

test("returns null when only the sort button and header more icon are present", () => {
  const documentRoot = new El("html");

  const columnHeader = new El("div").append(
    new El("div", { role: "button", "aria-haspopup": "menu" }).append(svg("更多"))
  );

  const sortContainer = new El("div", { "data-pressable-container": "true" });
  const sortButton = new El("div", { role: "button", "aria-haspopup": "menu" }, { text: "熱門" });
  sortButton.append(svg("排序"), svg("更多"));
  sortContainer.append(sortButton);

  documentRoot.append(columnHeader, sortContainer);

  const found = makeUtils().findPermalinkPostMenuButton(documentRoot);
  assert.equal(found, null);
});

test("listPermalinkPostMenuButtons orders main post before replies and excludes the sort button", () => {
  const { documentRoot, mainPostMenuButton, replyMenuButton } = realisticPageDom();
  const list = makeUtils().listPermalinkPostMenuButtons(documentRoot);
  assert.deepEqual(list, [mainPostMenuButton, replyMenuButton]);
});
