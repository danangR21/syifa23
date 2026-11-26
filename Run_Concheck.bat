@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title RAN Concheck Analyzer V3.7.5 BOTH Foundation

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creating Python virtual environment...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo ERROR: Python 3 was not found. Install Python 3.10+ and enable Add Python to PATH.
        pause
        exit /b 1
    )
)

echo [2/3] Installing / checking dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo [3/3] Starting RAN Concheck Analyzer V3.7.5 BOTH Foundation...
".venv\Scripts\python.exe" -m streamlit run app.py --server.headless false
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo ERROR: Setup or application launch failed. Review the messages above.
pause
exit /b 1
