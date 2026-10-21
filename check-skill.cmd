@echo off
rem ============================================================
rem  Skill package check - double click to run
rem  Validates huaweicloud-provision.zip before importing to CodeArts
rem ============================================================
setlocal
set "ROOT=%~dp0"

rem Switch console to UTF-8 so Chinese output is not garbled
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
rem  Do not write __pycache__ into the skill package
set "PYTHONDONTWRITEBYTECODE=1"

where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] python not found in PATH.
    echo        Install Python 3.8+ and try again.
    pause
    exit /b 3
)

echo.
echo Checking: %ROOT%huaweicloud-provision.zip
echo ------------------------------------------------------------
python "%ROOT%.codeartsdoer\skills\huaweicloud-provision\scripts\validate_skill.py" --zip "%ROOT%huaweicloud-provision.zip"
set "CODE=%ERRORLEVEL%"
echo ------------------------------------------------------------

if "%CODE%"=="0" (
    echo [PASS] Ready to import. Use CodeArts: Settings - Skills and Rules - Project level - Import
) else (
    echo [FAIL] Do NOT import yet. Fix the issues listed above.
)

echo.
pause
exit /b %CODE%
