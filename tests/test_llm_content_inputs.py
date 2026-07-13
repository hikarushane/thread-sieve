from __future__ import annotations

from note_generator.models import ClassifiedBookmark, EnrichedBookmark, SourceBookmark, ThreadPost
from note_generator.services.category_classifier import CategoryClassifier
from note_generator.services.title_generator import TitleGenerator


class PromptCapturingLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate_text(self, prompt: str, model_name: str) -> str:
        self.prompts.append(prompt)
        return self.response

    def generate_text_with_image(self, prompt: str, image_bytes: bytes, model_name: str) -> str:
        raise NotImplementedError


def _enriched_with_context() -> EnrichedBookmark:
    return EnrichedBookmark(
        source=SourceBookmark(
            post_url="https://www.threads.com/@replier_b/post/FOCAL01",
            author_handle="@replier_b",
            content_text="收藏的回應內容",
        ),
        primary_content="收藏的回應內容",
        saved_kind="reply",
        ancestor_chain=[ThreadPost(code="ROOT01", author_handle="original_poster", text="母帖脈絡文字")],
        reply_threads=[[ThreadPost(code="C1", author_handle="commenter_c", text="回覆區雜訊")]],
    )


def test_classifier_prompt_includes_ancestor_context_but_not_replies() -> None:
    llm = PromptCapturingLLM("Tech")
    classifier = CategoryClassifier(
        llm_client=llm,
        model_name="test-model",
        categories=["Tech", "Food"],
        hints=[],
    )
    classifier.classify(_enriched_with_context())
    prompt = llm.prompts[0]
    assert "母帖脈絡文字" in prompt
    assert "收藏的回應內容" in prompt
    assert "回覆區雜訊" not in prompt


def test_title_prompt_includes_ancestor_context_but_not_replies() -> None:
    llm = PromptCapturingLLM("好標題")
    generator = TitleGenerator(llm_client=llm, model_name="test-model", max_title_length=80)
    classified = ClassifiedBookmark(enriched=_enriched_with_context(), category="Tech")
    generator.generate(classified)
    prompt = llm.prompts[0]
    assert "母帖脈絡文字" in prompt
    assert "回覆區雜訊" not in prompt
