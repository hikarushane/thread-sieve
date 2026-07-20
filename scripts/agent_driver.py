"""Agent driver: control the running Threads /saved tab via chrome-ws CDP.

Wraps the bundled superpowers-chrome `chrome-ws` CLI so an agent (or this
script invoked directly) can trigger the scrape from outside the browser.
After the scrape, the watcher/classify step writes unsave.json; the scrape
command's confirmation gate reads that file from disk at confirm time and
injects it into the page through the window.ThreadSieveAgent bridge
(full-branch userscript >= 0.4.2) to run the one-shot unsave pass.

Commands:
  python scripts/agent_driver.py probe
      Verify panel exists, SCRIPT_VERSION matches, autosave bound, agent bridge present.

  python scripts/agent_driver.py status
      Dump the current panel meta block.

  python scripts/agent_driver.py scrape [--wait-seconds N]
      Click 開始抓取. If --wait-seconds > 0, poll panel state until state.status
      reports an idle state or timeout.

  python scripts/agent_driver.py click <button-id>
      Click an arbitrary panel button id (e.g. start, stop, clear, unsave-run).
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

from note_generator.config import (
    DEFAULT_INPUT_PATH,
    DEFAULT_UNSAVE_PATH,
    load_json_config,
    read_path_setting,
)


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
EXPECTED_VERSION = "0.5.4"
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


def chrome_eval(tab_index: int, expression: str, *, timeout: float = 30.0) -> object:
    raw = _run_chrome_ws("eval", str(tab_index), expression, timeout=timeout)
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
            has_preview_metadata = any(
                str(item.get(key) or "").strip()
                for key in ("authorName", "authorHandle", "contentText")
            )
            if not has_preview_metadata:
                lines.append("作者:(unknown)| 貼文:(post not found in catch.json)")
                continue
            post = item
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


AGENT_BRIDGE_MISSING_HINT = (
    "ThreadSieveAgent bridge missing — install the full-branch userscript "
    "(userscripts/threads-scriber-auto.user.js >= 0.4.2)"
)
BRIDGE_PROBE_EXPR = "(()=>JSON.stringify({present:!!window.ThreadSieveAgent?.runUnsave}))()"
MAX_UNSAVE_PAYLOAD_CHARS = 200_000
UNSAVE_EVAL_TIMEOUT_SECONDS = 900.0


def agent_bridge_present(tab_index: int) -> bool:
    result = _coerce_chrome_json(chrome_eval(tab_index, BRIDGE_PROBE_EXPR))
    return bool(result.get("present"))


def build_agent_unsave_expr(payload_text: str) -> str:
    return (
        "(async()=>{"
        "const api=window.ThreadSieveAgent;"
        "if(!api?.runUnsave) return JSON.stringify({ok:false,error:" + json.dumps(AGENT_BRIDGE_MISSING_HINT) + "});"
        "const result=await api.runUnsave(" + json.dumps(payload_text) + ");"
        "return JSON.stringify(result);"
        "})()"
    )


def run_agent_bridge_unsave(tab_index: int, payload_text: str) -> dict:
    if len(payload_text) > MAX_UNSAVE_PAYLOAD_CHARS:
        raise RuntimeError(
            f"unsave.json too large to inject over CDP ({len(payload_text)} chars > "
            f"{MAX_UNSAVE_PAYLOAD_CHARS}); run the unsave from the browser panel instead"
        )
    result = _coerce_chrome_json(
        chrome_eval(tab_index, build_agent_unsave_expr(payload_text), timeout=UNSAVE_EVAL_TIMEOUT_SECONDS)
    )
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "agent bridge unsave failed"))
    return result


def resolve_pipeline_paths() -> tuple[Path, Path]:
    config_data = load_json_config()
    catch_path = Path(
        os.environ.get("CATCH_PATH", "").strip()
        or read_path_setting(config_data, "catch-json", str(DEFAULT_INPUT_PATH))
    )
    unsave_path = Path(
        os.environ.get("UNSAVE_PATH", "").strip()
        or read_path_setting(config_data, "unsave-json", str(DEFAULT_UNSAVE_PATH))
    )
    return catch_path, unsave_path


def read_generated_at(path: Path) -> str:
    try:
        payload = load_json_file(path)
    except (FileNotFoundError, json.JSONDecodeError):
        return ""
    if isinstance(payload, dict):
        return str(payload.get("generatedAt") or "")
    return ""


def wait_for_unsave_payload(
    *,
    unsave_path: Path,
    previous_generated_at: str,
    timeout_seconds: float,
    poll_seconds: float = 1.0,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        try:
            payload = load_json_file(unsave_path)
        except (FileNotFoundError, json.JSONDecodeError):
            time.sleep(poll_seconds)
            continue
        if isinstance(payload, dict):
            generated_at = str(payload.get("generatedAt") or "")
            if generated_at and generated_at != previous_generated_at:
                return payload
        time.sleep(poll_seconds)
    raise TimeoutError(f"unsave.json did not update within {timeout_seconds:g}s: {unsave_path}")


def run_unsave_confirmation_gate(
    *,
    tab_index: int,
    catch_path: Path,
    unsave_path: Path,
    previous_generated_at: str,
    timeout_seconds: float,
    input_fn=input,
) -> int:
    print(f"等待新的 unsave.json: {unsave_path}")
    try:
        unsave_payload = wait_for_unsave_payload(
            unsave_path=unsave_path,
            previous_generated_at=previous_generated_at,
            timeout_seconds=timeout_seconds,
        )
    except TimeoutError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 3

    items = unsave_payload.get("items", []) if isinstance(unsave_payload, dict) else []
    if not items:
        print("unsave.json 已更新，但沒有候選貼文；不需取消儲存。")
        return 0

    catch_posts = load_json_file(catch_path)
    print("即將取消儲存以下貼文:")
    for line in build_unsave_preview_lines(catch_posts, unsave_payload):
        print(line)

    if not ask_confirmation(input_fn):
        print("已取消執行；unsave.json 已保留，瀏覽器端不動。")
        return 0

    payload_text = unsave_path.read_text(encoding="utf-8")
    result = run_agent_bridge_unsave(tab_index, payload_text)
    print(
        "已執行取消儲存；"
        f"unsaved={result.get('unsaved', '?')} "
        f"skipped={result.get('skipped', '?')} "
        f"failed={result.get('failed', '?')} "
        f"stopReason={result.get('stopReason', '?')}"
    )
    return 0


PROBE_BUTTON_KEYS = ("start", "stop", "autosave", "clear", "unsave-run")


def evaluate_probe_result(result: dict) -> list[str]:
    problems: list[str] = []
    if result.get("error"):
        problems.append(str(result["error"]))
        return problems
    if result.get("scriptVersion") != EXPECTED_VERSION:
        problems.append(f"scriptVersion={result.get('scriptVersion')} expected {EXPECTED_VERSION}")
    if not result.get("autoSaveBound"):
        problems.append("autosave (catch.json) not bound")
    if not result.get("agentBridge"):
        problems.append(AGENT_BRIDGE_MISSING_HINT)
    buttons = result.get("buttons", {})
    missing_buttons = [k for k, v in buttons.items() if not v]
    if missing_buttons:
        problems.append(f"missing buttons: {missing_buttons}")
    return problems


def cmd_probe() -> int:
    idx = find_saved_tab_index()
    button_keys_js = json.dumps(list(PROBE_BUTTON_KEYS))
    expr = (
        "(()=>{"
        "const panel=document.getElementById('" + PANEL_ID + "');"
        "if(!panel) return JSON.stringify({error:'panel missing'});"
        "const meta=document.getElementById('" + PANEL_ID + "-meta')?.textContent||'';"
        "const versionMatch=meta.match(/腳本版本:\\s*([0-9.]+)/);"
        "const autoSave=/自動存檔:\\s*已設定/.test(meta);"
        "const bridge=!!window.ThreadSieveAgent?.runUnsave;"
        "const buttons={};" + button_keys_js
        + ".forEach(k=>{buttons[k]=!!document.getElementById('" + PANEL_ID + "-'+k);});"
        "return JSON.stringify({url:location.href,scriptVersion:versionMatch?versionMatch[1]:null,autoSaveBound:autoSave,agentBridge:bridge,buttons});"
        "})()"
    )
    result = chrome_eval(idx, expr)
    if isinstance(result, str):
        result = json.loads(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))

    problems = evaluate_probe_result(result)
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


def cmd_scrape(
    wait_seconds: float,
    cutoff: str,
    *,
    confirm_unsave: bool = False,
    unsave_timeout_seconds: float = 600.0,
    input_fn=input,
) -> int:
    idx = find_saved_tab_index()
    catch_path: Path | None = None
    unsave_path: Path | None = None
    previous_generated_at = ""
    if confirm_unsave:
        catch_path, unsave_path = resolve_pipeline_paths()
        previous_generated_at = read_generated_at(unsave_path)
        try:
            bridge_ready = agent_bridge_present(idx)
        except RuntimeError as error:
            print(f"ERROR: cannot check agent bridge: {error}", file=sys.stderr)
            return 2
        if not bridge_ready:
            print(f"ERROR: cannot enable Terminal B gate: {AGENT_BRIDGE_MISSING_HINT}", file=sys.stderr)
            print("Deploy the latest userscript with: python scripts/push_userscript.py --probe", file=sys.stderr)
            return 2
        print("agent bridge ready; Terminal B confirmation gate is active")
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
        scrape_rc = 0
    else:
        scrape_rc = None
    if scrape_rc is None:
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
                scrape_rc = 0
                break
            time.sleep(3.0)
        if scrape_rc is None:
            print("WARN: scrape did not reach idle within timeout", file=sys.stderr)
            scrape_rc = 2

    if scrape_rc != 0:
        return scrape_rc
    if confirm_unsave:
        assert catch_path is not None
        assert unsave_path is not None
        return run_unsave_confirmation_gate(
            tab_index=idx,
            catch_path=catch_path,
            unsave_path=unsave_path,
            previous_generated_at=previous_generated_at,
            timeout_seconds=unsave_timeout_seconds,
            input_fn=input_fn,
        )
    return 0


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
    sp_scrape.add_argument(
        "--no-unsave-confirm",
        action="store_true",
        help="skip the Terminal B unsave confirmation gate and only trigger scrape",
    )
    sp_scrape.add_argument(
        "--unsave-timeout-seconds",
        type=float,
        default=600.0,
        help="seconds to wait for watch_pipeline/classify to write a fresh unsave.json before prompting",
    )
    sp_click = sub.add_parser("click", help="click an arbitrary panel button by short key")
    sp_click.add_argument("button_key", help="e.g. start, stop, autosave, clear, unsave-run")
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
        return cmd_scrape(
            args.wait_seconds,
            args.cutoff,
            confirm_unsave=not args.no_unsave_confirm,
            unsave_timeout_seconds=args.unsave_timeout_seconds,
        )
    if args.cmd == "click":
        return cmd_click(args.button_key)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
