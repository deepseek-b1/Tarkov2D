# -*- coding: utf-8 -*-
"""Tarkov2D 帧耗时基准(无头,确定性)。

* 固定随机种子 -> 每次跑都是同一张图 / 同一批拾荒者与战利品
* 报告 MEDIAN / p95(平均值会被 GC 与 AI 尖峰带偏)
* update() 与 draw() 分开计时,并且按手机(触屏)模式测
* 用临时存档目录,不碰真实存档

用法:
    python tools/bench_frames.py [--profile] [--mode raid|assault|story]
"""
import cProfile
import io
import os
import pstats
import random
import statistics
import sys
import tempfile
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRATCH = os.path.join(tempfile.gettempdir(), "tarkov2d_bench_save")
SEED = 20261004

os.makedirs(SCRATCH, exist_ok=True)
os.environ["LOCALAPPDATA"] = SCRATCH
os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
sys.path.insert(0, PROJECT)

import pygame  # noqa: E402

pygame.mixer.pre_init(44100, -16, 1, 512)
pygame.init()
import audio  # noqa: E402
audio.init()

from settings import W, H  # noqa: E402
from game import Game  # noqa: E402
import save as save_mod  # noqa: E402

screen = pygame.display.set_mode((W, H))
DT = 1.0 / 120.0
PROFILE = "--profile" in sys.argv


def make_game(mode="raid", open_panel=None, combat=False, moving=False):
    random.seed(SEED)
    g = Game()
    g.save.touch = True
    g.save.seen_intro = True
    g.save.mode = mode
    if mode == "hideout":
        return g
    g.start_raid()
    r = g.raid
    if combat:
        p = r.player
        p.weapon = p.weapon or __import__("inventory").Item.weapon("ak74", mag=30)
        for i in range(6):
            r.add_particles(p.x + i * 8, p.y + i * 4, 12, (255, 140, 60))
        for s in r.scavs[:5]:
            s.x, s.y = p.x + random.randint(60, 260), p.y + random.randint(60, 260)
            s.hp = 0 if random.random() < 0.5 else s.hp
        r.shake = 3.0
        p.hurt_flash = 0.6
    if open_panel == "inv":
        r.inv_open = True
    elif open_panel == "loot":
        r.loot_target = next(c for c in r.containers if c.container.items)
    if moving:
        # 一直推着摇杆走:迷雾多边形每次移动 >=6px 都要重算(最贵的路径)
        r.touch.touches[0] = (100, 100)
        r.touch.stick_id = 0
        r.touch.stick_base = (200, 200)
        r.touch.stick_vec = (1.0, 0.35)
    return g


def measure_block(frames, warmup, **kw):
    g = make_game(**kw)
    for _ in range(warmup):
        g.update(DT, [])
        g.draw(screen)
    t0 = time.perf_counter()
    for _ in range(frames):
        g.update(DT, [])
        g.draw(screen)
    return (time.perf_counter() - t0) / frames * 1000.0


def bench_all(scenarios, frames=120, warmup=30, reps=4):
    """场景交叉重复,每个场景取多遍里的最小值。

    这台机器后台还有别的进程,墙钟计时有抖动,i5-4210U 也会热降频
    (同一段代码同一进程里前后能差一倍)。交叉重复 + 取最小值才拿得到
    「这一帧本身要多少 CPU」。
    """
    best = {label: 1e9 for label, _ in scenarios}
    for _rep in range(reps):
        for label, kw in scenarios:
            ms = measure_block(frames, warmup, **kw)
            if ms < best[label]:
                best[label] = ms
    for label, _ in scenarios:
        ms = best[label]
        print("  %-34s %6.2f ms/frame   ->  %5.1f fps"
              % (label, ms, 1000.0 / ms))
    return best


def burn(seconds=3.0):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        for _ in range(20000):
            pass


try:
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(
        ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080)   # HIGH
    print("process priority: HIGH")
except Exception as exc:
    print("could not raise priority: %s" % exc)

which = "raid"
if "--mode" in sys.argv:
    which = sys.argv[sys.argv.index("--mode") + 1]

print("python %s | pygame %s | seed=%d" % (sys.version.split()[0],
                                           pygame.version.ver, SEED))
print("project: %s" % PROJECT)
print("best of 4 interleaved reps, 120 frames each, dt=1/120")
burn()
print("=" * 78)
scenarios = [
    ("hideout", dict(mode="hideout")),
    ("%s: standing still" % which, dict(mode=which)),
    ("%s: moving (fog recompute)" % which, dict(mode=which, moving=True)),
    ("%s + inventory open" % which, dict(mode=which, open_panel="inv")),
    ("%s + loot window" % which, dict(mode=which, open_panel="loot")),
    ("%s + firefight (particles)" % which, dict(mode=which, combat=True)),
]
bench_all(scenarios)
print("=" * 78)

if PROFILE:
    g = make_game(mode=which, moving=True)
    for _ in range(60):
        g.update(DT, [])
        g.draw(screen)
    pr = cProfile.Profile()
    pr.enable()
    for _ in range(200):
        g.update(DT, [])
        g.draw(screen)
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats("tottime").print_stats(16)
    print(s.getvalue())
