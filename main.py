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
"""
import asyncio
import os
import sys
import traceback


def write_run_version():
    """把当前版本写到存档目录,便于排查"现在跑的是哪一版"。"""
    try:
        import save as _save
        from settings import GAME_VERSION
        os.makedirs(_save.SAVE_DIR, exist_ok=True)
        with open(os.path.join(_save.SAVE_DIR, "last_run_version.txt"),
                  "w", encoding="utf-8") as f:
            f.write(GAME_VERSION + "\n")
    except Exception:
        pass


def _is_web():
    return sys.platform == "emscripten"


async def run_game():
    """异步主循环:每帧 await 一下,网页版(wasm)才能正常刷新。"""
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    # 手机模式:关闭 SDL 的"触摸合成鼠标"行为,避免和虚拟摇杆/按钮重复响应
    try:
        import save as _save_mod
        want_touch = "--touch" in sys.argv or (
            "--pc" not in sys.argv and _save_mod.load_data().touch)
        if want_touch:
            os.environ["SDL_TOUCH_MOUSE_EVENTS"] = "0"
    except Exception:
        pass

    import pygame

    # 中文输入法会拦截字母键(导致 WASD 失灵):
    # 线程级禁用 IME,须在创建窗口前调用(仅 Windows)
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.imm32.ImmDisableIME(0)
        except Exception:
            pass

    pygame.mixer.pre_init(44100, -16, 1, 512)
    pygame.init()

    import audio
    audio.init()

    from settings import W, H, FPS
    from game import Game

    on_android = bool(os.environ.get("ANDROID_ARGUMENT"))
    flags = pygame.SCALED | pygame.FULLSCREEN if (on_android or _is_web()) else 0
    screen = pygame.display.set_mode((W, H), flags)
    pygame.display.set_caption("Tarkov2D — 类塔科夫 2D 搜打撤")

    # 双保险:解除窗口 IME 上下文 + 关闭文本输入(仅 Windows)
    if sys.platform == "win32":
        try:
            import ctypes
            hwnd = pygame.display.get_wm_info().get("window")
            if hwnd:
                ctypes.windll.imm32.ImmAssociateContext(hwnd, 0)
        except Exception:
            pass
    try:
        pygame.key.stop_text_input()
    except Exception:
        pass

    write_run_version()

    # 启动时检查更新(--no-update 可跳过;网页/安卓上不检查,由包本身更新)
    if "--no-update" not in sys.argv and not _is_web() and not on_android:
        try:
            import updater
            if updater.run_startup_check(screen):
                pygame.quit()
                return       # 已触发自动更新,批处理会覆盖并重启
        except Exception:
            pass

    clock = pygame.time.Clock()
    game = Game(screen)
    # 命令行/平台覆盖手机模式
    if "--touch" in sys.argv:
        game.save.touch = True
    elif "--pc" in sys.argv:
        game.save.touch = False
    elif on_android or _is_web():
        game.save.touch = True      # 安卓 / 网页版默认手机模式(触屏 + 自动锁敌)

    try:
        while not game.quit:
            dt = min(clock.tick(FPS) / 1000.0, 0.05)
            events = pygame.event.get()
            game.update(dt, events)
            if game.quit:
                break
            game.draw(screen)
            pygame.display.flip()
            await asyncio.sleep(0)     # 让出控制权(网页版必需)
    finally:
        game.shutdown()


def main():
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
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        _write_crash_log()
        raise
