"""Agent driver: control the running Threads /saved tab via chrome-ws CDP.

Wraps the bundled superpowers-chrome `chrome-ws` CLI so an agent (or this
script invoked directly) can trigger the scrape from outside the browser.
The rest of the pipeline (classify -> notes -> scribe-ai.json -> AutoAiSync
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

CHROME_WS: Path | None = Path(os.environ["CHROME_WS_PATH"]) if os.environ.get("CHROME_WS_PATH") else None
EXPECTED_VERSION = "0.3.0"
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


def cmd_probe() -> int:
    idx = find_saved_tab_index()
    expr = (
        "(()=>{"
        "const panel=document.getElementById('" + PANEL_ID + "');"
        "if(!panel) return JSON.stringify({error:'panel missing'});"
        "const meta=document.getElementById('" + PANEL_ID + "-meta')?.textContent||'';"
        "const versionMatch=meta.match(/腳本版本:\\s*([0-9.]+)/);"
        "const autoSave=/自動存檔:\\s*已設定/.test(meta);"
        "const autoPanel=!!document.getElementById('crawl-the-threads-auto-panel');"
        "const autoStatus=document.querySelector('#crawl-the-threads-auto-panel [data-role=\"status\"]')?.textContent||'';"
        "const buttons={};['start','load-ai','apply-ai','select-high','unsave-selected','autosave']"
        ".forEach(k=>{buttons[k]=!!document.getElementById('" + PANEL_ID + "-'+k);});"
        "return JSON.stringify({url:location.href,scriptVersion:versionMatch?versionMatch[1]:null,autoSaveBound:autoSave,autoPanelPresent:autoPanel,autoStatus:autoStatus.trim(),buttons});"
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
        problems.append("autosave (scribe.json) not bound")
    if not result.get("autoPanelPresent"):
        problems.append("AutoAiSync panel missing")
    autostatus = result.get("autoStatus", "")
    if "handle: not bound" in autostatus or autostatus.startswith("handle: not bound"):
        problems.append("scribe-ai.json handle not bound in AutoAiSync panel")
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
        result = chrome_eval(idx, expr)
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
        print(f"ERROR: CHROME_WS_PATH not set or path not found ({CHROME_WS}). Set CHROME_WS_PATH in .env.", file=sys.stderr)
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
