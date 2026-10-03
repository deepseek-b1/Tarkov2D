# -*- coding: utf-8 -*-
"""地图:瓦片解析、碰撞、视线(DDA)、A*寻路、战利品箱、撤离区。"""
import heapq
import math
import random

import pygame

from settings import TILE, MW, MH, MAPS, CONTAINER_INFO, COL
from inventory import Container

WALL = "#"
TREE = "T"
WATER = "W"
SOLID = {WALL, TREE, WATER}     # 水域同样不可通行、挡视线
_LOOT_LETTER = {"C": "crate", "M": "med", "G": "gun", "V": "val"}
_SCAV_LETTER = {"p": "pistol", "g": "shotgun", "r": "ar", "m": "melee"}
_SPECIAL = ("S", "1", "2", "3", "X", "Y", "Z")


class LootContainer:
    def __init__(self, kind, cx, cy, container=None):
        name, w, h = CONTAINER_INFO[kind]
        self.kind = kind
        self.name = name
        self.container = container if container is not None else Container(w, h)
        self.rect = pygame.Rect(0, 0, TILE, TILE)
        self.rect.center = (cx, cy)
        self.searched = False   # 仅用于地图预渲染标记(已被搜过)

    @property
    def pos(self):
        return self.rect.center

    def is_empty(self):
        return not self.container.items


