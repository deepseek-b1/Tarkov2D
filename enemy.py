# -*- coding: utf-8 -*-
"""拾荒者 AI:待机/游荡 -> 听声搜索 -> 视线发现追击 -> 射击/近战。"""
import math
import random

from settings import SCAVS, TILE, SCAV_LOD_DIST, REPAIR_RANGE


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

    @property
    def pos(self):
        return self.x, self.y

    # ---- 感知 ----
    def hear(self, pos, radius):
        """听到枪声等噪音。"""
        if self.state == "chase":
            return
        if math.hypot(pos[0] - self.x, pos[1] - self.y) <= radius:
            self.alert = pos
            self.state = "search"
            self.search_t = 0.0
            self.path = []

    def sees_player(self, raid, target=None):
        """目标是否在视野内且视线通畅。target 已算过时直接传入,避免重复选目标。

        目标是玩家时读 raid.sight_vis 缓存(refresh_fog 算好的对称视线,
        半径大于任何视距),不再每帧每敌人打一条 DDA 射线。
        注意用 sight_vis 而不是 fog_vis:夜战里 fog_vis 只包含玩家光源内的
        敌人(表示玩家能不能看见他),跟敌人能不能看见玩家无关。
        """
        p = raid.threat_for(self) if target is None else target
        dist = math.hypot(p.x - self.x, p.y - self.y)
        if dist > self.d["view"]:
            return False
        if p is raid.player:
            return id(self) in raid.sight_vis
        return raid.map.los_clear(self.x, self.y, p.x, p.y)

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
        dist = math.hypot(dx, dy)
        if dist < 6:
            self.path_i += 1
            return True
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
        p = raid.threat_for(self)      # 目标可能是玩家,也可能是暴露的队友
        dist = math.hypot(p.x - self.x, p.y - self.y)
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
        # 50 人大本营要靠这个把帧率稳住
        self.path_interval = 0.6 if dist <= SCAV_LOD_DIST else 1.6
        far = dist > SCAV_LOD_DIST
        if far and self.state != "chase":
            if self.state == "idle":
                self.wander_t -= dt
                if self.wander_t <= 0:
                    self.wander_t = random.uniform(1.5, 4.0)
            self._follow_path(raid, dt, self.d["speed"] * 0.45)
            return
        see = self.sees_player(raid, p)
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
