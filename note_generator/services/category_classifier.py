from __future__ import annotations

import re

from note_generator.models import ClassifiedBookmark, EnrichedBookmark
from note_generator.services.category_overrides import CategoryOverride, detect_forced_category
from note_generator.services.llm_client import LLMClient


_CATEGORY_PREFIX_RE = re.compile(r"^(?:分類|category)\s*[:：]\s*", re.IGNORECASE)
_LEADING_WRAP_RE = re.compile(r'^[\s`"\'「『（(\[]+')
_TRAILING_WRAP_RE = re.compile(r'[\s`"\'」』）)\]]+$')


class CategoryClassifier:
    def __init__(
        self,
        llm_client: LLMClient,
        model_name: str,
        categories: list[str],
        hints: list[str],
        category_overrides: list[CategoryOverride] | None = None,
        provider: str = "gemini",
    ) -> None:
        if not categories:
            raise ValueError("config.json categories must not be empty")
        self._llm_client = llm_client
        self._model_name = model_name
        self._categories = categories
        self._hints = hints
        self._category_overrides = category_overrides or []
        self._provider = provider
        self._category_set = set(categories)
        self._canonical_by_casefold = {
            category.casefold(): category
            for category in categories
        }

    def classify(self, item: EnrichedBookmark) -> ClassifiedBookmark:
        forced_category = detect_forced_category(
            item.combined_content,
            self._category_overrides,
            self._categories,
        )
        if forced_category:
            return ClassifiedBookmark(
                enriched=item,
                category=forced_category,
                category_reason="category override",
            )

        prompt = self._build_prompt(item)
        raw_category = self._llm_client.generate_text(prompt, model_name=self._model_name)
        category = self._normalize_category(raw_category)
        if category not in self._category_set:
            raise RuntimeError(f"LLM returned invalid category: {category or raw_category!r}")
        return ClassifiedBookmark(
            enriched=item,
            category=category,
            category_reason=self._provider,
        )

    def _build_prompt(self, item: EnrichedBookmark) -> str:
        hints_block = "\n".join(f"- {hint}" for hint in self._hints)
        return (
            "請從以下分類中只選一個最適合的分類。\n"
            "只能輸出分類名稱本身，不要解釋、不要標點、不要額外文字。\n\n"
            f"可選分類：{'、'.join(self._categories)}\n\n"
            + (f"分類判別補充：\n{hints_block}\n\n" if hints_block else "")
            + f"作者：{item.source.author_handle}\n"
            + f"內容：{item.combined_content[:5000]}"
        )

    def _normalize_category(self, raw_category: str) -> str:
        for line in raw_category.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            without_prefix = _CATEGORY_PREFIX_RE.sub("", candidate)
            normalized = _LEADING_WRAP_RE.sub("", without_prefix)
            normalized = _TRAILING_WRAP_RE.sub("", normalized)
            normalized = normalized.strip().rstrip("，。；：:,.!！?")
            if normalized:
                return self._canonical_by_casefold.get(
                    normalized.casefold(),
                    normalized,
                )
        return ""
