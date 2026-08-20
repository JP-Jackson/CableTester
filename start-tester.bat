@echo off
setlocal EnableExtensions
title Polk RS-232 Cable Tester
pushd "%~dp0"

echo.
echo  ================================================
echo    POLK PRODUCTION TECHNOLOGIES
echo    RS-232 Cable Tester
echo  ================================================
echo.

rem ---------------------------------------------------------------
rem  1. Find Python. The 'py' launcher is preferred because a bare
rem     'python' on Windows can be the Microsoft Store stub, which
rem     opens the Store instead of running anything.
rem ---------------------------------------------------------------
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if not defined PY (
  python --version >nul 2>&1
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo  [X] Python was not found on this PC.
  echo.
  echo      Install Python 3.9 or newer from
  echo        https://www.python.org/downloads/
  echo      and tick "Add python.exe to PATH" during setup.
  echo.
  goto :stop
)

rem ---------------------------------------------------------------
rem  2. Pull the latest version. Never fatal: a bench PC with no
rem     internet should still be able to run the copy it has.
rem ---------------------------------------------------------------
git --version >nul 2>&1
if errorlevel 1 (
  echo  [!] Git is not installed, so this cannot check for updates.
  echo      Running the version already on this PC.
  goto :afterupdate
)
if not exist ".git" (
  echo  [!] This folder is not a git clone, so this cannot check for updates.
  goto :afterupdate
)

echo  Checking GitHub for updates...
git pull --ff-only origin main
if errorlevel 1 (
  echo.
  echo  [!] Could not update. Running the version already on this PC.
  echo      Usually this means no internet, or you have edited a file
  echo      here. To throw away local edits and force an update:
  echo        git reset --hard origin/main
  echo.
)
:afterupdate

rem ---------------------------------------------------------------
rem  3. Build the virtual environment on first run.
rem ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo  First run on this PC: creating the Python environment.
  echo  This takes a minute or two. It only happens once.
  %PY% -m venv .venv
  if errorlevel 1 (
    echo.
    echo  [X] Could not create the environment in .venv
    echo      Try deleting the .venv folder and running this again.
    goto :stop
  )
)
set "VPY=.venv\Scripts\python.exe"

rem ---------------------------------------------------------------
rem  4. Install or refresh dependencies. Also not fatal offline, so
rem     long as the packages are already there from a previous run.
rem ---------------------------------------------------------------
echo  Checking dependencies...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  "%VPY%" -c "import serial, flask" >nul 2>&1
  if errorlevel 1 (
    echo.
    echo  [X] Could not install pyserial and Flask, and they are not
    echo      already installed. This PC needs internet for the first run.
    goto :stop
  )
  echo  [!] Could not reach the internet. Using the packages already installed.
)

rem ---------------------------------------------------------------
rem  5. Open the browser once the server is actually answering, so
rem     it never lands on a connection-refused page.
rem ---------------------------------------------------------------
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "$u='http://localhost:5000/'; for($i=0; $i -lt 60; $i++){ try { $null = Invoke-WebRequest -UseBasicParsing $u -TimeoutSec 1; Start-Process $u; break } catch { Start-Sleep -Milliseconds 500 } }"

echo.
echo  ------------------------------------------------
echo   Starting. The browser opens on its own.
echo   If it does not, go to:  http://localhost:5000
echo.
echo   KEEP THIS WINDOW OPEN while you are testing.
echo   Close it, or press Ctrl+C, to stop the tester.
echo  ------------------------------------------------
echo.

"%VPY%" run.py %*

echo.
echo  The tester has stopped.
echo.
echo  If it stopped straight away with "Address already in use",
echo  the tester is already running in another window. Use that one,
echo  or close it and try again.

:stop
echo.
popd
pause
endlocal
