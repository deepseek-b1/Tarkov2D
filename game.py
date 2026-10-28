# -*- coding: utf-8 -*-
"""游戏状态机:藏身处 <-> 战局。"""
import sys

import pygame

import assault
import audio
import bindings
import mystery
import net as net_mod
import quests
import save as save_mod
import story as story_mod
import raid_ui
from hideout import Hideout
from settings import W, H, COOP_MODES


def _install_vsync_default():
    """给 display.set_mode 补一个「默认开 vsync」的兜底。

    为什么放在这里:main.py 里创建窗口的那行是

        screen = pygame.display.set_mode((W, H), flags)

    vsync 不传就是 0(不同步),帧率一高画面就会"撕"开(手机上表现为屏幕中间
    一条横贯的黑杠)。main.py 自己也修了,但**已经打包好的 exe 里 main 是编译好
    的字节码,改不动** —— 而 main 在创建窗口之前会先 `from game import Game`,
    所以把兜底放在这个模块里,已经打好的 exe 也能吃到。

    行为:
      * 调用方显式传了 vsync      -> 原样放行(不干扰 main.py 自己的回退逻辑)
      * 没传                      -> 先试 vsync=1,抛异常就退回不传
      * 平台不支持也不会崩,和改动前完全一致

    用 idempotent 标记防止被包装多次。
    """
    try:
        orig = pygame.display.set_mode
    except Exception:
        return
    if getattr(orig, "_t2d_vsync_default", False):
        return

    def set_mode(size=(0, 0), flags=0, depth=0, display=0, **kw):
        if "vsync" in kw:
            return orig(size, flags, depth, display, **kw)
        try:
            return orig(size, flags, depth, display, vsync=1, **kw)
        except Exception:
            return orig(size, flags, depth, display, **kw)

    set_mode._t2d_vsync_default = True
    pygame.display.set_mode = set_mode


_install_vsync_default()


def synth_mouse_events(events):
    """触屏模式:把 FINGER* 事件额外合成一份鼠标事件(带 synthetic 标记)。

    main 在触屏模式关掉了 SDL 的触摸→鼠标合成(SDL_TOUCH_MOUSE_EVENTS=0,
    不然虚拟摇杆会和界面点击双触发),但藏身处/背包/搜刮/暂停面板全是
    鼠标点击驱动的 —— 这里按需合成,让触屏能点所有界面。

    被标记 synthetic 的鼠标事件在战局操作里会被忽略(战局由 TouchUI
    消费原始 FINGER 事件),只在界面弹窗打开时才当点击用。
    """
    out = []
    for ev in events:
        out.append(ev)
        t = ev.type
        if t == pygame.FINGERDOWN:
            out.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                          pos=(ev.x * W, ev.y * H), button=1,
                                          synthetic=True))
        elif t == pygame.FINGERMOTION:
            out.append(pygame.event.Event(pygame.MOUSEMOTION,
                                          pos=(ev.x * W, ev.y * H),
                                          rel=(ev.dx * W, ev.dy * H),
                                          buttons=(1, 0, 0), synthetic=True))
        elif t == pygame.FINGERUP or t == getattr(pygame, "FINGERCANCEL", -1):
            out.append(pygame.event.Event(pygame.MOUSEBUTTONUP,
                                          pos=(ev.x * W, ev.y * H), button=1,
                                          synthetic=True))
    return out


