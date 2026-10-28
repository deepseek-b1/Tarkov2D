# -*- coding: utf-8 -*-
"""共享 UI 组件:格子容器绘制、物品图标、悬浮提示、按钮。"""
import pygame

from settings import (get_font, COL, fmt_rub, ITEMS, ATTACH_SLOTS,
                      weapon_params, weapon_capacity, weapon_ammo_ids,
                      weapon_slots, weapon_attach, weapon_talent, weapon_class,
                      weapon_fire_modes, weapon_fire_mode, fire_mode_name,
                      MISFIRE_JAM_TIME)
from inventory import Container, Placed

CELL = 40  # 界面格子像素


def draw_panel(surface, rect, title=None):
    pygame.draw.rect(surface, COL["panel"], rect, border_radius=8)
    pygame.draw.rect(surface, COL["border"], rect, 2, border_radius=8)
    if title:
        t = get_font(20, bold=True).render(title, True, COL["text"])
        surface.blit(t, (rect.x + 12, rect.y + 8))
    return rect


def draw_grid(surface, x, y, container, cell=CELL, title=None,
              scroll=0.0, view_h=None):
    """绘制格子容器,返回 (Rect, cell)。

    scroll / view_h:仓库变大后只画看得见的一段(配合滚轮),不会画出面板外。
    """
    w = container.w * cell
    total_h = container.h * cell
    shown_h = view_h if view_h else total_h
    rect = pygame.Rect(x, y, w, total_h)
    pygame.draw.rect(surface, COL["grid_bg"], (x, y, w, shown_h), border_radius=4)
    off = int(scroll)
    clip = pygame.Rect(x, y, w, view_h) if view_h else None
    if clip:
        surface.set_clip(clip)
    for gx in range(container.w):
        for gy in range(container.h):
            r = pygame.Rect(x + gx * cell, y + gy * cell - off, cell, cell)
            if view_h and (r.bottom < y or r.top > y + view_h):
                continue
            pygame.draw.rect(surface, COL["grid"], r, 1)
    for p in container.items:
        iw, ih = p.item.size()
        iy = y + p.y * cell - off
        if view_h and (iy + ih * cell < y or iy > y + view_h):
            continue
        draw_item_icon(surface, p.item, x + p.x * cell, iy, cell)
    if clip:
        surface.set_clip(None)
    if title:
        t = get_font(16, bold=True).render(title, True, COL["text_dim"])
        surface.blit(t, (x, y - 24))
    return rect, cell


def grid_hit(container, rect, cell, mx, my, scroll=0.0):
    """像素坐标 -> 命中的 Placed(或 None)。scroll 必须和绘制时一致。"""
    if not rect.collidepoint(mx, my):
        return None
    gx = (mx - rect.x) // cell
    gy = (my - rect.y + int(scroll)) // cell
    return container.at(int(gx), int(gy))


