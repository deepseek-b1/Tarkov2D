# -*- coding: utf-8 -*-
"""战局:搜刮-战斗-撤离。玩家操作、子弹、战利品、撤离引导、阵亡结算。"""
import math
import random

import pygame

import audio
import coop as coop_mod
import story as story_mod
import uikit
from settings import (W, H, TILE, COL, PLAYER, RAID_TIME, EXTRACT_TIME,
                      INTERACT_DIST, ITEMS, LOOT, SCAV_DROPS, DIFFICULTIES,
                      CLASSIFIED, DOC_SPAWN_CHANCE, armor_allows,
                      MAPS, BOSSES, GUARD_ARMOR_DROP, GUARD_ARMORS,
                      AUTHOR_BOSS, AUTHOR_MIN_DIFFICULTY, RPG_BLAST_RADIUS,
                      RPG_HALF_HP_ARMOR_LEVEL, TOUCH, MODES, MODE_MAP,
                      HOSTAGE_COUNT, HOSTAGE_ENEMIES, ALLY_COUNT,
                      HOSTAGE_RESCUE_TIME, REVIVE_TIME, INTERACT_RANGE, ALLY_DMG,
                      ASSAULT_ENEMIES, ASSAULT_ALLIES, ASSAULT_PLANT_TIME,
                      ASSAULT_START_POINTS, ASSAULT_KILL_POINTS, ASSAULT_DIFF,
                      STORY_DIFF, STORY_TIMES, STORY_FINAL_TIME,
                      STORY_WANTED_BONUS, STORY_INTERACT,
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
                      weapon_fire_mode, weapon_fire_modes, cycle_fire_mode,
                      fire_mode_name, BURST_COUNT,
                      FOG_MOVE_STEP, FOG_VIS_REFRESH, FOG_VIS_RADIUS,
                      MOVE_AIM_MUL, MOVE_RELOAD_MUL,
                      COOP, COOP_MODES,
                      fmt_rub, get_font)
import bindings
from inventory import Item, try_move
from world import GameMap, LootContainer
from enemy import Scav
from npc import Ally, Hostage
import touch as touch_mod
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


class StoryPoint:
    """剧情模式的关键点:一个目标(搜索/下载/取得/对话)或一段 NPC 对白。"""

    def __init__(self, x, y, obj=None, dia=None):
        self.x, self.y = x, y
        self.r = 20
        self.obj = obj        # story.py 的目标 dict(id/name/kind/need/effects)
        self.dia = dia        # 或一段对白 dict(speaker/lines/choices)

    @property
    def name(self):
        if self.obj is not None:
            return self.obj["name"]
        if self.dia is not None:
            return self.dia["speaker"]
        return ""

    @property
    def kind(self):
        if self.obj is not None:
            return self.obj["kind"]
        if self.dia is not None:
            return "talk"
        return ""


