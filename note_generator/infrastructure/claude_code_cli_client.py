from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 300


class ClaudeCodeCLIClient:
    """LLMClient adapter that shells out to the local Claude Code CLI (`claude -p`).

    Uses the CLI's own login session — no API key required. An empty
    `model_name` defers to the CLI's configured default model.
    """

    def __init__(
        self,
        *,
        executable: str = "claude",
        max_retries: int = 2,
        retry_base_delay: float = 1.5,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if shutil.which(executable) is None:
            raise RuntimeError(
                f"{executable!r} CLI not found on PATH; install Claude Code and log in "
                "before using the claude-code backend"
            )
        self._executable = executable
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = retry_base_delay
        self._timeout = timeout

    def generate_text(self, prompt: str, *, model_name: str) -> str:
        def _call() -> str:
            return self._run_cli(prompt, model_name=model_name, cwd=tempfile.gettempdir())

        return self._with_retries(_call, label="Claude Code CLI")

    def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
        # No retry wrapper — matches GeminiClient.generate_text_from_image parity (single-shot OCR).
        # The image is written inside the CLI's cwd so the auto-allowed Read tool can open it.
        with tempfile.TemporaryDirectory(prefix="threadsieve-claude-ocr-") as workdir:
            image_path = Path(workdir) / "image.jpg"
            image_path.write_bytes(image_bytes)
            full_prompt = (
                f"Read the image file at {image_path} first, then follow the instructions "
                f"below and answer with the result only.\n\n{prompt}"
            )
            return self._run_cli(full_prompt, model_name=model_name, cwd=workdir)

    def _run_cli(self, prompt: str, *, model_name: str, cwd: str) -> str:
        # cwd points at a throwaway directory so no project CLAUDE.md or project
        # hook output can leak into the prompt. (`--bare` would isolate further
        # but breaks CLI-session auth on some setups, so it is deliberately not used.)
        command = [self._executable, "-p", "--output-format", "text"]
        normalized_model = model_name.strip()
        if normalized_model:
            command += ["--model", normalized_model]
        result = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=self._timeout,
            cwd=cwd,
        )
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                f"claude CLI exited with code {result.returncode}: {stderr[:500]}"
            )
        text = (result.stdout or "").strip()
        if not text:
            logger.warning("Claude Code CLI returned empty text response")
        return text

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
