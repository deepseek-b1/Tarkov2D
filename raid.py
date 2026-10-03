# -*- coding: utf-8 -*-
"""战局:搜刮-战斗-撤离。玩家操作、子弹、战利品、撤离引导、阵亡结算。"""
import math
import random

import pygame

import audio
from settings import (W, H, TILE, COL, PLAYER, RAID_TIME, EXTRACT_TIME,
                      INTERACT_DIST, ITEMS, LOOT, SCAV_DROPS, DIFFICULTIES,
                      CLASSIFIED, DOC_HARDENED_COUNT, armor_allows,
                      MAPS, BOSSES, GUARD_ARMOR_DROP, GUARD_ARMORS,
                      AUTHOR_BOSS, AUTHOR_MIN_DIFFICULTY, RPG_BLAST_RADIUS,
                      RPG_HALF_HP_ARMOR_LEVEL, TOUCH, fmt_rub, get_font)
from inventory import Item, try_move
from world import GameMap, LootContainer
from enemy import Scav
from touch import TouchUI


class Player:
    def __init__(self, sd):
        self.x, self.y = 0.0, 0.0
        self.max_hp = PLAYER["hp"]
        self.hp = self.max_hp
        self.weapon = sd.weapon   # 与存档共用引用,撤离后自然持久化
        self.armor = sd.armor
        self.bag = sd.bag
        self.aim = 0.0
        self.fire_cd = 0.0
        self.reload_t = 0.0
        self.reloading = False
        self.hurt_flash = 0.0

    def take_damage(self, dmg, raid, rpg=False):
        if rpg:
            # 火箭弹:穿 6 级甲只掉一半血;<6 级甲直接阵亡
            if (self.armor is not None
                    and self.armor.def_.get("level", 0) >= RPG_HALF_HP_ARMOR_LEVEL):
                self.hp -= int(self.max_hp * 0.5)
                raid.add_toast("火箭弹命中!6 级甲挡下了这一炮(掉一半血)",
                               COL["accent"], 3.6)
            else:
                self.hp = 0
                raid.add_toast("火箭弹命中 —— 没有 6 级甲,当场阵亡!", COL["bad"], 3.6)
            self.hurt_flash = 1.0
            audio.play("hurt")
            raid.shake = 12
            raid.add_particles(self.x, self.y, 26, (255, 170, 60), speed=210)
            if self.hp <= 0:
                if (self.armor is not None and self.armor.def_.get("revive")
                        and not raid.revive_used):
                    raid.revive_used = True
                    self.hp = max(1, int(self.max_hp * 0.3))
                    raid.add_toast("倒地自救成功!(本局仅一次)", COL["good"], 3.6)
                    return
                self.hp = 0
                raid.finish("death")
            return
        if self.armor is not None:
            dmg *= (1 - self.armor.def_.get("reduce", 0))
        dmg = max(1, round(dmg))
        self.hp -= dmg
        self.hurt_flash = 0.45
        audio.play("hurt")
        raid.shake = min(12, raid.shake + 5)
        raid.add_particles(self.x, self.y, 5, (200, 50, 50))
        if self.hp <= 0:
            # 6级甲自带的倒地自救:每局一次,免于阵亡
            if (self.armor is not None and self.armor.def_.get("revive")
                    and not raid.revive_used):
                raid.revive_used = True
                self.hp = max(1, int(self.max_hp * 0.3))
                self.hurt_flash = 1.0
                raid.shake = 12
                raid.add_particles(self.x, self.y, 18, (120, 220, 255), speed=150)
                audio.play("heal")
                raid.add_toast("倒地自救成功!(本局仅一次)", COL["good"], 3.6)
                return
            self.hp = 0
            raid.finish("death")

    def heal(self, n):
        before = self.hp
        self.hp = min(self.max_hp, self.hp + n)
        return self.hp - before

    def speed(self, walking):
        s = PLAYER["walk"] if walking else PLAYER["speed"]
        if self.armor is not None:
            s *= (1 - self.armor.def_.get("slow", 0))
        return s

    def reserve_count(self):
        if self.weapon is None:
            return 0
        ammo = self.weapon.def_["ammo"]
        return sum(p.item.count for p in self.bag.items if p.item.iid == ammo)