def draw_item_icon(surface, item, x, y, cell=CELL):
    """按类别画简单图标:武器=枪形,弹药=子弹,医疗=十字,护甲=背心,值钱品=菱形。"""
    w, h = item.size()
    wpx, hpx = w * cell, h * cell
    rect = pygame.Rect(x, y, wpx, hpx)
    col = item.def_["color"]
    pygame.draw.rect(surface, col, rect.inflate(-6, -6), border_radius=4)
    pygame.draw.rect(surface, (20, 20, 24), rect.inflate(-6, -6), 2, border_radius=4)
    cx, cy = rect.center
    inner = rect.inflate(-8, -8)
    cat = item.cat
    if item.def_.get("drone"):
        # 侦察无人机:四旋翼 + 中央机身 + 摄像头(和枪形区分开)
        for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            rx, ry = cx + dx * 11, cy + dy * 6
            pygame.draw.line(surface, (34, 40, 44), (cx, cy), (rx, ry), 3)
            pygame.draw.circle(surface, (34, 40, 44), (rx, ry), 4)
        pygame.draw.rect(surface, (34, 40, 44),
                         (cx - 7, cy - 5, 14, 11), border_radius=3)
        pygame.draw.circle(surface, (240, 230, 150), (cx, cy + 1), 2)
    elif cat == "weapon":
        # 枪管 + 枪身
        pygame.draw.line(surface, (40, 40, 46), (inner.left, cy), (inner.right, cy), 4)
        pygame.draw.rect(surface, (50, 50, 58),
                         (cx - 10, cy - 3, 14, 10), border_radius=2)
        pygame.draw.rect(surface, (50, 50, 58), (cx + 2, cy + 2, 8, 6))
    elif cat == "ammo":
        for i in range(3):
            pygame.draw.rect(surface, (60, 60, 66),
                             (inner.left + 4 + i * 8, inner.top + 8, 5, 12), border_radius=2)
    elif cat == "med":
        pygame.draw.rect(surface, (240, 240, 240), (cx - 9, cy - 3, 18, 6), border_radius=2)
        pygame.draw.rect(surface, (240, 240, 240), (cx - 3, cy - 9, 6, 18), border_radius=2)
    elif cat == "armor":
        pygame.draw.polygon(surface, (36, 36, 42), [
            (inner.left + 4, cy - 12), (inner.right - 4, cy - 12),
            (inner.right - 4, cy + 2), (cx, cy + 13), (inner.left + 4, cy + 2)])
    elif cat == "pack":
        # 背包:主体 + 顶部提手 + 横带
        pygame.draw.rect(surface, (32, 32, 38),
                         (inner.left + 3, cy - 7, inner.w - 6, inner.h - 11),
                         border_radius=5)
        pygame.draw.rect(surface, (28, 28, 32),
                         (inner.left + 3, cy - 7, inner.w - 6, 5), border_radius=2)
        pygame.draw.arc(surface, (28, 28, 32),
                        (cx - 10, inner.top + 2, 20, 20), 0.3, 2.9, 3)
        pygame.draw.line(surface, (28, 28, 32), (inner.left + 3, cy + 4),
                         (inner.right - 3, cy + 4), 2)
    elif cat == "kit":
        # 全装包:礼盒 + 十字丝带 + 蝴蝶结
        pygame.draw.rect(surface, (30, 30, 36),
                         (inner.left + 3, inner.top + 6, inner.w - 6, inner.h - 9),
                         border_radius=3)
        pygame.draw.line(surface, (250, 240, 210), (cx, inner.top + 6),
                         (cx, inner.bottom - 3), 3)
        pygame.draw.line(surface, (250, 240, 210), (inner.left + 3, cy + 1),
                         (inner.right - 3, cy + 1), 3)
        pygame.draw.circle(surface, (250, 240, 210), (cx - 4, inner.top + 4), 3)
        pygame.draw.circle(surface, (250, 240, 210), (cx + 4, inner.top + 4), 3)
    elif cat == "attach":
        # 配件:导轨 + 镜筒
        pygame.draw.rect(surface, (30, 30, 34),
                         (inner.left + 2, cy - 3, inner.w - 4, 8), border_radius=2)
        pygame.draw.circle(surface, (30, 30, 34), (cx, cy - 6), 6, 3)
        pygame.draw.line(surface, (30, 30, 34), (cx, cy - 3), (cx, cy - 1), 3)
    elif cat == "misc":
        # 杂物:六角螺母 + 中心孔
        pygame.draw.polygon(surface, (44, 44, 50), [
            (cx, cy - 11), (cx + 9, cy - 5), (cx + 9, cy + 5),
            (cx, cy + 11), (cx - 9, cy + 5), (cx - 9, cy - 5)])
        pygame.draw.circle(surface, (26, 26, 30), (cx, cy), 4)
    elif cat == "helmet":
        # 头盔:圆顶 + 下沿 + 护颚
        pygame.draw.arc(surface, (30, 30, 36),
                        (inner.left + 2, inner.top + 2, inner.w - 4, inner.h),
                        0.15, 3.0, 4)
        pygame.draw.rect(surface, (30, 30, 36),
                         (inner.left + 3, cy - 1, inner.w - 6, 6), border_radius=3)
        pygame.draw.rect(surface, (30, 30, 36),
                         (cx - 5, cy + 5, 10, 9), border_radius=2)
    else:  # valuable
        pygame.draw.polygon(surface, (255, 255, 255),
                            [(cx, cy - 11), (cx + 10, cy), (cx, cy + 11), (cx - 10, cy)])
    # 数量 / 弹匣
    if item.is_stackable() and item.count > 1:
        t = get_font(13, bold=True).render(f"x{item.count}", True, (255, 255, 255))
        surface.blit(t, (rect.right - t.get_width() - 6, rect.bottom - t.get_height() - 3))
    if cat == "weapon" and not item.def_.get("drone"):
        mag = item.state.get("mag", 0)
        t = get_font(13, bold=True).render(f"{mag}", True,
                                           (120, 255, 120) if mag else (255, 120, 110))
        surface.blit(t, (rect.x + 6, rect.bottom - t.get_height() - 3))


