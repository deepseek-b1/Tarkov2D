# -*- coding: utf-8 -*-
"""生成网页版的 index.html(pygbag 的浏览器页面),绕过 pygbag 自己卡住的下载步骤。

做法:
  1. 取 pygbag 官方页面模板(CDN 上的 default.tmpl),填好占位符
  2. 用 pygame 生成 favicon.png
  3. 输出到 webapp/build/web/,与 webapp.apk 一起就是完整网页版

之后可用 serve_web.py 本地起服务(带 COOP/COEP 头,性能更好),
或把整个 webapp/build/web 目录丢给 HBuilderX 打成 APK。
"""
import io
import os
import sys
import urllib.request

import pygame

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "webapp", "build", "web")
TMPL = os.path.join(WEB, "default.tmpl")

# 与 pygbag 0.9.3 的默认值保持一致
CDN = "https://pygame-web.github.io/cdn/0.9.3/"
ARCHIVE = "webapp"          # 会去加载 webapp.apk
TITLE = "Tarkov2D"
VERSION = "0.9.3"
PYBUILD = "3.12"
WIDTH, HEIGHT = 1280, 720
UME_BLOCK = 1               # 需要点击一次才开始(手机音频解锁)
CAN_CLOSE = 0
XTERMJS = 1
AUTHORS = "pgw"

CC = {
    "cdn": CDN,
    "archive": ARCHIVE,
    "title": TITLE,
    "version": VERSION,
    "PYBUILD": PYBUILD,
    "width": WIDTH,
    "height": HEIGHT,
    "ume_block": UME_BLOCK,
    "can_close": CAN_CLOSE,
    "xtermjs": XTERMJS,
    "authors": AUTHORS,
    "icon": "favicon.png",
    "directory": ARCHIVE,
    "proxy": "",
    "autorun": "0",
    "spdx": "",
    "COLUMNS": "132",
    "LINES": "42",
    "CONSOLE": "0",
    "INI": "",
}


def fetch_template():
    if os.path.exists(TMPL) and os.path.getsize(TMPL) > 1000:
        return io.open(TMPL, encoding="utf-8").read()
    url = CDN + "default.tmpl"
    print("下载页面模板:", url)
    with urllib.request.urlopen(url, timeout=60) as r:
        text = r.read().decode("utf-8")
    os.makedirs(WEB, exist_ok=True)
    io.open(TMPL, "w", encoding="utf-8", newline="").write(text)
    return text


def make_favicon(path):
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    if not pygame.get_init():
        pygame.init()
    surf = pygame.Surface((32, 32))
    surf.fill((18, 20, 24))
    pygame.draw.rect(surf, (255, 176, 32), (4, 4, 24, 24), 3, border_radius=4)
    pygame.draw.line(surf, (255, 176, 32), (9, 23), (23, 9), 4)
    pygame.image.save(surf, path)


def main():
    os.makedirs(WEB, exist_ok=True)
    text = fetch_template()
    for key, value in CC.items():
        text = text.replace("{{cookiecutter." + key + "}}", str(value))
    left = text.count("{{cookiecutter.")
    out = os.path.join(WEB, "index.html")
    io.open(out, "w", encoding="utf-8", newline="").write(text)
    make_favicon(os.path.join(WEB, "favicon.png"))
    apk = os.path.join(WEB, ARCHIVE + ".apk")
    print("index.html :", out, f"({os.path.getsize(out)} 字节)")
    print("favicon.png: 已生成")
    print("应用包     :", apk,
          "(%.1f MB)" % (os.path.getsize(apk) / 1e6) if os.path.exists(apk) else "缺失!")
    if left:
        print(f"提示:{left} 个占位符未替换(通常是注释里的,可忽略)")
    print("\n下一步:python serve_web.py(电脑上调);或把该目录交给 HBuilderX 打成 APK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
