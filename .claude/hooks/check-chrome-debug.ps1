# PreToolUse hook: block agent_driver.py / push_userscript.py when Chrome
# remote debugging is not running on port 9222.
$raw = [Console]::In.ReadToEnd()
$data = $raw | ConvertFrom-Json
$cmd = $data.tool_input.command

if ($cmd -notmatch 'agent_driver\.py|push_userscript\.py') { exit 0 }

$ok = $false
try {
    $tcp = [System.Net.Sockets.TcpClient]::new()
    $ar  = $tcp.BeginConnect('127.0.0.1', 9222, $null, $null)
    $ok  = $ar.AsyncWaitHandle.WaitOne(500)
    $tcp.Close()
} catch {}

if (-not $ok) {
    [Console]::Error.WriteLine("ERROR: Chrome remote debugging not detected on port 9222.")
    [Console]::Error.WriteLine("Launch Chrome with --remote-debugging-port=9222 first (use the dedicated shortcut from README).")
    [Console]::Error.WriteLine("Do NOT open Edge or a plain Chrome window.")
    exit 2
}
