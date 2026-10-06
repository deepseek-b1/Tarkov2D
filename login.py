# -*- coding: utf-8 -*-
"""启动登录界面:输入「名字 + 密码」进入自己的存档。

一个名字 = 一份独立存档(accounts.py);密码只用来校验身份,不存明文。
电脑上可以直接打字,也可以用屏幕键盘点(手机/触屏必用屏幕键盘)。
"""
import asyncio

import pygame

import accounts
import audio
import uikit
from settings import W, H, COL, get_font

# 屏幕键盘布局:(显示, 值, 宽度倍数)—— 值 "caps" / "back" / "clear" 是功能键
_ROW0 = [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"), ("5", "5"),
         ("6", "6"), ("7", "7"), ("8", "8"), ("9", "9"), ("0", "0")]
_ROW1 = [(c, c) for c in "qwertyuiop"]
_ROW2 = [(c, c) for c in "asdfghjkl"]
_ROW3 = [(c, c) for c in "zxcvbnm"] + [("大写", "caps", 1.5), ("退格", "back", 1.5)]

KEY_W, KEY_H, KEY_GAP = 72, 40, 6
KEY_SETS = [_ROW0, _ROW1, _ROW2, _ROW3]
NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")


def _panel():
    return pygame.Rect(60, 140, 380, 320)


def _field_rects():
    return dict(
        name=pygame.Rect(470, 174, 740, 44),
        pw=pygame.Rect(470, 258, 740, 44),
        pw2=pygame.Rect(470, 342, 740, 44),
    )


def _key_rects():
    """屏幕键盘每一行的按键命中区(每帧算一次,布局常量)。"""
    out = []
    for ri, row in enumerate(KEY_SETS):
        wsum = sum(KEY_W * (v[2] if len(v) > 2 else 1) for v in row) \
            + KEY_GAP * (len(row) - 1)
        x = (W - wsum) // 2
        y = 462 + ri * 44
        for v in row:
            w = KEY_W * (v[2] if len(v) > 2 else 1)
            out.append((pygame.Rect(x, y, int(w), KEY_H), v))
            x += int(w) + KEY_GAP
    return out


