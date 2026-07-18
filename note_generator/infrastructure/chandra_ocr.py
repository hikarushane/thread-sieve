from __future__ import annotations

from io import BytesIO
from typing import Any


class ChandraOcrEngine:
    def __init__(
        self,
        *,
        method: str = "hf",
        prompt_type: str = "ocr_layout",
        max_output_tokens: int = 12384,
        include_headers_footers: bool = False,
        include_images: bool = False,
        max_workers: int = 8,
        max_retries: int = 6,
    ) -> None:
        self._method = method.strip().lower() or "hf"
        self._prompt_type = prompt_type
        self._max_output_tokens = max_output_tokens
        self._include_headers_footers = include_headers_footers
        self._include_images = include_images
        self._max_workers = max_workers
        self._max_retries = max_retries
        self._model: Any | None = None
        self._batch_item_cls: Any | None = None

    def generate_markdown(self, image_bytes: bytes) -> str:
        model, batch_item_cls = self._load()
        image = self._open_image(image_bytes)
        batch = [batch_item_cls(image=image, prompt_type=self._prompt_type)]
        options: dict[str, object] = {
            "max_output_tokens": self._max_output_tokens,
            "include_images": self._include_images,
            "include_headers_footers": self._include_headers_footers,
        }
        if self._method == "vllm":
            options["max_workers"] = self._max_workers
            options["max_retries"] = self._max_retries
        result = model.generate(batch, **options)[0]
        if getattr(result, "error", False):
            return ""
        return _result_text(result)

    def _load(self) -> tuple[Any, Any]:
        if self._model is None or self._batch_item_cls is None:
            try:
                from chandra.model import InferenceManager
                from chandra.model.schema import BatchInputItem
            except ImportError as error:
                raise RuntimeError(
                    "Chandra OCR is not installed. Install it with `pip install chandra-ocr[hf]` "
                    "for local HuggingFace inference, or `pip install chandra-ocr` for a vLLM backend."
                ) from error
            self._model = InferenceManager(method=self._method)
            self._batch_item_cls = BatchInputItem
        return self._model, self._batch_item_cls

    @staticmethod
    def _open_image(image_bytes: bytes) -> Any:
        try:
            from PIL import Image
        except ImportError as error:
            raise RuntimeError("Pillow is required by Chandra OCR but is not installed.") from error
        return Image.open(BytesIO(image_bytes)).convert("RGB")


def _result_text(result: object) -> str:
    markdown = str(getattr(result, "markdown", "") or "").strip()
    if markdown:
        return markdown
    return str(getattr(result, "html", "") or "").strip()
