# -*- coding: utf-8 -*-
"""藏身处:仓库管理、出战整备、开局。"""
import time

import pygame

import audio
import intro
import quests
import save as save_mod
from settings import (W, H, COL, fmt_rub, get_font, DIFF_ORDER, DIFFICULTIES,
                      weapon_slots, weapon_attach, weapon_capacity, ATTACH_SLOTS,
                      ITEMS, TRADE_GOODS, TRADE_TABS, TRADE_PAGE_H,
                      trade_buy_price, trade_sell_price, STASH_VIEW_ROWS,
                      MODE_DIFF, DEPTS, TASKS,
                      armor_allows, MAPS, MAP_ORDER, MODES, MODE_ORDER, MODE_MAP)
from inventory import Item, Placed, try_move
import uikit
from uikit import draw_grid, draw_button, draw_slot, draw_tooltip


def _layout():
    return dict(
        stash_panel=pygame.Rect(30, 100, 470, 430),
        loadout_panel=pygame.Rect(516, 100, 390, 430),
        side_panel=pygame.Rect(922, 100, 330, 438),
        weapon=pygame.Rect(542, 146, 110, 84),
        armor=pygame.Rect(662, 146, 110, 84),
        pack=pygame.Rect(782, 146, 110, 84),
        bag_origin=(542, 262),      # 出战背包网格原点(cell 动态)
        intro_btn=pygame.Rect(542, 484, 170, 34),
        touch_btn=pygame.Rect(722, 484, 160, 34),
        start=pygame.Rect(542, 548, 340, 54),
        supply=pygame.Rect(30, 548, 220, 46),
        reset=pygame.Rect(262, 548, 220, 46),
        trade=pygame.Rect(922, 548, 160, 46),
        tasks=pygame.Rect(1092, 548, 160, 46),
        trade_stash=pygame.Rect(30, 100, 470, 570),
        trade_goods=pygame.Rect(530, 100, 720, 570),
    )


BAG_MAX_CELL = 46      # 出战背包网格最大格子边长
BAG_AREA_W = 340       # 可用于背包网格的宽度