class LoginScreen:
    def __init__(self):
        self.names = accounts.list_names()
        self.name = accounts.last_name() if accounts.last_name() else ""
        self.pw = ""
        self.pw2 = ""
        self.field = "pw" if self.name else "name"
        self.show_pw = False
        self.caps = False
        self.msg = ""
        self.msg_col = COL["text_dim"]
        self.msg_t = 0.0
        self.armed_delete = 0.0     # 「删档」再点一次确认
        self.chip_sel = -1
        self.done = False           # 登录成功
        self.quit = False
        self.migrated = False       # 是否把老存档并进了这个账号
        self._compute_layout()

    def _compute_layout(self):
        """命中区(账号列表会随增删变化,所以每次都按当前列表重算)。"""
        p = _panel()
        self.lay_chips = [pygame.Rect(p.x + 20, p.y + 48 + i * 38, p.w - 40, 32)
                          for i in range(min(7, len(self.names)))]
        self.lay_show_pw = pygame.Rect(1130, 232, 80, 24)
        self.lay_primary = pygame.Rect(470, 660, 340, 46)
        self.lay_quit = pygame.Rect(830, 660, 170, 46)
        self.lay_delete = pygame.Rect(1010, 660, 200, 46)

    # ---- 状态 ----
    @property
    def signup(self):
        """名字还没人用 = 建新号流程(多一个「再输一次密码」)。"""
        return bool(self.name) and not accounts.exists(self.name)

    def say(self, text, col=None):
        self.msg = text
        self.msg_col = col or COL["text_dim"]
        self.msg_t = 4.0

    # ---- 输入 ----
    def _target(self):
        """当前该往哪个字段写字。字段不存在时退回密码框。"""
        if self.field == "pw2" and not self.signup:
            return "pw"
        return self.field

    def _get(self, field):
        return {"name": self.name, "pw": self.pw, "pw2": self.pw2}.get(field, "")

    def _set(self, field, value):
        if field == "name":
            self.name = value
        elif field == "pw":
            self.pw = value
        elif field == "pw2":
            self.pw2 = value

    def add_text(self, ch):
        f = self._target()
        if not ch or ch == "\t":
            return
        if ord(ch) < 32 or ord(ch) > 126:    # 只收可见 ASCII(英文/数字/符号)
            return
        cur = self._get(f)
        if f == "name" and ch not in NAME_CHARS:
            self.say("名字只能用字母 / 数字 / 下划线 _ / 横杠 -", COL["bad"])
            return
        if len(cur) >= (accounts.NAME_MAX if f == "name" else 24):
            return
        self._set(f, cur + ch)
        if self.msg_t > 0 and "名字只能" in self.msg:
            self.msg_t = 0.0

    def backspace(self):
        f = self._target()
        self._set(f, self._get(f)[:-1])

    def clear_field(self):
        f = self._target()
        if self._get(f):
            self._set(f, "")
        elif self.name:
            self.name = ""

    def next_field(self):
        order = ["name", "pw"] + (["pw2"] if self.signup else [])
        i = order.index(self._target()) if self._target() in order else 0
        self.field = order[(i + 1) % len(order)]

    def press_key(self, value):
        if value == "caps":
            self.caps = not self.caps
            audio.play("click")
        elif value == "back":
            self.backspace()
            audio.play("click")
        elif value == "clear":
            self.clear_field()
            audio.play("click")
        else:
            if self.caps and len(value) == 1 and value.isalpha():
                value = value.upper()      # 屏幕键盘的「⇧ 大写」
            self.add_text(value)

    # ---- 提交 ----
    def submit(self):
        """按「进入」:该登录就登录,该建号就建号。返回 True = 可以进游戏了。"""
        why = accounts.name_reason(self.name)
        if why:
            self.say(why, COL["bad"])
            self.field = "name"
            return False
        if accounts.exists(self.name):
            if not self.pw:
                self.say("请输入密码", COL["bad"])
                self.field = "pw"
                return False
            ok, why, migrated = accounts.login(self.name, self.pw)
            if not ok:
                self.say(f"{why} —— 再试一次(忘了密码只能删档重来)", COL["bad"])
                self.pw = ""
                self.field = "pw"
                return False
            audio.play("pickup")
            self.done = True
            self.migrated = migrated
            return True
        # 新账号
        if len(self.pw) < 3:
            self.say("新账号的密码至少 3 位", COL["bad"])
            self.field = "pw"
            return False
        if self.pw2 != self.pw:
            self.say("两次输入的密码不一样", COL["bad"])
            self.field = "pw2"
            return False
        ok, why, migrated = accounts.register_and_login(self.name, self.pw)
        if not ok:
            self.say(why, COL["bad"])
            return False
        audio.play("pickup")
        self.done = True
        self.migrated = migrated
        return True

    def delete_account(self):
        """删档(要密码):把该账号的存档文件备份成 .deleted-*。"""
        if not accounts.exists(self.name):
            self.say("没有这个账号", COL["bad"])
            return
        if not accounts.verify(self.name, self.pw):
            self.say("删档要先在上面输入正确的密码", COL["bad"])
            self.field = "pw"
            return
        if self.armed_delete <= 0:
            self.armed_delete = 5.0
            self.say(f"再点一次「删档」确认删除账号「{self.name}」(不可恢复)", COL["bad"])
            return
        ok, why = accounts.remove(self.name, self.pw)
        self.armed_delete = 0.0
        if ok:
            self.names = accounts.list_names()
            self.pw = self.pw2 = ""
            self.say(why, COL["good"])
        else:
            self.say(why, COL["bad"])

    # ---- 事件 ----
    def handle(self, ev):
        if ev.type == pygame.QUIT:
            self.quit = True
        elif ev.type == pygame.TEXTINPUT:
            self.add_text(ev.text)
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_ESCAPE:
                self.clear_field()
            elif ev.key == pygame.K_RETURN or ev.key == pygame.K_KP_ENTER:
                self.submit()
            elif ev.key == pygame.K_TAB:
                self.next_field()
            elif ev.key == pygame.K_BACKSPACE:
                self.backspace()
            else:
                ch = getattr(ev, "unicode", "")
                if ch and ch.isprintable():
                    self.add_text(ch)
        elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            self.click(ev.pos)

    def click(self, pos):
        f = _field_rects()
        for key, rect in f.items():
            if rect.collidepoint(pos):
                if key == "pw2" and not self.signup:
                    self.say("这是老账号 —— 直接输密码进入(新账号才要输两次)",
                             COL["text_dim"])
                    self.field = "pw"
                else:
                    self.field = key
                audio.play("click")
                return
        if self.lay_show_pw.collidepoint(pos):
            self.show_pw = not self.show_pw
            audio.play("click")
            return
        if self.lay_primary.collidepoint(pos):
            self.submit()
            return
        if self.lay_quit.collidepoint(pos):
            self.quit = True
            return
        if self.lay_delete.collidepoint(pos):
            self.delete_account()
            return
        for rect, v in _key_rects():
            if rect.collidepoint(pos):
                self.press_key(v[1])
                return
        for i, rect in enumerate(self.lay_chips):
            if rect.collidepoint(pos):
                self.name = self.names[i]
                self.pw = ""
                self.pw2 = ""
                self.field = "pw"
                self.chip_sel = i
                self.armed_delete = 0.0
                self.say(f"已填入账号「{self.names[i]}」—— 请输密码", COL["accent"])
                audio.play("click")
                return

    # ---- 绘制 ----
    def update(self, dt):
        self.msg_t = max(0.0, self.msg_t - dt)
        self.armed_delete = max(0.0, self.armed_delete - dt)

    def draw(self, screen):
        self._compute_layout()
        screen.fill(COL["bg"])
        t = get_font(34, bold=True).render("Tarkov2D", True, COL["accent"])
        screen.blit(t, t.get_rect(center=(W // 2, 46)))
        t = get_font(19, bold=True).render("输入名字和密码,进入你自己的存档", True,
                                           COL["text"])
        screen.blit(t, t.get_rect(center=(W // 2, 88)))

        # 左:已有账号
        p = _panel()
        uikit.draw_panel(screen, p, "已有账号")
        f = get_font(15)
        mx, my = pygame.mouse.get_pos()
        if not self.names:
            t = f.render("还没有账号 —— 右边输入名字和密码,", True, COL["text_dim"])
            screen.blit(t, (p.x + 20, p.y + 60))
            t = f.render("再点「创建账号并进入」就是新档", True, COL["text_dim"])
            screen.blit(t, (p.x + 20, p.y + 84))
        else:
            for i, nm in enumerate(self.names[:7]):
                r = self.lay_chips[i]
                sel = (self.name == nm)
                hover = r.collidepoint(mx, my)
                pygame.draw.rect(screen, COL["panel_hi"] if (hover or sel)
                                 else COL["grid_bg"], r, border_radius=6)
                pygame.draw.rect(screen, COL["accent"] if sel else COL["border"],
                                 r, 2 if sel else 1, border_radius=6)
                t = get_font(16, bold=True).render(nm, True,
                                                   COL["accent"] if sel else COL["text"])
                screen.blit(t, (r.x + 10, r.y + 6))
            t = f.render("点名字可自动填入(密码还得自己输)", True, COL["text_dim"])
            screen.blit(t, (p.x + 20, p.bottom - 30))

        # 右:输入框
        lay = _field_rects()
        uikit.draw_button(screen, self.lay_show_pw,
                          "隐藏" if self.show_pw else "显示", small=True,
                          hover=self.lay_show_pw.collidepoint(mx, my))
        rows = [("名字", "name", "字母 / 数字 / _ / -,最多 %d 位" % accounts.NAME_MAX),
                ("密码", "pw", "")]
        if self.signup:
            rows.append(("再输一次密码", "pw2", "新账号要输两次,老账号不用"))
        for i, (label, key, note) in enumerate(rows):
            y = 150 + i * 84
            t = get_font(17, bold=True).render(label, True, COL["accent"])
            screen.blit(t, (470, y))
            if note:
                t = f.render(note, True, COL["text_dim"])
                screen.blit(t, (470 + get_font(17, bold=True).size(label)[0] + 10, y + 2))
            r = lay[key]
            focused = (self._target() == key)
            pygame.draw.rect(screen, COL["grid_bg"], r, border_radius=6)
            pygame.draw.rect(screen, COL["accent"] if focused else COL["border"], r,
                             3 if focused else 2, border_radius=6)
            val = self._get(key)
            if key != "name" and not self.show_pw:
                val = "●" * len(val)
            t = get_font(22).render(val + ("|" if focused else ""), True, COL["text"])
            screen.blit(t, (r.x + 12, r.y + 7))

        if not self.name:
            state, scol = "新账号:起个名字、设个密码,点「创建账号并进入」", COL["text_dim"]
        elif accounts.exists(self.name):
            state, scol = "老账号:输入密码后点「登录并进入」", COL["good"]
        else:
            state, scol = "这个名字还没人用 —— 点「创建账号并进入」就是新档", COL["accent"]
        t = get_font(17, bold=True).render(state, True, scol)
        screen.blit(t, (470, 384))
        if self.msg_t > 0:
            t = get_font(16, bold=True).render(self.msg, True, self.msg_col)
            screen.blit(t, (470, 408))
        hint = ("密码只存加盐哈希(不存明文) · 存档:存档目录\\accounts\\<名字>\\save.json")
        t = f.render(hint, True, COL["text_dim"])
        screen.blit(t, (470, 432))

        # 屏幕键盘(手机/触屏必须用;电脑也可以点)
        for rect, v in _key_rects():
            label = v[0].upper() if (self.caps and len(v[1]) == 1) else v[0]
            small = len(v[1]) > 1
            uikit.draw_button(screen, rect, label, small=True,
                              hover=rect.collidepoint(mx, my))
        t = get_font(14).render("键盘也能直接打字:Tab 换输入框 · 回车 = 进入 · "
                                "ESC = 清空当前框", True, COL["text_dim"])
        screen.blit(t, (470, 128))

        # 底部按钮
        primary_txt = ("登录并进入" if accounts.exists(self.name) and self.name
                       else "创建账号并进入")
        uikit.draw_button(screen, self.lay_primary, primary_txt,
                          hover=self.lay_primary.collidepoint(mx, my))
        uikit.draw_button(screen, self.lay_quit, "退出游戏", small=True,
                          hover=self.lay_quit.collidepoint(mx, my))
        uikit.draw_button(screen, self.lay_delete,
                          "确认删档?" if self.armed_delete > 0 else "删除该账号",
                          small=True, enabled=bool(self.name),
                          hover=self.lay_delete.collidepoint(mx, my))


async def run_login(screen):
    """登录界面主循环。

    返回 (是否进入游戏, 是否把老存档并进了这个账号)。
    """
    try:
        pygame.key.start_text_input()      # 允许打字(main 里为防 IME 关过)
    except Exception:
        pass
    screen_state = LoginScreen()
    clock = pygame.time.Clock()
    while not (screen_state.done or screen_state.quit):
        dt = min(clock.tick(60) / 1000.0, 0.05)
        events = pygame.event.get()
        # TEXTINPUT 与 KEYDOWN.unicode 可能同时到;有 TEXTINPUT 时只认它(防重复)
        has_text = any(e.type == pygame.TEXTINPUT and getattr(e, "text", "")
                       for e in events)
        for ev in events:
            if has_text and ev.type == pygame.KEYDOWN:
                self_uni = getattr(ev, "unicode", "")
                if self_uni and self_uni.isprintable():
                    continue
            screen_state.handle(ev)
        screen_state.update(dt)
        screen_state.draw(screen)
        pygame.display.flip()
        await asyncio.sleep(0)
    try:
        pygame.key.stop_text_input()
    except Exception:
        pass
    return bool(screen_state.done), bool(screen_state.migrated)
