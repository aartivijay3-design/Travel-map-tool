@echo off
:: ============================================================
::  Travel Map Tool  –  Server Setup  (No IT required)
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
set "PORT=5000"

:: ── Step 1: Download & install Python 3.11 silently ─────────
if exist "%PYTHON%" (
    echo  [OK] Python already installed.
) else (
    echo  [1/5] Downloading Python 3.11.9 ...
    curl -L -o "%TEMP%\python_installer.exe" ^
        "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    if ERRORLEVEL 1 (
        echo  ERROR: Could not download Python. Check internet access on this server.
        pause & exit /b 1
    )
    echo  Installing Python (this takes ~1 minute) ...
    "%TEMP%\python_installer.exe" /quiet InstallAllUsers=1 ^
        PrependPath=1 TargetDir="%PYTHON_INSTALL%"
    if ERRORLEVEL 1 (
        echo  ERROR: Python installation failed.
        pause & exit /b 1
    )
    echo  [OK] Python installed.
)

:: ── Step 2: Create virtual environment ───────────────────────
if not exist "%VENV%\Scripts\activate.bat" (
    echo  [2/5] Creating virtual environment ...
    "%PYTHON%" -m venv "%VENV%"
) else (
    echo  [OK] Virtual environment exists.
)

:: ── Step 3: Install dependencies ─────────────────────────────
echo  [3/5] Installing dependencies (first run takes a few minutes) ...
call "%VENV%\Scripts\activate.bat"
pip install --upgrade pip --quiet
pip install -r "%BACKEND%\requirements.txt" --quiet
if ERRORLEVEL 1 (
    echo  ERROR: Dependency installation failed.
    pause & exit /b 1
)
echo  [OK] Dependencies installed.

:: ── Step 4: Download NSSM ────────────────────────────────────
if not exist "%NSSM%" (
    echo  [4/5] Downloading NSSM (Windows service manager) ...
    curl -L -o "%TEMP%\nssm.zip" "https://nssm.cc/release/nssm-2.24.zip"
    if ERRORLEVEL 1 (
        echo  ERROR: Could not download NSSM.
        pause & exit /b 1
    )
    powershell -Command ^
        "Expand-Archive '%TEMP%\nssm.zip' '%TEMP%\nssm_extract' -Force; ^
         Copy-Item '%TEMP%\nssm_extract\nssm-2.24\win64\nssm.exe' '%NSSM%'"
    echo  [OK] NSSM ready.
) else (
    echo  [OK] NSSM already present.
)

:: ── Step 5: Open firewall port ───────────────────────────────
echo  [5/5] Opening firewall port %PORT% ...
netsh advfirewall firewall delete rule name="TravelMapTool" >nul 2>&1
netsh advfirewall firewall add rule ^
    name="TravelMapTool" ^
    dir=in ^
    action=allow ^
    protocol=TCP ^
    localport=%PORT% ^
    description="Travel Map Tool web interface"
echo  [OK] Firewall port %PORT% open.

:: ── Step 6: Register / update Windows Service ────────────────
echo  Registering Windows Service ...
if not exist "%PROJECT%logs" mkdir "%PROJECT%logs"

sc query TravelMapTool >nul 2>&1
if NOT ERRORLEVEL 1 (
    "%NSSM%" stop TravelMapTool >nul 2>&1
    "%NSSM%" remove TravelMapTool confirm >nul 2>&1
)

"%NSSM%" install    TravelMapTool "%VENV%\Scripts\python.exe"
"%NSSM%" set        TravelMapTool AppParameters  "%BACKEND%\serve.py"
"%NSSM%" set        TravelMapTool AppDirectory   "%BACKEND%"
"%NSSM%" set        TravelMapTool DisplayName    "Travel Map Tool"
"%NSSM%" set        TravelMapTool Description    "Luxury Travel Map Generator – internal web tool"
"%NSSM%" set        TravelMapTool Start          SERVICE_AUTO_START
"%NSSM%" set        TravelMapTool AppStdout      "%PROJECT%logs\app.log"
"%NSSM%" set        TravelMapTool AppStderr      "%PROJECT%logs\app.log"
"%NSSM%" set        TravelMapTool AppRotateFiles 1
"%NSSM%" set        TravelMapTool AppRotateBytes 5242880

:: ── Step 7: Start the service ────────────────────────────────
echo  Starting service ...
"%NSSM%" start TravelMapTool
timeout /t 4 /nobreak >nul

sc query TravelMapTool | find "RUNNING" >nul
if ERRORLEVEL 1 (
    echo.
    echo  WARNING: Service did not start. Check logs at:
    echo  %PROJECT%logs\app.log
    pause & exit /b 1
)

:: ── Show the URL people should use ───────────────────────────
echo.
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do (
    set "SERVER_IP=%%a"
    goto :gotip
)
:gotip
set "SERVER_IP=%SERVER_IP: =%"

echo  ============================================================
echo.
echo   SUCCESS! The tool is now live.
echo.
echo   Share this URL with your team:
echo.
echo     http://%SERVER_IP%:%PORT%
echo.
echo   Or using the server name:
echo     http://%COMPUTERNAME%:%PORT%
echo.
echo   The app will start automatically every time
echo   this server reboots. No action needed.
echo.
echo   To stop/start: search "Services" in Start Menu
echo   find "Travel Map Tool"
echo.
echo   Logs: %PROJECT%logs\app.log
echo  ============================================================
echo.
pause
