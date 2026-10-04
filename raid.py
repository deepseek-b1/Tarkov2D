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
                      RPG_HALF_HP_ARMOR_LEVEL, TOUCH, MODES, MODE_MAP,
                      HOSTAGE_COUNT, HOSTAGE_ENEMIES, ALLY_COUNT,
                      HOSTAGE_RESCUE_TIME, REVIVE_TIME, INTERACT_RANGE, ALLY_DMG,
                      ASSAULT_ENEMIES, ASSAULT_ALLIES, ASSAULT_PLANT_TIME,
                      ASSAULT_START_POINTS, ASSAULT_KILL_POINTS, ASSAULT_DIFF,
                      SUPPORT, SUPPORT_ORDER,
                      C4_FUSE, C4_BLAST_RADIUS, C4_UNIT_DMG, C4_STRUCT_DMG,
                      C4_PLANT_RANGE, STRUCT_INFO, ALLY_STRUCT_HP, MODE_DIFF,
                      SUPPLY_RESERVE_CAP, SUPPLY_GIVE, SUPPLY_COOLDOWN, SUPPLY_RANGE,
                      STRUCT_BULLET_DMG, STRUCT_BULLET_MUL, REPAIR_RATE,
                      REPAIR_RANGE, REPAIR_MAX_WORKERS, REPAIR_SEARCH,
                      ENEMY_REINF_INTERVAL, ENEMY_REINF_SQUAD, ENEMY_REINF_CAP,
                      ENEMY_REINF_MIN_DIST, ALLY_REINF_INTERVAL,
                      ALLY_REINF_SQUAD, ALLY_REINF_CAP,
                      HQ_REACTION_DELAY, HQ_REACTION_SQUAD,
                      HQ_REACTION_COOLDOWN, REBUILD_RATE,
                      weapon_params, weapon_capacity, weapon_ammo_ids,
                      weapon_slots, weapon_attach, weapon_blast_mul, ATTACH_SLOTS,
                      fmt_rub, get_font)
from inventory import Item, try_move
from world import GameMap, LootContainer
from enemy import Scav
from npc import Ally, Hostage
from touch import TouchUI


class Structure:
    """战场设施:突袭模式里敌我双方都有指挥/通讯设施。

    能被打坏(枪弹效率很低,C4 一发入魂),也能被各自一方派人修回来。
    指挥设施 + 通讯设施是"援兵开关"。
    """

    def __init__(self, name, x, y, role, side, hp):
        self.name = name
        self.x, self.y = x, y
        self.role = role            # command / comms / depot
        self.side = side            # enemy / ally
        self.r = 22
        self.max_hp = float(hp)
        self.hp = float(hp)
        self.destroyed = False
        self.c4 = None              # 已安放的 C4:{"t": 剩余秒数}
        self.repair_workers = []    # 正在修它的单位

    @property
    def damaged(self):
        return not self.destroyed and self.hp < self.max_hp

    @property
    def label(self):
        return STRUCT_INFO.get(self.role, {}).get("label", "设施")

    def damage(self, n):
        if self.destroyed and self.hp <= 0:
            return                     # 已经炸成废墟、没人在抢修的,子弹也打不动了
        self.hp = max(0.0, self.hp - n)
        if self.hp <= 0:
            self.hp = 0.0
            self.destroyed = True
            self.c4 = None

    def repair(self, n):
        if self.destroyed:
            return
        self.hp = min(self.max_hp, self.hp + n)

    @property
    def rebuilding(self):
        """被总指挥部的检修队抢修中(炸毁了,但血量正在往回涨)。"""
        return self.destroyed and self.hp > 0

    def rebuild(self, n):
        """检修队重建:血量从 0 一点点加回来,加满才算修好。返回是否修好。"""
        self.hp = min(self.max_hp, self.hp + n)
        if self.hp >= self.max_hp:
            self.hp = self.max_hp
            self.destroyed = False
            self.c4 = None
            return True
        return False


class Objective(Structure):
    """突袭模式:要塞里的敌方指挥设施(安放 C4 炸掉)。"""

    def __init__(self, name, x, y, role):
        super().__init__(name, x, y, role, "enemy", STRUCT_INFO[role]["hp"])


class SupplyPoint:
    """我方前沿弹药库:靠近按 E 给当前武器补子弹(有上限和冷却)。"""

    def __init__(self, name, x, y):
        self.name = name
        self.x, self.y = x, y
        self.r = 20
        self.cd = 0.0


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
        ids = weapon_ammo_ids(self.weapon)
        return sum(p.item.count for p in self.bag.items if p.item.iid in ids)


