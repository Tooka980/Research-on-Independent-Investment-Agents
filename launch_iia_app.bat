@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
set "PYTHONPATH=%CD%\src"

if not exist "%PYTHON_EXE%" (
  echo Python runtime was not found.
  echo Expected: %PYTHON_EXE%
  pause
  exit /b 1
)

echo Starting Independent Investment Agents web dashboard...
echo URL: http://127.0.0.1:8501
"%PYTHON_EXE%" -m independent_investment_agents.app.launch_dashboard --host 127.0.0.1 --port 8501

pause
