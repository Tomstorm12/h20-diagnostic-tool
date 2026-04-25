@echo off
REM ============================================================
REM  H20 Diagnostic Tool - Build Script
REM  Draait vanuit build\ map. Bouwt src\h20_diagnostic.py om
REM  tot een standalone .exe in de project-root.
REM ============================================================

setlocal

REM Ga naar de projectroot (een map omhoog vanaf dit script)
pushd "%~dp0\.."

echo.
echo ============================================================
echo   H20 Diagnostic Tool - Build
echo ============================================================
echo.

REM Stap 1: Dependencies installeren
echo [1/4] Installeren van dependencies...
python -m pip install --upgrade pip
python -m pip install -r build\requirements.txt
if errorlevel 1 (
    echo.
    echo [FOUT] pip install is mislukt. Controleer je Python-installatie.
    popd
    pause
    exit /b 1
)

REM Stap 2: PyInstaller aanroepen
REM --onefile: alles in een enkele .exe
REM --console: klein terminal-venster voor tqdm-progressie tijdens scan
REM --name:    naam van het uitvoerbestand
REM --clean:   oude build-bestanden opruimen
echo.
echo [2/4] Bouwen van h20_diagnostic.exe met PyInstaller...
python -m PyInstaller ^
    --onefile ^
    --console ^
    --name h20_diagnostic ^
    --clean ^
    --noconfirm ^
    --distpath . ^
    --workpath build\_pyinstaller_work ^
    --specpath build\_pyinstaller_work ^
    --add-data "assets/h20_logo.txt;assets" ^
    src\h20_diagnostic.py

if errorlevel 1 (
    echo.
    echo [FOUT] PyInstaller build is mislukt.
    popd
    pause
    exit /b 1
)

REM Stap 3: Tijdelijke build-bestanden opruimen
echo.
echo [3/4] Opruimen van tijdelijke bestanden...
if exist build\_pyinstaller_work rmdir /s /q build\_pyinstaller_work

REM Stap 4: Melding tonen
echo.
echo [4/4] Klaar.
echo.
echo ============================================================
echo   Build geslaagd.
echo   h20_diagnostic.exe staat in de projectroot.
echo   Kopieer dat bestand naar je USB-stick.
echo ============================================================
echo.

popd
endlocal
pause
