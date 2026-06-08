from __future__ import annotations

import base64
import logging
import time

from anthropic import Anthropic

logger = logging.getLogger(__name__)

_DEFAULT_MAX_TOKENS = 1024


class AnthropicClient:
    """LLMClient adapter for Anthropic Claude (text + vision)."""

    def __init__(
        self,
        api_key: str,
        *,
        max_retries: int = 2,
        retry_base_delay: float = 1.5,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        if not api_key.strip():
            raise RuntimeError("ANTHROPIC_API_KEY is required for the Anthropic backend")
        self._client = Anthropic(api_key=api_key)
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = retry_base_delay
        self._max_tokens = max_tokens

    def generate_text(self, prompt: str, *, model_name: str) -> str:
        def _call() -> str:
            response = self._client.messages.create(
                model=model_name,
                max_tokens=self._max_tokens,
                temperature=0,
                messages=[{"role": "user", "content": prompt}],
            )
            return _extract_text(response)

        return self._with_retries(_call, label="Anthropic")

    def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
        encoded = base64.standard_b64encode(image_bytes).decode("ascii")
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": encoded,
                },
            },
            {"type": "text", "text": prompt},
        ]
        # No retry wrapper — matches GeminiClient.generate_text_from_image parity (single-shot OCR).
        response = self._client.messages.create(
            model=model_name,
            max_tokens=self._max_tokens,
            temperature=0,
            messages=[{"role": "user", "content": content}],
        )
        return _extract_text(response)

    def _with_retries(self, call, *, label: str) -> str:
        attempt = 0
        last_error: Exception | None = None
        while attempt <= self._max_retries:
            try:
                return call()
            except Exception as error:
                last_error = error
                attempt += 1
                if attempt > self._max_retries:
                    break
                delay = self._retry_base_delay * attempt
                logger.warning("%s call failed (attempt %d): %s. Retrying in %.1fs", label, attempt, error, delay)
                time.sleep(delay)
        assert last_error is not None
        raise last_error


def _extract_text(response) -> str:
    blocks = getattr(response, "content", None) or []
    parts: list[str] = []
    for block in blocks:
        if getattr(block, "type", None) == "text":
            parts.append(getattr(block, "text", "") or "")
    text = "".join(parts).strip()
    if not text:
        logger.warning("Anthropic returned empty text response")
    return text
