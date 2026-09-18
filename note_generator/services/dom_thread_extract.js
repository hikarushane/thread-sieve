// DOM thread extractor.
//
// Source of the DOM facts encoded below: manual inspection of a live
// www.threads.com post page (www.threads.com, no <article> wrapper),
// performed 2026-09-18. See the task notes for the full write-up; summary:
//
// - Each post = one `[data-pressable-container]`. A *valid* post container
//   has a `time[datetime]` inside it whose closest <a> has an href shaped
//   like `/@handle/post/<code>` (optionally with a trailing `/media`).
//   Non-post containers (e.g. the cookie dialog) also use
//   `data-pressable-container` but lack that link, so they must be filtered
//   out this way.
// - Author handle = the handle segment of that href.
// - Body text = the container's `span[dir="auto"]` elements' `innerText`
//   (never `textContent` — icons carry `<svg><title>` text), in order:
//   author name, optional topic tag, relative time, body..., like/reply
//   counts. The body is what remains after dropping spans equal to the
//   handle, equal to the `<time>` element's text, purely numeric/count
//   spans (e.g. "12", "1.2萬", "3.4K"), and empty spans, then joining what's
//   left with newlines.
// - The focal post is the one whose href code matches the caller's
//   `focalCode`.
// - Thread membership: for every valid container c, compute the DOM depth
//   of the lowest common ancestor (LCA) of c and the focal container.
//   Containers sharing the *deepest* such LCA with focal belong to this
//   thread. The page's "Related threads"/"相關串文" recommendation block
//   sits one level shallower, so it is excluded by this depth check; as a
//   second safeguard, a container is also excluded when the branch element
//   directly under the LCA (on the path to that container) has innerText
//   starting with "相關串文" or "Related threads".
// - Within the thread, DOM order relative to the focal container
//   distinguishes ancestors (before focal) from replies (after focal).
// - Reply grouping: let R be the ordered reply containers. With 2+ replies,
//   blockDepth = LCA-depth(R[0], R[last]). Walking R in order, a reply
//   starts a new group unless its LCA-depth with the previous reply is
//   greater than blockDepth (deeper => same reply chain). With 0 or 1
//   replies, each reply (if any) is its own group.
(focalCode) => {
  function ancestorChain(node) {
    const chain = [];
    let cur = node;
    while (cur) {
      chain.push(cur);
      cur = cur.parentElement;
    }
    chain.reverse();
    return chain;
  }

  function commonPrefixLen(a, b) {
    const ca = ancestorChain(a);
    const cb = ancestorChain(b);
    let i = 0;
    while (i < ca.length && i < cb.length && ca[i] === cb[i]) {
      i += 1;
    }
    return i;
  }

  function branchIsRelatedThreads(a, b) {
    const ca = ancestorChain(a);
    const cb = ancestorChain(b);
    const lcaLen = commonPrefixLen(a, b);
    const branchNode = cb[lcaLen];
    if (!branchNode) return false;
    const text = (branchNode.innerText || "").trim();
    return text.startsWith("相關串文") || text.startsWith("Related threads");
  }

  const HREF_RE = /^\/@([^/]+)\/post\/([^/?#]+)/;
  const COUNT_RE = /^[\d,.]+(?:[KkMm萬千]+)?$/;

  const containers = Array.from(document.querySelectorAll("[data-pressable-container]"));
  const entries = [];

  for (const container of containers) {
    const time = container.querySelector("time[datetime]");
    if (!time) continue;
    const anchor = time.closest("a");
    if (!anchor) continue;
    const href = anchor.getAttribute("href") || "";
    const match = HREF_RE.exec(href);
    if (!match) continue;

    const handle = match[1];
    const code = match[2];
    const timeText = (time.innerText || "").trim();

    const spans = Array.from(container.querySelectorAll('span[dir="auto"]'));
    const bodyLines = [];
    for (const span of spans) {
      const text = (span.innerText || "").trim();
      if (!text) continue;
      if (text === handle) continue;
      if (text === timeText) continue;
      if (COUNT_RE.test(text)) continue;
      bodyLines.push(text);
    }

    entries.push({
      container,
      code,
      authorHandle: handle,
      text: bodyLines.join("\n"),
      datetime: time.getAttribute("datetime") || timeText,
    });
  }

  const focalEntry = entries.find((entry) => entry.code === focalCode);
  if (!focalEntry) {
    return { focalCode, posts: [] };
  }

  let maxDepth = -1;
  for (const entry of entries) {
    if (entry === focalEntry) continue;
    const depth = commonPrefixLen(focalEntry.container, entry.container);
    if (depth > maxDepth) maxDepth = depth;
  }

  const threadEntries = entries.filter((entry) => {
    if (entry === focalEntry) return true;
    const depth = commonPrefixLen(focalEntry.container, entry.container);
    if (depth !== maxDepth) return false;
    if (branchIsRelatedThreads(focalEntry.container, entry.container)) return false;
    return true;
  });

  const focalIndex = threadEntries.indexOf(focalEntry);
  const posts = [];

  for (let i = 0; i < focalIndex; i += 1) {
    const entry = threadEntries[i];
    posts.push({
      code: entry.code,
      authorHandle: entry.authorHandle,
      text: entry.text,
      datetime: entry.datetime,
      role: "ancestor",
      group: 0,
    });
  }

  posts.push({
    code: focalEntry.code,
    authorHandle: focalEntry.authorHandle,
    text: focalEntry.text,
    datetime: focalEntry.datetime,
    role: "focal",
    group: 0,
  });

  const replyEntries = threadEntries.slice(focalIndex + 1);
  let blockDepth = -1;
  if (replyEntries.length >= 2) {
    blockDepth = commonPrefixLen(
      replyEntries[0].container,
      replyEntries[replyEntries.length - 1].container
    );
  }

  let group = 0;
  for (let i = 0; i < replyEntries.length; i += 1) {
    const entry = replyEntries[i];
    if (i === 0) {
      group = 1;
    } else if (replyEntries.length >= 2) {
      const depth = commonPrefixLen(replyEntries[i - 1].container, entry.container);
      if (depth <= blockDepth) {
        group += 1;
      }
    } else {
      group += 1;
    }
    posts.push({
      code: entry.code,
      authorHandle: entry.authorHandle,
      text: entry.text,
      datetime: entry.datetime,
      role: "reply",
      group,
    });
  }

  return { focalCode, posts };
}
