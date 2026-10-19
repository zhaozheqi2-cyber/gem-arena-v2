@echo off
setlocal
cd /d "%~dp0"
set "ARENA_PY=py -3.12"
%ARENA_PY% --version >nul 2>nul
if errorlevel 1 set "ARENA_PY=python"
%ARENA_PY% --version >nul 2>nul
if errorlevel 1 set ARENA_PY="%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
%ARENA_PY% --version >nul 2>nul
if errorlevel 1 goto missing
set "ARENA_OUT=runs\demo-%RANDOM%-%RANDOM%"
%ARENA_PY% -m arena.tournament --out "%ARENA_OUT%"
if errorlevel 1 goto failed
%ARENA_PY% -m arena.verify "%ARENA_OUT%"
if errorlevel 1 goto failed
start "" "%ARENA_OUT%\index.html"
pause
exit /b 0
:missing
echo Install Python 3.12 and enable "Add Python to PATH", then try again.
pause
exit /b 1
:failed
echo Run failed. See the error above.
pause
exit /b 1
