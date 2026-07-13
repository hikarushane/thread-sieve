from __future__ import annotations

from pathlib import Path

from note_generator.models import EnrichedBookmark, MarkdownDocumentOutput, TitledBookmark


def _yaml_str(v: str) -> str:
    return '"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _build_context_section(enriched: EnrichedBookmark) -> str:
    if not enriched.ancestor_chain:
        return ""

    blocks: list[str] = []
    for depth, post in enumerate(enriched.ancestor_chain):
        prefix = "> " * (depth + 1)
        label = "（原帖）" if depth == 0 else ""
        lines = [f"{prefix.rstrip()} **@{post.author_handle}**{label}："]
        text_lines = post.text.splitlines() or [""]
        lines.extend(f"{prefix.rstrip()} {line}".rstrip() for line in text_lines)
        blocks.append("\n".join(lines))

    return "## 上文脈絡\n\n" + "\n>\n".join(blocks)


def _build_replies_callout(enriched: EnrichedBookmark) -> str:
    chains = enriched.reply_threads
    if not chains:
        return ""

    root_author = (
        enriched.ancestor_chain[0].author_handle
        if enriched.ancestor_chain
        else enriched.source.author_handle.lstrip("@")
    )
    total = sum(len(chain) for chain in chains)
    op_count = sum(
        1 for chain in chains for post in chain if post.author_handle == root_author
    )
    suffix = "，已截斷" if enriched.reply_threads_truncated else ""
    lines = [f"> [!quote]- 回覆（{total} 則，含原作者 {op_count} 則{suffix}）"]

    for chain in chains:
        for depth, post in enumerate(chain):
            indent = "  " * depth
            marker = "- " if depth == 0 else "- ↳ "
            label = "（原作者）" if post.author_handle == root_author else ""
            text_lines = [line for line in post.text.splitlines() if line.strip()] or [""]
            lines.append(f"> {indent}{marker}**@{post.author_handle}**{label}：{text_lines[0]}")
            lines.extend(f"> {indent}  {extra}" for extra in text_lines[1:])

    return "\n".join(lines)


class MarkdownContentBuilder:
    def build(self, item: TitledBookmark, output_path: Path) -> MarkdownDocumentOutput:
        enriched = item.classified.enriched
        category = item.classified.category
        content_block = enriched.combined_content.strip()
        ocr_texts = item.classified.ocr_texts
        if ocr_texts:
            content_block += "\n\n## 圖片文字\n\n" + "\n\n---\n\n".join(ocr_texts)

        context_section = _build_context_section(enriched)
        if context_section:
            content_block += "\n\n" + context_section

        replies_callout = _build_replies_callout(enriched)
        if replies_callout:
            content_block += "\n\n" + replies_callout

        markdown_body = (
            "---\n"
            f"url: {_yaml_str(enriched.source.post_url)}\n"
            f"author: {_yaml_str(enriched.source.author_handle)}\n"
            f"clip_type: {_yaml_str(category)}\n"
            f"saved_kind: {_yaml_str(enriched.saved_kind)}\n"
            "---\n\n"
            f"{content_block}\n"
        )

        return MarkdownDocumentOutput(
            output_filename=output_path.name,
            output_path=output_path,
            markdown_body=markdown_body,
            category=category,
            source_url=enriched.source.post_url,
            author_handle=enriched.source.author_handle,
        )
