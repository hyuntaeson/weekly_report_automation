@echo off
rem WeeklyPulse fast launcher
rem - pyenv shim('python')을 거치면 버전 해석에 약 6초가 걸리므로
rem   실제 인터프리터 경로를 직접 지정한다. Python 버전을 올리면 아래 경로만 수정.
rem - pythonw.exe로 실행해 콘솔 창 없이 GUI만 띄운다 (콘솔 로그 필요하면 python -m weekly_report).

set "PY=C:\Users\SSG\.pyenv\pyenv-win\versions\3.11.9\pythonw.exe"
if not exist "%PY%" (
  for /f "delims=" %%i in ('where pythonw.exe 2^>nul') do set "PY=%%i" & goto :found
)
:found
if not exist "%PY%" set "PY=pythonw"
cd /d "%~dp0"
start "" "%PY%" -m weekly_report
