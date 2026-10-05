# -*- coding: utf-8 -*-
"""手机(触屏)操作层:左半屏虚拟摇杆移动 + 右侧按钮,配合自动锁敌。

同时接受 FINGER*(真触屏,可多指)与鼠标事件(电脑上也能用手机模式测试)。
按钮位置支持玩家自定义(sd.touch_layout,在藏身处「设置-触屏」里拖拽调整),
覆盖数据是 [x比例, y比例, 半径]。
"""
import math

import pygame

from settings import W, H, TOUCH, COL, get_font

BUTTONS = [
    # (按键名, 显示文字, 屏幕坐标比例(x, y), 半径)
    ("fire", "开火", (0.915, 0.80), 66),
    ("brace", "架枪", (0.795, 0.90), 48),
    ("reload", "装填", (0.665, 0.905), 42),
    # 射击模式:按钮文字每帧由 Raid 更新成当前模式(单发/三连发/全自动)
    ("mode", "模式", (0.72, 0.72), 40),
    ("heal", "打药", (0.915, 0.615), 42),
    ("loot", "搜刮", (0.835, 0.50), 42),
    ("bag", "背包", (0.955, 0.44), 40),
    ("menu", "菜单", (0.955, 0.07), 30),
]

# 突袭模式追加:友军支援快捷按钮(1 空袭 / 2 炮火覆盖 / 3 无人机侦察)
SUPPORT_BUTTONS = [
    ("sup1", "空袭", (0.575, 0.40), 34),
    ("sup2", "炮火", (0.655, 0.315), 34),
    ("sup3", "侦察", (0.735, 0.245), 34),
]

# 玩家自定义布局(设置页编辑;Raid 启动时从存档 apply_layout 进来)
_layout_overrides = {}


def apply_layout(ov):
    """应用玩家自定义布局(sd.touch_layout)。非法条目直接忽略。"""
    global _layout_overrides
    clean = {}
    if isinstance(ov, dict):
        for name, v in ov.items():
            try:
                rx, ry, r = float(v[0]), float(v[1]), float(v[2])
            except (TypeError, ValueError, IndexError):
                continue
            if 0.0 <= rx <= 1.0 and 0.0 <= ry <= 1.0 and 18 <= r <= 120:
                clean[str(name)] = (rx, ry, int(r))
    _layout_overrides = clean


def layout_overrides():
    return _layout_overrides


# 触屏事件类型(不同版本暴露的常量不一样:pygame 有 FINGERDOWN/MOTION/UP,
# SDL 的 FINGERCANCEL 不一定有 —— 直接写 pygame.FINGERCANCEL 会 AttributeError)
FINGER_EVENTS = tuple(
    getattr(pygame, name) for name in
    ("FINGERDOWN", "FINGERMOTION", "FINGERUP", "FINGERCANCEL")
    if hasattr(pygame, name))


def merged_layout(support=False):
    """默认布局 + 玩家覆盖 -> {name: dict(label, pos, r)}(设置页编辑器也用它)。"""
    src = BUTTONS + SUPPORT_BUTTONS if support else BUTTONS
    out = {}
    for name, label, (rx, ry), r in src:
        ov = _layout_overrides.get(name)
        if ov is not None:
            rx, ry, r = ov
        out[name] = dict(label=label, pos=(int(W * rx), int(H * ry)), r=r)
    return out


def hit_test(pos, support=False):
    """屏幕坐标 -> 按钮名(编辑器与 TouchUI 共用的命中判定)。"""
    for name, d in merged_layout(support).items():
        if math.hypot(pos[0] - d["pos"][0], pos[1] - d["pos"][1]) <= d["r"]:
            return name
    return None


# 按钮贴图缓存:底色/描边/文字都不依赖每帧状态,只有 (文字, 半径, 按下) 三种变化
_button_cache = {}


