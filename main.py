# -*- coding: utf-8 -*-
"""Tarkov2D 启动入口(电脑 / 安卓 / 网页版共用一套代码)。

用法:
    python main.py              正常启动(会先检查更新)
    python main.py --touch      手机(触屏)模式
    python main.py --pc         强制电脑模式
    python main.py --no-update  跳过更新检查
    python main.py --version    输出版本号
    python main.py --selftest   无头自检(不弹窗)

网页版(手机浏览器):  pygbag --build .

------------------------------------------------------------------------
本版追加的"自证清白"设施(玩家反馈"一登录就闪退",但没有任何日志):
  * startup.log —— 启动每一步都落盘。就算程序被硬崩溃干掉,也能看出死在哪一步。
  * fault.log   —— faulthandler 抓 C 层崩溃(访问违例等),Python 的 try/except
                   抓不到这类问题,只有它能留下堆栈。
  * 开窗口带降级链 —— 1280x720 开不出来就依次试 SCALED / 按桌面分辨率缩小的尺寸,
                   每一步都记日志,而不是直接闪退。
  * 每个退出路径都写日志(退出原因),区分"玩家自己点了退出"和"崩了"。
所有日志都在存档目录(%LOCALAPPDATA%\\Tarkov2D),和 crash.log 放一起。
"""
import asyncio
import os
import sys
import time
import traceback

_FAULT_STREAM = None


_LOG_DIR = None


def _log_dir():
    """日志目录:必须是**真的能写**的目录。

    首选和存档目录一致(save.SAVE_DIR,它自己已经带"不可写就退到便携目录"的
    回退);万一连 save 都还没能导入,就按 LOCALAPPDATA -> exe 旁边 -> 当前目录
    逐个试。日志写不进去的话,"闪退"就永远查不出来了。
    """
    global _LOG_DIR
    if _LOG_DIR:
        return _LOG_DIR
    cands = []
    try:
        import save as _s
        cands.append(_s.SAVE_DIR)
    except Exception:
        pass
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    cands.append(os.path.join(base, "Tarkov2D"))
    try:
        here = os.path.dirname(os.path.abspath(
            sys.executable if getattr(sys, "frozen", False) else __file__))
    except Exception:
        here = os.getcwd()
    cands += [os.path.join(here, "Tarkov2D-save"), os.getcwd()]
    for d in cands:
        try:
            os.makedirs(d, exist_ok=True)
            probe = os.path.join(d, ".t2d_log_test")
            with open(probe, "w", encoding="utf-8") as f:
                f.write("x")
            os.remove(probe)
            _LOG_DIR = d
            return d
        except Exception:
            continue
    _LOG_DIR = os.getcwd()
    return _LOG_DIR


