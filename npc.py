# -*- coding: utf-8 -*-
"""人质模式的两类己方 NPC:队友(Ally)与人质(Hostage)。"""
import math
import random

from settings import ALLY_HP, ALLY_RANGE, REPAIR_RANGE, TILE

# 队友选目标不必每帧做(见 Ally.nearest_enemy);0.12s 兼顾了跟枪手感与开销
THINK_INTERVAL = 0.12


def _first(t):
    return t[0]


class Walker:
    """带 A* 寻路的简易移动体(队友/人质共用)。"""

    def __init__(self, x, y):
        self.x, self.y = x, y
        self.r = 11
        self.path = []
        self.path_i = 0
        self.repath_t = 0.0
        self.aim = 0.0

    def _repath(self, raid, tx, ty, force=False):
        if not force and self.repath_t > 0:
            return
        self.repath_t = 0.6
        start = (int(self.x // TILE), int(self.y // TILE))
        goal = (int(tx // TILE), int(ty // TILE))
        path = raid.map.astar(start, goal)
        self.path = path[1:] if path and len(path) > 1 else []
        self.path_i = 0

    def _follow(self, raid, dt, speed):
        if not self.path or self.path_i >= len(self.path):
            self.path = []
            return False
        tx, ty = self.path[self.path_i]
        gx, gy = tx * TILE + TILE // 2, ty * TILE + TILE // 2
        dx, dy = gx - self.x, gy - self.y
        dist = math.hypot(dx, dy)
        if dist < 6:
            self.path_i += 1
            return True
        step = speed * dt
        nx = self.x + dx / dist * step
        ny = self.y + dy / dist * step
        if raid.map.collides(nx, ny, self.r):
            self.path_i += 1          # 卡住就换下一个路径点
        else:
            self.x, self.y = nx, ny
            self.aim = math.atan2(dy, dx)
        return True


class Ally(Walker):
    """队友:跟着玩家推进,看到敌人自动开火;被打倒后需要玩家按 E 拉起。"""

    def __init__(self, x, y):
        super().__init__(x, y)
        self.r = 12
        self.max_hp = ALLY_HP
        self.hp = ALLY_HP
        self.downed = False
        self.fire_cd = 0.0
        self.name = "队友"
        self.repair_target = None   # 被派去修的设施(突袭模式)
        # 目标缓存(见 nearest_enemy)
        self.tgt = None
        self.tgt_ok = False         # 「已算过」而不是「算到了目标」
        self.tgt_t = -1.0
        self.think = random.uniform(0.0, THINK_INTERVAL)

    def nearest_enemy(self, raid):
        """最近的可见敌人(带缓存)。

        原来每个队友每帧扫一遍 50 个守军(math.hypot + 排序),再对最近的 8 个
        各打一条视线 —— 10 个队友就是 500 次 hypot 和最多 80 条视线。目标在
        0.2 秒里不会变,所以按 raid.now 错峰重算(用平方距离,省掉 hypot)。
        """
        if self.tgt_ok and raid.now < self.tgt_t:
            return self.tgt
        self.tgt_t = raid.now + THINK_INTERVAL + self.think
        self.tgt_ok = True          # 「这帧没找到敌人」也要缓存,否则会每帧重扫
        r2 = float(ALLY_RANGE) * ALLY_RANGE
        sx, sy = self.x, self.y
        cands = []
        for s in raid.scavs:
            dx = s.x - sx
            dy = s.y - sy
            d2 = dx * dx + dy * dy
            if d2 < r2:
                cands.append((d2, s))
        if not cands:
            self.tgt = None
            return None
        cands.sort(key=_first)
        los = raid.map.los_clear
        for _d2, s in cands[:8]:
            if los(sx, sy, s.x, s.y):
                self.tgt = s
                return s
        self.tgt = None
        return None

    def update(self, raid, dt):
        self.repath_t -= dt
        if self.downed:
            return
        # 被派去修设施:先跑过去站住(回血由 Raid._assign_repair 结算)
        st = self.repair_target
        if st is not None:
            if st.destroyed or not st.damaged:
                self.repair_target = None
            else:
                if math.hypot(st.x - self.x, st.y - self.y) > REPAIR_RANGE:
                    self._repath(raid, st.x, st.y)
                    self._follow(raid, dt, 175)
                else:
                    self.path = []
                self.aim = math.atan2(st.y - self.y, st.x - self.x)
                return
        self.fire_cd -= dt
        p = raid.player
        tgt = self.nearest_enemy(raid)
        if tgt is not None:
            self.aim = math.atan2(tgt.y - self.y, tgt.x - self.x)
            dx = tgt.x - self.x
            dy = tgt.y - self.y
            if self.fire_cd <= 0:
                self.fire_cd = 0.16
                raid.spawn_ally_bullet(self.x, self.y, self.aim)
            if dx * dx + dy * dy > 240 * 240:     # 拉近到有效射程
                self._repath(raid, tgt.x, tgt.y)
                self._follow(raid, dt, 150)
            else:
                self.path = []
        else:
            dx = p.x - self.x
            dy = p.y - self.y
            if dx * dx + dy * dy > 140 * 140:     # 跟上玩家
                self._repath(raid, p.x, p.y)
                self._follow(raid, dt, 190)
            else:
                self.path = []
                self.aim = math.atan2(p.y - self.y, p.x - self.x)

    def take_damage(self, dmg, raid):
        if self.downed:
            return
        self.hp -= dmg
        raid.add_particles(self.x, self.y, 3, (210, 170, 90))
        if self.hp <= 0:
            self.hp = 0
            self.downed = True
            raid.add_toast("队友倒地!靠近按 E 把他拉起来", (235, 180, 90), 3.5)

    def revive(self):
        self.downed = False
        self.hp = int(self.max_hp * 0.6)


class Hostage(Walker):
    """人质:解救前蹲在原地,解救后跟着玩家撤离。"""

    def __init__(self, x, y):
        super().__init__(x, y)
        self.rescued = False
        self.name = "人质"

    def update(self, raid, dt):
        if not self.rescued:
            return
        p = raid.player
        self.repath_t -= dt
        d = math.hypot(p.x - self.x, p.y - self.y)
        if d > 100:
            self._repath(raid, p.x, p.y)
            self._follow(raid, dt, 150)
        else:
            self.path = []