class GameMap:
    def __init__(self, map_key="border"):
        if map_key not in MAPS:
            map_key = "border"
        self.map_key = map_key
        self.map_name = MAPS[map_key]["name"]
        extracts_def = MAPS[map_key]["extracts"]
        rows = [r.ljust(MW, ".")[:MW] for r in MAPS[map_key]["rows"]]
        self.tiles = []            # 每格字符:'#'墙 'T'树 'W'水 '.'野外 'B'室内
        self.solid = []            # bool:阻挡移动
        self.block_sight = []      # bool:阻挡视线
        self.extracts = []         # [(name, Rect_world)]
        self.loot = []             # [LootContainer]
        self.scav_spawns = []      # [(kind, (x, y))]
        self.boss_spawn = None     # (x, y) 像素坐标(头目)
        self.guard_spawns = []     # [(x, y)] 头目手下
        self.author_spawn = None   # (x, y) 隐藏头目「作者」
        self.spawn = None          # (x, y) 像素坐标

        for ty, row in enumerate(rows):
            trow, srow, brow = [], [], []
            for tx, ch in enumerate(row):
                if ch in _LOOT_LETTER or ch in _SCAV_LETTER or ch in _SPECIAL:
                    # 看邻居推断地板类型,避免室内出现草地色块
                    nb = [rows[ny][nx] for ny, nx in
                          ((ty - 1, tx), (ty + 1, tx), (ty, tx - 1), (ty, tx + 1))
                          if 0 <= ny < MH and 0 <= nx < MW]
                    ch = "B" if "B" in nb else "."
                trow.append(ch)
                srow.append(ch in SOLID)
                brow.append(ch in SOLID)   # 树、墙、水都挡视线
            self.tiles.append(trow)
            self.solid.append(srow)
            self.block_sight.append(brow)

        for ty, row in enumerate(rows):
            for tx, ch in enumerate(row):
                cx, cy = tx * TILE + TILE // 2, ty * TILE + TILE // 2
                if ch in _LOOT_LETTER:
                    self.loot.append(LootContainer(_LOOT_LETTER[ch], cx, cy))
                elif ch in _SCAV_LETTER:
                    self.scav_spawns.append((_SCAV_LETTER[ch], (cx, cy)))
                elif ch == "X":
                    self.boss_spawn = (cx, cy)
                elif ch == "Y":
                    self.guard_spawns.append((cx, cy))
                elif ch == "Z":
                    self.author_spawn = (cx, cy)
                elif ch == "S":
                    self.spawn = (cx, cy)
                elif ch in ("1", "2", "3"):
                    r = pygame.Rect(0, 0, TILE * 3, TILE * 3)
                    r.center = (cx, cy)
                    self.extracts.append((extracts_def[ch], r))

        self.px_w, self.px_h = MW * TILE, MH * TILE

    # ---- 碰撞 ----
    def tile_solid(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= MW or ty >= MH:
            return True
        return self.solid[ty][tx]

    def collides(self, x, y, r):
        """圆形实体是否与实心格重叠。"""
        x0 = int((x - r) // TILE); x1 = int((x + r) // TILE)
        y0 = int((y - r) // TILE); y1 = int((y + r) // TILE)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if not self.tile_solid(tx, ty):
                    continue
                rx, ry = tx * TILE, ty * TILE
                nx = max(rx, min(x, rx + TILE))
                ny = max(ry, min(y, ry + TILE))
                if (x - nx) ** 2 + (y - ny) ** 2 < r * r:
                    return True
        return False

    def move_circle(self, pos, dx, dy, r):
        """分轴移动实现贴墙滑行。pos: (x, y)。"""
        x, y = pos
        if dx:
            nx = x + dx
            if not self.collides(nx, y, r):
                x = nx
        if dy:
            ny = y + dy
            if not self.collides(x, ny, r):
                y = ny
        return x, y

    # ---- 视线 ----
    def los_clear(self, x1, y1, x2, y2):
        dist = math.hypot(x2 - x1, y2 - y1)
        if dist < 1:
            return True
        steps = int(dist // 10) + 1
        dx = (x2 - x1) / dist
        dy = (y2 - y1) / dist
        for i in range(1, steps):
            t = i * 10.0
            tx = int((x1 + dx * t) // TILE)
            ty = int((y1 + dy * t) // TILE)
            if tx < 0 or ty < 0 or tx >= MW or ty >= MH:
                return False
            if self.block_sight[ty][tx]:
                return False
        return True

    def visibility_polygon(self, x, y, radius, n=140):
        """玩家视野多边形(用于战争迷雾)。"""
        pts = []
        step = math.tau / n
        for i in range(n):
            a = i * step
            dx, dy = math.cos(a), math.sin(a)
            d = 0.0
            while d < radius:
                d += 12.0
                tx = int((x + dx * d) // TILE)
                ty = int((y + dy * d) // TILE)
                if tx < 0 or ty < 0 or tx >= MW or ty >= MH or self.block_sight[ty][tx]:
                    break
            pts.append((x + dx * min(d, radius), y + dy * min(d, radius)))
        return pts

    # ---- A* 寻路(4向,格坐标) ----
    def astar(self, start, goal):
        sx, sy = start
        gx, gy = goal
        if self.tile_solid(gx, gy):
            return None
        openq = [(0.0, sx, sy)]
        came = {(sx, sy): None}
        cost = {(sx, sy): 0.0}
        while openq:
            _, cx, cy = heapq.heappop(openq)
            if (cx, cy) == (gx, gy):
                path = []
                cur = (cx, cy)
                while cur is not None:
                    path.append(cur)
                    cur = came[cur]
                path.reverse()
                return path
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = cx + dx, cy + dy
                if self.tile_solid(nx, ny):
                    continue
                nc = cost[(cx, cy)] + 1.0
                if (nx, ny) not in cost or nc < cost[(nx, ny)]:
                    cost[(nx, ny)] = nc
                    pri = nc + abs(nx - gx) + abs(ny - gy)
                    heapq.heappush(openq, (pri, nx, ny))
                    came[(nx, ny)] = (cx, cy)
            if len(came) > 6000:
                break
        return None

    def walkable_near(self, tx, ty, tries=12):
        """在 tx,ty 附近找一个可走格。"""
        for _ in range(tries):
            nx = tx + random.randint(-3, 3)
            ny = ty + random.randint(-3, 3)
            if not self.tile_solid(nx, ny):
                return nx, ny
        return None

    # ---- 预渲染整张地图表面 ----
    def prerender(self):
        surf = pygame.Surface((self.px_w, self.px_h))
        rnd = random.Random(7)
        for ty in range(MH):
            for tx in range(MW):
                ch = self.tiles[ty][tx]
                x, y = tx * TILE, ty * TILE
                if ch == WATER:
                    # 海水:深蓝底 + 波纹
                    pygame.draw.rect(surf, (28, 46, 74), (x, y, TILE, TILE))
                    wave = (44, 66, 100) if (tx + ty) % 2 == 0 else (38, 58, 90)
                    pygame.draw.line(surf, wave, (x + 3, y + 9), (x + TILE - 5, y + 9), 2)
                    pygame.draw.line(surf, wave, (x + 7, y + 21), (x + TILE - 3, y + 21), 2)
                    continue
                if ch == "B":
                    base = COL["indoor"] if (tx + ty) % 2 == 0 else COL["indoor2"]
                else:
                    base = COL["ground"] if (tx + ty) % 2 == 0 else COL["ground2"]
                pygame.draw.rect(surf, base, (x, y, TILE, TILE))
                # 地面杂点
                if rnd.random() < 0.22 and ch != WALL:
                    px = x + rnd.randint(2, TILE - 4)
                    py = y + rnd.randint(2, TILE - 4)
                    c = tuple(max(0, v - 14) for v in base)
                    surf.fill(c, (px, py, 2, 2))
        # 墙/树画在地面之上
        for ty in range(MH):
            for tx in range(MW):
                ch = self.tiles[ty][tx]
                x, y = tx * TILE, ty * TILE
                if ch == WALL:
                    pygame.draw.rect(surf, COL["wall"], (x, y, TILE, TILE))
                    pygame.draw.rect(surf, COL["wall_edge"], (x, y, TILE, 2))
                    pygame.draw.rect(surf, (30, 32, 38), (x, y + TILE - 3, TILE, 3))
                elif ch == TREE:
                    pygame.draw.circle(surf, COL["tree"], (x + TILE // 2, y + TILE // 2), TILE // 2 - 2)
                    pygame.draw.circle(surf, (34, 70, 40),
                                       (x + TILE // 2, y + TILE // 2), TILE // 2 - 8)
        # 战利品容器
        for lc in self.loot:
            r = lc.rect
            col = {"crate": COL["crate"], "med": COL["med"],
                   "gun": COL["gun"], "val": COL["safe"]}[lc.kind]
            pygame.draw.rect(surf, col, r)
            pygame.draw.rect(surf, (25, 25, 28), r, 2)
            if lc.kind == "med":
                pygame.draw.rect(surf, (210, 60, 60),
                                 (r.centerx - 8, r.centery - 3, 16, 6))
                pygame.draw.rect(surf, (210, 60, 60),
                                 (r.centerx - 3, r.centery - 8, 6, 16))
            elif lc.kind == "val":
                pygame.draw.circle(surf, (40, 40, 46), r.center, 6)
                pygame.draw.circle(surf, (210, 170, 60), r.center, 3)
            else:
                pygame.draw.line(surf, (25, 25, 28),
                                 (r.x + 3, r.y + 3), (r.right - 3, r.bottom - 3), 2)
        # 撤离区地面标记
        for name, r in self.extracts:
            pygame.draw.rect(surf, (30, 90, 84), r.inflate(0, 0), border_radius=6)
            pygame.draw.rect(surf, COL["extract"], r, 3, border_radius=6)
            f = None
            try:
                from settings import get_font
                f = get_font(15, bold=True)
            except Exception:
                pass
            if f:
                t = f.render(name, True, COL["extract"])
                surf.blit(t, t.get_rect(center=(r.centerx, r.y - 10)))
        return surf
