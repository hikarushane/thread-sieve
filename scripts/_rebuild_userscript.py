"""One-shot helper to rebuild userscripts/threads-scriber-auto.user.js as:
  base threads-scriber.user.js 0.1.3  +  AutoAiSync wrapper

Strategy: take base 0.1.3 (which already contains all DOM/AI bug fixes),
splice in the AutoAiSync block extracted from the existing auto fork,
update header + bump SCRIPT_VERSION to 0.3.0, centralize scriptVersion
injection into _appendEventNow.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE_PATH = Path(r"D:\shane_yeh\Documents\_Claude_Code\threads-scriber\threads-scriber.user.js")
AUTO_PATH = ROOT / "userscripts" / "threads-scriber-auto.user.js"
NEW_VERSION = "0.3.0"


def main() -> int:
    base = BASE_PATH.read_text(encoding="utf-8")
    auto_old = AUTO_PATH.read_text(encoding="utf-8")

    # 1. Extract AutoAiSync block from old auto.
    #    From the divider comment `// AutoAiSync — crawl-the-threads addition`
    #    through the matching `bootAutoAiSync` boot trigger lines, stopping
    #    just before the closing `})();`.
    m = re.search(
        r"(\n  // ─+\n  // AutoAiSync.*?bootAutoAiSync\(\);\s*\n\s*}\s*)(?:\n}\)\(\);\s*)?\Z",
        auto_old,
        re.DOTALL,
    )
    if not m:
        print("ERROR: failed to locate AutoAiSync block in current auto.user.js")
        return 1
    auto_block = m.group(1)

    # The auto_block currently includes the boot trigger block that calls both
    # boot() and bootAutoAiSync(). Base has its own boot trigger that calls only
    # boot(). Split auto_block at the `if (document.readyState === "loading")`
    # so we can replace base's trigger entirely.
    split_marker = "\n  if (document.readyState === \"loading\") {"
    if split_marker not in auto_block:
        print("ERROR: failed to locate boot trigger in AutoAiSync extract")
        return 1
    auto_modules, auto_boot_trigger = auto_block.split(split_marker, 1)
    auto_boot_trigger = split_marker + auto_boot_trigger

    # 2. Rewrite base header.
    base = re.sub(r"// @name         Threads Scriber\n",
                  "// @name         Threads Scriber (Auto, crawl-the-threads)\n", base, count=1)
    base = re.sub(r"// @namespace    https://local-only\.example/\n",
                  "// @namespace    https://local-only.example/crawl-the-threads/\n", base, count=1)
    base = re.sub(r"// @version      0\.1\.3\n",
                  f"// @version      {NEW_VERSION}\n", base, count=1)
    base = re.sub(r"// @description  Export saved Threads posts from the web UI to CSV or JSON\.\n",
                  "// @description  Fork of Threads Scriber that auto-loads scribe-ai.json on disk change and (optionally) auto-runs the unsave flow. Part of the crawl-the-threads project.\n",
                  base, count=1)
    base = re.sub(r"// @author       Codex\n",
                  "// @author       crawl-the-threads\n", base, count=1)

    # 3. Bump SCRIPT_VERSION constant.
    base = re.sub(r'const SCRIPT_VERSION = "0\.1\.3";',
                  f'const SCRIPT_VERSION = "{NEW_VERSION}";', base, count=1)

    # 4. Centralize scriptVersion injection so every debug event carries it.
    base = base.replace(
        "      const entry = {\n"
        "        timestamp: new Date().toISOString(),\n"
        "        type,\n"
        "        pageUrl: location.href,\n"
        "        ...payload\n"
        "      };",
        "      const entry = {\n"
        "        timestamp: new Date().toISOString(),\n"
        "        type,\n"
        "        pageUrl: location.href,\n"
        "        scriptVersion: SCRIPT_VERSION,\n"
        "        ...payload\n"
        "      };",
        1,
    )

    # 5. Splice AutoAiSync module + bootAutoAiSync function in just before
    #    base's existing boot trigger (`if (document.readyState === "loading") {`).
    boot_marker = "\n  if (document.readyState === \"loading\") {\n    document.addEventListener(\"DOMContentLoaded\", boot, { once: true });\n  } else {\n    boot();\n  }\n})();\n"
    if boot_marker not in base:
        print("ERROR: base boot trigger not in expected form")
        return 1
    replacement = auto_modules + "\n" + auto_boot_trigger.rstrip() + "\n})();\n"
    base = base.replace(boot_marker, replacement)

    AUTO_PATH.write_text(base, encoding="utf-8")
    print(f"OK: wrote {AUTO_PATH}")
    print(f"     SCRIPT_VERSION={NEW_VERSION}")
    print(f"     AutoAiSync block size={len(auto_modules)} chars")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
