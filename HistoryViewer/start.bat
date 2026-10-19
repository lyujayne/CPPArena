@echo off
setlocal
cd /d "%~dp0"
if exist "E:\anaconda\python.exe" (
    "E:\anaconda\python.exe" viewer.py %*
) else (
    python viewer.py %*
)
endlocal
