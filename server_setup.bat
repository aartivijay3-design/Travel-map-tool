@echo off
:: ============================================================
::  Travel Map Tool  –  Server Setup Script
::  Run ONCE on the server as Administrator.
::  After this runs, the app starts automatically on every boot.
:: ============================================================
setlocal EnableDelayedExpansion

echo.
echo  ============================================================
echo   Travel Map Tool  --  Server Setup
echo  ============================================================
echo.

:: ── Where is this script? Use that as the project root ───────
set "PROJECT=%~dp0"
set "BACKEND=%PROJECT%backend"
set "PYTHON_INSTALL=%SystemDrive%\Python311"
set "PYTHON=%PYTHON_INSTALL%\python.exe"
set "VENV=%PROJECT%venv"
set "NSSM=%PROJECT%nssm.exe"

:: ── Step 1: Download & install Python 3.11 silently ─────────
if exist "%PYTHON%" (
    echo  Python already installed at %PYTHON%
) else (
    echo  Downloading Python 3.11.9 ...
    curl -L -o "%TEMP%\python_installer.exe" ^
        "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    if ERRORLEVEL 1 (
        echo  ERROR: Could not download Python. Check internet access.
        pause & exit /b 1
    )
    echo  Installing Python (this takes ~1 minute) ...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=1 ^
        PrependPath=1 TargetDir="%PYTHON_INSTALL%"
    if ERRORLEVEL 1 (
        echo  ERROR: Python installation failed.
        pause & exit /b 1
    )
    echo  Python installed.
)

:: ── Step 2: Create virtual environment ───────────────────────
if not exist "%VENV%\Scripts\activate.bat" (
    echo  Creating virtual environment ...
    "%PYTHON%" -m venv "%VENV%"
)

:: ── Step 3: Install dependencies ─────────────────────────────
echo  Installing dependencies (first run takes a few minutes) ...
call "%VENV%\Scripts\activate.bat"
pip install --upgrade pip --quiet
pip install -r "%BACKEND%\requirements.txt" --quiet
if ERRORLEVEL 1 (
    echo  ERROR: Dependency installation failed.
    echo  Try running manually: pip install -r backend\requirements.txt
    pause & exit /b 1
)
echo  Dependencies installed.

:: ── Step 4: Download NSSM (service manager) ──────────────────
if not exist "%NSSM%" (
    echo  Downloading NSSM service manager ...
    curl -L -o "%TEMP%\nssm.zip" ^
        "https://nssm.cc/release/nssm-2.24.zip"
    if ERRORLEVEL 1 (
        echo  ERROR: Could not download NSSM.
        pause & exit /b 1
    )
    powershell -Command ^
        "Expand-Archive '%TEMP%\nssm.zip' '%TEMP%\nssm_extract' -Force; ^
         Copy-Item '%TEMP%\nssm_extract\nssm-2.24\win64\nssm.exe' '%NSSM%'"
    echo  NSSM ready.
)

:: ── Step 5: Remove old service if present ────────────────────
sc query TravelMapTool >nul 2>&1
if NOT ERRORLEVEL 1 (
    echo  Removing old service ...
    "%NSSM%" stop TravelMapTool
    "%NSSM%" remove TravelMapTool confirm
)

:: ── Step 6: Register as Windows Service ──────────────────────
echo  Registering Windows Service ...
"%NSSM%" install TravelMapTool "%VENV%\Scripts\python.exe"
"%NSSM%" set TravelMapTool AppParameters "%BACKEND%\serve.py"
"%NSSM%" set TravelMapTool AppDirectory "%BACKEND%"
"%NSSM%" set TravelMapTool DisplayName "Travel Map Tool"
"%NSSM%" set TravelMapTool Description "Luxury Travel Map Generator"
"%NSSM%" set TravelMapTool Start SERVICE_AUTO_START
"%NSSM%" set TravelMapTool AppStdout "%PROJECT%logs\app.log"
"%NSSM%" set TravelMapTool AppStderr "%PROJECT%logs\app.log"
"%NSSM%" set TravelMapTool AppRotateFiles 1
"%NSSM%" set TravelMapTool AppRotateBytes 5242880

:: Create logs folder
if not exist "%PROJECT%logs" mkdir "%PROJECT%logs"

:: ── Step 7: Start the service ─────────────────────────────────
echo  Starting service ...
"%NSSM%" start TravelMapTool
timeout /t 3 /nobreak >nul

:: Verify
sc query TravelMapTool | find "RUNNING" >nul
if ERRORLEVEL 1 (
    echo.
    echo  WARNING: Service may not have started. Check logs at:
    echo  %PROJECT%logs\app.log
) else (
    echo  Service is RUNNING on http://127.0.0.1:5000
)

echo.
echo  ============================================================
echo   DONE. App is running as a Windows Service.
echo.
echo   Next step: configure IIS reverse proxy.
echo   See DEPLOYMENT_GUIDE.txt for instructions.
echo  ============================================================
echo.
pause
