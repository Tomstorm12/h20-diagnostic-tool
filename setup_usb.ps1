# H20 Diagnostic Tool - Setup & Build
# Run als administrator in PowerShell

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  H20 Diagnostic Tool - Setup & Build" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Stap 1: Python check
Write-Host "[1/4] Python controleren..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Python niet gevonden. Installeren via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --silent
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}
python --version
Write-Host "Python OK" -ForegroundColor Green

# Stap 2: Repo downloaden
Write-Host ""
Write-Host "[2/4] Repo downloaden van GitHub..." -ForegroundColor Yellow
$zip = "$env:TEMP\h20-tool.zip"
$dir = "$env:TEMP\h20-diagnostic-tool"
Invoke-WebRequest -Uri "https://github.com/Tomstorm12/h20-diagnostic-tool/archive/refs/heads/main.zip" -OutFile $zip
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $env:TEMP
Rename-Item "$env:TEMP\h20-diagnostic-tool-main" $dir
Write-Host "Download OK" -ForegroundColor Green

# Stap 3: Builden
Write-Host ""
Write-Host "[3/4] .exe bouwen..." -ForegroundColor Yellow
Set-Location $dir
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt -q
python -m PyInstaller --onefile --console --name h20_diagnostic --clean --noconfirm --add-data "assets/h20_logo.txt;assets" src\h20_diagnostic.py
Write-Host "Build OK" -ForegroundColor Green

# Stap 4: Klaar
Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Klaar! .exe staat hier:" -ForegroundColor Green
Write-Host "  $dir\dist\h20_diagnostic.exe" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "Kopieer h20_diagnostic.exe naar je USB-stick." -ForegroundColor Cyan
Write-Host ""
Pause
