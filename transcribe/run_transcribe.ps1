#!/usr/bin/env pwsh
# Runs transcribe.py with the local faster-whisper venv, forwarding every argument.

$ErrorActionPreference = 'Stop'

$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$transcribe = Join-Path $PSScriptRoot 'transcribe.py'

if (-not (Test-Path $venvPython)) {
    Write-Error "Python executable not found: $venvPython"
}
if (-not (Test-Path $transcribe)) {
    Write-Error "transcribe.py not found: $transcribe"
}

& $venvPython $transcribe @args
exit $LASTEXITCODE
