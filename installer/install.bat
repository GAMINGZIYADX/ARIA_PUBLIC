@echo off
setlocal EnableDelayedExpansion

:: =============================================================================
:: ARIA — Windows Fallback Installer
:: Run this if you cannot execute the .exe installer (e.g. corporate policy).
::
:: Usage:
::   1. Clone / extract the ARIA repo so you have a local copy.
::   2. Open this file's location in File Explorer.
::   3. Right-click install.bat → "Run as administrator" is NOT required.
::   4. Follow the prompts.
::
:: Prerequisites (install these before running):
::   Python 3.10+  https://www.python.org/downloads/
::   Ollama        https://ollama.com/download
:: =============================================================================

:: ── Paths ─────────────────────────────────────────────────────────────────────
:: SRC = the repo root (one level above installer\)
set "SRC=%~dp0.."
set "ARIA_DIR=%LOCALAPPDATA%\ARIA"
set "VENV=%ARIA_DIR%\.venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"
set "OLLAMA_MODEL=qwen2.5:7b"

title ARIA Installer
color 0B

echo.
echo  ================================================================
echo    ARIA — Autonomous Reasoning ^& Intelligent Assistant
echo    Windows Installer
echo  ================================================================
echo.

:: =============================================================================
:: STEP 0 — Check Python 3.10+
:: =============================================================================
echo [1/7] Checking Python version...

:: Try the Windows py launcher first
py -3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYCMD=py -3"
    goto :python_ok
)

:: Fall back to plain 'python'
python -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if %errorlevel% equ 0 (
    set "PYCMD=python"
    goto :python_ok
)

echo.
echo  ERROR: Python 3.10 or newer not found.
echo.
echo  Please install Python 3.11 or 3.12 (64-bit) from:
echo    https://www.python.org/downloads/
echo.
echo  IMPORTANT: Check "Add Python to PATH" during installation.
echo.
echo  After installing Python, re-run this script.
echo.
start https://www.python.org/downloads/
pause
exit /b 1

:python_ok
for /f "tokens=*" %%v in ('!PYCMD! --version 2^>^&1') do echo    Found: %%v
echo.

:: =============================================================================
:: STEP 1 — Check Ollama
:: =============================================================================
echo [2/7] Checking Ollama...
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: Ollama is not installed or not on PATH.
    echo.
    echo  Please install Ollama from:
    echo    https://ollama.com/download
    echo.
    echo  After installing Ollama, re-run this script.
    echo.
    start https://ollama.com/download
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('ollama --version 2^>^&1') do echo    Found: %%v
echo.

:: =============================================================================
:: STEP 2 — Copy ARIA files
:: =============================================================================
echo [3/7] Copying ARIA files to %ARIA_DIR% ...

if not exist "%ARIA_DIR%" mkdir "%ARIA_DIR%"

:: robocopy exit code 0 = nothing to copy, 1 = success, 2-7 = various OK states
:: 8+ = error. We treat 0-7 as success.
robocopy "%SRC%" "%ARIA_DIR%" /E ^
    /XD .git __pycache__ installer .venv dist ^
    /XF *.pyc *.pyo .gitignore ^
    /NP /NFL /NDL /NJH /NJS

if %errorlevel% geq 8 (
    echo.
    echo  ERROR: Failed to copy files (robocopy exit code %errorlevel%).
    echo  Make sure you are running from the ARIA repo directory.
    echo.
    pause
    exit /b 1
)
echo    Done.
echo.

