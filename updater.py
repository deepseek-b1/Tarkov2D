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
import threading
import time
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


def _load_local():
    p = local_manifest_path()
    if not os.path.exists(p):
        return None, "无本地 version.json"
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f), "本地 version.json"
    except Exception as e:
        return None, f"本地清单损坏:{e.__class__.__name__}"


def _load_remote(url):
    if not url:
        return None, "未配置更新源"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Tarkov2D-updater"})
        with urllib.request.urlopen(req, timeout=getattr(_settings(), "UPDATE_TIMEOUT", 3)) as r:
            return json.loads(r.read().decode("utf-8")), url
    except Exception as e:
        return None, f"检查更新失败({e.__class__.__name__})"


def fetch_manifest(prefer_remote=False):
    """返回 (清单 dict 或 None, 说明文字)。

    prefer_remote=True 时先问网络(实时更新用:推送即生效),
    失败才退回 EXE 同目录的 version.json;默认仍是本地优先。
    """
    url = getattr(_settings(), "UPDATE_MANIFEST_URL", "") or ""
    last = "未配置更新源"
    order = ((_load_remote, url), (_load_local, None)) if prefer_remote \
        else ((_load_local, None), (_load_remote, url))
    for fn, arg in order:
        man, src = (fn(arg) if arg is not None else fn())
        if man is not None:
            return man, src
        last = src
    return None, last


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


# ---------------- 运行期实时更新(看门狗) ----------------
# 启动时那次检查之外,游戏跑起来之后每隔 UPDATE_POLL_INTERVAL 秒再问一次清单。
# 网络读取和下载全在后台线程,主线程每帧只读一份状态快照并画提示条,不阻塞渲染。
# 在局内发现新版本 -> 右上角提示 + 藏身处 toast;按 F9 下载,下完再按一次 F9 重启安装。

_watch_lock = threading.Lock()
_watch = {
    "started": False,
    "hk_down": False,
    "last_check": 0.0,
    "checks": 0,
    "last_error": "",
    "remote": None,      # 发现的新版本清单(None = 没有)
    "source": "",
    "download": None,    # {"version","done","total"}
    "ready": None,       # 已下载待安装 {"version","path"}
    "notified": False,
    "installing": False,
}


def _snapshot():
    with _watch_lock:
        d = dict(_watch)
        for k in ("remote", "download", "ready"):
            if d.get(k):
                d[k] = dict(d[k])
        return d


def _set(**kw):
    with _watch_lock:
        _watch.update(kw)


def poll_once():
    """问一次清单。返回 True 表示发现比当前版本更新的版本。不抛异常。"""
    st = _settings()
    try:
        man, src = fetch_manifest(prefer_remote=True)
    except Exception as e:
        man, src = None, f"{e.__class__.__name__}: {e}"
    with _watch_lock:
        _watch["last_check"] = time.time()
        _watch["checks"] += 1
        if not man or not man.get("version"):
            _watch["last_error"] = str(src)
            return False
        _watch["last_error"] = ""
        _watch["source"] = src
        remote = str(man["version"])
        if is_newer(remote, st.GAME_VERSION):
            prev = (_watch.get("remote") or {}).get("version")
            if not _watch.get("download") and not _watch.get("ready"):
                _watch["remote"] = dict(man)
                if prev != remote:
                    _watch["notified"] = False       # 换了个版本,重新提示
            return True
        # 远端不再更新(或已经追平):清掉待更新状态,避免提示条挂着不走
        if not _watch.get("download") and not _watch.get("ready"):
            _watch["remote"] = None
            _watch["notified"] = False
        return False


def _watch_loop(interval, quiet):
    if quiet > 0:
        time.sleep(quiet)
    while True:
        try:
            poll_once()
        except Exception:
            pass
        time.sleep(interval)


def start_watchdog():
    """启动后台轮询线程。interval<=0 表示不启用。重复调用只生效一次。"""
    st = _settings()
    try:
        interval = int(getattr(st, "UPDATE_POLL_INTERVAL", 0) or 0)
        quiet = int(getattr(st, "UPDATE_POLL_QUIET", 20) or 0)
    except Exception:
        return False
    if interval <= 0:
        return False
    with _watch_lock:
        if _watch["started"]:
            return False
        _watch["started"] = True
    threading.Thread(target=_watch_loop, args=(max(30, interval), max(0, quiet)),
                     name="tarkov2d-update-watchdog", daemon=True).start()
    return True


def _download_loop(url, version):
    dest = os.path.join(_base_dir(), "Tarkov2D.new.exe")

    def on_progress(done, total):
        with _watch_lock:
            if _watch.get("download"):
                _watch["download"]["done"] = done
                _watch["download"]["total"] = total

    ok = download(url, dest, on_progress)
    with _watch_lock:
        _watch["download"] = None
        if ok:
            _watch["ready"] = {"version": version, "path": dest}
        else:
            _watch["last_error"] = "下载失败"


