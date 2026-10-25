[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$python = Join-Path $workspace 'work/speech-venv/Scripts/python.exe'

Push-Location $workspace
try {
    # Fail before making changes if the two externally installed runtimes are absent.
    $bootstrapPython = (Get-Command python.exe -ErrorAction Stop).Source
    $npm = (Get-Command npm.cmd -ErrorAction Stop).Source
    & $bootstrapPython -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.12 or later, then rerun setup.' }

    New-Item -ItemType Directory -Path (Join-Path $workspace 'work') -Force | Out-Null
    if (!(Test-Path -LiteralPath $python)) {
        Write-Host 'Creating work/speech-venv...'
        & $bootstrapPython -m venv (Join-Path $workspace 'work/speech-venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    Write-Host 'Installing pinned Python dependencies...'
    & $python -m pip install -r requirements-lock.txt
    if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
    & $python -m pip install --no-deps -e '.[voice,test]'
    if ($LASTEXITCODE -ne 0) { throw 'Project installation failed.' }

    if (!(Test-Path -LiteralPath (Join-Path $workspace '.env'))) {
        Copy-Item -LiteralPath (Join-Path $workspace '.env.example') -Destination (Join-Path $workspace '.env')
        Write-Host 'Created .env. Configure GEMINI_API_KEY, LLM_BASE_URL and LLM_MODEL before starting.'
    }
    if (!(Test-Path -LiteralPath (Join-Path $workspace 'work/livekit/livekit-server.exe'))) {
        & (Join-Path $PSScriptRoot 'setup-livekit.ps1')
    }
    Write-Host 'Checking hosted Gemini speech access...'
    & $python (Join-Path $PSScriptRoot 'setup_speech.py')
    if ($LASTEXITCODE -ne 0) { throw 'Gemini speech preflight failed. Check the error above before starting.' }
    & $npm --prefix (Join-Path $workspace 'frontend') ci
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }

    Write-Host "`nSetup complete in $workspace"
    Write-Host 'Configure your LLM in .env, then run:'
    Write-Host 'powershell -ExecutionPolicy Bypass -File scripts/start-demo.ps1 -OpenBrowser'
} finally {
    Pop-Location
}
