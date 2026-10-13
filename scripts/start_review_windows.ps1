# Run in VS Code PowerShell from any working directory.
$ErrorActionPreference = "Stop"
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $repo
$python = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  python -m venv .venv
  if ($LASTEXITCODE -ne 0) { throw "Python 3 is required" }
}
& $python -m pip install "flask>=3,<4"
if ($LASTEXITCODE -ne 0) { throw "Flask installation failed" }
& $python -m review.preview
