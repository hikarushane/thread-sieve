"""Push the local userscript into the running Tampermonkey editor.

Reads `userscripts/threads-scriber-auto.user.js`, injects it into Tampermonkey
via `chrome-ws` (Chrome at --remote-debugging-port=9222), clicks the active
script's Save button, and reloads the Threads /saved tab.

Auto-detects the Tampermonkey editor tab by title prefix (no UUID config).
Auto-detects the active script's save button by matching the URL hash UUID
against the base64-encoded button ids (locale-independent).

Patterns reused from `scripts/agent_driver.py`: chrome-ws subprocess wrapper,
tab list parser, eval helper, /saved tab finder.

Exit codes:
  0  push + save + reload succeeded
  2  prerequisites missing (chrome-ws CLI path or Tampermonkey editor tab)
  3  save click failed
  4  /saved tab reload failed
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
USERSCRIPT = PROJECT_ROOT / "userscripts" / "threads-scriber-auto.user.js"
EDITOR_TITLE_SUBSTRS = ("ThreadSieve (Auto", "Threads Scriber (Auto")
SAVED_URL_SUBSTR = "/saved"


def _run_chrome_ws(*args: str, timeout: float = 30.0) -> str:
    cmd = ["node", str(CHROME_WS), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"chrome-ws {args[0]} failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout.strip()


def list_tabs() -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for line in _run_chrome_ws("tabs").splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            out.append((parts[0], parts[1], parts[2]))  # id, url, title
    return out


def find_editor_tab(tabs: list[tuple[str, str, str]]) -> tuple[int, str]:
    matches = [
        (i, url)
        for i, (_id, url, title) in enumerate(tabs)
        if any(substr in title for substr in EDITOR_TITLE_SUBSTRS)
    ]
    if not matches:
        print(
            f"ERROR: no Tampermonkey editor tab with title containing one of {EDITOR_TITLE_SUBSTRS!r}.\n"
            "Open the Tampermonkey dashboard and click into the 'ThreadSieve (Auto)' script once.",
            file=sys.stderr,
        )
        sys.exit(2)
    if len(matches) > 1:
        print(f"WARN: {len(matches)} editor tabs match; using first (idx={matches[0][0]}).", file=sys.stderr)
    return matches[0]


def find_saved_tab_index(tabs: list[tuple[str, str, str]]) -> int | None:
    for i, (_id, url, _t) in enumerate(tabs):
        if SAVED_URL_SUBSTR in url:
            return i
    return None


def chrome_eval(idx: int, expression: str, timeout: float = 30.0) -> object:
    raw = _run_chrome_ws("eval", str(idx), expression, timeout=timeout)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


# Windows CreateProcess argv has a hard ~32k char limit. The userscript is
# ~140 KB and JSON-encoding bloats further, so we chunk into a window-level
# buffer and finalize with one setValue.
_PUSH_CHUNK = 6000


def push_source(idx: int, source: str) -> int:
    # Reset buffer
    chrome_eval(idx, "(()=>{window.__crawlPushBuf=''; return 'ok';})()")
    # Append chunks
    for start in range(0, len(source), _PUSH_CHUNK):
        chunk = source[start:start + _PUSH_CHUNK]
        expr = "(()=>{window.__crawlPushBuf+=" + json.dumps(chunk) + "; return window.__crawlPushBuf.length;})()"
        chrome_eval(idx, expr)
    # Commit buffer into CodeMirror
    finalize = (
        "(()=>{"
        "const uuid=(location.hash.match(/nav=([0-9a-f-]{36})/)||[])[1]||'';"
        "const encodedUuid=btoa(uuid).replace(/\\//g,'_').replace(/\\+/g,'-').replace(/=+$/,'');"
        "const editors=[...document.querySelectorAll('.CodeMirror')];"
        "const el=editors.find(cm=>{"
        "  for(let p=cm;p;p=p.parentElement){"
        "    if((p.id||'').includes(encodedUuid)) return true;"
        "  }"
        "  return false;"
        "})||editors[0];"
        "if(!el||!el.CodeMirror){delete window.__crawlPushBuf;"
        "return JSON.stringify({error:'no CodeMirror in tab'});}"
        "const buf=window.__crawlPushBuf||'';"
        "el.CodeMirror.setValue(buf);"
        "const got=el.CodeMirror.getValue().length;"
        "delete window.__crawlPushBuf;"
        "return JSON.stringify({len:got});})()"
    )
    res = chrome_eval(idx, finalize)
    if isinstance(res, str):
        res = json.loads(res)
    if res.get("error"):
        print(f"ERROR: push failed: {res['error']}", file=sys.stderr)
        sys.exit(3)
    n = int(res["len"])
    if n != len(source):
        print(f"WARN: pushed length {n} != source length {len(source)}", file=sys.stderr)
    return n


def click_save(idx: int) -> bool:
    """Click the active script's Save button (not Save-to-disk, not another script's).

    Strategy: parse UUID from `location.hash` (nav=<uuid>+editor), base64-decode
    each save-button id, click the one whose decoded prefix matches the UUID.
    Falls back to synthetic Ctrl+S on the CodeMirror textarea if no match.
    """
    expr = (
        "(()=>{"
        "const uuid=(location.hash.match(/nav=([0-9a-f-]{36})/)||[])[1]||'';"
        "const cands=[...document.querySelectorAll('button.imgbutton[title]')]"
        ".filter(b=>/^(Save|儲存|保存)$/.test((b.title||'').trim()));"
        "for(const b of cands){"
        "  const m=b.id.match(/^button_(.+?)_bu$/);"
        "  if(!m) continue;"
        "  try{"
        "    const b64=m[1].replace(/_/g,'/').replace(/-/g,'+');"
        "    const dec=atob(b64+'='.repeat((4-b64.length%4)%4));"
        "    if(dec.startsWith(uuid)){b.click();return JSON.stringify({via:'button',id:b.id});}"
        "  }catch(e){}"
        "}"
        "const ta=document.querySelector('.CodeMirror textarea');"
        "if(ta){"
        "  const ev=new KeyboardEvent('keydown',{key:'s',code:'KeyS',keyCode:83,which:83,ctrlKey:true,bubbles:true,cancelable:true});"
        "  ta.dispatchEvent(ev);"
        "  return JSON.stringify({via:'ctrl-s-fallback'});"
        "}"
        "return JSON.stringify({error:'no save button matched UUID and no CodeMirror textarea'});"
        "})()"
    )
    res = chrome_eval(idx, expr)
    if isinstance(res, str):
        res = json.loads(res)
    if res.get("error"):
        print(f"ERROR: save failed: {res['error']}", file=sys.stderr)
        return False
    print(f"saved via: {res.get('via')}", file=sys.stderr)
    return True


def reload_saved(tabs: list[tuple[str, str, str]]) -> bool:
    """Reload the /saved tab by re-navigating to its current URL.

    `chrome-ws eval` with `location.reload()` hangs: the eval call awaits a
    response over the per-tab WebSocket, but navigation kills that target
    before the response arrives. Page.navigate (via `chrome-ws navigate`) is
    fire-and-forget on the same channel.
    """
    saved = [(i, url) for i, (_id, url, _t) in enumerate(tabs) if SAVED_URL_SUBSTR in url]
    if not saved:
        print("WARN: no /saved tab open; skipping reload.", file=sys.stderr)
        return True
    idx, url = saved[0]
    try:
        _run_chrome_ws("navigate", str(idx), url)
        return True
    except RuntimeError as e:
        print(f"ERROR: reload /saved failed: {e}", file=sys.stderr)
        return False


def settle_after_reload(seconds: float = 10.0) -> None:
    """Sleep so Threads + Tampermonkey finish booting before heavy CDP evals.

    Polling for panel presence sounds tighter, but the page may report panel
    present while still mid-bootstrap, causing the next heavy eval (e.g.
    `agent_driver.py probe`) to hang past chrome-ws's 30 s timeout. A fixed
    sleep is empirically reliable (~8 s on this machine).
    """
    time.sleep(seconds)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-reload", action="store_true", help="skip reloading /saved tab after save")
    ap.add_argument("--probe", action="store_true", help="run `agent_driver.py probe` after reload")
    args = ap.parse_args()

    if not CHROME_WS or not CHROME_WS.exists():
        print(
            f"ERROR: chrome-ws CLI path not set or path not found ({CHROME_WS}).\n"
            "Set paths.chrome-ws-cli in config.json (see README setup, section 0).",
            file=sys.stderr,
        )
        return 2

    src = USERSCRIPT.read_text(encoding="utf-8")
    tabs = list_tabs()
    editor_idx, editor_url = find_editor_tab(tabs)
    n = push_source(editor_idx, src)
    print(f"pushed {n} chars into editor tab {editor_idx} ({editor_url[:80]})")

    if not click_save(editor_idx):
        return 3
    time.sleep(0.5)

    if not args.no_reload:
        if not reload_saved(tabs):
            return 4

    if args.probe:
        settle_after_reload()
        driver = Path(__file__).with_name("agent_driver.py")
        return subprocess.call([sys.executable, str(driver), "probe"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
