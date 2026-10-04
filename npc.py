# -*- coding: utf-8 -*-
"""人质模式的两类己方 NPC:队友(Ally)与人质(Hostage)。"""
import math

from settings import ALLY_HP, ALLY_RANGE, REPAIR_RANGE, TILE


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

    def nearest_enemy(self, raid):
        """最近的可见敌人。先按距离粗筛再算视线(大本营 50 名守军时省很多)。"""
        cands = []
        for s in raid.scavs:
            d = math.hypot(s.x - self.x, s.y - self.y)
            if d < ALLY_RANGE:
                cands.append((d, s))
        if not cands:
            return None
        cands.sort(key=lambda t: t[0])
        for _d, s in cands[:8]:
            if raid.map.los_clear(self.x, self.y, s.x, s.y):
                return s
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
            d = math.hypot(tgt.x - self.x, tgt.y - self.y)
            if self.fire_cd <= 0:
                self.fire_cd = 0.16
                raid.spawn_ally_bullet(self.x, self.y, self.aim)
            if d > 240:               # 拉近到有效射程
                self._repath(raid, tgt.x, tgt.y)
                self._follow(raid, dt, 150)
            else:
                self.path = []
        else:
            d = math.hypot(p.x - self.x, p.y - self.y)
            if d > 140:               # 跟上玩家
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
