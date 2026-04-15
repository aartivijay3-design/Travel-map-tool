@echo off
:: Luxury Travel Map Tool — setup & launch script for Windows
:: Run this once to install deps, then again to start the server.

echo.
echo  ============================================
echo   Luxury Travel Map Generator
echo  ============================================
echo.

:: Check for Python
where python >nul 2>&1
IF ERRORLEVEL 1 (
    echo  ERROR: Python not found.
    echo  Download Python 3.11+ from https://www.python.org/downloads/
    echo  Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)

python --version

:: Create virtual environment if needed
IF NOT EXIST "venv\Scripts\activate.bat" (
    echo.
    echo  Creating virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Install / upgrade dependencies
echo.
echo  Installing dependencies (this may take a minute on first run)...
pip install --upgrade pip --quiet
pip install -r backend\requirements.txt --quiet

IF ERRORLEVEL 1 (
    echo.
    echo  ERROR: Dependency installation failed.
    echo  Try running: pip install -r backend\requirements.txt
    pause
    exit /b 1
)

echo.
echo  Starting server at http://localhost:5000
echo  Press Ctrl+C to stop.
echo.

cd backend
python app.py
