# -*- coding: utf-8 -*-
"""启动更新检查:读取版本清单 -> 若有新版则下载 -> 用批处理等本进程退出后就地替换 EXE -> 重启。

清单来源(按优先级):
  1. EXE 同目录的 version.json(离线/内网发布用)
  2. settings.UPDATE_MANIFEST_URL(HTTP,例如自建服务器或 GitHub raw)
清单格式:
  {"version": "1.0.1", "url": "http://127.0.0.1:8765/Tarkov2D.exe", "notes": "更新说明"}
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

MANIFEST_NAME = "version.json"


def _settings():
    import settings
    return settings


def _base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def local_manifest_path():
    return os.path.join(_base_dir(), MANIFEST_NAME)


def parse_version(s):
    """'1.10.2' -> (1, 10, 2)"""
    out = []
    for part in str(s).strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(remote, current):
    a, b = parse_version(remote), parse_version(current)
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return a > b


def fetch_manifest():
    """返回 (清单 dict 或 None, 说明文字)。"""
    st = _settings()
    p = local_manifest_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f), "本地 version.json"
        except Exception as e:
            return None, f"本地清单损坏:{e.__class__.__name__}"
    url = getattr(st, "UPDATE_MANIFEST_URL", "") or ""
    if not url:
        return None, "未配置更新源"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Tarkov2D-updater"})
        with urllib.request.urlopen(req, timeout=getattr(st, "UPDATE_TIMEOUT", 3)) as r:
            return json.loads(r.read().decode("utf-8")), url
    except Exception as e:
        return None, f"检查更新失败({e.__class__.__name__})"


def download(url, dest, progress=None):
    """流式下载,progress(已下载, 总大小) 可为 None。返回 True/False。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Tarkov2D-updater"})
        with urllib.request.urlopen(req, timeout=getattr(_settings(), "UPDATE_TIMEOUT", 3)) as r:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            with open(dest, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        return os.path.getsize(dest) > 0
    except Exception:
        return False


def _resolve_url(base_url, new_url):
    if new_url.startswith(("http://", "https://", "file://")):
        return new_url
    return urllib.parse.urljoin(base_url, new_url)


def launch_self_replace(new_file, target_exe):
    """写一个批处理:等本进程完全退出(用"重试覆盖"代替等 PID)，
    覆盖 EXE 后重启,最后删除自己。

    注意:PyInstaller 单文件模式的父引导进程比子进程晚退出,
    只等 PID 会在文件仍被占用时 copy 失败并静默重启旧版。
    """
    pid = os.getpid()
    bat = os.path.join(tempfile.gettempdir(), f"tarkov2d_update_{pid}.bat")
    script = (
        "@echo off\r\n"
        "chcp 65001 >nul 2>nul\r\n"
        "set /a tries=0\r\n"
        ":copy_loop\r\n"
        f'copy /Y "{new_file}" "{target_exe}" >nul 2>nul\r\n'
        "if not errorlevel 1 goto done\r\n"
        "set /a tries+=1\r\n"
        "if %tries% GEQ 90 goto failed\r\n"
        "timeout /t 1 /nobreak >nul\r\n"
        "goto copy_loop\r\n"
        ":done\r\n"
        f'del "{new_file}" >nul 2>nul\r\n'
        f'start "" "{target_exe}"\r\n'
        'del "%~f0"\r\n'
        "exit /b 0\r\n"
        ":failed\r\n"
        f'del "{new_file}" >nul 2>nul\r\n'
        f'start "" "{target_exe}"\r\n'
        'del "%~f0"\r\n'
        "exit /b 0\r\n"
    )
    with open(bat, "w", encoding="utf-8") as f:
        f.write(script)
    DETACHED = 0x00000008
    NO_WINDOW = 0x08000000
    subprocess.Popen(["cmd", "/c", bat], creationflags=DETACHED | NO_WINDOW,
                     close_fds=True)
    return bat


def run_startup_check(screen):
    """启动时检查更新。返回 True 表示已触发更新(调用方应结束进程)。"""
    import pygame
    from settings import W, H, get_font

    st = _settings()
    clock = pygame.time.Clock()

    def pump(seconds=0.0):
        """绘制后停留一小段时间,期间保持窗口响应。"""
        pygame.display.flip()
        end = pygame.time.get_ticks() + int(seconds * 1000)
        while pygame.time.get_ticks() < end:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    sys.exit(0)
            clock.tick(60)

    def draw(status, note="", color=(150, 220, 150), progress=None):
        screen.fill((18, 20, 24))
        f1 = get_font(34, bold=True).render("TARKOV 2D", True, (255, 176, 32))
        screen.blit(f1, f1.get_rect(center=(W // 2, H // 2 - 90)))
        t = get_font(20).render(f"当前版本 v{st.GAME_VERSION}", True, (222, 226, 232))
        screen.blit(t, t.get_rect(center=(W // 2, H // 2 - 40)))
        t = get_font(22, bold=True).render(status, True, color)
        screen.blit(t, t.get_rect(center=(W // 2, H // 2 + 10)))
        if note:
            t = get_font(16).render(note, True, (150, 156, 166))
            screen.blit(t, t.get_rect(center=(W // 2, H // 2 + 46)))
        if progress is not None:
            r = pygame.Rect(W // 2 - 200, H // 2 + 80, 400, 18)
            pygame.draw.rect(screen, (40, 44, 52), r, border_radius=6)
            pygame.draw.rect(screen, (255, 176, 32),
                             (r.x, r.y, int(r.w * max(0.0, min(1.0, progress))), r.h),
                             border_radius=6)

    draw("正在检查更新…", color=(200, 200, 210))
    pump(0.15)

    man, src = fetch_manifest()
    if not man or not man.get("version"):
        draw("未发现更新源,直接开始游戏", src, color=(200, 200, 210))
        pump(0.7)
        return False

    remote = str(man["version"])
    if not is_newer(remote, st.GAME_VERSION):
        draw("已是最新版本", f"v{st.GAME_VERSION}", color=(150, 220, 150))
        pump(0.7)
        return False

    # 发现新版本
    notes = str(man.get("notes", "") or "")
    draw(f"发现新版本 v{remote}", notes, color=(255, 200, 90))
    pump(0.6)

    url = _resolve_url(src if src.startswith(("http", "file")) else "", str(man.get("url", "")))
    if not url:
        draw("更新清单缺少下载地址,继续游戏", "", color=(220, 140, 120))
        pump(1.2)
        return False

    exe = sys.executable if getattr(sys, "frozen", False) else None
    if exe is None:
        draw("开发模式(python 运行):跳过自动替换", "请用 PyInstaller 打包后再验证更新",
             color=(220, 200, 140))
        pump(1.5)
        return False

    new_file = os.path.join(os.path.dirname(exe), "Tarkov2D.new.exe")
    last = [0.0]

    def on_progress(done, total):
        if total:
            last[0] = done / total
        draw(f"正在下载 v{remote}…",
             f"{done // 1024} KB" + (f" / {total // 1024} KB" if total else ""),
             color=(255, 200, 90), progress=last[0])
        pump(0.02)

    if not download(url, new_file, on_progress):
        draw("下载失败,继续游戏(本次不更新)", url, color=(220, 140, 120))
        pump(1.4)
        return False

    draw("下载完成,正在安装并重启…", "游戏会自动关闭后重新打开", color=(150, 220, 150))
    pump(0.8)
    try:
        launch_self_replace(new_file, exe)
    except Exception as e:
        draw("自动安装失败,继续游戏", e.__class__.__name__, color=(220, 140, 120))
        pump(1.4)
        return False
    return True
