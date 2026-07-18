from pathlib import Path

import scripts.image_ocr_to_markdown as mod


def test_find_markdown_by_post_url_matches_any_markdown_containing_url(tmp_path: Path) -> None:
    first = tmp_path / "first.md"
    nested = tmp_path / "nested"
    nested.mkdir()
    second = nested / "target.md"
    first.write_text("no match", encoding="utf-8")
    second.write_text("來源 https://www.threads.com/@demo/post/ABC123", encoding="utf-8")

    assert mod.find_markdown_by_post_url(tmp_path, "https://www.threads.com/@demo/post/ABC123") == second


def test_apply_ocr_section_inserts_before_sources(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text("body\n\n## Sources\n\n- source\n", encoding="utf-8")

    mod.apply_ocr_section(path, ["圖片一", "圖片二"])

    assert path.read_text(encoding="utf-8") == (
        "body\n\n"
        "## 圖片文字\n\n"
        "圖片一\n\n---\n\n圖片二\n\n"
        "## Sources\n\n"
        "- source\n"
    )


def test_apply_ocr_section_replaces_existing_section(tmp_path: Path) -> None:
    path = tmp_path / "note.md"
    path.write_text(
        "body\n\n## 圖片文字\n\nold text\n\n## Sources\n\n- source\n",
        encoding="utf-8",
    )

    mod.apply_ocr_section(path, ["new text"])

    text = path.read_text(encoding="utf-8")
    assert "old text" not in text
    assert text.count("## 圖片文字") == 1
    assert "new text" in text


def test_extract_post_image_urls_from_dom_records_filters_carousel_images() -> None:
    records = [
        {"src": "https://cdn.example/v/t51.82787-19/avatar.jpg", "w": 150, "h": 150},
        {"src": "https://cdn.example/v/t51.82787-15/slide-1.jpg", "w": 224, "h": 280},
        {"src": "https://cdn.example/v/t51.82787-15/slide-1.jpg", "w": 224, "h": 280},
        {"src": "https://cdn.example/v/t51.82787-15/tiny.jpg", "w": 100, "h": 100},
        {"src": "https://cdn.example/v/t51.82787-15/slide-2.jpg", "w": 224, "h": 280},
    ]

    assert mod.extract_post_image_urls_from_dom_records(records) == [
        "https://cdn.example/v/t51.82787-15/slide-1.jpg",
        "https://cdn.example/v/t51.82787-15/slide-2.jpg",
    ]


def test_build_gemini_ocr_image_downloads_image_and_runs_client(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []

    class FakeClient:
        def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
            calls.append(("generate", (image_bytes, prompt, model_name)))
            return "Gemini text"

    def fake_factory(provider: str, api_keys):
        calls.append(("factory", provider, dict(api_keys)))
        return FakeClient()

    monkeypatch.setattr(mod, "build_llm_client", fake_factory)
    monkeypatch.setattr(mod, "download_image", lambda url: b"image-bytes")

    ocr_image = mod.build_gemini_ocr_image(api_key="key", model="gemini-test")

    assert ocr_image("https://image") == "Gemini text"
    assert calls == [
        ("factory", "gemini", {"gemini": "key"}),
        ("generate", (b"image-bytes", mod.OCR_PROMPT, "gemini-test")),
    ]


def test_build_ocr_image_defaults_to_gemini(monkeypatch) -> None:
    monkeypatch.setattr(mod, "build_gemini_ocr_image", lambda **kwargs: lambda image_url: "gemini")

    assert mod.build_ocr_image(api_key="key")("https://image") == "gemini"


def test_build_ocr_image_rejects_unsupported_backend() -> None:
    import pytest

    with pytest.raises(RuntimeError, match="Use 'gemini' or 'chandra'"):
        mod.build_ocr_image(backend="tesseract", api_key="key")


def test_ocr_post_images_uses_injected_ocr_callable_and_skips_failures(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "fetch_image_urls_with_playwright",
        lambda post_url, *, headless: ["https://image/1", "https://image/2", "https://image/3"],
    )

    def ocr_image(image_url: str) -> str:
        if image_url.endswith("/2"):
            raise RuntimeError("bad image")
        return f"text for {image_url}"

    assert mod.ocr_post_images(post_url="https://post", ocr_image=ocr_image) == [
        "text for https://image/1",
        "text for https://image/3",
    ]


def test_trigger_items_uses_classification_reasons(tmp_path: Path) -> None:
    posts = [
        {"postId": "p1", "postUrl": "https://threads/p1"},
        {"postId": "p2", "postUrl": "https://threads/p2"},
        {"postId": "p3", "postUrl": "https://threads/p3"},
    ]
    classifications = {
        "items": [
            {"postId": "p1", "postUrl": "https://threads/p1", "reason": "AI"},
            {"postId": "p2", "postUrl": "https://threads/p2", "reason": "Claude Code"},
            {"postId": "p3", "postUrl": "https://threads/p3", "reason": "科技"},
        ]
    }

    result = mod.select_trigger_posts(posts, classifications, {"AI", "Claude Code"})

    assert [post["postId"] for post in result] == ["p1", "p2"]


def test_read_int_env_uses_first_present_value(monkeypatch) -> None:
    monkeypatch.setenv("MAX_OUTPUT_TOKENS", "99")

    assert mod.read_int_env("IMAGE_OCR_MAX_OUTPUT_TOKENS", "MAX_OUTPUT_TOKENS", default=10) == 99


def test_read_ocr_config_loads_image_ocr_section(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"image-ocr": {"backend": "chandra", "trigger-categories": ["AI"]}}',
        encoding="utf-8",
    )

    assert mod.read_ocr_config(config_path) == {
        "backend": "chandra",
        "trigger-categories": ["AI"],
    }


def test_read_configured_set_supports_json_list() -> None:
    assert mod.read_configured_set(["AI", "Claude Code"], {"fallback"}) == {"AI", "Claude Code"}
