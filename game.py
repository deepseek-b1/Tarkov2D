# -*- coding: utf-8 -*-
"""游戏状态机:藏身处 <-> 战局。"""
import pygame

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
        self.raid = raid_mod.Raid(self)
        self.phase = "raid"
        self.save.stats["raids"] += 1

    def raid_finished(self, result):
        """战局结算:extract 保留装备,死亡/超时清空带入装备。"""
        sd = self.save
        sd.stats["kills"] += result["kills"]
        if result["kind"] == "extract":
            sd.stats["extracts"] += 1
            sd.stats["value"] += result["gained"]
            if self.raid is not None:
                # 关键:战局内可能换装/卸装,撤离前把玩家当前装备写回存档,
                # 否则同一物品会被同时序列化到槽位与背包(复制),新装备丢失
                sd.weapon = self.raid.player.weapon
                sd.armor = self.raid.player.armor
        else:
            sd.stats["deaths"] += 1
            sd.wipe_loadout()
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
            save_mod.save_data(self.save)
        except Exception:
            pass
        pygame.quit()
