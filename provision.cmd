@echo off
rem ============================================================
rem  Call from any directory:  provision.cmd <subcommand> [args...]
rem  Example:  D:\ICT_creating_match\provision.cmd list rds
rem  Example:  D:\ICT_creating_match\provision.cmd create rds --name x --dry-run
rem ============================================================
setlocal
chcp 65001 >nul 2>nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"
set "ROOT=%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [FAIL] python not found in PATH.
    exit /b 3
)

python "%ROOT%.codeartsdoer\skills\huaweicloud-provision\scripts\provision.py" %*
exit /b %ERRORLEVEL%
