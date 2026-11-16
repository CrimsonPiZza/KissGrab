@echo off
setlocal EnableDelayedExpansion
set "SCRIPT_DIR=%~dp0"
set "AUTO_YES=0"

if /i "%~1"=="-y" set "AUTO_YES=1"
if /i "%~1"=="--yes" set "AUTO_YES=1"
if /i "%~1"=="-h" goto :help
if /i "%~1"=="--help" goto :help
goto :start

:help
echo Usage: setup.bat [-y^|--yes] [-h^|--help]
echo.
echo First-time setup helper for KissGrab ^(Windows^):
echo   1. Checks/installs FFmpeg (via winget/scoop/choco)
echo   2. Checks Python 3.10+ and creates .venv
echo   3. Installs kisskh-downloader and dependencies
echo   4. Optionally installs Playwright + Chromium for auto kkey
exit /b 0

:start
echo ================================================================
echo   KissGrab - Windows First-Time Setup
echo ================================================================
echo.

rem 1. Check FFmpeg
set "FFMPEG_FOUND=0"
where ffmpeg >nul 2>&1 && set "FFMPEG_FOUND=1"
if exist "%LOCALAPPDATA%\Microsoft\WinGet\Links\ffmpeg.exe" set "FFMPEG_FOUND=1"
if exist "%USERPROFILE%\scoop\shims\ffmpeg.exe" set "FFMPEG_FOUND=1"
if exist "%ProgramData%\chocolatey\bin\ffmpeg.exe" set "FFMPEG_FOUND=1"

if "!FFMPEG_FOUND!"=="1" (
    echo [ok] FFmpeg found.
) else (
    echo [!] FFmpeg not found ^(needed for video muxing and subtitle embedding^).
    set "DO_FFMPEG=Y"
    if "!AUTO_YES!"=="0" (
        set /p "DO_FFMPEG=Install FFmpeg via winget/scoop/choco now? [Y/n]: "
    )
    if /i "!DO_FFMPEG!"=="" set "DO_FFMPEG=Y"
    if /i "!DO_FFMPEG!"=="Y" (
        where winget >nul 2>&1
        if !errorlevel!==0 (
            echo [*] Installing Gyan.FFmpeg via winget...
            winget install -e --id Gyan.FFmpeg --accept-package-agreements --accept-source-agreements
        ) else (
            where scoop >nul 2>&1
            if !errorlevel!==0 (
                echo [*] Installing ffmpeg via scoop...
                scoop install ffmpeg
            ) else (
                where choco >nul 2>&1
                if !errorlevel!==0 (
                    echo [*] Installing ffmpeg via choco...
                    choco install ffmpeg -y
                ) else (
                    echo [warn] Neither winget, scoop, nor choco was found.
                    echo        Install FFmpeg manually from https://www.gyan.dev/ffmpeg/builds/
                )
            )
        )
    ) else (
        echo [skip] Skipped FFmpeg install.
    )
)

rem 2. Check Python 3
echo.
set "PY_CMD="
where py >nul 2>&1
if %errorlevel%==0 (
    py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
    if !errorlevel!==0 set "PY_CMD=py -3"
)
if not defined PY_CMD (
    where python >nul 2>&1
    if !errorlevel!==0 (
        python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
        if !errorlevel!==0 set "PY_CMD=python"
    )
)

if not defined PY_CMD (
    echo [error] Python 3.10+ is required.
    where winget >nul 2>&1
    if !errorlevel!==0 (
        echo         You can install it with: winget install -e --id Python.Python.3.12
    ) else (
        echo         Download Python from https://www.python.org/downloads/
    )
    pause
    exit /b 1
)
echo [ok] Python found ^(!PY_CMD!^).

rem 3. Virtual environment & dependencies
set "VENV_DIR=%SCRIPT_DIR%.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [*] Creating virtual environment in .venv...
    %PY_CMD% -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo [error] Failed to create .venv.
        pause
        exit /b 1
    )
)

echo [*] Installing/updating Python dependencies...
"%VENV_PY%" -m pip install --upgrade pip >nul
"%VENV_PY%" -m pip install -r "%SCRIPT_DIR%requirements.txt"
if !errorlevel! neq 0 (
    echo [error] Failed to install dependencies from requirements.txt.
    pause
    exit /b 1
)
echo [ok] kisskh-downloader installed in .venv.

rem 4. Playwright + Chromium
echo.
"%VENV_PY%" -c "import playwright" >nul 2>&1
if !errorlevel!==0 (
    echo [ok] Playwright Python package is installed.
) else (
    echo [!] Playwright is needed to auto-generate KissKH 'kkey' tokens.
    set "DO_PW=Y"
    if "!AUTO_YES!"=="0" (
        set /p "DO_PW=Install Playwright + Chromium now? [Y/n]: "
    )
    if /i "!DO_PW!"=="" set "DO_PW=Y"
    if /i "!DO_PW!"=="Y" (
        "%VENV_PY%" -m pip install playwright
        "%VENV_PY%" -m playwright install chromium
        echo [ok] Playwright + Chromium installed.
    ) else (
        echo [skip] You can install it later inside the app under [4] Setup ^& Tools.
    )
)

rem 5. System PATH Setup (run 'kissgrab' from anywhere)
echo.
echo ================================================================
echo   System PATH Setup (Run 'kissgrab' from anywhere)
echo ================================================================
set "DO_LINK=Y"
if "!AUTO_YES!"=="0" (
    set /p "DO_LINK=Make 'kissgrab' runnable from any command prompt / PowerShell? [Y/n]: "
)
if /i "!DO_LINK!"=="" set "DO_LINK=Y"
if /i "!DO_LINK!"=="Y" (
    set "WIN_APPS=%USERPROFILE%\AppData\Local\Microsoft\WindowsApps"
    if exist "!WIN_APPS!" (
        (
            echo @echo off
            echo call "%SCRIPT_DIR%run.bat" %%*
        ) > "!WIN_APPS!\kissgrab.cmd"
        echo [ok] Installed 'kissgrab' command to !WIN_APPS!\kissgrab.cmd
    ) else (
        echo [!] WindowsApps directory not found. You can run KissGrab with run.bat.
    )
)

rem 6. Optional: Pipx Setup via winget
where pipx >nul 2>&1
if !errorlevel! neq 0 (
    where winget >nul 2>&1
    if !errorlevel!==0 (
        echo.
        set "DO_PIPX=N"
        if "!AUTO_YES!"=="0" (
            set /p "DO_PIPX=Install 'pipx' via winget (for managing Python CLI packages)? [y/N]: "
        )
        if /i "!DO_PIPX!"=="Y" (
            winget install pipx
            echo [ok] pipx install requested via winget.
        )
    )
)

echo.
echo ================================================================
echo   Setup Complete!
echo   Start KissGrab anytime with:     kissgrab  (or run.bat)
echo ================================================================
if "%AUTO_YES%"=="0" pause
exit /b 0