class Raid:
    def __init__(self, game, difficulty=None):
        self.game = game
        self.diff_key = difficulty if difficulty in DIFFICULTIES else \
            (getattr(game.save, "difficulty", None) or "lockdown")
        if self.diff_key not in DIFFICULTIES:
            self.diff_key = "lockdown"
        self.diff = DIFFICULTIES[self.diff_key]
        self.map_key = getattr(game.save, "map_key", "border")
        if self.map_key not in MAPS:
            self.map_key = "border"
        self.touch_mode = bool(getattr(game.save, "touch", False))
        self.touch = TouchUI() if self.touch_mode else None
        self.aim_locked = None
        self.boss_cfg = BOSSES[self.map_key]
        self.map = GameMap(self.map_key)
        self.map_surf = self.map.prerender()
        self.player = Player(game.save)
        self.player.x, self.player.y = self.map.spawn
        self.cam = [0, 0]
        self.shake = 0.0
        self.start_value = self._loadout_value()   # 进局装备总值(撤离收益快照基准)

        self.scavs = [Scav(k, x, y, self.diff) for k, (x, y) in self._pick_spawns()]
        self._spawn_boss_and_guards()
        self._spawn_author()
        self.containers = list(self.map.loot)
        # 强化封锁:机密文件固定刷在保险箱(先放入,保证有位置)
        if self.diff_key == "hardened" and DOC_HARDENED_COUNT > 0:
            safes = [c for c in self.containers if c.kind == "val"]
            random.shuffle(safes)
            for lc in safes[:DOC_HARDENED_COUNT]:
                lc.container.add_item(Item(CLASSIFIED))
        for lc in self.containers:
            self._gen_loot(lc)

        self.bullets = []
        self.particles = []
        self.toasts = []
        if self.diff_key == "hardened" and DOC_HARDENED_COUNT > 0:
            self.add_toast("强化封锁:机密文件已刷新,藏在保险箱之一",
                           COL["accent"], 4.5)
        self.add_toast(f"头目 {self.boss_cfg['name']} 在场 —— 击杀可爆 5 级甲与专属枪械",
                       COL["accent"], 4.0)
        if any(getattr(s, "tag", None) == "author" for s in self.scavs):
            self.add_toast("警报:隐藏头目「作者」携 RPG 在场!(没穿 6 级甲别硬碰)",
                           COL["bad"], 5.0)
        self.time_left = float(RAID_TIME)
        self.kills = 0
        self.loot_log = []       # 撤离结算用:{"name","count","value"}
        self.inv_open = False
        self.loot_target = None
        self.paused = False
        self.over = False
        self.result = None
        self.extract_t = 0.0
        self.fire_edge = False
        self.braced = False       # 长按右键架枪(提升精度)
        self.ask_merge = False   # "整理弹药"确认框
        self.revive_used = False  # 6级甲倒地自救(每局一次)
        self.warned = set()
        self._click_cd = 0.0

    # ---------- 提示/粒子 ----------
    def add_toast(self, text, color=None, ttl=2.6):
        self.toasts.append([text, ttl, ttl, color or COL["text"]])

    def add_particles(self, x, y, n, color, speed=90):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(0.3, 1.0) * speed
            ttl = random.uniform(0.25, 0.6)
            self.particles.append(dict(x=x, y=y, dx=math.cos(a) * s, dy=math.sin(a) * s,
                                       ttl=ttl, max_ttl=ttl, color=color,
                                       size=random.randint(2, 4)))

    def emit_noise(self, x, y, radius):
        for s in self.scavs:
            s.hear((x, y), radius)

    # ---------- 战利品 ----------
    def _pick_spawns(self):
        """按难度决定敌人数量与位置。"""
        spawns = list(self.map.scav_spawns)
        wanted = self.diff["scavs"]
        if wanted <= len(spawns):
            return random.sample(spawns, wanted) if wanted < len(spawns) else spawns
        px, py = self.map.spawn
        result = spawns
        tries = 0
        while len(result) < wanted and tries < 120:
            tries += 1
            k, (sx, sy) = random.choice(spawns)
            spot = self.map.walkable_near(int(sx // TILE), int(sy // TILE))
            if not spot:
                continue
            x, y = spot[0] * TILE + TILE // 2, spot[1] * TILE + TILE // 2
            if math.hypot(x - px, y - py) < 350:
                continue
            result.append((k, (x, y)))
        return result

    def _gen_loot(self, lc):
        table = LOOT.get(lc.kind)
        if not table:
            return
        iids = [t[0] for t in table]
        weights = [t[2] for t in table]
        for _ in range(self.diff["rolls"]):
            iid = random.choices(iids, weights=weights)[0]
            d = ITEMS[iid]
            if d["cat"] == "ammo":
                count = random.randint(1, d.get("stack", 1))
                count = max(1, min(d.get("stack", 1),
                                   int(round(count * self.diff["loot"]))))
                it = Item(iid, count=count)
            else:
                it = Item(iid, count=1)
                if d["cat"] == "weapon":
                    it.state["mag"] = random.randint(0, d["mag"])
                    if random.random() < 0.5:
                        ammo = ITEMS[d["ammo"]]
                        lc.container.add_item(Item(d["ammo"],
                                                    count=random.randint(8, min(30, ammo.get("stack", 30)))))
            lc.container.add_item(it)

    def _scav_drops(self, kind):
        items = []
        if kind in SCAV_DROPS and random.random() < 0.6:
            wi, ai, amin, amax = SCAV_DROPS[kind]
            items.append(Item.weapon(wi, mag=random.randint(0, ITEMS[wi]["mag"])))
            items.append(Item(ai, count=random.randint(amin, amax)))
        if kind == "melee":
            if random.random() < 0.4:
                items.append(Item("bandage"))
        else:
            if random.random() < 0.25:
                items.append(Item("bandage"))
            if random.random() < 0.18:
                items.append(Item("gold"))
        return items

    def _spawn_boss_and_guards(self):
        """按地图配置生成头目与他的手下(独立于普通拾荒者的随机刷新)。"""
        b = self.boss_cfg
        if self.map.boss_spawn:
            bx, by = self.map.boss_spawn
            self.scavs.append(Scav("ar", bx, by, self.diff,
                                   custom=dict(b), tag="boss"))
        guard_custom = dict(
            name="头目手下", hp=b.get("guard_hp", 95), dmg=b.get("guard_dmg", 11),
            spread=0.10, rof=0.13, auto=True, burst=3, pause=1.2,
            range=700, view=480, pellets=1, speed=150)
        for gx, gy in self.map.guard_spawns[:b.get("guards", 3)]:
            self.scavs.append(Scav("ar", gx, gy, self.diff,
                                   custom=dict(guard_custom), tag="guard"))

    def _spawn_author(self):
        """隐藏头目「作者」:扛 RPG,只在封锁及以上难度出现。"""
        if self.diff_key not in AUTHOR_MIN_DIFFICULTY:
            return
        if not self.map.author_spawn:
            return
        ax, ay = self.map.author_spawn
        self.scavs.append(Scav("ar", ax, ay, self.diff,
                               custom=dict(AUTHOR_BOSS), tag="author"))

    def _author_drops(self):
        """作者必掉:RPG-7 + 火箭弹 + 6 级甲 + 值钱货。"""
        a = AUTHOR_BOSS
        items = [Item.weapon(a["weapon"], mag=1),
                 Item("rocket", count=3),
                 Item(a["armor"])]
        items.append(Item(random.choice(["btc", "gold", "cpu", "gpu"])))
        if random.random() < 0.5:
            items.append(Item("medkit"))
        return items

    def _boss_drops(self):
        """头目必掉:5 级甲 + 专属枪械 + 对应弹药 + 值钱货。"""
        b = self.boss_cfg
        wid = b["weapon"]
        wd = ITEMS[wid]
        items = [Item(b["armor"]),
                 Item.weapon(wid, mag=random.randint(max(1, wd["mag"] // 3), wd["mag"]))]
        items.append(Item(wd["ammo"], count=random.randint(20, 60)))
        items.append(Item(random.choice(["gold", "cpu", "gpu", "vase", "btc"])))
        if random.random() < 0.6:
            items.append(Item("medkit"))
        if random.random() < 0.4:
            items.append(Item(random.choice(GUARD_ARMORS)))
        return items

    def _corpse_pos(self, x, y):
        """尸体盒子位置:与已有容器太近时按黄金角环形错开,避免叠在一起。"""
        for attempt in range(14):
            too_close = any(
                math.hypot(x - lc.rect.centerx, y - lc.rect.centery) < TILE * 0.9
                for lc in self.containers)
            if not too_close:
                return x, y
            ang = attempt * 2.39996
            rad = TILE * (0.9 + 0.3 * (attempt // 4))
            x = int(x + math.cos(ang) * rad)
            y = int(y + math.sin(ang) * rad)
        return x, y

    def kill_scav(self, scav):
        self.scavs.remove(scav)
        self.kills += 1
        audio.play("kill")
        tag = getattr(scav, "tag", None)
        cx, cy = self._corpse_pos(int(scav.x), int(scav.y))
        if tag == "author":
            corpse = LootContainer("boss_corpse", cx, cy)
            for it in self._author_drops():
                corpse.container.add_item(it)
            self.containers.append(corpse)
            self.add_toast("你击杀了「作者」!爆出 RPG 与 6 级甲",
                           COL["accent"], 4.5)
            return
        if tag == "boss":
            corpse = LootContainer("boss_corpse", cx, cy)
            for it in self._boss_drops():
                corpse.container.add_item(it)
            self.containers.append(corpse)
            self.add_toast(f"击杀头目 {scav.d['name']}!已掉落 5 级甲与专属枪械",
                           COL["accent"], 4.0)
            return
        corpse = LootContainer("corpse", cx, cy)
        for it in self._scav_drops(scav.kind):
            corpse.container.add_item(it)
        if tag == "guard":
            # 头目手下:有概率爆 5 级甲
            if random.random() < GUARD_ARMOR_DROP:
                corpse.container.add_item(Item(random.choice(GUARD_ARMORS)))
                self.add_toast("头目手下爆出了 5 级甲!", COL["good"], 3.0)
            if random.random() < 0.35:
                corpse.container.add_item(Item("gold"))
        self.containers.append(corpse)
        self.add_toast(f"击杀 {scav.d['name']}", COL["good"])

    def nearest_container(self):
        p = self.player
        best, bd = None, INTERACT_DIST
        for lc in self.containers:
            d = math.hypot(lc.rect.centerx - p.x, lc.rect.centery - p.y)
            if d < bd:
                best, bd = lc, d
        return best

    # ---------- 射击 ----------
    def try_fire(self, held):
        p = self.player
        w = p.weapon
        if w is None or p.reload_t > 0 or p.fire_cd > 0:
            return
        d = w.def_
        if not d["auto"] and not self.fire_edge:
            return
        if d["auto"] and not held:
            return
        if w.state.get("mag", 0) <= 0:
            if self.fire_edge:
                audio.play("empty")
            return
        w.state["mag"] -= 1
        p.fire_cd = d["rof"]
        tx = p.x + math.cos(p.aim) * 22
        ty = p.y + math.sin(p.aim) * 22
        # 架枪(长按右键)可大幅收拢散布:M139 等重型武器腰射很散
        spread = d["spread"]
        if self.braced and d.get("spread_braced") is not None:
            spread = d["spread_braced"]
        for _ in range(d["pellets"]):
            ang = p.aim + random.uniform(-spread, spread)
            is_rpg = d.get("ammo") == "rocket"
            spd = 520.0 if is_rpg else 1100.0
            self.bullets.append(dict(x=tx, y=ty, dx=math.cos(ang) * spd,
                                     dy=math.sin(ang) * spd, dmg=d["dmg"],
                                     owner="player", ttl=d["range"] / spd,
                                     rpg=is_rpg))
        audio.play(d["sfx"])
        self.emit_noise(p.x, p.y, d["loud"])
        self.add_particles(tx, ty, 3 if not d.get("ammo") == "rocket" else 10,
                           (255, 210, 90), speed=160)
        self.shake = min(12, self.shake + (6.0 if d.get("ammo") == "rocket"
                                          else (2.5 if d["pellets"] > 1 else 1.2)))

    def spawn_scav_bullet(self, x, y, ang, dmg, pellets, spread, rng, sfx,
                          rpg=False, src=None):
        for _ in range(pellets):
            a = ang + random.uniform(-spread * 0.6, spread * 0.6)
            spd = 400.0 if rpg else 760.0        # 火箭弹飞得慢,可以闪避
            self.bullets.append(dict(x=x, y=y, dx=math.cos(a) * spd, dy=math.sin(a) * spd,
                                     dmg=dmg, owner="scav", ttl=rng / spd, rpg=rpg,
                                     src=src))
        audio.play(sfx)
        self.emit_noise(x, y, 700 if rpg else 400)

    def explode(self, x, y, dmg, owner, src=None):
        """火箭弹爆炸:半径内的拾荒者一律吃伤害(不用瞄准);
        玩家被波及则按火箭弹规则判定(穿 6 级甲半血,否则阵亡)。src 为发射者,不吃自己的爆炸。"""
        audio.play("sg")
        self.shake = min(14, self.shake + 8)
        self.add_particles(x, y, 26, (255, 170, 60), speed=240)
        self.add_particles(x, y, 14, (255, 240, 180), speed=150)
        self.emit_noise(x, y, 900)
        for s in list(self.scavs):
            if s is src:
                continue
            if math.hypot(s.x - x, s.y - y) <= RPG_BLAST_RADIUS:
                s.damage(dmg)
                if s.dead:
                    self.kill_scav(s)
        p = self.player
        if math.hypot(p.x - x, p.y - y) <= RPG_BLAST_RADIUS:
            p.take_damage(dmg, self, rpg=True)

    def _update_bullets(self, dt):
        alive = []
        for b in self.bullets:
            # 分小步采样,防止低帧率下 55px/步 穿墙/穿人
            total = math.hypot(b["dx"], b["dy"]) * dt
            n = max(1, int(total / 14) + 1)
            sdt = dt / n
            dead = False
            is_rpg = b.get("rpg", False)
            for _ in range(n):
                b["x"] += b["dx"] * sdt
                b["y"] += b["dy"] * sdt
                b["ttl"] -= sdt
                if b["ttl"] <= 0:
                    if is_rpg:
                        self.explode(b["x"], b["y"], b["dmg"], b["owner"],
                                     src=b.get("src"))
                    dead = True
                    break
                tx, ty = int(b["x"] // TILE), int(b["y"] // TILE)
                if self.map.tile_solid(tx, ty):
                    if is_rpg:
                        self.explode(b["x"], b["y"], b["dmg"], b["owner"],
                                     src=b.get("src"))
                    else:
                        self.add_particles(b["x"], b["y"], 3, (200, 200, 160), speed=60)
                    dead = True
                    break
                if is_rpg:
                    # 火箭弹:碰到人/被挡就引爆,溅射范围内都吃伤害(不必精确瞄准)
                    for s in list(self.scavs):
                        if math.hypot(s.x - b["x"], s.y - b["y"]) < s.r + 3:
                            self.explode(b["x"], b["y"], b["dmg"], b["owner"],
                                         src=b.get("src"))
                            dead = True
                            break
                    if dead:
                        break
                    p0 = self.player
                    if math.hypot(p0.x - b["x"], p0.y - b["y"]) < PLAYER["radius"] + 2:
                        self.explode(b["x"], b["y"], b["dmg"], b["owner"],
                                     src=b.get("src"))
                        dead = True
                        break
                    continue
                if b["owner"] == "player":
                    for s in self.scavs:
                        if math.hypot(s.x - b["x"], s.y - b["y"]) < s.r + 3:
                            s.damage(b["dmg"])
                            audio.play("hit")
                            self.add_particles(b["x"], b["y"], 4, (190, 40, 40))
                            if s.dead:
                                self.kill_scav(s)
                            dead = True
                            break
                else:
                    p = self.player
                    if math.hypot(p.x - b["x"], p.y - b["y"]) < PLAYER["radius"] + 2:
                        p.take_damage(b["dmg"], self)
                        dead = True
                if dead:
                    break
            if not dead:
                alive.append(b)
        self.bullets = alive

    # ---------- 装填/使用/装备 ----------
    def start_reload(self):
        p = self.player
        if p.weapon is None or p.reloading or p.reload_t > 0:
            return
        w = p.weapon
        if w.state.get("mag", 0) >= w.def_["mag"]:
            return
        if p.reserve_count() <= 0:
            self.add_toast("没有可用弹药!", COL["bad"])
            return
        p.reload_t = 1.6
        p.reloading = True
        audio.play("reload")

    def _finish_reload(self):
        p = self.player
        w = p.weapon
        if w is None:
            # 装填途中卸下武器:直接取消
            p.reloading = False
            p.reload_t = 0
            return
        need = w.def_["mag"] - w.state.get("mag", 0)
        got = 0
        for placed in list(p.bag.items):
            if placed.item.iid == w.def_["ammo"] and need > 0:
                take = min(need, placed.item.count)
                got += take
                need -= take
                placed.item.count -= take
                if placed.item.count <= 0:
                    p.bag.remove_placed(placed)
        if got:
            w.state["mag"] = w.state.get("mag", 0) + got
            self.add_toast(f"装填完成 {w.state['mag']}/{w.def_['mag']}", COL["good"])

    def use_med(self, placed):
        p = self.player
        if p.hp >= p.max_hp:
            self.add_toast("生命值已满", COL["text_dim"])
            return
        healed = p.heal(placed.item.def_["heal"])
        p.bag.remove_placed(placed)
        audio.play("heal")
        self.add_toast(f"治疗 +{healed}", COL["good"])

    def _aim_assist_target(self):
        """辅助瞄准(手机):视野内最近的可见敌人。"""
        p = self.player
        best, bd = None, TOUCH["aim_assist_range"]
        for s in self.scavs:
            d = math.hypot(s.x - p.x, s.y - p.y)
            if d < bd and self.map.los_clear(p.x, p.y, s.x, s.y):
                best, bd = s, d
        return best

    def quick_heal(self):
        """快捷打药(按 H):直接用最合适的医疗品,不用开背包。"""
        p = self.player
        if p.hp >= p.max_hp:
            self.add_toast("生命值已满", COL["text_dim"])
            return
        meds = [pl for pl in p.bag.items if pl.item.cat == "med"]
        if not meds:
            self.add_toast("背包里没有医疗品!", COL["bad"])
            return
        missing = p.max_hp - p.hp
        cover = [pl for pl in meds if pl.item.def_.get("heal", 0) >= missing]
        # 优先用刚好够用的小药,避免浪费医疗包
        pick = min(cover, key=lambda pl: pl.item.def_["heal"]) if cover else \
            max(meds, key=lambda pl: pl.item.def_["heal"])
        self.use_med(pick)

    def equip_from_bag(self, placed):
        p = self.player
        item = placed.item
        if item.cat == "weapon":
            if not armor_allows(p.armor, item.def_):
                self.add_toast(
                    f"需 {item.def_['req_armor_level']} 级护甲才能持用 {item.name}",
                    COL["bad"], 3.0)
                return
            old = p.weapon
            p.bag.remove_placed(placed)
            if old is not None and not p.bag.add_item(old):
                p.bag.items.append(placed)   # 放不下旧枪:回滚
                self.add_toast("背包空间不足", COL["bad"])
                return
            p.weapon = item
            p.reloading = False   # 换枪取消装填
            p.reload_t = 0
            audio.play("click")
        elif item.cat == "armor":
            old = p.armor
            p.bag.remove_placed(placed)
            if old is not None and not p.bag.add_item(old):
                p.bag.items.append(placed)
                self.add_toast("背包空间不足", COL["bad"])
                return
            p.armor = item
            audio.play("click")

    def drop_from_bag(self, placed):
        item = self.player.bag.take_placed(placed)
        pile = None
        p = self.player
        for lc in self.containers:
            if lc.kind == "ground" and math.hypot(lc.rect.centerx - p.x,
                                                  lc.rect.centery - p.y) < 48:
                pile = lc
                break
        created = False
        if pile is None:
            pile = LootContainer("ground", int(p.x), int(p.y))
            created = True
        if pile.container.add_item(item):
            if created:
                self.containers.append(pile)
            self._unlog_gained(item)
            audio.play("click")
            self.add_toast(f"丢弃 {item.name}", COL["text_dim"])
        else:
            # 放不下:物品回到背包,不留下空堆
            self.player.bag.items.append(placed)

    def merge_ammo(self, container=None):
        """整理弹药:把相同子弹叠放成组,每组至多 max_stack(120)发。
        返回实际合并过的弹种数。"""
        bag = container if container is not None else self.player.bag
        groups = {}
        for placed in bag.items:
            if placed.item.is_stackable():
                groups.setdefault(placed.item.iid, []).append(placed)
        merged = 0
        for iid, plist in groups.items():
            maxs = ITEMS[iid].get("stack", 1)
            total = sum(p.item.count for p in plist)
            need = (total + maxs - 1) // maxs
            if len(plist) <= need:
                continue   # 已经是最紧凑状态
            for p in plist:
                bag.remove_placed(p)
            remaining = total
            while remaining > 0:
                chunk = min(maxs, remaining)
                if not bag.add_item(Item(iid, count=chunk)):
                    # 极端兜底:放不下就保持剩余一组(不会更差)
                    bag.add_item(Item(iid, count=remaining))
                    break
                remaining -= chunk
            merged += 1
        return merged

    def _handle_ask_click(self, pos):
        import raid_ui
        lay = raid_ui.ask_layout()
        if lay["yes"].collidepoint(pos):
            n = self.merge_ammo()
            self.ask_merge = False
            audio.play("pickup")
            if n:
                self.add_toast(f"弹药已整理:合并了 {n} 种子弹", COL["good"])
            else:
                self.add_toast("没有可合并的子弹", COL["text_dim"])
        elif lay["no"].collidepoint(pos):
            self.ask_merge = False
            audio.play("click")

    # ---------- 结算 ----------
    def _loadout_value(self):
        p = self.player
        v = p.bag.total_value()
        if p.weapon is not None:
            v += p.weapon.total_price()
        if p.armor is not None:
            v += p.armor.total_price()
        return v

    def finish(self, kind):
        if self.over:
            return
        self.over = True
        self.inv_open = False
        self.loot_target = None
        self.paused = False
        if kind == "extract":
            audio.play("extract")
        else:
            audio.play("death")
        # 用"撤离时装备总值 - 进局时装备总值"快照计算净收益,事件式记账
        # 会在放回物品/部分堆叠转移时失真
        gained = max(0, int(self._loadout_value() - self.start_value))
        self.result = dict(kind=kind, kills=self.kills, gained=gained,
                           n=len(self.loot_log), time=RAID_TIME - self.time_left,
                           entries=self.loot_log)
        self.game.raid_finished(self.result)

    # ---------- 每帧 ----------
    def update(self, dt, events):
        p = self.player
        self._click_cd = max(0.0, self._click_cd - dt)

        # 结算页:任意键返回藏身处
        if self.over:
            for ev in events:
                if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN):
                    self.game.to_hideout()
            return

        # 事件
        pending_edge = False
        for ev in events:
            # 手机模式且没有弹窗时,触摸先交给虚拟摇杆/按钮
            if self.touch_mode and not (self.inv_open or self.loot_target is not None
                                        or self.ask_merge or self.paused):
                if self.touch.handle_event(ev):
                    continue
            if ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    if self.ask_merge:
                        self.ask_merge = False
                    elif self.inv_open or self.loot_target:
                        self.inv_open = False
                        self.loot_target = None
                    elif self.paused:
                        self.paused = False
                    else:
                        self.paused = True
                elif self.paused:
                    continue   # 暂停中其余按键不生效,防止"暂停+背包"死状态
                elif ev.key == pygame.K_TAB:
                    self.loot_target = None
                    self.ask_merge = False
                    self.inv_open = not self.inv_open
                elif ev.key == pygame.K_e:
                    if self.loot_target:
                        self.loot_target = None
                    elif self.inv_open:
                        self.inv_open = False
                    else:
                        lc = self.nearest_container()
                        if lc is not None:
                            self.loot_target = lc
                            audio.play("click")
                elif ev.key == pygame.K_r:
                    if not (self.inv_open or self.loot_target):
                        self.start_reload()
                elif ev.key == pygame.K_h:
                    if not (self.inv_open or self.loot_target):
                        self.quick_heal()
            elif ev.type == pygame.MOUSEBUTTONDOWN:
                if self.paused:
                    self._handle_pause_click(ev.pos)
                elif self.ask_merge:
                    self._handle_ask_click(ev.pos)
                elif self.inv_open:
                    self._handle_inv_click(ev)
                elif self.loot_target is not None:
                    self._handle_loot_click(ev)
                else:
                    if ev.button == 1 and not self.touch_mode:
                        pending_edge = True
        self.fire_edge = pending_edge
        if self.paused:
            return

        # 计时
        self.time_left -= dt
        if self.time_left <= 120 and 120 not in self.warned:
            self.warned.add(120)
            self.add_toast("注意:战局只剩 2 分钟!", COL["bad"], 3.2)
        if self.time_left <= 30 and 30 not in self.warned:
            self.warned.add(30)
            self.add_toast("最后 30 秒!超时视为阵亡!", COL["bad"], 3.2)
        if self.time_left <= 0:
            self.time_left = 0
            self.add_toast("行动超时", COL["bad"])
            self.finish("mia")
            return

        # 移动(M139 架枪时无法移动;手机模式用左半屏摇杆)
        if self.touch_mode:
            vx, vy = self.touch.move_axis()
            walking = False
        else:
            keys = pygame.key.get_pressed()
            vx = float((keys[pygame.K_d] or keys[pygame.K_RIGHT])
                       - (keys[pygame.K_a] or keys[pygame.K_LEFT]))
            vy = float((keys[pygame.K_s] or keys[pygame.K_DOWN])
                       - (keys[pygame.K_w] or keys[pygame.K_UP]))
            walking = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
        immobile = (self.braced and p.weapon is not None
                    and p.weapon.def_.get("braced_immobile"))
        moving = bool(vx or vy) and not immobile
        if moving:
            length = math.hypot(vx, vy)
            spd = p.speed(walking)
            scale = min(1.0, length)     # 摇杆推一半 = 半速
            dx = vx / length * spd * scale * dt
            dy = vy / length * spd * scale * dt
            p.x, p.y = self.map.move_circle((p.x, p.y), dx, dy, PLAYER["radius"])

        # 瞄准:电脑用鼠标;手机自动锁敌(视野内最近的敌人,不用手动瞄准)
        if self.touch_mode:
            self.aim_locked = self._aim_assist_target()
            if self.aim_locked is not None:
                p.aim = math.atan2(self.aim_locked.y - p.y, self.aim_locked.x - p.x)
            elif moving:
                p.aim = math.atan2(vy, vx)
        else:
            self.aim_locked = None
            mpx, mpy = pygame.mouse.get_pos()
            world_x = self.cam[0] + mpx
            world_y = self.cam[1] + mpy
            p.aim = math.atan2(world_y - p.y, world_x - p.x)

        # 搜刮窗口超距自动关闭(防隔空取物)
        if self.loot_target is not None:
            lc = self.loot_target
            if math.hypot(lc.rect.centerx - p.x, lc.rect.centery - p.y) > INTERACT_DIST * 1.8:
                self.loot_target = None
                self.add_toast("距离过远,搜刮窗口已关闭", COL["text_dim"])

        # 射击 / 架枪
        if self.touch_mode:
            held = self.touch.hold("fire")
            self.braced = self.touch.hold("brace")
            for name in self.touch.take_taps():
                if name == "fire":
                    self.fire_edge = True       # 点按也能点射
                elif name == "reload":
                    self.start_reload()
                elif name == "heal":
                    self.quick_heal()
                elif name == "loot":
                    if self.loot_target:
                        self.loot_target = None
                    elif self.inv_open:
                        self.inv_open = False
                    else:
                        lc = self.nearest_container()
                        if lc is not None:
                            self.loot_target = lc
                            audio.play("click")
                elif name == "bag":
                    self.loot_target = None
                    self.inv_open = not self.inv_open
        else:
            held = pygame.mouse.get_pressed()[0]
            self.braced = bool(pygame.mouse.get_pressed()[2])   # 右键=架枪
        world_active = not (self.inv_open or self.loot_target is not None)
        if world_active:
            self.try_fire(held)
        self.fire_edge = False

        # 装填计时
        p.fire_cd = max(0.0, p.fire_cd - dt)
        if p.reloading:
            p.reload_t -= dt
            if p.reload_t <= 0:
                p.reload_t = 0
                p.reloading = False
                self._finish_reload()
        # 自动换弹:弹匣空了且背包里有对应弹药,自动开始装填(不必按 R)
        if (p.weapon is not None and not p.reloading and p.reload_t <= 0
                and p.weapon.state.get("mag", 0) <= 0
                and p.reserve_count() > 0 and not self.over):
            self.start_reload()
        p.hurt_flash = max(0.0, p.hurt_flash - dt)

        # 撤离引导
        zone = None
        for name, r in self.map.extracts:
            if r.collidepoint(p.x, p.y):
                zone = name
                break
        if zone is not None and not moving and not p.reloading:
            if self.extract_t == 0:
                self.add_toast(f"开始撤离:{zone}", COL["accent"])
            self.extract_t += dt
            if self.extract_t >= EXTRACT_TIME:
                self.add_toast("撤离成功!", COL["good"])
                self.finish("extract")
                return
        else:
            self.extract_t = max(0.0, self.extract_t - dt * 3)

        # 实体
        for s in self.scavs:
            s.update(self, dt)
        self._update_bullets(dt)
        for pt in self.particles:
            pt["ttl"] -= dt
            pt["x"] += pt["dx"] * dt
            pt["y"] += pt["dy"] * dt
            pt["dx"] *= 0.9
            pt["dy"] *= 0.9
        self.particles = [pt for pt in self.particles if pt["ttl"] > 0]
        for t in self.toasts:
            t[1] -= dt
        self.toasts = [t for t in self.toasts if t[1] > 0]
        self.shake = max(0.0, self.shake - dt * 18)

        # 摄像机
        self.cam[0] = max(0, min(self.map.px_w - W, p.x - W / 2))
        self.cam[1] = max(0, min(self.map.px_h - H, p.y - H / 2))

    # ---------- 界面点击 ----------
    def _handle_pause_click(self, pos):
        import raid_ui
        lay = raid_ui.pause_layout()
        if lay["resume"].collidepoint(pos):
            self.paused = False
            audio.play("click")
        elif lay["giveup"].collidepoint(pos):
            self.add_toast("放弃行动,按阵亡处理", COL["bad"])
            self.finish("death")
        elif lay["quit"].collidepoint(pos):
            self.game.request_quit()

    def _handle_inv_click(self, ev):
        import raid_ui
        p = self.player
        lay = raid_ui.inv_layout(p.bag.w, p.bag.h)
        pos = ev.pos
        if lay["close"].collidepoint(pos):
            self.inv_open = False
            audio.play("click")
            return
        # 整理弹药按钮 -> 弹确认框询问
        if lay["merge"].collidepoint(pos):
            self.ask_merge = True
            audio.play("click")
            return
        # 装备槽点击 = 卸下
        if lay["weapon"].collidepoint(pos) and p.weapon is not None:
            old = p.weapon
            if p.bag.add_item(old):
                p.weapon = None
                p.reloading = False   # 卸枪取消装填
                p.reload_t = 0
                audio.play("click")
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        if lay["armor"].collidepoint(pos) and p.armor is not None:
            if p.weapon is not None and not armor_allows(None, p.weapon.def_):
                self.add_toast(
                    f"手里的 {p.weapon.name} 需要 6 级甲,先换掉武器",
                    COL["bad"], 3.0)
                return
            old = p.armor
            if p.bag.add_item(old):
                p.armor = None
                audio.play("click")
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        placed = raid_ui.grid_hit_px(p.bag, lay["bag"], pos)
        if placed is None:
            return
        if ev.button == 3:
            self.drop_from_bag(placed)
        elif ev.button == 1:
            if placed.item.cat == "med":
                self.use_med(placed)
            elif placed.item.cat in ("weapon", "armor"):
                self.equip_from_bag(placed)
            else:
                self.add_toast(f"{placed.item.name}:自动装填消耗 / 右键丢弃",
                               COL["text_dim"], 1.8)

    def _handle_loot_click(self, ev):
        import raid_ui
        p = self.player          # 必须在两个分支前绑定:点背包侧也要用
        lay = raid_ui.loot_layout(self.loot_target.container.w,
                                  self.loot_target.container.h,
                                  p.bag.w, p.bag.h)
        lc = self.loot_target
        pos = ev.pos
        if ev.button != 1:
            return
        if lay["close"].collidepoint(pos):
            self.loot_target = None
            audio.play("click")
            return
        if lay["takeall"].collidepoint(pos):
            for placed in list(lc.container.items):
                if try_move(lc.container, placed, self.player.bag):
                    self._log_gained(placed.item)
            audio.play("pickup")
            return
        placed = raid_ui.grid_hit_px(lc.container, lay["src"], pos)
        if placed is not None:
            item = placed.item
            # 空槽时武器/护甲直接装备(受限武器需 6 级甲,否则进背包)
            if (item.cat == "weapon" and p.weapon is None
                    and not armor_allows(p.armor, item.def_)):
                self.add_toast(
                    f"需 {item.def_['req_armor_level']} 级护甲才能持用 {item.name}",
                    COL["bad"], 3.0)
            if item.cat == "weapon" and p.weapon is None and armor_allows(p.armor, item.def_):
                lc.container.remove_placed(placed)
                p.weapon = item
                p.reloading = False
                p.reload_t = 0
                self._log_gained(item)
                audio.play("pickup")
                self.add_toast(f"装备 {item.name}", COL["good"])
            elif item.cat == "armor" and p.armor is None:
                lc.container.remove_placed(placed)
                p.armor = item
                self._log_gained(item)
                audio.play("pickup")
                self.add_toast(f"装备 {item.name}", COL["good"])
            elif try_move(lc.container, placed, p.bag):
                self._log_gained(item)
                audio.play("pickup")
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        placed = raid_ui.grid_hit_px(p.bag, lay["dst"], pos)
        if placed is not None:
            if try_move(p.bag, placed, lc.container):
                self._unlog_gained(placed.item)   # 放回物品撤销搜刮记账
                audio.play("click")
            else:
                self.add_toast("放不进去", COL["bad"])

    def _log_gained(self, item):
        if item.is_stackable() and item.count <= 0:
            return
        self.loot_log.append(dict(id=id(item), name=item.name, count=item.count,
                                  value=item.total_price()))

    def _unlog_gained(self, item):
        """物品放回箱子/丢弃时,从搜刮记录中移除对应条目。"""
        iid = id(item)
        self.loot_log = [e for e in self.loot_log if e.get("id") != iid]

    def value_of(self, item):
        return item.total_price()
