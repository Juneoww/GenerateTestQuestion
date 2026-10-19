@rem Function: Launch the standalone v4 Tkinter prototype or its smoke test.
@rem Implementation: Locate the repository and invoke its existing Python environment.
@rem Inputs: Optional --smoke-test argument.
@rem Outputs: A local GUI or smoke-test JSON; no application data is changed.
@rem Dependencies: .venv\Scripts\python.exe in the project root.
@rem Usage: Double-click this file, or pass --smoke-test in a terminal.
@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] Project Python environment was not found. 1>&2
  exit /b 1
)
".venv\Scripts\python.exe" prototypes\v4_native_prototype.py %*
set "v4_prototype_exit=%errorlevel%"
if not "%v4_prototype_exit%"=="0" if "%~1"=="" (
  echo [ERROR] Prototype exited with an error.
  pause
)
exit /b %v4_prototype_exit%
