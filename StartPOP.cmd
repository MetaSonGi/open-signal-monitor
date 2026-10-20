@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" -m learning.pop
    goto finish
)
where py >nul 2>nul
if not errorlevel 1 (
    py -3 -m learning.pop
) else (
    python -m learning.pop
)
:finish
if errorlevel 1 (
    echo.
    echo Python 3.11 or later with tkinter is recommended.
    pause
)
