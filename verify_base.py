# -*- coding: utf-8 -*-
"""临时校验:大本营地图结构(守军/队友/目标/撤离点可达)。用完即删。"""
import os
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
pygame.init()
pygame.display.set_mode((1, 1))

from settings import TILE, ASSAULT_ENEMIES, ASSAULT_ALLIES, OBJECTIVES
from world import GameMap

m = GameMap("base")
print("scav spawns:", len(m.scav_spawns))
print("ally spawns:", len(m.ally_spawns))
print("objectives :", m.objectives)
print("extracts   :", [(n, r.center) for n, r in m.extracts])
print("loot       :", len(m.loot))
print("player spawn:", m.spawn)

assert len(m.scav_spawns) >= ASSAULT_ENEMIES, len(m.scav_spawns)
assert len(m.ally_spawns) >= ASSAULT_ALLIES, len(m.ally_spawns)
assert len(m.objectives) == len(OBJECTIVES), m.objectives
assert len(m.extracts) == 2

sx, sy = m.spawn
st = (int(sx // TILE), int(sy // TILE))
assert not m.tile_solid(*st), "出生点在墙里"

# 所有关键点可达
for name, (ox, oy) in m.objectives:
    t = (int(ox // TILE), int(oy // TILE))
    assert not m.tile_solid(*t), f"目标在墙里 {name}"
    assert m.astar(st, t) is not None, f"目标不可达 {name}"
for i, (n, r) in enumerate(m.extracts):
    t = (int(r.centerx // TILE), int(r.centery // TILE))
    assert m.astar(st, t) is not None, f"撤离点不可达 {n}"
for kind, (x, y) in m.scav_spawns:
    t = (int(x // TILE), int(y // TILE))
    assert not m.tile_solid(*t), f"守军在墙里 {kind} {t}"
    assert m.astar(st, t) is not None, f"守军不可达 {kind} {t}"
for (x, y) in m.ally_spawns:
    t = (int(x // TILE), int(y // TILE))
    assert not m.tile_solid(*t), f"队友在墙里 {t}"
    assert m.astar(st, t) is not None, f"队友不可达 {t}"

# 坐标不能重叠(守军/队友/目标/物资/撤离点各占一格)
seen = {}
for kind, (x, y) in m.scav_spawns:
    seen.setdefault((int(x // TILE), int(y // TILE)), []).append("scav:" + kind)
for (x, y) in m.ally_spawns:
    seen.setdefault((int(x // TILE), int(y // TILE)), []).append("ally")
for name, (x, y) in m.objectives:
    seen.setdefault((int(x // TILE), int(y // TILE)), []).append("obj:" + name)
for lc in m.loot:
    t = (lc.rect.centerx // TILE, lc.rect.centery // TILE)
    seen.setdefault(t, []).append("loot:" + lc.kind)
for n, r in m.extracts:
    seen.setdefault((r.centerx // TILE, r.centery // TILE), []).append("extract")
seen.setdefault((int(sx // TILE), int(sy // TILE)), []).append("spawn")
dups = {k: v for k, v in seen.items() if len(v) > 1}
assert not dups, f"标记重叠: {dups}"

# 守军在要塞内/外的分布(粗略:y<=36 为要塞内)
inside = sum(1 for _k, (x, y) in m.scav_spawns if y // TILE <= 36)
print(f"要塞内守军 {inside} / 要塞外 {len(m.scav_spawns) - inside}")
print("OK")
