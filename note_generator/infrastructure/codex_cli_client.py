from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 300


class CodexCLIClient:
    """LLMClient adapter that shells out to the local OpenAI Codex CLI (`codex exec`).

    Uses the CLI's own login session — no API key required. An empty
    `model_name` defers to the CLI's configured default model.
    """

    def __init__(
        self,
        *,
        executable: str = "codex",
        max_retries: int = 2,
        retry_base_delay: float = 1.5,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if shutil.which(executable) is None:
            raise RuntimeError(
                f"{executable!r} CLI not found on PATH; install the OpenAI Codex CLI and "
                "log in before using the codex backend"
            )
        self._executable = executable
        self._max_retries = max(0, max_retries)
        self._retry_base_delay = retry_base_delay
        self._timeout = timeout

    def generate_text(self, prompt: str, *, model_name: str) -> str:
        def _call() -> str:
            return self._run_cli(prompt, model_name=model_name)

        return self._with_retries(_call, label="Codex CLI")

    def generate_text_from_image(self, image_bytes: bytes, prompt: str, *, model_name: str) -> str:
        # No retry wrapper — matches GeminiClient.generate_text_from_image parity (single-shot OCR).
        return self._run_cli(prompt, model_name=model_name, image_bytes=image_bytes)

    def _run_cli(self, prompt: str, *, model_name: str, image_bytes: bytes | None = None) -> str:
        # cwd is a throwaway directory and the sandbox is read-only, so the agent
        # cannot touch the user's project; the final answer is read from the
        # `--output-last-message` file because stdout carries progress logging.
        with tempfile.TemporaryDirectory(prefix="threadsieve-codex-") as workdir:
            last_message_path = Path(workdir) / "last_message.txt"
            command = [
                self._executable,
                "exec",
                "--sandbox", "read-only",
                "--skip-git-repo-check",
                "--output-last-message", str(last_message_path),
            ]
            normalized_model = model_name.strip()
            if normalized_model:
                command += ["--model", normalized_model]
            if image_bytes is not None:
                image_path = Path(workdir) / "image.jpg"
                image_path.write_bytes(image_bytes)
                command += ["--image", str(image_path)]
            command.append("-")  # read the prompt from stdin
            result = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                cwd=workdir,
            )
            if result.returncode != 0:
                stderr = (result.stderr or "").strip()
                raise RuntimeError(
                    f"codex CLI exited with code {result.returncode}: {stderr[:500]}"
                )
            text = ""
            if last_message_path.exists():
                text = last_message_path.read_text(encoding="utf-8").strip()
            if not text:
                logger.warning("Codex CLI returned empty text response")
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
