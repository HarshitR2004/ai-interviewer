$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$destination = Join-Path $workspace 'work/livekit'
New-Item -ItemType Directory -Force -Path $destination | Out-Null
$archive = Join-Path $destination 'server.zip'
Invoke-WebRequest 'https://github.com/livekit/livekit/releases/download/v1.13.10/livekit_1.13.10_windows_amd64.zip' -OutFile $archive
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower() -ne 'fd4b7c2c3c1e4c71adaa4f6a046ad1c0abaaaf1e09fae904b35bf231ffae11d2') {
    throw 'LiveKit checksum mismatch. The archive was not extracted.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $destination -Force
Write-Output 'Installed LiveKit 1.13.10 in work/livekit. Start with --dev --bind 127.0.0.1.'
