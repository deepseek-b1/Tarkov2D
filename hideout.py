# -*- coding: utf-8 -*-
"""藏身处:仓库管理、出战整备、开局。"""
import math
import time

import pygame

import audio
import bindings
import intro
import quests
import save as save_mod
import touch as touch_mod
from settings import (W, H, COL, fmt_rub, get_font, DIFF_ORDER, DIFFICULTIES,
                      weapon_slots, weapon_attach, weapon_capacity, ATTACH_SLOTS,
                      ITEMS, TRADE_GOODS, TRADE_TABS, TRADE_PAGE_H, FPS_CAP_CHOICES,
                      trade_buy_price, trade_sell_price, STASH_VIEW_ROWS,
                      MODE_DIFF, DEPTS, TASKS,
                      armor_allows, MAPS, MAP_ORDER, MODES, MODE_ORDER, MODE_MAP,
                      weapon_class, WEAPON_CLASS_COL)
from inventory import Item, Placed, organize, try_move
import uikit
from uikit import draw_grid, draw_button, draw_slot, draw_tooltip


def _layout():
    return dict(
        stash_panel=pygame.Rect(30, 100, 470, 430),
        loadout_panel=pygame.Rect(516, 100, 390, 430),
        side_panel=pygame.Rect(922, 100, 330, 438),
        weapon=pygame.Rect(542, 146, 86, 84),
        armor=pygame.Rect(634, 146, 86, 84),
        helmet=pygame.Rect(726, 146, 86, 84),
        pack=pygame.Rect(818, 146, 86, 84),
        bag_origin=(542, 262),      # 出战背包网格原点(cell 动态)
        intro_btn=pygame.Rect(542, 484, 170, 34),
        touch_btn=pygame.Rect(722, 484, 160, 34),
        start=pygame.Rect(542, 548, 340, 54),
        supply=pygame.Rect(30, 548, 220, 46),
        reset=pygame.Rect(262, 548, 220, 46),
        trade=pygame.Rect(930, 548, 72, 46),
        tasks=pygame.Rect(1008, 548, 72, 46),
        story=pygame.Rect(1086, 548, 72, 46),
        options=pygame.Rect(1164, 548, 72, 46),
        organize=pygame.Rect(374, 106, 116, 24),      # 仓库:一键整理
        stash_all=pygame.Rect(712, 106, 184, 24),     # 出战配置:放回仓库并整理
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
        self.mode_rects = [pygame.Rect(sp.x + 18 + i * 58, sp.y + 172, 55, 30)
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
        self.trade_stash_view_h = 9 * 40      # 交易所左侧仓库可见高度(其余滚轮翻)
        self.trade_cat = None            # 当前分区(None = 全部)
        self.trade_scroll = 0.0          # 滚轮偏移(像素)
        self.trade_tab_rects = [
            pygame.Rect(548 + i * 86, 132, 80, 30) for i in range(len(TRADE_TABS))]
        self.trade_view_top = 178        # 商品区可见范围
        self.trade_view_bottom = 178 + TRADE_PAGE_H
        self.trade_close = pygame.Rect(1140, 76, 100, 36)
        self.trade_drag = False          # 正在拖商品列表的滚动条
        self.trade_slider = None         # 本帧的 (轨道, 手柄),画的时候填
        # 批量出售:开关 / 快捷选择 / 出售 / 清空 + 确认框
        self.sell_mode = False
        self.sell_sel = []                    # 选中的 Placed(按点击顺序)
        self.sell_ask = None                  # 待确认:{items, total}
        self.sell_toggle = pygame.Rect(66, 540, 176, 30)
        self.sell_junk = pygame.Rect(252, 540, 108, 30)
        self.sell_ammo = pygame.Rect(368, 540, 108, 30)
        self.sell_go = pygame.Rect(66, 578, 410, 34)
        self.sell_clear = pygame.Rect(66, 618, 410, 26)
        self.sell_ask_panel = pygame.Rect(W // 2 - 290, H // 2 - 130, 580, 260)
        self.sell_ask_yes = pygame.Rect(self.sell_ask_panel.x + 50,
                                        self.sell_ask_panel.bottom - 84, 220, 48)
        self.sell_ask_no = pygame.Rect(self.sell_ask_panel.right - 270,
                                       self.sell_ask_panel.bottom - 84, 220, 48)
        # 玩法简介(首次启动自动弹出)
        self.show_intro = not getattr(self.game.save, "seen_intro", False)
        self.intro_page = 0
        # ---- 设置视图(控制 / 触屏 / 画质) ----
        self.opt_tab = "controls"
        self.opt_tab_keys = ["controls", "touch", "video"]
        self.opt_tab_rects = [pygame.Rect(548 + i * 214, 132, 200, 32)
                              for i in range(3)]
        self.opt_close = pygame.Rect(1140, 76, 100, 36)
        self.opt_rebind = None      # 正在等待新按键的动作名(None = 不在改键)
        self.opt_sel = None         # 触屏布局:选中的按钮名
        self.opt_drag = None        # 触屏布局:正在拖动的按钮名
        self.opt_layout = {}        # 触屏布局工作副本:{name: dict(rx,ry,r,label)}
        self.opt_bind_rects = [pygame.Rect(852, 184 + i * 28, 240, 26)
                               for i in range(len(bindings.ACTIONS))]
        self.opt_fps_rects = [pygame.Rect(772 + i * 108, 214, 98, 34)
                              for i in range(len(FPS_CAP_CHOICES))]
        self.opt_fps_toggle = pygame.Rect(772, 274, 98, 34)
        self.opt_filter_rects = [pygame.Rect(772 + i * 134, 334, 124, 34)
                                 for i in range(2)]
        self.opt_minus = pygame.Rect(1000, 552, 44, 30)
        self.opt_plus = pygame.Rect(1052, 552, 44, 30)
        self.opt_save = pygame.Rect(548, 616, 200, 40)
        self.opt_defaults = pygame.Rect(770, 616, 200, 40)
        # 触屏模式的翻页按钮(手机没有滚轮)
        self.scroll_btns = {}
        self.rscroll_btns = {}

    # ---- 设置:触屏布局编辑工作副本 ----
    def _opt_layout_base(self):
        base = {}
        for name, label, (rx, ry), r in touch_mod.BUTTONS + touch_mod.SUPPORT_BUTTONS:
            base[name] = dict(label=label, rx=float(rx), ry=float(ry), r=int(r))
        return base

    def _opt_layout_load(self):
        """进入触屏页:默认布局 + 存档覆盖。"""
        sd = self.game.save
        self.opt_layout = self._opt_layout_base()
        saved = getattr(sd, "touch_layout", None) or {}
        for name, v in saved.items():
            if name in self.opt_layout:
                try:
                    rx, ry, r = float(v[0]), float(v[1]), int(v[2])
                except (TypeError, ValueError, IndexError):
                    continue
                self.opt_layout[name].update(rx=rx, ry=ry, r=r)
        self.opt_sel = None
        self.opt_drag = None

    def _opt_layout_to_save(self):
        """工作副本 -> 存档覆盖(只存与默认不同的项)。"""
        base = self._opt_layout_base()
        out = {}
        for name, d in self.opt_layout.items():
            b = base[name]
            if (abs(d["rx"] - b["rx"]) > 1e-6 or abs(d["ry"] - b["ry"]) > 1e-6
                    or d["r"] != b["r"]):
                out[name] = [round(d["rx"], 4), round(d["ry"], 4), int(d["r"])]
        return out

    def _opt_apply_save(self, note=None):
        """保存并应用(触屏布局同步给 touch 模块;键位/画质本来就是即时生效)。"""
        sd = self.game.save
        if self.opt_tab == "touch":
            sd.touch_layout = self._opt_layout_to_save()
            touch_mod.apply_layout(sd.touch_layout)
        save_mod.save_data(sd)
        audio.play("pickup")
        self.say(note or "设置已保存并应用", COL["good"], 3.0)

    def _opt_restore_defaults(self):
        sd = self.game.save
        if self.opt_tab == "controls":
            bindings.reset_all(sd)
            save_mod.save_data(sd)
            self.say("键位已恢复默认(点「保存并应用」写盘)", COL["accent"], 3.0)
        elif self.opt_tab == "touch":
            sd.touch_layout = {}
            touch_mod.apply_layout({})
            self._opt_layout_load()
            save_mod.save_data(sd)
            self.say("触屏按键位置已恢复默认", COL["accent"], 3.0)
        else:
            sd.fps_cap = 120
            sd.show_fps = True
            sd.scale_filter = "linear"
            save_mod.save_data(sd)
            self.say("画质设置已恢复默认(默认 120 帧上限 · 显示帧率 · 柔和)",
                     COL["accent"], 3.2)

    def _options_update(self, dt, events):
        """设置页事件:改键捕获 / 触屏拖拽 / 点击。"""
        sd = self.game.save
        for ev in events:
            if ev.type == pygame.KEYDOWN:
                if self.opt_rebind is not None:
                    act = self.opt_rebind
                    if ev.key == pygame.K_ESCAPE:
                        self.opt_rebind = None
                        self.say("已取消改键", COL["text_dim"], 2.0)
                        continue
                    ok, conflicts = bindings.assign(sd, act, ev.key)
                    if ok:
                        self.opt_rebind = None
                        self.say(f"{bindings.action_label(act)} → "
                                 f"{bindings.key_label(ev.key)}(点「保存并应用」写盘)",
                                 COL["good"], 3.2)
                    else:
                        names = "、".join(bindings.action_label(a) for a in conflicts)
                        self.say(f"「{bindings.key_label(ev.key)}」已被 {names} 占用,"
                                 f"换一个键(ESC 取消)", COL["bad"], 3.4)
                    continue
                if ev.key == pygame.K_ESCAPE:
                    self.opt_rebind = None
                    self.opt_drag = None
                    self.view = "stash"
                    save_mod.save_data(sd)
                    audio.play("click")
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                self._options_click(ev.pos)
            elif ev.type == pygame.MOUSEMOTION and self.opt_drag is not None:
                self._options_drag_to(ev.pos)
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                self.opt_drag = None

    def _options_drag_to(self, pos):
        """触屏布局:把正在拖动的按钮挪到手指/鼠标位置(比例坐标,边界留 3%)。"""
        name = self.opt_drag
        d = self.opt_layout.get(name)
        if d is None:
            return
        d["rx"] = min(0.97, max(0.03, pos[0] / float(W)))
        d["ry"] = min(0.97, max(0.03, pos[1] / float(H)))

    def _options_click(self, pos):
        sd = self.game.save
        mx, my = pos
        audio.play("click")
        if self.opt_rebind is not None:
            # 改键等待中:点别处 = 取消
            self.opt_rebind = None
            return
        if self.opt_close.collidepoint(pos) or not self._options_panel().collidepoint(pos):
            self.view = "stash"
            save_mod.save_data(sd)
            return
        for i, key in enumerate(self.opt_tab_keys):
            if self.opt_tab_rects[i].collidepoint(pos):
                self.opt_tab = key
                if key == "touch":
                    self._opt_layout_load()
                return
        if self.opt_save.collidepoint(pos):
            self._opt_apply_save()
            return
        if self.opt_defaults.collidepoint(pos):
            self._opt_restore_defaults()
            return
        if self.opt_tab == "controls":
            for i, (act, _name) in enumerate(bindings.ACTIONS):
                if self.opt_bind_rects[i].collidepoint(pos):
                    self.opt_rebind = act
                    self.say(f"按下要给「{bindings.action_label(act)}」绑定的新键"
                             f"(ESC 取消)", COL["accent"], 4.0)
                    return
            return
        if self.opt_tab == "touch":
            if self.opt_sel is not None:
                if self.opt_minus.collidepoint(pos):
                    d = self.opt_layout[self.opt_sel]
                    d["r"] = max(20, d["r"] - 6)
                    return
                if self.opt_plus.collidepoint(pos):
                    d = self.opt_layout[self.opt_sel]
                    d["r"] = min(110, d["r"] + 6)
                    return
            hit = None
            for name, d in self.opt_layout.items():
                px, py = d["rx"] * W, d["ry"] * H
                if math.hypot(pos[0] - px, pos[1] - py) <= max(22, d["r"]):
                    hit = name
                    break
            if hit is not None:
                self.opt_sel = hit
                self.opt_drag = hit
                return
            self.opt_sel = None
            return
        if self.opt_tab == "video":
            from settings import FPS_CAP_CHOICES as CHOICES
            for i, cap in enumerate(CHOICES):
                if self.opt_fps_rects[i].collidepoint(pos):
                    sd.fps_cap = int(cap)
                    save_mod.save_data(sd)
                    self.say("帧率上限已设为 "
                             + ("不锁(能跑多快跑多快)" if cap == 0 else f"{cap} 帧"),
                             COL["good"], 2.6)
                    return
            if self.opt_fps_toggle.collidepoint(pos):
                sd.show_fps = not sd.show_fps
                save_mod.save_data(sd)
                self.say("帧率显示已" + ("开启" if sd.show_fps else "关闭"),
                         COL["good"], 2.4)
                return
            for i, key in enumerate(("linear", "nearest")):
                if self.opt_filter_rects[i].collidepoint(pos):
                    if sd.scale_filter != key:
                        sd.scale_filter = key
                        save_mod.save_data(sd)
                        self.say("画面缩放滤镜已改为「"
                                 + ("柔和(双线性)" if key == "linear" else "锐利(最近邻)")
                                 + "」,重启游戏后生效", COL["accent"], 3.6)
                    return

    def _options_panel(self):
        return pygame.Rect(530, 100, 720, 570)

    # ---- 设置页渲染 ----
    def _draw_options(self, screen):
        """设置页:控制 / 触屏 / 画质 三个标签页 + 保存并应用 / 恢复默认。"""
        lay = self.lay
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])
        uikit.draw_panel(screen, self._options_panel(), "设置")
        draw_button(screen, self.opt_close, "返回",
                    self.opt_close.collidepoint(mx, my), small=True)
        t = get_font(30, bold=True).render("设置 — 键位 / 触屏 / 画质", True,
                                           COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))

        labels = {"controls": "控制(键盘)", "touch": "触屏按键", "video": "画质与帧率"}
        for i, key in enumerate(self.opt_tab_keys):
            r = self.opt_tab_rects[i]
            sel = self.opt_tab == key
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen,
                             COL["panel_hi"] if (hover or sel) else COL["panel"],
                             r, border_radius=8)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"], r,
                             2 if sel else 1, border_radius=8)
            ft = get_font(16, bold=True).render(
                labels[key], True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))

        if self.opt_tab == "controls":
            self._draw_options_controls(screen, mx, my)
        elif self.opt_tab == "touch":
            self._draw_options_touch(screen, mx, my)
        else:
            self._draw_options_video(screen, mx, my)

        draw_button(screen, self.opt_save, "保存并应用",
                    self.opt_save.collidepoint(mx, my))
        dtext = {"controls": "恢复默认键位", "touch": "恢复默认布局",
                 "video": "恢复默认画质"}[self.opt_tab]
        draw_button(screen, self.opt_defaults, dtext,
                    self.opt_defaults.collidepoint(mx, my), small=True)
        if self.opt_rebind is not None:
            t = get_font(17, bold=True).render("请按下新按键…(ESC 取消)", True,
                                               COL["accent"])
            screen.blit(t, t.get_rect(center=(W // 2, 588)))
        elif self.msg_t > 0 and self.msg:
            t = get_font(15, bold=True).render(self.msg, True, self.msg_col)
            screen.blit(t, t.get_rect(center=(W // 2, 588)))

    def _draw_options_controls(self, screen, mx, my):
        """控制页:每个动作一行,右边是当前的键(点它改键)。"""
        sd = self.game.save
        f = get_font(16)
        fk = get_font(16, bold=True)
        for i, (act, name) in enumerate(bindings.ACTIONS):
            r = self.opt_bind_rects[i]
            t = f.render(name, True, COL["text"])
            screen.blit(t, (548, r.y + 3))
            waiting = self.opt_rebind == act
            modified = bindings.is_modified(sd, act)
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen,
                             COL["panel_hi"] if (hover or waiting) else COL["panel"],
                             r, border_radius=6)
            pygame.draw.rect(screen,
                             COL["accent"] if (waiting or modified) else COL["border"],
                             r, 2 if waiting else 1, border_radius=6)
            label = "按新按键…" if waiting else bindings.label_for(sd, act)
            ft = fk.render(label, True,
                           COL["accent"] if (waiting or modified) else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        tip = get_font(13).render(bindings.FIXED_NOTES, True, COL["text_dim"])
        screen.blit(tip, (548, 560))
        tip2 = get_font(13).render("橙色 = 已改过(可再点改;冲突时会被拒绝)",
                                   True, COL["text_dim"])
        screen.blit(tip2, (548, 578))

    def _draw_options_touch(self, screen, mx, my):
        """触屏页:所见即所得预览 + 拖动 + 选中后 +/- 调大小。"""
        if not self.opt_layout:
            self._opt_layout_load()
        tip = get_font(15).render(
            "拖动按钮改位置 · 选中后用 − / + 改大小 · 左半屏摇杆区固定不可移",
            True, COL["text_dim"])
        screen.blit(tip, (548, 176))
        frame = pygame.Rect(560, 206, 660, 340)
        pygame.draw.rect(screen, (16, 18, 22), frame, border_radius=8)
        pygame.draw.rect(screen, COL["border"], frame, 1, border_radius=8)
        sx = frame.x + frame.w * 0.22
        sy = frame.bottom - 78
        pygame.draw.circle(screen, (48, 52, 62), (int(sx), int(sy)), 44, 2)
        tt = get_font(12).render("摇杆区(固定)", True, (110, 118, 132))
        screen.blit(tt, tt.get_rect(center=(int(sx), int(sy) + 58)))
        for name, d in self.opt_layout.items():
            px = frame.x + d["rx"] * frame.w
            py = frame.y + d["ry"] * frame.h
            r = max(10, int(d["r"] * frame.h / float(H)))
            sel = name == self.opt_sel
            pygame.draw.circle(screen, (72, 92, 120) if sel else (40, 46, 58),
                               (int(px), int(py)), r)
            pygame.draw.circle(screen, COL["accent"] if sel else (96, 104, 118),
                               (int(px), int(py)), r, 3 if sel else 2)
            ft = get_font(12, bold=True).render(d["label"], True, COL["text"])
            screen.blit(ft, ft.get_rect(center=(int(px), int(py))))
        if self.opt_sel is not None:
            d = self.opt_layout[self.opt_sel]
            info = get_font(15, bold=True).render(
                f"已选中「{d['label']}」 · 直径 {d['r']}px", True, COL["accent"])
            screen.blit(info, (548, 556))
            draw_button(screen, self.opt_minus, "−",
                        self.opt_minus.collidepoint(mx, my), small=True)
            draw_button(screen, self.opt_plus, "+",
                        self.opt_plus.collidepoint(mx, my), small=True)
        else:
            t = get_font(15).render("点一个按钮选中它", True, COL["text_dim"])
            screen.blit(t, (548, 560))

    def _draw_options_video(self, screen, mx, my):
        """画质页:帧率上限 / 显示帧率 / 缩放滤镜。"""
        from settings import FPS_CAP_CHOICES
        sd = self.game.save
        f = get_font(17, bold=True)
        for name, y in (("帧率上限", 214), ("显示帧率", 274), ("画面缩放滤镜", 334)):
            t = f.render(name, True, COL["text"])
            screen.blit(t, (548, y + 6))
        for i, cap in enumerate(FPS_CAP_CHOICES):
            r = self.opt_fps_rects[i]
            sel = int(sd.fps_cap) == int(cap)
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen,
                             COL["panel_hi"] if (sel or hover) else COL["panel"],
                             r, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"], r,
                             2 if sel else 1, border_radius=6)
            label = "不锁" if cap == 0 else f"{cap}"
            ft = get_font(15, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        r = self.opt_fps_toggle
        sel = bool(sd.show_fps)
        hover = r.collidepoint(mx, my)
        pygame.draw.rect(screen,
                         COL["panel_hi"] if (sel or hover) else COL["panel"],
                         r, border_radius=6)
        pygame.draw.rect(screen, COL["accent"] if sel else COL["border"], r,
                         2 if sel else 1, border_radius=6)
        ft = get_font(15, bold=True).render("开" if sel else "关", True,
                                            COL["accent"] if sel else COL["text"])
        screen.blit(ft, ft.get_rect(center=r.center))
        for i, (label, key) in enumerate((("柔和(线性)", "linear"),
                                          ("锐利(最近邻)", "nearest"))):
            r = self.opt_filter_rects[i]
            sel = sd.scale_filter == key
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen,
                             COL["panel_hi"] if (sel or hover) else COL["panel"],
                             r, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"], r,
                             2 if sel else 1, border_radius=6)
            ft = get_font(15, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        lines = [
            "· 帧率上限:高刷屏建议 120 或不锁;发热/掉电快就退回 60",
            "· 显示帧率:右上角实时 FPS(绿 ≥110 · 黄 ≥55 · 红更低)",
            "· 画面缩放滤镜 = 720p 画面拉到全屏时的采样方式(重启后生效)",
            "   柔和=平滑;锐利=最近邻(边缘更硬,可能有锯齿)",
            "· 手机屏幕分辨率高于 720p,任何滤镜都做不到像素级清晰;",
            "   真正清晰要按原生分辨率重做界面(后续大工程,暂不做)",
        ]
        y = 392
        for ln in lines:
            t = get_font(14).render(ln, True, COL["text_dim"])
            screen.blit(t, (548, y))
            y += 24

    # ---- 批量出售 ----
    def sell_selected(self):
        """当前仍有效的选中项(物品被卖掉/整理后就自动剔除)。"""
        sd = self.game.save
        self.sell_sel = [p for p in self.sell_sel if p in sd.stash.items]
        return self.sell_sel

    def sell_total(self):
        return sum(trade_sell_price(p.item) for p in self.sell_selected())

    def _sell_pick(self, cats):
        """快捷选择:把仓库里这些类别的物品全部选中(再次点击则取消这些)。"""
        sd = self.game.save
        sel = self.sell_selected()
        targets = [p for p in sd.stash.items if p.item.cat in cats]
        if targets and all(p in sel for p in targets):
            self.sell_sel = [p for p in sel if p not in targets]   # 再点一次 = 取消
        else:
            for p in targets:
                if p not in sel:
                    sel.append(p)
            self.sell_sel = sel
        return len(targets)

    def _sell_do(self):
        """确认出售:把选中的东西一次性卖掉。"""
        sd = self.game.save
        items = [p for p in (self.sell_ask or {}).get("items", [])
                 if p in sd.stash.items]
        total = sum(trade_sell_price(p.item) for p in items)
        n = 0
        for p in items:
            sd.stash.remove_placed(p)
            n += 1
        self.sell_ask = None
        self.sell_sel = []
        if n == 0:
            return False, "物品已变化,没有可卖的东西"
        sd.rubles += total
        save_mod.save_data(sd)
        return True, f"批量出售 {n} 件 +{fmt_rub(total)}"

    def _draw_sell_ask(self, screen):
        """批量出售确认框。"""
        dark = pygame.Surface((W, H), pygame.SRCALPHA)
        dark.fill((0, 0, 0, 130))
        screen.blit(dark, (0, 0))
        panel = self.sell_ask_panel
        uikit.draw_panel(screen, panel, "批量出售")
        ask = self.sell_ask or {}
        n = len(ask.get("items", []))
        f = get_font(17)
        lines = [f"确定卖掉选中的 {n} 件物品?",
                 f"合计可得 {fmt_rub(ask.get('total', 0))}"
                 f"(回收价 = 原价 60%,卖错了只能高价买回)"]
        y = panel.y + 58
        for ln in lines:
            t = f.render(ln, True, COL["text"])
            screen.blit(t, (panel.x + 34, y))
            y += 32
        names = "、".join(p.item.name for p in ask.get("items", [])[:6])
        if n > 6:
            names += f" 等 {n} 件"
        t = get_font(14).render(names, True, COL["text_dim"])
        screen.blit(t, (panel.x + 34, y + 6))
        mx, my = pygame.mouse.get_pos()
        draw_button(screen, self.sell_ask_yes, "出售",
                    self.sell_ask_yes.collidepoint(mx, my))
        draw_button(screen, self.sell_ask_no, "取消",
                    self.sell_ask_no.collidepoint(mx, my))

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
        # 右列窄一点,给右边的滚动条让位(否则点商品会误触滑块)
        return pygame.Rect(548 + col * 346,
                           self.trade_view_top + row * (row_h + 4) - int(self.trade_scroll),
                           338, row_h)

    def trade_max_scroll(self):
        goods, per, row_h = self.trade_rows()
        rows = (len(goods) + 1) // 2
        content_bottom = self.trade_view_top + rows * (row_h + 4)
        return max(0.0, float(content_bottom - self.trade_view_bottom))

    # ---- 交易所滚动条(可拖动) ----
    def trade_slider_track(self):
        return pygame.Rect(self.lay["trade_goods"].right - 18,
                           self.trade_view_top, 14, TRADE_PAGE_H)

    def _trade_drag_to(self, y):
        """把手柄拖到某个 y:换算成滚动位置。"""
        if not self.trade_slider:
            return
        track, handle = self.trade_slider
        ms = self.trade_max_scroll()
        span = track.h - handle.h
        if span <= 0 or ms <= 0:
            return
        ratio = (y - track.y - handle.h / 2.0) / span
        self.trade_scroll = max(0.0, min(ms, ratio * ms))

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

    # ---- 一键整理 / 一键放回仓库 ----
    def organize_stash(self):
        """一键整理仓库:合并同类堆叠、卷起背包、按类别分区分区摆放。"""
        sd = self.game.save
        before = len(sd.stash.items)
        ok, overflow = organize(sd.stash)
        if not ok:
            names = "、".join(it.name for it in overflow[:3])
            return False, f"整理后放不下({names} 等),先卖掉或用掉一些东西"
        save_mod.save_data(sd)
        audio.play("click")
        return True, (f"仓库已整理:{before} 件 → {len(sd.stash.items)} 件"
                      "(子弹并组 · 背包卷起 · 枪/甲/子弹各归一片)")

    def stash_all_and_organize(self):
        """把出战背包 + 武器/护甲/背包全部放回仓库并整理。

        全程先在克隆仓库上试算:只要有一件放不下,就【什么都不动】并提示,
        避免出现"武器卸了、背包还在"这种做一半的状态。
        """
        from inventory import Container
        sd = self.game.save
        stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
        carry = list(sd.bag.items)
        slots = []
        for name in ("weapon", "armor", "helmet", "pack"):
            it = getattr(sd, name)
            if it is None:
                continue
            clone = self._clone_item(it)
            if clone.state.get("rolled"):
                clone.state.pop("rolled", None)      # 放回仓库时按展开尺寸算空间
            slots.append((name, clone))
        blocked = []
        for placed in carry:
            if not stash.add_item(placed.item):
                blocked.append(placed.item.name)
        for _name, clone in slots:
            if not stash.add_item(clone):
                blocked.append(clone.name)
        if blocked:
            return False, ("仓库放不下:" + "、".join(blocked[:3])
                           + " —— 什么都没动,先卖掉或用掉一些再试")
        ok, overflow = organize(stash)
        if not ok:
            names = "、".join(it.name for it in overflow[:3])
            return False, f"整理后放不下({names} 等),什么都没动,先清点空间"
        # 全部试算通过:正式落盘
        for placed in carry:
            sd.bag.remove_placed(placed)
        for name, _clone in slots:
            setattr(sd, name, None)
        sd.stash = stash
        if sd.pack is None:
            sd.apply_pack()          # 背包已空,安全退回口袋容量
        save_mod.save_data(sd)
        audio.play("click")
        moved = len(carry) + len(slots)
        return True, f"已放回 {moved} 件并整理好仓库(枪/甲/子弹分区,背包已卷起)"

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
        # 设置页自己处理全部事件(改键捕获 / 触屏拖拽 / 点击)
        if self.view == "options":
            self._options_update(dt, events)
            return
        for ev in events:
            # 商品列表滚动条拖动中:鼠标移动 = 改滚动位置
            if ev.type == pygame.MOUSEMOTION and self.trade_drag:
                self._trade_drag_to(ev.pos[1])
                continue
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and self.trade_drag:
                self.trade_drag = False
                continue
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
                if ev.key == pygame.K_ESCAPE and self.view in ("trade", "task",
                                                               "story"):
                    self.view = "stash"
                    save_mod.save_data(self.game.save)
                    audio.play("click")
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 3:
                # 右键:仓库/背包里的背包类物品 卷起 / 展开
                if self.view == "stash":
                    self._right_click(ev.pos)
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self._scroll_click(ev.pos):     # 触屏翻页按钮最优先
                    return
                if self.view == "trade":
                    self._trade_click(ev.pos)
                elif self.view == "task":
                    self._task_click(ev.pos)
                elif self.view == "story":
                    self._story_click(ev.pos)
                else:
                    self._click(ev.pos)
                return

    # ---- 触屏翻页按钮(手机没有滚轮) ----
    def _scroll_buttons(self):
        """触屏 ▲▼ 按钮:key = (视图, 第几块列表)。"""
        if not self.scroll_btns:
            self.scroll_btns = {
                ("stash", 0): (pygame.Rect(468, 280, 28, 48),
                               pygame.Rect(468, 336, 28, 48)),
                ("trade", 0): (pygame.Rect(466, 250, 28, 48),
                               pygame.Rect(466, 306, 28, 48)),
                ("trade", 1): (pygame.Rect(1218, 250, 28, 48),
                               pygame.Rect(1218, 306, 28, 48)),
                ("task", 0): (pygame.Rect(1218, 300, 28, 48),
                              pygame.Rect(1218, 356, 28, 48)),
            }
        return self.scroll_btns

    def _scroll_click(self, pos):
        """点 ▲▼ 翻页。返回 True = 已消费这次点击。"""
        if not self.game.save.touch:
            return False
        b = self._scroll_buttons()

        def step(key):
            up, dn = b[key]
            if up.collidepoint(pos):
                return -1
            if dn.collidepoint(pos):
                return 1
            return 0

        if self.view == "stash":
            d = step(("stash", 0))
            if d:
                self.stash_scroll = max(0.0, min(
                    self.stash_scroll + d * 40, self.stash_max_scroll()))
                return True
        elif self.view == "trade":
            d = step(("trade", 1))
            if d:
                self.trade_scroll = max(0.0, min(
                    self.trade_scroll + d * 48, self.trade_max_scroll()))
                return True
            d = step(("trade", 0))
            if d:
                self.stash_scroll = max(0.0, min(
                    self.stash_scroll + d * 40, self.trade_stash_max_scroll()))
                return True
        elif self.view == "task":
            d = step(("task", 0))
            if d:
                self.task_scroll = max(0.0, min(
                    self.task_scroll + d * 44, self.task_max_scroll()))
                return True
        return False

    def _draw_scroll_buttons(self, screen, keys):
        """画 ▲▼(只在触屏模式)。"""
        if not self.game.save.touch:
            return
        b = self._scroll_buttons()
        mx, my = pygame.mouse.get_pos()
        for k in keys:
            up, dn = b[k]
            for r, label in ((up, "▲"), (dn, "▼")):
                hover = r.collidepoint(mx, my)
                pygame.draw.rect(screen,
                                 COL["panel_hi"] if hover else COL["panel"],
                                 r, border_radius=6)
                pygame.draw.rect(screen,
                                 COL["accent"] if hover else COL["border"],
                                 r, 2, border_radius=6)
                t = get_font(16, bold=True).render(
                    label, True, COL["accent"] if hover else COL["text"])
                screen.blit(t, t.get_rect(center=r.center))

    def _click(self, pos):
        sd = self.game.save
        lay = self.lay
        audio.play("click")

        # 地图选择(人质大楼/大本营/卡斯卡德 = 专用模式地图)
        for i, key in enumerate(MAP_ORDER):
            if self.map_rects[i].collidepoint(pos):
                sd.map_key = key
                if key == "indoor":
                    sd.mode = "hostage"
                elif key == "base":
                    sd.mode = "assault"
                elif key == "city":
                    sd.mode = "story"
                elif sd.mode in ("hostage", "assault", "story"):
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

        # 难度选择(突袭/人质/剧情是固定强度,没有难度档)
        if sd.mode in ("assault", "story") or sd.mode in MODE_DIFF:
            fixed_txt = ("突袭模式是固定强度,不适用难度档(系统会配发满配装备)"
                         if sd.mode == "assault" else
                         "剧情模式为固定强度(《灰区二日》有分支与结局,不吃难度档)"
                         if sd.mode == "story" else
                         "黑暗行动默认强化封锁(漆黑里再放水就没意思了),不适用难度档"
                         if sd.mode == "night" else
                         "人质解救固定为强化封锁强度,不适用难度档")
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
        if lay["story"].collidepoint(pos):
            self.view = "story"
            audio.play("click")
            return
        if lay["options"].collidepoint(pos):
            self.view = "options"
            self.opt_rebind = None
            self.opt_tab = "controls"
            self._opt_layout_load()
            audio.play("click")
            return
        if lay["organize"].collidepoint(pos):
            ok, msg = self.organize_stash()
            self.say(msg, COL["good"] if ok else COL["bad"], 3.4)
            return
        if lay["stash_all"].collidepoint(pos):
            ok, msg = self.stash_all_and_organize()
            self.say(msg, COL["good"] if ok else COL["bad"], 3.6)
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
        if lay["helmet"].collidepoint(pos):
            if sd.helmet is not None:
                old = sd.helmet
                if sd.stash.add_item(old):
                    sd.helmet = None
                    save_mod.save_data(sd)
                    self.say(f"已卸下 {old.name}")
                else:
                    self.say("仓库空间不足", COL["bad"])
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
                elif item.cat == "helmet":
                    old = sd.helmet
                    sd.stash.remove_placed(placed)
                    if old is not None and not sd.stash.add_item(old):
                        sd.stash.items.append(placed)
                        self.say("仓库空间不足", COL["bad"])
                        return
                    sd.helmet = item
                    save_mod.save_data(sd)
                    nvg = item.def_.get("nvg")
                    self.say(f"装备头盔 {item.name}"
                             + (f"(夜视半径 {int(nvg[0])})" if nvg else ""))
                elif item.cat == "attach":
                    self._install_attachment(sd, placed)
                elif item.cat == "pack":
                    idx = next((i for i, p in enumerate(sd.stash.items)
                                if p is placed), -1)
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
        """从仓库第 idx 件物品装备背包(全程克隆试算,失败绝不动存档)。"""
        from inventory import Container
        from settings import pack_grid
        sd = self.game.save
        if idx < 0 or idx >= len(sd.stash.items):
            return False, "物品已变化"
        live = sd.stash.items[idx]
        new_pack = live.item
        if new_pack.cat != "pack":
            return False, ""
        # 关键:先克隆试算,别动真身 —— 卷起的背包一旦就地展开,就会撑破它
        # 原来占的格子(变成越界物品),之后任何摆放/探测都会直接崩。
        stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
        bag = Container.deserialize(sd.bag.w, sd.bag.h, sd.bag.serialize())
        # 克隆里是复制出来的新对象,所以按 (iid, 坐标) 认人,不能按身份或旧下标
        target = next((p for p in stash.items
                       if p.item.iid == new_pack.iid
                       and p.x == live.x and p.y == live.y), None)
        if target is None:
            return False, "物品已变化"
        pack = self._clone_item(sd.pack)
        gw, gh = pack_grid(new_pack.iid)
        new_bag, overflow = bag.resized(gw, gh)
        stash.remove_placed(target)
        for it in overflow:
            if not stash.add_item(it):
                return False, f"背包收窄到 {gw}×{gh},放不下的东西仓库也塞不下"
        if pack is not None and not stash.add_item(pack):
            return False, "仓库空间不足,无法换下旧背包"
        # 试算全部通过,这时才真正把新背包展开并装到身上
        new_pack.state.pop("rolled", None)
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
        # 商品列表右边的滚动条:点手柄/轨道就开始拖
        if self.trade_slider is not None:
            track, handle = self.trade_slider
            if handle.collidepoint(pos):
                self.trade_drag = True
                return
            if track.collidepoint(pos):
                self.trade_drag = True
                self._trade_drag_to(pos[1])
                return
        # 批量出售的确认框最优先
        if self.sell_ask is not None:
            if self.sell_ask_yes.collidepoint(pos):
                ok, msg = self._sell_do()
                self.say(msg, COL["good"] if ok else COL["bad"], 3.4)
            elif self.sell_ask_no.collidepoint(pos):
                self.sell_ask = None
                self.say("已取消批量出售", COL["text_dim"])
            return
        if self.trade_close.collidepoint(pos):
            self.view = "stash"
            self.sell_mode = False
            self.sell_sel = []
            save_mod.save_data(sd)
            return
        # 批量出售的按钮
        if self.sell_toggle.collidepoint(pos):
            self.sell_mode = not self.sell_mode
            if not self.sell_mode:
                self.sell_sel = []
            return
        if self.sell_mode:
            if self.sell_junk.collidepoint(pos):
                n = self._sell_pick(("misc", "valuable"))
                self.say(f"已选中 {n} 件杂物/值钱货" if self.sell_selected()
                         else f"已取消 {n} 件杂物/值钱货", COL["accent"], 2.4)
                return
            if self.sell_ammo.collidepoint(pos):
                n = self._sell_pick(("ammo",))
                self.say(f"已选中 {n} 组子弹" if self.sell_selected()
                         else f"已取消 {n} 组子弹", COL["accent"], 2.4)
                return
            if self.sell_clear.collidepoint(pos):
                self.sell_sel = []
                self.say("已清空选择", COL["text_dim"], 2.0)
                return
            if self.sell_go.collidepoint(pos):
                sel = self.sell_selected()
                if not sel:
                    self.say("先在左边点选要卖的物品(或点快捷选择)", COL["bad"], 3.0)
                    return
                self.sell_ask = dict(items=list(sel), total=self.sell_total())
                return
        # 分区标签
        for i, (label, cat) in enumerate(TRADE_TABS):
            if self.trade_tab_rects[i].collidepoint(pos):
                self.trade_cat = cat
                self.trade_scroll = 0.0
                return
        # 点仓库物品:批量模式下 = 选中/取消;普通模式 = 直接卖掉
        placed = self.trade_stash_hit(pos)
        if placed is not None:
            if self.sell_mode:
                sel = self.sell_selected()
                if placed in sel:
                    sel.remove(placed)
                else:
                    sel.append(placed)
                self.sell_sel = sel
                return
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
            self._draw_scroll_buttons(screen, [("trade", 0), ("trade", 1)])
            return
        if self.view == "task":
            self._draw_task(screen)
            self._draw_scroll_buttons(screen, [("task", 0)])
            return
        if self.view == "story":
            self._draw_story_brief(screen)
            return
        if self.view == "options":
            self._draw_options(screen)
            return
        lay = self.lay
        sd = self.game.save
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])

        t = get_font(34, bold=True).render("藏身处 — TARKOV 2D", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))

        # ---- 仓库(格子变多了:只画看得见的一段,滚轮上下翻) ----
        uikit.draw_panel(screen, lay["stash_panel"],
                         "仓库 (左键放装备 · 右键背包卷起)")
        draw_grid(screen, self.stash_grid[0], self.stash_grid[1], sd.stash, 40,
                  scroll=self.stash_scroll, view_h=self.stash_view_h)
        draw_button(screen, lay["organize"], "一键整理",
                    lay["organize"].collidepoint(mx, my), small=True)
        if self.stash_max_scroll() > 0:
            t = get_font(13).render(
                f"滚轮上下翻(仓库共 {sd.stash.h} 行)",
                True, COL["text_dim"])
            screen.blit(t, (self.stash_grid[0],
                            self.stash_grid[1] + self.stash_view_h + 10))
        self._draw_scroll_buttons(screen, [("stash", 0)])

        # ---- 出战配置 ----
        uikit.draw_panel(screen, lay["loadout_panel"], "出战配置")
        draw_button(screen, lay["stash_all"], "一键放回仓库并整理",
                    lay["stash_all"].collidepoint(mx, my), small=True)
        draw_slot(screen, lay["weapon"], sd.weapon, "武器",
                  hover=lay["weapon"].collidepoint(mx, my))
        draw_slot(screen, lay["armor"], sd.armor, "护甲",
                  hover=lay["armor"].collidepoint(mx, my))
        draw_slot(screen, lay["helmet"], sd.helmet, "头盔",
                  hover=lay["helmet"].collidepoint(mx, my))
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
                    {k: MODES[k].get("short", MODES[k]["name"]) for k in MODE_ORDER},
                    sd.mode)
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
            if sd.mode == "night":
                fixed_lines = ("黑暗行动:全图漆黑,只有光源范围可见 ——",
                               "默认强化封锁,光源要自己带(手电/夜视头盔)")
            else:
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
        kl = bindings.label_for(sd, "interact")
        hr = bindings.label_for(sd, "heal")
        hb = bindings.label_for(sd, "bag")
        move_txt = "WASD 移动" if not bindings.is_modified(sd, "up") else (
            "移动 " + "".join(bindings.label_for(sd, a)
                              for a in ("up", "left", "down", "right")))
        lines = [
            f"出击 {st['raids']} 次    撤离 {st['extracts']} 次",
            f"阵亡 {st['deaths']} 次    击杀 {st['kills']} 人",
            f"余额 {fmt_rub(sd.rubles)}    搜刮 {fmt_rub(st['value'])}",
            "",
            f"{move_txt} · 左键射击 · 右键架枪",
            f"弹匣空自动换弹 · {hr} 打药 · {kl} 搜刮/救人",
            f"{hb} 背包 · 死亡会丢失带入的装备!",
        ]
        if assault_run:
            lines[-1] = (f"{hb} 背包 · "
                         + " / ".join(bindings.label_for(sd, a)
                                      for a in ("support1", "support2", "support3"))
                         + " 呼叫友军支援")
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
        draw_button(screen, lay["trade"], "交易",
                    lay["trade"].collidepoint(mx, my), small=True)
        ready_n = sum(1 for t in TASKS
                      if quests.task_state(sd, t)[0] == "ready")
        draw_button(screen, lay["tasks"],
                    "任务" + (f"({ready_n})" if ready_n else ""),
                    lay["tasks"].collidepoint(mx, my), small=True)
        draw_button(screen, lay["story"], "剧情",
                    lay["story"].collidepoint(mx, my), small=True)
        draw_button(screen, lay["options"], "设置",
                    lay["options"].collidepoint(mx, my), small=True)
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
        if hover_item is None and lay["helmet"].collidepoint(mx, my) and sd.helmet:
            hover_item = sd.helmet
        if hover_item is None and lay["pack"].collidepoint(mx, my) and sd.pack:
            hover_item = sd.pack
        if hover_item is not None:
            draw_tooltip(screen, mx, my, hover_item)

    # ---------- 剧情简报 ----------
    def _story_panel(self):
        return pygame.Rect(120, 92, W - 240, 460)

    def _story_click(self, pos):
        """剧情简报页:点「返回」退回仓库;点面板外的空白处也退(别卡在这一页)。"""
        if (self.task_close.collidepoint(pos)
                or not self._story_panel().collidepoint(pos)):
            audio.play("click")
            self.view = "stash"
            save_mod.save_data(self.game.save)

    # ---------- 剧情简报渲染 ----------
    def _draw_story_brief(self, screen):
        """《灰区二日》简报:当前时段任务、状态、已解锁结局。"""
        import story as story_mod
        sd = self.game.save
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])
        t = get_font(34, bold=True).render("剧情 ·《灰区二日》", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 44)))
        bal = get_font(20, bold=True).render("北境工业城 卡斯卡德-7", True,
                                             COL["text_dim"])
        screen.blit(bal, (W - bal.get_width() - 30, 40))

        panel = self._story_panel()
        uikit.draw_panel(screen, panel, "当前情况")
        lines = story_mod.brief_lines(sd)
        f = get_font(17)
        y = panel.y + 46
        for i, ln in enumerate(lines):
            col = COL["accent"] if i == 0 else (
                COL["good"] if ":" in ln or "结局" in ln else COL["text"])
            t = f.render(ln, True, col)
            screen.blit(t, (panel.x + 26, y))
            y += 26
            if y > panel.bottom - 40:
                break
        t = get_font(15).render(
            "每个时段出击一次:做完目标就从开放的撤离点撤出;"
            "阵亡/超时不丢进度,但会丢装备", True, COL["text_dim"])
        screen.blit(t, (panel.x + 26, panel.bottom - 32))
        if sd.mode != "story":
            t = get_font(18, bold=True).render(
                "提示:把「游戏模式」切到「剧情」后开始战局,才会推进剧情",
                True, COL["bad"])
            screen.blit(t, t.get_rect(center=(W // 2, panel.bottom + 40)))
        else:
            t = get_font(17, bold=True).render(
                f"开始战局将进入:{story_mod.mission_title(sd)}", True, COL["good"])
            screen.blit(t, t.get_rect(center=(W // 2, panel.bottom + 40)))
        draw_button(screen, self.task_close, "返回",
                    self.task_close.collidepoint(mx, my), small=True)

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

        # ---- 左:仓库(点击出售 / 批量出售;格子多了用滚轮翻) ----
        sel = self.sell_selected()
        uikit.draw_panel(screen, lay["trade_stash"],
                         "你的仓库 — 点物品选中(批量出售)" if self.sell_mode
                         else "你的仓库 — 点击物品出售")
        gx0, gy0 = self.trade_stash_grid
        draw_grid(screen, gx0, gy0, sd.stash, 40,
                  scroll=self.stash_scroll, view_h=self.trade_stash_view_h)
        # 批量模式:被选中的物品描边高亮
        if self.sell_mode:
            for p in sel:
                w, h = p.item.size()
                r = pygame.Rect(gx0 + p.x * 40,
                                gy0 + p.y * 40 - int(self.stash_scroll),
                                w * 40, h * 40)
                if r.bottom < gy0 or r.top > gy0 + self.trade_stash_view_h:
                    continue
                hl = pygame.Surface(r.size, pygame.SRCALPHA)
                hl.fill((120, 220, 120, 80))
                screen.blit(hl, r)
                pygame.draw.rect(screen, COL["good"], r, 3)
        t = get_font(14).render(
            ("批量出售:左键点物品 选中/取消  ·  回收价 60%"
             if self.sell_mode else "出售价 = 原价 60%,卖错了只能高价买回")
            + ("  (滚轮翻仓库)" if self.trade_stash_max_scroll() > 0 else ""),
            True, COL["text_dim"])
        screen.blit(t, (gx0, gy0 + self.trade_stash_view_h + 10))
        draw_button(screen, self.sell_toggle,
                    "批量出售:开" if self.sell_mode else "批量出售:关",
                    self.sell_toggle.collidepoint(mx, my), small=True)
        if self.sell_mode:
            draw_button(screen, self.sell_junk, "全选杂物",
                        self.sell_junk.collidepoint(mx, my), small=True)
            draw_button(screen, self.sell_ammo, "全选子弹",
                        self.sell_ammo.collidepoint(mx, my), small=True)
            n = len(sel)
            total = self.sell_total()
            draw_button(screen, self.sell_go,
                        f"出售选中 {n} 件 · {fmt_rub(total)}" if n
                        else "出售选中(先点物品)",
                        self.sell_go.collidepoint(mx, my) and n > 0,
                        small=True)
            if n:
                draw_button(screen, self.sell_clear, f"清空选择({n})",
                            self.sell_clear.collidepoint(mx, my), small=True)

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
            # 枪械分类标签(暗区式:突击步枪/冲锋枪/狙击步枪/轻机枪/霰弹枪…)
            cls = weapon_class(iid)
            if cls:
                tag = get_font(12, bold=True).render(
                    cls, True, WEAPON_CLASS_COL.get(cls, COL["text_dim"]))
                tx = rect.x + 26 + t.get_width()
                if tx + tag.get_width() + 12 < rect.right - 90:
                    pygame.draw.rect(screen, (46, 50, 58),
                                     (tx, rect.y + 9, tag.get_width() + 10, 18),
                                     border_radius=4)
                    pygame.draw.rect(screen, WEAPON_CLASS_COL.get(cls, COL["border"]),
                                     (tx, rect.y + 9, tag.get_width() + 10, 18),
                                     1, border_radius=4)
                    screen.blit(tag, (tx + 5, rect.y + 11))
            tp = get_font(15, bold=True).render(fmt_rub(price), True,
                                                COL["accent"] if afford else COL["text_dim"])
            screen.blit(tp, (rect.right - tp.get_width() - 10, rect.y + 7))
        # 滚动条(可以用鼠标拖着走;手机用 ▲▼)
        ms = self.trade_max_scroll()
        self.trade_slider = None
        if ms > 0:
            track = self.trade_slider_track()
            pygame.draw.rect(screen, COL["grid_bg"], track, border_radius=5)
            ratio = TRADE_PAGE_H / (TRADE_PAGE_H + ms)
            h = max(30, int(track.h * ratio))
            pos = int((self.trade_scroll / ms) * (track.h - h))
            handle = pygame.Rect(track.x, track.y + pos, track.w, h)
            hover = handle.collidepoint(mx, my) or self.trade_drag
            pygame.draw.rect(screen, COL["accent"] if hover else (120, 128, 142),
                             handle, border_radius=5)
            for i in range(3):     # 手柄上的三道纹,一眼能看出可以拖
                yy = handle.centery - 6 + i * 6
                pygame.draw.line(screen, (32, 36, 44),
                                 (handle.x + 3, yy), (handle.right - 3, yy), 2)
            self.trade_slider = (track, handle)
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
            placed = self.trade_stash_hit((mx, my))     # 要算上滚轮偏移
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
        if self.sell_ask is not None:
            self._draw_sell_ask(screen)