class Raid:
    def __init__(self, game, difficulty=None):
        self.game = game
        self.mode = getattr(game.save, "mode", "raid")
        if self.mode not in MODES:
            self.mode = "raid"
        if self.mode == "assault":
            # 突袭是独立模式:固定强度,不参与 简单/封锁/强化封锁 三档
            self.diff_key = "assault"
            self.diff = ASSAULT_DIFF
        else:
            # 人质解救固定成强化封锁强度(不给难度档)
            forced = MODE_DIFF.get(self.mode)
            self.diff_key = forced if forced else (
                difficulty if difficulty in DIFFICULTIES
                else (getattr(game.save, "difficulty", None) or "lockdown"))
            if self.diff_key not in DIFFICULTIES:
                self.diff_key = "lockdown"
            self.diff = DIFFICULTIES[self.diff_key]
        map_key = MODE_MAP.get(self.mode) or getattr(game.save, "map_key", "border")
        self.map_key = map_key if map_key in MAPS else "border"
        self.boss_cfg = BOSSES.get(self.map_key)
        self.touch_mode = bool(getattr(game.save, "touch", False))
        self.touch = TouchUI(support=self.mode == "assault") if self.touch_mode else None
        self.aim_locked = None
        self.map = GameMap(self.map_key)
        self.map_surf = self.map.prerender()
        self.player = Player(game.save)
        self.player.x, self.player.y = self.map.spawn
        self.cam = [0, 0]
        self.shake = 0.0
        self.start_value = self._loadout_value()   # 进局装备总值(撤离收益快照基准)

        self.scavs = [Scav(k, x, y, self.diff) for k, (x, y) in self._pick_spawns()]
        if self.mode == "hostage":
            # 人质模式:匪徒固定 20 名(刷新点按房间均匀分布),没有头目/手下/作者
            random.shuffle(self.scavs)
            self.scavs = self.scavs[:HOSTAGE_ENEMIES]
        elif self.mode == "assault":
            # 突袭:大本营守军 50 名 + 要塞司令与警卫(无「作者」)
            random.shuffle(self.scavs)
            self.scavs = self.scavs[:ASSAULT_ENEMIES]
            self._spawn_boss_and_guards()
        else:
            self._spawn_boss_and_guards()
            self._spawn_author()
        # 己方单位:人质模式 3 名队友,突袭模式 10 名突击队员
        ally_n = ASSAULT_ALLIES if self.mode == "assault" else ALLY_COUNT
        self.allies = [Ally(x, y) for x, y in self.map.ally_spawns[:ally_n]] \
            if self.mode in ("hostage", "assault") else []
        self.hostages = [Hostage(x, y) for x, y in self.map.hostage_spawns[:HOSTAGE_COUNT]] \
            if self.mode == "hostage" else []
        # 突袭目标:要炸掉的敌方指挥设施 + 我方前沿设施(指挥所/通讯室)
        self.structures = []
        if self.mode == "assault":
            self.structures += [Objective(n, x, y, role)
                                for n, (x, y), role in self.map.objectives]
            self.structures += [Structure(n, x, y, role, "ally", ALLY_STRUCT_HP)
                                for n, (x, y), role in self.map.friend_structures]
        self.objectives = [s for s in self.structures if s.side == "enemy"]
        self.friend_structs = [s for s in self.structures if s.side == "ally"]
        # 我方弹药库(突袭模式:局内补弹,免得把子弹打光)
        self.supplies = [SupplyPoint(n, x, y)
                         for n, (x, y) in self.map.supplies] \
            if self.mode == "assault" else []
        self.channel = None       # 救人质 / 拉起队友 / 安放 C4 的引导状态
        # 援兵:敌方靠「通讯站 + 指挥官」,我方靠「前沿指挥所 + 前沿通讯室」
        self.enemy_reinf_t = ENEMY_REINF_INTERVAL if self.mode == "assault" else 0.0
        self.ally_reinf_t = ALLY_REINF_INTERVAL if self.mode == "assault" else 0.0
        self.enemy_waves = 0
        self.ally_waves = 0
        # 敌方总指挥部的反应:前沿守军全灭(= 失联)后 30 秒察觉,派检修队来查/修
        self.hq_t = None            # 察觉倒计时(非 None = 正在倒计时)
        self.hq_cd = 0.0            # 两次反应之间的间隔
        self.hq_teams = 0           # 已经派了几支检修队
        self.hq_team = []           # 当前这支检修队
        # 友军支援(仅突袭模式):积分靠击杀赚,呼叫要花积分
        self.support_points = ASSAULT_START_POINTS if self.mode == "assault" else 0
        self.support_cd = {k: 0.0 for k in SUPPORT_ORDER}
        self.strikes = []         # 待生效的支援:{kind,x,y,t,cfg}
        self.recon_t = 0.0        # 无人机侦察剩余时间(秒)
        self.support_calls = 0
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
        if self.boss_cfg is not None:
            if self.mode == "assault":
                self.add_toast(f"头目 {self.boss_cfg['name']} 在场 —— 击杀可爆 6 级甲与"
                               "精英机枪 M139(他镇守指挥所,但敌方援兵是总部按通讯站派的)",
                               COL["accent"], 5.0)
            else:
                self.add_toast(
                    f"头目 {self.boss_cfg['name']} 在场 —— 击杀可爆 5 级甲与专属枪械",
                    COL["accent"], 4.0)
        if self.mode == "hostage":
            self.add_toast(f"任务:救出 {HOSTAGE_COUNT} 名人质后撤离 —— 拐角有死角,小心埋伏",
                           COL["accent"], 5.0)
        if self.mode == "assault":
            self.add_toast(f"任务:给 {len(self.objectives)} 座指挥设施安 C4"
                           f"(按 E 安放,{int(C4_FUSE)} 秒后起爆,爆区 ±{C4_BLAST_RADIUS})",
                           COL["accent"], 6.0)
            self.add_toast("想掐断敌方援兵:炸掉通讯站(他们联系不上总部就没人可派了);"
                           "打死司令只掉装备,不影响援兵", COL["good"], 6.0)
            self.add_toast("友军支援 1 空袭 / 2 炮火覆盖 / 3 无人机侦察(击杀换积分)",
                           COL["good"], 5.0)
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
        """按难度决定敌人数量与位置。人质模式固定不低于 HOSTAGE_ENEMIES。"""
        spawns = list(self.map.scav_spawns)
        wanted = self.diff["scavs"]
        if self.mode == "hostage":
            # 室内图的刷新点本身就是按房间均匀摆设的,取满即可保证分散
            wanted = max(wanted, HOSTAGE_ENEMIES)
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
                        aid = random.choice(weapon_ammo_ids(it))
                        ammo = ITEMS[aid]
                        lc.container.add_item(Item(
                            aid, count=random.randint(8, min(30, ammo.get("stack", 30)))))
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
        if b is None:
            return
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

    def nearest_interactable(self):
        """最近的可交互对象:未解救人质 / 倒地球友 / 突袭模式要炸的指挥设施。"""
        p = self.player
        best, bd, kind = None, INTERACT_RANGE, None
        for h in self.hostages:
            if h.rescued:
                continue
            d = math.hypot(h.x - p.x, h.y - p.y)
            if d < bd:
                best, bd, kind = h, d, "rescue"
        for a in self.allies:
            if not a.downed:
                continue
            d = math.hypot(a.x - p.x, a.y - p.y)
            if d < bd:
                best, bd, kind = a, d, "revive"
        for o in self.objectives:
            if o.destroyed or o.c4 is not None:
                continue          # 炸过的、已经安好 C4 的都不用再管
            d = math.hypot(o.x - p.x, o.y - p.y)
            if d < bd:
                best, bd, kind = o, d, "destroy"
        for sp in self.supplies:
            d = math.hypot(sp.x - p.x, sp.y - p.y)
            if d < min(bd, SUPPLY_RANGE):
                best, bd, kind = sp, d, "supply"
        return (kind, best) if best is not None else (None, None)

    def channel_need(self, kind=None):
        """引导类交互所需的秒数。"""
        k = kind or (self.channel["kind"] if self.channel else None)
        return {"rescue": HOSTAGE_RESCUE_TIME, "revive": REVIVE_TIME,
                "destroy": ASSAULT_PLANT_TIME}.get(k, 1.0)

    def objectives_done(self):
        return len(self.objectives) > 0 and all(o.destroyed for o in self.objectives)

    def allows_extract(self):
        """突袭模式必须先把指挥设施全炸掉才能撤离。"""
        return self.mode != "assault" or self.objectives_done()

    def interact(self):
        """E / 搜刮按钮:优先救人质、拉队友、炸设施,其次搜刮容器。"""
        if self.channel is not None:
            self.channel = None
            return
        kind, ent = self.nearest_interactable()
        if kind == "supply":
            self.use_supply(ent)
            return
        if kind is not None:
            self.channel = dict(kind=kind, ent=ent, t=0.0)
            audio.play("click")
            return
        if self.loot_target:
            self.loot_target = None
        elif self.inv_open:
            self.inv_open = False
        else:
            lc = self.nearest_container()
            if lc is not None:
                self.loot_target = lc
                audio.play("click")

    def _update_channel(self, dt):
        """解救人质 / 拉起队友 / 炸设施的引导进度(需要站定且保持在附近)。"""
        if self.channel is None or self.over:
            return
        p = self.player
        ent = self.channel["ent"]
        need = self.channel_need()
        d = math.hypot(ent.x - p.x, ent.y - p.y)
        keys = pygame.key.get_pressed()
        moving = any(keys[k] for k in (pygame.K_w, pygame.K_a, pygame.K_s, pygame.K_d,
                                       pygame.K_UP, pygame.K_DOWN, pygame.K_LEFT,
                                       pygame.K_RIGHT))
        if self.touch_mode and self.touch is not None:
            moving = moving or any(abs(v) > 0.1 for v in self.touch.move_axis())
        if d > INTERACT_RANGE * 1.6:
            self.channel = None
            self.add_toast("离太远了,引导中断", COL["bad"])
            return
        self.channel["t"] += dt                  # 站定推进(边走边做也能完成,但更慢)
        if moving:
            self.channel["t"] -= dt * 0.5
        if self.channel["t"] < 0:
            self.channel["t"] = 0.0
        if self.channel["t"] >= need:
            kind = self.channel["kind"]
            self.channel = None
            if kind == "rescue":
                ent.rescued = True
                done = sum(1 for h in self.hostages if h.rescued)
                audio.play("pickup")
                self.add_toast(f"解救人质 {done}/{len(self.hostages)}", COL["good"], 3.0)
                if done >= len(self.hostages):
                    self.add_toast("全部人质已解救!带队撤离!", COL["accent"], 5.0)
            elif kind == "destroy":
                # 安放 C4:25 秒后起爆,爆区半径内一律吃伤害
                self.plant_c4(ent)
            else:
                ent.revive()
                audio.play("heal")
                self.add_toast("队友已重新站起", COL["good"], 3.0)

    def kill_scav(self, scav):
        self.scavs.remove(scav)
        self.kills += 1
        if self.mode == "assault":
            # 击杀守军换支援积分(硬点子给得多)
            self.support_points += ASSAULT_KILL_POINTS.get(scav.kind, 1)
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
            if self.mode == "assault":
                if self.comms_alive("enemy"):
                    self.add_toast("司令死了,但通讯站还在 —— 剩下的兵会直接呼叫总部,"
                                   "援兵照样来!", COL["bad"], 4.5)
                else:
                    self.add_toast("司令已击毙,通讯站也炸了 —— 总部派人也没人接头了",
                                   COL["good"], 4.5)
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
        dmg, pellets, hip, braced_s, rng, _rl, loud, burn = weapon_params(w)
        w.state["mag"] -= 1
        p.fire_cd = d["rof"]
        tx = p.x + math.cos(p.aim) * 22
        ty = p.y + math.sin(p.aim) * 22
        # 架枪(长按右键)用架枪散布;腰射用腰射散布(配件/天赋都会影响)
        spread = braced_s if self.braced else hip
        is_rpg = "rocket" in weapon_ammo_ids(w)
        for _ in range(pellets):
            ang = p.aim + random.uniform(-spread, spread)
            spd = 520.0 if is_rpg else 1100.0
            self.bullets.append(dict(x=tx, y=ty, dx=math.cos(ang) * spd,
                                     dy=math.sin(ang) * spd, dmg=dmg,
                                     owner="player", ttl=rng / spd,
                                     rpg=is_rpg, burn=burn,
                                     blast=weapon_blast_mul(w)))
        audio.play(d["sfx"])
        self.emit_noise(p.x, p.y, loud)
        self.add_particles(tx, ty, 3 if not is_rpg else 10,
                           (255, 210, 90), speed=160)
        self.shake = min(12, self.shake + (6.0 if is_rpg
                                          else (2.5 if pellets > 1 else 1.2)))

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

    def spawn_ally_bullet(self, x, y, ang):
        """队友射击:子弹只伤害敌人,不会误伤玩家。"""
        spd = 900.0
        self.bullets.append(dict(x=x, y=y, dx=math.cos(ang) * spd, dy=math.sin(ang) * spd,
                                 dmg=ALLY_DMG, owner="ally", ttl=520 / spd))
        audio.play("epm")
        self.emit_noise(x, y, 450)

    def threat_for(self, scav):
        """拾荒者的当前目标:优先玩家;玩家不可见而被队友看得见时打队友。"""
        p = self.player
        if math.hypot(p.x - scav.x, p.y - scav.y) <= scav.d["view"] \
                and self.map.los_clear(scav.x, scav.y, p.x, p.y):
            return p
        best, bd = None, scav.d["view"]
        for a in self.allies:
            if getattr(a, "downed", False):
                continue
            d = math.hypot(a.x - scav.x, a.y - scav.y)
            if d < bd and self.map.los_clear(scav.x, scav.y, a.x, a.y):
                best, bd = a, d
        return best if best is not None else p

    def explode(self, x, y, dmg, owner, src=None, blast_mul=1.0, radius=None,
                friendly=False, struct_dmg=None):
        """火箭弹/支援火力/C4 爆炸:半径内的拾荒者一律吃伤害(不用瞄准);
        玩家被波及则按火箭弹规则判定(穿 6 级甲半血,否则阵亡)。src 为发射者,不吃自己的爆炸。
        radius 可覆盖溅射半径(友军支援/C4 用);friendly=True 时对玩家按普通伤害结算
        (护甲减伤,不会被自己叫的空袭一炮带走);struct_dmg 为对设施的伤害。"""
        audio.play("sg")
        self.shake = min(14, self.shake + 8)
        self.add_particles(x, y, 26, (255, 170, 60), speed=240)
        self.add_particles(x, y, 14, (255, 240, 180), speed=150)
        self.emit_noise(x, y, 900)
        rad = RPG_BLAST_RADIUS * blast_mul if radius is None else radius
        for s in list(self.scavs):
            if s is src:
                continue
            if math.hypot(s.x - x, s.y - y) <= rad:
                s.damage(dmg)
                if s.dead:
                    self.kill_scav(s)
        if self.structures:
            self.damage_structures_at(x, y, rad,
                                      dmg if struct_dmg is None else struct_dmg,
                                      owner=owner)
        p = self.player
        if math.hypot(p.x - x, p.y - y) <= rad:
            if friendly:
                if self.mode == "assault":
                    self.add_toast("被友军火力波及!", COL["bad"], 2.6)
                p.take_damage(dmg * 0.5, self)
            else:
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
                                     src=b.get("src"),
                                     blast_mul=b.get("blast", 1.0))
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
                # 设施也能被枪弹啃(效率很低,想拆还是得靠 C4)
                if self.structures:
                    for st in self.structures:
                        if st.destroyed:
                            continue
                        own = (b["owner"] in ("player", "ally")) == (st.side == "ally")
                        if own:
                            continue
                        if math.hypot(st.x - b["x"], st.y - b["y"]) < st.r:
                            st.damage(STRUCT_BULLET_DMG + b["dmg"] * STRUCT_BULLET_MUL)
                            self.add_particles(b["x"], b["y"], 3, (210, 200, 150))
                            if st.destroyed:
                                self.add_toast(f"{st.name} 被摧毁!", COL["accent"], 3.4)
                            dead = True
                            break
                    if dead:
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
                if b["owner"] in ("player", "ally"):
                    for s in self.scavs:
                        if math.hypot(s.x - b["x"], s.y - b["y"]) < s.r + 3:
                            s.damage(b["dmg"])
                            if b.get("burn"):
                                s.burn_t = 1.5
                                s.burn_dps = b["burn"]
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
                    else:
                        for a in self.allies:
                            if a.downed:
                                continue
                            if math.hypot(a.x - b["x"], a.y - b["y"]) < a.r + 2:
                                a.take_damage(b["dmg"], self)
                                dead = True
                                break
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
        if w.state.get("mag", 0) >= weapon_capacity(w):
            return
        if p.reserve_count() <= 0:
            self.add_toast("没有可用弹药!", COL["bad"])
            return
        p.reload_t = weapon_params(w)[5]
        p.reloading = True
        audio.play("reload")

    def _finish_reload(self):
        p = self.player
        w = p.weapon
        p.reloading = False        # 装填完成,状态自洽(外部直接调用也安全)
        p.reload_t = 0.0
        if w is None:
            return
        cap = weapon_capacity(w)
        need = cap - w.state.get("mag", 0)
        got = 0
        ids = weapon_ammo_ids(w)
        for placed in list(p.bag.items):
            if placed.item.iid in ids and need > 0:
                take = min(need, placed.item.count)
                got += take
                need -= take
                w.state["loaded"] = placed.item.iid   # 记录实际装填的弹种
                placed.item.count -= take
                if placed.item.count <= 0:
                    p.bag.remove_placed(placed)
        if got:
            w.state["mag"] = w.state.get("mag", 0) + got
            self.add_toast(f"装填完成 {w.state['mag']}/{cap}", COL["good"])

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
        elif item.cat == "attach":
            self.install_attachment(p, placed, p.bag)

    def install_attachment(self, p, placed, src, stash_mode=False):
        """把配件装到当前武器上(把旧配件放回 src)。"""
        item = placed.item
        w = p.weapon
        slot = item.def_.get("slot")
        if w is None:
            self.add_toast("先装备武器才能装配件", COL["bad"])
            return
        if slot not in weapon_slots(w.iid):
            self.add_toast(f"{w.name} 不支持{ATTACH_SLOTS.get(slot, '该')}配件",
                           COL["bad"], 3.0)
            return
        old = weapon_attach(w).get(slot)
        if old is not None and not src.add_item(Item(old)):
            self.add_toast("空间不足,无法换下旧配件", COL["bad"])
            return
        src.remove_placed(placed)
        w.state.setdefault("attach", {})[slot] = item.iid
        cap = weapon_capacity(w)
        if w.state.get("mag", 0) > cap:
            w.state["mag"] = cap            # 换小弹夹时截断已装填
        audio.play("click")
        self.add_toast(f"已安装 {item.name}({ATTACH_SLOTS.get(slot, '')})",
                       COL["good"], 3.0)

    # ---------- 友军支援(突袭模式) ----------
    def support_state(self, key):
        """返回 (是否可用, 说明文字)。"""
        cfg = SUPPORT[key]
        if self.mode != "assault" or self.over:
            return False, "只有突袭模式能呼叫友军支援"
        cd = self.support_cd.get(key, 0.0)
        if cd > 0:
            return False, f"{cfg['name']}冷却中({int(cd) + 1}s)"
        if self.support_points < cfg["cost"]:
            return False, f"积分不足:{self.support_points}/{cfg['cost']}"
        return True, ""

    def _support_target(self):
        """支援落点:电脑 = 鼠标位置;手机 = 锁定的敌人(没有就取身前一段距离)。"""
        p = self.player
        if self.touch_mode:
            if self.aim_locked is not None:
                return self.aim_locked.x, self.aim_locked.y
            return p.x + math.cos(p.aim) * 320, p.y + math.sin(p.aim) * 320
        mpx, mpy = pygame.mouse.get_pos()
        return self.cam[0] + mpx, self.cam[1] + mpy

    def call_support(self, key, x, y):
        """呼叫友军支援:花积分,延迟后落到 (x, y)。"""
        if key not in SUPPORT:
            return False
        ok, why = self.support_state(key)
        if not ok:
            self.add_toast(why, COL["bad"], 2.8)
            audio.play("empty")
            return False
        cfg = SUPPORT[key]
        self.support_points -= cfg["cost"]
        self.support_cd[key] = cfg["cd"]
        self.support_calls += 1
        self.strikes.append(dict(kind=key, x=x, y=y, t=cfg["delay"], cfg=cfg))
        if key == "recon":
            self.add_toast(f"无人机已在路上(-{cfg['cost']} 积分):{cfg['delay']:.0f}s 后标记守军",
                           COL["accent"], 3.2)
        elif key == "barrage":
            self.add_toast(f"炮火覆盖呼叫成功(-{cfg['cost']} 积分):{cfg['delay']:.0f}s 后落弹",
                           COL["accent"], 3.4)
        else:
            self.add_toast(f"空袭呼叫成功(-{cfg['cost']} 积分):{cfg['delay']:.0f}s 后投弹",
                           COL["accent"], 3.4)
        audio.play("click")
        return True

    def _update_support(self, dt):
        """支援计时:冷却、延迟、无人机侦察、落弹。"""
        if self.mode != "assault":
            return
        for k in self.support_cd:
            if self.support_cd[k] > 0:
                self.support_cd[k] = max(0.0, self.support_cd[k] - dt)
        self.recon_t = max(0.0, self.recon_t - dt)
        if not self.strikes:
            return
        keep = []
        for st in self.strikes:
            if st["kind"] == "shell":
                keep.append(st)          # 落弹只需倒计时,下一段处理
                continue
            st["t"] -= dt
            if st["t"] > 0:
                keep.append(st)
                continue
            kind, cfg = st["kind"], st["cfg"]
            if kind == "recon":
                self.recon_t = float(cfg["dur"])
                self.add_toast(f"无人机到位:守军位置全图标记 {int(cfg['dur'])}s",
                               COL["good"], 3.2)
                audio.play("pickup")
            else:
                # 空袭 / 炮火覆盖:展开成一串落弹(炮弹带各自的延时)
                n = int(cfg["bombs"]) if kind == "airstrike" else int(cfg["shells"])
                gap = 0.22 if kind == "airstrike" else cfg["gap"]
                for i in range(n):
                    ang = random.uniform(0, math.tau)
                    rad = random.uniform(0, cfg["scatter"])
                    keep.append(dict(kind="shell", x=st["x"] + math.cos(ang) * rad,
                                     y=st["y"] + math.sin(ang) * rad, t=i * gap,
                                     cfg=cfg, radius=cfg["radius"], dmg=cfg["dmg"]))
                audio.play("sg")
        self.strikes = []
        ready = []
        for st in keep:
            if st["kind"] == "shell":
                st["t"] -= dt            # 落弹的延时(展开时已经扣过一帧,这里只扣延迟)
                if st["t"] <= 0:
                    ready.append(st)
                else:
                    self.strikes.append(st)
            else:
                self.strikes.append(st)
        for sh in ready:
            self.explode(sh["x"], sh["y"], sh["dmg"], "support",
                         radius=sh["radius"], friendly=True)

    # ---------- 设施 / C4 / 援兵(突袭模式) ----------
    def comms_alive(self, side):
        return any(s.role == "comms" and not s.destroyed
                   for s in self.structures if s.side == side)

    def command_alive(self, side):
        return any(s.role == "command" and not s.destroyed
                   for s in self.structures if s.side == side)

    def commander(self):
        for s in self.scavs:
            if getattr(s, "tag", None) == "boss":
                return s
        return None

    def reinforce_reason(self, side):
        """援兵还能不能来 + 原因(给 HUD/提示用)。

        敌方靠的是「通讯站连总部」:通讯站在,总部就一直往前沿调遣敌人 ——
        司令死不死都一样(剩下的兵自己也会去呼叫总部要人)。
        """
        if side == "ally":
            if not self.command_alive("ally"):
                return False, "前沿指挥所被毁"
            if not self.comms_alive("ally"):
                return False, "前沿通讯室被毁"
            return True, "指挥所+通讯室完好"
        if not self.comms_alive("enemy"):
            return False, "通讯站已炸毁,联系不上总部"
        return True, "通讯站在,总部持续调遣"

    def use_supply(self, sp):
        """我方弹药库:给当前武器补一盒弹药(有上限,免得变成无限弹药)。"""
        p = self.player
        if sp.cd > 0:
            self.add_toast(f"{sp.name}补给中,{sp.cd:.0f} 秒后再来", COL["text_dim"], 2.2)
            return False
        if p.weapon is None:
            self.add_toast("手上没武器,不知道该给你补什么弹", COL["bad"])
            return False
        ids = weapon_ammo_ids(p.weapon)
        iid = p.weapon.state.get("loaded")
        if iid not in ids:
            iid = ids[0]
        have = sum(pl.item.count for pl in p.bag.items if pl.item.iid == iid)
        add = min(int(SUPPLY_GIVE), int(SUPPLY_RESERVE_CAP) - have)
        if add <= 0:
            self.add_toast(f"备弹已满({have}/{SUPPLY_RESERVE_CAP}),先打掉一些", COL["text_dim"], 2.4)
            return False
        if not p.bag.add_item(Item(iid, count=add)):
            self.add_toast("背包塞不下弹药,先清点空间", COL["bad"])
            return False
        sp.cd = SUPPLY_COOLDOWN
        audio.play("pickup")
        self.add_toast(f"{sp.name}:补给 {ITEMS[iid]['name']} ×{add}"
                       f"(备弹 {have + add}/{SUPPLY_RESERVE_CAP})", COL["good"], 3.0)
        return True

    def _update_supplies(self, dt):
        for sp in self.supplies:
            if sp.cd > 0:
                sp.cd = max(0.0, sp.cd - dt)

    def plant_c4(self, ent):
        """在设施上安放 C4(25 秒后起爆,爆区半径固定)。"""
        ent.c4 = dict(t=C4_FUSE)
        audio.play("click")
        self.add_toast(f"C4 已安放:{ent.name} —— {int(C4_FUSE)} 秒后起爆!"
                       f"(爆区半径 {C4_BLAST_RADIUS},快离开)", COL["bad"], 4.5)

    def _update_c4(self, dt):
        for st in self.structures:
            if st.c4 is None or st.destroyed:
                continue
            st.c4["t"] -= dt
            if st.c4["t"] <= 0:
                self.detonate_c4(st)

    def detonate_c4(self, ent):
        """C4 起爆:爆区半径内所有单位吃伤害,设施直接炸毁。"""
        ent.c4 = None
        audio.play("sg")
        self.add_toast(f"{ent.name} 的 C4 起爆!", COL["accent"], 3.4)
        self.explode(ent.x, ent.y, C4_UNIT_DMG, "player",
                     radius=C4_BLAST_RADIUS, struct_dmg=C4_STRUCT_DMG)
        if not self.objectives_done() and ent.side == "enemy" and ent.destroyed:
            done = sum(1 for o in self.objectives if o.destroyed)
            self.add_toast(f"敌方设施已摧毁 {done}/{len(self.objectives)}",
                           COL["good"], 3.4)
        if self.objectives_done():
            self.add_toast("全部指挥设施已摧毁!撤出要塞!", COL["accent"], 5.0)

    def _assign_repair(self, st, pool, dt):
        """派最近的人去修设施(双方通用)。"""
        st.repair_workers = [w for w in st.repair_workers
                             if getattr(w, "hp", 1) > 0
                             and not getattr(w, "downed", False)
                             and getattr(w, "repair_target", None) is st]
        if st.destroyed or not st.damaged:
            return
        if len(st.repair_workers) < REPAIR_MAX_WORKERS:
            cands = []
            for u in pool:
                if getattr(u, "repair_target", None) is not None:
                    continue
                d = math.hypot(u.x - st.x, u.y - st.y)
                if d <= REPAIR_SEARCH:
                    cands.append((d, u))
            cands.sort(key=lambda t: t[0])
            for _d, u in cands[:REPAIR_MAX_WORKERS - len(st.repair_workers)]:
                u.repair_target = st
                st.repair_workers.append(u)
        # 站到位的修理单位按秒回血
        rate = REPAIR_RATE * dt * len([w for w in st.repair_workers
                                       if math.hypot(w.x - st.x, w.y - st.y)
                                       <= REPAIR_RANGE])
        if rate:
            st.repair(rate)

    def _update_repair(self, dt):
        if self.mode != "assault":
            return
        for st in self.friend_structs:
            self._assign_repair(st, self.allies, dt)
        for st in self.objectives:
            self._assign_repair(st, self.scavs, dt)
        # 修好了/目标没了就放人(但总指挥部检修队的目标是"炸毁的设施",不能放)
        for st in self.structures:
            if st.destroyed or not st.damaged:
                keep = []
                for w in st.repair_workers:
                    if getattr(w, "tag", None) == "repair":
                        keep.append(w)
                        continue
                    if getattr(w, "repair_target", None) is st:
                        w.repair_target = None
                st.repair_workers = keep

    def _spawn_enemy_wave(self):
        """敌方援兵:从要塞纵深赶来的守军。"""
        p = self.player
        spots = [pos for _k, pos in self.map.scav_spawns
                 if math.hypot(pos[0] - p.x, pos[1] - p.y) >= ENEMY_REINF_MIN_DIST]
        if not spots:
            spots = [pos for _k, pos in self.map.scav_spawns]
        random.shuffle(spots)
        kinds = ["ar", "ar", "shotgun", "pistol"]
        for i in range(int(ENEMY_REINF_SQUAD)):
            if len(self.scavs) >= ENEMY_REINF_CAP:
                break
            x, y = spots[i % len(spots)]
            s = Scav(kinds[i % len(kinds)], x + random.randint(-10, 10),
                     y + random.randint(-10, 10), self.diff)
            s.state = "search"
            s.alert = (p.x, p.y)
            self.scavs.append(s)
        self.enemy_waves += 1
        audio.play("kill")
        self.add_toast(f"敌方援兵抵达(第 {self.enemy_waves} 波)!"
                       "总部通过通讯站在往前沿调人 —— 想断援兵只能炸通讯站",
                       COL["bad"], 3.6)

    def _spawn_ally_wave(self):
        """我方援兵:从前沿指挥所补上来的突击队员。"""
        if len(self.allies) >= ALLY_REINF_CAP:
            return
        base = None
        for st in self.friend_structs:
            if st.role == "command" and not st.destroyed:
                base = st
                break
        if base is None and self.friend_structs:
            base = self.friend_structs[0]
        if base is None:
            return
        n = int(ALLY_REINF_SQUAD)
        for i in range(n):
            if len(self.allies) >= ALLY_REINF_CAP:
                break
            spot = self.map.walkable_near(int(base.x // TILE) + i,
                                          int(base.y // TILE)) or \
                (int(base.x // TILE), int(base.y // TILE))
            self.allies.append(Ally(spot[0] * TILE + TILE // 2,
                                    spot[1] * TILE + TILE // 2))
        self.ally_waves += 1
        audio.play("pickup")
        self.add_toast(f"我方援兵加入战场(第 {self.ally_waves} 波)", COL["good"], 3.2)

    def _update_reinforce(self, dt):
        if self.mode != "assault":
            return
        if self.reinforce_reason("enemy")[0]:
            self.enemy_reinf_t -= dt
            if self.enemy_reinf_t <= 0:
                self.enemy_reinf_t = ENEMY_REINF_INTERVAL
                self._spawn_enemy_wave()
        if self.reinforce_reason("ally")[0]:
            self.ally_reinf_t -= dt
            if self.ally_reinf_t <= 0:
                self.ally_reinf_t = ALLY_REINF_INTERVAL
                self._spawn_ally_wave()

    # ---------- 敌方总指挥部的反应(前沿失联 -> 派检修队) ----------
    def _update_hq(self, dt):
        """守军全灭 = 前沿失联:30 秒后总指挥部察觉异常,派检修队来查。

        检修队到了通讯站:如果通讯站被炸毁,他们就地抢修(修好 = 敌方援兵恢复);
        如果通讯站完好,他们查完就原地驻防(不会额外增援)。
        """
        if self.mode != "assault" or self.over:
            return
        if self.hq_cd > 0:
            self.hq_cd = max(0.0, self.hq_cd - dt)
        if self.hq_t is None:
            # 场上一个守军都没有 -> 前沿失联,开始倒计时
            if not self.scavs and self.hq_cd <= 0:
                self.hq_t = HQ_REACTION_DELAY
                self.add_toast(f"敌方总指挥部察觉到前沿失去联络:{int(HQ_REACTION_DELAY)} "
                               "秒后会派人来看", COL["bad"], 4.5)
            return
        self.hq_t -= dt
        if self.hq_t > 0:
            return
        self.hq_t = None
        self.hq_cd = HQ_REACTION_COOLDOWN
        self._send_hq_team()

    def _send_hq_team(self):
        """从要塞后方派一支检修队(带枪的工兵),让他们去通讯站。"""
        comms = next((s for s in self.objectives if s.role == "comms"), None)
        p = self.player
        spots = [pos for _k, pos in self.map.scav_spawns
                 if math.hypot(pos[0] - p.x, pos[1] - p.y) >= ENEMY_REINF_MIN_DIST]
        if not spots:
            spots = [pos for _k, pos in self.map.scav_spawns]
        random.shuffle(spots)
        self.hq_team = []
        for i in range(int(HQ_REACTION_SQUAD)):
            x, y = spots[i % len(spots)]
            s = Scav("ar", x + random.randint(-12, 12), y + random.randint(-12, 12),
                     self.diff)
            s.tag = "repair"
            if comms is not None:
                s.repair_target = comms      # 直奔通讯站
            self.scavs.append(s)
            self.hq_team.append(s)
        self.hq_teams += 1
        audio.play("kill")
        if comms is not None and comms.destroyed:
            self.add_toast(f"总指挥部派来第 {self.hq_teams} 支检修队:"
                           "通讯站是坏的,他们会把它修好!", COL["bad"], 5.0)
        else:
            self.add_toast(f"总指挥部派来第 {self.hq_teams} 支巡检队:"
                           "通讯站完好,他们查完就留下驻防", COL["accent"], 5.0)

    def _update_rebuild(self, dt):
        """检修队就地抢修被炸毁的设施(修好 = 该设施恢复功能)。"""
        for u in list(self.scavs):
            st = getattr(u, "repair_target", None)
            if st is None or not st.destroyed:
                continue
            if math.hypot(u.x - st.x, u.y - st.y) > REPAIR_RANGE:
                continue
            if st.rebuild(REBUILD_RATE * dt):
                u.repair_target = None
                if st.role == "comms":
                    self.add_toast(f"{st.name} 已被敌方检修队修复 —— 敌方援兵恢复!",
                                   COL["bad"], 5.0)
                else:
                    self.add_toast(f"{st.name} 被敌方检修队修复了!", COL["bad"], 4.0)
                self.emit_noise(st.x, st.y, 700)
        # 检修队全灭/目标没了就清掉记录
        self.hq_team = [u for u in self.hq_team if u in self.scavs]

    def damage_structures_at(self, x, y, radius, dmg, owner="player"):
        """爆炸波及设施:自己人的爆炸不会炸自己人的设施。"""
        for st in self.structures:
            if st.destroyed:
                continue
            own = (owner in ("player", "ally")) == (st.side == "ally")
            if own:
                continue
            if math.hypot(st.x - x, st.y - y) <= radius + st.r:
                st.damage(dmg)
                if st.destroyed:
                    self.add_toast(f"{st.name} 被炸毁!", COL["accent"], 3.4)

    def _update_burn(self, dt):
        """龙息弹燃烧伤害。"""
        for s in list(self.scavs):
            if getattr(s, "burn_t", 0.0) > 0:
                s.burn_t -= dt
                s.damage(s.burn_dps * dt)
                if s.dead:
                    self.kill_scav(s)

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
        rescued = sum(1 for h in self.hostages if h.rescued)
        objs_done = sum(1 for o in self.objectives if o.destroyed)
        if self.mode == "hostage":
            mission = len(self.hostages) > 0 and rescued >= len(self.hostages)
        elif self.mode == "assault":
            mission = self.objectives_done()
        else:
            mission = True
        self.result = dict(kind=kind, kills=self.kills, gained=gained,
                           n=len(self.loot_log), time=RAID_TIME - self.time_left,
                           entries=self.loot_log,
                           mode=self.mode, rescued=rescued,
                           hostages=len(self.hostages),
                           objectives=len(self.objectives),
                           objectives_done=objs_done,
                           support_calls=self.support_calls,
                           support_points=self.support_points,
                           enemy_waves=self.enemy_waves,
                           ally_waves=self.ally_waves,
                           hq_teams=self.hq_teams,
                           commander_killed=(self.mode == "assault"
                                             and self.commander() is None),
                           mission=mission)
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
                    self.interact()
                elif ev.key == pygame.K_r:
                    if not (self.inv_open or self.loot_target):
                        self.start_reload()
                elif ev.key == pygame.K_h:
                    if not (self.inv_open or self.loot_target):
                        self.quick_heal()
                elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3) and self.mode == "assault":
                    # 友军支援快捷呼叫:1 空袭 / 2 炮火覆盖 / 3 无人机侦察
                    if not (self.inv_open or self.loot_target):
                        idx = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2}[ev.key]
                        tx, ty = self._support_target()
                        self.call_support(SUPPORT_ORDER[idx], tx, ty)
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
                    self.interact()
                elif name == "bag":
                    self.loot_target = None
                    self.inv_open = not self.inv_open
                elif name in ("sup1", "sup2", "sup3"):
                    idx = {"sup1": 0, "sup2": 1, "sup3": 2}[name]
                    tx, ty = self._support_target()
                    self.call_support(SUPPORT_ORDER[idx], tx, ty)
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
        if zone is not None and not self.allows_extract():
            # 突袭模式:指挥设施没炸完不让撤
            if "locked" not in self.warned:
                self.warned.add("locked")
                self.add_toast("先炸掉全部指挥设施才能撤离!", COL["bad"], 3.6)
            zone = None
            self.extract_t = max(0.0, self.extract_t - dt * 3)
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
        for a in self.allies:
            a.update(self, dt)
        for h in self.hostages:
            h.update(self, dt)
        self._update_burn(dt)
        self._update_channel(dt)
        self._update_support(dt)
        self._update_c4(dt)
        self._update_repair(dt)
        self._update_reinforce(dt)
        self._update_hq(dt)
        self._update_rebuild(dt)
        self._update_supplies(dt)
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
            elif placed.item.cat in ("weapon", "armor", "attach"):
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
