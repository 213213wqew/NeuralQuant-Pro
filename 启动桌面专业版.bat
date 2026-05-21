@echo off
setlocal
cd /d "%~dp0"
echo Starting A-Quant Desktop Pro...
echo.
echo [温馨提示] 如果点击了黑窗内部导致程序卡住，请按 [回车] 键恢复。
echo [Tip] If the program freezes after clicking the console, press [Enter] to resume.
echo.
python run_flet.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Launch failed. Please install dependencies:
    echo pip install flet plotly pandas
    pause
)
pause
