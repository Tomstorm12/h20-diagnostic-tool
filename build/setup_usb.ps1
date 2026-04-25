# H20 Diagnostic Tool - Setup, Build & USB Deploy
# Run als administrator in PowerShell.
# Dit script:
#   1. Installeert Python (indien nodig)
#   2. Downloadt de repo van GitHub
#   3. Bouwt h20_diagnostic.exe
#   4. Vraagt naar je USB-drive en kopieert de .exe + maakt een Reports/ map

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  H20 Diagnostic Tool - Setup, Build & Deploy" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# --- Stap 1: Python check ----------------------------------------------------
Write-Host "[1/5] Python controleren..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "      Python niet gevonden. Installeren via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --silent
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
}
python --version
Write-Host "      Python OK" -ForegroundColor Green

# --- Stap 2: Repo downloaden -------------------------------------------------
Write-Host ""
Write-Host "[2/5] Repo downloaden van GitHub..." -ForegroundColor Yellow
$zip = "$env:TEMP\h20-tool.zip"
$dir = "$env:TEMP\h20-diagnostic-tool"
Invoke-WebRequest -Uri "https://github.com/Tomstorm12/h20-diagnostic-tool/archive/refs/heads/main.zip" -OutFile $zip
if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
Expand-Archive -Path $zip -DestinationPath $env:TEMP -Force
Rename-Item "$env:TEMP\h20-diagnostic-tool-main" $dir
Write-Host "      Download OK ($dir)" -ForegroundColor Green

# --- Stap 3: Builden ---------------------------------------------------------
Write-Host ""
Write-Host "[3/5] .exe bouwen..." -ForegroundColor Yellow
Set-Location $dir
python -m pip install --upgrade pip -q
python -m pip install -r build\requirements.txt -q
python -m PyInstaller `
    --onefile `
    --console `
    --name h20_diagnostic `
    --clean `
    --noconfirm `
    --distpath . `
    --workpath build\_pyinstaller_work `
    --specpath build\_pyinstaller_work `
    --add-data "assets/h20_logo.txt;assets" `
    src\h20_diagnostic.py

$exePath = Join-Path $dir "h20_diagnostic.exe"
if (-not (Test-Path $exePath)) {
    Write-Host ""
    Write-Host "[FOUT] Build mislukt - h20_diagnostic.exe niet gevonden." -ForegroundColor Red
    Write-Host "       Bekijk de PyInstaller-output hierboven voor de oorzaak." -ForegroundColor Red
    Pause
    exit 1
}
Write-Host "      Build OK ($exePath)" -ForegroundColor Green

# --- Stap 4: USB-stick selecteren --------------------------------------------
Write-Host ""
Write-Host "[4/5] USB-stick kiezen..." -ForegroundColor Yellow

# Toon alle removable drives
$removable = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2"
if (-not $removable) {
    Write-Host "      Geen USB-stick gedetecteerd." -ForegroundColor Yellow
    Write-Host "      Voer hieronder handmatig de drive-letter in (bv. E)," -ForegroundColor Yellow
    Write-Host "      of laat leeg om over te slaan." -ForegroundColor Yellow
} else {
    Write-Host "      Beschikbare verwijderbare drives:" -ForegroundColor White
    foreach ($d in $removable) {
        $label = if ($d.VolumeName) { $d.VolumeName } else { "(geen label)" }
        $sizeGB = [math]::Round($d.Size / 1GB, 1)
        Write-Host "        $($d.DeviceID)  $label  ($sizeGB GB)" -ForegroundColor White
    }
}

$letter = Read-Host "      Welke drive wil je gebruiken? (alleen de letter, bv. E)"
if ([string]::IsNullOrWhiteSpace($letter)) {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Yellow
    Write-Host "  USB-deploy overgeslagen." -ForegroundColor Yellow
    Write-Host "  De .exe staat hier: $exePath" -ForegroundColor White
    Write-Host "  Kopieer hem zelf naar je USB-stick + maak een" -ForegroundColor White
    Write-Host "  map 'Reports' in de root." -ForegroundColor White
    Write-Host "================================================" -ForegroundColor Yellow
    Write-Host ""
    Pause
    exit 0
}

$letter = $letter.Trim().TrimEnd(':').ToUpper()
$usbRoot = "${letter}:\"
if (-not (Test-Path $usbRoot)) {
    Write-Host "[FOUT] Drive $usbRoot bestaat niet." -ForegroundColor Red
    Pause
    exit 1
}

# --- Stap 5: Deploy naar USB -------------------------------------------------
Write-Host ""
Write-Host "[5/5] Deployen naar $usbRoot ..." -ForegroundColor Yellow

$usbExe = Join-Path $usbRoot "h20_diagnostic.exe"
$usbReports = Join-Path $usbRoot "Reports"

Copy-Item -Path $exePath -Destination $usbExe -Force
Write-Host "      Gekopieerd: h20_diagnostic.exe" -ForegroundColor Green

if (-not (Test-Path $usbReports)) {
    New-Item -ItemType Directory -Path $usbReports | Out-Null
    Write-Host "      Aangemaakt:  Reports\" -ForegroundColor Green
} else {
    Write-Host "      Bestond al:  Reports\" -ForegroundColor Green
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  Klaar! Inhoud van je USB-stick:" -ForegroundColor Green
Write-Host "    ${letter}:\h20_diagnostic.exe" -ForegroundColor White
Write-Host "    ${letter}:\Reports\" -ForegroundColor White
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Stop de USB in een doel-PC en dubbelklik de .exe." -ForegroundColor Cyan
Write-Host "  Het rapport komt automatisch in Reports\<PCNAAM>.html" -ForegroundColor Cyan
Write-Host ""
Pause
