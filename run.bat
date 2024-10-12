@echo off

:: windows does this silly thing where it navigates away from the current directory to C:/Windows/system32
:: when the script is ran as administrator. ensure we're in the right directory.
setlocal enableextensions
cd /d "%~dp0"

:: check for admin permissions (so that we can modify HKEY_LOCAL_MACHINE)
net session >nul 2>&1
if not %errorlevel% == 0 (
	echo [-] this script requires administrator permissions.
	echo [-] run it again as administrator to properly launch it.
	pause
	exit
)

pip install -r requirements.txt
cls
python add-library.py [gui]
pause