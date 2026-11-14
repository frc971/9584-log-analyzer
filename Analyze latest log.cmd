@echo off
rem Double-click to run the full report on the newest log in logs\ (and save its numbers).
rem Same as typing:  python analyze.py
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 analyze.py %*
) else (
    python analyze.py %*
)
echo.
pause
