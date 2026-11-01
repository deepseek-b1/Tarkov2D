@echo off
rem ---------------------------------------------------------------------------
rem Build the Windows 7 compatible 32-bit single-file EXE.
rem
rem Why: the normal build uses CPython 3.13 (64-bit), which requires Windows 8.1+
rem      and python313.dll depends on api-ms-win-core-path-l1-1-0.dll (missing on
rem      Windows 7). Windows 7 needs CPython 3.8 (the last version supporting it)
rem      built for 32-bit; that also runs on Win10/11 via WoW64.
rem
rem Toolchain (tested):
rem      CPython 3.8.10 32-bit
rem      pygame 2.6.1 (cp38-win32 / SDL 2.28.4)
rem      PyInstaller 6.19.0
rem
rem Setup:
rem      <py38-32>\python.exe -m pip install pygame==2.6.1 pyinstaller==6.19.0
rem      then put that python.exe first on PATH (or edit PY= below).
rem ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"
set PY=python

%PY% -c "import sys,struct; print('python', sys.version); print('bits', struct.calcsize('P')*8)"
%PY% -c "import pygame, PyInstaller; print('pygame', pygame.__version__); print('pyinstaller', PyInstaller.__version__)"

rem runtime-tmpdir keeps the onefile extraction next to the exe (some locked-down
rem machines deny %TEMP%); delete the option if you prefer the system temp dir.
%PY% -m PyInstaller --onefile --noconsole --name Tarkov2D ^
     --runtime-tmpdir .\_mei_cache --clean main.py
if errorlevel 1 goto fail

echo.
echo Done: dist\Tarkov2D.exe   (PE32 / Machine 0x014C / MinOS 6.0)
echo       Works on Windows 7 SP1 (32/64-bit), Windows 8/8.1/10/11.
goto end

:fail
echo.
echo Build FAILED
:end
pause
