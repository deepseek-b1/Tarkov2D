# -*- coding: utf-8 -*-
"""一键发布更新:改版本号 -> PyInstaller 打包 -> 放进 update_server -> 写 version.json

用法:
    python publish_update.py 1.0.2 "修复了XXX"
之后启动更新服务器(可选):
    python -m http.server 8765 --directory update_server
游戏启动时会读取 http://127.0.0.1:8765/version.json 并自动升级。
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(ROOT, "settings.py")
SERVER_DIR = os.path.join(ROOT, "update_server")


def main():
    if len(sys.argv) < 2:
        print("用法: python publish_update.py <版本号> [更新说明]")
        return 1
    version = sys.argv[1].strip()
    notes = sys.argv[2] if len(sys.argv) > 2 else ""
    if not re.fullmatch(r"\d+(\.\d+)*", version):
        print("版本号格式应为 1.2.3")
        return 1

    src = io.open(SETTINGS, encoding="utf-8").read()
    new_src, n = re.subn(r'GAME_VERSION = "[^"]*"', f'GAME_VERSION = "{version}"', src)
    if not n:
        print("未找到 GAME_VERSION,发布中止")
        return 1
    io.open(SETTINGS, "w", encoding="utf-8", newline="").write(new_src)
    print(f"[1/4] 版本号 -> {version}")

    print("[2/4] PyInstaller 打包中…(约 1 分钟)")
    # 必须带 --add-data "art;art":玩家立绘等图片资源不在包里就会退回圆点绘制
    # (分隔符 Windows 是 ';'、Linux/macOS 是 ':',所以用 os.pathsep)
    rc = subprocess.call([sys.executable, "-m", "PyInstaller", "--onefile",
                          "--noconsole", "--clean", "--name", "Tarkov2D",
                          "--add-data", f"art{os.pathsep}art", "main.py"],
                         cwd=ROOT)
    if rc != 0:
        print("打包失败")
        return rc

    os.makedirs(SERVER_DIR, exist_ok=True)
    shutil.copy2(os.path.join(ROOT, "dist", "Tarkov2D.exe"),
                 os.path.join(SERVER_DIR, "Tarkov2D.exe"))
    print("[3/4] 已复制到 update_server\\Tarkov2D.exe")

    manifest = {"version": version, "url": "Tarkov2D.exe", "notes": notes}
    with io.open(os.path.join(SERVER_DIR, "version.json"), "w",
                 encoding="utf-8", newline="") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[4/4] 已写入 version.json: v{version} {notes}")
    print("\n启动更新服务器后,玩家启动游戏即可自动升级:")
    print("    python -m http.server 8765 --directory update_server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
