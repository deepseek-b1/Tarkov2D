# -*- coding: utf-8 -*-
"""游戏状态机:藏身处 <-> 战局。"""
import pygame

import assault
import audio
import bindings
import quests
import save as save_mod
import story as story_mod
import raid_ui
from hideout import Hideout
from settings import W, H


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
        self.phase = "hideout"
        self.hideout = Hideout(self)
        self.raid = None
        self.quit = False
        # 突袭模式:系统配发装备前的配置快照(战局结束原样还原)
        self.assault_snap = None
        # 剧情模式:配发 M4A1 前的配置快照 + 本次配发清单
        self.story_snap = None
        self.story_issued = []

    def update(self, dt, events):
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

    def raid_finished(self, result):
        """战局结算:extract 保留装备,死亡/超时清空带入装备。
        突袭/剧情模式例外:配发装备一律回收,玩家的原配置原样还原;
        剧情模式撤离时,背包里的战利品会先放进仓库。"""
        sd = self.save
        assault_run = self.is_assault()
        story_run = self.is_story()
        sd.stats["kills"] += result["kills"]
        if result["kind"] == "extract":
            sd.stats["extracts"] += 1
            if not assault_run and not story_run:
                sd.stats["value"] += result["gained"]
                if self.raid is not None:
                    # 关键:战局内可能换装/卸装,撤离前把玩家当前装备写回存档,
                    # 否则同一物品会被同时序列化到槽位与背包(复制),新装备丢失
                    sd.weapon = self.raid.player.weapon
                    sd.armor = self.raid.player.armor
            if story_run:
                kept, lost = story_mod.bank_loot(sd)
                result["banked"] = kept
                result["bank_lost"] = lost
        else:
            sd.stats["deaths"] += 1
            if not assault_run and not story_run:
                sd.wipe_loadout()
        if assault_run:
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

    def shutdown(self):
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
        pygame.quit()
