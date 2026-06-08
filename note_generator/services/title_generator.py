from __future__ import annotations

import re

from note_generator.models import ClassifiedBookmark, TitledBookmark
from note_generator.services.llm_client import LLMClient


_TITLE_PREFIX_RE = re.compile(r"^(?:標題|title)\s*[:：]\s*", re.IGNORECASE)
_LEADING_WRAP_RE = re.compile(r'^[\s"\'「『（(\[]+')
_TRAILING_WRAP_RE = re.compile(r'[\s"\'」』）)\]]+$')


class TitleGenerator:
    def __init__(self, llm_client: LLMClient, model_name: str, max_title_length: int) -> None:
        self._llm_client = llm_client
        self._model_name = model_name
        self._max_title_length = max_title_length

    def generate(self, item: ClassifiedBookmark) -> TitledBookmark:
        prompt = (
            f"請根據以下「{item.category}」類別的 Threads 內容產生一個簡短、自然的繁體中文標題。"
            "只輸出一個標題，不要解釋，不要引號，不要第二行。\n\n"
            "如果內容包含英文人名、品牌、專案名稱、產品名稱或社群名稱，"
            "請保留原本的英文拼寫，不要自行翻譯。\n\n"
            f"{item.enriched.combined_content[:4000]}"
        )
        raw_title = self._llm_client.generate_text(prompt, model_name=self._model_name)
        title = self._clean_title(raw_title)
        title = title[: self._max_title_length].strip()
        if not title:
            raise RuntimeError("LLM returned an empty title")
        return TitledBookmark(
            classified=item,
            generated_title=title,
        )

    def _clean_title(self, raw_title: str) -> str:
        first_line = next((line.strip() for line in raw_title.splitlines() if line.strip()), "")
        without_prefix = _TITLE_PREFIX_RE.sub("", first_line)
        cleaned = _LEADING_WRAP_RE.sub("", without_prefix)
        cleaned = _TRAILING_WRAP_RE.sub("", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()
