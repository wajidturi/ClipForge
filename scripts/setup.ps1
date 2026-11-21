# One-time developer setup (Windows PowerShell). Safe to re-run.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

function Require($name, $hint) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    Write-Host "Missing: $name. $hint" -ForegroundColor Red
    exit 1
  }
}
Require uv     'Install: winget install astral-sh.uv'
Require node   'Install Node.js 22+ : winget install OpenJS.NodeJS.LTS'
Require ffmpeg 'Install: winget install Gyan.FFmpeg (then open a new terminal)'

git -C $root config core.longpaths true

Write-Host '> Backend: Python 3.12 + dependencies' -ForegroundColor Cyan
Push-Location "$root\backend"
uv python install 3.12
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
  Write-Host '  NVIDIA GPU found: adding CUDA libraries for fast transcription (~2 GB)'
  uv sync --python 3.12 --extra gpu
} else {
  uv sync --python 3.12
}
uv run pre-commit install
uv run clipforge doctor
Pop-Location

Write-Host '> Frontend: npm packages' -ForegroundColor Cyan
Push-Location "$root\frontend"
npm ci
Pop-Location

if (-not (Test-Path "$root\.env")) { Copy-Item "$root\.env.example" "$root\.env" }
Write-Host 'Setup complete. Start everything with: .\scripts\dev.ps1' -ForegroundColor Green