class Hideout:
    def __init__(self, game):
        self.game = game
        self.msg = ""
        self.msg_t = 0.0
        self.msg_col = COL["text"]
        self.reset_armed = 0.0
        self.view = "stash"    # stash / trade
        self.lay = _layout()
        sp = self.lay["side_panel"]
        # 地图按钮改两行排布(现在有 5 张图)
        self.map_rects = []
        for i in range(len(MAP_ORDER)):
            row, col = divmod(i, 3)
            self.map_rects.append(pygame.Rect(
                sp.x + 18 + col * 100, sp.y + 62 + row * 34, 92, 30))
        self.mode_rects = [pygame.Rect(sp.x + 18 + i * 100, sp.y + 172, 92, 30)
                           for i in range(len(MODE_ORDER))]
        self.diff_rects = [pygame.Rect(sp.x + 18 + i * 100, sp.y + 248, 92, 30)
                           for i in range(3)]
        # 仓库滚轮(仓库格子变多了,面板只显示一部分)
        self.stash_scroll = 0.0
        self.stash_grid = (66, 176)
        self.stash_view_h = 40 * STASH_VIEW_ROWS
        # 任务中心:三个部门(教官 / 医疗部门 / 后勤部门)
        self.task_dept = "instructor"
        self.task_scroll = 0.0
        self.task_tab_rects = [pygame.Rect(548 + i * 214, 132, 200, 32)
                               for i in range(len(DEPTS))]
        self.task_view_top = 186
        self.task_view_bottom = 600
        self.task_row_h = 56
        self.task_close = pygame.Rect(1140, 76, 100, 36)
        # 交易所:仓库网格 66,150 / 分区标签 / 商品行(双列可滚动) / 返回按钮
        self.trade_stash_grid = (66, 150)
        self.trade_stash_view_h = 12 * 40     # 交易所左侧仓库可见高度(其余滚轮翻)
        self.trade_cat = None            # 当前分区(None = 全部)
        self.trade_scroll = 0.0          # 滚轮偏移(像素)
        self.trade_tab_rects = [
            pygame.Rect(548 + i * 86, 132, 80, 30) for i in range(len(TRADE_TABS))]
        self.trade_view_top = 178        # 商品区可见范围
        self.trade_view_bottom = 178 + TRADE_PAGE_H
        self.trade_close = pygame.Rect(1140, 76, 100, 36)
        # 玩法简介(首次启动自动弹出)
        self.show_intro = not getattr(self.game.save, "seen_intro", False)
        self.intro_page = 0

    # ---- 交易站:分区商品与滚动 ----
    def trade_goods(self):
        """当前分区的商品列表(「特殊枪械」= 头目专属枪械)。"""
        from settings import trade_cat_match
        return [g for g in TRADE_GOODS if trade_cat_match(g[0], self.trade_cat)]

    def trade_rows(self):
        """返回 (商品列表, 每列行数, 行高)。"""
        goods = self.trade_goods()
        n = max(1, len(goods))
        per = (n + 1) // 2
        row_h = 30 if per > 11 else 36
        return goods, per, row_h

    def trade_row_rect(self, i, per, row_h):
        col, row = divmod(i, per)
        return pygame.Rect(548 + col * 352,
                           self.trade_view_top + row * (row_h + 4) - int(self.trade_scroll),
                           344, row_h)

    def trade_max_scroll(self):
        goods, per, row_h = self.trade_rows()
        rows = (len(goods) + 1) // 2
        content_bottom = self.trade_view_top + rows * (row_h + 4)
        return max(0.0, float(content_bottom - self.trade_view_bottom))

    # ---- 仓库滚轮 ----
    def stash_max_scroll(self):
        total = self.game.save.stash.h * 40
        return max(0.0, float(total - self.stash_view_h))

    def stash_visible_rect(self):
        ox, oy = self.stash_grid
        return pygame.Rect(ox, oy, self.game.save.stash.w * 40, self.stash_view_h)

    # 交易所里的仓库面板(比藏身处窄一点,可见高度也不同)
    def trade_stash_max_scroll(self):
        total = self.game.save.stash.h * 40
        return max(0.0, float(total - self.trade_stash_view_h))

    def trade_stash_hit(self, pos):
        ox, oy = self.trade_stash_grid
        if not pygame.Rect(ox, oy, self.game.save.stash.w * 40,
                           self.trade_stash_view_h).collidepoint(pos):
            return None
        gx = int((pos[0] - ox) // 40)
        gy = int((pos[1] - oy + int(self.stash_scroll)) // 40)
        return self.game.save.stash.at(gx, gy)

    def stash_hit(self, pos):
        """按当前滚动偏移把屏幕坐标换算成仓库里的物品。"""
        ox, oy = self.stash_grid
        if not self.stash_visible_rect().collidepoint(pos):
            return None
        gx = int((pos[0] - ox) // 40)
        gy = int((pos[1] - oy + int(self.stash_scroll)) // 40)
        return self.game.save.stash.at(gx, gy)

    # ---- 背包卷起 / 展开 ----
    def _toggle_roll(self, container, placed):
        """把背包卷起(占格变小)或展开(占格变大,要先看放不放得下)。"""
        it = placed.item
        if it.cat != "pack":
            return False, ""
        wanted = not it.is_rolled()
        container.remove_placed(placed)
        if wanted:
            it.state["rolled"] = True
            container.items.append(Placed(it, placed.x, placed.y))
            rw, rh = it.roll_size()
            return True, f"{it.name} 已卷起(占 {rw}×{rh} 格)"
        it.state["rolled"] = False
        if container.fits(it, placed.x, placed.y):
            container.items.append(Placed(it, placed.x, placed.y))
        else:
            pos = container.find_space(it)
            if pos is None:
                it.state["rolled"] = True        # 放不下就保持卷起状态
                container.items.append(Placed(it, placed.x, placed.y))
                return False, f"空间不够,展不开 {it.name}(先清出 {it.def_['w']}×{it.def_['h']} 格)"
            it.rot = pos[2]
            container.items.append(Placed(it, pos[0], pos[1]))
        return True, f"{it.name} 已展开"

    def _right_click(self, pos):
        """仓库/出战背包里右键背包 -> 卷起/展开。"""
        sd = self.game.save
        if self.lay["stash_panel"].collidepoint(pos):
            placed = self.stash_hit(pos)
            if placed is not None and placed.item.cat == "pack":
                ok, msg = self._toggle_roll(sd.stash, placed)
                if msg:
                    save_mod.save_data(sd)
                    audio.play("click")
                    self.say(msg, COL["good"] if ok else COL["bad"], 3.0)
            return
        if self.bag_rect().collidepoint(pos):
            cell = self.bag_cell()
            brect = self.bag_rect()
            gx = int((pos[0] - brect.x) // cell)
            gy = int((pos[1] - brect.y) // cell)
            placed = sd.bag.at(gx, gy)
            if placed is not None and placed.item.cat == "pack":
                ok, msg = self._toggle_roll(sd.bag, placed)
                if msg:
                    save_mod.save_data(sd)
                    audio.play("click")
                    self.say(msg, COL["good"] if ok else COL["bad"], 3.0)

    # ---- 任务中心 ----
    def task_entries(self):
        """当前部门的条目列表。"""
        if self.task_dept == "instructor":
            return [(t, quests.task_state(self.game.save, t)) for t in TASKS]
        return [(e, ("doing" if not quests.can_barter(self.game.save, e) else "ready"),
                 None, None) for e in quests.barter_list(self.task_dept)]

    def task_rows(self):
        entries = self.task_entries()
        return entries, max(1, int((self.task_view_bottom - self.task_view_top)
                                   // self.task_row_h))

    def task_row_rect(self, i):
        return pygame.Rect(530, self.task_view_top + i * self.task_row_h
                           - int(self.task_scroll), 720, self.task_row_h - 6)

    def task_max_scroll(self):
        entries, per = self.task_rows()
        content = self.task_view_top + len(entries) * self.task_row_h
        return max(0.0, float(content - self.task_view_bottom))

    def _task_click(self, pos):
        sd = self.game.save
        audio.play("click")
        if self.task_close.collidepoint(pos):
            self.view = "stash"
            save_mod.save_data(sd)
            return
        for i, (key, _label) in enumerate(DEPTS):
            if self.task_tab_rects[i].collidepoint(pos):
                self.task_dept = key
                self.task_scroll = 0.0
                return
        entries, per = self.task_rows()
        for i, entry in enumerate(entries):
            if not self.task_row_rect(i).collidepoint(pos):
                continue
            if self.task_dept == "instructor":
                task = entry[0]
                ok, msg = quests.claim(sd, task)
            else:
                barter = entry[0]
                ok, msg = quests.barter(sd, barter)
            save_mod.save_data(sd)
            self.say(msg, COL["good"] if ok else COL["bad"], 3.4)
            return

    # ---- 出战背包网格(容量随装备的背包变化) ----
    def bag_cell(self):
        bw = max(1, self.game.save.bag.w)
        return max(20, min(BAG_MAX_CELL, BAG_AREA_W // bw))

    def bag_rect(self):
        ox, oy = self.lay["bag_origin"]
        b = self.game.save.bag
        return pygame.Rect(ox, oy, b.w * self.bag_cell(), b.h * self.bag_cell())

    def say(self, text, color=None, ttl=2.6):
        self.msg = text
        self.msg_t = ttl
        self.msg_col = color or COL["text"]

    # ---------- 逻辑 ----------
    def update(self, dt, events):
        self.msg_t -= dt
        self.reset_armed = max(0.0, self.reset_armed - dt)
        # 玩法简介:先读完再进游戏
        if self.show_intro:
            for ev in events:
                if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN,
                               pygame.FINGERDOWN):
                    nxt = intro.advance(self.intro_page)
                    audio.play("click")
                    if nxt is None:
                        self.show_intro = False
                        self.game.save.seen_intro = True
                        save_mod.save_data(self.game.save)
                    else:
                        self.intro_page = nxt
            return
        for ev in events:
            if ev.type == pygame.MOUSEWHEEL:
                if self.view == "trade":
                    # 鼠标压在左边仓库上 -> 翻仓库;否则翻商品
                    st = self.trade_stash_grid
                    stash_area = pygame.Rect(st[0], st[1],
                                             self.game.save.stash.w * 40,
                                             self.trade_stash_view_h)
                    if stash_area.collidepoint(pygame.mouse.get_pos()):
                        self.stash_scroll -= ev.y * 40
                        self.stash_scroll = max(0.0, min(self.stash_scroll,
                                                         self.trade_stash_max_scroll()))
                    else:
                        self.trade_scroll -= ev.y * 48
                        self.trade_scroll = max(0.0, min(self.trade_scroll,
                                                         self.trade_max_scroll()))
                elif self.view == "stash":
                    self.stash_scroll -= ev.y * 40
                    self.stash_scroll = max(0.0, min(self.stash_scroll,
                                                     self.stash_max_scroll()))
                elif self.view == "task":
                    self.task_scroll -= ev.y * 44
                    self.task_scroll = max(0.0, min(self.task_scroll,
                                                    self.task_max_scroll()))
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE and self.view in ("trade", "task"):
                    self.view = "stash"
                    save_mod.save_data(self.game.save)
                    audio.play("click")
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
                # 右键:仓库/背包里的背包类物品 卷起 / 展开
                if self.view == "stash":
                    self._right_click(ev.pos)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.view == "trade":
                    self._trade_click(ev.pos)
                elif self.view == "task":
                    self._task_click(ev.pos)
                else:
                    self._click(ev.pos)
                return

    def _click(self, pos):
        sd = self.game.save
        lay = self.lay
        audio.play("click")

        # 地图选择(人质大楼/大本营 = 专用模式地图)
        for i, key in enumerate(MAP_ORDER):
            if self.map_rects[i].collidepoint(pos):
                sd.map_key = key
                if key == "indoor":
                    sd.mode = "hostage"
                elif key == "base":
                    sd.mode = "assault"
                elif sd.mode in ("hostage", "assault"):
                    sd.mode = "raid"
                save_mod.save_data(sd)
                self.say(f"出战地图已设为「{MAPS[key]['name']}」:{MAPS[key]['desc']}",
                         COL["accent"], ttl=3.2)
                return

        # 模式选择
        for i, key in enumerate(MODE_ORDER):
            if self.mode_rects[i].collidepoint(pos):
                sd.mode = key
                forced = MODE_MAP.get(key)
                if forced:
                    sd.map_key = forced
                save_mod.save_data(sd)
                self.say(f"模式已设为「{MODES[key]['name']}」:{MODES[key]['desc']}",
                         COL["accent"], ttl=3.2)
                return

        # 难度选择(突袭/人质解救是固定强度,没有难度档)
        if sd.mode == "assault" or sd.mode in MODE_DIFF:
            fixed_txt = ("突袭模式是固定强度,不适用难度档(系统会配发满配装备)"
                         if sd.mode == "assault"
                         else "人质解救固定为强化封锁强度,不适用难度档")
            for r in self.diff_rects:
                if r.collidepoint(pos):
                    self.say(fixed_txt, COL["bad"], 3.0)
                    return
        else:
            for i, key in enumerate(DIFF_ORDER):
                if self.diff_rects[i].collidepoint(pos):
                    sd.difficulty = key
                    save_mod.save_data(sd)
                    d = DIFFICULTIES[key]
                    self.say(f"难度已设为「{d['name']}」:{d['desc']},{d['loot_desc']}",
                             COL["accent"], ttl=3.2)
                    return

        # 底部按钮
        if lay["intro_btn"].collidepoint(pos):
            self.show_intro = True
            self.intro_page = 0
            return
        if lay["touch_btn"].collidepoint(pos):
            sd.touch = not sd.touch
            save_mod.save_data(sd)
            self.say("已开启手机(触屏)模式:左半屏摇杆 + 右侧按钮 + 自动锁敌" if sd.touch
                     else "已切回电脑模式(键盘 + 鼠标)", COL["accent"], 3.2)
            return
        if lay["start"].collidepoint(pos):
            self.game.start_raid()
            return
        if lay["trade"].collidepoint(pos):
            self.view = "trade"
            self.trade_scroll = 0.0
            audio.play("click")
            return
        if lay["tasks"].collidepoint(pos):
            self.view = "task"
            self.task_scroll = 0.0
            audio.play("click")
            return
        if lay["supply"].collidepoint(pos) and not sd.any_weapon():
            sd.weapon = Item.weapon("pm", mag=8)
            if sd.pack is None:
                sd.pack = Item("pack_mid")
                sd.apply_pack()
            sd.bag.add_item(Item("a9", count=30))
            sd.bag.add_item(Item("bandage"))
            save_mod.save_data(sd)
            self.say("已领取基础补给:PM 手枪 + 弹药 + 绷带 + 背包", COL["good"])
            return
        if lay["reset"].collidepoint(pos):
            if self.reset_armed > 0:
                self.game.save = save_mod.reset_data()
                self.reset_armed = 0
                self.say("存档已重置", COL["good"])
            else:
                self.reset_armed = 3.0
                self.say("再次点击按钮确认清空存档!", COL["bad"])
            return

        # 装备槽:卸下
        if lay["weapon"].collidepoint(pos):
            if sd.weapon is not None:
                old = sd.weapon
                if sd.stash.add_item(old):
                    sd.weapon = None
                    save_mod.save_data(sd)
                else:
                    self.say("仓库空间不足", COL["bad"])
            return
        if lay["armor"].collidepoint(pos):
            if sd.armor is not None:
                if sd.weapon is not None and not armor_allows(None, sd.weapon.def_):
                    self.say(f"手里的 {sd.weapon.name} 需要 6 级甲,先换掉武器",
                             COL["bad"], 3.2)
                    return
                old = sd.armor
                if sd.stash.add_item(old):
                    sd.armor = None
                    save_mod.save_data(sd)
                else:
                    self.say("仓库空间不足", COL["bad"])
            return
        if lay["pack"].collidepoint(pos):
            ok, msg = self._try_unequip_pack()
            self.say(msg, COL["good"] if ok else COL["bad"], 3.0)
            return

        # 仓库物品 -> 装备/出战背包
        if lay["stash_panel"].collidepoint(pos):
            placed = self.stash_hit(pos)
            if placed is not None:
                item = placed.item
                if item.cat == "weapon":
                    if not armor_allows(sd.armor, item.def_):
                        self.say(f"需先穿上 {item.def_['req_armor_level']} 级护甲,"
                                 f"才拿得动 {item.name}", COL["bad"], 3.2)
                        return
                    old = sd.weapon
                    sd.stash.remove_placed(placed)
                    if old is not None and not sd.stash.add_item(old):
                        sd.stash.items.append(placed)
                        self.say("仓库空间不足", COL["bad"])
                        return
                    sd.weapon = item
                    save_mod.save_data(sd)
                    self.say(f"装备武器 {item.name}")
                elif item.cat == "armor":
                    old = sd.armor
                    sd.stash.remove_placed(placed)
                    if old is not None and not sd.stash.add_item(old):
                        sd.stash.items.append(placed)
                        self.say("仓库空间不足", COL["bad"])
                        return
                    sd.armor = item
                    save_mod.save_data(sd)
                    self.say(f"装备护甲 {item.name}")
                elif item.cat == "attach":
                    self._install_attachment(sd, placed)
                elif item.cat == "pack":
                    idx = sd.stash.items.index(placed)
                    ok, msg = self._try_equip_pack(idx)
                    self.say(msg, COL["good"] if ok else COL["bad"], 3.0)
                else:
                    if try_move(sd.stash, placed, sd.bag):
                        self.say(f"{item.name} 已放入出战背包")
                    else:
                        self.say("出战背包空间不足", COL["bad"])
            return

        # 出战背包 -> 仓库
        if self.bag_rect().collidepoint(pos):
            cell = self.bag_cell()
            ox, oy = lay["bag_origin"]
            gx = int((pos[0] - ox) // cell)
            gy = int((pos[1] - oy) // cell)
            placed = sd.bag.at(gx, gy)
            if placed is not None:
                if try_move(sd.bag, placed, sd.stash):
                    self.say(f"{placed.item.name} 已放回仓库")
                else:
                    self.say("仓库空间不足", COL["bad"])
            return

    # ---------- 配件安装 ----------
    def _install_attachment(self, sd, placed):
        item = placed.item
        w = sd.weapon
        slot = item.def_.get("slot")
        if w is None:
            self.say("先装备武器,再点配件安装", COL["bad"], 3.0)
            return
        if slot not in weapon_slots(w.iid):
            self.say(f"{w.name} 不支持{ATTACH_SLOTS.get(slot, '该')}配件"
                     + ("(机枪不装配件)" if w.iid == "m139" else ""),
                     COL["bad"], 3.2)
            return
        old = weapon_attach(w).get(slot)
        if old is not None and not sd.stash.add_item(Item(old)):
            self.say("仓库空间不足,无法换下旧配件", COL["bad"])
            return
        sd.stash.remove_placed(placed)
        w.state.setdefault("attach", {})[slot] = item.iid
        cap = weapon_capacity(w)
        if w.state.get("mag", 0) > cap:
            w.state["mag"] = cap
        save_mod.save_data(sd)
        self.say(f"已给 {w.name} 装上 {item.name}({ATTACH_SLOTS.get(slot, '')})",
                 COL["good"], 3.0)

    # ---------- 背包装卸(克隆试算,失败不改动) ----------
    @staticmethod
    def _clone_item(it):
        return Item.from_dict(it.serialize()) if it is not None else None

    def _try_equip_pack(self, idx):
        """从仓库第 idx 件物品装备背包。"""
        from inventory import Container
        from settings import pack_grid
        sd = self.game.save
        if idx >= len(sd.stash.items):
            return False, "物品已变化"
        new_pack = sd.stash.items[idx].item
        if new_pack.cat != "pack":
            return False, ""
        new_pack.state.pop("rolled", None)     # 装备时自动展开(卷起的包不能用)
        # 克隆后再试算,任何一步失败都不改动真实存档
        stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
        bag = Container.deserialize(sd.bag.w, sd.bag.h, sd.bag.serialize())
        pack = self._clone_item(sd.pack)
        gw, gh = pack_grid(new_pack.iid)
        new_bag, overflow = bag.resized(gw, gh)
        stash.remove_placed(stash.items[idx])
        for it in overflow:
            if not stash.add_item(it):
                return False, f"背包收窄到 {gw}×{gh},放不下的东西仓库也塞不下"
        if pack is not None and not stash.add_item(pack):
            return False, "仓库空间不足,无法换下旧背包"
        sd.bag, sd.stash, sd.pack = new_bag, stash, new_pack
        save_mod.save_data(sd)
        return True, f"已装备 {new_pack.name},携行 {gw}×{gh} 格"

    def _try_unequip_pack(self):
        """卸下背包,退回口袋容量。"""
        from inventory import Container
        from settings import POCKETS
        sd = self.game.save
        if sd.pack is None:
            return False, "当前没有装备背包(仅口袋携行)"
        stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
        bag = Container.deserialize(sd.bag.w, sd.bag.h, sd.bag.serialize())
        pack = self._clone_item(sd.pack)
        gw, gh = POCKETS
        new_bag, overflow = bag.resized(gw, gh)
        for it in overflow:
            if not stash.add_item(it):
                return False, f"背包里的东西放不进 {gw}×{gh} 口袋,先精简背包"
        if not stash.add_item(pack):
            return False, "仓库空间不足"
        sd.bag, sd.stash, sd.pack = new_bag, stash, None
        save_mod.save_data(sd)
        return True, f"已卸下 {pack.name},仅剩口袋 {gw}×{gh} 格"

    # ---------- 交易所 ----------
    def _trade_click(self, pos):
        sd = self.game.save
        audio.play("click")
        if self.trade_close.collidepoint(pos):
            self.view = "stash"
            save_mod.save_data(sd)
            return
        # 分区标签
        for i, (label, cat) in enumerate(TRADE_TABS):
            if self.trade_tab_rects[i].collidepoint(pos):
                self.trade_cat = cat
                self.trade_scroll = 0.0
                return
        # 出售:点击仓库物品(要算上滚轮偏移)
        placed = self.trade_stash_hit(pos)
        if placed is not None:
            price = trade_sell_price(placed.item)
            name = placed.item.name
            sd.stash.remove_placed(placed)
            sd.rubles += price
            save_mod.save_data(sd)
            self.say(f"出售 {name} +{fmt_rub(price)}", COL["good"])
            return
        # 购买:点击商品行(按分区过滤,支持滚轮偏移)
        goods, per, row_h = self.trade_rows()
        for i, (iid, count) in enumerate(goods):
            r = self.trade_row_rect(i, per, row_h)
            if not r.collidepoint(pos):
                continue
            # 超出可见区间的行不接受点击(避免点在看不见的商品上)
            if r.top < self.trade_view_top - row_h or r.bottom > self.trade_view_bottom:
                continue
            price = trade_buy_price(iid, count)
            if sd.rubles < price:
                self.say("余额不足!", COL["bad"])
                return
            d = ITEMS[iid]
            if d["cat"] == "weapon":
                item = Item.weapon(iid, mag=d["mag"])
            else:
                item = Item(iid, count=count)
            if not sd.stash.add_item(item):
                self.say("仓库空间不足!", COL["bad"])
                return
            sd.rubles -= price
            save_mod.save_data(sd)
            self.say(f"购买 {item.name} -{fmt_rub(price)}", COL["accent"])
            return

    # ---------- 渲染 ----------
    def draw(self, screen):
        if self.show_intro:
            intro.draw(screen, self.intro_page)
            return
        if self.view == "trade":
            self._draw_trade(screen)
            return
        if self.view == "task":
            self._draw_task(screen)
            return
        lay = self.lay
        sd = self.game.save
        screen.fill(COL["bg"])

        t = get_font(34, bold=True).render("藏身处 — TARKOV 2D", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))

        # ---- 仓库(格子变多了:只画看得见的一段,滚轮上下翻) ----
        uikit.draw_panel(screen, lay["stash_panel"],
                         "仓库 (点击物品放入出战配置 · 右键背包可卷起)")
        draw_grid(screen, self.stash_grid[0], self.stash_grid[1], sd.stash, 40,
                  scroll=self.stash_scroll, view_h=self.stash_view_h)
        if self.stash_max_scroll() > 0:
            t = get_font(13).render(
                f"滚轮上下翻(仓库共 {sd.stash.h} 行,面板显示 {STASH_VIEW_ROWS} 行)",
                True, COL["text_dim"])
            screen.blit(t, (self.stash_grid[0],
                            self.stash_grid[1] + self.stash_view_h + 8))

        # ---- 出战配置 ----
        uikit.draw_panel(screen, lay["loadout_panel"], "出战配置")
        mx, my = pygame.mouse.get_pos()
        draw_slot(screen, lay["weapon"], sd.weapon, "武器",
                  hover=lay["weapon"].collidepoint(mx, my))
        draw_slot(screen, lay["armor"], sd.armor, "护甲",
                  hover=lay["armor"].collidepoint(mx, my))
        draw_slot(screen, lay["pack"], sd.pack, "背包",
                  hover=lay["pack"].collidepoint(mx, my))
        bcell = self.bag_cell()
        brect = self.bag_rect()
        cap = "口袋" if sd.pack is None else sd.pack.name
        draw_grid(screen, brect.x, brect.y, sd.bag, bcell,
                  f"出战背包 {sd.bag.w}×{sd.bag.h}({cap})  点击放回仓库")

        # ---- 侧栏:地图 + 难度 + 统计 + 说明 ----
        uikit.draw_panel(screen, lay["side_panel"], "藏身处")
        st = sd.stats
        f = get_font(16)
        sp = lay["side_panel"]

        def draw_choice(rects, order, names, sel_key):
            for i, key in enumerate(order):
                sel = sel_key == key
                r = rects[i]
                base = COL["panel_hi"] if r.collidepoint(mx, my) else COL["panel"]
                pygame.draw.rect(screen, base, r, border_radius=8)
                pygame.draw.rect(screen, COL["accent"] if sel else COL["border"],
                                 r, 2 if sel else 1, border_radius=8)
                ft = get_font(14, bold=True).render(
                    names[key], True, COL["accent"] if sel else COL["text"])
                screen.blit(ft, ft.get_rect(center=r.center))

        t = get_font(17, bold=True).render("出战地图", True, COL["accent"])
        screen.blit(t, (sp.x + 18, sp.y + 38))
        draw_choice(self.map_rects, MAP_ORDER,
                    {k: MAPS[k].get("short", MAPS[k]["name"]) for k in MAP_ORDER},
                    sd.map_key)
        t = get_font(13).render(MAPS[sd.map_key]["desc"], True, COL["text_dim"])
        screen.blit(t, (sp.x + 18, sp.y + 132))

        t = get_font(17, bold=True).render("游戏模式", True, COL["accent"])
        screen.blit(t, (sp.x + 18, sp.y + 148))
        draw_choice(self.mode_rects, MODE_ORDER,
                    {k: MODES[k]["name"] for k in MODE_ORDER}, sd.mode)
        t = get_font(13).render(MODES[sd.mode]["desc"], True,
                                COL["good"] if sd.mode != "raid" else COL["text_dim"])
        screen.blit(t, (sp.x + 18, sp.y + 206))

        assault_run = sd.mode == "assault"
        t = get_font(17, bold=True).render("战局难度", True, COL["accent"])
        screen.blit(t, (sp.x + 18, sp.y + 224))
        fixed_lines = None
        if sd.mode == "assault":
            fixed_lines = ("突袭模式为固定强度(不适用难度档)",
                           "系统随机配发满配高级装备,战后回收")
        elif sd.mode in MODE_DIFF:
            fixed_lines = ("人质解救固定为强化封锁强度,",
                           "不适用简单/封锁难度档")
        if fixed_lines:
            for i, ln in enumerate(fixed_lines):
                t = get_font(13).render(ln, True, COL["text_dim"])
                screen.blit(t, (sp.x + 18, sp.y + 246 + i * 20))
        else:
            draw_choice(self.diff_rects, DIFF_ORDER,
                        {k: DIFFICULTIES[k]["name"] for k in DIFF_ORDER}, sd.difficulty)
            d = DIFFICULTIES[sd.difficulty]
            t = get_font(13).render(f"{d['desc']} · {d['loot_desc']}", True,
                                    COL["text_dim"])
            screen.blit(t, (sp.x + 18, sp.y + 282))

        y = sp.y + 302
        lines = [
            f"出击 {st['raids']} 次    撤离 {st['extracts']} 次",
            f"阵亡 {st['deaths']} 次    击杀 {st['kills']} 人",
            f"余额 {fmt_rub(sd.rubles)}    搜刮 {fmt_rub(st['value'])}",
            "",
            "WASD 移动 · 左键射击 · 右键架枪",
            "弹匣空自动换弹 · H 打药 · E 搜刮/救人",
            "TAB 背包 · 死亡会丢失带入的装备!",
        ]
        if assault_run:
            lines[-1] = "TAB 背包 · 1/2/3 呼叫友军支援"
        for ln in lines:
            col = COL["text_dim"] if ln == "" else COL["text"]
            t = f.render(ln, True, col)
            screen.blit(t, (sp.x + 18, y))
            y += 18

        # ---- 按钮 ----
        draw_button(screen, lay["intro_btn"], "玩法简介",
                    lay["intro_btn"].collidepoint(mx, my), small=True)
        draw_button(screen, lay["touch_btn"],
                    "手机模式:开" if sd.touch else "手机模式:关",
                    lay["touch_btn"].collidepoint(mx, my), small=True)
        draw_button(screen, lay["start"], f"开始战局 · {MODES[sd.mode]['name']}",
                    lay["start"].collidepoint(mx, my))
        draw_button(screen, lay["trade"], "交易所",
                    lay["trade"].collidepoint(mx, my), small=True)
        ready_n = sum(1 for t in TASKS
                      if quests.task_state(sd, t)[0] == "ready")
        draw_button(screen, lay["tasks"],
                    "任务中心" + (f"({ready_n})" if ready_n else ""),
                    lay["tasks"].collidepoint(mx, my), small=True)
        if not sd.any_weapon():
            draw_button(screen, lay["supply"], "领取基础补给",
                        lay["supply"].collidepoint(mx, my), small=True)
        reset_text = "确认清档?!" if self.reset_armed > 0 else "重置存档"
        draw_button(screen, lay["reset"], reset_text,
                    lay["reset"].collidepoint(mx, my), small=True)

        # ---- 提示行 ----
        if self.msg_t > 0 and self.msg:
            t = get_font(17, bold=True).render(self.msg, True, self.msg_col)
            screen.blit(t, t.get_rect(center=(W // 2, H - 26)))

        # ---- 悬浮提示 ----
        hover_item = None
        if lay["stash_panel"].collidepoint(mx, my):
            placed = self.stash_hit((mx, my))
            if placed:
                hover_item = placed.item
        brect = self.bag_rect()
        if hover_item is None and brect.collidepoint(mx, my):
            bcell = self.bag_cell()
            gx = int((mx - brect.x) // bcell)
            gy = int((my - brect.y) // bcell)
            placed = sd.bag.at(gx, gy)
            if placed:
                hover_item = placed.item
        if hover_item is None and lay["weapon"].collidepoint(mx, my) and sd.weapon:
            hover_item = sd.weapon
        if hover_item is None and lay["armor"].collidepoint(mx, my) and sd.armor:
            hover_item = sd.armor
        if hover_item is None and lay["pack"].collidepoint(mx, my) and sd.pack:
            hover_item = sd.pack
        if hover_item is not None:
            draw_tooltip(screen, mx, my, hover_item)

    # ---------- 任务中心渲染 ----------
    def _draw_task(self, screen):
        sd = self.game.save
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])
        t = get_font(34, bold=True).render("任务中心", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))
        bal = get_font(24, bold=True).render(f"余额 {fmt_rub(sd.rubles)}", True,
                                             COL["accent"])
        screen.blit(bal, (W - bal.get_width() - 30, 36))

        uikit.draw_panel(screen, self.lay["trade_goods"],
                         "部门 — 教官发任务,医疗/后勤用局内材料换东西")
        # 部门标签
        for i, (key, label) in enumerate(DEPTS):
            r = self.task_tab_rects[i]
            sel = self.task_dept == key
            base = COL["panel_hi"] if r.collidepoint(mx, my) else COL["panel"]
            pygame.draw.rect(screen, base, r, border_radius=7)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"],
                             r, 2 if sel else 1, border_radius=7)
            if key == "instructor":
                ready = sum(1 for tk in TASKS
                            if quests.task_state(sd, tk)[0] == "ready")
                label = f"{label}(可领 {ready})" if ready else label
            ft = get_font(16, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        hint = ("左键:领取奖励" if self.task_dept == "instructor"
                else "左键:交货换东西(材料从仓库+背包里扣)")
        if self.task_max_scroll() > 0:
            hint += " · 滚轮翻页"
        t = get_font(13).render(hint, True, COL["text_dim"])
        screen.blit(t, (556, 168))

        entries, per = self.task_rows()
        fn = get_font(16, bold=True)
        fc = get_font(14)
        for i, entry in enumerate(entries):
            rect = self.task_row_rect(i)
            if rect.bottom < self.task_view_top or rect.top > self.task_view_bottom:
                continue
            if self.task_dept == "instructor":
                task, (state, p, need) = entry
                done = state == "done"
                ready = state == "ready"
                name = f"{task['name']}  ({min(p, need)}/{need})"
                if task.get("repeat"):
                    name += "  [可重复]"
                right = ("已结算" if done else
                         ("点击领取" if ready else "进行中"))
                sub = f"{task['desc']}   奖励:{quests.reward_text(task['reward'])}"
                col = (COL["good"] if ready else
                       (COL["text_dim"] if done else COL["text"]))
            else:
                barter = entry[0]
                miss = quests.missing_materials(sd, barter)
                ready = not miss
                name = barter["name"]
                right = "点击交货" if ready else "材料不足"
                sub = (f"需要:{quests.need_text(barter)}   得到:{quests.out_text(barter)}"
                       + ("" if ready else "   缺:" + "、".join(
                           f"{ITEMS[iid]['name']}×{n}" for iid, n in miss)))
                col = COL["good"] if ready else COL["text"]
            hover = rect.collidepoint(mx, my)
            pygame.draw.rect(screen, COL["panel_hi"] if hover else COL["panel"],
                             rect, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if hover else COL["border"],
                             rect, 2 if hover else 1, border_radius=6)
            screen.blit(fn.render(name, True, col), (rect.x + 12, rect.y + 6))
            screen.blit(fc.render(sub, True, COL["text_dim"]), (rect.x + 12, rect.y + 28))
            rt = fn.render(right, True, COL["accent"] if ready else COL["text_dim"])
            screen.blit(rt, (rect.right - rt.get_width() - 14, rect.y + 14))

        t = get_font(14).render("任务进度在你打战局时自动累计(击杀/撤离/价值/人质/突袭)",
                                True, COL["text_dim"])
        screen.blit(t, (530, self.task_view_bottom + 10))
        draw_button(screen, self.task_close, "返回",
                    self.task_close.collidepoint(mx, my), small=True)

    # ---------- 交易所渲染 ----------
    def _draw_trade(self, screen):
        sd = self.game.save
        lay = self.lay
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])

        t = get_font(34, bold=True).render("交易所", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))
        bal = get_font(24, bold=True).render(f"余额 {fmt_rub(sd.rubles)}", True, COL["accent"])
        screen.blit(bal, (W - bal.get_width() - 30, 36))

        # ---- 左:仓库(点击出售;格子多了用滚轮翻) ----
        uikit.draw_panel(screen, lay["trade_stash"], "你的仓库 — 点击物品出售")
        gx0, gy0 = self.trade_stash_grid
        draw_grid(screen, gx0, gy0, sd.stash, 40,
                  scroll=self.stash_scroll, view_h=self.trade_stash_view_h)
        t = get_font(14).render(
            "出售价 = 原价 60%,卖错了只能高价买回"
            + ("(滚轮翻仓库)" if self.trade_stash_max_scroll() > 0 else ""),
            True, COL["text_dim"])
        screen.blit(t, (gx0, gy0 + self.trade_stash_view_h + 12))

        # ---- 右:商品(分区 + 滚轮翻看) ----
        uikit.draw_panel(screen, lay["trade_goods"], "商品 — 点击购买")
        # 分区标签
        for i, (label, cat) in enumerate(TRADE_TABS):
            r = self.trade_tab_rects[i]
            sel = self.trade_cat == cat
            base = COL["panel_hi"] if r.collidepoint(mx, my) else COL["panel"]
            pygame.draw.rect(screen, base, r, border_radius=7)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"],
                             r, 2 if sel else 1, border_radius=7)
            ft = get_font(15, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        goods, per, row_h = self.trade_rows()
        t = get_font(13).render("左键购买 · 滚轮翻看更多" if self.trade_max_scroll() > 0
                                else "左键购买", True, COL["text_dim"])
        screen.blit(t, (556, 166))
        # 商品行(超出可见区间的裁剪掉)
        f16 = get_font(15, bold=True)
        view = pygame.Rect(530, self.trade_view_top - row_h, 720,
                           TRADE_PAGE_H + row_h * 2)
        for i, (iid, count) in enumerate(goods):
            d = ITEMS[iid]
            price = trade_buy_price(iid, count)
            rect = self.trade_row_rect(i, per, row_h)
            if not view.colliderect(rect):
                continue
            afford = sd.rubles >= price
            visible = (rect.top >= self.trade_view_top - row_h
                       and rect.bottom <= self.trade_view_bottom)
            hover = rect.collidepoint(mx, my) and visible
            base = COL["panel_hi"] if hover and afford else COL["panel"]
            pygame.draw.rect(screen, base, rect, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if (hover and afford) else COL["border"],
                              rect, 2 if (hover and afford) else 1, border_radius=6)
            # 类别色块
            pygame.draw.rect(screen, d["color"], (rect.x + 6, rect.y + 6, 7, 24),
                             border_radius=2)
            name = d["name"] + (f" ×{count}" if d["cat"] == "ammo" else "")
            t = f16.render(name, True, COL["text"] if afford else (110, 110, 116))
            screen.blit(t, (rect.x + 20, rect.y + 7))
            tp = get_font(15, bold=True).render(fmt_rub(price), True,
                                                COL["accent"] if afford else COL["text_dim"])
            screen.blit(tp, (rect.right - tp.get_width() - 10, rect.y + 7))
        # 滚动条
        ms = self.trade_max_scroll()
        if ms > 0:
            bar_x = lay["trade_goods"].right - 14
            track = pygame.Rect(bar_x, self.trade_view_top, 6, TRADE_PAGE_H)
            pygame.draw.rect(screen, COL["grid_bg"], track, border_radius=3)
            ratio = TRADE_PAGE_H / (TRADE_PAGE_H + ms)
            h = max(24, int(TRADE_PAGE_H * ratio))
            pos = int((self.trade_scroll / ms) * (TRADE_PAGE_H - h))
            pygame.draw.rect(screen, COL["accent"],
                             (bar_x, self.trade_view_top + pos, 6, h), border_radius=3)
        t = get_font(14).render("买满弹药再进战局;搜刮到的贵重物拿回来卖钱",
                                True, COL["text_dim"])
        screen.blit(t, (556, lay["trade_goods"].bottom - 34))

        # 关闭按钮
        draw_button(screen, self.trade_close, "返回",
                    self.trade_close.collidepoint(mx, my), small=True)

        # ---- 提示行 ----
        if self.msg_t > 0 and self.msg:
            t = get_font(17, bold=True).render(self.msg, True, self.msg_col)
            screen.blit(t, t.get_rect(center=(W // 2, H - 26)))

        # ---- 悬浮提示 ----
        hover_item = None
        if lay["trade_stash"].collidepoint(mx, my):
            gx = int((mx - gx0) // 40)
            gy = int((my - gy0) // 40)
            placed = sd.stash.at(gx, gy)
            if placed:
                hover_item = placed.item
        if hover_item is not None:
            draw_tooltip(screen, mx, my, hover_item)
        else:
            goods, per, row_h = self.trade_rows()
            for i, (iid, count) in enumerate(goods):
                r = self.trade_row_rect(i, per, row_h)
                visible = (r.top >= self.trade_view_top - row_h
                           and r.bottom <= self.trade_view_bottom)
                if visible and r.collidepoint(mx, my):
                    d = ITEMS[iid]
                    if d["cat"] == "weapon":
                        preview = Item.weapon(iid, mag=d["mag"])
                    else:
                        preview = Item(iid, count=count)
                    draw_tooltip(screen, mx, my, preview)
                    break
