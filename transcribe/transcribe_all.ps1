<#
Transcribe all .wav files in a directory using the project's venv and transcribe.py.

Usage:
  .\transcribe_all.ps1 -Dir "." -Model medium
  .\transcribe_all.ps1 -Dir "C:\path\to\wavs" -Model medium -Recursive

Defaults:
  Dir: current directory
  Model: medium
  Venv python: .faster-whisper-venv\Scripts\python.exe (auto-detected next to this script)
#>

param(
    [string]$Dir = ".",
    [string]$Model = "medium",
    [string]$VenvPython = "",
    [switch]$Recursive
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $VenvPython) {
    $VenvPython = Join-Path $scriptDir '.faster-whisper-venv\Scripts\python.exe'
}

$transcribeScript = Join-Path $scriptDir 'transcribe.py'

$absDir = Resolve-Path -Path $Dir

$outRoot = Join-Path $absDir $Model
if (-not (Test-Path $outRoot)) {
    New-Item -ItemType Directory -Path $outRoot | Out-Null
}

if ($Recursive) {
    $wavFiles = Get-ChildItem -Path $absDir -Recurse -File -Filter *.wav
} else {
    $wavFiles = Get-ChildItem -Path $absDir -File -Filter *.wav
}

if (-not $wavFiles) {
    Write-Host "No .wav files found in $absDir"
    exit 0
}

foreach ($file in $wavFiles) {
    $inPath = $file.FullName
    $base = [System.IO.Path]::GetFileNameWithoutExtension($file.Name)
    $outPath = Join-Path $outRoot ($base + '.txt')

    Write-Host "Transcribing:`n  Input: $inPath`n  Output: $outPath"

    & $VenvPython $transcribeScript $inPath $Model --output $outPath

    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Transcription failed for $inPath (exit code $LASTEXITCODE)"
    }
}

Write-Host "Done. Outputs saved to: $outRoot"