:: =============================================================================
:: STEP 3 — Create virtual environment
:: =============================================================================
echo [4/7] Creating Python virtual environment...
!PYCMD! -m venv "%VENV%"
if %errorlevel% neq 0 (
    echo  ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

echo    Upgrading pip...
"%PYTHON%" -m pip install --upgrade pip --quiet
echo    Done.
echo.

:: =============================================================================
:: STEP 4 — Install dependencies
:: =============================================================================
echo [5/7] Installing Python packages...
echo    This may take several minutes depending on your connection speed.
echo.
"%PIP%" install -r "%ARIA_DIR%\requirements.txt"
if %errorlevel% neq 0 (
    echo.
    echo  ERROR: pip install failed. Check the output above for details.
    pause
    exit /b 1
)
echo.
echo    Packages installed successfully.
echo.

:: =============================================================================
:: STEP 5 — Pull Ollama model
:: =============================================================================
echo [6/7] Pulling Ollama model: %OLLAMA_MODEL%
echo    This may take several minutes (model is ~4.7 GB).
echo.
ollama pull %OLLAMA_MODEL%
if %errorlevel% neq 0 (
    echo.
    echo  WARNING: ollama pull returned an error.
    echo  Make sure Ollama is running (ollama serve) and try again:
    echo    ollama pull %OLLAMA_MODEL%
    echo.
    echo  You can continue and pull the model later.
    pause
)
echo.

:: =============================================================================
:: STEP 6 — Run configuration wizard
:: =============================================================================
echo [7/7] Running ARIA configuration wizard...
echo    Answer the prompts to configure your .env and persona.
echo.
"%PYTHON%" "%ARIA_DIR%\setup.py"
if %errorlevel% neq 0 (
    echo.
    echo  WARNING: setup.py exited with an error.
    echo  You can re-run it later: python setup.py  (inside %ARIA_DIR%)
    echo.
)

:: =============================================================================
:: STEP 7 — Create shortcuts
:: =============================================================================
echo Creating shortcuts...

:: Desktop shortcut via PowerShell
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $sc = $ws.CreateShortcut([System.IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'ARIA.lnk')); ^
     $sc.TargetPath  = '%VENV%\Scripts\python.exe'; ^
     $sc.Arguments   = '\"%ARIA_DIR%\app.py\"'; ^
     $sc.WorkingDirectory = '%ARIA_DIR%'; ^
     $sc.Description = 'Launch ARIA voice assistant'; ^
     $sc.Save()" >nul 2>&1
if %errorlevel% equ 0 (echo    Desktop shortcut created.) else (echo    WARNING: Could not create desktop shortcut.)

:: Start Menu shortcut
set "START_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\ARIA"
if not exist "%START_DIR%" mkdir "%START_DIR%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ws = New-Object -ComObject WScript.Shell; ^
     $sc = $ws.CreateShortcut('%START_DIR%\ARIA.lnk'); ^
     $sc.TargetPath  = '%VENV%\Scripts\python.exe'; ^
     $sc.Arguments   = '\"%ARIA_DIR%\app.py\"'; ^
     $sc.WorkingDirectory = '%ARIA_DIR%'; ^
     $sc.Description = 'Launch ARIA voice assistant'; ^
     $sc.Save()" >nul 2>&1
if %errorlevel% equ 0 (echo    Start Menu shortcut created.) else (echo    WARNING: Could not create Start Menu shortcut.)

echo.

:: =============================================================================
:: Done
:: =============================================================================
color 0A
echo  ================================================================
echo    Installation complete!
echo.
echo    ARIA is installed at:
echo      %ARIA_DIR%
echo.
echo    To launch ARIA:
echo      • Double-click the "ARIA" shortcut on your Desktop
echo      • Or run:  "%PYTHON%" "%ARIA_DIR%\app.py"
echo      • Then open http://localhost:5000 in your browser
echo.
echo    To uninstall:
echo      Run installer\uninstall.bat  (or delete %ARIA_DIR%)
echo  ================================================================
echo.

set /p LAUNCH=Launch ARIA now? [Y/n]:
if /i "!LAUNCH!" neq "n" (
    start "" "%PYTHON%" "%ARIA_DIR%\app.py"
    timeout /t 2 /nobreak >nul
    start http://localhost:5000
)

endlocal
pause
