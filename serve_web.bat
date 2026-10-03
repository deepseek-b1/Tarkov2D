@echo off
rem 启动网页版服务器(手机连同一个 Wi-Fi,浏览器打开电脑 IP:8000 即可玩)
cd /d %~dp0
echo 本机地址:
ipconfig | findstr /i "IPv4"
echo.
echo 手机浏览器打开:  http://<上面那个IPv4>:8000
echo 按 Ctrl+C 停止
python -m http.server 8000 --directory build\web