def _trace(msg):
    """启动追踪:只追加写,绝不抛异常。"""
    line = f"{time.strftime('%m-%d %H:%M:%S')}  {msg}"
    try:
        print("[trace] " + line, flush=True)
    except Exception:
        pass
    try:
        with open(os.path.join(_log_dir(), "startup.log"), "a",
                  encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _setup_faulthandler():
    """让 C 层崩溃(访问违例/栈溢出)也留下堆栈 —— 这是"闪退"唯一的取证手段。"""
    global _FAULT_STREAM
    try:
        import faulthandler
        _FAULT_STREAM = open(os.path.join(_log_dir(), "fault.log"), "a",
                             encoding="utf-8", buffering=1)
        _FAULT_STREAM.write(f"\n===== run {time.strftime('%Y-%m-%d %H:%M:%S')} "
                            f"argv={sys.argv[1:]} =====\n")
        _FAULT_STREAM.flush()
        faulthandler.enable(file=_FAULT_STREAM, all_threads=True)
        _trace("faulthandler enabled -> fault.log")
    except Exception:
        _trace("faulthandler setup failed:\n" + traceback.format_exc())


def _hook_exceptions():
    """未捕获异常的兜底(正常路径下 main 里已经处理,这里再保一层)。"""
    def _hook(exc_type, exc, tb):
        _trace("!!! sys.excepthook !!!\n" + "".join(
            traceback.format_exception(exc_type, exc, tb)))
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass
    try:
        sys.excepthook = _hook
    except Exception:
        pass


def write_run_version():
    """把当前版本(和登录的账号)写到存档目录,便于排查"现在跑的是哪一版"。"""
    try:
        import save as _save
        from settings import GAME_VERSION
        os.makedirs(_save.SAVE_DIR, exist_ok=True)
        with open(os.path.join(_save.SAVE_DIR, "last_run_version.txt"),
                  "w", encoding="utf-8") as f:
            f.write(GAME_VERSION + "\n")
            if getattr(_save, "PROFILE", None):
                f.write(f"account: {_save.PROFILE}\n")
        _trace(f"write_run_version ok (profile={getattr(_save, 'PROFILE', None)})")
    except Exception:
        # 这一步失败不能拖垮游戏,但一定要留痕(以前是静默 pass,查不出来)
        _trace("write_run_version FAILED:\n" + traceback.format_exc())


def _is_web():
    return sys.platform == "emscripten"


def _open_window(pygame, W, H):
    """开窗口:失败就一级级降级。返回 surface(找不到任何可用尺寸才抛)。"""
    tries = [
        (f"标准窗口 {W}x{H}", (W, H), 0),
        (f"SCALED {W}x{H}", (W, H), pygame.SCALED),
    ]
    try:
        info = pygame.display.Info()
        dw, dh = int(info.current_w), int(info.current_h)
        _trace(f"desktop = {dw}x{dh}")
        if dw > 0 and dh > 0:
            for sc in (0.9, 0.8, 0.7, 0.6):
                w, h = max(800, int(dw * sc)), max(450, int(dh * sc))
                if (w, h) not in [(s[0], s[1]) for _l, s, _f in tries]:
                    tries.append((f"降级 {w}x{h}", (w, h), 0))
    except Exception:
        _trace("pygame.display.Info() failed:\n" + traceback.format_exc())
    last = None
    for label, size, flags in tries:
        try:
            scr = pygame.display.set_mode(size, flags)
            _trace(f"set_mode OK via {label} (flags={flags})")
            return scr
        except Exception as exc:
            last = exc
            _trace(f"set_mode FAILED via {label}: {exc.__class__.__name__}: {exc}")
    raise last if last else RuntimeError("set_mode failed")


async def run_game():
    """异步主循环:每帧 await 一下,网页版(wasm)才能正常刷新。"""
    _trace("=== run_game start ===")
    _trace(f"frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")
    _trace(f"cwd={os.getcwd()} argv={sys.argv}")
    _trace(f"python={sys.version.split()[0]}  pid={os.getpid()}")
    _trace(f"localappdata={os.environ.get('LOCALAPPDATA')}")
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # 手机模式:关闭 SDL 的"触摸合成鼠标"行为,避免和虚拟摇杆/按钮重复响应
    # (界面点击由 game.synth_mouse_events 按需合成 FINGER 的镜像)
    try:
        import save as _save_mod
        _trace("import save ok")
        sd_boot = _save_mod.load_data()
        _trace(f"boot load_data ok (touch={getattr(sd_boot, 'touch', None)})")
        want_touch = "--touch" in sys.argv or (
            "--pc" not in sys.argv and sd_boot.touch)
        if want_touch:
            os.environ["SDL_TOUCH_MOUSE_EVENTS"] = "0"
        # 全屏缩放滤镜(SCALED 把 720p 拉到全屏时的采样方式;须在 set_mode 前设好):
        # linear=柔和(双线性,默认) / nearest=锐利(最近邻,可能有锯齿)
        os.environ.setdefault(
            "SDL_RENDER_SCALE_QUALITY",
            "0" if sd_boot.scale_filter == "nearest" else "1")
        _trace(f"touch={want_touch} scale_filter={sd_boot.scale_filter}")
    except Exception:
        _trace("boot save/env step failed:\n" + traceback.format_exc())

    _trace("importing pygame ...")
    import pygame
    _trace(f"pygame {pygame.version.ver} / SDL {pygame.version.SDL}")

    # 中文输入法会拦截字母键(导致 WASD 失灵):
    # 线程级禁用 IME,须在创建窗口前调用(仅 Windows)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.imm32.ImmDisableIME(0)
            _trace("ImmDisableIME ok")
        except Exception:
            _trace("ImmDisableIME failed:\n" + traceback.format_exc())

    try:
        _trace("pygame.mixer.pre_init ...")
        pygame.mixer.pre_init(44100, -16, 1, 512)
        _trace("pygame.init ...")
        pygame.init()
        _trace("pygame.init ok")
    except Exception:
        _trace("pygame init failed:\n" + traceback.format_exc())
        try:
            pygame.display.init()
            _trace("display.init fallback ok")
        except Exception:
            _trace("display.init fallback FAILED:\n" + traceback.format_exc())

    import audio
    _trace("import audio ok")
    audio.init()
    _trace(f"audio.init done (enabled={getattr(audio, '_enabled', None)})")

    from settings import W, H
    from game import Game
    _trace(f"imports ok (W={W} H={H})")

    on_android = bool(os.environ.get("ANDROID_ARGUMENT"))
    flags = pygame.SCALED | pygame.FULLSCREEN if (on_android or _is_web()) else 0
    screen = _open_window(pygame, W, H) if flags == 0 else \
        pygame.display.set_mode((W, H), flags)
    try:
        pygame.display.set_caption("Tarkov2D — 类塔科夫 2D 搜打撤")
    except Exception:
        pass

    # 字体预热:pygame 每建一个 Font 都要把字体文件重新解析一遍,而游戏用到
    # 15 种字号 × 常规/粗体。不预热的话这些开销会落在"第一次用到该字号"的那
    # 一帧上(进战局第一帧、以及打到一半某个新字号第一次出现时),每次重启
    # 进程都要重来 —— 表现就是"更新完之后莫名其妙掉帧"。
    # 字体已经裁剪过(tools/build_font_subset.py),现在全部预热只要几十毫秒。
    try:
        import settings as _settings
        _settings.warm_fonts()
        _trace("warm_fonts ok")
    except Exception:
        _trace("warm_fonts failed:\n" + traceback.format_exc())

    # 双保险:解除窗口 IME 上下文 + 关闭文本输入(仅 Windows)
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = pygame.display.get_wm_info().get("window")
            if hwnd:
                ctypes.windll.imm32.ImmAssociateContext(hwnd, 0)
            _trace(f"ImmAssociateContext ok (hwnd={hwnd})")
        except Exception:
            _trace("ImmAssociateContext failed:\n" + traceback.format_exc())
    try:
        pygame.key.stop_text_input()
    except Exception:
        pass

    _trace("write_run_version (登录前) ...")
    write_run_version()

    # 启动时检查更新(--no-update 可跳过;网页/安卓上不检查,由包本身更新)
    if "--no-update" not in sys.argv and not _is_web() and not on_android:
        try:
            _trace("updater.run_startup_check ...")
            import updater
            if updater.run_startup_check(screen):
                _trace("退出原因: 触发了自动更新(进程交给批处理替换后重启)")
                pygame.quit()
                return       # 已触发自动更新,批处理会覆盖并重启
            _trace("updater done (无更新)")
        except Exception:
            _trace("updater failed:\n" + traceback.format_exc())

    # 账号登录:一个「名字 + 密码」= 一份独立存档(accounts.py)。
    # 藏身处设置页的「切换账号」会回到这里重新登录,所以外面套一层循环。
    import login as login_mod
    _trace("进入登录循环 ...")
    while True:
        _trace("显示登录界面")
        entered, migrated = await login_mod.run_login(screen)
        _trace(f"登录界面返回 entered={entered} migrated={migrated}")
        if not entered:
            _trace("退出原因: 玩家在登录界面按了「退出」(不是崩溃)")
            pygame.quit()
            return              # 玩家在登录界面选择了退出
        _trace("登录成功,准备进游戏 ...")
        write_run_version()
        clock = pygame.time.Clock()
        _trace("构造 Game(screen) ...")
        game = Game(screen)
        _trace("Game() 构造完成")
        if migrated:
            game.hideout.say("原来那份存档已并进这个账号 —— 进度、仓库、钱都在",
                             None, ttl=9.0)
        # 命令行/平台覆盖手机模式
        if "--touch" in sys.argv:
            game.save.touch = True
        elif "--pc" in sys.argv:
            game.save.touch = False
        elif on_android or _is_web():
            game.save.touch = True      # 安卓 / 网页版默认手机模式(触屏 + 自动锁敌)

        try:
            _trace("进入主循环")
            n = 0
            while not game.quit:
                # 帧率上限从存档读(设置页可改;0 = 不锁)
                cap = int(getattr(game.save, "fps_cap", 0) or 0)
                dt = min(clock.tick(cap) / 1000.0, 0.05)
                events = pygame.event.get()
                game.update(dt, events)
                if game.quit:
                    break
                game.draw(screen)
                if getattr(game.save, "show_fps", True):
                    from settings import get_font
                    fps = clock.get_fps()
                    col = ((110, 220, 120) if fps >= 110 else
                           (240, 200, 90) if fps >= 55 else (240, 90, 80))
                    t = get_font(15, bold=True).render(f"{fps:.0f} FPS", True, col)
                    screen.blit(t, (W - t.get_width() - 12, 8))
                pygame.display.flip()
                n += 1
                if n % 300 == 0:
                    _trace(f"主循环 第 {n} 帧正常 view="
                           f"{getattr(game.hideout, 'view', None)!r}")
                await asyncio.sleep(0)     # 让出控制权(网页版必需)
            _trace(f"退出原因: game.quit=True(正常结束),共 {n} 帧")
        finally:
            # 切账号时保留窗口(pygame.quit 会把显示表面一起销毁)
            try:
                game.shutdown(keep_window=game.switch_account)
            except Exception:
                _trace("shutdown failed:\n" + traceback.format_exc())
        if not game.switch_account:
            break
        _trace("切换账号:回到登录界面")



def _apply_safe_mode():
    """--safe:闪退时的保命开关 —— 软渲染 + 静音 + 不检查更新 + 只有单发窗口。

    显卡驱动 / 音频驱动是"硬崩溃"(Python 抓不到的那种闪退)最常见的两个来源,
    这个开关把它们都换成最保守的路径,用来判断闪退到底是不是它们引起的。
    """
    if "--safe" not in sys.argv:
        return False
    os.environ["SDL_RENDER_DRIVER"] = "software"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    if "--no-update" not in sys.argv:
        sys.argv.append("--no-update")
    _trace("安全模式: 软件渲染 + 静音 + 跳过更新检查")
    return True


def main():
    _apply_safe_mode()
    if "--selftest" in sys.argv:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
        os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import selftest
        ok = selftest.run()
        sys.exit(0 if ok else 1)

    if "--version" in sys.argv:
        from settings import GAME_VERSION
        write_run_version()
        try:
            with open(os.path.abspath("version_info.txt"), "w", encoding="utf-8") as f:
                f.write(f"Tarkov2D {GAME_VERSION}\n")
        except Exception:
            pass
        print(f"Tarkov2D {GAME_VERSION}")
        return

    asyncio.run(run_game())



def _write_crash_log():
    try:
        import save as _save
        os.makedirs(_save.SAVE_DIR, exist_ok=True)
        path = os.path.join(_save.SAVE_DIR, "crash.log")
        with open(path, "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        _trace("crash.log 已写入")
    except Exception:
        pass


if __name__ == "__main__":
    _trace("=== 进程启动 ===")
    _hook_exceptions()
    _setup_faulthandler()
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        _trace("!!! 未捕获异常 !!!\n" + traceback.format_exc())
        _write_crash_log()
        raise
    finally:
        _trace("=== 进程退出 ===")
