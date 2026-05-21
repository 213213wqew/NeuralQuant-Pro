@echo off
setlocal
chcp 936 >nul
cd /d "%~dp0"

echo ========================================
echo   NeuralQuant Pro Build Script
echo ========================================
echo.

set "STAGING_DIST=dist_staging"
set "STAGING_BUILD=build_staging"
set "TARGET_DIR=dist\NeuralQuantPro"

if not exist "NeuralQuantPro.spec" (
    echo [ERROR] NeuralQuantPro.spec not found. Please run this script from the project root.
    pause
    exit /b 1
)

echo [1/4] Checking Python...
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    pause
    exit /b 1
)

echo [2/4] Checking PyInstaller...
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    python -m pip install --upgrade pip
    python -m pip install pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller installation failed.
        pause
        exit /b 1
    )
)

echo [3/4] Building package...
if exist "%STAGING_DIST%" rmdir /s /q "%STAGING_DIST%"
if exist "%STAGING_BUILD%" rmdir /s /q "%STAGING_BUILD%"
python -m PyInstaller --clean --noconfirm --distpath "%STAGING_DIST%" --workpath "%STAGING_BUILD%" NeuralQuantPro.spec
if errorlevel 1 (
    echo.
    echo [ERROR] Build failed. Please check the output above.
    pause
    exit /b 1
)

echo [3.5/4] Syncing files into %TARGET_DIR% ...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
robocopy "%STAGING_DIST%\NeuralQuantPro" "%TARGET_DIR%" /E /NFL /NDL /NJH /NJS /NP
set "ROBOCODE=%ERRORLEVEL%"
if %ROBOCODE% GEQ 8 (
    echo [ERROR] File sync failed. Robocopy exit code: %ROBOCODE%
    pause
    exit /b 1
)

echo.
echo [4/4] Build finished.
echo Output: dist\NeuralQuantPro\NeuralQuantPro.exe

echo.
set /p RUN_APP=Run the app now? (y/n): 
if /i "%RUN_APP%"=="y" (
    if exist "dist\NeuralQuantPro\NeuralQuantPro.exe" (
        start "" "dist\NeuralQuantPro\NeuralQuantPro.exe"
    ) else (
        echo [WARN] Executable not found in dist folder.
    )
)

pause
endlocal
