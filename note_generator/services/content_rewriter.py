from __future__ import annotations

import re
from dataclasses import dataclass

from note_generator.models import ClassifiedBookmark
from note_generator.services.llm_client import LLMClient


_VALID_STATUSES = {"reference", "wiki", "stub"}


@dataclass(frozen=True)
class RewriteResult:
    status: str
    summary: str
    content: str


class ContentRewriter:
    def __init__(self, llm_client: LLMClient, model_name: str) -> None:
        self._llm_client = llm_client
        self._model_name = model_name

    def rewrite(self, item: ClassifiedBookmark) -> RewriteResult:
        prompt = (
            "你正在為個人筆記庫整理一則社群貼文。\n\n"
            "## 保留度判斷\n"
            "- 來源是 GitHub repo README、官方文件、技術規格 → status: reference。"
            "幾乎不摘要，完整保留 API/指令簽名、參數、使用範例、相依條件。\n"
            "- 內容含可執行指令、程式碼、設定範例、步驟清單 → status: wiki。"
            "不得濃縮指令、參數、設定範例、步驟順序；前言背景結論可摘要。\n"
            "- 純觀點、心得、短評 → status: stub。可以摘要濃縮，"
            "重點是「這個人說了什麼觀點」。\n"
            "- 不確定時往高保留度靠。\n\n"
            "## 輸出格式（嚴格遵守）\n"
            "第一行只寫 status：reference、wiki 或 stub 其中一個，不要加其他文字。\n"
            "第二行空白。\n"
            "第三行起寫 1 到 2 句摘要，說明這則筆記的核心內容。\n"
            "空一行後寫重組後的正文。社群貼文的口語敘述重組成結構化段落，可用 ### 子標題與清單。\n\n"
            "## 硬性規則\n"
            "- 絕對不要輸出任何圖片連結或 ![...](...)。\n"
            "- 不要改變技術細節、指令、參數、程式碼的內容。\n"
            "- 英文專有名詞保持原文。\n"
            "- 不要用 ``` 把整份輸出包起來。\n\n"
            f"分類：{item.category}\n"
            f"內容：\n{item.enriched.llm_content[:6000]}"
        )
        raw = self._llm_client.generate_text(prompt, model_name=self._model_name)
        return self._parse_output(raw)

    def _parse_output(self, raw: str) -> RewriteResult:
        lines = raw.strip().splitlines()
        if not lines:
            return RewriteResult(status="wiki", summary="", content="")

        status = lines[0].strip().lower().rstrip(".:：。")
        status = re.sub(r"^status\s*[:：]\s*", "", status).strip()
        if status not in _VALID_STATUSES:
            status = "wiki"

        rest = "\n".join(lines[1:]).strip()
        parts = re.split(r"\n\s*\n", rest, maxsplit=1)
        summary = parts[0].strip() if parts else ""
        content = parts[1].strip() if len(parts) > 1 else ""

        if not content and summary:
            content = summary
            summary = ""

        return RewriteResult(status=status, summary=summary, content=content)
