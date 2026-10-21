@echo off
rem ============================================================
rem  Call from any directory:  doctor.cmd
rem  Runs the environment health check (includes one real API call)
rem ============================================================
setlocal
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"
rem Strip the trailing backslash: a path ending in \ before a closing quote
rem makes cmd treat \" as an escaped quote, truncating the argument.
set "PPROOT=%ROOT:~0,-1%"

where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] python not found in PATH.
    exit /b 3
)

python "%ROOT%.codeartsdoer\skills\huaweicloud-provision\scripts\doctor.py" --project-root "%PPROOT%" %*
exit /b %ERRORLEVEL%
