# Spec: Backfill Image OCR for Existing Threads Markdown

## Assumptions
- This feature belongs in `threads-sieve`, not in `PROJECT_threads-to-note`.
- The command is an agent-assisted backfill tool: the user gives a file or folder, the script scans markdown notes, filters likely OCR-missing stubs, fetches Threads images from each note's frontmatter URL, OCRs those images, and updates the existing markdown file.
- The first implementation should be deterministic and testable. "內文不夠詳細" should use a configurable rule-based heuristic, not a hidden LLM judgment.
- Existing notes should be preserved. The tool may insert or replace only the `## 圖片文字` section, and by default it skips files that already have that section.
- OCR should reuse the ThreadSieve-side implementation added for the live pipeline, rather than re-creating the old `threads-to-note` feature.

## Objective
Build a batch backfill script at `scripts/backfill_image_ocr.py` for markdown files that were already written before image OCR existed.

The primary user is the local agent/operator maintaining the knowledge wiki. They should be able to point the tool at a specific markdown file or a folder, preview which files would be touched, then run the backfill safely. A single failing Threads post must not stop the batch.

Acceptance criteria:
- The script scans a file or directory of `.md` files.
- It selects default candidates only when frontmatter has `status: stub`, no existing `## 圖片文字`, a Threads URL exists in frontmatter key `網址` or `url`, and the markdown body is below the detail threshold.
- It fetches Threads images using the ThreadSieve-side OCR flow and OCRs them with the existing Gemini image OCR client.
- It inserts the generated `## 圖片文字` section before `## Sources`.
- It writes JSONL logs for `processed`, `skipped`, `failed`, and `no_images`.
- It supports `--dry-run` without modifying files.
- It prints a batch summary and exits successfully when individual files soft-fail.

## Tech Stack
- Language: Python 3.x, matching the existing scripts and tests.
- Test runner: `pytest`.
- Existing OCR modules to reuse:
  - `scripts/image_ocr_to_markdown.py` for Threads image discovery/OCR helpers where practical.
  - `scripts/_gemini_client.py` for Gemini Vision OCR calls.
- Existing browser dependency: Playwright, already used by ThreadSieve-side OCR.
- Configuration:
  - Gemini API key should come from existing environment/config patterns.
  - No hardcoded secrets.
  - No hardcoded knowledge-wiki absolute paths.

## Commands
Create feature branch:

```powershell
git switch -c codex/backfill-image-ocr
```

Preview candidates in a folder:

```powershell
python scripts/backfill_image_ocr.py --path "D:\shane_yeh\Documents\_Claude_Code\knowledge-wiki\wiki-pages\AI 工具" --dry-run
```

Backfill one markdown file:

```powershell
python scripts/backfill_image_ocr.py --path "D:\shane_yeh\Documents\_Claude_Code\knowledge-wiki\wiki-pages\AI 工具\AI Agent\Claude Code：30秒搞定套件CVE.md"
```

Backfill with explicit log path:

```powershell
python scripts/backfill_image_ocr.py --path "D:\shane_yeh\Documents\_Claude_Code\knowledge-wiki\wiki-pages\AI 工具" --log data/backfill-image-ocr.jsonl
```

Run focused tests:

```powershell
pytest tests/test_backfill_image_ocr.py -q
```

Run full test suite:

```powershell
pytest tests/ -q
```

## Project Structure
```text
scripts/
  backfill_image_ocr.py        # New batch backfill CLI and pure helper functions
  image_ocr_to_markdown.py     # Existing ThreadSieve-side Threads image/OCR flow to reuse
  _gemini_client.py            # Existing Gemini image OCR client

tests/
  test_backfill_image_ocr.py   # New unit tests for parsing, insertion, dry-run, summary
  test_image_ocr_to_markdown.py# Existing OCR helper tests; update only if helpers are shared

data/
  backfill-image-ocr.jsonl     # Default or example log destination if user supplies data/
```

## CLI Behavior
The script should expose a small, explicit CLI:

