@echo off
REM Soft Yeti volunteer bootstrap - double-click to run, no PowerShell knowledge needed.
setlocal
set "INSTALL_DIR=%USERPROFILE%\soft-yeti"
set "ZIP_PATH=%TEMP%\soft-yeti-volunteer.zip"

echo.
echo === Soft Yeti Volunteer Setup ===
echo.
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo Downloading setup bundle to %INSTALL_DIR% ...
REM cache-busting timestamp query param - Cloudflare edge-caches .zip by extension regardless of origin Cache-Control
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); Invoke-WebRequest -Uri \"https://soft-yeti.com/download/volunteer.zip?v=$ts\" -OutFile '%ZIP_PATH%' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    echo Download failed. Check your internet connection and try again.
    pause
    exit /b 1
)

echo Extracting...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Expand-Archive -Path '%ZIP_PATH%' -DestinationPath '%INSTALL_DIR%' -Force } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    echo Extraction failed.
    pause
    exit /b 1
)
del "%ZIP_PATH%" >nul 2>&1

cd /d "%INSTALL_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\setup_volunteer.ps1"

echo.
echo Setup finished. You can close this window.
pause
