@echo off
setlocal
powershell.exe -STA -NoProfile -ExecutionPolicy Bypass -File "%~dp0Build-Patched-ISO.ps1" -Interactive %*
set "build_exit=%errorlevel%"
echo.
if not "%build_exit%"=="0" echo The ISO build failed. See the error above.
pause
exit /b %build_exit%
