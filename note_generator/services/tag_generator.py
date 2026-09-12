from __future__ import annotations

import json
import re

from note_generator.models import ClassifiedBookmark
from note_generator.services.llm_client import LLMClient


_JSON_ARRAY_RE = re.compile(r"\[.*?\]", re.DOTALL)
_LEADING_WRAP_RE = re.compile(r'^[\s"\'「『（(\[]+')
_TRAILING_WRAP_RE = re.compile(r'[\s"\'」』）)\]]+$')


class TagGenerator:
    def __init__(self, llm_client: LLMClient, model_name: str) -> None:
        self._llm_client = llm_client
        self._model_name = model_name

    def generate(self, item: ClassifiedBookmark) -> list[str]:
        prompt = (
            "你正在為個人筆記庫的一則筆記產生 tags。\n\n"
            "## 規則\n"
            "1. 產生 2 到 4 個主題 tag（不含分類名稱，分類會自動加）。\n"
            "2. tag 是短詞，不是句子。用繁體中文，但工具名、專案名、品牌名保留英文。\n"
            "3. 優先使用已存在的常見 tag，例如：Claude Code、求職、省錢、旅遊、"
            "程式開發、設定配置、CLI、除錯踩坑、入門教學、效率、自動化、"
            "開發流程、架構設計、AI Agent、LLM、Prompt、瀏覽器、部署。\n"
            "4. 不要把分類名稱重複當 tag。\n"
            "5. 只輸出 JSON array，例如：[\"Claude Code\", \"自動化\", \"CLI\"]\n\n"
            f"分類：{item.category}\n"
            f"內容：\n{item.enriched.llm_content[:3000]}"
        )
        raw = self._llm_client.generate_text(prompt, model_name=self._model_name)
        tags = self._parse_tags(raw)
        if not tags:
            return [item.category]
        return [item.category] + tags[:4]

    def _parse_tags(self, raw: str) -> list[str]:
        match = _JSON_ARRAY_RE.search(raw)
        if match:
            try:
                parsed = json.loads(match.group())
                if isinstance(parsed, list):
                    return [str(t).strip() for t in parsed if str(t).strip()]
            except (json.JSONDecodeError, ValueError):
                pass

        tags: list[str] = []
        for line in raw.splitlines():
            candidate = line.strip().lstrip("-•*").strip()
            candidate = _LEADING_WRAP_RE.sub("", candidate)
            candidate = _TRAILING_WRAP_RE.sub("", candidate)
            candidate = candidate.strip().rstrip("，。；：:,.!！?")
            if candidate and len(candidate) < 30:
                tags.append(candidate)
        return tags