class Player:
    def __init__(self, sd):
        self.x, self.y = 0.0, 0.0
        self.max_hp = PLAYER["hp"]
        self.hp = self.max_hp
        self.weapon = sd.weapon   # 与存档共用引用,撤离后自然持久化
        self.armor = sd.armor
        self.helmet = getattr(sd, "helmet", None)   # 夜视头盔(黑暗模式)
        self.bag = sd.bag
        self.safe = sd.safe       # 保险箱:与存档共用引用,阵亡不丢
        self.aim = 0.0
        self.fire_cd = 0.0
        self.burst_left = 0       # 三连发剩余待发数(按 G 可切换射击模式)
        self.reload_t = 0.0
        self.reloading = False
        self.hurt_flash = 0.0
        self.dead = False         # 双人合作:倒下的玩家不再操作/不再被瞄准
        self.extracted = False    # 已经撤出战场(双人合作:另一个还能继续打)
        self.out = False          # 已离场(阵亡或已撤离)—— 操作/AI/伤害一律忽略
        self.extract_gain = None  # 撤离那一刻的净收益(结算用)

    def fire_mode(self):
        """当前武器的射击模式(semi/burst/auto)。"""
        return weapon_fire_mode(self.weapon)

    def cycle_fire_mode(self):
        """按 G 切到下一个射击模式;只有单发的枪返回 None。"""
        self.burst_left = 0
        return cycle_fire_mode(self.weapon)

    def take_damage(self, dmg, raid, rpg=False):
        if self.out:       # 双人合作里已经倒下 / 已经撤离的不再吃伤害
            return
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
                        and raid.can_revive(self)):
                    raid.mark_revive(self)
                    self.hp = max(1, int(self.max_hp * 0.3))
                    raid.add_toast("倒地自救成功!(本局仅一次)", COL["good"], 3.6)
                    return
                self.hp = 0
                raid.player_down(self)
            return
        if self.armor is not None:
            dmg *= (1 - self.armor.def_.get("reduce", 0))
        if self.helmet is not None:
            # 头盔再分担一部分伤害(乘在护甲减伤之后;火箭弹规则只看护甲等级)
            dmg *= (1 - self.helmet.def_.get("reduce", 0))
        dmg = max(1, round(dmg))
        self.hp -= dmg
        self.hurt_flash = 0.45
        audio.play("hurt")
        raid.shake = min(12, raid.shake + 5)
        raid.add_particles(self.x, self.y, 5, (200, 50, 50))
        if self.hp <= 0:
            # 6级甲自带的倒地自救:每局一次,免于阵亡
            if (self.armor is not None and self.armor.def_.get("revive")
                    and raid.can_revive(self)):
                raid.mark_revive(self)
                self.hp = max(1, int(self.max_hp * 0.3))
                self.hurt_flash = 1.0
                raid.shake = 12
                raid.add_particles(self.x, self.y, 18, (120, 220, 255), speed=150)
                audio.play("heal")
                raid.add_toast("倒地自救成功!(本局仅一次)", COL["good"], 3.6)
                return
            self.hp = 0
            raid.player_down(self)

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
        elif self.mode == "story":
            # 剧情模式:固定强度(有分支与结局,不吃难度档)
            self.diff_key = "story"
            self.diff = STORY_DIFF
        else:
            # 人质解救 / 黑暗行动固定成强化封锁强度(不给难度档)
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
        # 玩家自定义的触屏按键布局(设置页编辑)要在建 TouchUI 前生效
        touch_mod.apply_layout(getattr(game.save, "touch_layout", None))
        self.touch = TouchUI(support=self.mode == "assault") if self.touch_mode else None
        if self.touch is not None:
            # 「模式」按钮先写上当前武器的射击模式(update 里每帧刷新)
            self.touch.mode_label = fire_mode_name(
                weapon_fire_mode(getattr(game.save, "weapon", None)))
        self.aim_locked = None
        self.map = GameMap(self.map_key)
        self.map_surf = self.map.prerender()
        # 剧情模式的装备由 game.start_raid 里的系统配发负责(这里只留提示清单)
        self.story_issued = list(getattr(game, "story_issued", []) or [])
        self.player = Player(game.save)
        self.player.x, self.player.y = self.map.spawn
        # ---- 双人合作:第二位玩家(键盘操作,装备由系统配发,见 coop.py) ----
        self.coop = (bool(getattr(game.save, "coop", False))
                     and self.mode in COOP_MODES and not self.touch_mode)
        self.player2 = None
        self.p2_kit = None
        self.p2_revive_used = False     # P2 的 6 级甲自救(每局一次)
        self.p2_take = None             # P2 的自动搜刮状态
        self.p2_extract_t = 0.0         # P2 的撤离引导进度
        self.p2_fire_edge = False       # P2 的点射沿(键盘按下那一帧)
        self.p2_start_value = 0
        if self.coop:
            self.p2_kit = coop_mod.P2Kit()
            self.player2 = Player(self.p2_kit)
            self.player2.x, self.player2.y = self._p2_spawn()
            self.player2.aim = self.player.aim
        self.cam = [0, 0]
        self.shake = 0.0
        self.start_value = self._loadout_value()   # 进局装备总值(撤离收益快照基准)
        if self.coop:
            self.p2_start_value = self._loadout_value(self.player2)

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
        elif self.mode == "story":
            # 剧情模式:城区守军,通缉越高人越多;头目/精英由剧情决定
            wanted = story_mod.st(game.save)["wanted"]
            want_n = int(STORY_DIFF["scavs"]) + wanted * STORY_WANTED_BONUS
            random.shuffle(self.scavs)
            self.scavs = self.scavs[:want_n]
            self._spawn_story_bosses()
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
        # 剧情模式《灰区二日》:当前时段目标 + 关键点 + 对白
        self.story_sd = game.save if self.mode == "story" else None
        self.story_mission = story_mod.mission(game.save) if self.mode == "story" else None
        self.story_targets = []
        if self.mode == "story":
            for (sx, sy) in self.map.story_points:
                o = story_mod.objective_by_point(game.save, sx, sy)
                dia = story_mod.dialogues_at(game.save, sx, sy) if o is None else None
                if o is not None or dia is not None:
                    self.story_targets.append(StoryPoint(sx, sy, o, dia))
        self.dialogue = None      # 对白面板:speaker/lines/idx/choices/reply/at
        self.cutscene = None      # 剧情演出:{kind,x,y,t,dur}(救人/处决/给药/抢夺)
        self.floaters = []        # 飘字:[{text,x,y,t,dur,col}]
        self.subtitle = None      # 录音字幕:{text,t,dur}
        self.captive_state = None  # 俘虏:None 待决定 / "freed" 放走 / "dead" 被处决
        self.story_log = []       # 本次出击的剧情提示(结算页用)
        self.containers = list(self.map.loot)
        # 强化封锁:机密文件是 0.1% 的孤品(每局判定一次),命中才刷在随机保险箱
        doc_spawned = (self.diff_key == "hardened"
                       and random.random() < DOC_SPAWN_CHANCE)
        if doc_spawned:
            safes = [c for c in self.containers if c.kind == "val"]
            if safes:
                random.choice(safes).container.add_item(Item(CLASSIFIED))
            else:
                doc_spawned = False
        self.doc_spawned = doc_spawned
        for lc in self.containers:
            self._gen_loot(lc)

        self.bullets = []
        self.particles = []
        self.toasts = []
        if self.doc_spawned:
            self.add_toast("天降鸿运:这局某个保险箱里藏了一份机密文件(价值 ¥500 万)!",
                           COL["accent"], 5.0)
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
        if self.mode == "night":
            from settings import weapon_beam as _beam, helmet_nvg as _nvg

            def _light_of(q):
                src = []
                helmet = _nvg(getattr(q, "helmet", None))
                light = _beam(getattr(q, "weapon", None))
                if helmet is not None:
                    src.append(f"夜视 {int(helmet[0])}")
                if light is not None:
                    src.append(f"枪灯 {int(light[0])}")
                return src

            mine = _light_of(self.player)
            if self.coop:
                # 双人:两人各拿系统的满配枪(都带强光探照灯),谁没灯单独提醒
                other = _light_of(self.player2) if self.player2 is not None else []
                self.add_toast("黑暗行动 · 光源 P1:" + ("+".join(mine) or "无")
                               + " / P2:" + ("+".join(other) or "无"),
                               COL["good"] if (mine and other) else COL["bad"], 6.0)
            elif not mine:
                self.add_toast("黑暗行动:你身上没有任何光源 —— 只看得到脚边一小圈!",
                               COL["bad"], 6.5)
                self.add_toast("去交易所买「战术手电」(装到枪上)或「夜视头盔」再来",
                               COL["accent"], 6.5)
            else:
                self.add_toast("黑暗行动 · 光源:" + " + ".join(mine), COL["good"], 5.5)
            self.add_toast("只有亮区里的敌人才看得见(也才会被自动瞄准);敌人可不受你的灯光限制",
                           COL["accent"], 6.0)
        if self.coop:
            self.add_toast("双人合作:配发装备 · 各自撤离(谁先撤谁那份先进仓库)· "
                           "P2 靠近箱子按交互自动搜刮", COL["good"], 9.0)
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
        if self.mode == "story":
            # 开场无线电 + 当前时段目标
            st_now = story_mod.st(game.save)
            self.add_toast(f"第 {st_now['day']} 天 · "
                           f"{story_mod.PERIODS[min(3, st_now['period'])]} · "
                           f"{story_mod.mission_title(game.save)}", COL["accent"], 5.5)
            if self.story_mission is not None:
                for speaker, line in self.story_mission["brief"]:
                    self.add_toast(f"{speaker}:{line}", COL["good"], 6.0)
            if self.story_issued:
                self.add_toast("系统补给:" + "、".join(self.story_issued)
                               + "(剧情模式保证你手里有家伙)", COL["good"], 5.0)
            self.time_left = float(STORY_FINAL_TIME
                                   if (self.story_mission or {}).get("id") == "d2_4"
                                   else STORY_TIMES[min(3, st_now["period"])])
        else:
            self.time_left = float(RAID_TIME)
        self.kills = 0
        self.loot_log = []       # 撤离结算用:{"name","count","value"}
        self.inv_open = False
        self.loot_target = None
        self.paused = False
        self._panels_was_open = False   # 触屏:弹窗开合沿(清理按住状态用)
        self.drop_mode = False   # 背包「丢弃模式」:手机没有右键,开着时点物品即丢
        self.safe_mode = False   # 保险箱存入模式:点背包物品 = 存进保险箱
        self.hold = uikit.HoldInfo()   # 触屏长按详情面板
        self.take = None         # 搜刮读条:{lc, item, queue, t, need}
        self.heal_ch = None      # 打药读条:{placed, t, need}
        self.searched = set()    # 已经搜出身份的物品(id(Placed));没搜过的是"未知"
        self.over = False
        self.result = None
        self.extract_t = 0.0
        self.banked = 0          # 双人合作:已进仓库的战利品件数(各自撤离时累加)
        self.bank_lost = 0       # 仓库塞不下、只能丢掉的件数
        self.fire_edge = False
        self.braced = False       # 长按右键架枪(提升精度)
        self.ask_merge = False   # "整理弹药"确认框
        self.revive_used = False  # 6级甲倒地自救(每局一次)
        self.warned = set()
        self._click_cd = 0.0
        # 迷雾/可见性缓存(性能:见 refresh_fog;敌人 AI 与绘制都读它)
        self.fog_polygon = None
        self.fog_polys = []         # 每位活着的玩家一个视野多边形(双人时有 2 个)
        self.fog_vis = set()
        self.fog_px = -1e9
        self.fog_py = -1e9
        self.fog2_px = -1e9
        self.fog2_py = -1e9
        self.fog2_aim = 0.0
        self.fog_t = 0.0
        self.fog_dirty = True      # 有人倒下/撤离 -> 视野多边形要重算
        self.fog_version = 0
        self._fog_drawn_ver = -1
        self.sight_vis2 = set()     # 能看见 P2 的敌人(双人合作)
        # 黑暗模式(夜战):光源形状(世界坐标)+ 亮区内的敌人集合
        self.dark = self.mode == "night"
        self.light_shapes = []      # [("poly", pts) | ("circle", (x, y, r, tint))]
        self.sight_vis = set()      # 敌人里「能看见玩家」的那些(离得近有视线)
        self.fog_aim = 0.0
        self.refresh_fog(force=True)
        # AI 共用的单调时钟:各单位「选目标」按它错峰重算(见 enemy.THINK_INTERVAL)
        self.now = 0.0
        self._aim_t = -1.0          # 辅助瞄准的下次重算时刻
        self.frame = 0              # 帧序号(远景守军按它错峰降频)
        self.view_reach2 = 1e18     # 玩家屏幕位置到四个屏幕角的最大距离²(每帧算)

    # ---------- 玩家集合(单人 / 双人合作共用) ----------
    def players(self):
        """本局所有玩家:P1,双人合作时还有 P2。"""
        if self.player2 is not None:
            return (self.player, self.player2)
        return (self.player,)

    def _p2_spawn(self):
        """给 P2 找一个离 P1 一两格、站得下人的出生点(找不到就同点出生)。"""
        bx, by = self.map.spawn
        tx, ty = int(bx // TILE), int(by // TILE)
        for rad in (1, 2, 3):
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (-1, -1), (1, -1), (-1, 1)):
                nx, ny = tx + dx * rad, ty + dy * rad
                if self.map.tile_solid(nx, ny):
                    continue
                cx, cy = nx * TILE + TILE // 2, ny * TILE + TILE // 2
                if self.map.collides(cx, cy, PLAYER["radius"]):
                    continue
                if math.hypot(cx - bx, cy - by) < TILE * 0.8:
                    continue
                return cx, cy
        return bx, by

    def active_players(self):
        """还在场上的人(没倒下、也没撤出去)。

        双人合作是**各自撤离**:P1 撤出去以后 P2 还要继续打,所以"撤离"和
        "阵亡"一样要从场上剔掉 —— 镜头、视野、敌人选目标、子弹判定都用它。
        """
        return tuple(p for p in self.players() if not p.out)

    def p_is_p2(self, p):
        return self.player2 is not None and p is self.player2

    def player_name(self, p):
        return "P2" if self.p_is_p2(p) else "P1"

    def p_start_value(self, p):
        """该玩家进局时的装备总值(净收益快照基准)。"""
        return self.p2_start_value if self.p_is_p2(p) else self.start_value

    def nearest_player_d2(self, x, y):
        """(x, y) 到最近玩家的距离²(守军 AI 的远景降级判定用)。"""
        pool = self.active_players() or self.players()
        best = 1e18
        for p in pool:
            dx = p.x - x
            dy = p.y - y
            d2 = dx * dx + dy * dy
            if d2 < best:
                best = d2
        return best

    def seek_player(self, x, y):
        """离 (x, y) 最近的还在场上的玩家(都没了就给 P1)。"""
        pool = self.active_players()
        if not pool:
            return self.player
        return min(pool, key=lambda q: (q.x - x) ** 2 + (q.y - y) ** 2)

    def cam_anchor(self):
        """镜头跟随的锚点位置(双人 = 还在场上的玩家的中点)。"""
        if self.coop:
            pool = self.active_players() or self.players()
            return (sum(q.x for q in pool) / len(pool),
                    sum(q.y for q in pool) / len(pool))
        return self.player.x, self.player.y

    def can_revive(self, p):
        """6 级甲倒地自救还能用吗(每位玩家每局一次)。"""
        if self.p_is_p2(p):
            return not self.p2_revive_used
        return not self.revive_used

    def mark_revive(self, p):
        if self.p_is_p2(p):
            self.p2_revive_used = True
        else:
            self.revive_used = True

    def player_down(self, p):
        """玩家倒下:单人 = 直接结算;双人 = 只要还有人在场上就继续打。"""
        p.dead = True
        p.out = True
        p.hp = 0
        self.fog_dirty = True
        if self.coop and self.active_players():
            self.add_toast(f"{self.player_name(p)} 倒下了 —— 另一个人还在场上,"
                           "活下去把他那一份也带出去!", COL["bad"], 5.5)
            return
        self._finish_when_cleared()

    def player_extracted(self, p):
        """一位玩家完成撤离:他这一份战利品立刻进仓库,人退出战场。

        双人合作是各自撤离 —— 剩下的队友还能继续搜刮/战斗(不会一起被带走),
        等两个人都撤离或倒下之后再统一结算。
        """
        p.extracted = True
        p.out = True
        self.fog_dirty = True
        if p.extract_gain is None:
            p.extract_gain = max(0, int(self._loadout_value(p)
                                        - self.p_start_value(p)))
        audio.play("extract")
        if not self.coop:
            # 单人:照旧只提示一声,战利品跟着装备一起带走(见 game.raid_finished)
            self.add_toast("撤离成功!", COL["good"])
            self.finish("extract")
            return
        kept, lost = coop_mod.bank_player(self.game.save, self, p)
        self.banked += kept
        self.bank_lost += lost
        others = self.active_players()
        msg = f"{self.player_name(p)} 撤离成功!战利品已进仓库({kept} 件)"
        if others:
            msg += f" —— {self.player_name(others[0])} 继续行动,按自己的节奏撤离"
        self.add_toast(msg, COL["good"], 6.5)
        if not others:
            self._finish_when_cleared()

    def _finish_when_cleared(self):
        """场上没人了:只要有人撤出去过,这一局就算撤离成功(倒下那位丢装备)。"""
        if self.over:
            return
        if any(q.extracted for q in self.players()):
            self.finish("extract")
        else:
            self.finish("death")

    # ---------- 按键(双人时 P1 要让出 P2 独占的键) ----------
    def _p1_keys(self, action):
        """P1 该动作实际生效的键位(双人合作时过滤掉 P2 的键)。"""
        ks = bindings.keys_for(self.game.save, action)
        if not self.coop:
            return ks
        blocked = coop_mod.p2_key_set()
        out = tuple(k for k in ks if k not in blocked)
        if out:
            return out
        # 玩家把该动作全改到方向键上了:退回默认键(双人时 P1 用 WASD)
        out = tuple(k for k in bindings.DEFAULTS.get(action, ks)
                    if k not in blocked)
        return out or ks

    def key_down(self, keys, p, action):
        """某位玩家此刻某动作是否被按住。

        P1 走 bindings(会过滤 P2 的键),P2 走 settings.COOP 里固定的键。
        自检里 get_pressed() 会被换成 dict 式假对象,取不到就当作没按。
        """
        ks = (COOP["keys"].get(action, ()) if self.p_is_p2(p)
              else self._p1_keys(action))
        for k in ks:
            try:
                if keys[k]:
                    return True
            except (IndexError, KeyError, TypeError):
                continue
        return False

    def moving_now(self, p):
        """该玩家此刻是否在推移动键 / 摇杆。"""
        if p is self.player and self.touch_mode and self.touch is not None:
            if any(abs(v) > 0.1 for v in self.touch.move_axis()):
                return True
        keys = pygame.key.get_pressed()
        return any(self.key_down(keys, p, a)
                   for a in ("up", "down", "left", "right"))

    def nearest_visible_enemy(self, x, y, max_range):
        """以 (x, y) 为圆心、max_range 内最近的可见敌人(手机锁敌 / P2 自动瞄准)。"""
        vis = self.fog_vis
        dark = self.dark
        los = self.map.los_clear
        best, bd2 = None, float(max_range) ** 2
        for s in self.scavs:
            if dark and id(s) not in vis:
                continue
            dx = s.x - x
            dy = s.y - y
            d2 = dx * dx + dy * dy
            if d2 < bd2 and los(x, y, s.x, s.y):
                best, bd2 = s, d2
        return best

    # ---------- 黑暗模式:光照形状 ----------
    def night_light(self, p=None):
        """返回 (亮区形状列表, 敌人可见判定函数用的参数)。

        光源优先级:枪上照明配件(锥形,跟准星) > 夜视头盔(全向圆) > 脚边微光。
        玩家没带任何光源时只能看见脚下一小圈 —— 这就是「夜战必须带装备」。
        """
        from settings import (NIGHT_AMBIENT, NIGHT_AMBIENT_TINT, NIGHT_BEAM_STEPS,
                              weapon_beam, helmet_nvg)
        p = p or self.player
        shapes = []
        nvg = helmet_nvg(getattr(p, "helmet", None))
        beam = weapon_beam(getattr(p, "weapon", None))
        # 画到压暗层上时先画暗的、后画亮的(后画的覆盖先画的)
        shapes.append(("circle", (p.x, p.y, NIGHT_AMBIENT, NIGHT_AMBIENT_TINT)))
        if nvg is not None:
            r, bright = nvg
            shapes.append(("circle", (p.x, p.y, r, (bright // 3, bright, bright // 2))))
        if beam is not None:
            rng, half_deg = beam
            half = math.radians(half_deg)
            pts = [(p.x, p.y)]
            steps = NIGHT_BEAM_STEPS
            for i in range(steps + 1):
                a = p.aim - half + (2 * half) * (i / float(steps))
                pts.append((p.x + math.cos(a) * rng, p.y + math.sin(a) * rng))
            shapes.append(("poly", pts))
        return shapes

    def in_light(self, x, y, p=None):
        """某点在不在亮区里(敌人「可见」的几何判定,视线另外算)。"""
        from settings import NIGHT_AMBIENT, helmet_nvg, weapon_beam
        p = p or self.player
        nvg = helmet_nvg(getattr(p, "helmet", None))
        beam = weapon_beam(getattr(p, "weapon", None))
        dx, dy = x - p.x, y - p.y
        if nvg is not None and math.hypot(dx, dy) <= nvg[0]:
            return True
        if beam is not None:
            d = math.hypot(dx, dy)
            if d <= beam[0]:
                diff = abs((math.atan2(dy, dx) - p.aim + math.pi) % math.tau - math.pi)
                if diff <= math.radians(beam[1]):
                    return True
        return math.hypot(dx, dy) <= NIGHT_AMBIENT

    def refresh_fog(self, dt=0.0, force=False):
        """战争迷雾 / 夜战光照的两级缓存(120fps 的关键)。

        白天:
          1) 视野多边形(140 条 DDA 射线)**每位活着的玩家一个**,只在有人
             移动超过 FOG_MOVE_STEP 时整批重算;
          2) 可见敌人集合在(1)之外,最短每 FOG_VIS_REFRESH 秒也刷一次 ——
             玩家站着不动时,敌人自己走进/走出视野也要能判定。
        夜里(黑暗模式):可见 = 在光源形状内(手电锥形 / 夜视圆 / 脚边微光)+ 有视线;
          光锥跟着准星转,所以准星变化超过阈值也要重算。

        双人合作:屏幕上只有一张画面,所以可见范围是两位玩家的并集。
        fog_vis  = 能看见的敌人(绘制与自动锁敌用)
        sight_vis / sight_vis2 = 能看见 P1 / P2 的敌人(敌人 AI 用)
        """
        p = self.player
        p2 = self.player2
        p2_alive = p2 is not None and not p2.out
        if force:
            do_poly = True
        else:
            self.fog_t += dt
            moved = math.hypot(p.x - self.fog_px, p.y - self.fog_py) >= FOG_MOVE_STEP
            if p2_alive:
                moved = moved or math.hypot(
                    p2.x - self.fog2_px, p2.y - self.fog2_py) >= FOG_MOVE_STEP
            if self.dark:
                turned = abs((p.aim - self.fog_aim + math.pi) % math.tau - math.pi) > 0.05
                if p2_alive:
                    turned = turned or abs(
                        (p2.aim - self.fog2_aim + math.pi) % math.tau - math.pi) > 0.05
                # 夜里 fog_polygon 恒为 None(不用 360° 视野多边形),
                # 所以"首次"要用 light_shapes 判断 —— 否则每帧都会重建光照层
                do_poly = moved or turned or self.fog_dirty or not self.light_shapes
            else:
                do_poly = moved or self.fog_dirty or not self.fog_polys
            if not do_poly and self.fog_t < FOG_VIS_REFRESH:
                return
        if do_poly:
            self.fog_dirty = False
            self.fog_polys = []
            self.light_shapes = []
            if self.dark:
                for q in self.active_players():
                    self.light_shapes.extend(self.night_light(q))
                self.fog_polygon = None      # 夜里不用 360° 视野多边形
            else:
                for q in self.active_players():
                    self.fog_polys.append(
                        self.map.visibility_polygon(q.x, q.y, 560))
                self.fog_polygon = self.fog_polys[0] if self.fog_polys else None
            self.fog_px, self.fog_py = p.x, p.y
            self.fog_aim = p.aim
            if p2 is not None:
                self.fog2_px, self.fog2_py = p2.x, p2.y
                self.fog2_aim = p2.aim
            self.fog_version += 1
        vis = set()
        sight = set()
        sight2 = set()
        r = FOG_VIS_RADIUS
        los = self.map.los_clear
        dark = self.dark
        for i, q in enumerate(self.players()):
            if q.out:
                continue
            qx, qy = q.x, q.y
            mine_sight = sight2 if i else sight
            for s in self.scavs:
                dx = s.x - qx
                if dx > r or dx < -r:
                    continue
                dy = s.y - qy
                if dy > r or dy < -r:
                    continue
                if los(qx, qy, s.x, s.y):
                    mine_sight.add(id(s))
                    if (not dark) or self.in_light(s.x, s.y, q):
                        vis.add(id(s))
        self.fog_vis = vis
        self.sight_vis = sight
        self.sight_vis2 = sight2
        self.fog_t = 0.0

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
        # 剧情关键点 / 剧情 NPC
        if self.mode == "story":
            sd = self.game.save
            for t in self.story_targets:
                if t.obj is not None and story_mod.is_done(sd, t.obj["id"]):
                    continue
                if t.kind == "extract":
                    continue
                d = math.hypot(t.x - p.x, t.y - p.y)
                if d < min(bd, STORY_INTERACT):
                    best, bd, kind = t, d, "story"
        return (kind, best) if best is not None else (None, None)

    def channel_need(self, kind=None):
        """引导类交互所需的秒数。"""
        k = kind or (self.channel["kind"] if self.channel else None)
        if k == "story":
            o = self.channel["ent"].obj
            return float(o.get("need", 2.0)) if o else 2.0
        return {"rescue": HOSTAGE_RESCUE_TIME, "revive": REVIVE_TIME,
                "destroy": ASSAULT_PLANT_TIME}.get(k, 1.0)

    def channel_label(self, kind=None):
        k = kind or (self.channel["kind"] if self.channel else None)
        if k == "story":
            o = self.channel["ent"].obj
            return f"{o['name']}中" if o else "进行中"
        return {"rescue": "解救人质中", "revive": "拉起队友中",
                "destroy": "安放炸药中"}.get(k, "进行中")

    def objectives_done(self):
        return len(self.objectives) > 0 and all(o.destroyed for o in self.objectives)

    def allows_extract(self):
        """突袭模式必须先把指挥设施全炸掉才能撤离。"""
        return self.mode != "assault" or self.objectives_done()

    def _extract_tick(self, p, cur, dt, moving=None):
        """一位玩家的撤离引导进度。返回 (新进度, 是否站满)。

        撤离点条件(突袭要先炸完 / 剧情各点各的规矩)在两人身上都生效。
        moving 由调用方传入(P1 用本帧算好的值,含 M139 架枪不能动的情况);
        不传就现算(P2)。
        """
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
            cur = max(0.0, cur - dt * 3)
        if zone is not None and self.mode == "story":
            # 剧情:每个撤离点都有自己的条件(信任/通行证/样本/隐藏点)
            ok, why = story_mod.can_use_extract(self.game.save, zone)
            if not ok:
                if zone not in self.warned:
                    self.warned.add(zone)
                    self.add_toast(f"「{zone}」现在还走不了:{why}", COL["bad"], 3.6)
                zone = None
                cur = max(0.0, cur - dt * 3)
        if zone is not None and not (moving if moving is not None
                                     else self.moving_now(p)) and not p.reloading:
            if cur <= 0:
                who = (f"{self.player_name(p)} " if self.coop
                       and self.p_is_p2(p) else "")
                self.add_toast(f"{who}开始撤离:{zone}", COL["accent"])
            cur += dt
            return cur, cur >= EXTRACT_TIME
        return max(0.0, cur - dt * 3), False

    def interact(self):
        """E / 搜刮按钮:优先剧情交互、救人质、拉队友、炸设施,其次搜刮容器。"""
        if self.dialogue is not None:
            self.dialogue_next()
            return
        if self.channel is not None:
            self.channel = None
            return
        kind, ent = self.nearest_interactable()
        if kind == "supply":
            self.use_supply(ent)
            return
        if kind == "story":
            if ent.dia is not None:
                self.open_dialogue(ent.dia, (ent.x, ent.y))
                return
            o = ent.obj
            if o["kind"] == "talk":
                self.open_dialogue(story_mod.DIA.get(o.get("dialogue", "")),
                                   (ent.x, ent.y))
                return
            if o["kind"] == "kill":
                self.add_toast("先把守在这里的家伙解决掉", COL["bad"], 2.6)
                return
            self.channel = dict(kind="story", ent=ent, t=0.0)
            audio.play("click")
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
        moving = self.moving_now(p)
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
            ent = self.channel["ent"]
            self.channel = None
            if kind == "story":
                if ent.obj is not None:
                    self._story_objective_done(ent.obj)
            elif kind == "rescue":
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
        if self.mode == "story" and tag in ("echo", "viktor", "wolf", "courier"):
            sd = self.game.save
            title = {"echo": "回声体", "viktor": "黑曜石指挥官维克托",
                     "wolf": "灰狼", "courier": "信使"}.get(tag, "剧情人物")
            if tag == "viktor":
                story_mod.set_flag(sd, "viktor_dead")
                self.add_toast(f"击毙 {title} —— 直升机坪现在可以撤离了",
                               COL["accent"], 4.5)
            elif tag == "wolf":
                story_mod.set_flag(sd, "wolf_dead")
                self.add_toast(f"你杀死了 {title}。灰区再也不会有人叫你英雄了。",
                               COL["bad"], 4.5)
            elif tag == "courier":
                story_mod.set_flag(sd, "killed_courier")
                self.add_toast(f"击毙 {title}", COL["accent"], 3.4)
            else:
                self.add_toast(f"击毙 {title}", COL["accent"], 3.4)
            self.story_log.append(f"击毙 {title}")
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
    def try_fire(self, held, p=None, edge=None, braced=None):
        p = p or self.player
        if edge is None:
            edge = self.fire_edge
        if braced is None:
            braced = self.braced
        w = p.weapon
        if w is None or p.reload_t > 0 or p.fire_cd > 0:
            return
        d = w.def_
        mode = p.fire_mode()
        if mode == "auto":
            if not held:
                return
        elif mode == "burst":
            # 三连发:扣一次扳机打 BURST_COUNT 发,打完必须松手再扣
            # (点按也算一次扣扳机 —— 手机点按只给 fire_edge,没有 held)
            if p.burst_left <= 0:
                if not edge:
                    return
                p.burst_left = BURST_COUNT
        else:
            if not edge:
                return
        if w.state.get("mag", 0) <= 0:
            if edge:
                audio.play("empty")
            p.burst_left = 0
            return
        dmg, pellets, hip, braced_s, rng, _rl, loud, burn = weapon_params(w)
        w.state["mag"] -= 1
        if mode == "burst":
            p.burst_left = max(0, p.burst_left - 1)
        p.fire_cd = d["rof"]
        tx = p.x + math.cos(p.aim) * 22
        ty = p.y + math.sin(p.aim) * 22
        # 架枪(长按右键)用架枪散布;腰射用腰射散布(配件/天赋都会影响)
        spread = braced_s if braced else hip
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

    def cycle_shoot_mode(self):
        """按 G 切换射击模式(单发 / 三连发 / 全自动)。"""
        p = self.player
        if p.weapon is None:
            self.add_toast("空手,没有可切换的射击模式", COL["text_dim"], 2.0)
            return
        nxt = p.cycle_fire_mode()
        if nxt is None:
            self.add_toast(f"{p.weapon.name} 只有单发模式", COL["text_dim"], 2.0)
            return
        audio.play("click")
        self.add_toast(f"射击模式:{fire_mode_name(nxt)}", COL["accent"], 2.0)

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

    def sees_player(self, scav, p):
        """该守军是否看得见某位玩家(读 refresh_fog 算好的缓存)。"""
        if self.p_is_p2(p):
            return id(scav) in self.sight_vis2
        return id(scav) in self.sight_vis

    def threat_for(self, scav):
        """拾荒者的当前目标:最近的可见玩家(双人时两个都算);都不行就打队友。

        返回 (目标, 是否看得见)。原来拆成 threat_for + sees_player 两步,而
        sees_player 会把这里的距离与可见性判定整个再做一遍 —— 一次算完返回。
        距离比较全部走平方,省掉 50 个守军每帧上百次 math.hypot。

        玩家可见性读 fog 缓存(refresh_fog 算好的对称视线),
        不再对每个敌人每帧打一条 DDA 射线。
        """
        view2 = scav.view2
        best, bd2 = None, view2
        for q in self.players():
            if q.out:
                continue
            dx = q.x - scav.x
            dy = q.y - scav.y
            d2 = dx * dx + dy * dy
            if d2 <= view2 and d2 < bd2 and self.sees_player(scav, q):
                best, bd2 = q, d2
        if best is not None:
            return best, True
        best, bd2 = None, view2
        los = self.map.los_clear
        sx, sy = scav.x, scav.y
        for a in self.allies:
            if a.downed:
                continue
            dx = a.x - sx
            dy = a.y - sy
            d2 = dx * dx + dy * dy
            if d2 < bd2 and los(sx, sy, a.x, a.y):
                best, bd2 = a, d2
        if best is not None:
            return best, True
        return self.seek_player(sx, sy), False

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
        for q in self.players():
            if q.out:
                continue
            if math.hypot(q.x - x, q.y - y) <= rad:
                if friendly:
                    if self.mode == "assault":
                        self.add_toast("被友军火力波及!", COL["bad"], 2.6)
                    q.take_damage(dmg * 0.5, self)
                else:
                    q.take_damage(dmg, self, rpg=True)

    def _update_bullets(self, dt):
        alive = []
        scavs = self.scavs
        # 空间占位表:每颗子弹每小步都要跟全部守军比一次距离(50 人 = 50 次),
        # 而子弹绝大多数时候周围一个敌人都没有。按 64px 分格记下「哪些格子里
        # 有人」,先花 9 次字典查询确认邻域是空的就直接跳过,命中判定仍走原来
        # 的完整循环(语义不变,连击杀时的列表增删行为都保持一致)。
        cells = set()
        for s in scavs:
            cells.add((int(s.x) >> 6, int(s.y) >> 6))
        cells_get = cells.__contains__
        for b in self.bullets:
            # 分小步采样,防止低帧率下 55px/步 穿墙/穿人
            bdx = b["dx"]
            bdy = b["dy"]
            n = max(1, int(math.sqrt(bdx * bdx + bdy * bdy) * dt / 14) + 1)
            sdt = dt / n
            dead = False
            is_rpg = b.get("rpg", False)
            for _ in range(n):
                bx = b["x"] + bdx * sdt
                by = b["y"] + bdy * sdt
                b["x"] = bx
                b["y"] = by
                b["ttl"] -= sdt
                if b["ttl"] <= 0:
                    if is_rpg:
                        self.explode(bx, by, b["dmg"], b["owner"],
                                     src=b.get("src"),
                                     blast_mul=b.get("blast", 1.0))
                    dead = True
                    break
                if self.map.tile_solid(int(bx // TILE), int(by // TILE)):
                    if is_rpg:
                        self.explode(bx, by, b["dmg"], b["owner"],
                                     src=b.get("src"))
                    else:
                        self.add_particles(bx, by, 3, (200, 200, 160), speed=60)
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
                        dx = st.x - bx
                        dy = st.y - by
                        lim = st.r
                        if dx > lim or dx < -lim or dy > lim or dy < -lim:
                            continue
                        if dx * dx + dy * dy < lim * lim:
                            st.damage(STRUCT_BULLET_DMG + b["dmg"] * STRUCT_BULLET_MUL)
                            self.add_particles(bx, by, 3, (210, 200, 150))
                            if st.destroyed:
                                self.add_toast(f"{st.name} 被摧毁!", COL["accent"], 3.4)
                            dead = True
                            break
                    if dead:
                        break
                if is_rpg:
                    # 火箭弹:碰到人/被挡就引爆,溅射范围内都吃伤害(不必精确瞄准)
                    cx = int(bx) >> 6
                    cy = int(by) >> 6
                    if (cells_get((cx, cy)) or cells_get((cx - 1, cy))
                            or cells_get((cx + 1, cy)) or cells_get((cx, cy - 1))
                            or cells_get((cx, cy + 1)) or cells_get((cx - 1, cy - 1))
                            or cells_get((cx + 1, cy - 1)) or cells_get((cx - 1, cy + 1))
                            or cells_get((cx + 1, cy + 1))):
                        for s in list(scavs):
                            dx = s.x - bx
                            dy = s.y - by
                            lim = s.r + 3
                            if dx > lim or dx < -lim or dy > lim or dy < -lim:
                                continue
                            if dx * dx + dy * dy < lim * lim:
                                self.explode(bx, by, b["dmg"], b["owner"],
                                             src=b.get("src"))
                                dead = True
                                break
                    if dead:
                        break
                    p0 = self.player
                    lim = PLAYER["radius"] + 2
                    for q in self.players():
                        if q.out:
                            continue
                        dx = q.x - bx
                        dy = q.y - by
                        if (dx < lim and dx > -lim and dy < lim and dy > -lim
                                and dx * dx + dy * dy < lim * lim):
                            self.explode(bx, by, b["dmg"], b["owner"],
                                         src=b.get("src"))
                            dead = True
                            break
                    if dead:
                        break
                    continue
                if b["owner"] in ("player", "ally"):
                    # 先看邻域里有没有人,再逐个做轴向粗筛 + 平方距离
                    # (命中半径只有 15px,原来是每颗子弹每小步 50 次 hypot)
                    cx = int(bx) >> 6
                    cy = int(by) >> 6
                    if (cells_get((cx, cy)) or cells_get((cx - 1, cy))
                            or cells_get((cx + 1, cy)) or cells_get((cx, cy - 1))
                            or cells_get((cx, cy + 1)) or cells_get((cx - 1, cy - 1))
                            or cells_get((cx + 1, cy - 1)) or cells_get((cx - 1, cy + 1))
                            or cells_get((cx + 1, cy + 1))):
                        for s in scavs:
                            dx = s.x - bx
                            dy = s.y - by
                            lim = s.r + 3
                            if dx > lim or dx < -lim or dy > lim or dy < -lim:
                                continue
                            if dx * dx + dy * dy < lim * lim:
                                s.damage(b["dmg"])
                                if b.get("burn"):
                                    s.burn_t = 1.5
                                    s.burn_dps = b["burn"]
                                audio.play("hit")
                                self.add_particles(bx, by, 4, (190, 40, 40))
                                if s.dead:
                                    self.kill_scav(s)
                                dead = True
                                break
                else:
                    lim = PLAYER["radius"] + 2
                    for q in self.players():
                        if q.out:
                            continue
                        dx = q.x - bx
                        dy = q.y - by
                        if (dx < lim and dx > -lim and dy < lim and dy > -lim
                                and dx * dx + dy * dy < lim * lim):
                            q.take_damage(b["dmg"], self)
                            dead = True
                            break
                    if not dead:
                        for a in self.allies:
                            if a.downed:
                                continue
                            dx = a.x - bx
                            dy = a.y - by
                            lim = a.r + 2
                            if dx > lim or dx < -lim or dy > lim or dy < -lim:
                                continue
                            if dx * dx + dy * dy < lim * lim:
                                a.take_damage(b["dmg"], self)
                                dead = True
                                break
                if dead:
                    break
            if not dead:
                alive.append(b)
        self.bullets = alive

    # ---------- 装填/使用/装备 ----------
    def start_reload(self, p=None):
        p = p or self.player
        if p.weapon is None or p.reloading or p.reload_t > 0:
            return
        w = p.weapon
        if w.state.get("mag", 0) >= weapon_capacity(w):
            return
        if p.reserve_count() <= 0:
            who = f"{self.player_name(p)}:" if self.coop else ""
            self.add_toast(who + "没有可用弹药!", COL["bad"])
            return
        p.reload_t = weapon_params(w)[5]
        p.reloading = True
        p.burst_left = 0          # 装填会打断三连发
        audio.play("reload")

    def _finish_reload(self, p=None):
        p = p or self.player
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
            who = f"{self.player_name(p)} " if self.coop else ""
            self.add_toast(f"{who}装填完成 {w.state['mag']}/{cap}", COL["good"])

    def use_med(self, placed):
        p = self.player
        if p.hp >= p.max_hp:
            self.add_toast("生命值已满", COL["text_dim"])
            return
        healed = p.heal(placed.item.def_["heal"])
        p.bag.remove_placed(placed)
        audio.play("heal")
        self.add_toast(f"治疗 +{healed}", COL["good"])

    def _aim_assist_target(self, staggered=False):
        """辅助瞄准(手机):视野内最近的可见敌人。

        黑暗模式下只锁「亮区里」的敌人 —— 看不见的目标不该被自动瞄准,
        否则手电/夜视就没有意义了。

        staggered=True 时按 raid.now 缓存 0.08 秒(主循环每帧都调它,而锁定
        目标在 0.08 秒里不会变)。直接调用(自检/外部)一律现算,保证语义不变。
        """
        if staggered and self.now < self._aim_t:
            return self.aim_locked
        if staggered:
            self._aim_t = self.now + 0.08
        p = self.player
        return self.nearest_visible_enemy(p.x, p.y, TOUCH["aim_assist_range"])

    def quick_heal(self):
        """快捷打药(按 H / 手机打药键):自动挑最合适的医疗品,然后读条 1~3 秒。"""
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
        self.start_heal(pick)

    # ---------- 搜刮 / 打药读条 ----------
    def loot_take_time(self, item):
        """搜一件东西要多久:按占格数(大件更慢)。"""
        from settings import (LOOT_TAKE_TIME, LOOT_TAKE_PER_CELL,
                              LOOT_TAKE_MIN, LOOT_TAKE_MAX)
        w, h = item.size()
        t = LOOT_TAKE_TIME + LOOT_TAKE_PER_CELL * (w * h - 1)
        return max(LOOT_TAKE_MIN, min(LOOT_TAKE_MAX, t))

    # ---------- 搜刮:未知 -> 搜索揭示 -> 取出 ----------
    def mark_known(self, placed):
        """标记这件东西已经知道是什么(自己丢的/放进去的/搜出来的)。"""
        self.searched.add(id(placed))

    def is_known(self, placed):
        return id(placed) in self.searched

    def start_take(self, lc, items):
        """开始逐件搜索(1~2 秒一件);搜出来的只是"这是什么",东西还在箱子里。"""
        items = [x for x in items if lc is not None and x in lc.container.items
                 and not self.is_known(x)]
        if not items:
            return
        self.take = dict(lc=lc, item=items[0], queue=items[1:],
                         t=0.0, need=self.loot_take_time(items[0].item))
        audio.play("click")

    def cancel_take(self, note=None):
        if self.take is not None:
            self.take = None
            if note:
                self.add_toast(note, COL["text_dim"], 2.0)

    def take_known(self, lc, placed):
        """取出已经搜出来的东西(进背包;空手时武器/护甲/头盔直接装备)。"""
        p = self.player
        item = placed.item
        if item.cat == "weapon" and p.weapon is None and armor_allows(p.armor, item.def_):
            lc.container.remove_placed(placed)
            p.weapon = item
            p.burst_left = 0
            p.reloading = False
            p.reload_t = 0
            self._log_gained(item)
            audio.play("pickup")
            self.add_toast(f"装备 {item.name}", COL["good"])
            return True
        if item.cat == "armor" and p.armor is None:
            lc.container.remove_placed(placed)
            p.armor = item
            self._log_gained(item)
            audio.play("pickup")
            self.add_toast(f"装备 {item.name}", COL["good"])
            return True
        if item.cat == "helmet" and p.helmet is None:
            lc.container.remove_placed(placed)
            p.helmet = item
            self._log_gained(item)
            audio.play("pickup")
            self.add_toast(f"装备 {item.name}", COL["good"])
            return True
        if try_move(lc.container, placed, p.bag):
            self._log_gained(item)
            audio.play("pickup")
            self.add_toast(f"拿走 {item.name}", COL["good"], 2.0)
            return True
        # 背包满了?试试保险箱(剧情/突袭是系统配发装备,不允许往里塞)
        if self.mode not in ("story", "assault") \
                and try_move(lc.container, placed, p.safe):
            self._log_gained(item)
            audio.play("pickup")
            self.add_toast(f"背包放不下:{item.name} 已塞进保险箱(阵亡不丢)",
                           COL["accent"], 2.8)
            return True
        self.add_toast("背包空间不足", COL["bad"], 3.0)
        return False

    def _update_take(self, dt):
        """搜索读条:需要箱子还开着、物品还在、人没走远;搜完 = 揭示身份。"""
        tk = self.take
        if tk is None or self.over:
            return
        p = self.player
        lc = tk["lc"]
        placed = tk["item"]
        alive = (lc in self.containers and placed in lc.container.items
                 and math.hypot(lc.rect.centerx - p.x, lc.rect.centery - p.y)
                 <= INTERACT_DIST * 1.8)
        if not alive or self.loot_target is not lc:
            self.cancel_take("搜索中断")
            return
        tk["t"] += dt
        if tk["t"] < tk["need"]:
            return
        nxt = list(tk.get("queue") or [])
        self.take = None
        self.mark_known(placed)
        audio.play("pickup")
        self.add_toast("搜出来了:" + placed.item.name
                       + (f" ×{placed.item.count}" if placed.item.count > 1 else ""),
                       COL["good"], 2.4)
        if nxt:
            self.start_take(lc, nxt)

    def heal_time(self, item):
        from settings import (HEAL_TIME, HEAL_TIME_PER_HP, HEAL_TIME_MIN,
                              HEAL_TIME_MAX)
        t = HEAL_TIME + item.def_.get("heal", 0) * HEAL_TIME_PER_HP
        return max(HEAL_TIME_MIN, min(HEAL_TIME_MAX, t))

    def start_heal(self, placed):
        """开始打药读条(1~3 秒,按治疗量);移动时进度减半。"""
        p = self.player
        if p.hp >= p.max_hp:
            self.add_toast("生命值已满", COL["text_dim"])
            return
        if placed not in p.bag.items:
            return
        self.heal_ch = dict(placed=placed, t=0.0, need=self.heal_time(placed.item))
        audio.play("click")

    def player_moving(self):
        """玩家此刻是否在推移动键/摇杆(读条时移动会减慢进度)。"""
        return self.moving_now(self.player)

    def _update_heal(self, dt):
        hc = self.heal_ch
        if hc is None or self.over:
            return
        p = self.player
        placed = hc["placed"]
        if placed not in p.bag.items or p.hp >= p.max_hp:
            self.heal_ch = None
            return
        hc["t"] += dt * (0.5 if self.player_moving() else 1.0)
        if hc["t"] >= hc["need"]:
            self.heal_ch = None
            self.use_med(placed)

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
            # 旧枪塞不进背包就丢在脚边(以前这里直接拒绝,感觉像"卡住了")
            ok, note = self._stow_or_drop(old)
            if not ok:
                p.bag.items.append(placed)   # 回滚
                self.add_toast(note, COL["bad"])
                return
            p.weapon = item
            p.burst_left = 0      # 换枪重置三连发
            p.reloading = False   # 换枪取消装填
            p.reload_t = 0
            audio.play("click")
            self.add_toast(note or f"换上 {item.name}", COL["accent"] if note else COL["good"], 3.0)
        elif item.cat == "armor":
            old = p.armor
            p.bag.remove_placed(placed)
            ok, note = self._stow_or_drop(old)
            if not ok:
                p.bag.items.append(placed)
                self.add_toast(note, COL["bad"])
                return
            p.armor = item
            audio.play("click")
            self.add_toast(note or f"穿上 {item.name}", COL["accent"] if note else COL["good"], 3.0)
        elif item.cat == "helmet":
            old = p.helmet
            p.bag.remove_placed(placed)
            ok, note = self._stow_or_drop(old)
            if not ok:
                p.bag.items.append(placed)
                self.add_toast(note, COL["bad"])
                return
            p.helmet = item
            audio.play("click")
            nvg = item.def_.get("nvg")
            self.add_toast(note or (f"已戴上 {item.name}"
                                    + (f"(夜视半径 {int(nvg[0])})" if nvg else "")),
                           COL["accent"] if note else COL["good"], 3.0)
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

    def _spawn_story_bosses(self):
        """剧情模式:按时段与选择生成 Boss(回声体/维克托/灰狼/信使)。"""
        for b in story_mod.bosses(self.game.save):
            try:
                bx, by = story_mod.at_pos(b["at"])
            except KeyError:
                continue
            self.scavs.append(Scav("ar", bx, by, self.diff,
                                   custom=dict(b["stats"], name=b["name"]),
                                   tag=b["tag"]))

    def open_dialogue(self, dia, at=None):
        """打开对白面板(台词读完才给选项)。at = 说话人所在坐标(演出用)。"""
        if dia is None:
            return
        self.dialogue = dict(speaker=dia.get("speaker", "?"),
                             lines=list(dia.get("lines", [])),
                             idx=0, choices=dia.get("choices"), reply=None,
                             at=at)
        audio.play("click")

    def dialogue_next(self):
        """推进对白:下一句 -> 选项 -> 选后回复 -> 关闭。"""
        d = self.dialogue
        if d is None:
            return
        if d["reply"] is not None:
            self.dialogue = None
            return
        if d["idx"] < len(d["lines"]) - 1:
            d["idx"] += 1
            return
        if d["choices"]:
            return                     # 等玩家点选项
        self.dialogue = None

    def dialogue_choose(self, i):
        """选择分支:套用效果 + 放个剧情演出,再显示回复。"""
        d = self.dialogue
        if d is None or not d["choices"] or not (0 <= i < len(d["choices"])):
            return False
        c = d["choices"][i]
        eff = c.get("effects", {})
        story_mod.apply_effects(self.game.save, eff)
        self.story_log.append(f"{d['speaker']} → {c['text']}")
        audio.play("click")
        d["reply"] = c.get("reply", "……")
        d["choices"] = None
        # 演出:按这次选择写下的标记挑一种动画
        x, y = d.get("at", (self.player.x, self.player.y))
        for f in eff.get("flags", []):
            fx = story_mod.CHOICE_FX.get(f)
            if fx:
                self._start_cutscene(fx[0], x, y, fx[1])
                break
        # 信任变化飘个数字(和上面的结果提示错开,别叠在一起)
        if eff.get("wolf"):
            n = int(eff["wolf"])
            self._floater(f"灰狼信任 {'+' if n > 0 else ''}{n}", x, y - 62,
                          COL["good"] if n > 0 else COL["bad"])
        if eff.get("erin"):
            n = int(eff["erin"])
            self._floater(f"艾琳信任 {'+' if n > 0 else ''}{n}", x, y - 90,
                          COL["good"] if n > 0 else COL["bad"])
        return True

    def _floater(self, text, x, y, col=None):
        self.floaters.append(dict(text=text, x=x, y=y, t=0.0, dur=2.6,
                                  col=col or COL["accent"]))

    def _start_cutscene(self, kind, x, y, text=""):
        """放一段简单演出(救援/处决/给药/拒绝/抢夺/跟踪),并让俘虏状态生效。"""
        self.cutscene = dict(kind=kind, x=x, y=y, t=0.0, dur=2.6)
        if kind == "rescue":
            self.captive_state = "freed"
            self.add_particles(x, y, 18, (120, 220, 130), speed=110)
        elif kind == "shoot":
            self.captive_state = "dead"
            self.add_particles(x, y, 22, (200, 60, 60), speed=140)
            self.add_particles(x, y, 8, (255, 230, 150), speed=90)
            audio.play("sg")
        elif kind == "aid":
            self.add_particles(x, y, 16, (120, 220, 130), speed=80)
        elif kind == "rob":
            self.add_particles(x, y, 16, (220, 120, 60), speed=120)
        else:
            self.add_particles(x, y, 12, (150, 200, 230), speed=90)
        if text:
            self._floater(text, x, y - 26, COL["accent"])

    def _story_objective_done(self, o):
        """完成一个剧情目标:写进度、套效果、可能接一段对白。"""
        sd = self.game.save
        story_mod.mark_done(sd, o["id"])
        eff = o.get("effects", {})
        story_mod.apply_effects(sd, eff)
        audio.play("pickup")
        self.add_toast(f"{o['name']} ✓", COL["good"], 3.2)
        self.story_log.append(o["name"])
        # 录音:屏幕下方出一串字幕(像无线电里放出来的原话)
        if o.get("at") == "tapes" and "tape_index" in o:
            self.subtitle = dict(text=story_mod.tape_line(o["tape_index"]),
                                 t=8.0, dur=8.0)
            self.add_toast(f"录到第 {story_mod.st(sd)['tapes']}/12 份录音",
                           COL["accent"], 3.0)
        if eff.get("dialogue"):
            self.open_dialogue(story_mod.DIA.get(eff["dialogue"]))
        left = [x for x in story_mod.objectives(sd)
                if x["kind"] not in ("extract",) and x["at"] != "tapes"
                and not story_mod.is_done(sd, x["id"])]
        if not left and self.story_mission is not None:
            self.add_toast("本时段的目标都做完了 —— 找撤离点撤出去",
                           COL["accent"], 4.5)

    def _update_story_fx(self, dt):
        """剧情演出/飘字/字幕的计时。"""
        if self.cutscene is not None:
            self.cutscene["t"] += dt
            if self.cutscene["t"] >= self.cutscene["dur"]:
                self.cutscene = None
        for f in self.floaters:
            f["t"] += dt
        self.floaters = [f for f in self.floaters if f["t"] < f["dur"]]
        if self.subtitle is not None:
            self.subtitle["t"] -= dt
            if self.subtitle["t"] <= 0:
                self.subtitle = None

    def _update_story(self, dt):
        """剧情:击杀目标(Boss)判定。"""
        if self.mode != "story" or self.over:
            return
        sd = self.game.save
        for o in story_mod.objectives(sd):
            if o["kind"] != "kill" or story_mod.is_done(sd, o["id"]):
                continue
            tag = o.get("boss")
            alive = any(getattr(s, "tag", None) == tag for s in self.scavs)
            if not alive:
                self._story_objective_done(o)

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

    def drop_to_ground(self, item):
        """把一件东西丢在脚边(附近有地面堆就塞进去)。成功返回 True。"""
        p = self.player
        pile = None
        for lc in self.containers:
            if lc.kind == "ground" and math.hypot(lc.rect.centerx - p.x,
                                                  lc.rect.centery - p.y) < 48:
                pile = lc
                break
        created = False
        if pile is None:
            pile = LootContainer("ground", int(p.x), int(p.y))
            created = True
        if not pile.container.add_item(item):
            return False
        if created:
            self.containers.append(pile)
        self._unlog_gained(item)
        for pl in pile.container.items:      # 自己丢的当然知道是什么
            if pl.item is item:
                self.mark_known(pl)
                break
        return True

    def _stow_or_drop(self, old):
        """换装时把旧装备塞回背包;塞不下就丢在脚边(别让玩家卡住)。

        返回 (ok, 提示文案);失败时不做任何改动(旧装备仍在身上)。
        """
        if old is None:
            return True, ""
        if self.player.bag.add_item(old):
            return True, ""
        if self.drop_to_ground(old):
            return True, f"{old.name} 放不进背包,已丢在脚边"
        return False, "背包空间不足,地上也放不下"

    def drop_from_bag(self, placed):
        """背包里的东西丢到地上(电脑右键 / 手机「丢弃模式」点一下)。"""
        item = self.player.bag.take_placed(placed)
        if self.drop_to_ground(item):
            audio.play("click")
            self.add_toast(f"丢弃 {item.name}", COL["text_dim"])
        else:
            self.player.bag.items.append(placed)   # 地上也放不下:回到背包
            self.add_toast("放不下,没能丢出去", COL["bad"])

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
    def _loadout_value(self, p=None):
        p = p or self.player
        v = p.bag.total_value()
        if p.weapon is not None:
            v += p.weapon.total_price()
        if p.armor is not None:
            v += p.armor.total_price()
        if getattr(p, "helmet", None) is not None:
            v += p.helmet.total_price()
        return v

    def finish(self, kind):
        if self.over:
            return
        self.over = True
        self.inv_open = False
        self.loot_target = None
        self.paused = False
        self.safe_mode = False
        self.hold.hide()
        if kind == "extract":
            audio.play("extract")
        else:
            audio.play("death")
        # 用"撤离时装备总值 - 进局时装备总值"快照计算净收益,事件式记账
        # 会在放回物品/部分堆叠转移时失真。
        # 双人合作:各自撤离,谁撤出去就算谁的净收益(撤离那一刻已经存过一份)
        if self.coop and self.player2 is not None:
            gained = sum(max(0, int(q.extract_gain or 0))
                         for q in self.players() if q.extracted)
            for q in self.players():
                if not q.out:      # 还在场上的(理论上不会),按现值算
                    gained += max(0, int(self._loadout_value(q)
                                         - self.p_start_value(q)))
        else:
            gained = max(0, int(self._loadout_value() - self.start_value))
        rescued = sum(1 for h in self.hostages if h.rescued)
        objs_done = sum(1 for o in self.objectives if o.destroyed)
        if self.mode == "hostage":
            mission = len(self.hostages) > 0 and rescued >= len(self.hostages)
        elif self.mode == "assault":
            mission = self.objectives_done()
        else:
            mission = True
        # 双人合作:每人各自的结局(撤离 / 阵亡 / 没撤出来),结算页照这个显示
        coop_status = []
        if self.coop:
            for q in self.players():
                if q.extracted:
                    coop_status.append((self.player_name(q), "extract"))
                elif q.dead:
                    coop_status.append((self.player_name(q), "dead"))
                else:
                    coop_status.append((self.player_name(q), "mia"))
        self.result = dict(kind=kind, kills=self.kills, gained=gained,
                           n=len(self.loot_log), time=RAID_TIME - self.time_left,
                           entries=self.loot_log,
                           mode=self.mode, rescued=rescued,
                           hostages=len(self.hostages),
                           coop=self.coop,
                           coop_status=coop_status,
                           banked=self.banked, bank_lost=self.bank_lost,
                           p2_dead=(self.player2 is not None and self.player2.dead),
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
        if self.mode == "story" and not self.result.get("story_note"):
            # 时段结算:写剧情进度并推进到下一个时段(可能直接进入结局)
            self.result["story_note"] = story_mod.settle_period(self.game.save,
                                                               self.result)
            self.result["story_log"] = list(self.story_log[-6:])
            self.result["brief"] = story_mod.brief_lines(self.game.save)
        self.game.raid_finished(self.result)

    # ---------- 每帧 ----------
    def update(self, dt, events):
        p = self.player
        self._click_cd = max(0.0, self._click_cd - dt)
        self.now += dt                 # AI 错峰用的单调时钟

        # 结算页:任意键/任意触摸返回藏身处
        if self.over:
            for ev in events:
                if ev.type in (pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                               pygame.FINGERDOWN):
                    self.game.to_hideout()
            return

        # 事件
        sd = self.game.save
        panels_open = (self.inv_open or self.loot_target is not None
                       or self.ask_merge or self.paused)
        if self.touch_mode and self.touch is not None:
            # 弹窗刚打开的那一刻:清掉「按住」状态(FINGER 抬起收不到)。
            # 注意别清 just_pressed —— 本帧的「再点一次背包=关闭」还要用它。
            if panels_open and not self._panels_was_open:
                self.touch.reset_hold()
            self._panels_was_open = panels_open
        # 触屏长按(背包/搜刮面板):点按延迟到抬起;按住 0.45s 弹物品详情
        events = self._filter_hold_events(events)
        self.hold.update(dt, self._hold_query)
        pending_edge = False
        for ev in events:
            # 对白面板优先吃掉输入(读完台词 -> 选项 -> 关闭)
            if self.dialogue is not None:
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_ESCAPE:
                        self.dialogue = None
                    elif (bindings.key_matches(ev.key, sd, "interact")
                          or ev.key in (pygame.K_SPACE, pygame.K_RETURN)):
                        self.dialogue_next()
                    elif ev.key in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4):
                        self.dialogue_choose({pygame.K_1: 0, pygame.K_2: 1,
                                              pygame.K_3: 2, pygame.K_4: 3}[ev.key])
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    import raid_ui as _rui
                    hit = False
                    for i, r in enumerate(_rui.dialogue_layout(self)):
                        if r.collidepoint(ev.pos):
                            self.dialogue_choose(i)
                            hit = True
                            break
                    if not hit:
                        self.dialogue_next()
                continue
            # 触屏模式:FINGER 交给虚拟摇杆/按钮;合成出来的鼠标镜像
            # 只在弹窗打开时当点击用(战局操作已由 TouchUI 消费,避免双触发)
            if self.touch_mode:
                if ev.type in touch_mod.FINGER_EVENTS:
                    if not panels_open:
                        self.touch.handle_event(ev)
                    continue
                if getattr(ev, "synthetic", False):
                    if not panels_open:
                        continue
                elif not panels_open and ev.type in (pygame.MOUSEBUTTONDOWN,
                                                     pygame.MOUSEMOTION,
                                                     pygame.MOUSEBUTTONUP):
                    # 电脑上用 --touch 测试:真鼠标也走 TouchUI
                    self.touch.handle_event(ev)
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
                elif p.out:
                    # 双人合作里 P1 已经倒下/撤离:只能看,不能操作(ESC 仍可用)
                    continue
                elif bindings.key_matches(ev.key, sd, "bag"):
                    self.loot_target = None
                    self.ask_merge = False
                    self.inv_open = not self.inv_open
                elif bindings.key_matches(ev.key, sd, "interact"):
                    self.interact()
                elif bindings.key_matches(ev.key, sd, "reload"):
                    if not (self.inv_open or self.loot_target):
                        self.start_reload()
                elif bindings.key_matches(ev.key, sd, "firemode"):
                    if not (self.inv_open or self.loot_target):
                        self.cycle_shoot_mode()
                elif bindings.key_matches(ev.key, sd, "heal"):
                    if not (self.inv_open or self.loot_target):
                        self.quick_heal()
                elif self.mode == "assault":
                    for i, act in enumerate(("support1", "support2", "support3")):
                        if bindings.key_matches(ev.key, sd, act) \
                                and not (self.inv_open or self.loot_target):
                            tx, ty = self._support_target()
                            self.call_support(SUPPORT_ORDER[i], tx, ty)
                            break
                # 双人合作:P2 的动作键(与 P1 的键不重叠,不会互相触发)
                if self.coop and not (self.inv_open or self.loot_target):
                    self._p2_key(ev.key)
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
        keys = pygame.key.get_pressed()
        if self.touch_mode:
            vx, vy = self.touch.move_axis()
            walking = False
        elif p.out:
            vx, vy, walking = 0.0, 0.0, False      # 双人合作:P1 倒下/已撤离后只操作 P2
        else:
            vx = float(self.key_down(keys, p, "right")
                       - self.key_down(keys, p, "left"))
            vy = float(self.key_down(keys, p, "down")
                       - self.key_down(keys, p, "up"))
            walking = self.key_down(keys, p, "walk")
        # 动作对移动的影响:架枪(瞄准)剩 20%;换弹剩 40%;
        # 重武器(M139,braced_immobile)架枪或换弹时完全不能动
        heavy = (p.weapon is not None
                 and p.weapon.def_.get("braced_immobile"))
        mul = 1.0
        if self.braced:
            mul = min(mul, MOVE_AIM_MUL)
        if p.reloading:
            mul = min(mul, MOVE_RELOAD_MUL)
        immobile = heavy and (self.braced or p.reloading)
        moving = bool(vx or vy) and not immobile
        if moving:
            length = math.hypot(vx, vy)
            spd = p.speed(walking) * mul
            scale = min(1.0, length)     # 摇杆推一半 = 半速
            dx = vx / length * spd * scale * dt
            dy = vy / length * spd * scale * dt
            p.x, p.y = self.map.move_circle((p.x, p.y), dx, dy, PLAYER["radius"])
        self.move_mul = mul          # HUD 显示用(装填中/架枪中减速)

        # 瞄准:电脑用鼠标;手机自动锁敌(视野内最近的敌人,不用手动瞄准)
        if self.touch_mode:
            self.aim_locked = self._aim_assist_target(True)
            if self.aim_locked is not None:
                p.aim = math.atan2(self.aim_locked.y - p.y, self.aim_locked.x - p.x)
            elif moving:
                p.aim = math.atan2(vy, vx)
        elif p.out:
            self.aim_locked = None
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
                elif name == "mode":
                    self.cycle_shoot_mode()
                elif name == "heal":
                    self.quick_heal()
                elif name == "loot":
                    self.interact()
                elif name == "bag":
                    self.loot_target = None
                    self.inv_open = not self.inv_open
                elif name == "menu":
                    # 手机没有 ESC:虚拟按钮进/出暂停菜单
                    self.paused = not self.paused
                    audio.play("click")
                elif name in ("sup1", "sup2", "sup3"):
                    idx = {"sup1": 0, "sup2": 1, "sup3": 2}[name]
                    tx, ty = self._support_target()
                    self.call_support(SUPPORT_ORDER[idx], tx, ty)
            # 「模式」按钮上写当前射击模式(处理完本帧点按后再刷新)
            self.touch.mode_label = fire_mode_name(p.fire_mode())
        else:
            held = pygame.mouse.get_pressed()[0]
            self.braced = bool(pygame.mouse.get_pressed()[2])   # 右键=架枪
        world_active = not (self.inv_open or self.loot_target is not None
                            or self.dialogue is not None)
        if world_active and not p.out:
            self.try_fire(held)
        self.fire_edge = False
        # 双人合作:P2 移动/自动瞄准/开火(键盘)
        if self.coop:
            self._update_p2(dt, keys)

        # 装填计时 / 自动换弹 / 受击闪光(两人各自算)
        self._update_weapon_timers(p, dt)
        if self.coop and self.player2 is not None:
            self._update_weapon_timers(self.player2, dt)

        # 撤离引导(双人合作:**各自撤离** —— 谁站满谁走,队友还能继续打)
        if not p.out:
            self.extract_t, ready = self._extract_tick(p, self.extract_t, dt,
                                                       moving=moving)
            if ready:
                self.player_extracted(p)
        p2 = self.player2
        if p2 is not None and not p2.out:
            self.p2_extract_t, ready2 = self._extract_tick(
                p2, self.p2_extract_t, dt)
            if ready2:
                self.player_extracted(p2)
        if self.over:
            return

        # 迷雾/可见性缓存刷新(敌人 AI 的 threat_for/sees_player 都读它)
        self.refresh_fog(dt)

        # 「玩家屏幕位置到四个屏幕角的最大距离」—— 超过它的守军一定在画面外,
        # 于是可以降频模拟(enemy.Scav.update 里的远景降级)。摄像机贴地图边时
        # 玩家不在屏幕正中,所以必须每帧按实际相机位置算,不能用常数。
        # 双人合作:取两位玩家里的最大值(任何一位能看到就不许降级)。
        self.frame += 1
        camx, camy = self.cam
        reach = 0.0
        for q in (self.active_players() or self.players()):
            pxs = q.x - camx
            pys = q.y - camy
            wx = W - pxs
            hy = H - pys
            reach = max(reach, pxs * pxs + pys * pys,
                        wx * wx + pys * pys,
                        pxs * pxs + hy * hy,
                        wx * wx + hy * hy)
        self.view_reach2 = reach

        # 实体
        for s in self.scavs:
            s.update(self, dt)
        for a in self.allies:
            a.update(self, dt)
        for h in self.hostages:
            h.update(self, dt)
        self._update_burn(dt)
        self._update_channel(dt)
        self._update_take(dt)
        self._update_p2_take(dt)
        self._update_heal(dt)
        self._update_support(dt)
        self._update_c4(dt)
        self._update_repair(dt)
        self._update_reinforce(dt)
        self._update_hq(dt)
        self._update_rebuild(dt)
        self._update_supplies(dt)
        self._update_story(dt)
        self._update_story_fx(dt)
        self._update_bullets(dt)
        # 粒子:阻尼按 dt 折算(原来每帧 *0.9,120fps 下衰减快一倍)
        damp = 0.9 ** (dt * 60.0)
        for pt in self.particles:
            pt["ttl"] -= dt
            pt["x"] += pt["dx"] * dt
            pt["y"] += pt["dy"] * dt
            pt["dx"] *= damp
            pt["dy"] *= damp
        self.particles = [pt for pt in self.particles if pt["ttl"] > 0]
        for t in self.toasts:
            t[1] -= dt
        self.toasts = [t for t in self.toasts if t[1] > 0]
        self.shake = max(0.0, self.shake - dt * 18)

        # 摄像机:双人合作跟随还活着的玩家的中点(倒下的不再拉着镜头)
        fx, fy = self.cam_anchor()
        self.cam[0] = max(0, min(self.map.px_w - W, fx - W / 2))
        self.cam[1] = max(0, min(self.map.px_h - H, fy - H / 2))

    # ---------- 双人合作:P2 的操作 ----------
    def _update_weapon_timers(self, p, dt):
        """武器计时:开火冷却 / 装填 / 自动换弹 / 受击闪光(每位玩家各算)。"""
        p.fire_cd = max(0.0, p.fire_cd - dt)
        if p.reloading:
            p.reload_t -= dt
            if p.reload_t <= 0:
                p.reload_t = 0
                p.reloading = False
                self._finish_reload(p)
        # 自动换弹:弹匣空了且背包里有对应弹药,自动开始装填(不必按 R)
        if (p.weapon is not None and not p.reloading and p.reload_t <= 0
                and p.weapon.state.get("mag", 0) <= 0
                and p.reserve_count() > 0 and not self.over):
            self.start_reload(p)
        p.hurt_flash = max(0.0, p.hurt_flash - dt)

    def _update_p2(self, dt, keys):
        """P2:方向键移动 + 自动瞄准最近可见敌人 + 动作键(全程不用鼠标)。"""
        p2 = self.player2
        if p2 is None or p2.out or self.over:
            return
        # 移动(换弹时减速;重武器换弹不能动)
        vx = float(self.key_down(keys, p2, "right")
                   - self.key_down(keys, p2, "left"))
        vy = float(self.key_down(keys, p2, "down")
                   - self.key_down(keys, p2, "up"))
        heavy = (p2.weapon is not None
                 and p2.weapon.def_.get("braced_immobile"))
        if p2.reloading and heavy:
            vx = vy = 0.0
        if vx or vy:
            length = math.hypot(vx, vy)
            spd = p2.speed(False) * (MOVE_RELOAD_MUL if p2.reloading else 1.0)
            p2.x, p2.y = self.map.move_circle(
                (p2.x, p2.y), vx / length * spd * dt, vy / length * spd * dt,
                PLAYER["radius"])
        # 瞄准:自动锁最近的可见敌人(看不到就朝移动方向)
        tgt = self.nearest_visible_enemy(p2.x, p2.y, COOP["aim_range"])
        if tgt is not None:
            p2.aim = math.atan2(tgt.y - p2.y, tgt.x - p2.x)
        elif vx or vy:
            p2.aim = math.atan2(vy, vx)
        # 开火:按住 = 连发,点按 = 点射(具体由武器射击模式决定)
        if self.dialogue is None and not self.over:
            self.try_fire(self.key_down(keys, p2, "fire"), p=p2,
                          edge=self.p2_fire_edge, braced=False)
        self.p2_fire_edge = False

    def _p2_key(self, key):
        """P2 按下的动作键(不认识的键直接忽略)。"""
        if self.player2 is None or self.player2.out:
            return
        k = COOP["keys"]
        if key in k["fire"]:
            self.p2_fire_edge = True
        elif key in k["interact"]:
            self.p2_interact()
        elif key in k["reload"]:
            if not (self.inv_open or self.loot_target is not None):
                self.start_reload(self.player2)
        elif key in k["heal"]:
            if not (self.inv_open or self.loot_target is not None):
                self.p2_quick_heal()

    def nearest_container_for(self, p, dist):
        best, bd = None, dist
        for lc in self.containers:
            d = math.hypot(lc.rect.centerx - p.x, lc.rect.centery - p.y)
            if d < bd:
                best, bd = lc, d
        return best

    def p2_interact(self):
        """P2 的交互:正在搜刮就停下;附近有箱子就开始自动搜刮。

        P2 不打开搜刮面板(鼠标是 P1 的),所以这里是「逐件搜出 + 直接进包」。
        """
        p2 = self.player2
        if self.p2_take is not None:
            self.p2_take = None
            self.add_toast("P2 停止搜刮", COL["text_dim"], 2.0)
            return
        lc = self.nearest_container_for(p2, COOP["bank_range"])
        if lc is None:
            self.add_toast("P2:附近没有可搜的箱子", COL["text_dim"], 2.2)
            return
        queue = list(lc.container.items)
        if not queue:
            self.add_toast(f"P2:{lc.name} 是空的", COL["text_dim"], 2.2)
            return
        self.p2_take = dict(lc=lc, queue=queue, t=0.0,
                            need=self.loot_take_time(queue[0].item))
        self.add_toast(f"P2 开始搜刮 {lc.name}(再按一次交互可停)", COL["accent"], 2.6)
        audio.play("click")

    def p2_take_one(self, lc, placed):
        """P2 拿走一件:空手时武器/护甲/头盔直接装上,否则进背包。放不下 = 停。"""
        p2 = self.player2
        item = placed.item
        if item.cat == "weapon" and p2.weapon is None \
                and armor_allows(p2.armor, item.def_):
            lc.container.remove_placed(placed)
            p2.weapon = item
            p2.burst_left = 0
            p2.reloading = False
            p2.reload_t = 0
        elif item.cat == "armor" and p2.armor is None:
            lc.container.remove_placed(placed)
            p2.armor = item
        elif item.cat == "helmet" and p2.helmet is None:
            lc.container.remove_placed(placed)
            p2.helmet = item
        elif not try_move(lc.container, placed, p2.bag):
            self.add_toast("P2 背包满了!先撤离(战利品并进仓库),或让 P1 收剩下的",
                           COL["bad"], 3.4)
            return False
        self._log_gained(item)
        audio.play("pickup")
        self.add_toast(f"P2 收走 {item.name}"
                       + (f" ×{item.count}" if item.count > 1 else ""),
                       COL["good"], 1.8)
        return True

    def _update_p2_take(self, dt):
        """P2 的自动搜刮:读条搜出身份 -> 收进自己背包 -> 下一件。"""
        tk = self.p2_take
        if tk is None or self.over:
            return
        p2 = self.player2
        if p2 is None or p2.out:
            self.p2_take = None
            return
        lc = tk["lc"]
        if lc not in self.containers or \
                math.hypot(lc.rect.centerx - p2.x,
                           lc.rect.centery - p2.y) > COOP["bank_range"]:
            self.p2_take = None
            self.add_toast("P2 离开太远,搜刮中断", COL["text_dim"], 2.2)
            return
        queue = [x for x in tk["queue"] if x in lc.container.items]
        if not queue:
            self.p2_take = None
            self.add_toast(f"P2:{lc.name} 搜完了", COL["good"], 2.4)
            return
        placed = queue[0]
        tk["t"] += dt
        if tk["t"] < tk["need"]:
            return
        self.mark_known(placed)
        if not self.p2_take_one(lc, placed):
            self.p2_take = None
            return
        tk["queue"] = queue[1:]
        tk["t"] = 0.0
        if tk["queue"]:
            tk["need"] = self.loot_take_time(tk["queue"][0].item)
        else:
            self.p2_take = None
            self.add_toast(f"P2:{lc.name} 搜完了", COL["good"], 2.4)

    def p2_quick_heal(self):
        """P2 打药:直接用手上最合适的那件(双人里 P2 不开背包,所以不读条)。"""
        p2 = self.player2
        if p2 is None or p2.out:
            return
        if p2.hp >= p2.max_hp:
            self.add_toast("P2:生命值已满", COL["text_dim"], 1.8)
            return
        meds = [pl for pl in p2.bag.items if pl.item.cat == "med"]
        if not meds:
            self.add_toast("P2:背包里没有医疗品", COL["bad"], 2.2)
            return
        missing = p2.max_hp - p2.hp
        cover = [pl for pl in meds if pl.item.def_.get("heal", 0) >= missing]
        pick = min(cover, key=lambda pl: pl.item.def_["heal"]) if cover else \
            max(meds, key=lambda pl: pl.item.def_["heal"])
        healed = p2.heal(pick.item.def_["heal"])
        p2.bag.remove_placed(pick)
        audio.play("heal")
        self.add_toast(f"P2 打药 +{healed}({pick.item.name})", COL["good"], 2.2)

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
        lay = raid_ui.inv_layout(p.bag.w, p.bag.h, p.safe.w, p.safe.h)
        pos = ev.pos
        if lay["close"].collidepoint(pos):
            self.inv_open = False
            self.drop_mode = False
            self.safe_mode = False
            audio.play("click")
            return
        # 整理弹药按钮 -> 弹确认框询问
        if lay["merge"].collidepoint(pos):
            self.ask_merge = True
            audio.play("click")
            return
        # 丢弃模式开关(手机没有右键:开着时点物品就丢)
        if lay["drop"].collidepoint(pos):
            self.drop_mode = not self.drop_mode
            audio.play("click")
            self.add_toast("丢弃模式已开启:点物品/装备槽就丢在地上" if self.drop_mode
                           else "丢弃模式已关闭(恢复:点物品=使用/装备)",
                           COL["accent" if self.drop_mode else "text_dim"], 3.0)
            return
        # 保险箱存入开关(手机没有右键:开着时点背包物品 = 存进保险箱)
        if lay["safe_mode"].collidepoint(pos):
            if self.mode in ("story", "assault"):
                self.add_toast("本模式装备为系统配发,保险箱只出不进", COL["bad"], 3.0)
                return
            self.safe_mode = not self.safe_mode
            audio.play("click")
            self.add_toast("保险箱存入已开启:点背包物品就存进保险箱(阵亡不丢)"
                           if self.safe_mode else
                           "保险箱存入已关闭(点保险箱里的物品可取回背包)",
                           COL["accent" if self.safe_mode else "text_dim"], 3.0)
            return
        # 保险箱:点物品取回背包(丢弃模式下直接丢地上)
        safe_pl = raid_ui.grid_hit_px(p.safe, lay["safe"], pos)
        if safe_pl is not None:
            if self.drop_mode:
                if self.drop_to_ground(safe_pl.item):
                    p.safe.remove_placed(safe_pl)
                    audio.play("click")
                    self.add_toast(f"丢弃 {safe_pl.item.name}", COL["text_dim"])
            elif try_move(p.safe, safe_pl, p.bag):
                audio.play("click")
                self.add_toast(f"{safe_pl.item.name} 已从保险箱取回", COL["text_dim"])
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        # 装备槽点击 = 卸下(丢弃模式下直接丢地上)
        if lay["weapon"].collidepoint(pos) and p.weapon is not None:
            old = p.weapon
            if self.drop_mode:
                p.weapon = None
                p.reloading = False
                p.reload_t = 0
                self.drop_to_ground(old)
                audio.play("click")
                self.add_toast(f"丢弃 {old.name}", COL["text_dim"])
            elif p.bag.add_item(old):
                p.weapon = None
                p.reloading = False   # 卸枪取消装填
                p.reload_t = 0
                audio.play("click")
            elif self.drop_to_ground(old):
                p.weapon = None
                p.reloading = False
                p.reload_t = 0
                audio.play("click")
                self.add_toast(f"{old.name} 放不进背包,已丢在脚边", COL["accent"], 3.0)
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
            if self.drop_mode:
                p.armor = None
                self.drop_to_ground(old)
                audio.play("click")
                self.add_toast(f"丢弃 {old.name}", COL["text_dim"])
            elif p.bag.add_item(old):
                p.armor = None
                audio.play("click")
            elif self.drop_to_ground(old):
                p.armor = None
                audio.play("click")
                self.add_toast(f"{old.name} 放不进背包,已丢在脚边", COL["accent"], 3.0)
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        if lay["helmet"].collidepoint(pos) and p.helmet is not None:
            old = p.helmet
            if self.drop_mode:
                p.helmet = None
                self.drop_to_ground(old)
                audio.play("click")
                self.add_toast(f"丢弃 {old.name}", COL["text_dim"])
            elif p.bag.add_item(old):
                p.helmet = None
                audio.play("click")
            elif self.drop_to_ground(old):
                p.helmet = None
                audio.play("click")
                self.add_toast(f"{old.name} 放不进背包,已丢在脚边", COL["accent"], 3.0)
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        placed = raid_ui.grid_hit_px(p.bag, lay["bag"], pos)
        if placed is None:
            return
        if ev.button == 3 or self.drop_mode:
            self.drop_from_bag(placed)
        elif ev.button == 1:
            if self.safe_mode:
                if self.mode in ("story", "assault"):
                    self.add_toast("本模式装备为系统配发,保险箱只出不进",
                                   COL["bad"], 3.0)
                elif try_move(p.bag, placed, p.safe):
                    audio.play("click")
                    self.add_toast(f"{placed.item.name} 已存进保险箱(阵亡不丢)",
                                   COL["good"], 2.6)
                else:
                    self.add_toast("保险箱放不下(40 个承包商任务可扩到 4 格)",
                                   COL["bad"], 3.0)
            elif placed.item.cat == "med":
                self.start_heal(placed)      # 打药要读条
            elif placed.item.cat in ("weapon", "armor", "helmet", "attach"):
                self.equip_from_bag(placed)
            else:
                self.add_toast(f"{placed.item.name}:自动装填消耗 / 右键丢弃",
                               COL["text_dim"], 1.8)

    def _handle_loot_click(self, ev):
        import raid_ui
        p = self.player          # 必须在两个分支前绑定:点背包侧也要用
        lay = raid_ui.loot_layout(self.loot_target.container.w,
                                  self.loot_target.container.h,
                                  p.bag.w, p.bag.h, p.safe.w, p.safe.h)
        lc = self.loot_target
        pos = ev.pos
        if ev.button != 1:
            return
        if lay["close"].collidepoint(pos):
            self.loot_target = None
            audio.play("click")
            return
        if lay["searchall"].collidepoint(pos):
            # 全部搜出 = 排队逐件搜索(每件都要读条)
            self.start_take(lc, list(lc.container.items))
            return
        if lay["takeall"].collidepoint(pos):
            # 全部拿走 = 只拿已经搜出来的(未知的先搜)
            n = 0
            for placed in list(lc.container.items):
                if self.is_known(placed) and self.take_known(lc, placed):
                    n += 1
            if n == 0:
                self.add_toast("这里还没有搜出来的东西(先点「全部搜出」)",
                               COL["text_dim"], 2.6)
            return
        placed = raid_ui.grid_hit_px(lc.container, lay["src"], pos)
        if placed is not None:
            if self.is_known(placed):
                self.take_known(lc, placed)      # 已知 = 直接拿走/装备
            else:
                self.start_take(lc, [placed])    # 未知 = 先搜(读条后才知道是什么)
            return
        safe_pl = raid_ui.grid_hit_px(p.safe, lay["safe"], pos)
        if safe_pl is not None:
            if try_move(p.safe, safe_pl, p.bag):
                audio.play("click")
                self.add_toast(f"{safe_pl.item.name} 已从保险箱取回", COL["text_dim"])
            else:
                self.add_toast("背包空间不足", COL["bad"])
            return
        placed = raid_ui.grid_hit_px(p.bag, lay["dst"], pos)
        if placed is not None:
            if getattr(self, "drop_mode", False):
                self.drop_from_bag(placed)      # 丢弃模式:直接从背包丢地上
                return
            if try_move(p.bag, placed, lc.container):
                self._unlog_gained(placed.item)   # 放回物品撤销搜刮记账
                self.mark_known(placed)           # 自己放进去的当然认得
                audio.play("click")
            else:
                self.add_toast("放不进去", COL["bad"])

    # ---- 触屏长按(背包/搜刮面板):点按延迟到抬起 + 详情面板 ----
    def _filter_hold_events(self, events):
        """触屏长按事件过滤。非触屏或没有面板打开时原样返回。"""
        active = (self.touch_mode and (self.inv_open or self.loot_target is not None)
                  and not (self.ask_merge or self.paused))
        if not active:
            self.hold.hide()
            return events
        out = []
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.hold.active():
                    # 面板已弹出:点动作按钮 = 执行(战局里只有"旋转");点别处 = 关闭
                    if (self.hold.action_rect is not None
                            and self.hold.action_rect.collidepoint(ev.pos)):
                        self._hold_action()
                    self.hold.hide()
                    continue
                self.hold.press(ev.pos)
                continue
            if ev.type == pygame.MOUSEMOTION:
                self.hold.move(ev.pos)
                out.append(ev)
                continue
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self.hold.consume_release():
                    # 普通点按:重放成一次按下(原逻辑照常)
                    out.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                                  pos=ev.pos, button=1))
                else:
                    out.append(ev)
                continue
            out.append(ev)
        return out

    def _hold_action(self):
        from inventory import rotate_in_place
        cb = self.hold.action_cb
        if cb is None:
            return
        container, placed = cb
        if placed is None or placed not in container.items:
            return
        res = rotate_in_place(container, placed)
        if res is None:
            self.add_toast(f"{placed.item.name} 是方形,不用旋转", COL["text_dim"], 2.0)
        elif res:
            audio.play("click")
            self.add_toast(f"已调整 {placed.item.name} 的摆放方向(横 / 竖)",
                           COL["text_dim"], 2.2)
        else:
            self.add_toast("原位转不开,先给它周围腾点地方", COL["bad"], 2.4)

    def _hold_query(self, pos):
        """长按落点查询:返回 (item, (container, placed)) / (item, None) / None。"""
        import raid_ui
        p = self.player
        if self.inv_open:
            lay = raid_ui.inv_layout(p.bag.w, p.bag.h, p.safe.w, p.safe.h)
            pl = raid_ui.grid_hit_px(p.bag, lay["bag"], pos)
            if pl is not None:
                return pl.item, (p.bag, pl)
            pl = raid_ui.grid_hit_px(p.safe, lay["safe"], pos)
            if pl is not None:
                return pl.item, (p.safe, pl)
            for key in ("weapon", "armor", "helmet"):
                if lay[key].collidepoint(pos):
                    it = getattr(p, key)
                    if it is not None:
                        return it, None
            return None
        if self.loot_target is not None:
            lc = self.loot_target
            lay = raid_ui.loot_layout(lc.container.w, lc.container.h,
                                      p.bag.w, p.bag.h, p.safe.w, p.safe.h)
            pl = raid_ui.grid_hit_px(lc.container, lay["src"], pos)
            if pl is not None:
                if not self.is_known(pl):
                    return None            # 未知物品:长按不泄底
                return pl.item, None
            pl = raid_ui.grid_hit_px(p.bag, lay["dst"], pos)
            if pl is not None:
                return pl.item, (p.bag, pl)
            pl = raid_ui.grid_hit_px(p.safe, lay["safe"], pos)
            if pl is not None:
                return pl.item, (p.safe, pl)
        return None

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
