@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found in PATH. Please install Python 3 and retry.
  pause
  exit /b 1
)
python -m pip install -r requirements.txt
python ctrip_package_intro_filling.pyw
pause
