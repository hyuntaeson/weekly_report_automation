@echo off
cd /d "%~dp0"
echo Starting WeeklyPulse Modern UI...
python modern_gui.py
if errorlevel 1 (
    echo Error occurred. Press any key to exit...
    pause
)