```text
python scripts/backfill_image_ocr.py --path <file-or-directory> [options]

Options:
  --path <path>                 Required. Markdown file or folder to scan.
  --log <path>                  Optional JSONL log path. Default can be timestamped under data/.
  --dry-run                     Scan and log planned actions without fetching images or editing files.
  --force                       Reprocess files that already contain ## 圖片文字.
  --min-content-chars <int>     Detail threshold for non-frontmatter body text. Default: 800.
  --limit <int>                 Optional cap for agent-controlled test batches.
  --headless / --headed         Playwright mode, following existing OCR defaults.
```

Default candidate rule:

```python
def should_backfill(note):
    return (
        note.frontmatter.get("status") == "stub"
        and note.thread_url is not None
        and not note.has_image_text_section
        and note.main_content_chars < min_content_chars
    )
```

`--force` relaxes only the existing-section skip, allowing replacement of `## 圖片文字`. It should not bypass missing URL or missing `status: stub`.

## Markdown Parsing
Frontmatter parsing requirements:
- Support YAML-style frontmatter bounded by `---` at the beginning of the file.
- Extract URL from frontmatter key `網址` first, then `url`.
- Strip quotes around URL values.
- Treat missing or malformed frontmatter as `skipped`.

Body detail heuristic:
- Count characters after frontmatter while excluding the `## Sources` section and excluding any existing `## 圖片文字` section.
- Default threshold: `800` non-whitespace characters.
- The threshold must be configurable for tests and CLI use.

Section insertion requirements:
- If `## 圖片文字` does not exist, insert the section immediately before `## Sources`.
- If `## Sources` does not exist, append the section at the end of the file.
- If `## 圖片文字` exists and `--force` is set, replace only that section.
- Preserve the rest of the markdown content and line endings as much as practical.
- Use this section shape:

```markdown
## 圖片文字

### 圖片 1

<ocr text>

### 圖片 2

<ocr text>
```

## OCR Flow
For each selected candidate:
- Fetch the Threads post URL from frontmatter.
- Use the ThreadSieve-side Threads image discovery flow to find post image URLs.
- If no image URLs are found, write a `no_images` log entry and leave the file unchanged.
- For each image, use the existing Gemini image OCR client.
- If OCR returns usable text for at least one image, insert or replace the markdown section.
- If fetching or OCR raises, write a `failed` log entry and continue to the next file.

Soft failure policy:
- Per-file failures must not abort the batch.
- The process should return success if the batch runner itself worked, even when individual files failed.
- Fatal CLI/input errors, such as missing `--path`, unreadable root path, or invalid log destination, may exit non-zero before processing.

## JSONL Log
The script writes one JSON object per considered markdown file.

Required fields:

```json
{
  "timestamp": "2026-05-24T12:34:56+02:00",
  "path": "D:\\...",
  "post_url": "https://www.threads.com/@...",
  "status": "processed",
  "reason": "ocr_inserted",
  "dry_run": false,
  "image_count": 3,
  "ocr_text_count": 3,
  "chars_before": 421,
  "chars_after": 2140,
  "error": null
}
```

Valid `status` values:
- `processed`: file was updated, or would be updated in `--dry-run`.
- `skipped`: file did not match candidate criteria.
- `no_images`: candidate matched, but no Threads post images were discovered.
- `failed`: candidate matched, but fetch/OCR/write failed.

Recommended `reason` values:
- `dry_run_candidate`
- `ocr_inserted`
- `ocr_replaced`
- `already_has_image_text`
- `status_not_stub`
- `content_detailed_enough`
- `missing_url`
- `no_images_found`
- `fetch_failed`
- `ocr_failed`
- `write_failed`

## Batch Summary
At the end, print a concise summary:

```text
Backfill Image OCR summary
Scanned: 42
Processed: 6
Skipped: 31
No images: 3
Failed: 2
Log: data/backfill-image-ocr-20260524-123456.jsonl
```

The summary should be returned from a pure helper as data so tests can assert it without scraping stdout.

