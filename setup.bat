@echo off
REM Soft Yeti volunteer bootstrap — double-click to run, no PowerShell knowledge needed.
setlocal
set "INSTALL_DIR=%USERPROFILE%\soft-yeti"

echo.
echo === Soft Yeti Volunteer Setup ===
echo.
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

echo Downloading setup script to %INSTALL_DIR% ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { Invoke-WebRequest -Uri 'https://soft-yeti.com/download/setup.ps1' -OutFile '%INSTALL_DIR%\setup_volunteer.ps1' -UseBasicParsing } catch { Write-Host $_.Exception.Message -ForegroundColor Red; exit 1 }"
if errorlevel 1 (
    echo.
    echo Download failed. Check your internet connection and try again.
    pause
    exit /b 1
)

cd /d "%INSTALL_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%INSTALL_DIR%\setup_volunteer.ps1"

echo.
echo Setup finished. You can close this window.
pause