class Game:
    def __init__(self, screen=None):
        self.screen = screen
        self.save = save_mod.load_data()
        # 礼品:神秘人每次"登录游戏"换一份收集清单(顺便掷一次机密文件)
        mystery.roll(self.save)
        self.phase = "hideout"
        self.hideout = Hideout(self)
        self.raid = None
        self.quit = False
        self.switch_account = False   # True = 回登录界面换账号(main 会重新登录)
        # 突袭模式:系统配发装备前的配置快照(战局结束原样还原)
        self.assault_snap = None
        # 剧情模式:配发 M4A1 前的配置快照 + 本次配发清单
        self.story_snap = None
        self.story_issued = []
        # 局域网联机:None / "host"(本机跑模拟)/ "client"(镜像主机)
        self.lan_role = None
        self.net = net_mod.Net(self)
        self._prewarm_map()
        self._lan_from_argv()

    def _prewarm_map(self):
        """把"下一张要打的地图"提前预渲染好。

        Raid 初始化时会把整张地图画进一张表面(1920×1408,实测约 150 ms),
        原来这笔开销正好落在**进战局的那一帧**上 —— 就是"点开始战局会卡一下"
        的来源。地图表面按 map_key 缓存,所以在这里(载入阶段,还没画第一帧)
        先付掉,之后每次进同一张图都是白拿。
        """
        try:
            from maps import MODE_MAP
            from world import GameMap, darkened_map
            from settings import COL, NIGHT_DARK_RGB, fog_darken
            mode = getattr(self.save, "mode", "raid")
            key = MODE_MAP.get(mode) or getattr(self.save, "map_key", "border")
            GameMap(key).prerender()
            # 快速迷雾用的「已压暗地图」也一起预热:生成一次约 100ms,
            # 不预热就会落在进战局的第一帧上。只预热当前会用到的那一档。
            dark_tint = (fog_darken((*NIGHT_DARK_RGB, 255)) if mode == "night"
                         else fog_darken(COL["fog"]))
            darkened_map(key, dark_tint)
        except Exception:
            pass

    def update(self, dt, events):
        # 联机消息(主机:收输入/发快照由 after_update 做;客户端:收状态/开局)
        try:
            self.net.tick(dt)
        except Exception:
            pass
        if self.save.touch:
            events = synth_mouse_events(events)
        for ev in events:
            if ev.type == pygame.QUIT:
                self.request_quit()
        if self.quit:
            return
        if self.phase == "hideout":
            self.hideout.update(dt, events)
        elif self.raid is not None:
            self.raid.update(dt, events)
        # --lan-auto:对方一连上就自动开局(只开一次)
        if (self._lan_auto_once and self.phase == "hideout"
                and self.lan_role is None and self.net.role == "host"
                and self.net.link is not None and self.net._client_ready):
            self._lan_auto_once = False
            try:
                self.lan_start_raid()
            except Exception:
                pass
        if self.lan_role == "host" and self.phase == "raid" and self.raid is not None:
            try:
                self.net.host_after_update(self.raid, dt)
            except Exception:
                pass

    def draw(self, screen):
        if self.phase == "hideout":
            self.hideout.draw(screen)
        elif self.raid is not None:
            raid_ui.draw_raid(self.raid, screen)

    def start_raid(self):
        import raid as raid_mod
        self.story_issued = []
        if self.is_assault():
            # 突袭:系统强制配发一套随机满配的高级装备(战后回收,不动仓库)
            self.assault_snap = assault.issue(self.save)
        elif self.is_coop():
            # 双人合作:两位玩家都由系统配发装备(战后回收,不动仓库),
            # 撤离时背包里的战利品会先并进仓库 —— 仓库里自己的装备不会被碰
            self.assault_snap = assault.issue(self.save)
        elif self.is_story():
            # 剧情:系统配发 M4A1 + 6 级甲 + 药品(战后回收,不动仓库);
            # 撤离时背包里的战利品会先存进仓库再回收配发装备
            self.story_snap = assault.snapshot(self.save)
            self.story_issued = story_mod.issue_kit(self.save)
        self.raid = raid_mod.Raid(self)
        self.phase = "raid"
        self.save.stats["raids"] += 1

    def is_assault(self):
        return getattr(self.save, "mode", "raid") == "assault"

    def is_story(self):
        return getattr(self.save, "mode", "raid") == "story"

    def is_coop(self):
        """双人合作(同一台电脑两人玩):搜打撤 / 夜战都能开,手机模式不行(要键盘)。"""
        return (bool(getattr(self.save, "coop", False))
                and getattr(self.save, "mode", "raid") in COOP_MODES
                and not getattr(self.save, "touch", False))

    # ---------- 局域网联机(见 net.py) ----------
    def _lan_from_argv(self):
        """命令行开关:--lan-host / --lan-join [IP] / --lan-auto(不想点界面时用)。"""
        argv = sys.argv[1:]
        self._lan_auto_once = False
        try:
            if "--lan-host" in argv:
                self.net.host_room()
            elif "--lan-join" in argv:
                i = argv.index("--lan-join")
                ip = None
                if i + 1 < len(argv) and not argv[i + 1].startswith("-"):
                    ip = argv[i + 1]
                self.net.join(ip)
            if "--lan-auto" in argv and self.net.role == "host":
                # 等对方一连上就自动开局(免人工点按钮,方便快速开局/自动化)
                self._lan_auto_once = True
        except Exception:
            pass

    def lan_host_ready(self):
        """主机:对方是否已经连上(连上才能开局)。"""
        return self.net.role == "host" and self.net.link is not None

    def lan_start_raid(self):
        """主机:开一局联机战局,并把开局配置发给客户端。"""
        if not self.lan_host_ready():
            return False
        sd = self.save
        sd.coop = True
        sd.touch = False
        if getattr(sd, "mode", "raid") not in COOP_MODES:
            sd.mode = "raid"      # 联机只支持搜打撤 / 夜战(和同屏双人一致)
        self.lan_role = "host"
        try:
            self.start_raid()
        except Exception:
            self.lan_role = None
            raise
        raid = self.raid
        self.net.host_start(dict(
            mode=raid.mode, diff_key=getattr(raid, "diff_key", None),
            map_key=raid.map_key, time_left=raid.time_left, coop=True,
            host=getattr(sd, "name", "") or self.net.room_name))
        return True

    def lan_client_begin(self, cfg):
        """客户端:收到主机的开局配置,在自己这边准备一份镜像战局。"""
        sd = self.save
        sd.coop = True
        sd.touch = False
        sd.mode = cfg.get("mode") or "raid"
        if cfg.get("diff_key"):
            sd.difficulty = cfg["diff_key"]
        if cfg.get("map_key"):
            sd.map_key = cfg["map_key"]
        self.lan_role = "client"
        self.start_raid()
        raid = self.raid
        raid.lan = "client"
        raid.add_toast("已加入房主的战局 —— 交互键自动搜刮 / 打药键用药 / 换弹键换弹",
                       None, 6.0)

    def lan_client_extract(self, data):
        """主机说:本机玩家撤出去了。主机挑好的战利品进**本机**仓库。"""
        raid = self.raid
        if raid is None:
            return
        kept = lost = 0
        for node in ((data or {}).get("loot") or []):
            try:
                item = net_mod.decode_value(node, raid)
            except Exception:
                item = None
            if item is None:
                continue
            try:
                if self.save.stash.add_item(item):
                    kept += 1
                else:
                    lost += 1
            except Exception:
                lost += 1
        raid.banked += kept
        raid.bank_lost += lost
        msg = "撤离成功!战利品已进你自己的仓库(%d 件)" % kept
        if lost:
            msg += " —— 仓库塞不下,丢了 %d 件" % lost
        raid.add_toast(msg, None, 6.0)
        try:
            save_mod.save_data(self.save)
        except Exception:
            pass

    def lan_client_over(self, data):
        """主机结算:客户端跟着结算,显示同一张结算页。"""
        raid = self.raid
        if raid is None:
            return
        result = (data or {}).get("result")
        if isinstance(result, dict):
            raid.result = result
        if not raid.over:
            raid.over = True
            try:
                self.raid_finished(raid.result or {})
            except Exception:
                pass

    def lan_abort(self):
        """和主机断开:回藏身处,别让本机卡在一个没人管的战局里。"""
        if self.phase != "raid":
            self.lan_role = None
            return
        try:
            if self.assault_snap is not None:
                assault.restore(self.save, self.assault_snap)
                self.assault_snap = None
            save_mod.save_data(self.save)
        except Exception:
            pass
        self.raid = None
        self.phase = "hideout"
        self.lan_role = None
        try:
            self.hideout.say("与主机断开连接,已回到藏身处", None, 4.0)
        except Exception:
            pass

    def raid_finished(self, result):
        """战局结算:extract 保留装备,死亡/超时清空带入装备。
        突袭/剧情/双人合作模式例外:配发装备一律回收,玩家的原配置原样还原;
        剧情与双人合作撤离时,背包里的战利品会先放进仓库。"""
        sd = self.save
        assault_run = self.is_assault()
        story_run = self.is_story()
        coop_run = self.is_coop()
        sd.stats["kills"] += result["kills"]
        if result["kind"] == "extract":
            sd.stats["extracts"] += 1
            if not assault_run and not story_run and not coop_run:
                sd.stats["value"] += result["gained"]
                if self.raid is not None:
                    # 关键:战局内可能换装/卸装,撤离前把玩家当前装备写回存档,
                    # 否则同一物品会被同时序列化到槽位与背包(复制),新装备丢失
                    sd.weapon = self.raid.player.weapon
                    sd.armor = self.raid.player.armor
                    sd.helmet = getattr(self.raid.player, "helmet", None)
            if story_run:
                kept, lost = story_mod.bank_loot(sd)
                result["banked"] = kept
                result["bank_lost"] = lost
            if coop_run:
                # 战利品在「各自撤离」那一刻就已经进仓库了(见 raid.player_extracted),
                # 这里只记收益;谁背包丢了看结算页的每人结果
                sd.stats["value"] += result["gained"]
        elif not coop_run:
            sd.stats["deaths"] += 1
            if not assault_run and not story_run:
                sd.wipe_loadout()
        if coop_run and self.raid is not None:
            # 双人合作按人数记阵亡(有人撤出去过这局算 extract,倒下的单独累加)
            sd.stats["deaths"] += sum(1 for q in self.raid.players() if q.dead)
        if assault_run or coop_run:
            assault.restore(sd, self.assault_snap)
            self.assault_snap = None
        if story_run:
            # 配发装备回收:玩家自己的出战配置原样还原(撤离时的战利品已存进仓库)
            assault.restore(sd, getattr(self, "story_snap", None))
            self.story_snap = None
        # 任务进度(教官任务按类型累计;突袭只算击杀/撤离,不进"物资价值")
        quests.add_progress(sd, "kills", result["kills"])
        if result["kind"] == "extract":
            quests.add_progress(sd, "extracts", 1)
            if result.get("mode") == "raid":
                quests.add_progress(sd, "value", result["gained"])
            if result.get("mode") == "hostage" and result.get("mission"):
                quests.add_progress(sd, "hostage_win", 1)
            if result.get("mode") == "assault" and result.get("mission"):
                quests.add_progress(sd, "assault_win", 1)
        save_mod.save_data(sd)

    def to_hideout(self):
        self.raid = None
        self.phase = "hideout"

    def request_quit(self):
        # 战局中途退出按阵亡处理(MIA),避免关窗回档
        if self.phase == "raid" and self.raid is not None and not self.raid.over:
            self.raid.finish("mia")
        self.quit = True

    def request_switch_account(self):
        """回登录界面换账号(藏身处设置页)。战局中不允许(先撤/先死)。"""
        if self.phase != "hideout":
            return False
        self.switch_account = True
        self.quit = True
        return True

    def shutdown(self, keep_window=False):
        try:
            self.net.close(notify=True)
        except Exception:
            pass
        try:
            if self.assault_snap is not None:
                # 中途关窗也要把配发装备还掉,别把系统装备写进存档
                assault.restore(self.save, self.assault_snap)
                self.assault_snap = None
            if getattr(self, "story_snap", None) is not None:
                assault.restore(self.save, self.story_snap)
                self.story_snap = None
            save_mod.save_data(self.save)
        except Exception:
            pass
        if not keep_window:
            pygame.quit()