## Code Style
Prefer small pure helpers around the file-system and network edges. The network/OCR parts should be injectable for tests.

Example shape:

```python
@dataclass(frozen=True)
class BackfillDecision:
    status: str
    reason: str
    post_url: str | None = None


def extract_frontmatter_url(markdown: str) -> str | None:
    frontmatter = parse_frontmatter(markdown)
    return frontmatter.get("網址") or frontmatter.get("url")


def insert_image_text_section(markdown: str, ocr_texts: list[str], *, force: bool = False) -> str:
    section = build_image_text_section(ocr_texts)
    if has_image_text_section(markdown):
        if not force:
            return markdown
        return replace_image_text_section(markdown, section)
    return insert_before_sources(markdown, section)
```

Guidelines:
- Keep CLI parsing thin; put behavior in testable functions.
- Do not use ad hoc path globals.
- Keep JSONL event construction centralized.
- Reuse existing OCR helpers rather than duplicating browser/Gemini code.
- Do not add broad refactors unrelated to backfill behavior.

## Testing Strategy
Add `tests/test_backfill_image_ocr.py` with focused unit tests. Mock image discovery and OCR; do not hit Threads or Gemini in unit tests.

Required tests:
- URL extraction:
  - Extracts `網址` from frontmatter.
  - Extracts `url` from frontmatter.
  - Prefers `網址` when both are present.
  - Handles quoted values.
  - Returns missing-url skip decision when absent.
- Section insertion/replacement:
  - Inserts `## 圖片文字` before `## Sources`.
  - Appends when `## Sources` is absent.
  - Replaces existing `## 圖片文字` only with `--force`.
  - Preserves surrounding content.
- Skip existing:
  - Default behavior skips files already containing `## 圖片文字`.
  - `--force` turns the existing section into a candidate.
- Dry-run:
  - Does not call image discovery/OCR.
  - Does not write markdown files.
  - Writes/logs `processed` with `reason: dry_run_candidate` for candidates.
- Batch summary:
  - Aggregates `processed`, `skipped`, `failed`, and `no_images`.
  - Continues after one item fails.
  - Returns summary data independent of stdout.

Optional integration smoke test:
- Use a temporary markdown file with injected fake image discovery/OCR callables and verify the file is updated on disk.

## Boundaries
Always:
- Keep all failures soft at the per-note level.
- Skip existing `## 圖片文字` by default.
- Use frontmatter `網址` or `url` as the source URL.
- Insert OCR output before `## Sources`.
- Log every considered markdown file as JSONL.
- Run `pytest tests/test_backfill_image_ocr.py -q` before claiming implementation complete.

Ask first:
- Adding new third-party dependencies.
- Changing existing live crawl/watch pipeline behavior.
- Editing README beyond the README consistency gate.
- Changing the default candidate heuristic from deterministic rules to LLM judgment.
- Processing non-`stub` notes by default.

Never:
- Hardcode API keys, tokens, passwords, or local user-specific paths in source code.
- Require `PROJECT_threads-to-note` to run this backfill.
- Delete or rewrite unrelated markdown sections.
- Abort the whole batch because one Threads post fails.
- Commit generated JSONL logs unless explicitly requested.

## Success Criteria
- `scripts/backfill_image_ocr.py` exists and can scan a file or folder.
- A dry run against a folder reports candidates without modifying files.
- A real run updates eligible markdown by adding `## 圖片文字` before `## Sources`.
- Files with existing `## 圖片文字` are skipped by default.
- JSONL logs contain one event per considered file with the required status set.
- Unit tests cover URL extraction, section insertion/replacement, skip existing, dry-run, and batch summary.
- Full `pytest tests/ -q` passes.

## Open Questions
- Should `status: Stub` or other case variants be accepted, or only exact `stub`?
- Should the default detail threshold be `800` characters, or do you prefer a different number for your wiki notes?
- Should `--force` also allow non-`stub` notes, or should that require a separate future flag?
