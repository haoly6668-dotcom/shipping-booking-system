@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py
) else if exist "..\.venv\Scripts\python.exe" (
  "..\.venv\Scripts\python.exe" run.py
) else (
  echo Please run setup.ps1 first to create the Python environment.
)
pause
