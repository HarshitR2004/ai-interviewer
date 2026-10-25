[CmdletBinding()]
param(
    [ValidateSet('Start', 'Stop', 'Status', 'Check')]
    [string]$Action = 'Start',
    [switch]$OpenBrowser,
    [ValidateRange(30, 600)]
    [int]$StartupTimeoutSeconds = 180
)

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$runDirectory = Join-Path $workspace 'work/demo'
$statePath = Join-Path $runDirectory 'processes.json'
$python = Join-Path $workspace 'work/speech-venv/Scripts/python.exe'
$livekit = Join-Path $workspace 'work/livekit/livekit-server.exe'
$next = Join-Path $workspace 'frontend/node_modules/next/dist/bin/next'
$browserUrl = 'http://127.0.0.1:5173'
$script:services = @()
$script:outputs = @()

function Get-OwnedProcess($Service) {
    $process = Get-Process -Id $Service.pid -ErrorAction SilentlyContinue
    if ($process -and $process.StartTime.ToUniversalTime().Ticks.ToString() -eq $Service.startTicks -and
        $process.Path -eq $Service.path) {
        return $process
    }
    return $null
}

function Stop-Demo {
    if (!(Test-Path -LiteralPath $statePath)) {
        Write-Host 'No launcher-managed demo is running.'
        return
    }
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    # Validate process identity before stopping its tree, including worker inference children.
    foreach ($service in @($saved.services)[($saved.services.Count - 1)..0]) {
        $process = Get-OwnedProcess $service
        if ($process) {
            Write-Host "Stopping $($service.name)..."
            & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0 -and (Get-OwnedProcess $service)) {
                throw "Could not stop $($service.name). State retained at $statePath"
            }
        }
    }
    Remove-Item -LiteralPath $statePath
    Write-Host 'Demo stopped.'
}