def start_download():
    """后台下载已发现的新版本。返回 (是否已开始, 说明)。"""
    s = _snapshot()
    if s.get("installing"):
        return False, "正在安装"
    if s.get("ready"):
        return False, "已下载完成,按 F9 重启安装"
    if s.get("download"):
        return False, "正在下载"
    man = s.get("remote")
    if not man:
        return False, "没有可用更新"
    if not getattr(sys, "frozen", False):
        return False, "开发模式(python 运行):不下载,请用打包后的 EXE 验证"
    src = s.get("source") or ""
    base = src if src.startswith(("http://", "https://", "file://")) else ""
    url = _resolve_url(base, str(man.get("url", "")))
    if not url:
        return False, "更新清单缺少下载地址"
    version = str(man.get("version"))
    with _watch_lock:
        _watch["download"] = {"version": version, "done": 0, "total": 0}
    threading.Thread(target=_download_loop, args=(url, version),
                     name="tarkov2d-update-download", daemon=True).start()
    return True, "已开始下载"


def install_ready():
    """把已下载的文件交给批处理就地替换并重启。返回 (是否触发, 说明)。"""
    s = _snapshot()
    ready = s.get("ready")
    if not ready:
        return False, "还没有下载完成"
    if s.get("installing"):
        return False, "正在安装"
    exe = sys.executable if getattr(sys, "frozen", False) else None
    if not exe:
        return False, "开发模式不替换 EXE"
    _set(installing=True)
    try:
        launch_self_replace(ready["path"], exe)
    except Exception as e:
        _set(installing=False)
        return False, f"自动安装失败({e.__class__.__name__})"
    return True, f"正在重启并安装 v{ready.get('version')}"


def _hud_text(s):
    """把状态快照翻成一行提示文字 + 进度(0~1 或 None)。"""
    if s.get("installing"):
        return "正在安装更新…", None
    dl = s.get("download")
    if dl:
        total, done = dl.get("total") or 0, dl.get("done") or 0
        ratio = (done / total) if total else 0.0
        return f"正在下载 v{dl.get('version')}  {int(ratio * 100)}%", ratio
    ready = s.get("ready")
    if ready:
        return f"v{ready.get('version')} 已下载 · 按 F9 重启安装", 1.0
    man = s.get("remote")
    if man:
        return f"发现新版本 v{man.get('version')} · 按 F9 更新", None
    return "", None


def watchdog_tick(screen, game=None, hotkey="f9"):
    """主循环每帧调用:画实时更新提示条 + 收热键。

    返回 True 表示已经触发了就地替换,调用方应尽快退出进程(交给批处理重启)。
    """
    import pygame
    from settings import W, get_font

    s = _snapshot()
    if not (s.get("remote") or s.get("download") or s.get("ready") or s.get("installing")):
        return False

    # 第一次发现新版本:在藏身处弹一条 toast(局内只挂右上角提示条,不打断战斗)
    man = s.get("remote")
    if man and not s["notified"] and not s.get("download"):
        if game is not None:
            try:
                game.hideout.say(f"发现新版本 v{man.get('version')} —— 按 F9 立即更新",
                                 None, ttl=8.0)
            except Exception:
                pass
        _set(notified=True)

    # 热键(边沿触发:按住只算一次)
    try:
        code = getattr(pygame, "K_" + str(hotkey).upper(), None)
        down = bool(code is not None and pygame.key.get_pressed()[code])
    except Exception:
        down = False
    edge = down and not s["hk_down"]
    _set(hk_down=down)
    if edge:
        if s.get("ready"):
            ok, _msg = install_ready()
            if ok:
                return True
        elif man and not s.get("download"):
            start_download()

    # 提示条(右上角,FPS 下面)
    text, ratio = _hud_text(s)
    if not text:
        return False
    color = (140, 230, 150) if (s.get("ready") or s.get("installing")) else (255, 200, 90)
    try:
        font = get_font(15, bold=True)
        surf = font.render(text, True, color)
        pad = 7
        h = surf.get_height() + pad * 2 + (6 if ratio is not None else 0)
        w = surf.get_width() + pad * 2
        x, y = W - w - 12, 30
        box = pygame.Surface((w, h), pygame.SRCALPHA)
        box.fill((14, 16, 20, 210))
        screen.blit(box, (x, y))
        pygame.draw.rect(screen, color, (x, y, w, h), 1, border_radius=4)
        screen.blit(surf, (x + pad, y + pad))
        if ratio is not None:
            bx, by = x + pad, y + pad + surf.get_height() + 2
            pygame.draw.rect(screen, (52, 56, 64), (bx, by, w - pad * 2, 4))
            pygame.draw.rect(screen, color,
                             (bx, by, int((w - pad * 2) * max(0.0, min(1.0, ratio))), 4))
    except Exception:
        pass
    return False
