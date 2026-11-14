@echo off

:: windows does this silly thing where it navigates away from the current directory to C:/Windows/system32
:: when the script is ran as administrator. ensure we're in the right directory.
setlocal enableextensions
cd /d "%~dp0"

set "SCRIPT_PATH=%~f0"
net session >nul 2>&1
if not %errorlevel% == 0 (
	echo [.] administrator permissions are required, elevating...
	powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath $env:SCRIPT_PATH -Verb RunAs" 2>nul
	
	if errorlevel 1 (
		echo [-] could not obtain administrator permissions.
		pause
	)

	exit /b
)

pip install -r requirements.txt
cls
python add-library.py [gui]
pause
