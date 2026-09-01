@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please run once in this folder:
  echo   uv venv
  echo   uv pip install -p .venv/Scripts/python.exe -r requirements.txt
  pause
  exit /b 1
)
".venv\Scripts\python.exe" app.py %*
if errorlevel 1 (
  echo.
  echo [ERROR] App exited with an error. See message above.
  pause
)
endlocal
