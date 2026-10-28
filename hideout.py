# -*- coding: utf-8 -*-
"""藏身处:仓库管理、出战整备、开局。"""
import math
import time

import pygame

import audio
import bindings
import intro
import mystery
import quests
import save as save_mod
import touch as touch_mod
from settings import (W, H, COL, fmt_rub, get_font, DIFF_ORDER, DIFFICULTIES,
                      weapon_slots, weapon_attach, weapon_capacity, ATTACH_SLOTS,
                      ITEMS, TRADE_GOODS, TRADE_TABS, TRADE_PAGE_H, FPS_CAP_CHOICES,
                      trade_buy_price, trade_sell_price, STASH_VIEW_ROWS,
                      MODE_DIFF, DEPTS, TASKS, SAFE_CONTRACT,
                      MYSTERY_STARS, MYSTERY_KITS,
                      armor_allows, MAPS, MAP_ORDER, MODES, MODE_ORDER, MODE_MAP,
                      weapon_class, WEAPON_CLASS_COL, COOP_MODES, to_display,
                      LOADOUT_SLOTS, LOADOUT_SLOT_NAMES, loadout_get, loadout_set,
                      loadout_add, loadout_all, loadout_weapons, loadout_limits,
                      loadout_free_slot, is_melee)
from inventory import Item, Placed, organize, try_move
import accounts
import coop as coop_mod
import uikit
from uikit import draw_grid, draw_button, draw_slot, draw_tooltip


# 全屏暗幕缓存:每帧新建 (W,H) SRCALPHA 表面 + fill + 逐像素 alpha blit 是
# 这条路径上最贵的一笔(见 ANDROID-BUILD.md §9 的 SDL 实测表)。按 key 复用,
# 和 raid_ui._overlay 同一套做法。
_dark_cache = {}


def _overlay(key, size, color):
    surf = _dark_cache.get(key)
    if surf is None:
        surf = to_display(pygame.Surface(size, pygame.SRCALPHA), True)
        _dark_cache[key] = surf
    surf.fill(color)
    return surf


