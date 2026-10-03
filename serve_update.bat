@echo off
rem 启动本地更新服务器(把 update_server 目录发布到 8765 端口)
rem 玩家机器上把 settings.py 的 UPDATE_MANIFEST_URL 指向你的服务器/GitHub raw 即可
cd /d %~dp0
echo 更新服务器: http://127.0.0.1:8765/version.json
echo 按 Ctrl+C 停止
python -m http.server 8765 --directory update_server
