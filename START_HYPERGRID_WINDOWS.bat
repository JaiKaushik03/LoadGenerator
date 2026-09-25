@echo off
setlocal
cd /d "%~dp0"
title HyperGrid Battery Digital Twin

echo ============================================================
echo   HyperGrid Battery Digital Twin v0.2 - PORTABLE
echo   No pip install. No MATLAB. No external Python packages.
echo ============================================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
    py -3 app.py
    goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
    python app.py
    goto :end
)

echo ERROR: Python was not found.
echo Install Python 3.10 or newer from https://www.python.org/downloads/
echo Make sure "Add Python to PATH" is checked.
pause
:end
if not %errorlevel%==0 pause