def _layout():
    # 出战配置面板:4 个武器位(2 主武器 + 副武器 + 近战)排成 2×2,下面一行放
    # 护甲/头盔/背包,再下面是出战背包网格。
    return dict(
        stash_panel=pygame.Rect(30, 100, 470, 430),
        loadout_panel=pygame.Rect(516, 100, 390, 430),
        side_panel=pygame.Rect(922, 100, 330, 438),
        weapon=pygame.Rect(542, 146, 86, 46),
        main2=pygame.Rect(630, 146, 86, 46),
        side=pygame.Rect(542, 196, 86, 46),
        melee=pygame.Rect(630, 196, 86, 46),
        armor=pygame.Rect(542, 246, 86, 46),
        helmet=pygame.Rect(634, 246, 86, 46),
        pack=pygame.Rect(726, 246, 86, 46),
        bag_origin=(542, 302),      # 出战背包网格原点(cell 动态)
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


BAG_MAX_CELL = 42      # 出战背包网格最大格子边长(要给上面 4 个武器位腾地方)
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
        # 双人合作开关(同一台电脑两人玩;搜打撤 / 夜战都能开,见 coop.py)
        self.coop_rect = pygame.Rect(sp.x + 220, sp.y + 146, 92, 26)
        # 局域网联机小节(创建房间 / 搜索并加入 / 断开 / 手动 IP;内核见 net.py)。
        # 底部按钮(548~602)下面正好空着一条带,整块放这儿,不动别的布局。
        self.net_panel = pygame.Rect(30, 606, 1226, 72)
        self.net_host_btn = pygame.Rect(48, 636, 96, 28)
        self.net_join_btn = pygame.Rect(152, 636, 120, 28)
        self.net_off_btn = pygame.Rect(280, 636, 72, 28)
        self.net_ip_box = pygame.Rect(372, 636, 168, 28)
        self.net_ip_go = pygame.Rect(548, 636, 64, 28)
        self.net_start_btn = pygame.Rect(620, 636, 132, 28)   # 主机开局
        self.net_ip = ""             # 手动输入的房主 IP(可选项)
        self.net_ip_edit = False     # 正在输入 IP(这期间键盘归输入框)
        self.net_hosts = []          # 最近一次扫描到的房间:[{ip,name,port}, ...]
        self.net_scan_t = 0.0        # >0 = 还在扫描(时间到再决定连谁)
        self.net_mod_ok = None       # net.py 在不在(只为把提示说准,查一次就缓存)
        self.diff_rects = [pygame.Rect(sp.x + 18 + i * 100, sp.y + 248, 92, 30)
                           for i in range(3)]
        # 仓库滚轮(仓库格子变多了,面板只显示一部分)
        self.stash_scroll = 0.0
        self.stash_grid = (66, 176)
        self.stash_view_h = 40 * STASH_VIEW_ROWS
        # 保险箱(阵亡不丢):仓库面板底部一条;40 个承包商任务全部完成升 4 格
        self.safe_in = False                 # 存入模式:点仓库物品进保险箱
        self.safe_grid = (66, 478)
        self.safe_cell = 24
        self.safe_toggle = pygame.Rect(262, 484, 158, 30)
        # 触屏长按(显示物品详情;普通点按延迟到抬起判定)
        self.hold = uikit.HoldInfo()
        # 任务中心:五个部门(教官 / 医疗 / 后勤 / 保险承包商 / 礼品)
        self.task_dept = "instructor"
        self.task_scroll = 0.0
        self.task_tab_rects = [pygame.Rect(544 + i * 140, 132, 134, 32)
                               for i in range(len(DEPTS))]
        self.task_view_top = 186
        self.task_view_bottom = 600
        self.task_row_h = 56
        self.task_close = pygame.Rect(1140, 76, 100, 36)
        # 礼品页:神秘人的收集清单 + 交付按钮
        self.gift_btn = pygame.Rect(560, 578, 660, 44)
        # 交易所:一页 —— 左边你的仓库(点物品出售 / 批量出售),右边分区 + 商品。
        # 分区标签横排一行、商品网格在右半屏:这样「点仓库物品」和「点分区标签」
        # 各占一块地方,谁也不会盖住谁(分成购买/出售两页时两块都落在左面板上)。
        self.trade_stash_grid = (66, 150)
        self.trade_stash_view_h = 9 * 40      # 交易所左侧仓库可见高度(其余滚轮翻)
        self.trade_cat = None            # 当前分区(None = 全部)
        self.trade_scroll = 0.0          # 商品网格的滚动偏移
        self.trade_view_top = 178        # 商品网格可见范围(与 trade_view_bottom 一对)
        self.trade_view_bottom = 178 + TRADE_PAGE_H
        self.trade_close = pygame.Rect(W - 130, 22, 100, 40)
        self.trade_drag = False          # 正在拖商品列表的滚动条
        self.trade_slider = None         # 本帧商品滚动条 (轨道, 手柄),画的时候填
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
        # 拖动判定:手指按下时先不算拖动,移动超过阈值才真拖 ——
        # 否则"点一下选中"会顺手把按钮挪走几个像素(手机上很难操作)
        self.opt_drag_from = (0, 0)     # 按下时的位置
        self.opt_drag_moved = False     # 本次是否真的拖动过
        self.opt_drag_space = "screen"  # 拖动按哪套坐标算:"screen" 屏幕 / "preview" 缩略图
        self.opt_bind_rects = [pygame.Rect(852, 184 + i * 28, 240, 26)
                               for i in range(len(bindings.ACTIONS))]
        self.opt_fps_rects = [pygame.Rect(772 + i * 108, 214, 98, 34)
                              for i in range(len(FPS_CAP_CHOICES))]
        self.opt_fps_toggle = pygame.Rect(772, 274, 98, 34)
        self.opt_filter_rects = [pygame.Rect(772 + i * 134, 334, 124, 34)
                                 for i in range(2)]
        # +/- 改大小。原来是 44x30 —— 在手机上折算下来只有约 3mm,
        # 远小于可点中的最小尺寸(7~9mm),屏幕稍微一点就点空/点错,所以放大。
        self.opt_minus = pygame.Rect(1040, 548, 84, 52)
        self.opt_plus = pygame.Rect(1132, 548, 84, 52)
        self.opt_save = pygame.Rect(548, 616, 200, 40)
        self.opt_defaults = pygame.Rect(770, 616, 200, 40)
        # 账号:显示当前存档属于谁 + 回登录界面换账号(见 accounts.py)
        self.opt_account = pygame.Rect(1010, 74, 150, 30)
        # 触屏模式的翻页按钮(手机没有滚轮)
        self.scroll_btns = {}
        self.rscroll_btns = {}

    # ---- 交易所:布局 ----
    # 所有几何一律从这里出,绘制和命中共用同一份 —— 设置页的触屏编辑器
    # 就吃过「画在一处、点在另一处」的亏,这里不再给它机会。
    TRADE_COLS = 4           # 商品每行列数
    TRADE_CELL_H = 64        # 商品格高
    TRADE_PAD = 6
    TRADE_TAB_H = 30         # 分区标签高
    TRADE_TAB_PAD = 6        # 分区标签间距

    def _trade_panels(self):
        """(左面板, 右面板):左 = 你的仓库,右 = 分区标签 + 商品。"""
        lay = self.lay
        return (lay["trade_stash"], lay["trade_goods"])

    def _trade_cat_rows(self):
        """分区标签 [(label, cat, rect)]:横排一行,全都在右面板顶上。"""
        p = self._trade_panels()[1]
        n = max(1, len(TRADE_TABS))
        w = (p.w - 24 - self.TRADE_TAB_PAD * (n - 1)) // n
        x0 = p.x + 12
        y = p.y + 44                       # 让开面板标题那一行
        return [(label, cat,
                 pygame.Rect(x0 + i * (w + self.TRADE_TAB_PAD), y, w,
                             self.TRADE_TAB_H))
                for i, (label, cat) in enumerate(TRADE_TABS)]

    def _trade_goods_view(self):
        """右侧商品网格的可见范围(上面留给分区标签,右边留给滚动条)。"""
        p = self._trade_panels()[1]
        x = p.x + 18
        return pygame.Rect(x, self.trade_view_top,
                           p.right - 36 - x, TRADE_PAGE_H)

    def _trade_cell_rect(self, i):
        """第 i 个商品的格子(网格排布,已应用滚动偏移)。"""
        view = self._trade_goods_view()
        cols = self.TRADE_COLS
        cw = (view.w - self.TRADE_PAD * (cols - 1)) // cols
        col, row = i % cols, i // cols
        return pygame.Rect(view.x + col * (cw + self.TRADE_PAD),
                           view.y + row * (self.TRADE_CELL_H + self.TRADE_PAD)
                           - int(self.trade_scroll),
                           cw, self.TRADE_CELL_H)

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

    # ---- 触屏布局:预览框 ----
    # 预览框是整屏按 16:9 缩小的"缩略图";存档里的 rx/ry 始终是**整屏比例**
    # (touch.py 按 rx*W, ry*H 摆按钮,战局里用的就是它,设置页的 +/- 也按它算)。
    # 所以命中判定先把点落回整屏坐标再比距离:点缩略图里 = 换算回去,
    # 点框外 = 就是屏幕上的真实位置。画出来什么样,就点什么。
    def _opt_touch_frame(self):
        """预览框。

        宽高比必须和游戏画面一致(1280:720 = 16:9):原来框是 660x340(≈1.94),
        横向被拉伸了 9%,照着预览摆出来的位置和实战对不上。
        604x340 正好把 16:9 装进这块地方。
        """
        return pygame.Rect(560, 206, 604, 340)

    def _opt_touch_pos(self, name):
        """按钮名 -> (预览框内的 x, y, 显示半径)。只给预览框绘制用。"""
        d = self.opt_layout[name]
        f = self._opt_touch_frame()
        return (f.x + d["rx"] * f.w,
                f.y + d["ry"] * f.h,
                max(10, int(d["r"] * f.h / float(H))))

    def _opt_touch_pick(self, pos):
        """点选:先把点落回整屏坐标,再取**最近**的按钮,不是字典里第一个。

        返回 (按钮名, 这次操作在哪套坐标里 —— "preview" 缩略图 / "screen" 屏幕)。
        以前是遍历到第一个命中的就 break,按钮一重叠就永远只能选到
        排在前面的那个。顺带:如果点到的正是当前已选中的按钮,就轮到下一个,
        这样被压住的按钮也选得中。
        """
        f = self._opt_touch_frame()
        if f.collidepoint(pos):              # 点的缩略图:换算回整屏坐标
            x = (pos[0] - f.x) / float(f.w) * W
            y = (pos[1] - f.y) / float(f.h) * H
            space = "preview"
        else:                                # 点的就是屏幕真实位置
            x, y = pos[0], pos[1]
            space = "screen"
        cands = []
        for name in self.opt_layout:
            d = self.opt_layout[name]
            px, py = d["rx"] * W, d["ry"] * H
            r = max(22, d["r"])              # 手指的最小命中半径
            dist = math.hypot(x - px, y - py)
            if dist <= r:
                cands.append((dist, name))
        if not cands:
            return None, space
        cands.sort()
        names = [n for _d, n in cands]
        if len(names) > 1 and self.opt_sel in names:
            return names[(names.index(self.opt_sel) + 1) % len(names)], space
        return names[0], space

    def _options_drag_to(self, pos):
        """触屏布局:把正在拖动的按钮挪到手指位置(比例坐标 = 整屏比例)。"""
        name = self.opt_drag
        d = self.opt_layout.get(name)
        if d is None:
            return
        # 没超过阈值就还不算拖动 —— 单纯点一下不会把按钮蹭走几个像素
        if not self.opt_drag_moved:
            sx, sy = self.opt_drag_from
            if math.hypot(pos[0] - sx, pos[1] - sy) < 8:
                return
            self.opt_drag_moved = True
        f = self._opt_touch_frame()
        if self.opt_drag_space == "preview":   # 在缩略图里拖:换算回整屏比例
            rx = (pos[0] - f.x) / float(f.w)
            ry = (pos[1] - f.y) / float(f.h)
        else:                                  # 直接按屏幕位置拖
            rx = pos[0] / float(W)
            ry = pos[1] / float(H)
        # 按半径留边:至少让大半个按钮留在屏幕里(拖出去了就再也点不到)
        mx = min(0.45, d["r"] * 0.5 / float(W))
        my = min(0.45, d["r"] * 0.5 / float(H))
        d["rx"] = min(1.0 - mx, max(mx, rx))
        d["ry"] = min(1.0 - my, max(my, ry))

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
        if self.opt_account.collidepoint(pos):
            # 回登录界面换账号(藏身处才允许;战局中不能换)
            if self.game.request_switch_account():
                audio.play("pickup")
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
            hit, space = self._opt_touch_pick(pos)
            if hit is not None:
                self.opt_sel = hit
                self.opt_drag = hit
                # 记下按下点和这次操作在哪套坐标里:拖动时按这个点算"有没有
                # 真的动过",并沿同一套坐标换算(见 _options_drag_to)
                self.opt_drag_space = space
                self.opt_drag_from = pos
                self.opt_drag_moved = False
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

        # 账号(存档归属)+ 换账号
        acct = getattr(save_mod, "PROFILE", None)
        t = get_font(15, bold=True).render(
            f"账号:{acct or '(未登录)'}", True, COL["text_dim"])
        screen.blit(t, (546, 80))
        draw_button(screen, self.opt_account, "切换账号",
                    self.opt_account.collidepoint(mx, my), small=True)

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
        frame = self._opt_touch_frame()
        pygame.draw.rect(screen, (16, 18, 22), frame, border_radius=8)
        pygame.draw.rect(screen, COL["border"], frame, 1, border_radius=8)
        sx = frame.x + frame.w * 0.22
        sy = frame.bottom - 78
        pygame.draw.circle(screen, (48, 52, 62), (int(sx), int(sy)), 44, 2)
        tt = get_font(12).render("摇杆区(固定)", True, (110, 118, 132))
        screen.blit(tt, tt.get_rect(center=(int(sx), int(sy) + 58)))
        # 一律走 _opt_touch_pos:缩略图里的位置和存档里的整屏比例是同一套(见该函数说明)
        for name in self.opt_layout:
            px, py, r = self._opt_touch_pos(name)
            d = self.opt_layout[name]
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
            screen.blit(info, (548, 562))
            draw_button(screen, self.opt_minus, "−",
                        self.opt_minus.collidepoint(mx, my))
            draw_button(screen, self.opt_plus, "+",
                        self.opt_plus.collidepoint(mx, my))
        else:
            t = get_font(15).render("点一个按钮选中它", True, COL["text_dim"])
            screen.blit(t, (548, 566))

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
        dark = _overlay("sell_ask_dark", (W, H), (0, 0, 0, 130))
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

    # ---- 交易站:商品网格与滚动 ----
    def trade_goods(self):
        """当前分区的商品列表(「特殊枪械」= 头目专属枪械)。"""
        from settings import trade_cat_match
        return [g for g in TRADE_GOODS if trade_cat_match(g[0], self.trade_cat)]

    def trade_max_scroll(self):
        goods = self.trade_goods()
        rows = (len(goods) + self.TRADE_COLS - 1) // self.TRADE_COLS
        content = rows * (self.TRADE_CELL_H + self.TRADE_PAD)
        return max(0.0, float(content - self._trade_goods_view().h))

    # ---- 滚动条(可拖动;手机上没滚轮时靠它) ----
    def trade_slider_track(self):
        p = self._trade_panels()[1]
        return pygame.Rect(p.right - 18, self.trade_view_top, 14, TRADE_PAGE_H)

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
        for name in ("armor", "helmet", "pack"):
            it = getattr(sd, name)
            if it is None:
                continue
            clone = self._clone_item(it)
            if clone.state.get("rolled"):
                clone.state.pop("rolled", None)      # 放回仓库时按展开尺寸算空间
            slots.append((name, clone))
        for name, it in loadout_all(sd).items():
            if it is None:
                continue
            clone = self._clone_item(it)
            if clone.state.get("rolled"):
                clone.state.pop("rolled", None)
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
            if name in LOADOUT_SLOTS:
                loadout_set(sd, name, None)
            else:
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
        """仓库/背包/保险箱里右键:背包 = 卷起/展开;全装包 = 打开;其他 = 横竖旋转。"""
        sd = self.game.save
        if self.lay["stash_panel"].collidepoint(pos):
            placed = self.stash_hit(pos)
            if placed is not None:
                if placed.item.cat in ("pack", "kit"):
                    self._use_placed(sd.stash, placed)
                else:
                    self._rotate_placed(sd.stash, placed)
            return
        if self.safe_rect().collidepoint(pos):
            placed = self._safe_at(pos)
            if placed is not None:
                if placed.item.cat == "kit":
                    self._use_placed(sd.safe, placed)
                else:
                    self._rotate_placed(sd.safe, placed)
            return
        if self.bag_rect().collidepoint(pos):
            cell = self.bag_cell()
            brect = self.bag_rect()
            gx = int((pos[0] - brect.x) // cell)
            gy = int((pos[1] - brect.y) // cell)
            placed = sd.bag.at(gx, gy)
            if placed is not None:
                if placed.item.cat in ("pack", "kit"):
                    self._use_placed(sd.bag, placed)
                else:
                    self._rotate_placed(sd.bag, placed)

    def _use_placed(self, container, placed):
        """背包类 = 卷起/展开;全装包 = 打开成一套装备。都会落盘并给提示。"""
        it = placed.item
        if it.cat == "kit":
            ok, msg = mystery.open_kit(container, placed)
        else:
            ok, msg = self._toggle_roll(container, placed)
        if msg:
            save_mod.save_data(self.game.save)
            audio.play("click")
            self.say(msg, COL["good"] if ok else COL["bad"], 3.4)

    # ---- 保险箱(阵亡不丢) ----
    def safe_rect(self):
        sd = self.game.save
        return pygame.Rect(self.safe_grid[0], self.safe_grid[1],
                           sd.safe.w * self.safe_cell, sd.safe.h * self.safe_cell)

    def _safe_at(self, pos):
        gx = int((pos[0] - self.safe_grid[0]) // self.safe_cell)
        gy = int((pos[1] - self.safe_grid[1]) // self.safe_cell)
        return self.game.save.safe.at(gx, gy)

    def _rotate_placed(self, container, placed):
        """原位横竖旋转 + 反馈。旋转成功会落盘。"""
        from inventory import rotate_in_place
        res = rotate_in_place(container, placed)
        if res is None:
            self.say(f"{placed.item.name} 是方形,不用旋转", COL["text_dim"], 2.0)
        elif res:
            save_mod.save_data(self.game.save)
            audio.play("click")
            self.say(f"已调整 {placed.item.name} 的摆放方向(横 / 竖)")
        else:
            self.say("原位转不开,先给它周围腾点地方", COL["bad"], 2.6)

    # ---- 触屏长按:点按延迟到抬起 + 按住 0.45s 弹详情 ----
    def _hold_filter(self, dt, events):
        """触屏事件过滤。普通点按在抬起时重放;长按弹面板;拖动不误触。"""
        out = []
        for ev in events:
            if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.hold.active():
                    # 面板已弹出:点动作按钮 = 执行;点别处 = 关闭(都吞掉)
                    if (self.hold.action_rect is not None
                            and self.hold.action_rect.collidepoint(ev.pos)):
                        self._hold_action()
                    self.hold.hide()
                    continue
                if self.view == "trade" and self.trade_slider is not None:
                    track, _handle = self.trade_slider
                    if track.collidepoint(ev.pos):
                        out.append(ev)      # 滚动条保持立即拖动
                        continue
                self.hold.press(ev.pos)
                continue
            if ev.type == pygame.MOUSEMOTION:
                self.hold.move(ev.pos)
                out.append(ev)
                continue
            if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self.hold.consume_release():
                    # 普通点按:重放成一次按下(所有原逻辑照常)。
                    # 坐标用**按下点**(见 uikit.HoldInfo.click_pos):手抖时
                    # 用抬起点会滑到隔壁商品格上,变成买错东西。
                    out.append(pygame.event.Event(
                        pygame.MOUSEBUTTONDOWN,
                        pos=self.hold.click_pos() or ev.pos, button=1))
                else:
                    out.append(ev)
                continue
            out.append(ev)
        self.hold.update(dt, self._hold_query)
        return out

    def _hold_action(self):
        """长按面板上的动作按钮:全装包 = 打开;背包 = 卷起/展开;其他 = 旋转。"""
        cb = self.hold.action_cb
        if cb is None:
            return
        container, placed = cb
        if placed is None or placed not in container.items:
            return
        if placed.item.cat in ("pack", "kit"):
            self._use_placed(container, placed)
        else:
            self._rotate_placed(container, placed)

    def _hold_query(self, pos):
        """长按落点查询:返回 (item, (container, placed)) 或 None。"""
        sd = self.game.save
        if self.view == "trade":
            placed = self.trade_stash_hit(pos)
            if placed is not None:
                return placed.item, (sd.stash, placed)
            gview = self._trade_goods_view()
            for i, (iid, _c) in enumerate(self.trade_goods()):
                r = self._trade_cell_rect(i)
                if (iid in ITEMS and gview.contains(r) and r.collidepoint(pos)):
                    it = (Item.weapon(iid) if ITEMS[iid]["cat"] == "weapon"
                          else Item(iid))
                    return it, None
            return None
        placed = self.stash_hit(pos)
        if placed is not None:
            return placed.item, (sd.stash, placed)
        if self.safe_rect().collidepoint(pos):
            placed = self._safe_at(pos)
            if placed is not None:
                return placed.item, (sd.safe, placed)
        brect = self.bag_rect()
        if brect.collidepoint(pos):
            cell = self.bag_cell()
            gx = int((pos[0] - brect.x) // cell)
            gy = int((pos[1] - brect.y) // cell)
            placed = sd.bag.at(gx, gy)
            if placed is not None:
                return placed.item, (sd.bag, placed)
        for name in ("weapon", "armor", "helmet", "pack"):
            it = getattr(sd, name)
            if it is not None and self.lay[name].collidepoint(pos):
                return it, None
        return None

    # ---- 任务中心 ----
    def task_entries(self):
        """当前部门的条目列表(礼品页是自定义版面,不走这里的行列表)。"""
        if self.task_dept == "instructor":
            return [(t, quests.task_state(self.game.save, t)) for t in TASKS]
        if self.task_dept == "contractor":
            return [(t, quests.task_state(self.game.save, t))
                    for t in SAFE_CONTRACT]
        if self.task_dept == "gift":
            return []
        return [(e, ("doing" if not quests.can_barter(self.game.save, e) else "ready"),
                 None, None) for e in quests.barter_list(self.task_dept)]

    # ---- 礼品页:神秘人的收集清单 ----
    def _gift_click(self, pos):
        """礼品页只有一个交互:点交付按钮把清单交给神秘人。"""
        if not self.gift_btn.collidepoint(pos):
            return
        sd = self.game.save
        ok, msg = mystery.turn_in(sd)
        save_mod.save_data(sd)
        self.say(msg, COL["good"] if ok else COL["bad"], 4.0)

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
        if self.task_dept == "gift":
            self._gift_click(pos)
            return
        entries, per = self.task_rows()
        for i, entry in enumerate(entries):
            if not self.task_row_rect(i).collidepoint(pos):
                continue
            if self.task_dept in ("instructor", "contractor"):
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
    def _prewarm_selected_map(self):
        """把当前选中的地图提前画好(只做一次,之后命中缓存直接返回)。

        进战局时 Raid 会把整张地图画一遍(1920×1408,约 150 ms),原来这笔钱
        正好落在"点了开始战局"的那一帧上。放在藏身处(菜单,帧率不敏感)先付掉,
        玩家在地图/模式之间切换也会跟着重新预热。
        每帧只是一次字典查询,代价可以忽略。
        """
        try:
            import world as world_mod
            from maps import MODE_MAP
            sd = self.game.save
            key = (MODE_MAP.get(getattr(sd, "mode", "raid"))
                   or getattr(sd, "map_key", "border"))
            if not world_mod.is_prerendered(key):
                world_mod.prerender_map(key)
        except Exception:
            pass

    # ---------- 局域网联机 ----------
    # 联机内核(net.py / Game.net)只在调用点上依赖:net.py 缺失、Game 上还没挂
    # Net、Net 内部抛异常,都只能在状态行里说一句 —— 单机游戏不能因此崩。
    # 全部延迟 import / getattr,启动路径上一行都不多花。
    def _net(self):
        """取联机对象;拿不到返回 None(由调用方给中文提示)。"""
        n = getattr(self.game, "net", None)
        if n is not None:
            return n
        try:
            import net as net_mod
        except Exception:
            return None
        # net.py 在、只是 Game 上还没挂(并行开发期常见):自己兜一个 Net,
        # 顺手挂回 game,免得每帧新建一个。
        make = getattr(net_mod, "Net", None)
        if not callable(make):
            return None
        try:
            n = make(self.game)
        except Exception:
            return None
        try:
            self.game.net = n
        except Exception:
            pass
        return n

    def _net_status(self, n):
        """状态行文字:直接用 net.status_text() 的返回;读不到给兜底文案。"""
        if n is None:
            if self.net_mod_ok is None:
                try:
                    import net as net_mod       # noqa: F401  只为把提示说准
                    self.net_mod_ok = True
                except Exception:
                    self.net_mod_ok = False
            return ("联机内核没接上:net.py 在,但 Game.net 是空的"
                    if self.net_mod_ok else "联机不可用:缺少 net.py")
        try:
            txt = str(n.status_text() or "").strip()
        except Exception:
            return "联机状态读取失败(联机内核报错)"
        return txt or "联机:空闲"

    def _net_role(self, n):
        """当前角色:None / "host" / "client"(读不到当没联机)。"""
        if n is None:
            return None
        try:
            role = getattr(n, "role", None)
        except Exception:
            return None
        return role if role in ("host", "client") else None

    def _net_host_label(self, host):
        """「房间名 · ip:port」—— 扫描结果里字段缺了也要显示得出来。"""
        if not isinstance(host, dict):
            return str(host)
        name = str(host.get("name") or "未命名房间")
        ip = str(host.get("ip") or "?")
        port = host.get("port")
        return f"{name} · {ip}:{port}" if port else f"{name} · {ip}"

    def _net_host_rects(self):
        """扫描结果的可点击行。绘制与命中共用这一份(画一处点一处是老毛病)。"""
        out = []
        x = self.net_panel.x + 738
        w = max(80, self.net_panel.right - 12 - x)
        y = self.net_panel.y + 6
        for host in self.net_hosts[:3]:
            out.append((host, pygame.Rect(x, y, w, 20)))
            y += 21
        return out

    def _net_scan_begin(self, n):
        """点「搜索并加入」:请求一次扫描,留 2 秒收结果(结果进 found_hosts)。"""
        try:
            n.request_scan()
        except Exception:
            self.say("扫描局域网失败:联机内核报错(看状态行)", COL["bad"], 3.6)
            return
        self.net_hosts = []
        self.net_scan_t = 2.0
        self.say("正在扫描局域网…", COL["accent"], 2.0)

    def _net_poll(self, dt):
        """扫描期间每帧收结果,时间到再决定:1 个直接连 / 多个列出来点。"""
        if self.net_scan_t <= 0:
            return
        n = self._net()
        if n is None:
            self.net_scan_t = 0.0
            return
        try:
            hosts = n.found_hosts() or []
        except Exception:
            hosts = []
        if hosts:
            self.net_hosts = [h for h in hosts if isinstance(h, dict)] or list(hosts)
        self.net_scan_t -= dt
        if self.net_scan_t > 0:
            return
        self.net_scan_t = 0.0
        if not self.net_hosts:
            self.say("没找到房间，确认两台电脑在同一局域网、且房主已点创建房间",
                     COL["bad"], 6.0)
        elif len(self.net_hosts) == 1:
            # 只发现一个:不用再点一下,直接连
            self._net_join(self.net_hosts[0])
        else:
            self.say(f"发现 {len(self.net_hosts)} 个房间,点右边的房间名直接加入",
                     COL["accent"], 5.0)

    def _net_join(self, host):
        """按 ip 连一个房间(host = found_hosts() 里的一项)。"""
        n = self._net()
        if n is None:
            self.say("联机不可用:缺少 net.py / Game.net", COL["bad"], 3.6)
            return
        ip = str(host.get("ip") or "") if isinstance(host, dict) else ""
        try:
            ok = bool(n.join(ip or None))
        except Exception:
            ok = False
        if ok:
            self.say(f"已加入房间「{self._net_host_label(host)}」", COL["good"], 5.0)
        else:
            self.say("加入失败:" + self._net_status(n), COL["bad"], 5.0)

    def _net_join_ip(self):
        """手动 IP:填了就按这个地址连,没填就提示。"""
        ip = self.net_ip.strip()
        self.net_ip_edit = False
        if not ip:
            self.say("还没填 IP:点左边的输入框敲房主地址(例如 192.168.1.5)",
                     COL["bad"], 4.0)
            return
        self._net_join({"ip": ip, "name": ip})

    def _net_host_ready(self):
        """主机且对方已连上 = 可以开局(game.lan_host_ready 没接上就按不能算)。"""
        fn = getattr(self.game, "lan_host_ready", None)
        if not callable(fn):
            return False
        try:
            return bool(fn())
        except Exception:
            return False

    def _net_start(self):
        """「开始联机战局」:只有房主(且对方已连上)能开局,其余人只给提示。"""
        role = self._net_role(self._net())
        if role != "host":
            self.say("等房主开局(自己开房请点「创建房间」)" if role == "client"
                     else "先点「创建房间」当房主,等对方连上再开局",
                     COL["bad"], 4.2)
            return
        start = getattr(self.game, "lan_start_raid", None)
        if not callable(start):
            self.say("联机开局还没接上(game.lan_start_raid 不存在)",
                     COL["bad"], 4.0)
            return
        ok = False
        try:
            ok = bool(start())          # 开局成功后 game 自己切战局,这里不用管
        except Exception:
            ok = False
        if not ok:
            self.say("还没人和你连上：让对方点「搜索并加入」", COL["bad"], 4.6)

    def _net_off(self, n=None):
        """断开:关掉监听 / 连接,顺手清掉扫描状态。"""
        n = n if n is not None else self._net()
        if n is None:
            self.say("联机不可用:缺少 net.py / Game.net", COL["bad"], 3.6)
            return
        try:
            n.close()
        except Exception:
            pass
        self.net_hosts = []
        self.net_scan_t = 0.0
        self.net_ip_edit = False
        self.say("已断开联机", COL["text_dim"], 3.0)

    def _net_click(self, pos):
        """底部联机小节的点击。返回 True = 这次点击已被吃掉。"""
        if self.net_ip_box.collidepoint(pos):
            self.net_ip_edit = True
            audio.play("pickup")
            self.say("输入房主 IP(回车连接 · ESC 取消)", COL["accent"], 4.0)
            return True
        if self.net_ip_go.collidepoint(pos):
            self._net_join_ip()
            return True
        n = self._net()
        if self.net_host_btn.collidepoint(pos):
            if n is None:
                self.say("联机不可用:缺少 net.py / Game.net", COL["bad"], 3.6)
                return True
            try:
                ok = bool(n.host_room())
            except Exception:
                ok = False
            if ok:
                self.say("房间已创建,等对方点「搜索并加入」· " + self._net_status(n),
                         COL["good"], 6.0)
            else:
                self.say("创建房间失败:" + self._net_status(n), COL["bad"], 5.0)
            return True
        if self.net_join_btn.collidepoint(pos):
            if n is None:
                self.say("联机不可用:缺少 net.py / Game.net", COL["bad"], 3.6)
                return True
            self._net_scan_begin(n)
            return True
        if self.net_off_btn.collidepoint(pos):
            self._net_off(n)
            return True
        if self.net_start_btn.collidepoint(pos):
            self._net_start()
            return True
        for host, r in self._net_host_rects():      # 扫描到的房间:点名字直接进
            if r.collidepoint(pos):
                self._net_join(host)
                return True
        return False

    def _net_key(self, ev):
        """手动 IP 输入框吃键盘。返回 True = 这个按键已被吃掉。"""
        if not self.net_ip_edit:
            return False
        if ev.key == pygame.K_ESCAPE:
            self.net_ip_edit = False
            self.say("已取消输入 IP", COL["text_dim"], 2.4)
            return True
        if ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._net_join_ip()
            return True
        if ev.key == pygame.K_BACKSPACE:
            self.net_ip = self.net_ip[:-1]
            return True
        ch = getattr(ev, "unicode", "") or ""
        if ch and (ch.isdigit() or ch in ".:") and len(self.net_ip) < 21:
            self.net_ip += ch
        # 输入期间的其它按键一律吞掉:别让 WASD/ESC 漏给别的界面
        return True

    def _draw_net(self, screen, mx, my):
        """底部「局域网联机」小节:一行状态 + 创建/搜索/断开 + 手动 IP + 房间列表。"""
        r = self.net_panel
        uikit.draw_panel(screen, r, None)
        n = self._net()
        # 标题带上角色(房主 / 客户端),一眼看得出自己是哪边
        role = self._net_role(n)
        tag = {"host": "房主", "client": "客户端"}.get(role, "未联机")
        t = get_font(15, bold=True).render("局域网联机 · " + tag, True, COL["accent"])
        screen.blit(t, (r.x + 18, r.y + 8))
        # 状态行:net.status_text() 原样显示(太长就截断,别顶到右边的房间列表)
        ft = get_font(14)
        txt = self._net_status(n)
        tx = r.x + 24 + t.get_width()
        room = r.x + 700
        if tx + ft.size(txt)[0] > room:
            while txt and tx + ft.size(txt + "…")[0] > room:
                txt = txt[:-1]
            txt += "…"
        screen.blit(ft.render(txt, True,
                              COL["text"] if n is not None else COL["bad"]),
                    (tx, r.y + 9))
        # 三个按钮(沿用这页的老写法:draw_button + small)
        draw_button(screen, self.net_host_btn, "创建房间",
                    self.net_host_btn.collidepoint(mx, my), small=True)
        draw_button(screen, self.net_join_btn, "搜索并加入",
                    self.net_join_btn.collidepoint(mx, my), small=True)
        draw_button(screen, self.net_off_btn, "断开",
                    self.net_off_btn.collidepoint(mx, my), small=True)
        # 可选手动 IP:点框开始输,回车连(输入中框变橙)
        box = self.net_ip_box
        hov = box.collidepoint(mx, my)
        pygame.draw.rect(screen,
                         COL["panel_hi"] if (hov or self.net_ip_edit)
                         else COL["grid_bg"], box, border_radius=6)
        pygame.draw.rect(screen, COL["accent"] if self.net_ip_edit else COL["border"],
                         box, 2 if self.net_ip_edit else 1, border_radius=6)
        if self.net_ip_edit:
            label, col = self.net_ip + "|", COL["text"]
        elif self.net_ip:
            label, col = self.net_ip, COL["text"]
        else:
            label, col = "手动输入 IP", COL["text_dim"]
        it = get_font(14, bold=bool(self.net_ip_edit)).render(label, True, col)
        screen.blit(it, it.get_rect(center=box.center))
        draw_button(screen, self.net_ip_go, "连接",
                    self.net_ip_go.collidepoint(mx, my), small=True)
        # 主机开局:房主且对方已连上才亮(灰着也能点 —— 点了会说明为什么还不能开)
        draw_button(screen, self.net_start_btn, "开始联机战局",
                    self.net_start_btn.collidepoint(mx, my),
                    enabled=self._net_host_ready(), small=True)
        # 扫描到的房间:房间名 + IP,点一下直接加入(最多列 3 个)
        for host, hr in self._net_host_rects():
            hover = hr.collidepoint(mx, my)
            pygame.draw.rect(screen, COL["panel_hi"] if hover else COL["panel"],
                             hr, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if hover else COL["border"], hr,
                             1, border_radius=6)
            ht = get_font(13, bold=hover).render(
                self._net_host_label(host), True,
                COL["accent"] if hover else COL["text"])
            screen.blit(ht, ht.get_rect(midleft=(hr.x + 8, hr.centery)))

    def update(self, dt, events):
        self.msg_t -= dt
        self.reset_armed = max(0.0, self.reset_armed - dt)
        self._prewarm_selected_map()
        self._net_poll(dt)
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
        # 触屏(仓库/交易所):长按弹物品详情;普通点按延迟到抬起判定
        if self.game.save.touch and self.view in ("stash", "trade"):
            events = self._hold_filter(dt, events)
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
                    # 滚轮翻「鼠标压在哪个面板」那一边 —— 左仓库 / 右商品各自独立
                    lp, _rp = self._trade_panels()
                    if lp.collidepoint(pygame.mouse.get_pos()):
                        self.stash_scroll -= ev.y * 40
                        self.stash_scroll = max(0.0, min(
                            self.stash_scroll, self.trade_stash_max_scroll()))
                    else:
                        self.trade_scroll -= ev.y * 48
                        self.trade_scroll = max(
                            0.0, min(self.trade_scroll, self.trade_max_scroll()))
                elif self.view == "stash":
                    self.stash_scroll -= ev.y * 40
                    self.stash_scroll = max(0.0, min(self.stash_scroll,
                                                     self.stash_max_scroll()))
                elif self.view == "task":
                    self.task_scroll -= ev.y * 44
                    self.task_scroll = max(0.0, min(self.task_scroll,
                                                    self.task_max_scroll()))
            elif ev.type == pygame.KEYDOWN:
                if self._net_key(ev):      # 正在手输联机 IP:键盘先归输入框
                    continue
                if ev.key == pygame.K_ESCAPE and self.hold.active():
                    self.hold.hide()
                    continue
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

        # 双人合作开关(同一台电脑两人玩;搜打撤 / 夜战都能开,见 coop.py)
        if self.coop_rect.collidepoint(pos):
            if sd.touch:
                self.say("双人合作要键盘:P2 用方向键操作 —— "
                         "先把「手机模式」关掉", COL["bad"], 3.6)
                return
            if sd.mode not in COOP_MODES:
                self.say("双人合作只在「搜打撤」和「夜战」模式生效(先切过去)",
                         COL["bad"], 3.4)
                return
            sd.coop = not sd.coop
            save_mod.save_data(sd)
            if sd.coop:
                self.say("双人合作已开启 · " + coop_mod.key_hint(), COL["accent"], 6.0)
            else:
                self.say("双人合作已关闭(恢复单人)", COL["text_dim"], 3.2)
            return

        # 局域网联机小节(创建房间 / 搜索并加入 / 断开 / 手动 IP;内核见 net.py)
        if self._net_click(pos):
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
        if lay["supply"].collidepoint(pos) and not loadout_weapons(sd):
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

        # 装备槽:卸下(4 个武器位 + 护甲/头盔/背包)
        for slot in LOADOUT_SLOTS:
            rect = lay["weapon"] if slot == "main1" else lay.get(slot)
            if rect is None or not rect.collidepoint(pos):
                continue
            old = loadout_get(sd, slot)
            if old is not None:
                if sd.stash.add_item(old):
                    loadout_set(sd, slot, None)
                    # main1 卸空后要是有别的武器,把它顶到 main1 —— 否则存档里
                    # 的 weapon 为空,另外两个槽就跟着丢了。
                    if slot == "main1" and sd.weapon is None:
                        rest = [w for s, w in loadout_all(sd).items()
                                if s != "main1" and w is not None]
                        if rest:
                            loadout_set(sd, "main1", rest[0])
                            for s, w in loadout_all(sd).items():
                                if w is rest[0] and s != "main1":
                                    loadout_set(sd, s, None)
                    save_mod.save_data(sd)
                    self.say(f"已卸下 {old.name}")
                else:
                    self.say("仓库空间不足", COL["bad"])
            return
        if lay["armor"].collidepoint(pos):
            if sd.armor is not None:
                # 手里正拿着的枪需要护甲 -> 不能脱(备用的枪不影响换甲)
                cur = sd.weapon
                if cur is not None and not armor_allows(None, cur.def_):
                    self.say(f"手里的 {cur.name} 需要 {cur.def_['req_armor_level']} "
                             f"级护甲,先换上别的枪再脱甲", COL["bad"], 3.2)
                    return
                # 备用位上还压着重武器 -> 提醒,但仍允许脱甲(它可以留在包里不拿)
                heavy = next((w for w in loadout_weapons(sd)
                              if w.def_.get("req_armor_level", 0)
                              > (sd.armor.def_.get("level", 0))), None)
                old = sd.armor
                if sd.stash.add_item(old):
                    sd.armor = None
                    save_mod.save_data(sd)
                    if heavy is not None:
                        self.say(f"已脱下 {old.name};{heavy.name} 需要 "
                                 f"{heavy.def_['req_armor_level']} 级护甲,"
                                 f"拿它之前先穿回甲", COL["accent"], 3.4)
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

        # 保险箱:存入开关 / 点物品取回仓库
        if self.safe_toggle.collidepoint(pos):
            self.safe_in = not self.safe_in
            self.say("存入模式已开启:点仓库里的物品就会放进保险箱(阵亡不丢)"
                     if self.safe_in else
                     "存入模式已关闭(恢复:点物品=装备/放背包)", COL["accent"], 3.2)
            return
        if self.safe_rect().collidepoint(pos):
            placed = self._safe_at(pos)
            if placed is not None:
                if try_move(sd.safe, placed, sd.stash):
                    save_mod.save_data(sd)
                    self.say(f"{placed.item.name} 已从保险箱取出")
                else:
                    self.say("仓库空间不足", COL["bad"])
            return

        # 仓库物品 -> 装备/出战背包
        if lay["stash_panel"].collidepoint(pos):
            placed = self.stash_hit(pos)
            if placed is not None:
                item = placed.item
                if self.safe_in:
                    if try_move(sd.stash, placed, sd.safe):
                        save_mod.save_data(sd)
                        self.say(f"{item.name} 已存入保险箱(阵亡不丢)")
                    else:
                        self.say("保险箱放不下(40 个承包商任务完成后扩为 4 格)",
                                 COL["bad"], 3.2)
                    return
                if item.cat == "weapon":
                    if not armor_allows(sd.armor, item.def_):
                        self.say(f"需先穿上 {item.def_['req_armor_level']} 级护甲,"
                                 f"才拿得动 {item.name}", COL["bad"], 3.2)
                        return
                    free = loadout_free_slot(sd, item)
                    if free is None:
                        self.say("武器位满了(2 主武器 + 副武器 + 近战),"
                                 "先卸下一件再拿", COL["bad"], 3.2)
                        return
                    sd.stash.remove_placed(placed)
                    loadout_set(sd, free, item)
                    save_mod.save_data(sd)
                    self.say(f"装备武器 {item.name} → {LOADOUT_SLOT_NAMES[free]}")
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
        """交易所点击:返回 / 滚动条 / 确认框 / 批量出售按钮 / 仓库物品 / 购买。

        一页式,顺序照「确认框 → 按钮 → 分区标签 → 仓库 → 商品」来:
        点仓库里的东西 = 出售(批量模式 = 选中/取消),点商品格 = 购买。
        """
        sd = self.game.save
        audio.play("click")

        # 顶栏:返回
        if self.trade_close.collidepoint(pos):
            self.view = "stash"
            self.sell_mode = False
            self.sell_sel = []
            save_mod.save_data(sd)
            return

        # 商品滚动条优先(否则点轨道会误触商品格)
        if self.trade_slider is not None:
            track, handle = self.trade_slider
            if handle.collidepoint(pos):
                self.trade_drag = True
                return
            if track.collidepoint(pos):
                self.trade_drag = True
                self._trade_drag_to(pos[1])
                return

        # 批量出售的确认框最优先(没确认完不能点别的)
        if self.sell_ask is not None:
            if self.sell_ask_yes.collidepoint(pos):
                ok, msg = self._sell_do()
                self.say(msg, COL["good"] if ok else COL["bad"], 3.4)
            elif self.sell_ask_no.collidepoint(pos):
                self.sell_ask = None
                self.say("已取消批量出售", COL["text_dim"])
            return

        if self._trade_click_sell(pos):        # 批量出售按钮 / 点仓库物品
            return
        self._trade_click_buy(pos)             # 分区标签 / 点商品购买

    def _trade_click_buy(self, pos):
        """购买侧:点分区标签选分区,点商品格买。"""
        sd = self.game.save
        # 分区标签
        for label, cat, r in self._trade_cat_rows():
            if r.collidepoint(pos):
                self.trade_cat = cat
                self.trade_scroll = 0.0          # 换分区回到顶部
                return
        # 商品格
        view = self._trade_goods_view()
        goods = self.trade_goods()
        for i, (iid, count) in enumerate(goods):
            r = self._trade_cell_rect(i)
            if not r.collidepoint(pos):
                continue
            # 被裁掉一半的格子不接受点击(否则会点在看不见的格子上)
            if not view.contains(r):
                continue
            price = trade_buy_price(iid, count)
            if sd.rubles < price:
                self.say("余额不足!", COL["bad"])
                return
            d = ITEMS[iid]
            item = (Item.weapon(iid, mag=d["mag"]) if d["cat"] == "weapon"
                    else Item(iid, count=count))
            if not sd.stash.add_item(item):
                self.say("仓库空间不足!", COL["bad"])
                return
            sd.rubles -= price
            save_mod.save_data(sd)
            self.say(f"购买 {item.name} -{fmt_rub(price)}", COL["accent"])
            return

    def _trade_click_sell(self, pos):
        """出售侧:批量出售按钮 + 点仓库物品。返回 True = 这次点击已处理。"""
        sd = self.game.save
        if self.sell_toggle.collidepoint(pos):
            self.sell_mode = not self.sell_mode
            if not self.sell_mode:
                self.sell_sel = []
            self.say("批量出售:开(左键点物品选中/取消)" if self.sell_mode
                     else "批量出售:关(左键点物品直接卖)", COL["accent"], 2.6)
            return True
        if self.sell_mode:
            if self.sell_junk.collidepoint(pos):
                n = self._sell_pick(("misc",))
                self.say(f"已选中 {n} 件杂物" if n else "仓库里没有杂物",
                         COL["accent"], 2.4)
                return True
            if self.sell_ammo.collidepoint(pos):
                n = self._sell_pick(("ammo",))
                self.say(f"已选中 {n} 组子弹" if self.sell_selected()
                         else f"已取消 {n} 组子弹", COL["accent"], 2.4)
                return True
            if self.sell_clear.collidepoint(pos):
                self.sell_sel = []
                self.say("已清空选择", COL["text_dim"], 2.0)
                return True
            if self.sell_go.collidepoint(pos):
                sel = self.sell_selected()
                if not sel:
                    self.say("先在左边点选要卖的物品(或点快捷选择)",
                             COL["bad"], 3.0)
                    return True
                self.sell_ask = dict(items=list(sel), total=self.sell_total())
                return True
        # 仓库物品:批量模式下 = 选中/取消;普通模式 = 直接卖掉
        placed = self.trade_stash_hit(pos)
        if placed is None:
            return False
        if self.sell_mode:
            sel = self.sell_selected()
            if placed in sel:
                sel.remove(placed)
            else:
                sel.append(placed)
            self.sell_sel = sel
            return True
        price = trade_sell_price(placed.item)
        name = placed.item.name
        sd.stash.remove_placed(placed)
        sd.rubles += price
        save_mod.save_data(sd)
        self.say(f"出售 {name} +{fmt_rub(price)}", COL["good"])
        return True

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
                            self.stash_grid[1] + self.stash_view_h + 4))
        self._draw_scroll_buttons(screen, [("stash", 0)])

        # ---- 保险箱条(阵亡不丢;40 个承包商任务升 4 格) ----
        sr = self.safe_rect()
        draw_grid(screen, sr.x, sr.y, sd.safe, self.safe_cell,
                  title=None)
        up = quests.safe_upgraded(sd)
        t = get_font(14, bold=True).render(
            f"保险箱 {sd.safe.w}×{sd.safe.h}(阵亡不丢)", True,
            COL["good"] if up else COL["accent"])
        screen.blit(t, (sr.right + 10, sr.y + 1))
        sub = ("已升级 4 格:承包商 40 项全部完成!" if up else
               f"承包商任务 {quests.safe_done_count(sd)}/40 → 全完成扩为 4 格")
        t = get_font(12).render(sub, True, COL["text_dim"])
        screen.blit(t, (sr.right + 10, sr.y + 20))
        draw_button(screen, self.safe_toggle,
                    "存入:开" if self.safe_in else "存入:关",
                    hover=self.safe_toggle.collidepoint(mx, my), small=True)

        # ---- 出战配置 ----
        uikit.draw_panel(screen, lay["loadout_panel"], "出战配置")
        draw_button(screen, lay["stash_all"], "一键放回仓库并整理",
                    lay["stash_all"].collidepoint(mx, my), small=True)
        for slot in LOADOUT_SLOTS:
            r = lay["weapon"] if slot == "main1" else lay[slot]
            it = loadout_get(sd, slot)
            draw_slot(screen, r, it,
                      LOADOUT_SLOT_NAMES[slot] if it is not None
                      else LOADOUT_SLOT_NAMES[slot] + "(空)",
                      hover=r.collidepoint(mx, my))
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
        # 双人合作开关(放在标题右侧;只对搜打撤生效)
        coop_on = bool(getattr(sd, "coop", False))
        cbtn = self.coop_rect
        chov = cbtn.collidepoint(mx, my)
        pygame.draw.rect(screen, COL["panel_hi"] if chov else COL["panel"], cbtn,
                         border_radius=6)
        pygame.draw.rect(screen, COL["accent"] if coop_on else COL["border"], cbtn,
                         2 if coop_on else 1, border_radius=6)
        ct = get_font(13, bold=True).render(
            "双人合作:开" if coop_on else "双人合作:关", True,
            COL["accent"] if coop_on else COL["text_dim"])
        screen.blit(ct, ct.get_rect(center=cbtn.center))
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
            ("★ 双人合作已开:搜打撤 / 夜战生效(P2 方向键 + 右Shift)"
             if coop_on else ""),
            f"{move_txt} · 左键射击 · 右键架枪",
            f"弹匣空自动换弹 · {hr} 打药 · {kl} 搜刮/救人",
            f"{hb} 背包 · 死亡会丢装备(保险箱除外)",
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
        if mystery.ready(sd):          # 神秘人的货也算"有东西可交"
            ready_n += 1
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

        # ---- 局域网联机(底部空带:状态 + 创建/搜索/断开 + 手动 IP + 房间列表) ----
        self._draw_net(screen, mx, my)

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
        if hover_item is None:
            for slot in LOADOUT_SLOTS:
                r = lay["weapon"] if slot == "main1" else lay[slot]
                it = loadout_get(sd, slot)
                if it is not None and r.collidepoint(mx, my):
                    hover_item = it
                    break
        if hover_item is None and lay["armor"].collidepoint(mx, my) and sd.armor:
            hover_item = sd.armor
        if hover_item is None and lay["helmet"].collidepoint(mx, my) and sd.helmet:
            hover_item = sd.helmet
        if hover_item is None and lay["pack"].collidepoint(mx, my) and sd.pack:
            hover_item = sd.pack
        if hover_item is not None:
            draw_tooltip(screen, mx, my, hover_item)

        # ---- 触屏长按信息面板(最上层) ----
        uikit.draw_hold(screen, self.hold)

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
                         "部门 — 教官/承包商发任务,医疗/后勤/礼品用材料交货换东西")
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
            elif key == "contractor":
                label = f"{label} {quests.safe_done_count(sd)}/{len(SAFE_CONTRACT)}"
            elif key == "gift":
                label = f"{label} ★{MYSTERY_STARS}"
            ft = get_font(16, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))
        if self.task_dept == "gift":
            self._draw_gift(screen, mx, my)
            return
        hint = ("左键:领取奖励 · 全部 40 项完成解锁 4 格保险箱"
                if self.task_dept == "contractor"
                else "左键:领取奖励" if self.task_dept == "instructor"
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
            if self.task_dept in ("instructor", "contractor"):
                task, (state, p, need) = entry
                done = state == "done"
                ready = state == "ready"
                locked = state == "locked"
                name = f"{task['name']}  ({min(p, need)}/{need})"
                if task.get("repeat"):
                    name += "  [可重复]"
                pre = quests.task_by_id(task.get("req") or "") if locked else None
                right = ("已结算" if done else
                         ("未解锁" if locked else
                          ("点击领取" if ready else "进行中")))
                sub = f"{task['desc']}   奖励:{quests.reward_text(task['reward'])}"
                if locked:
                    sub = (f"需先完成并领取「{pre['name'] if pre else task.get('req')}」"
                           f"   奖励:{quests.reward_text(task['reward'])}")
                col = (COL["good"] if ready else
                       (COL["text_dim"] if (done or locked) else COL["text"]))
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

    def _draw_gift(self, screen, mx, my):
        """礼品页:神秘人的收集清单(10 星)+ 交付按钮。"""
        sd = self.game.save
        pan = self.lay["trade_goods"]
        need = mystery.need_list(sd)
        miss = mystery.missing(sd)
        ok_n, total = mystery.prepared_count(sd)
        done = mystery.claimed(sd)

        t = get_font(19, bold=True).render("神秘人 —— 长线收集委托", True, COL["accent"])
        screen.blit(t, (pan.x + 16, 184))
        st = get_font(15, bold=True).render("难度 " + "★" * MYSTERY_STARS
                                            + f"({MYSTERY_STARS} 星)", True, (240, 200, 90))
        screen.blit(st, (pan.x + 24 + t.get_width(), 188))
        t = get_font(13).render(
            f"第 {mystery.round_no(sd)} 轮 · 他每次启动游戏都换一批货"
            "(清单看的是仓库+背包里有没有,刷新不会让你白攒)", True, COL["text_dim"])
        screen.blit(t, (pan.x + 16, 212))
        t = get_font(13).render(
            f"交货可得:{mystery.reward_text()}(每包一整套满配装备)"
            " · 极小概率额外塞你一张机密文件(概率与强化封锁爆率相同)",
            True, COL["good"])
        screen.blit(t, (pan.x + 16, 232))

        # 清单:两列摆放(每列最多 7 行)
        col_w, row_h = 344, 30
        for i, (iid, n) in enumerate(need):
            cx = pan.x + 16 + (i % 2) * (col_w + 10)
            cy = 266 + (i // 2) * row_h
            have = quests.have_count(sd, iid)
            good = have >= n
            nm = ITEMS[iid]["name"]
            t = get_font(15).render(nm, True, COL["text"] if good else COL["text_dim"])
            screen.blit(t, (cx, cy))
            t2 = get_font(15, bold=True).render(
                f"{min(have, n)}/{n}", True, COL["good"] if good else COL["bad"])
            screen.blit(t2, (cx + col_w - 20 - t2.get_width(), cy))
            pygame.draw.rect(screen,
                             COL["good"] if good else COL["border"],
                             (cx - 10, cy + 7, 5, 5), border_radius=2)

        if not need:
            t = get_font(16).render("他还没给你清单(重开一次游戏就会刷新)",
                                    True, COL["bad"])
            screen.blit(t, (pan.x + 16, 266))
        state_txt = ("本轮已交付 —— 下次启动游戏他会给你新的清单(全装包在仓库里)"
                     if done else
                     (f"还差 {len(miss)} 种材料" if miss else "清单齐了,可以交货"))
        state_col = COL["text_dim"] if done else (COL["bad"] if miss else COL["good"])
        t = get_font(15, bold=True).render(
            f"已备齐 {ok_n}/{total} 种 · {state_txt}", True, state_col)
        screen.blit(t, (pan.x + 16, 494))

        # 6 套全装包分别是哪 6 套
        names = [ITEMS[k]["name"].replace("全装包 · ", "") for k in MYSTERY_KITS]
        rows = [f"{mystery.reward_text()}:", " / ".join(names[:3]),
                " / ".join(names[3:])]
        yy = 520
        for i, ln in enumerate(rows):
            t = get_font(13, bold=(i == 0)).render(ln, True,
                                                   COL["text"] if i == 0 else COL["text_dim"])
            screen.blit(t, (pan.x + 16, yy))
            yy += 18

        ready = mystery.ready(sd)
        label = ("这一轮已经交过了" if done else
                 (f"交付(还差 {len(miss)} 种)" if miss
                  else f"全部交给他 —— 换 {mystery.reward_text()}"))
        draw_button(screen, self.gift_btn, label,
                    self.gift_btn.collidepoint(mx, my), enabled=ready)
        t = get_font(13).render(
            "全装包是 2×2 物品:电脑右键 / 手机长按面板点「打开」→ 展开成一整套装备",
            True, COL["text_dim"])
        screen.blit(t, (pan.x + 16, pan.bottom - 26))

    # ---------- 交易所渲染 ----------
    def _draw_trade(self, screen):
        """交易所:左边你的仓库(点物品出售 / 批量出售),右边分区标签 + 商品。

        一页式:左面板点仓库物品 = 卖(批量模式 = 选中/取消),右面板点商品 = 买。
        分区标签横排在右面板顶上,以后往 TRADE_TABS / TRADE_GOODS 里加东西,
        标签宽度和商品网格自动适应,不用再算坐标。
        """
        sd = self.game.save
        mx, my = pygame.mouse.get_pos()
        screen.fill(COL["bg"])
        left_p, right_p = self._trade_panels()

        # ---- 顶栏:标题 / 余额 / 返回 ----
        t = get_font(34, bold=True).render("交易所", True, COL["accent"])
        screen.blit(t, (30, 22))
        bal = get_font(24, bold=True).render(f"余额 {fmt_rub(sd.rubles)}",
                                             True, COL["accent"])
        screen.blit(bal, (self.trade_close.x - bal.get_width() - 24, 32))
        draw_button(screen, self.trade_close, "返回",
                    self.trade_close.collidepoint(mx, my))

        # ---- 左:你的仓库;右:分区标签 + 商品网格 ----
        self._draw_trade_sell(screen, mx, my, left_p, right_p)
        self._draw_trade_buy(screen, mx, my, left_p, right_p)

        # ---- 触屏长按信息面板 ----
        uikit.draw_hold(screen, self.hold)
        if self.sell_ask is not None:
            self._draw_sell_ask(screen)

    def _draw_vscroll(self, screen, track, scroll, maxs, content_h):
        """竖直滚动条;放得下就不画。返回 (轨道, 手柄) 供拖动判定。"""
        if maxs <= 0:
            return None
        pygame.draw.rect(screen, (26, 29, 35), track, border_radius=5)
        hh = max(30, int(track.h * min(1.0, track.h / float(max(1, content_h)))))
        span = track.h - hh
        pos = int((scroll / maxs) * span) if maxs > 0 and span > 0 else 0
        handle = pygame.Rect(track.x, track.y + pos, track.w, hh)
        pygame.draw.rect(screen, COL["accent"], handle, border_radius=5)
        return track, handle

    def _draw_trade_buy(self, screen, mx, my, left_p, right_p):
        """购买侧:右面板顶上横排分区标签,下面是商品网格(可滚)。"""
        sd = self.game.save

        # ---- 分区标签 ----
        uikit.draw_panel(screen, right_p, "商品 — 点击购买")
        for label, cat, r in self._trade_cat_rows():
            sel = self.trade_cat == cat
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen, COL["panel_hi"] if (hover or sel)
                             else COL["panel"], r, border_radius=7)
            pygame.draw.rect(screen, COL["accent"] if sel else COL["border"],
                             r, 2 if sel else 1, border_radius=7)
            ft = get_font(14, bold=True).render(
                label, True, COL["accent"] if sel else COL["text"])
            screen.blit(ft, ft.get_rect(center=r.center))

        # ---- 商品网格 ----
        goods = self.trade_goods()
        view = self._trade_goods_view()
        screen.set_clip(view)             # 滚到一半的格子不许画到面板标题上
        for i, (iid, count) in enumerate(goods):
            r = self._trade_cell_rect(i)
            if r.bottom <= view.y or r.top >= view.bottom:
                continue                      # 完全在可见区外,连画都不画
            d = ITEMS[iid]
            price = trade_buy_price(iid, count)
            afford = sd.rubles >= price
            inside = view.contains(r)         # 被裁掉一半的格子不接受点击
            hover = inside and r.collidepoint(mx, my)
            pygame.draw.rect(screen, COL["panel_hi"] if (hover and afford)
                             else COL["panel"], r, border_radius=6)
            pygame.draw.rect(screen,
                             COL["accent"] if (hover and afford) else COL["border"],
                             r, 2 if (hover and afford) else 1, border_radius=6)
            pygame.draw.rect(screen, d["color"], (r.x + 8, r.y + 9, 8, 24),
                             border_radius=2)
            name = d["name"] + (f" ×{count}" if d["cat"] == "ammo" else "")
            nt = get_font(15, bold=True).render(
                name, True, COL["text"] if afford else (108, 108, 114))
            screen.blit(nt, (r.x + 24, r.y + 9))
            cls = weapon_class(iid)
            if cls:
                sub = get_font(12).render(cls, True, COL["text_dim"])
                screen.blit(sub, (r.x + 24, r.y + 32))
            pt = get_font(14, bold=True).render(
                fmt_rub(price), True, COL["accent"] if afford else COL["bad"])
            screen.blit(pt, (r.right - pt.get_width() - 10, r.bottom - 24))
        screen.set_clip(None)
        rows = (len(goods) + self.TRADE_COLS - 1) // self.TRADE_COLS
        self.trade_slider = self._draw_vscroll(
            screen, self.trade_slider_track(), self.trade_scroll,
            self.trade_max_scroll(),
            rows * (self.TRADE_CELL_H + self.TRADE_PAD))
        tip = get_font(13).render(
            "本类共 %d 件 · 左键购买 · 滚轮 / 拖右边条翻看" % len(goods),
            True, COL["text_dim"])
        screen.blit(tip, (right_p.x + 14, right_p.bottom - 16))

        # 悬停提示
        for i, (iid, count) in enumerate(goods):
            r = self._trade_cell_rect(i)
            if view.contains(r) and r.collidepoint(mx, my):
                d = ITEMS[iid]
                preview = (Item.weapon(iid, mag=d["mag"]) if d["cat"] == "weapon"
                           else Item(iid, count=count))
                draw_tooltip(screen, mx, my, preview)
                break

    def _draw_trade_sell(self, screen, mx, my, left_p, right_p):
        """出售侧:左面板 = 你的仓库(点物品直接卖 / 批量模式选中),下面是出售按钮。"""
        sd = self.game.save
        sel = self.sell_selected()
        uikit.draw_panel(screen, left_p,
                         "你的仓库 — 点物品选中(批量出售)" if self.sell_mode
                         else "你的仓库 — 点击物品出售")
        ox, oy = self.trade_stash_grid
        draw_grid(screen, ox, oy, sd.stash, 40,
                  scroll=self.stash_scroll, view_h=self.trade_stash_view_h)
        if self.sell_mode:
            for p in sel:
                w, h = p.item.size()
                r = pygame.Rect(ox + p.x * 40,
                                oy + p.y * 40 - int(self.stash_scroll),
                                w * 40, h * 40)
                if r.bottom < oy or r.top > oy + self.trade_stash_view_h:
                    continue
                hl = _overlay("sell_hl", r.size, (120, 220, 120, 80))
                screen.blit(hl, r)
                pygame.draw.rect(screen, COL["good"], r, 3)
        t = get_font(13).render(
            ("批量出售:左键点物品 选中/取消 · 回收价 60%" if self.sell_mode
             else "出售价 = 原价 60%,卖错了只能高价买回")
            + ("  (滚轮翻仓库)" if self.trade_stash_max_scroll() > 0 else ""),
            True, COL["text_dim"])
        screen.blit(t, (ox, oy + self.trade_stash_view_h + 10))
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
                        else "出售选中(先点左边物品)",
                        self.sell_go.collidepoint(mx, my) and n > 0, small=True)
            if n:
                draw_button(screen, self.sell_clear, f"清空选择({n})",
                            self.sell_clear.collidepoint(mx, my), small=True)
        # 悬停提示
        if left_p.collidepoint(mx, my):
            placed = self.trade_stash_hit((mx, my))
            if placed:
                draw_tooltip(screen, mx, my, placed.item)
