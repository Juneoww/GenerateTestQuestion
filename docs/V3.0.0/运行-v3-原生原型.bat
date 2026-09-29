@rem Function:
@rem   Launch the standalone GenerateTestQuestion v3.0.0 Tkinter prototype.
@rem Implementation:
@rem   Move to the project root, verify the existing virtual environment, then run the prototype.
@rem Inputs:
@rem   Optional command-line arguments, for example --smoke-test.
@rem Outputs:
@rem   A local prototype window by default, or JSON for --smoke-test; no project data is written.
@rem Dependencies:
@rem   .venv\Scripts\python.exe under the project root.
@rem Usage:
@rem   Double-click this file, or run it from a command prompt.
@echo off
setlocal
cd /d "%~dp0\..\.."
if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] .venv not found. Please create the project environment first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" prototypes\v3_native_prototype.py %*
if errorlevel 1 (
  echo.
  echo [ERROR] Prototype exited with an error. See message above.
  pause
)
endlocal