function Save-State {
    @{ services = @($script:services) } |
        ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Start-ServiceProcess([string]$Name, [string]$Executable, [string[]]$Arguments, [string]$Directory) {
    $info = New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Arguments -join ' '
    $info.WorkingDirectory = $Directory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $info.EnvironmentVariables['PYTHONUNBUFFERED'] = '1'
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $info
    [void]$process.Start()
    # A newly launched Windows process can briefly report an empty executable path.
    $executablePath = (Resolve-Path -LiteralPath $Executable).Path
    $script:services += [pscustomobject]@{
        name = $Name; pid = $process.Id; startTicks = $process.StartTime.ToUniversalTime().Ticks.ToString()
        path = $executablePath; ready = $false
    }
    foreach ($reader in @($process.StandardOutput, $process.StandardError)) {
        $script:outputs += [pscustomobject]@{
            name = $Name; reader = $reader; pending = $reader.ReadLineAsync(); closed = $false
        }
    }
    Save-State
    Write-Host "Started $Name (PID $($process.Id))."
}

function Write-ServiceOutput {
    foreach ($output in $script:outputs) {
        while (!$output.closed -and $output.pending.IsCompleted) {
            $line = $output.pending.GetAwaiter().GetResult()
            if ($null -eq $line) { $output.closed = $true; break }
            Write-Host "[$($output.name)] $line"
            if ($line -match 'registered worker') {
                ($script:services | Where-Object name -eq $output.name).ready = $true
            }
            $output.pending = $output.reader.ReadLineAsync()
        }
    }
}

function Wait-Service([string]$Name, [string]$Url = '') {
    $service = $script:services | Where-Object name -eq $Name
    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Write-ServiceOutput
        if (!(Get-OwnedProcess $service)) {
            throw "$Name exited during startup. See the terminal output above."
        }
        if ($Url) {
            try {
                $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 -Proxy $null
                if ($response.StatusCode -eq 200) { return }
            } catch { } # A bound port alone does not mean the service is ready.
        } else {
            if ($service.ready) { return }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$Name was not ready after $StartupTimeoutSeconds seconds. See the terminal output above."
}

if ($Action -eq 'Stop') { Stop-Demo; return }
if ($Action -eq 'Status') {
    if (!(Test-Path -LiteralPath $statePath)) { Write-Host 'Demo is stopped.'; return }
    $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    foreach ($service in $saved.services) {
        $status = if (Get-OwnedProcess $service) { 'running' } else { 'stopped' }
        Write-Host "$($service.name): $status (PID $($service.pid))"
    }
    Write-Host "Browser: $browserUrl"
    return
}

Push-Location $workspace
try {
    foreach ($required in @($python, $livekit, $next)) {
        if (!(Test-Path -LiteralPath $required)) {
            throw "Missing $required. These local files are generated, not included in Git. From $workspace run: powershell -ExecutionPolicy Bypass -File scripts/setup-demo.ps1"
        }
    }
    $node = (Get-Command node.exe -ErrorAction Stop).Source
    # Print only safe validation errors; never dump Settings or .env credentials.
    $preflight = @'
import importlib.util
import sys
from pathlib import Path
try:
    from backend.settings import Settings
    s = Settings()
    assert s.backend_url in ('http://127.0.0.1:8000', 'http://localhost:8000'), 'Use BACKEND_URL=http://127.0.0.1:8000 for this launcher.'
    assert s.livekit_url in ('ws://127.0.0.1:7880', 'ws://localhost:7880'), 'Use LIVEKIT_URL=ws://127.0.0.1:7880 for this launcher.'
    assert s.livekit_api_key == 'devkey' and s.livekit_api_secret.get_secret_value() == 'secret', 'Use the LiveKit development credentials from .env.example.'
    assert s.llm_api_key, 'Configure GEMINI_API_KEY for hosted speech.'
    for name in ('uvicorn', 'livekit.agents', 'google.genai'):
        assert importlib.util.find_spec(name), 'Missing Python voice dependencies; install requirements-lock.txt.'
except AssertionError as exc:
    print(str(exc))
    sys.exit(1)
except Exception:
    print('Python dependencies or settings are invalid. Check README.md and .env (including LIVE_REASONING_TIMEOUT_SEC=8).')
    sys.exit(1)
'@
    $result = & $python -c $preflight
    if ($LASTEXITCODE -ne 0) { throw "Demo preflight failed: $result" }
    if ($Action -eq 'Check') {
        Write-Host "Project: $workspace`nPython: $python`nLiveKit: $livekit`nFrontend: $next"
        Write-Host 'Demo prerequisites and local settings passed. Model loading is checked when the worker starts.'
        return
    }

    if (Test-Path -LiteralPath $statePath) {
        $saved = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
        $alive = @($saved.services | Where-Object { Get-OwnedProcess $_ })
        if ($alive.Count -gt 0) {
            throw 'A launcher-managed demo already has running processes. Use -Action Status or -Action Stop before starting again.'
        }
        Remove-Item -LiteralPath $statePath
    }
    foreach ($port in @(8000, 7880, 7881, 5173)) {
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $port)
        try { $listener.Start() } catch { throw "Port $port is occupied. Stop the existing service before starting the demo; no existing processes were stopped." }
        finally { $listener.Stop() }
    }
    New-Item -ItemType Directory -Path $runDirectory -Force | Out-Null
    try {
        Start-ServiceProcess 'livekit' $livekit @('--dev', '--bind', '127.0.0.1') $workspace
        Wait-Service 'livekit' 'http://127.0.0.1:7880'
        Start-ServiceProcess 'api' $python @('-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000') $workspace
        Wait-Service 'api' 'http://127.0.0.1:8000/openapi.json'
        Start-ServiceProcess 'voice' $python @('-m', 'backend.voice_agent', 'dev', '--no-reload', '--log-level', 'info') $workspace
        Write-Host 'Waiting for voice worker registration (hosted Gemini speech)...'
        Wait-Service 'voice'
        # Quote the file argument because the workspace may contain spaces.
        Start-ServiceProcess 'frontend' $node @(('"' + $next + '"'), 'dev', '--hostname', '127.0.0.1', '--port', '5173') (Join-Path $workspace 'frontend')
        Wait-Service 'frontend' $browserUrl
    } catch {
        Write-Warning $_.Exception.Message
        Stop-Demo
        throw
    }
    Write-Host "`nDemo ready: $browserUrl"
    Write-Host 'Streaming service logs below. Press Ctrl+C to stop the demo.'
    if ($OpenBrowser) { Start-Process $browserUrl }
    while ($true) {
        Write-ServiceOutput
        foreach ($service in $script:services) {
            if (!(Get-OwnedProcess $service)) {
                Write-ServiceOutput
                throw "$($service.name) exited. See the terminal output above."
            }
        }
        Start-Sleep -Milliseconds 100
    }
} finally {
    if ($script:services.Count -gt 0) { Stop-Demo }
    foreach ($output in $script:outputs) { $output.reader.Dispose() }
    Pop-Location
}
