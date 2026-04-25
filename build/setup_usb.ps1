# H20 Diagnostic Tool - Setup, Build & USB Deploy
# Run als administrator in PowerShell.
# Dit script:
#   1. Installeert Python (indien nodig)
#   2. Downloadt de repo van GitHub
#   3. Bouwt h20_diagnostic.exe
#   4. Vraagt naar je USB-drive en kopieert de .exe + maakt een Reports/ map

# Niet "Stop" gebruiken: we willen elke stap afhandelen en duidelijke fouten tonen
$ErrorActionPreference = "Continue"

function Fail($msg) {
    Write-Host ""
    Write-Host "================================================" -ForegroundColor Red
    Write-Host "  [FOUT] $msg" -ForegroundColor Red
    Write-Host "================================================" -ForegroundColor Red
    Pause
    exit 1
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  H20 Diagnostic Tool - Setup, Build & Deploy" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# --- Stap 1: Python check ----------------------------------------------------
Write-Host "[1/5] Python controleren..." -ForegroundColor Yellow
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "      Python niet gevonden. Installeren via winget..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("Path","User")
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Fail "Python kon niet worden geïnstalleerd. Installeer handmatig via https://www.python.org/downloads/ en draai dit script opnieuw."
    }
}
$pyVersion = python --version 2>&1
Write-Host "      $pyVersion" -ForegroundColor Green

# --- Stap 2: Repo downloaden -------------------------------------------------
Write-Host ""
Write-Host "[2/5] Repo downloaden van GitHub..." -ForegroundColor Yellow
$zip = "$env:TEMP\h20-tool.zip"
$dir = "$env:TEMP\h20-diagnostic-tool"
try {
    Invoke-WebRequest -Uri "https://github.com/Tomstorm12/h20-diagnostic-tool/archive/refs/heads/main.zip" -OutFile $zip -UseBasicParsing
    if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $env:TEMP -Force
    Rename-Item "$env:TEMP\h20-diagnostic-tool-main" $dir
} catch {
    Fail "Repo downloaden mislukt: $_"
}
Write-Host "      Download OK ($dir)" -ForegroundColor Green

# Sanity check: heeft de gedownloade repo de juiste structuur?
$reqFile = Join-Path $dir "build\requirements.txt"
$srcFile = Join-Path $dir "src\h20_diagnostic.py"
if (-not (Test-Path $reqFile)) { Fail "build\requirements.txt ontbreekt in de gedownloade repo." }
if (-not (Test-Path $srcFile)) { Fail "src\h20_diagnostic.py ontbreekt in de gedownloade repo." }

# --- Stap 3: Builden ---------------------------------------------------------
Write-Host ""
Write-Host "[3/5] .exe bouwen..." -ForegroundColor Yellow
Set-Location $dir

Write-Host "      pip upgraden..." -ForegroundColor Gray
python -m pip install --upgrade pip 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "pip upgrade mislukt (exit code $LASTEXITCODE)." }

Write-Host "      Dependencies installeren..." -ForegroundColor Gray
python -m pip install -r build\requirements.txt 2>&1 | Out-Host
if ($LASTEXITCODE -ne 0) { Fail "pip install -r build\requirements.txt mislukt (exit code $LASTEXITCODE)." }

# Extra: pywin32 nodig voor wmi op sommige Python-builds
python -m pip install pywin32 2>&1 | Out-Host

Write-Host "      PyInstaller draaien..." -ForegroundColor Gray
# Argumenten als array zodat PowerShell quoting geen issues geeft
$pyiArgs = @(
    "-m", "PyInstaller",
    "--onefile",
    "--console",
    "--name", "h20_diagnostic",
    "--clean",
    "--noconfirm",
    "--distpath", ".",
    "--workpath", "build\_pyinstaller_work",
    "--specpath", "build\_pyinstaller_work",
    "--add-data", "assets/h20_logo.txt;assets",
    "src\h20_diagnostic.py"
)
& python @pyiArgs 2>&1 | Out-Host
$pyiExit = $LASTEXITCODE

$exePath = Join-Path $dir "h20_diagnostic.exe"
if ($pyiExit -ne 0 -or -not (Test-Path $exePath)) {
    Write-Host ""
    Write-Host "      Build-map inhoud (voor debug):" -ForegroundColor Gray
    Get-ChildItem $dir | Format-Table Name, Length, LastWriteTime -AutoSize | Out-Host
    Fail "PyInstaller-build is gefaald (exit code $pyiExit). Scroll omhoog voor de fout."
}
Write-Host "      Build OK ($exePath)" -ForegroundColor Green

# --- Stap 4: USB-stick selecteren --------------------------------------------
Write-Host ""
Write-Host "[4/5] USB-stick kiezen..." -ForegroundColor Yellow

$removable = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2"
if (-not $removable) {
    Write-Host "      Geen verwijderbare drive gedetecteerd." -ForegroundColor Yellow
    Write-Host "      Stop een USB-stick in en typ de drive-letter, of laat leeg om over te slaan." -ForegroundColor Yellow
} else {
    Write-Host "      Beschikbare verwijderbare drives:" -ForegroundColor White
    foreach ($d in $removable) {
        $label = if ($d.VolumeName) { $d.VolumeName } else { "(geen label)" }
        $sizeGB = [math]::Round($d.Size / 1GB, 1)
        Write-Host "        $($d.DeviceID)  $label  ($sizeGB GB)" -ForegroundColor White
    }
}

$letter = Read-Host "      Welke drive? (alleen de letter, bv. E - leeg = overslaan)"
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
if (-not (Test-Path $usbRoot)) { Fail "Drive $usbRoot bestaat niet." }

# --- Stap 5: Deploy naar USB -------------------------------------------------
Write-Host ""
Write-Host "[5/5] Deployen naar $usbRoot ..." -ForegroundColor Yellow

$usbExe = Join-Path $usbRoot "h20_diagnostic.exe"
$usbReports = Join-Path $usbRoot "Reports"

try {
    Copy-Item -Path $exePath -Destination $usbExe -Force
    Write-Host "      Gekopieerd: h20_diagnostic.exe" -ForegroundColor Green

    if (-not (Test-Path $usbReports)) {
        New-Item -ItemType Directory -Path $usbReports | Out-Null
        Write-Host "      Aangemaakt:  Reports\" -ForegroundColor Green
    } else {
        Write-Host "      Bestond al:  Reports\" -ForegroundColor Green
    }
} catch {
    Fail "Deploy naar USB mislukt: $_"
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
