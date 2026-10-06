# -*- coding: utf-8 -*-
"""拾荒者 AI:待机/游荡 -> 听声搜索 -> 视线发现追击 -> 射击/近战。"""
import math
import random

from settings import SCAVS, TILE, SCAV_LOD_DIST, REPAIR_RANGE

_LOD2 = float(SCAV_LOD_DIST) * SCAV_LOD_DIST

# 选目标(到玩家 + 到每个队友各一次可见性判定)是 AI 里较贵的一步,而目标身份
# 在 0.1 秒里几乎不会变。按 raid.now 错峰重算:120fps 下就是每 12 帧算一次,
# 目标判定便宜了一个数量级,而「发现玩家」最多晚 0.1~0.2 秒(比人的反应还快)。
# 不用更长:再长会让守军隔着刚出现的墙继续射击,手感上看得出来。
THINK_INTERVAL = 0.10


class Scav:
    def __init__(self, kind, x, y, mod=None, custom=None, tag=None):
        d = dict(SCAVS[kind])
        if custom:
            d.update(custom)   # 头目/手下的自定义属性(先套用,再乘难度倍率)
        if mod:
            # 难度倍率:hp/dmg/speed/view 直接缩放; spread/rof 放大=更不准/更慢
            d["hp"] = max(10, int(round(d["hp"] * mod.get("hp", 1.0))))
            d["dmg"] = round(d["dmg"] * mod.get("dmg", 1.0), 1)
            d["speed"] = round(d["speed"] * mod.get("speed", 1.0), 1)
            d["view"] = int(d["view"] * mod.get("view", 1.0))
            if "spread" in d:
                d["spread"] = round(d["spread"] * mod.get("spread", 1.0), 3)
            if "rof" in d:
                d["rof"] = round(d["rof"] * mod.get("rof", 1.0), 2)
                if "pause" in d:
                    d["pause"] = round(d["pause"] * mod.get("rof", 1.0), 2)
            if "atk_cd" in d:
                d["atk_cd"] = round(d["atk_cd"] * mod.get("rof", 1.0), 2)
        self.kind = kind
        self.tag = tag             # None / "boss" / "guard"
        self.d = d
        self.x = x
        self.y = y
        self.hp = d["hp"]
        self.r = 12
        self.state = "idle"        # idle / search / chase
        self.facing = random.uniform(0, math.tau)
        self.path = []            # [tile]
        self.path_i = 0
        self.repath_t = 0.0
        self.path_interval = 0.6  # 重算路径的间隔(远端的守军放宽,省算力)
        self.alert = None         # 听声/最后目击点
        self.search_t = 0.0
        self.shoot_t = 0.0
        self.burst_left = 0
        self.wander_t = random.uniform(0.5, 2.0)
        self.dead = False
        self.hit_flash = 0.0
        self.burn_t = 0.0        # 燃烧剩余时间(龙息弹)
        self.burn_dps = 0.0
        self.repair_target = None  # 被派去修的设施(突袭模式:通讯站被打坏要修)
        # 目标缓存:当前目标 + 是否看得见 + 下次重算时刻(raid.now 时间轴)
        self.tgt = None
        self.tgt_see = False
        self.tgt_t = -1.0
        self.think = random.uniform(0.0, THINK_INTERVAL)   # 错峰相位
        self.lod_phase = random.randint(0, 3)              # 远景降频的错峰相位
        self.view2 = float(d["view"]) * d["view"]

    @property
    def pos(self):
        return self.x, self.y

    # ---- 感知 ----
    def hear(self, pos, radius):
        """听到枪声等噪音。"""
        if self.state == "chase":
            return
        dx = pos[0] - self.x
        dy = pos[1] - self.y
        if dx * dx + dy * dy <= radius * radius:
            self.alert = pos
            self.state = "search"
            self.search_t = 0.0
            self.path = []

    def threat(self, raid):
        """当前目标 + 是否看得见(带缓存,见 THINK_INTERVAL)。"""
        if self.tgt is None or raid.now >= self.tgt_t:
            self.tgt, self.tgt_see = raid.threat_for(self)
            self.tgt_t = raid.now + THINK_INTERVAL + self.think
        return self.tgt, self.tgt_see

    def sees_player(self, raid, target=None):
        """目标是否在视野内且视线通畅。

        不传 target 时直接用 threat() 缓存的结果 —— 原来这一步会把
        threat_for() 刚做过的距离与可见性判定整个再做一遍。
        """
        if target is None:
            return self.threat(raid)[1]
        dx = target.x - self.x
        dy = target.y - self.y
        if dx * dx + dy * dy > self.view2:
            return False
        if target is raid.player:
            return id(self) in raid.sight_vis
        return raid.map.los_clear(self.x, self.y, target.x, target.y)

    # ---- 移动 ----
    def _follow_path(self, raid, dt, speed):
        if not self.path:
            return False
        if self.path_i >= len(self.path):
            self.path = []
            return False
        tx, ty = self.path[self.path_i]
        gx = tx * TILE + TILE // 2
        gy = ty * TILE + TILE // 2
        dx, dy = gx - self.x, gy - self.y
        d2 = dx * dx + dy * dy
        if d2 < 36.0:
            self.path_i += 1
            return True
        dist = math.sqrt(d2)
        step = speed * dt
        nx = self.x + dx / dist * step
        ny = self.y + dy / dist * step
        if raid.map.collides(nx, ny, self.r):
            # 被卡住:直接换下一路径点
            self.path_i += 1
        else:
            self.x, self.y = nx, ny
            self.facing = math.atan2(dy, dx)
        return True

    def _repath(self, raid, target_px, force=False):
        if not force and self.repath_t > 0:
            return
        self.repath_t = self.path_interval
        start = (int(self.x // TILE), int(self.y // TILE))
        goal = (int(target_px[0] // TILE), int(target_px[1] // TILE))
        path = raid.map.astar(start, goal)
        if path:
            self.path = path[1:] if len(path) > 1 else path
            self.path_i = 0
        else:
            self.path = []

    # ---- 主逻辑 ----
    def update(self, raid, dt):
        self.hit_flash = max(0.0, self.hit_flash - dt)
        self.repath_t -= dt
        # 被派去修设施:先跑过去站住(回血由 Raid._assign_repair 结算)
        st = self.repair_target
        if st is not None:
            d_st = math.hypot(st.x - self.x, st.y - self.y)
            if self.tag == "repair":
                # 总指挥部检修队:不管设施好坏都要过去看一眼;到场后
                #   * 坏了/被炸了 -> 留下抢修
                #   * 一切正常     -> 归队防守
                keep_going = (d_st > REPAIR_RANGE) or st.damaged or st.destroyed
            else:
                keep_going = st.damaged        # 普通工兵只修"被打坏"的
            if not keep_going:
                self.repair_target = None
            else:
                if d_st > REPAIR_RANGE:
                    self._repath(raid, (st.x, st.y))
                    self._follow_path(raid, dt, self.d["speed"])
                else:
                    self.path = []
                self.facing = math.atan2(st.y - self.y, st.x - self.x)
                return
        # AI 降级:离玩家很远的守军不必每帧算视线/寻路(玩家在迷雾里也看不到),
        # 50 人大本营要靠这个把帧率稳住。
        # 关键顺序:先用「到玩家的距离」判降级,再选目标 —— 选目标要对每个队友
        # 做一次判定,原来放在最前面,于是远端守军白烧这份钱。
        pl = raid.player
        dpx = pl.x - self.x
        dpy = pl.y - self.y
        d2p = dpx * dpx + dpy * dpy
        self.path_interval = 0.6 if d2p <= _LOD2 else 1.6
        if d2p > _LOD2 and self.state != "chase":
            # 远景降级:连屏幕都够不到的守军(玩家在哪儿都看不到他)每 4 帧才
            # 动一次,步长乘 4 保持同样的平均速度。50 人以上的大本营里大多数
            # 守军都在这个档位,这一条把它们的模拟开销直接砍到 1/4。
            # 阈值用 raid.view_reach2(每帧按真实相机位置算出的可见半径),
            # 所以画面里绝不会出现"该动却没动"的守军。
            if d2p > raid.view_reach2:
                if (raid.frame + self.lod_phase) & 3:
                    return
                dt *= 4.0
            if self.state == "idle":
                self.wander_t -= dt
                if self.wander_t <= 0:
                    self.wander_t = random.uniform(1.5, 4.0)
            self._follow_path(raid, dt, self.d["speed"] * 0.45)
            return
        p, see = self.threat(raid)     # 目标可能是玩家,也可能是暴露的队友
        dx = p.x - self.x
        dy = p.y - self.y
        dist = math.sqrt(dx * dx + dy * dy)
        self.shoot_t -= dt

        if see:
            self.state = "chase"
            self.alert = (p.x, p.y)

        if self.state == "idle":
            self.wander_t -= dt
            if self.wander_t <= 0:
                self.wander_t = random.uniform(1.5, 4.0)
                spot = raid.map.walkable_near(int(self.x // TILE), int(self.y // TILE))
                if spot:
                    self._repath(raid, (spot[0] * TILE + 16, spot[1] * TILE + 16), force=True)
            self._follow_path(raid, dt, self.d["speed"] * 0.45)

        elif self.state == "search":
            if self.alert:
                self._repath(raid, self.alert)
                if not self._follow_path(raid, dt, self.d["speed"] * 0.8):
                    # 到达或无路:原地警戒一会儿
                    self.search_t += dt
                    if self.search_t > 3.5:
                        self.state = "idle"
                        self.alert = None
                else:
                    self.search_t = 0.0
            else:
                self.state = "idle"

        elif self.state == "chase":
            if see:
                self.alert = (p.x, p.y)
                goal = (p.x, p.y)
            elif self.alert:
                # 失去视线:只走向最后目击点,不透视追踪
                if math.hypot(self.alert[0] - self.x, self.alert[1] - self.y) < 40:
                    self.state = "search"
                    self.search_t = 0.0
                    self.path = []
                    return
                goal = self.alert
            else:
                goal = (p.x, p.y)
            self._repath(raid, goal)
            attack_range = self.d.get("range", self.d.get("atk_range", 34))
            if self.kind != "melee" and see and dist < attack_range * 0.9:
                # 站定射击
                self.facing = math.atan2(p.y - self.y, p.x - self.x)
            else:
                self._follow_path(raid, dt, self.d["speed"])
            if self.kind == "melee":
                if (dist < self.d["atk_range"] and self.shoot_t <= 0
                        and raid.map.los_clear(self.x, self.y, p.x, p.y)):
                    self.shoot_t = self.d["atk_cd"]
                    raid.player.take_damage(self.d["dmg"], raid)
                    raid.add_particles(self.x, self.y, 6, (200, 60, 60))
            else:
                if see and dist < self.d["range"] and self.shoot_t <= 0:
                    self._shoot(raid, p)

    def _shoot(self, raid, p):
        d = self.d
        burst = d.get("burst", 1)
        if self.burst_left <= 0:
            self.burst_left = burst
        # 本帧发射一发,随后按 rof 间隔继续;点射打完后追加点射间歇
        self.burst_left -= 1
        self.shoot_t = d["rof"]
        if self.burst_left <= 0:
            self.shoot_t += d.get("pause", 0)
        ang = math.atan2(p.y - self.y, p.x - self.x) + random.uniform(-d["spread"], d["spread"])
        raid.spawn_scav_bullet(self.x, self.y, ang, d["dmg"], d.get("pellets", 1),
                               d["spread"], d["range"], d.get("sfx", "epm"),
                               rpg=d.get("rpg", False), src=self)

    def damage(self, dmg):
        self.hp -= dmg
        self.hit_flash = 0.15
        if self.hp <= 0:
            self.dead = True
        # 受击必警觉
        if self.state != "chase":
            self.state = "search"
            self.search_t = 0.0
