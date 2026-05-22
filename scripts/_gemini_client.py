from __future__ import annotations

import logging
import time

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)


class GeminiClient:
    def __init__(self, api_key: str, *, max_retries: int = 2, retry_base_delay: float = 1.5) -> None:
        if not api_key.strip():
            raise RuntimeError("GEMINI_API_KEY is required")
        self._client = genai.Client(api_key=api_key)
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = retry_base_delay

    def generate_text(self, prompt: str, *, model: str) -> str:
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            try:
                response = self._client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0),
                )
                if not response.text:
                    candidates = getattr(response, "candidates", None) or []
                    for i, candidate in enumerate(candidates):
                        finish_reason = getattr(candidate, "finish_reason", "unknown")
                        safety_ratings = getattr(candidate, "safety_ratings", [])
                        logger.warning(
                            "Gemini empty response: candidate[%d] finish_reason=%r safety_ratings=%r",
                            i, finish_reason, safety_ratings,
                        )
                    if not candidates:
                        logger.warning(
                            "Gemini empty response: no candidates. prompt_feedback=%r",
                            getattr(response, "prompt_feedback", None),
                        )
                return (response.text or "").strip()
            except Exception as error:
                last_error = error
                attempt += 1
                if attempt > self._max_retries:
                    break
                delay = self._retry_base_delay * attempt
                logger.warning("Gemini call failed (attempt %d): %s. Retrying in %.1fs", attempt, error, delay)
                time.sleep(delay)
        assert last_error is not None
        raise last_error
