# -*- coding: utf-8 -*-
"""游戏状态机:藏身处 <-> 战局。"""
import pygame

import assault
import audio
import save as save_mod
import raid_ui
from hideout import Hideout


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

    def update(self, dt, events):
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
        if self.is_assault():
            # 突袭:系统强制配发一套随机满配的高级装备(战后回收,不动仓库)
            self.assault_snap = assault.issue(self.save)
        self.raid = raid_mod.Raid(self)
        self.phase = "raid"
        self.save.stats["raids"] += 1

    def is_assault(self):
        return getattr(self.save, "mode", "raid") == "assault"

    def raid_finished(self, result):
        """战局结算:extract 保留装备,死亡/超时清空带入装备。
        突袭模式例外:配发装备与战利品一律回收,玩家的原配置原样还原。"""
        sd = self.save
        assault_run = self.is_assault()
        sd.stats["kills"] += result["kills"]
        if result["kind"] == "extract":
            sd.stats["extracts"] += 1
            if not assault_run:
                sd.stats["value"] += result["gained"]
                if self.raid is not None:
                    # 关键:战局内可能换装/卸装,撤离前把玩家当前装备写回存档,
                    # 否则同一物品会被同时序列化到槽位与背包(复制),新装备丢失
                    sd.weapon = self.raid.player.weapon
                    sd.armor = self.raid.player.armor
        else:
            sd.stats["deaths"] += 1
            if not assault_run:
                sd.wipe_loadout()
        if assault_run:
            assault.restore(sd, self.assault_snap)
            self.assault_snap = None
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
            save_mod.save_data(self.save)
        except Exception:
            pass
        pygame.quit()
