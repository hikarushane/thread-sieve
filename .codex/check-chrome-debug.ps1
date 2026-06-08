$ErrorActionPreference = 'Stop'

function Get-CommandText {
    param($Data, [string] $Raw)

    $parts = New-Object System.Collections.Generic.List[string]

    if ($null -ne $Data) {
        foreach ($path in @(
            @('tool_input', 'command'),
            @('toolInput', 'command'),
            @('input', 'command'),
            @('arguments', 'command')
        )) {
            $node = $Data
            foreach ($segment in $path) {
                if ($null -eq $node -or -not ($node.PSObject.Properties.Name -contains $segment)) {
                    $node = $null
                    break
                }
                $node = $node.$segment
            }
            if ($node -is [string] -and $node.Trim().Length -gt 0) {
                $parts.Add($node)
            }
        }

        foreach ($name in @('tool_input', 'toolInput', 'input', 'arguments')) {
            if ($Data.PSObject.Properties.Name -contains $name) {
                $value = $Data.$name
                if ($value -is [string] -and $value.Trim().Length -gt 0) {
                    $parts.Add($value)
                }
            }
        }
    }

    if ($parts.Count -eq 0 -and -not [string]::IsNullOrWhiteSpace($Raw)) {
        $parts.Add($Raw)
    }

    return ($parts -join "`n")
}

function Test-PortOpen {
    param([string] $HostName, [int] $Port)

    try {
        $tcp = [System.Net.Sockets.TcpClient]::new()
        $async = $tcp.BeginConnect($HostName, $Port, $null, $null)
        $ok = $async.AsyncWaitHandle.WaitOne(500)
        if ($ok) {
            $tcp.EndConnect($async)
        }
        $tcp.Close()
        return $ok
    } catch {
        return $false
    }
}

try {
    $raw = [Console]::In.ReadToEnd()
    $data = $null
    if (-not [string]::IsNullOrWhiteSpace($raw)) {
        try {
            $data = $raw | ConvertFrom-Json
        } catch {
            $data = $null
        }
    }

    $commandText = Get-CommandText -Data $data -Raw $raw
    if ($commandText -notmatch 'agent_driver\.py|push_userscript\.py') {
        exit 0
    }

    if (Test-PortOpen -HostName '127.0.0.1' -Port 9222) {
        exit 0
    }

    [Console]::Error.WriteLine('Chrome remote debugging is NOT running on port 9222.')
    [Console]::Error.WriteLine('Launch Chrome with --remote-debugging-port=9222 first, using the dedicated Chrome shortcut from README.')
    [Console]::Error.WriteLine('Do NOT open Edge or a plain Chrome window for agent_driver.py / push_userscript.py automation.')
    exit 2
} catch {
    [Console]::Error.WriteLine("Chrome debug preflight hook failed: $($_.Exception.Message)")
    exit 2
}
