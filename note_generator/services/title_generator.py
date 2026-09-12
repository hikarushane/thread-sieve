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
            "你正在為個人筆記庫產生標題。目標：讓人只看標題就知道這則筆記的核心知識點或實用資訊。\n\n"
            "## 規則\n"
            "1. 寫出具體主題，不要寫聳動、模糊的行銷標題。\n"
            "2. 如果內容在講一個明確的工具、服務、專案、方法論或概念，標題要包含其正式名稱。\n"
            "3. 英文人名、品牌、專案名、產品名、社群名保留原本英文拼寫，不要翻譯。\n"
            "4. 不要放 GitHub 星數、價格、「免費」「白嫖」「必看」等噱頭詞。\n"
            "5. 不要用比喻或類比當標題（如「廚房管理術」「天堂」）。\n"
            "6. 標題是名詞短語或一句話描述，不是文章題目式的修辭。\n"
            "7. 只輸出一個標題，不要解釋，不要引號，不要第二行。\n\n"
            "## 壞標題 → 好標題範例\n"
            "- 「社畜求酒精光線插座天堂」→「台北市兼具酒精、光線、插座的工作空間」\n"
            "- 「白嫖網域！網站成本歸零」→「Digiplat 免費申請二級域名」\n"
            "- 「Git 三大流程：廚房管理術」→「Git Flow vs GitHub Flow vs GitLab Flow」\n"
            "- 「AI 實用評估 GitHub 專案：打破迷思」→「評估 Git 專案品質的方法」\n"
            "- 「AI專家員工庫，Github 81萬收藏！」→「awesome-agents，AI 專家 agent 列表」\n\n"
            f"類別：{item.category}\n"
            f"內容：\n{item.enriched.llm_content[:4000]}"
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
