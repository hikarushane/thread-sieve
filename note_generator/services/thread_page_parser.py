from __future__ import annotations

from dataclasses import dataclass, field
import json

from note_generator.models import ThreadPost


@dataclass(frozen=True)
class ThreadPageData:
    focal: ThreadPost | None
    ancestor_chain: list[ThreadPost] = field(default_factory=list)
    reply_threads: list[list[ThreadPost]] = field(default_factory=list)


def parse_thread_page(json_blobs: list[str], focal_code: str) -> ThreadPageData:
    chains: list[list[ThreadPost]] = []
    seen_signatures: set[tuple[str, ...]] = set()

    for blob in json_blobs:
        try:
            data = json.loads(blob)
        except (TypeError, ValueError):
            continue
        for chain in _collect_chains(data):
            signature = tuple(post.code for post in chain)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            chains.append(chain)

    focal: ThreadPost | None = None
    ancestor_chain: list[ThreadPost] = []
    reply_threads: list[list[ThreadPost]] = []

    for chain in chains:
        focal_index = next(
            (index for index, post in enumerate(chain) if post.code == focal_code),
            -1,
        )
        if focal_index < 0:
            reply_threads.append(chain)
            continue
        if focal is not None:
            # Same thread edge duplicated in another JSON blob with a
            # different item count; code-sequence dedupe above only
            # catches exact matches, so skip this longer/shorter copy
            # instead of reprinting the root and focal post as a reply.
            continue
        focal = chain[focal_index]
        ancestor_chain = chain[:focal_index]
        trailing = chain[focal_index + 1:]
        if trailing:
            reply_threads.append(trailing)

    if focal is None:
        return ThreadPageData(focal=None)
    return ThreadPageData(
        focal=focal,
        ancestor_chain=ancestor_chain,
        reply_threads=reply_threads,
    )


def parse_dom_thread(dom_posts: list[dict], focal_code: str) -> ThreadPageData:
    """Build ThreadPageData from DOM-extracted posts (see dom_thread_extract.js).

    Each dom_post carries role in {"ancestor", "focal", "reply"} and, for
    replies, a "group" index; adjacent replies sharing a group form one chain.
    """
    posts: list[ThreadPost] = []
    for raw in dom_posts:
        post = _to_thread_post_from_dom(raw)
        if post is not None:
            posts.append(post)

    focal_index = next(
        (index for index, raw in enumerate(dom_posts) if raw.get("role") == "focal"),
        -1,
    )
    if focal_index < 0 or focal_index >= len(posts):
        return ThreadPageData(focal=None)

    focal = posts[focal_index]
    ancestor_chain = [
        posts[index]
        for index, raw in enumerate(dom_posts)
        if raw.get("role") == "ancestor"
    ]

    reply_threads: list[list[ThreadPost]] = []
    current_group: object = None
    for index, raw in enumerate(dom_posts):
        if raw.get("role") != "reply":
            continue
        group = raw.get("group")
        if group != current_group or not reply_threads:
            reply_threads.append([])
            current_group = group
        reply_threads[-1].append(posts[index])

    return ThreadPageData(
        focal=focal,
        ancestor_chain=ancestor_chain,
        reply_threads=reply_threads,
    )


def _to_thread_post_from_dom(raw: object) -> ThreadPost | None:
    if not isinstance(raw, dict):
        return None
    code = str(raw.get("code") or "")
    author_handle = str(raw.get("authorHandle") or "").lstrip("/").lstrip("@")
    if not code or not author_handle:
        return None
    text = str(raw.get("text") or "")
    return ThreadPost(code=code, author_handle=author_handle, text=text, reply_to_handle="")


def _collect_chains(data: object) -> list[list[ThreadPost]]:
    chains: list[list[ThreadPost]] = []
    _walk(data, chains)
    return chains


def _walk(node: object, chains: list[list[ThreadPost]]) -> None:
    if isinstance(node, dict):
        edges = node.get("edges")
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                edge_node = edge.get("node")
                items = edge_node.get("thread_items") if isinstance(edge_node, dict) else None
                if not isinstance(items, list):
                    continue
                chain = [
                    post
                    for post in (_to_thread_post(item) for item in items)
                    if post is not None
                ]
                if chain:
                    chains.append(chain)
        for value in node.values():
            _walk(value, chains)
    elif isinstance(node, list):
        for value in node:
            _walk(value, chains)


def _to_thread_post(item: object) -> ThreadPost | None:
    if not isinstance(item, dict):
        return None
    post = item.get("post")
    if not isinstance(post, dict):
        return None

    code = str(post.get("code") or "")
    user = post.get("user") if isinstance(post.get("user"), dict) else {}
    author_handle = str(user.get("username") or "")
    if not code or not author_handle:
        return None

    caption = post.get("caption") if isinstance(post.get("caption"), dict) else {}
    text = str(caption.get("text") or "")

    info = (
        post.get("text_post_app_info")
        if isinstance(post.get("text_post_app_info"), dict)
        else {}
    )
    reply_to = (
        info.get("reply_to_author")
        if isinstance(info.get("reply_to_author"), dict)
        else {}
    )
    reply_to_handle = str(reply_to.get("username") or "")

    return ThreadPost(
        code=code,
        author_handle=author_handle,
        text=text,
        reply_to_handle=reply_to_handle,
    )
