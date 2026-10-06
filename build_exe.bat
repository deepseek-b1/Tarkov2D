@echo off
rem 一键打包:生成 dist\Tarkov2D.exe
cd /d %~dp0
python -m PyInstaller --onefile --noconsole --clean --name Tarkov2D main.py
echo.
echo 完成: dist\Tarkov2D.exe
pause