def draw_button(surface, rect, text, hover=False, enabled=True, small=False):
    base = COL["panel_hi"] if hover else COL["panel"]
    if not enabled:
        base = (44, 46, 50)
    pygame.draw.rect(surface, base, rect, border_radius=8)
    border = COL["accent"] if hover and enabled else COL["border"]
    pygame.draw.rect(surface, border, rect, 2, border_radius=8)
    f = get_font(18, bold=True) if not small else get_font(15, bold=True)
    col = COL["text"] if enabled else (120, 120, 126)
    t = f.render(text, True, col)
    surface.blit(t, t.get_rect(center=rect.center))
    return rect


def draw_slot(surface, rect, item, label, hover=False):
    """装备槽(武器/护甲)。"""
    pygame.draw.rect(surface, COL["grid_bg"], rect, border_radius=6)
    pygame.draw.rect(surface, COL["accent"] if hover else COL["border"], rect, 2, border_radius=6)
    t = get_font(14, bold=True).render(label, True, COL["text_dim"])
    surface.blit(t, (rect.x + 8, rect.y + 6))
    if item:
        cell = min((rect.w - 20) // max(1, item.size()[0]),
                   (rect.h - 30) // max(1, item.size()[1]), 34)
        ix = rect.centerx - item.size()[0] * cell // 2
        iy = rect.bottom - item.size()[1] * cell // 2 - 6
        draw_item_icon(surface, item, ix, iy, cell)
    else:
        t2 = get_font(13).render("空", True, (90, 94, 102))
        surface.blit(t2, t2.get_rect(center=(rect.centerx, rect.bottom - 26)))
    return rect


def item_info_lines(item):
    """悬浮提示信息行。"""
    d = item.def_
    lines = [d["name"]]
    w, h = item.base_size()
    sub = [f"{w}×{h} 格  {fmt_rub(d['price'])}"]
    if item.cat == "weapon" and d.get("drone"):
        # 侦察无人机:不是枪,只报侦察参数(伤害/弹匣这些没意义)
        from settings import drone_cfg
        cfg = drone_cfg()
        sub.append("左键放出 · F 掌镜(WASD 操纵)· 左键/F 收回")
        sub.append(f"侦察半径 {int(cfg['view_radius'])}  标记半径 "
                   f"{int(cfg['mark_radius'])}  标记保留 {cfg['mark_hold']:.0f}s")
        sub.append(f"电量 {cfg['battery']:.0f}s  飞行 {int(cfg['speed'])}/s  "
                   f"信号 {int(cfg['max_dist'])}")
        sub.append("★ 大范围照亮战争迷雾(夜战同样有效)")
        sub.append("★ 自动标记圈内守军,把位置同步给队友")
        sub.append(("★ 电量耗尽:离得近自动回收,离得远直接坠毁"
                    if cfg["crash_dmg"] <= 0 else
                    f"★ 失联坠毁自伤 {cfg['crash_dmg']:.0f}"))
        tal = weapon_talent(item.iid)
        if tal:
            sub.append(f"天赋·{tal['name']}:{tal.get('desc', '')}")
    elif item.cat == "weapon":
        cls = weapon_class(item.iid)
        if cls:
            sub.insert(0, f"分类: {cls}")
        (dmg, pellets, hip, braced_s, rng, rl_t, _loud, burn,
         wall_pen, wall_decay, misfire, misfire_dmg) = weapon_params(item)
        cap = weapon_capacity(item)
        sub.append(f"伤害 {dmg:.0f}×{pellets}  射速 {d['rof']}s  "
                   f"弹匣 {item.state.get('mag', 0)}/{cap}")
        names = "/".join(ITEMS[a]["name"] for a in weapon_ammo_ids(item) if a in ITEMS)
        modes = weapon_fire_modes(item)
        sub.append(f"弹药: {names}  " + "/".join(fire_mode_name(m) for m in modes)
                   + (f"  当前:{fire_mode_name(weapon_fire_mode(item))}"
                      if len(modes) > 1 else ""))
        if burn:
            sub.append(f"★ 燃烧伤害 {burn:.0f}/秒")
        if wall_pen:
            sub.append(f"★ 特殊弹:可穿透 {int(wall_pen)} 层墙"
                       f"(每层伤害 ×{wall_decay:.2f})")
        if misfire:
            sub.append(f"★ 炸膛概率 {misfire * 100:.0f}%"
                       f"(自伤 {misfire_dmg:.0f},卡壳 {MISFIRE_JAM_TIME:.1f}s)")
        if d.get("spread_braced") is not None:
            sub.append(f"散布:腰射 ±{hip:.3f} → 架枪 ±{braced_s:.3f}")
            if d.get("braced_immobile"):
                sub.append("★ 架枪时无法移动(重型机枪)")
        else:
            sub.append(f"散布:±{hip:.3f}(狙击枪,不参与架枪)")
        tal = weapon_talent(item.iid)
        if tal:
            sub.append(f"天赋·{tal['name']}:{tal.get('desc', '')}")
        slots = weapon_slots(item.iid)
        att = weapon_attach(item)
        if slots:
            parts = [f"{ATTACH_SLOTS[s]}:"
                     + (ITEMS[att[s]]["name"] if s in att else "空") for s in slots]
            sub.append(" ".join(parts))
        elif item.iid == "m139":
            sub.append("机枪不可装配件")
        loaded = item.state.get("loaded")
        if loaded in ITEMS:
            sub.append(f"当前装填:{ITEMS[loaded]['name']}")
        if d.get("req_armor_level"):
            sub.append(f"★ 需装备 {d['req_armor_level']} 级护甲才能持用")
    elif item.cat == "attach":
        sub.append(f"{ATTACH_SLOTS.get(d.get('slot'), '配件')} · {d.get('desc', '')}")
        sub.append("在藏身处装备武器后点它即可安装")
    elif item.cat == "armor":
        txt = ""
        if d.get("level"):
            txt += f"防弹级别 {d['level']}   "
        txt += f"减伤 {int(d['reduce'] * 100)}%"
        if d.get("slow"):
            txt += f"  移速 -{int(d['slow'] * 100)}%"
        sub.append(txt)
        if d.get("revive"):
            sub.append("★ 倒地自救 ×1(每局一次)")
    elif item.cat == "helmet":
        txt = ""
        if d.get("level"):
            txt += f"防弹级别 {d['level']}   "
        if d.get("reduce"):
            txt += f"额外减伤 {int(d['reduce'] * 100)}%"
        if txt:
            sub.append(txt.strip())
        if d.get("nvg"):
            sub.append(f"★ 夜视:周围 {int(d['nvg'][0])} 全向可见(黑暗模式)")
    elif item.cat == "pack":
        gw, gh = d.get("grid", (0, 0))
        sub.append(f"携行容量 {gw}×{gh} 格")
        if item.is_rolled():
            rw, rh = item.roll_size()
            sub.append(f"★ 已卷起:占 {rw}×{rh} 格(右键展开,展开占 "
                       f"{d['w']}×{d['h']} 格)")
        else:
            rw, rh = item.roll_size()
            sub.append(f"右键卷起:占格 {d['w']}×{d['h']} → {rw}×{rh}")
    elif item.cat == "kit":
        import mystery      # 局部导入:uikit 是被最多模块引用的底层件,别拖出环
        sub.append(f"打开后得到:{mystery.kit_summary(item.iid)}")
        sub.append(f"一整套 {len(mystery.kit_items(item.iid))} 件:"
                   "满配武器 + 6 级甲/头盔 + 背包 + 弹药 + 药")
        sub.append("★ 电脑右键 / 手机长按后点「打开」")
    elif item.cat == "misc":
        sub.append(f"杂物 · 价值 {fmt_rub(d['price'])}")
        if item.iid == "doc":
            sub.append("★ 仅「强化封锁」每局 0.1% 概率刷在保险箱(孤品)")
    elif item.cat == "med":
        sub.append(f"治疗 {d['heal']} HP")
    elif item.cat == "ammo":
        sub.append(f"剩余 {item.count} 发")
    lines.extend(sub)
    return lines


def draw_tooltip(surface, mx, my, item):
    lines = item_info_lines(item)
    f = get_font(15)
    th = sum(f.size(ln)[1] for ln in lines) + 14
    tw = max(f.size(ln)[0] for ln in lines) + 20
    x = mx + 16
    y = my + 16
    if x + tw > surface.get_width():
        x = mx - tw - 12
    if y + th > surface.get_height():
        y = my - th - 12
    rect = pygame.Rect(x, y, tw, th)
    s = pygame.Surface((tw, th), pygame.SRCALPHA)
    s.fill((14, 15, 18, 235))
    surface.blit(s, rect)
    pygame.draw.rect(surface, COL["border"], rect, 1)
    yy = y + 7
    for i, ln in enumerate(lines):
        t = f.render(ln, True, COL["accent"] if i == 0 else COL["text"])
        surface.blit(t, (x + 10, yy))
        yy += f.size(ln)[1]


# ---------- 触屏长按(显示物品详情;可附「旋转」按钮) ----------
class HoldInfo:
    """触屏长按提示:按住物品 0.45s 弹出信息面板。

    用法:按下时 press(pos),移动时 move(pos),抬起时 consume_release(),
    每帧 update(dt, query)。query(pos) -> (item, action_cb) 或 None。
    面板下方按钮的文案按物品类型变(旋转 / 卷起展开 / 打开全装包)。

    **这个类只决定"要不要弹信息面板",绝不能顺手把点按也吃掉。**
    面板打开时调用方会把所有左键按下吞掉、只在抬起时重放一次点击
    (见 raid._filter_hold_events / hideout._hold_filter)。所以只要
    consume_release() 返回 False,那次点击就凭空消失了 —— 玩家看到的是
    "点了没反应"。

    踩过的两个坑(都会让点按彻底失效):
      1) 原来 MOVE_TOL=14(曼哈顿距离,等于每轴只有 7px)。真机上正常点
         一下手指漂移 15~25px 很常见,一过阈值就 reset(),连点按一起没了。
         现在移动只让"不弹长按面板",点按照常重放。
      2) 原来按住超过 0.45s 而 query 返回 None(点在空白处,或点在**未知
         物品**上 —— 未知物品故意不泄底)时会把 holding 清掉,于是抬起
         既不弹面板、也不重放点击。搜刮窗口里点"?"格子想开始搜索,
         按久一点就完全没反应。现在只跳过弹面板,点按仍然有效。
    """
    DELAY = 0.45
    # 手抖 vs 划动的分界(曼哈顿距离)。正常点按漂移通常在 20px 以内,
    # 刻意划动一般 60px 以上,48 正好卡在中间。这个阈值只决定"算不算点按",
    # 绝不能再像以前那样顺手把点按也取消掉。
    MOVE_TOL = 48          # 只用于"要不要弹长按面板 / 算不算点按"

    def __init__(self):
        self.reset()

    def reset(self):
        self.holding = False
        self.t = 0.0
        self.pos = None
        self.fired = False
        self.dragged = False   # 手指移动超过阈值:不弹面板(但点按仍然有效)
        self.item = None
        self.action_cb = None
        self.btn_label = None
        self.lines = None
        self.rect = None
        self.action_rect = None

    def press(self, pos):
        self.reset()
        self.holding = True
        self.pos = tuple(pos)

    def move(self, pos):
        if (self.holding and not self.fired and self.pos is not None
                and abs(pos[0] - self.pos[0]) + abs(pos[1] - self.pos[1])
                > self.MOVE_TOL):
            # 手指移动了:不弹长按面板。但**不取消这次点按** ——
            # 面板里没有拖拽移动物品的操作,漂移只是手抖,抬起照样算点击。
            self.dragged = True

    def consume_release(self):
        """抬起:返回 True = 这次点按没被长按面板消费,调用方要重放一次点击。

        手指划动超过 MOVE_TOL 时算"划动",不重放(避免误点)。
        另外:**只有 press() 记下的这一次按下才算点按** —— 没有按下就来的
        抬起(比如在设置页点的关闭按钮,那一帧根本不走长按过滤)绝不能
        拿上一次的按下点去重放点击,否则会在别的界面上凭空多出一击。
        """
        tap = (self.holding and not self.fired and not self.dragged)
        self.holding = False
        return tap

    def click_pos(self):
        """重放这次点按该用的坐标 —— 用**按下点**,即玩家真正瞄准的位置。

        用抬起点的话,手指点一下漂移十几像素就会滑到隔壁格子上,点错东西。
        """
        return self.pos

    def update(self, dt, query):
        if not (self.holding and not self.fired):
            return
        self.t += dt
        if self.t < self.DELAY or self.dragged:
            return
        got = query(self.pos) if query is not None else None
        if got is None:
            # 没按在已知物品上(空白 / 未知物品):不弹面板。
            # 注意这里**不能**清掉 holding —— 清了的话抬起时既不弹面板、
            # 也不重放点击,这次点按就彻底丢了。
            return
        self.fired = True
        self.item, self.action_cb = got
        self.btn_label = hold_button_label(self.item)
        self.lines = item_info_lines(self.item)
        self.rect, self.action_rect = hold_layout(self.lines, self.pos,
                                                  self.btn_label is not None)

    def active(self):
        return self.fired and self.rect is not None and self.item is not None

    def hide(self):
        self.reset()


def hold_button_label(item):
    """长按面板下方按钮的文案(None = 这个物品没有额外动作)。"""
    if item is None:
        return None
    if item.cat == "kit":
        return "打开全装包"
    if item.cat == "pack":
        return "卷起 / 展开"
    return "旋转(横 / 竖互换)"


def hold_layout(lines, pos, has_action):
    """长按信息面板布局:返回 (面板 Rect, 动作按钮 Rect 或 None)。"""
    from settings import W, H
    f = get_font(15)
    th = sum(f.size(ln)[1] for ln in lines) + 14
    tw = max(f.size(ln)[0] for ln in lines) + 20
    btn_h = 40 if has_action else 0
    total_h = th + btn_h
    x = max(8, min(pos[0] - tw // 2, W - tw - 8))
    y = pos[1] - total_h - 18
    if y < 8:
        y = min(H - total_h - 8, pos[1] + 20)
    rect = pygame.Rect(x, y, tw, total_h)
    btn = pygame.Rect(x + 10, y + th + 4, tw - 20, 30) if has_action else None
    return rect, btn


def draw_hold(surface, hold):
    """绘制长按信息面板(信息行 + 可选动作按钮)。"""
    if hold is None or not hold.active():
        return
    rect = hold.rect
    s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
    s.fill((14, 15, 18, 240))
    surface.blit(s, rect)
    pygame.draw.rect(surface, COL["accent"], rect, 2)
    f = get_font(15)
    yy = rect.y + 7
    for i, ln in enumerate(hold.lines):
        t = f.render(ln, True, COL["accent"] if i == 0 else COL["text"])
        surface.blit(t, (rect.x + 10, yy))
        yy += f.size(ln)[1]
    if hold.action_rect is not None:
        draw_button(surface, hold.action_rect, hold.btn_label or "确定", small=True)
