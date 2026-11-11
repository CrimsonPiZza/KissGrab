@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "VENV_PY=%SCRIPT_DIR%.venv\Scripts\python.exe"

if exist "%VENV_PY%" (
    "%VENV_PY%" "%SCRIPT_DIR%main.py" %*
    goto :done
)

where py >nul 2>&1
if %errorlevel%==0 (
    py -3 "%SCRIPT_DIR%main.py" %*
    goto :done
)

where python >nul 2>&1
if %errorlevel%==0 (
    python "%SCRIPT_DIR%main.py" %*
    goto :done
)

echo [error] Python 3.10+ not found. Run setup.bat first.
pause
exit /b 1

:done
if %errorlevel% neq 0 (
    echo.
    pause
)
exit /b %errorlevel%