def _button_sprite(label, r, down):
    key = (label, r, bool(down))
    s = _button_cache.get(key)
    if s is None:
        d = r * 2 + 8
        s = pygame.Surface((d, d), pygame.SRCALPHA)
        base = (72, 92, 120) if down else (40, 46, 58)
        border = COL["accent"] if down else (96, 104, 118)
        pygame.draw.circle(s, base, (d // 2, d // 2), r)
        pygame.draw.circle(s, border, (d // 2, d // 2), r, 3)
        t = get_font(16, bold=True).render(label, True, COL["text"])
        s.blit(t, t.get_rect(center=(d // 2, d // 2)))
        if len(_button_cache) > 160:
            _button_cache.clear()
        _button_cache[key] = s
    return s


class TouchUI:
    """触屏输入状态机:摇杆 + 按钮(支持多指同时操作)。"""

    def __init__(self, support=False):
        self.touches = {}        # id -> (x, y)
        self.stick_id = None
        self.stick_base = (0, 0)
        self.stick_vec = (0.0, 0.0)
        self.pressed = {}        # id -> button name
        self.just_pressed = []   # 本帧新按下的按钮名(供点射用)
        self.support = support   # 是否显示友军支援按钮(突袭模式)
        self.mode_label = "模式"  # 「模式」按钮上的文字:当前射击模式(Raid 每帧刷新)

    # ---------- 几何 ----------
    def buttons(self):
        return BUTTONS + SUPPORT_BUTTONS if self.support else BUTTONS

    def button_layout(self):
        return merged_layout(self.support)

    def _hit_button(self, pos):
        return hit_test(pos, self.support)

    # ---------- 事件 ----------
    def handle_event(self, ev):
        """返回 True 表示这次触屏已被界面消费(不应再当作世界点击)。"""
        if ev.type == pygame.FINGERDOWN:
            return self._press(ev.finger_id, (ev.x * W, ev.y * H))
        if ev.type == pygame.FINGERMOTION:
            self._move(ev.finger_id, (ev.x * W, ev.y * H))
            return True
        if ev.type == pygame.FINGERUP:
            self._release(ev.finger_id)
            return True
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            return self._press("mouse", ev.pos)
        if ev.type == pygame.MOUSEMOTION:
            self._move("mouse", ev.pos)
            return "mouse" in self.touches
        if ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
            consumed = "mouse" in self.touches
            self._release("mouse")
            return consumed
        return False

    def _press(self, tid, pos):
        self.touches[tid] = pos
        btn = self._hit_button(pos)
        if btn is not None:
            self.pressed[tid] = btn
            self.just_pressed.append(btn)
            return True
        if pos[0] < W * TOUCH["stick_zone"]:
            # 左半屏:拖动 = 移动
            self.stick_id = tid
            self.stick_base = pos
            self.stick_vec = (0.0, 0.0)
            return True
        return False

    def _move(self, tid, pos):
        if tid not in self.touches:
            return
        self.touches[tid] = pos
        if tid == self.stick_id:
            dx = pos[0] - self.stick_base[0]
            dy = pos[1] - self.stick_base[1]
            dist = math.hypot(dx, dy)
            if dist > 1:
                k = min(1.0, dist / TOUCH["stick_radius"])
                self.stick_vec = (dx / dist * k, dy / dist * k)

    def _release(self, tid):
        self.touches.pop(tid, None)
        self.pressed.pop(tid, None)
        if tid == self.stick_id:
            self.stick_id = None
            self.stick_vec = (0.0, 0.0)

    def reset_hold(self):
        """清掉「按住」类状态(摇杆 + 按住的按钮),但保留本帧的点按队列。

        打开背包/暂停等界面弹窗时调用:弹窗期间 FINGER 事件不再喂给 TouchUI,
        手指抬起收不到,残留的「按住开火」会在关掉弹窗后继续开火。
        """
        if self.touches or self.pressed or self.stick_id is not None:
            self.touches.clear()
            self.pressed.clear()
            self.stick_id = None
            self.stick_vec = (0.0, 0.0)

    def reset(self):
        """清空全部触摸状态(含本帧点按队列)。"""
        self.reset_hold()
        self.just_pressed = []

    # ---------- 查询 ----------
    def hold(self, name):
        return any(v == name for v in self.pressed.values())

    def take_taps(self):
        """取出本帧新按下的按钮(用于点射/开关类操作),并清空。"""
        out = self.just_pressed
        self.just_pressed = []
        return out

    def active(self):
        return bool(self.touches) or self.stick_id is not None

    def move_axis(self):
        """移动方向(已归一化,带力度)。"""
        mx, my = self.stick_vec
        if mx == 0 and my == 0:
            return 0.0, 0.0
        length = math.hypot(mx, my)
        return mx / length * min(1.0, length), my / length * min(1.0, length)

    # ---------- 绘制 ----------
    def draw(self, screen):
        # 摇杆
        if self.stick_id is not None:
            bx, by = self.stick_base
            pygame.draw.circle(screen, (60, 66, 78), (int(bx), int(by)),
                               TOUCH["stick_radius"], 3)
            dx = self.stick_vec[0] * TOUCH["stick_radius"]
            dy = self.stick_vec[1] * TOUCH["stick_radius"]
            pygame.draw.circle(screen, (150, 170, 200), (int(bx + dx), int(by + dy)), 26)
        else:
            bx, by = int(W * 0.22), int(H * 0.76)
            pygame.draw.circle(screen, (48, 52, 62), (bx, by), TOUCH["stick_radius"], 2)
            pygame.draw.circle(screen, (70, 76, 90), (bx, by), 26, 2)
            t = get_font(14).render("拖动移动", True, (120, 128, 140))
            screen.blit(t, t.get_rect(center=(bx, by + TOUCH["stick_radius"] + 16)))
        # 按钮:整块按钮(底圆 + 描边 + 文字)预渲染成贴图,每帧只 blit 一次。
        # 原来是每帧每个按钮 2 次 circle + 1 次文字 blit(手机 8 个按钮就是 24 次)。
        for name, d in self.button_layout().items():
            label = self.mode_label if name == "mode" else d["label"]
            s = _button_sprite(label, d["r"], self.hold(name))
            screen.blit(s, (d["pos"][0] - s.get_width() // 2,
                            d["pos"][1] - s.get_height() // 2))
