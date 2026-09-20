$ErrorActionPreference = "Stop"

Write-Host "[1/4] Python version"
python --version

if (-not (Test-Path ".venv")) {
    Write-Host "[2/4] Creating virtual environment"
    python -m venv .venv
} else {
    Write-Host "[2/4] Reusing existing .venv"
}

$py = Join-Path (Get-Location) ".venv\\Scripts\\python.exe"
Write-Host "[3/4] Updating pip"
& $py -m pip install --upgrade pip setuptools wheel

Write-Host "[4/4] Installing backend dependencies"
& $py -m pip install -r requirements.txt

Write-Host ""
Write-Host "Done. Start API with:"
Write-Host ".\\.venv\\Scripts\\python.exe -m uvicorn app.main:app --reload --port 8000"
