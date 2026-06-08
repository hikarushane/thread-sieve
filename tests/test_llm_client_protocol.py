from __future__ import annotations

from note_generator.services.llm_client import LLMClient


class _FakeClient:
    def generate_text(self, prompt: str, *, model_name: str) -> str:
        return f"text:{model_name}:{prompt[:8]}"

    def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
        return f"image:{model_name}:{len(image_bytes)}"


def test_fake_client_satisfies_protocol():
    fake = _FakeClient()
    assert isinstance(fake, LLMClient)
    assert fake.generate_text("hello world", model_name="m") == "text:m:hello wo"
    assert fake.generate_text_from_image(b"xxx", "p", model_name="m") == "image:m:3"


def test_non_conforming_class_fails_isinstance_check():
    class _MissingMethod:
        def generate_text(self, prompt: str, *, model_name: str) -> str:
            return "x"

    assert not isinstance(_MissingMethod(), LLMClient)
