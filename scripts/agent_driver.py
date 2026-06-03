"""Agent driver: control the running Threads /saved tab via chrome-ws CDP.

Wraps the bundled superpowers-chrome `chrome-ws` CLI so an agent (or this
script invoked directly) can trigger the scrape from outside the browser.
The rest of the pipeline (classify -> notes -> unsave.json -> AutoAiSync
auto-load -> auto-unsave) happens automatically once the Tampermonkey panel
finishes the scrape.

Commands:
  python scripts/agent_driver.py probe
      Verify panel exists, SCRIPT_VERSION matches, autosave + AutoAiSync handle bound.

  python scripts/agent_driver.py status
      Dump the current panel meta block.

  python scripts/agent_driver.py scrape [--wait-seconds N]
      Click 開始抓取. If --wait-seconds > 0, poll panel state until state.status
      reports an idle state or timeout.

  python scripts/agent_driver.py click <button-id>
      Click an arbitrary panel button id (e.g. unsave-selected, load-ai).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from note_generator.config import load_json_config, read_path_setting


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


load_dotenv(PROJECT_ROOT / ".env")


def resolve_chrome_ws_path() -> Path | None:
    configured = os.environ.get("CHROME_WS_PATH", "").strip()
    if configured:
        return Path(configured)

    path = read_path_setting(load_json_config(), "chrome-ws-cli", "")
    return Path(path) if path else None


CHROME_WS: Path | None = resolve_chrome_ws_path()
EXPECTED_VERSION = "0.3.1"
PANEL_ID = "threads-saved-export-panel"
SAVED_URL_SUBSTR = "/saved"


def _run_chrome_ws(*args: str, timeout: float = 30.0) -> str:
    cmd = ["node", str(CHROME_WS), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"chrome-ws {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def list_tabs() -> list[tuple[str, str, str]]:
    raw = _run_chrome_ws("tabs")
    out: list[tuple[str, str, str]] = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            out.append((parts[0], parts[1], parts[2]))
    return out


def find_saved_tab_index() -> int:
    tabs = list_tabs()
    for idx, (_id, url, _title) in enumerate(tabs):
        if SAVED_URL_SUBSTR in url:
            return idx
    raise RuntimeError(f"no tab found containing '{SAVED_URL_SUBSTR}'. Open https://www.threads.com/saved.")


def chrome_eval(tab_index: int, expression: str) -> object:
    raw = _run_chrome_ws("eval", str(tab_index), expression)
    # chrome-ws prints the JSON-stringified result on stdout
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def chrome_click(tab_index: int, selector: str) -> None:
    _run_chrome_ws("click", str(tab_index), selector)


_SENTENCE_END_CHARS = "。！？!?."


def load_json_file(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def first_sentence(text: object) -> str:
    compact = " ".join(part.strip() for part in str(text or "").splitlines() if part.strip())
    if not compact:
        return ""
    for index, char in enumerate(compact):
        if char in _SENTENCE_END_CHARS:
            return compact[: index + 1].strip()
    return compact


def _posts_by_id(catch_posts: object) -> dict[str, dict]:
    if not isinstance(catch_posts, list):
        return {}
    out: dict[str, dict] = {}
    for post in catch_posts:
        if isinstance(post, dict) and post.get("postId"):
            out[str(post["postId"])] = post
    return out


def build_unsave_preview_lines(catch_posts: object, unsave_payload: object) -> list[str]:
    posts_by_id = _posts_by_id(catch_posts)
    items = unsave_payload.get("items", []) if isinstance(unsave_payload, dict) else []
    if not isinstance(items, list):
        return []

    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        post_id = str(item.get("postId") or "")
        post = posts_by_id.get(post_id)
        if not post:
            lines.append("作者:(unknown)| 貼文:(post not found in catch.json)")
            continue
        author = (
            str(post.get("authorName") or "").strip()
            or str(post.get("authorHandle") or "").strip()
            or "(unknown)"
        )
        sentence = first_sentence(post.get("contentText")) or "(empty)"
        lines.append(f"作者:{author}| 貼文:{sentence}")
    return lines


def ask_confirmation(input_fn=input) -> bool:
    try:
        answer = input_fn("確認執行?(y/n) ")
    except EOFError:
        return False
    return answer.strip().lower() == "y"


def _coerce_chrome_json(result: object) -> dict:
    if isinstance(result, str):
        parsed = json.loads(result)
    else:
        parsed = result
    if not isinstance(parsed, dict):
        raise RuntimeError(f"expected object result from browser, got {type(parsed).__name__}")
    return parsed


def set_browser_auto_unsave(tab_index: int, enabled: bool) -> dict:
    expr = (
        "(()=>{"
        "const api=window.ThreadSieveAutoAiSync;"
        "if(!api?.setAutoUnsave) return JSON.stringify({ok:false,error:'ThreadSieveAutoAiSync API missing'});"
        "const state=api.setAutoUnsave(" + json.dumps(enabled) + ");"
        "return JSON.stringify({ok:true,state});"
        "})()"
    )
    result = _coerce_chrome_json(chrome_eval(tab_index, expr))
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "failed to set autoUnsave"))
    return result


def run_confirmed_browser_unsave(tab_index: int) -> dict:
    expr = (
        "(async()=>{"
        "const api=window.ThreadSieveAutoAiSync;"
        "if(!api?.forceLoad||!api?.runConfirmedUnsave) return JSON.stringify({ok:false,error:'ThreadSieveAutoAiSync API missing'});"
        "const loaded=await api.forceLoad();"
        "if(!loaded?.ok) return JSON.stringify({ok:false,error:'forceLoad failed',loaded});"
        "const unsave=await api.runConfirmedUnsave();"
        "return JSON.stringify({ok:true,loaded,unsave});"
        "})()"
    )
    result = _coerce_chrome_json(chrome_eval(tab_index, expr))
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "confirmed unsave failed"))
    return result


def cmd_probe() -> int:
    idx = find_saved_tab_index()
    expr = (
        "(()=>{"
        "const panel=document.getElementById('" + PANEL_ID + "');"
        "if(!panel) return JSON.stringify({error:'panel missing'});"
        "const meta=document.getElementById('" + PANEL_ID + "-meta')?.textContent||'';"
        "const versionMatch=meta.match(/腳本版本:\\s*([0-9.]+)/);"
        "const autoSave=/自動存檔:\\s*已設定/.test(meta);"
        "const autoPanel=!!document.getElementById('threads-sieve-auto-panel');"
        "const autoStatus=document.querySelector('#threads-sieve-auto-panel [data-role=\"status\"]')?.textContent||document.documentElement.dataset.threadsSieveAutoAiSyncStatus||'';"
        "const autoSyncBound=document.documentElement.dataset.threadsSieveAutoAiSyncBound==='true'||(!autoPanel&&/handle:\\s*(?!not bound)/.test(autoStatus));"
        "const buttons={};['start','load-ai','apply-ai','select-high','unsave-selected','autosave']"
        ".forEach(k=>{buttons[k]=!!document.getElementById('" + PANEL_ID + "-'+k);});"
        "return JSON.stringify({url:location.href,scriptVersion:versionMatch?versionMatch[1]:null,autoSaveBound:autoSave,autoPanelPresent:autoPanel,autoSyncBound:autoSyncBound,autoStatus:autoStatus.trim(),buttons});"
        "})()"
    )
    result = chrome_eval(idx, expr)
    if isinstance(result, str):
        result = json.loads(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    problems: list[str] = []
    if result.get("error"):
        problems.append(result["error"])
    if result.get("scriptVersion") != EXPECTED_VERSION:
        problems.append(f"scriptVersion={result.get('scriptVersion')} expected {EXPECTED_VERSION}")
    if not result.get("autoSaveBound"):
        problems.append("autosave (catch.json) not bound")
    if not result.get("autoPanelPresent") and not result.get("autoSyncBound"):
        problems.append("AutoAiSync panel missing")
    autostatus = result.get("autoStatus", "")
    if not result.get("autoSyncBound") and ("handle: not bound" in autostatus or autostatus.startswith("handle: not bound")):
        problems.append("unsave.json handle not bound in AutoAiSync panel")
    buttons = result.get("buttons", {})
    missing_buttons = [k for k, v in buttons.items() if not v]
    if missing_buttons:
        problems.append(f"missing buttons: {missing_buttons}")
    if problems:
        print("\nPROBLEMS:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("\nOK: panel ready for agent-driven scrape", file=sys.stderr)
    return 0


def cmd_status() -> int:
    idx = find_saved_tab_index()
    expr = (
        "(()=>{const m=document.getElementById('" + PANEL_ID + "-meta');"
        "return JSON.stringify(m?m.textContent:'panel meta missing');})()"
    )
    result = chrome_eval(idx, expr)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            pass
    print(result)
    return 0


def cmd_scrape(wait_seconds: float, cutoff: str) -> int:
    idx = find_saved_tab_index()
    chrome_click(idx, "#" + PANEL_ID + "-clear")
    print(f"clicked #{PANEL_ID}-clear on tab {idx}")
    fill_expr = (
        "(()=>{const el=document.getElementById('" + PANEL_ID + "-date');"
        "if(!el) return 'no date input';"
        "el.value=" + json.dumps(cutoff) + ";"
        "el.dispatchEvent(new Event('input',{bubbles:true}));"
        "el.dispatchEvent(new Event('change',{bubbles:true}));"
        "return el.value;})()"
    )
    result = chrome_eval(idx, fill_expr)
    print(f"cutoff date set to: {result}")
    chrome_click(idx, "#" + PANEL_ID + "-start")
    print(f"clicked #{PANEL_ID}-start on tab {idx}")
    if wait_seconds <= 0:
        return 0
    deadline = time.time() + wait_seconds
    last_status = ""
    while time.time() < deadline:
        expr = (
            "(()=>{const m=document.getElementById('" + PANEL_ID + "-meta')?.textContent||'';"
            "const s=m.match(/狀態:\\s*([^\\n]+)/);"
            "const n=m.match(/已收集筆數:\\s*(\\d+)/);"
            "return JSON.stringify({status:s?s[1]:'',count:n?parseInt(n[1],10):0});})()"
        )
        try:
            result = chrome_eval(idx, expr)
        except subprocess.TimeoutExpired:
            print("WARN: status poll timed out; retrying", file=sys.stderr)
            time.sleep(3.0)
            continue
        if isinstance(result, str):
            result = json.loads(result)
        status = (result.get("status") or "").strip()
        count = result.get("count") or 0
        if status != last_status:
            print(f"[{time.strftime('%H:%M:%S')}] status={status!r} count={count}")
            last_status = status
        if any(token in status for token in ("待機中", "完成", "已停止")):
            return 0
        time.sleep(3.0)
    print("WARN: scrape did not reach idle within timeout", file=sys.stderr)
    return 2


def cmd_click(button_key: str) -> int:
    idx = find_saved_tab_index()
    chrome_click(idx, "#" + PANEL_ID + "-" + button_key)
    print(f"clicked #{PANEL_ID}-{button_key} on tab {idx}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="verify panel readiness")
    sub.add_parser("status", help="dump panel meta block")
    sp_scrape = sub.add_parser("scrape", help="click 開始抓取")
    sp_scrape.add_argument("--wait-seconds", type=float, default=0.0)
    sp_scrape.add_argument("--cutoff", default="2010-01-01", help="cutoff date YYYY-MM-DD (default 2010-01-01 = capture everything)")
    sp_click = sub.add_parser("click", help="click an arbitrary panel button by short key")
    sp_click.add_argument("button_key", help="e.g. start, load-ai, apply-ai, select-high, unsave-selected")
    args = parser.parse_args()

    if not CHROME_WS or not CHROME_WS.exists():
        print(
            f"ERROR: chrome-ws CLI path not set or path not found ({CHROME_WS}). "
            "Set paths.chrome-ws-cli in config.json.",
            file=sys.stderr,
        )
        return 2

    if args.cmd == "probe":
        return cmd_probe()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "scrape":
        return cmd_scrape(args.wait_seconds, args.cutoff)
    if args.cmd == "click":
        return cmd_click(args.button_key)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
