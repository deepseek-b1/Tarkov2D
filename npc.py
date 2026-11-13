# -*- coding: utf-8 -*-
"""人质模式的两类己方 NPC:队友(Ally)与人质(Hostage)。"""
import math
import random

from settings import (ALLY_HP, ALLY_RANGE, REPAIR_RANGE, TILE, ITEMS,
                      RESEARCHER_SIDE_POOL, RESEARCHER_RIFLE_POOL,
                      RESEARCHER_SIDE_RANGE, RESEARCHER_SIDE_DMG,
                      RESEARCHER_SIDE_CD, RESEARCHER_SIDE_SPREAD,
                      RESEARCHER_RIFLE_RANGE, RESEARCHER_RIFLE_DMG,
                      RESEARCHER_RIFLE_CD, RESEARCHER_RIFLE_SPREAD,
                      RESEARCHER_HP, RESEARCHER_INFECT_CHANCE)

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


class Researcher(Hostage):
    """探索模式的联络员(研究员):待救援时蹲在原地;救出后跟着玩家走、开枪帮忙。

    随身装备:一把手枪/冲锋枪(近距离)+ 随机一把突击步枪(远一点),伤害按
    「不是战斗人员」打折。会被打倒;打倒后有概率感染,感染按三个阶段恶化:
      一阶段 没症状 -> 二阶段 分不清敌我(乱开枪) -> 三阶段 攻击友军(可击毙)
    """

    def __init__(self, x, y, uid="", floor=1, side=None, rifle=None):
        super().__init__(x, y)
        self.name = "研究员"
        self.uid = uid           # 稳定编号 "<楼层>-<序号>":跨层恢复状态用
        self.floor = floor
        self.r = 10
        self.side = side if side in ITEMS else random.choice(RESEARCHER_SIDE_POOL)
        self.rifle = rifle if rifle in ITEMS else random.choice(RESEARCHER_RIFLE_POOL)
        self.fire_cd = random.uniform(0.0, 0.8)
        self.tgt = None
        self.tgt_t = -1.0
        # 受伤 / 倒地 / 感染
        self.max_hp = RESEARCHER_HP
        self.hp = self.max_hp
        self.downed = False      # 被打倒(还活着,可以拉起来)
        self.dead = False        # 感染发作后被击毙
        self.infected = False
        self.infect_t = 0.0      # 感染后经过的秒数(倒地时暂停)
        self.infect_stage = 0    # 0=没感染 1/2/3
        self.hostile = False     # 三阶段:开始打友军

    # ---------- 受伤 / 倒地 / 感染 ----------
    def take_damage(self, dmg, raid):
        if self.downed or self.dead:
            return
        self.hp -= dmg
        raid.add_particles(self.x, self.y, 3, (210, 130, 110))
        if self.hp > 0:
            return
        self.hp = 0
        if self.hostile:
            # 已经发作的救不回来了:直接击毙
            self.dead = True
            self.path = []
            raid.add_toast("感染发作的研究员被击毙了", (200, 90, 90), 3.6)
            return
        self.knock_down(raid)

    def knock_down(self, raid):
        self.downed = True
        self.path = []
        self.path_i = 0
        if not self.infected and random.random() < RESEARCHER_INFECT_CHANCE:
            self.infected = True
            self.infect_t = 0.0
            self.infect_stage = 1
        raid.add_toast("研究员被打倒了 —— 靠近按交互键拉起来", (235, 180, 90), 3.6)

    def revive(self):
        self.downed = False
        self.hp = int(self.max_hp * 0.6)

    def stage_label(self):
        """头顶那行小字(一阶段没症状,不显示)。"""
        return {0: "", 1: "", 2: "神志不清", 3: "感染发作"}.get(self.infect_stage, "")

    # ---------- 目标选择 ----------
    def _pick(self, raid, cands):
        """从候选里挑最近的、看得见的那个(0.35 秒缓存一次)。"""
        if self.tgt is not None and raid.now < self.tgt_t:
            return self.tgt if self.tgt in cands else None
        self.tgt_t = raid.now + 0.35
        r2 = float(RESEARCHER_RIFLE_RANGE) ** 2
        best, bd = None, r2
        los = raid.map.los_clear
        for c in cands:
            if c is self or getattr(c, "downed", False) or getattr(c, "dead", False):
                continue
            if getattr(c, "out", False):
                continue
            dx = c.x - self.x
            dy = c.y - self.y
            d2 = dx * dx + dy * dy
            if d2 < bd and los(self.x, self.y, c.x, c.y):
                best, bd = c, d2
        self.tgt = best
        return best

    def nearest_enemy(self, raid):
        """一阶段:只打敌人。"""
        return self._pick(raid, raid.scavs)

    def nearest_confused(self, raid):
        """二阶段:分不清敌我 —— 敌人和身边的研究员都算目标。"""
        return self._pick(raid, list(raid.scavs) + list(raid.researchers))

    def nearest_friendly(self, raid):
        """三阶段:优先玩家,其次队友/其他研究员。"""
        return self._pick(raid, list(raid.players()) + list(raid.allies)
                          + list(raid.researchers))

    # ---------- 每帧 ----------
    def _fire_at(self, raid, tgt, owner):
        d = math.hypot(tgt.x - self.x, tgt.y - self.y)
        if d <= RESEARCHER_SIDE_RANGE:
            dmg, cd, spread = (RESEARCHER_SIDE_DMG, RESEARCHER_SIDE_CD,
                               RESEARCHER_SIDE_SPREAD)
        else:
            dmg, cd, spread = (RESEARCHER_RIFLE_DMG, RESEARCHER_RIFLE_CD,
                               RESEARCHER_RIFLE_SPREAD)
        self.fire_cd = cd
        self.aim = math.atan2(tgt.y - self.y, tgt.x - self.x)
        raid.spawn_ally_bullet(self.x, self.y, self.aim, dmg=dmg, spread=spread,
                               owner=owner, src=self)

    def _update_hostile(self, raid, dt):
        """三阶段:追着友军打(可以被玩家击毙)。"""
        self.repath_t -= dt
        self.fire_cd -= dt
        tgt = self.nearest_friendly(raid)
        if tgt is None:
            p = raid.player
            if math.hypot(p.x - self.x, p.y - self.y) > 160:
                self._repath(raid, p.x, p.y)
                self._follow(raid, dt, 140)
            return
        if self.fire_cd <= 0:
            self._fire_at(raid, tgt, "infected")
        if math.hypot(tgt.x - self.x, tgt.y - self.y) > 240:
            self._repath(raid, tgt.x, tgt.y)
            self._follow(raid, dt, 145)
        else:
            self.path = []

    def update(self, raid, dt):
        if self.dead:
            return
        if self.hostile:
            self._update_hostile(raid, dt)
            return
        if not self.rescued or self.downed:
            return
        Hostage.update(self, raid, dt)      # 先跟着玩家走
        self.fire_cd -= dt
        if self.fire_cd > 0:
            return
        if self.infect_stage >= 2:
            tgt = self.nearest_confused(raid)
            owner = "infected"
        else:
            tgt = self.nearest_enemy(raid)
            owner = "ally"
        if tgt is None:
            return
        self._fire_at(raid, tgt, owner)

