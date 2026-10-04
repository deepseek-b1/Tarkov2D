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
_SPECIAL = ("S", "1", "2", "3", "4", "5", "6", "7",
            "X", "Y", "Z", "H", "T", "c",
            "O", "P", "Q", "o", "q", "A", "N", "K")

_INF = float("inf")
_RAY_DIRS = {}


def _ray_dirs(n):
    """按角度预生成射线方向:每帧 140 次 cos/sin 是白花的。"""
    dirs = _RAY_DIRS.get(n)
    if dirs is None:
        step = math.tau / n
        dirs = tuple((math.cos(i * step), math.sin(i * step)) for i in range(n))
        _RAY_DIRS[n] = dirs
    return dirs



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
        raw = MAPS[map_key]["rows"]
        # 每张地图用自己的尺寸(剧情模式的城区图比老图大),不再写死全局 MW/MH
        self.mw = max([len(r) for r in raw] + [MW])
        self.mh = max(len(raw), MH)
        rows = [r.ljust(self.mw, ".")[:self.mw] for r in raw]
        while len(rows) < self.mh:            # 补足行数,保证瓦片表尺寸一致
            rows.append("." * self.mw)
        self.tiles = []            # 每格字符:'#'墙 'T'树 'W'水 '.'野外 'B'室内
        self.solid = []            # bool:阻挡移动
        self.block_sight = []      # bool:阻挡视线
        self.extracts = []         # [(name, Rect_world)]
        self.loot = []             # [LootContainer]
        self.scav_spawns = []      # [(kind, (x, y))]
        self.boss_spawn = None     # (x, y) 像素坐标(头目)
        self.guard_spawns = []     # [(x, y)] 头目手下
        self.author_spawn = None   # (x, y) 隐藏头目「作者」
        self.hostage_spawns = []   # [(x, y)] 人质(人质模式)
        self.ally_spawns = []      # [(x, y)] 队友出生点
        self.objectives = []       # [(名称, (x, y))] 突袭模式要摧毁的敌方设施
        self.friend_structures = []  # [(名称, (x, y))] 我方前沿设施(指挥所/通讯室)
        self.supplies = []         # [(名称, (x, y))] 我方补给点(弹药库)
        self.story_npcs = []       # [(x, y)] 剧情 NPC 站位(身份由 story.py 按坐标认领)
        self.story_points = []     # [(x, y)] 剧情交互点(搜索/下载/取得/炸药…)同理由坐标认领
        self.corners = []          # [(x, y)] 拐角死角(敌人偏好蹲守)
        self.spawn = None          # (x, y) 像素坐标

        for ty, row in enumerate(rows):
            trow, srow, brow = [], [], []
            for tx, ch in enumerate(row):
                if ch in _LOOT_LETTER or ch in _SCAV_LETTER or ch in _SPECIAL:
                    # 看邻居推断地板类型,避免室内出现草地色块
                    nb = [rows[ny][nx] for ny, nx in
                          ((ty - 1, tx), (ty + 1, tx), (ty, tx - 1), (ty, tx + 1))
                          if 0 <= ny < self.mh and 0 <= nx < self.mw]
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
                elif ch == "H":
                    self.hostage_spawns.append((cx, cy))
                elif ch == "T":
                    self.ally_spawns.append((cx, cy))
                elif ch == "c":
                    self.corners.append((cx, cy))
                elif ch in ("O", "P", "Q"):
                    from settings import OBJECTIVES, STRUCT_ROLE
                    self.objectives.append((OBJECTIVES[ch], (cx, cy), STRUCT_ROLE[ch]))
                elif ch in ("o", "q"):
                    from settings import ALLY_STRUCTURES, STRUCT_ROLE
                    self.friend_structures.append(
                        (ALLY_STRUCTURES[ch], (cx, cy), STRUCT_ROLE[ch]))
                elif ch == "A":
                    from settings import ALLY_SUPPLY
                    self.supplies.append((ALLY_SUPPLY[ch], (cx, cy)))
                elif ch == "N":
                    self.story_npcs.append((cx, cy))
                elif ch == "K":
                    self.story_points.append((cx, cy))
                elif ch == "S":
                    self.spawn = (cx, cy)
                elif ch in ("1", "2", "3", "4", "5", "6", "7"):
                    r = pygame.Rect(0, 0, TILE * 3, TILE * 3)
                    r.center = (cx, cy)
                    self.extracts.append((extracts_def[ch], r))

        self.px_w, self.px_h = self.mw * TILE, self.mh * TILE

    # ---- 碰撞 ----
    def tile_solid(self, tx, ty):
        if tx < 0 or ty < 0 or tx >= self.mw or ty >= self.mh:
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
        """两点间是否无遮挡:沿格子 DDA 推进,不重不漏。

        原来是每 10px 采样一次,既慢(每条线几十次浮点除法)又会漏掉细墙;
        DDA 只走实际跨越的格子,且每步一次比较一次加法。
        """
        if abs(x2 - x1) < 1.0 and abs(y2 - y1) < 1.0:
            return True
        tile = TILE
        bs = self.block_sight
        tx = int(x1 // tile)
        ty = int(y1 // tile)
        dx = x2 - x1
        dy = y2 - y1
        if dx > 0.0:
            step_x = 1
            tmax_x = ((tx + 1) * tile - x1) / dx
            tdx = tile / dx
        elif dx < 0.0:
            step_x = -1
            tmax_x = (tx * tile - x1) / dx
            tdx = -tile / dx
        else:
            step_x = 0
            tmax_x = _INF
            tdx = _INF
        if dy > 0.0:
            step_y = 1
            tmax_y = ((ty + 1) * tile - y1) / dy
            tdy = tile / dy
        elif dy < 0.0:
            step_y = -1
            tmax_y = (ty * tile - y1) / dy
            tdy = -tile / dy
        else:
            step_y = 0
            tmax_y = _INF
            tdy = _INF
        while True:
            if tmax_x < tmax_y:
                if tmax_x > 1.0:
                    return True
                tx += step_x
                tmax_x += tdx
            else:
                if tmax_y > 1.0:
                    return True
                ty += step_y
                tmax_y += tdy
            if tx < 0 or ty < 0 or tx >= self.mw or ty >= self.mh or bs[ty][tx]:
                return False

    def visibility_polygon(self, x, y, radius, n=140):
        """玩家视野多边形(用于战争迷雾)。

        逐格 DDA 推进,而不是每 12px 采样一次:
          * 步数从固定的 radius/12(560 → 47 步)降到实际跨越的格数(约 25 步);
          * 每步只有一次比较 + 一次加法,原来是 2 次乘法、2 次浮点除法和 2 次取整;
          * 命中墙时取「进入墙格」的精确距离,迷雾边缘正好压在墙面上,不再渗进墙里。
        方向向量按 n 缓存,省掉每帧 140 次 cos/sin。
        """
        tile = TILE
        bs = self.block_sight
        tx0 = int(x // tile)
        ty0 = int(y // tile)
        pts = []
        append = pts.append
        for dx, dy in _ray_dirs(n):
            if dx > 0.0:
                step_x = 1
                tmax_x = ((tx0 + 1) * tile - x) / dx
                tdx = tile / dx
            elif dx < 0.0:
                step_x = -1
                tmax_x = (tx0 * tile - x) / dx
                tdx = -tile / dx
            else:
                step_x = 0
                tmax_x = _INF
                tdx = _INF
            if dy > 0.0:
                step_y = 1
                tmax_y = ((ty0 + 1) * tile - y) / dy
                tdy = tile / dy
            elif dy < 0.0:
                step_y = -1
                tmax_y = (ty0 * tile - y) / dy
                tdy = -tile / dy
            else:
                step_y = 0
                tmax_y = _INF
                tdy = _INF
            tx = tx0
            ty = ty0
            d = radius
            while True:
                if tmax_x < tmax_y:
                    if tmax_x >= radius:
                        break
                    hit_t = tmax_x
                    tx += step_x
                    tmax_x += tdx
                else:
                    if tmax_y >= radius:
                        break
                    hit_t = tmax_y
                    ty += step_y
                    tmax_y += tdy
                if tx < 0 or ty < 0 or tx >= self.mw or ty >= self.mh or bs[ty][tx]:
                    d = hit_t
                    break
            append((x + dx * d, y + dy * d))
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
        for ty in range(self.mh):
            for tx in range(self.mw):
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
        for ty in range(self.mh):
            for tx in range(self.mw):
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
