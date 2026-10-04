# -*- coding: utf-8 -*-
"""临时:突袭模式 50 守军的性能热点分析。用完即删。"""
import os
import time
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
pygame.init()

import random
random.seed(5)
import tempfile
import save as save_mod
save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="assault_prof_")
save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")

from settings import W, H
from game import Game
import world

# 统计 A* 调用
A = {"n": 0, "t": 0.0}
_orig = world.GameMap.astar


def counted(self, start, goal):
    t0 = time.perf_counter()
    r = _orig(self, start, goal)
    A["t"] += time.perf_counter() - t0
    A["n"] += 1
    return r


world.GameMap.astar = counted

screen = pygame.display.set_mode((W, H))
g = Game()
g.save = save_mod.reset_data()
g.save.mode = "assault"
g.save.seen_intro = True
g.start_raid()
r = g.raid
for s in r.scavs:
    s.state = "chase"
    s.alert = (r.player.x, r.player.y)

frames = 120
# update 计时
t0 = time.perf_counter()
for i in range(frames):
    if i % 30 == 0:
        for s in r.scavs:
            s.state = "chase"
            s.alert = (r.player.x, r.player.y)
    r.update(1 / 60, [])
t_upd = time.perf_counter() - t0
print(f"update: {t_upd / frames * 1000:.2f} ms/帧   A* 调用 {A['n']} 次 "
      f"共 {A['t'] * 1000:.0f} ms (单次 {A['t'] / max(1, A['n']) * 1000:.2f} ms)")

A["n"] = 0; A["t"] = 0.0
t0 = time.perf_counter()
for _ in range(frames):
    g.draw(screen)
t_draw = time.perf_counter() - t0
print(f"draw:   {t_draw / frames * 1000:.2f} ms/帧   A* 调用 {A['n']} 次")

# 只统计 AI 部分:scavs / allies
A["n"] = 0; A["t"] = 0.0
t0 = time.perf_counter()
for _ in range(frames):
    for s in r.scavs:
        s.update(r, 1 / 60)
t_scav = time.perf_counter() - t0
print(f"50x scav.update: {t_scav / frames * 1000:.2f} ms/帧  A* {A['n']} 次 "
      f"共 {A['t'] * 1000:.0f} ms")

A["n"] = 0; A["t"] = 0.0
t0 = time.perf_counter()
for _ in range(frames):
    for a in r.allies:
        a.update(r, 1 / 60)
t_ally = time.perf_counter() - t0
print(f"10x ally.update: {t_ally / frames * 1000:.2f} ms/帧  A* {A['n']} 次 "
      f"共 {A['t'] * 1000:.0f} ms")
