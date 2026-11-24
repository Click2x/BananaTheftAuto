@echo off
rem Local addition to this fork: double-click for the guided menu (find game, check PC, install tools, build).
title Leonida
cd /d "%~dp0"
set "PY="
for %%V in (3.14 3.13 3.12 3) do (
  if not defined PY (
    py -%%V -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=py -%%V"
  )
)
if not defined PY (
  where python >nul 2>nul && (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >nul 2>nul && set "PY=python"
  )
)
if not defined PY (
  echo.
  echo   Python 3.12 or newer was not found. Run Build.bat to have it installed for you,
  echo   or get it from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^).
  pause
  exit /b 1
)
%PY% -I "%~dp0leonida_menu.py" %*
pause
