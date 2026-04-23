@echo off
REM ============================================================
REM  H20 Diagnostic Tool - Build Script
REM  Bouwt h20_diagnostic.py om tot een standalone .exe
REM ============================================================

setlocal

echo.
echo ============================================================
echo   H20 Diagnostic Tool - Build
echo ============================================================
echo.

REM Stap 1: Dependencies installeren
echo [1/3] Installeren van dependencies...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [FOUT] pip install is mislukt. Controleer je Python-installatie.
    pause
    exit /b 1
)

REM Stap 2: PyInstaller aanroepen
REM --onefile: alles in een enkele .exe
REM --console: klein terminal-venster tonen voor tqdm-progressie tijdens scan
REM --name:    naam van het uitvoerbestand
REM --clean:   oude build-bestanden opruimen
echo.
echo [2/3] Bouwen van h20_diagnostic.exe met PyInstaller...
python -m PyInstaller ^
    --onefile ^
    --console ^
    --name h20_diagnostic ^
    --clean ^
    --noconfirm ^
    --add-data "assets/h20_logo.txt;assets" ^
    src\h20_diagnostic.py

if errorlevel 1 (
    echo.
    echo [FOUT] PyInstaller build is mislukt.
    pause
    exit /b 1
)

REM Stap 3: Melding tonen
echo.
echo [3/3] Opruimen van tijdelijke bestanden...
if exist build rmdir /s /q build
if exist h20_diagnostic.spec del /q h20_diagnostic.spec

echo.
echo ============================================================
echo   Build geslaagd. Kopieer dist\h20_diagnostic.exe naar je
echo   USB-stick.
echo ============================================================
echo.

endlocal
pause
