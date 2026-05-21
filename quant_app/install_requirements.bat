@echo off
echo Starting to install requirements...
cd /d "%~dp0"
pip install -r requirements.txt
echo.
echo Setup finished!
pause
