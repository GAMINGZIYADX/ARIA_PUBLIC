@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: ARIA — Uninstaller
:: Removes ARIA files, virtual environment, and shortcuts.
::
:: Run this if you installed via install.bat.
:: If you installed via the ARIA_Setup.exe, use Windows Settings → Apps instead.
:: =============================================================================

set "ARIA_DIR=%LOCALAPPDATA%\ARIA"
set "START_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\ARIA"

title ARIA Uninstaller
color 0C

echo.
echo  ================================================================
echo    ARIA Uninstaller
echo  ================================================================
echo.
echo  This will remove:
echo    %ARIA_DIR%
echo    Desktop shortcut
echo    Start Menu entry
echo.

set /p CONFIRM=Are you sure you want to uninstall ARIA? [y/N]:
if /i "!CONFIRM!" neq "y" (
    echo  Cancelled.
    pause
    exit /b 0
)

echo.

:: =============================================================================
:: Stop any running ARIA processes
:: =============================================================================
echo Stopping ARIA processes...
:: Kill python.exe processes whose command line references ARIA's app.py.
:: Uses Get-CimInstance (WMIC replacement, works on Windows 11 24H2+).
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { $_.CommandLine -like '*ARIA*app.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
:: Fallback: taskkill by window title set by launch.py (if any)
taskkill /fi "windowtitle eq ARIA*" /f >nul 2>&1
echo    Done.
echo.

:: =============================================================================
:: Remove installation directory
:: =============================================================================
echo Removing %ARIA_DIR% ...
if exist "%ARIA_DIR%" (
    rd /s /q "%ARIA_DIR%"
    if !errorlevel! neq 0 (
        echo.
        echo  ERROR: Could not fully remove %ARIA_DIR%.
        echo  A file may still be in use. Close ARIA and try again.
        echo.
        pause
        exit /b 1
    )
    echo    Removed.
) else (
    echo    Directory not found — already removed.
)
echo.

:: =============================================================================
:: Remove desktop shortcut
:: Uses GetFolderPath to handle OneDrive / redirected Desktop folders.
:: =============================================================================
echo Removing Desktop shortcut...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) 'ARIA.lnk';" ^
    "if (Test-Path $lnk) { Remove-Item $lnk -Force; Write-Host '   Removed.' }" ^
    "else { Write-Host '   Not found.' }"
echo.

:: =============================================================================
:: Remove Start Menu entry
:: =============================================================================
echo Removing Start Menu entry...
if exist "%START_DIR%" (
    rd /s /q "%START_DIR%"
    echo    Removed.
) else (
    echo    Not found.
)
echo.

:: =============================================================================
:: Done
:: =============================================================================
color 0A
echo  ================================================================
echo    ARIA has been uninstalled.
echo.
echo    Your Ollama models were NOT removed.
echo    To remove them:  ollama rm qwen2.5:7b
echo  ================================================================
echo.

endlocal
pause
