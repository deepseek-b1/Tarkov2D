@echo off
rem 一键打包:生成 dist\Tarkov2D.exe
rem 注意:必须带 --add-data "art;art"(玩家立绘等图片资源),否则 EXE 里没图,
rem       玩家会自动退回圆点绘制(自检 渲染-玩家立绘三视图与四向 会失败)。
cd /d %~dp0
python -m PyInstaller --onefile --noconsole --clean --name Tarkov2D --add-data "art;art" main.py
echo.
echo 完成: dist\Tarkov2D.exe
pause
