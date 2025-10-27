@echo off
REM ========================================================
REM pack_addon.bat — Package a directory into a ZIP file
REM ========================================================

REM === CONFIGURATION ======================================
set "SRC_DIR=t4p_clean"
set "DIST_DIR=dist"
set "ZIP_NAME=T4P_clean.zip"
REM ========================================================

REM Normalize full paths
for %%I in ("%SRC_DIR%") do set "SRC_DIR=%%~fI"
for %%I in ("%DIST_DIR%") do set "DIST_DIR=%%~fI"
set "ZIP_PATH=%DIST_DIR%\%ZIP_NAME%"

echo.
echo Cleaning old dist folder...
if exist "%DIST_DIR%" (
    rmdir /s /q "%DIST_DIR%"
)
mkdir "%DIST_DIR%" >nul

timeout /t 1 /nobreak >nul

echo Creating ZIP file...
echo.
powershell -nologo -noprofile -command ^
    "Compress-Archive -Path '%SRC_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"

timeout /t 1 /nobreak >nul

if %errorlevel% neq 0 (
    echo.
    echo Failed to create ZIP.
    exit /b %errorlevel%
) else (
    echo.
    echo ✅ ZIP created successfully:
    echo   %ZIP_PATH%
)
