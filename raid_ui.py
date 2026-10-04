# -*- coding: utf-8 -*-
"""战局渲染:世界+战争迷雾+HUD+背包/搜刮/暂停/结算界面。"""
import math

import pygame

import audio
from settings import (W, H, COL, BAG_W, BAG_H, RAID_TIME, EXTRACT_TIME,
                      HOSTAGE_RESCUE_TIME, REVIVE_TIME,
                      PLAYER, fmt_rub, get_font)
import uikit
from uikit import CELL, draw_grid, draw_item_icon, draw_tooltip, draw_button, draw_slot


# ---------- 布局(与 raid.py 交互命中区) ----------
def inv_layout(bag_w=6, bag_h=4):
    panel = pygame.Rect(W // 2 - 420, 120, 840, 470)
    cell = 44
    bag = (pygame.Rect(panel.right - 40 - bag_w * cell, panel.y + 80,
                       bag_w * cell, bag_h * cell), cell)
    weapon = pygame.Rect(panel.x + 30, panel.y + 80, 300, 100)
    armor = pygame.Rect(panel.x + 30, panel.y + 210, 300, 100)
    close = pygame.Rect(panel.right - 50, panel.y + 16, 34, 34)
    merge = pygame.Rect(panel.x + 30, panel.bottom - 92, 320, 42)
    return dict(panel=panel, bag=bag, weapon=weapon, armor=armor,
                close=close, merge=merge)


def ask_layout():
    """整理弹药确认框布局。"""
    panel = pygame.Rect(W // 2 - 270, H // 2 - 120, 540, 240)
    yes = pygame.Rect(panel.x + 44, panel.bottom - 76, 210, 48)
    no = pygame.Rect(panel.right - 254, panel.bottom - 76, 210, 48)
    return dict(panel=panel, yes=yes, no=no)


def loot_layout(cw, ch, bag_w=6, bag_h=4):
    cell = 34
    cont_w, cont_h = cw * cell, ch * cell
    bag_wp, bag_hp = bag_w * cell, bag_h * cell
    panel_w = max(40 + cont_w + 60 + bag_wp + 40, 560)
    panel = pygame.Rect(W // 2 - panel_w // 2, 140, panel_w, max(cont_h, bag_hp) + 150)
    src = (pygame.Rect(panel.x + 40, panel.y + 90, cont_w, cont_h), cell)
    dst = (pygame.Rect(src[0].right + 60, panel.y + 90, bag_wp, bag_hp), cell)
    takeall = pygame.Rect(src[0].x, src[0].bottom + 14, cont_w, 36)
    close = pygame.Rect(panel.right - 50, panel.y + 16, 34, 34)
    return dict(panel=panel, src=src, dst=dst, takeall=takeall, close=close)


def pause_layout():
    panel = pygame.Rect(W // 2 - 180, 210, 360, 270)
    return dict(
        panel=panel,
        resume=pygame.Rect(panel.x + 50, panel.y + 80, 260, 46),
        giveup=pygame.Rect(panel.x + 50, panel.y + 140, 260, 46),
        quit=pygame.Rect(panel.x + 50, panel.y + 200, 260, 46),
    )


def grid_hit_px(container, rect_cell, pos):
    rect, cell = rect_cell
    if not rect.collidepoint(*pos):
        return None
    gx = int((pos[0] - rect.x) // cell)
    gy = int((pos[1] - rect.y) // cell)
    return container.at(gx, gy)


# ---------- 世界绘制 ----------
def draw_raid(raid, screen):
    p = raid.player
    ticks = pygame.time.get_ticks()
    shake = raid.shake
    ox = -raid.cam[0] + (math.sin(ticks * 91.0) * shake if shake > 0.2 else 0)
    oy = -raid.cam[1] + (math.cos(ticks * 113.0) * shake if shake > 0.2 else 0)

    screen.blit(raid.map_surf, (ox, oy))

    # 撤离区呼吸边框
    pulse = (math.sin(ticks / 400.0) + 1) / 2
    for name, r in raid.map.extracts:
        c = (*COL["extract"], int(90 + 100 * pulse))
        s = pygame.Surface(r.size, pygame.SRCALPHA)
        pygame.draw.rect(s, c, s.get_rect(), 4, border_radius=6)
        screen.blit(s, (r.x + ox, r.y + oy))

    # 动态战利品(普通尸体 / 头目尸体 / 地面堆)
    for lc in raid.containers:
        if lc.kind == "corpse":
            x, y = lc.rect.centerx + ox, lc.rect.centery + oy
            pygame.draw.ellipse(screen, (120, 40, 40), (x - 14, y - 8, 28, 16))
            pygame.draw.line(screen, (60, 24, 24), (x - 8, y - 4), (x + 8, y + 4), 3)
        elif lc.kind == "boss_corpse":
            # 头目尸体:更大 + 金边,保证看得见
            x, y = lc.rect.centerx + ox, lc.rect.centery + oy
            pygame.draw.ellipse(screen, (128, 44, 44), (x - 20, y - 12, 40, 24))
            pygame.draw.ellipse(screen, COL["accent"], (x - 20, y - 12, 40, 24), 2)
            pygame.draw.line(screen, (70, 26, 26), (x - 12, y - 6), (x + 12, y + 6), 4)
            pygame.draw.line(screen, (70, 26, 26), (x - 12, y + 6), (x + 12, y - 6), 4)
        elif lc.kind == "ground":
            x, y = lc.rect.centerx + ox, lc.rect.centery + oy
            pygame.draw.circle(screen, (110, 106, 96), (x, y), 9)
            pygame.draw.circle(screen, (140, 136, 126), (x - 4, y + 3), 6)

    # 子弹(火箭弹画得更大更长)
    for b in raid.bullets:
        bx, by = b["x"] + ox, b["y"] + oy
        if b.get("rpg"):
            nx = bx - b["dx"] * 0.05
            ny = by - b["dy"] * 0.05
            pygame.draw.line(screen, (255, 170, 70), (nx, ny), (bx, by), 5)
            pygame.draw.circle(screen, (255, 220, 140), (int(bx), int(by)), 5)
            pygame.draw.circle(screen, (255, 140, 60), (int(bx), int(by)), 5, 2)
            continue
        nx = bx - b["dx"] * 0.012
        ny = by - b["dy"] * 0.012
        col = (255, 230, 120) if b["owner"] == "player" else (255, 150, 90)
        pygame.draw.line(screen, col, (nx, ny), (bx, by), 2)

    # 突袭目标:指挥设施(未摧毁 = 高亮工事;已摧毁 = 废墟)
    for o in getattr(raid, "objectives", []):
        x, y = o.x + ox, o.y + oy
        if o.destroyed:
            pygame.draw.rect(screen, (58, 56, 54), (x - 20, y - 20, 40, 40),
                             border_radius=4)
            pygame.draw.line(screen, (26, 26, 28), (x - 14, y - 14), (x + 14, y + 14), 5)
            pygame.draw.line(screen, (26, 26, 28), (x - 14, y + 14), (x + 14, y - 14), 5)
            t = get_font(12, bold=True).render(f"{o.name} 已摧毁", True, (150, 150, 156))
            screen.blit(t, t.get_rect(center=(x, y - 32)))
        else:
            pygame.draw.rect(screen, (120, 96, 58), (x - 20, y - 20, 40, 40),
                             border_radius=4)
            pygame.draw.rect(screen, COL["accent"], (x - 20, y - 20, 40, 40), 3,
                             border_radius=4)
            pygame.draw.circle(screen, COL["accent"], (int(x), int(y)), 6)
            t = get_font(13, bold=True).render(o.name, True, COL["accent"])
            screen.blit(t, t.get_rect(center=(x, y - 34)))

    # 待落下的友军支援:落点标记 + 倒计时
    for st in getattr(raid, "strikes", []):
        sx, sy = st["x"] + ox, st["y"] + oy
        cfg = st["cfg"]
        if st["kind"] == "shell":
            pygame.draw.circle(screen, (255, 150, 60), (int(sx), int(sy)), 6)
            continue
        rad = cfg.get("radius", 80)
        col = (255, 90, 90) if st["kind"] == "airstrike" else (255, 170, 60)
        pygame.draw.circle(screen, col, (int(sx), int(sy)), int(rad), 2)
        pygame.draw.line(screen, col, (sx - 14, sy), (sx + 14, sy), 2)
        pygame.draw.line(screen, col, (sx, sy - 14), (sx, sy + 14), 2)
        label = cfg["name"] if st["kind"] != "recon" else "无人机"
        t = get_font(14, bold=True).render(f"{label} {max(0.0, st['t']):.1f}s", True, col)
        screen.blit(t, t.get_rect(center=(sx, sy - rad - 12)))

    # 拾荒者(仅玩家视线内可见;无人机侦察期间全图标记)
    recon = getattr(raid, "recon_t", 0.0) > 0
    for s in raid.scavs:
        if not recon and not raid.map.los_clear(p.x, p.y, s.x, s.y):
            continue
        x, y = s.x + ox, s.y + oy
        if recon:
            pygame.draw.circle(screen, (90, 200, 220), (int(x), int(y)), s.r + 5, 1)
        body = COL["scav"] if s.hit_flash <= 0 else (255, 200, 180)
        pygame.draw.circle(screen, body, (int(x), int(y)), s.r)
        pygame.draw.circle(screen, (30, 30, 34), (int(x), int(y)), s.r, 2)
        wx = x + math.cos(s.facing) * 18
        wy = y + math.sin(s.facing) * 18
        pygame.draw.line(screen, (50, 46, 42), (x, y), (wx, wy), 4 if s.kind != "melee" else 2)
        if s.hp < s.d["hp"]:
            bw = 30
            pygame.draw.rect(screen, (40, 40, 46), (x - bw / 2, y - s.r - 10, bw, 5))
            pygame.draw.rect(screen, (220, 80, 70),
                             (x - bw / 2, y - s.r - 10, bw * s.hp / s.d["hp"], 5))

    # 队友与人质(人质模式)
    for a in raid.allies:
        x, y = a.x + ox, a.y + oy
        col = (110, 190, 110) if not a.downed else (120, 108, 88)
        pygame.draw.circle(screen, col, (int(x), int(y)), a.r)
        pygame.draw.circle(screen, (20, 30, 20), (int(x), int(y)), a.r, 2)
        if not a.downed:
            pygame.draw.line(screen, (235, 235, 235), (x, y),
                             (x + math.cos(a.aim) * 18, y + math.sin(a.aim) * 18), 3)
            if a.hp < a.max_hp:
                bw2 = 30
                pygame.draw.rect(screen, (40, 40, 46), (x - bw2 / 2, y - a.r - 10, bw2, 5))
                pygame.draw.rect(screen, (120, 220, 120),
                                 (x - bw2 / 2, y - a.r - 10, bw2 * a.hp / a.max_hp, 5))
        else:
            t = get_font(12, bold=True).render("倒地", True, (240, 190, 90))
            screen.blit(t, t.get_rect(center=(x, y - a.r - 12)))
    for h in raid.hostages:
        if not h.rescued and not raid.map.los_clear(p.x, p.y, h.x, h.y):
            continue
        x, y = h.x + ox, h.y + oy
        col = (238, 238, 248) if not h.rescued else (140, 200, 240)
        pygame.draw.circle(screen, col, (int(x), int(y)), h.r)
        pygame.draw.circle(screen, (40, 40, 60), (int(x), int(y)), h.r, 2)
        t = get_font(12, bold=True).render("人质" if not h.rescued else "已解救", True, col)
        screen.blit(t, t.get_rect(center=(x, y - h.r - 12)))

    # 粒子
    for pt in raid.particles:
        a = pt["ttl"] / pt["max_ttl"]
        c = (*pt["color"], int(255 * a))
        s = pygame.Surface((8, 8), pygame.SRCALPHA)
        pygame.draw.circle(s, c, (4, 4), int(pt["size"] * a + 1))
        screen.blit(s, (pt["x"] + ox - 4, pt["y"] + oy - 4))

    # 玩家
    px, py = p.x + ox, p.y + oy
    gun_len = 26 if p.weapon else 0
    if p.weapon:
        pygame.draw.line(screen, (235, 235, 240),
                         (px, py),
                         (px + math.cos(p.aim) * gun_len, py + math.sin(p.aim) * gun_len), 4)
    pygame.draw.circle(screen, COL["player"], (int(px), int(py)), PLAYER["radius"])
    pygame.draw.circle(screen, (20, 26, 34), (int(px), int(py)), PLAYER["radius"], 3)
    if p.hurt_flash > 0:
        pygame.draw.circle(screen, (255, 60, 50), (int(px), int(py)),
                           PLAYER["radius"] + 6, 2)

    # 战争迷雾
    fog = pygame.Surface((W, H), pygame.SRCALPHA)
    fog.fill(COL["fog"])
    pts = raid.map.visibility_polygon(p.x, p.y, 560)
    pts = [(x - raid.cam[0], y - raid.cam[1]) for x, y in pts]
    if len(pts) >= 3:
        pygame.draw.polygon(fog, (0, 0, 0, 0), pts)
    screen.blit(fog, (0, 0))

    # 受击红屏
    if p.hurt_flash > 0:
        vs = pygame.Surface((W, H), pygame.SRCALPHA)
        vs.fill((180, 20, 20, int(90 * p.hurt_flash)))
        screen.blit(vs, (0, 0))

    # 撤离点方向指示
    for name, r in raid.map.extracts:
        _edge_arrow(screen, raid, name, r, ox, oy)

    # 人质模式:指向最近未解救人质
    if raid.mode == "hostage":
        near, nd = None, 1e9
        for h in raid.hostages:
            if h.rescued:
                continue
            d = math.hypot(h.x - raid.player.x, h.y - raid.player.y)
            if d < nd:
                near, nd = h, d
        if near is not None and nd > 340:
            fake = pygame.Rect(0, 0, 2, 2)
            fake.center = (int(near.x), int(near.y))
            _edge_arrow(screen, raid, "人质", fake, ox, oy)

    # 突袭模式:指向最近的未摧毁指挥设施
    if raid.mode == "assault":
        near, nd = None, 1e9
        for o in raid.objectives:
            if o.destroyed:
                continue
            d = math.hypot(o.x - raid.player.x, o.y - raid.player.y)
            if d < nd:
                near, nd = o, d
        if near is not None and nd > 340:
            fake = pygame.Rect(0, 0, 2, 2)
            fake.center = (int(near.x), int(near.y))
            _edge_arrow(screen, raid, near.name, fake, ox, oy)

    # 辅助瞄准(手机):锁定标记
    if raid.aim_locked is not None:
        lx = raid.aim_locked.x + ox
        ly = raid.aim_locked.y + oy
        rr = raid.aim_locked.r + 8
        pygame.draw.circle(screen, COL["accent"], (int(lx), int(ly)), rr, 2)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            pygame.draw.line(screen, COL["accent"],
                             (lx + dx * rr, ly + dy * rr),
                             (lx + dx * (rr + 7), ly + dy * (rr + 7)), 2)

    # 撤离引导进度
    if raid.extract_t > 0:
        ratio = min(1.0, raid.extract_t / EXTRACT_TIME)
        bw = 90
        bx = px - bw / 2
        by = py - 34
        pygame.draw.rect(screen, (30, 30, 36), (bx, by, bw, 9), border_radius=4)
        pygame.draw.rect(screen, COL["extract"], (bx, by, bw * ratio, 9), border_radius=4)

    # 解救人质 / 拉起队友 引导进度条
    if raid.channel is not None:
        need = raid.channel_need()
        ratio = min(1.0, raid.channel["t"] / need)
        bw = 90
        bx = px - bw / 2
        by = py - 52
        pygame.draw.rect(screen, (30, 30, 36), (bx, by, bw, 9), border_radius=4)
        col = COL["accent"] if raid.channel["kind"] == "destroy" else COL["good"]
        pygame.draw.rect(screen, col, (bx, by, bw * ratio, 9), border_radius=4)

    _draw_hud(raid, screen)

    # 手机模式的虚拟摇杆与按钮(弹窗打开时不显示,让位给界面操作)
    if (raid.touch_mode and raid.touch is not None and not raid.over
            and not (raid.inv_open or raid.loot_target is not None or raid.paused)):
        raid.touch.draw(screen)

    if raid.inv_open:
        _draw_inventory(raid, screen)
    if raid.ask_merge:
        _draw_ask_merge(raid, screen)
    if raid.loot_target is not None:
        _draw_loot_window(raid, screen)
    if raid.paused:
        _draw_pause(raid, screen)
    if raid.over:
        _draw_result(raid, screen)


def _edge_arrow(screen, raid, name, r, ox, oy):
    p = raid.player
    sx, sy = r.centerx - raid.cam[0], r.centery - raid.cam[1]
    dist = math.hypot(r.centerx - p.x, r.centery - p.y)
    if dist < 300:
        return
    pxs, pys = p.x - raid.cam[0], p.y - raid.cam[1]
    dx, dy = sx - pxs, sy - pys
    if dx == dy == 0:
        return
    margin = 70
    t = 1e9
    if dx > 0:
        t = min(t, (W - margin - pxs) / dx)
    if dx < 0:
        t = min(t, (margin - pxs) / dx)
    if dy > 0:
        t = min(t, (H - margin - pys) / dy)
    if dy < 0:
        t = min(t, (margin - pys) / dy)
    ax, ay = pxs + dx * t, pys + dy * t
    ang = math.atan2(dy, dx)
    pts = [(ax + math.cos(ang) * 14, ay + math.sin(ang) * 14),
           (ax + math.cos(ang + 2.5) * 11, ay + math.sin(ang + 2.5) * 11),
           (ax + math.cos(ang - 2.5) * 11, ay + math.sin(ang - 2.5) * 11)]
    pygame.draw.polygon(screen, COL["extract"], pts)
    f = get_font(13, bold=True)
    t1 = f.render(f"{name} {int(dist // 32)}m", True, COL["extract"])
    screen.blit(t1, t1.get_rect(center=(ax - math.cos(ang) * 30,
                                        ay - math.sin(ang) * 30)))


def _draw_hud(raid, screen):
    p = raid.player
    # HP
    hp_r = pygame.Rect(24, H - 66, 260, 22)
    pygame.draw.rect(screen, COL["hp_bg"], hp_r, border_radius=4)
    pygame.draw.rect(screen, COL["hp"], (hp_r.x, hp_r.y,
                                         hp_r.w * p.hp / p.max_hp, hp_r.h), border_radius=4)
    pygame.draw.rect(screen, COL["border"], hp_r, 2, border_radius=4)
    f = get_font(15, bold=True)
    t = f.render(f"HP {int(p.hp)}/{p.max_hp}", True, (255, 255, 255))
    screen.blit(t, t.get_rect(center=hp_r.center))
    if p.armor is not None:
        ad = p.armor.def_
        txt = f"护甲:{p.armor.name}"
        if ad.get("level"):
            txt += f"  Lv{ad['level']}"
        txt += f"  -{int(ad['reduce'] * 100)}%"
        if ad.get("revive"):
            txt += "  自救:已用" if raid.revive_used else "  自救:可用"
        col = COL["text_dim"] if not (ad.get("revive") and not raid.revive_used) \
            else COL["good"]
        t = get_font(13).render(txt, True, col)
        screen.blit(t, (26, H - 40))
    # 快捷打药提示(血量过半以下且有医疗品时显示)
    if p.hp < p.max_hp * 0.5 and any(pl.item.cat == "med" for pl in p.bag.items):
        t = get_font(14, bold=True).render("按 H 快捷打药", True, COL["good"])
        screen.blit(t, (26, H - 92))

    # 武器/弹药
    wname = p.weapon.name if p.weapon else "未携带武器"
    f16 = get_font(16, bold=True)
    t = f16.render(wname, True, COL["text"])
    screen.blit(t, (W - t.get_width() - 26, H - 92))
    if p.weapon:
        d = p.weapon.def_
        col = COL["accent"]
        big = get_font(30, bold=True).render(
            f"{p.weapon.state.get('mag', 0)} / {p.reserve_count()}", True, col)
        screen.blit(big, (W - big.get_width() - 26, H - 64))
        cal = get_font(13).render(ITEMS_CAL(d), True, COL["text_dim"])
        screen.blit(cal, (W - cal.get_width() - 26, H - 30))
        if p.reloading:
            rt = get_font(15, bold=True).render("装填中…", True, (255, 200, 90))
            screen.blit(rt, (W - rt.get_width() - 26, H - 118))
        # 架枪(长按右键)提示:非狙击枪都可架枪,M139 架枪时不能移动
        if d.get("spread_braced") is not None:
            braced = getattr(raid, "braced", False)
            immo = d.get("braced_immobile")
            if braced:
                txt = "架枪中:精度大幅提升" + ("(无法移动)" if immo else "")
            else:
                txt = "长按右键架枪提升精度" + ("(M139 架枪时不能移动)" if immo else "")
            bt = get_font(15, bold=True).render(
                txt, True, COL["good"] if braced else COL["text_dim"])
            screen.blit(bt, (W - bt.get_width() - 26, H - 142))

    # 计时/击杀/难度
    tl = max(0, raid.time_left)
    mm, ss = int(tl) // 60, int(tl) % 60
    txt = (f"剩余 {mm:02d}:{ss:02d}    {raid.map.map_name} · "
           f"{raid.diff['name']}    击杀 {raid.kills}")
    t = get_font(20, bold=True).render(txt, True,
                                       COL["bad"] if tl < 60 else COL["text"])
    screen.blit(t, t.get_rect(center=(W // 2, 18)))

    # 人质模式:任务进度面板
    if raid.mode == "hostage" and not raid.over:
        done = sum(1 for h in raid.hostages if h.rescued)
        alive = sum(1 for a in raid.allies if not a.downed)
        info = f"人质 {done}/{len(raid.hostages)}    队友 {alive}/{len(raid.allies)}"
        t = get_font(18, bold=True).render(info, True, COL["accent"])
        bg = pygame.Surface((t.get_width() + 20, 32), pygame.SRCALPHA)
        bg.fill((10, 12, 14, 175))
        screen.blit(bg, (20, 16))
        screen.blit(t, (30, 22))

    # 突袭模式:目标进度 + 友军支援积分
    if raid.mode == "assault" and not raid.over:
        done = sum(1 for o in raid.objectives if o.destroyed)
        alive = sum(1 for a in raid.allies if not a.downed)
        info = (f"指挥设施 {done}/{len(raid.objectives)}    "
                f"守军 {len(raid.scavs)}   队友 {alive}/{len(raid.allies)}")
        t = get_font(18, bold=True).render(
            info, True, COL["good"] if done >= len(raid.objectives) else COL["accent"])
        bg = pygame.Surface((t.get_width() + 20, 32), pygame.SRCALPHA)
        bg.fill((10, 12, 14, 175))
        screen.blit(bg, (20, 16))
        screen.blit(t, (30, 22))
        _draw_support_panel(raid, screen, 20, 52)

    # 提示
    if not (raid.inv_open or raid.loot_target or raid.paused or raid.over):
        prompt = None
        for name, r in raid.map.extracts:
            if r.collidepoint(raid.player.x, raid.player.y):
                prompt = ("撤离区:保持不动完成撤离" if raid.allows_extract()
                          else "先炸掉全部指挥设施才能撤离")
                break
        if prompt is None and raid.channel is not None:
            need = raid.channel_need()
            label = {"rescue": "解救人质中", "revive": "拉起队友中",
                     "destroy": "安放炸药中"}.get(raid.channel["kind"], "进行中")
            prompt = f"{label}…{int(min(1.0, raid.channel['t'] / need) * 100)}%"
        if prompt is None and raid.mode in ("hostage", "assault"):
            kind, _ent = raid.nearest_interactable()
            if kind == "rescue":
                prompt = "E  解救人质"
            elif kind == "revive":
                prompt = "E  拉起队友"
            elif kind == "destroy":
                prompt = "E  安放炸药(摧毁设施)"
        if prompt is None:
            lc = raid.nearest_container()
            if lc is not None:
                prompt = f"E  搜刮 {lc.name}"
        if prompt:
            t = get_font(17, bold=True).render(prompt, True, COL["accent"])
            bg = pygame.Surface((t.get_width() + 20, 30), pygame.SRCALPHA)
            bg.fill((10, 10, 12, 170))
            screen.blit(bg, (W // 2 - bg.get_width() // 2, H - 120))
            screen.blit(t, t.get_rect(center=(W // 2, H - 105)))

    # 通知
    y = 56
    for text, ttl, maxttl, color in raid.toasts:
        a = min(1.0, ttl / 0.4)
        t = get_font(15, bold=True).render(text, True, color)
        surf = pygame.Surface((t.get_width() + 14, 24), pygame.SRCALPHA)
        surf.fill((12, 13, 16, int(180 * a)))
        screen.blit(surf, (W // 2 - surf.get_width() // 2, y))
        screen.blit(t, (W // 2 - t.get_width() // 2, y + 4))
        y += 28


def _draw_support_panel(raid, screen, x, y):
    """友军支援面板:积分 + 三个呼叫(热键/点击按钮)。"""
    from settings import SUPPORT, SUPPORT_ORDER
    f = get_font(15, bold=True)
    t = f.render(f"友军支援   积分 {raid.support_points}", True, COL["accent"])
    w = 268
    bg = pygame.Surface((w, 34 + 24 * len(SUPPORT_ORDER)), pygame.SRCALPHA)
    bg.fill((10, 12, 14, 175))
    screen.blit(bg, (x, y))
    screen.blit(t, (x + 10, y + 6))
    if getattr(raid, "recon_t", 0.0) > 0:
        rt = get_font(13, bold=True).render(f"侦察中 {int(raid.recon_t)}s", True,
                                            (90, 200, 220))
        screen.blit(rt, (x + w - rt.get_width() - 10, y + 8))
    fs = get_font(14)
    yy = y + 32
    for i, key in enumerate(SUPPORT_ORDER):
        cfg = SUPPORT[key]
        ok, why = raid.support_state(key)
        cd = raid.support_cd.get(key, 0.0)
        if ok:
            col, tag = COL["good"], "就绪"
        elif cd > 0:
            col, tag = COL["text_dim"], f"冷却 {int(cd) + 1}s"
        else:
            col, tag = COL["bad"], f"缺 {cfg['cost'] - raid.support_points} 分"
        line = f"[{i + 1}] {cfg['name']:<5s} {cfg['cost']:>2d} 分   {tag}"
        t = fs.render(line, True, col)
        screen.blit(t, (x + 10, yy))
        yy += 24


def ITEMS_CAL(d):
    """HUD 口径行。霰弹枪的 ammo 是弹种列表(龙息弹/穿甲独头弹),要逐项取名。"""
    from settings import ITEMS
    ammo = d["ammo"]
    ids = ammo if isinstance(ammo, list) else [ammo]
    return "/".join(ITEMS[a]["name"] for a in ids if a in ITEMS)


def _close_button(surface, rect):
    pygame.draw.rect(surface, COL["panel_hi"], rect, border_radius=6)
    f = get_font(16, bold=True)
    t = f.render("X", True, COL["text"])
    surface.blit(t, t.get_rect(center=rect.center))
    return rect


# ---------- 背包界面 ----------
def _draw_inventory(raid, screen):
    p = raid.player
    lay = inv_layout(p.bag.w, p.bag.h)
    uikit.draw_panel(screen, lay["panel"], "背包  (TAB 关闭)")
    _close_button(screen, lay["close"])
    mx, my = pygame.mouse.get_pos()

    uikit.draw_slot(screen, lay["weapon"], p.weapon, "武器",
                    hover=lay["weapon"].collidepoint(mx, my))
    uikit.draw_slot(screen, lay["armor"], p.armor, "护甲",
                    hover=lay["armor"].collidepoint(mx, my))
    bag_rect, cell = lay["bag"]
    draw_grid(screen, bag_rect.x, bag_rect.y, p.bag, cell,
              f"出战背包 {p.bag.w}×{p.bag.h}")
    # 携行/自救状态
    ry = get_font(14)
    t = ry.render(f"携行容量 {p.bag.w}×{p.bag.h} 格(战局内不可换包)",
                  True, COL["text_dim"])
    screen.blit(t, (lay["panel"].x + 30, lay["armor"].bottom + 8))
    if p.armor is not None and p.armor.def_.get("revive"):
        rv = "已用" if raid.revive_used else "可用"
        col = COL["text_dim"] if raid.revive_used else COL["good"]
        t = ry.render(f"倒地自救:{rv}(每局一次)", True, col)
        screen.blit(t, (lay["panel"].x + 30, lay["armor"].bottom + 30))
    # 整理弹药按钮
    draw_button(screen, lay["merge"], "整理弹药(叠至 120 发/组)",
                hover=lay["merge"].collidepoint(mx, my), small=True)
    hint = "左键:使用/装备   右键:丢弃   点击装备槽:卸下"
    t = get_font(14).render(hint, True, COL["text_dim"])
    screen.blit(t, (lay["panel"].x + 30, lay["panel"].bottom - 34))

    hovered = grid_hit_px(p.bag, lay["bag"], (mx, my))
    if hovered is None and lay["weapon"].collidepoint(mx, my) and p.weapon:
        draw_tooltip(screen, mx, my, p.weapon)
    elif hovered is None and lay["armor"].collidepoint(mx, my) and p.armor:
        draw_tooltip(screen, mx, my, p.armor)
    if hovered is not None:
        draw_tooltip(screen, mx, my, hovered.item)


def _draw_ask_merge(raid, screen):
    """整理弹药确认框。"""
    dark = pygame.Surface((W, H), pygame.SRCALPHA)
    dark.fill((0, 0, 0, 120))
    screen.blit(dark, (0, 0))
    lay = ask_layout()
    uikit.draw_panel(screen, lay["panel"], "整理弹药")
    f = get_font(17)
    lines = ["将背包内相同子弹叠放成组?", "每组最多 120 发,可节省背包空间。"]
    y = lay["panel"].y + 56
    for ln in lines:
        t = f.render(ln, True, COL["text"])
        screen.blit(t, (lay["panel"].x + 34, y))
        y += 30
    mx, my = pygame.mouse.get_pos()
    draw_button(screen, lay["yes"], "叠放",
                hover=lay["yes"].collidepoint(mx, my))
    draw_button(screen, lay["no"], "取消",
                hover=lay["no"].collidepoint(mx, my))


# ---------- 搜刮窗口 ----------
def _draw_loot_window(raid, screen):
    lc = raid.loot_target
    p = raid.player
    lay = loot_layout(lc.container.w, lc.container.h, p.bag.w, p.bag.h)
    uikit.draw_panel(screen, lay["panel"], f"搜刮:{lc.name}  (E/ESC 关闭)")
    _close_button(screen, lay["close"])
    mx, my = pygame.mouse.get_pos()

    src_rect, cell = lay["src"]
    draw_grid(screen, src_rect.x, src_rect.y, lc.container, cell)
    dst_rect, cell2 = lay["dst"]
    draw_grid(screen, dst_rect.x, dst_rect.y, p.bag, cell2, "你的背包")

    draw_button(screen, lay["takeall"], "拾取全部",
                hover=lay["takeall"].collidepoint(mx, my), small=True)
    hint = "左键物品:拾取 / 放回     空武器/护甲槽时点击可直接装备"
    t = get_font(14).render(hint, True, COL["text_dim"])
    screen.blit(t, (lay["panel"].x + 30, lay["panel"].bottom - 34))

    h1 = grid_hit_px(lc.container, lay["src"], (mx, my))
    h2 = grid_hit_px(p.bag, lay["dst"], (mx, my))
    if h1 is not None:
        draw_tooltip(screen, mx, my, h1.item)
    elif h2 is not None:
        draw_tooltip(screen, mx, my, h2.item)


# ---------- 暂停 ----------
def _draw_pause(raid, screen):
    dark = pygame.Surface((W, H), pygame.SRCALPHA)
    dark.fill((0, 0, 0, 140))
    screen.blit(dark, (0, 0))
    lay = pause_layout()
    uikit.draw_panel(screen, lay["panel"], "暂停")
    mx, my = pygame.mouse.get_pos()
    draw_button(screen, lay["resume"], "继续行动", lay["resume"].collidepoint(mx, my))
    draw_button(screen, lay["giveup"], "放弃行动(按阵亡处理)",
                lay["giveup"].collidepoint(mx, my), small=True)
    draw_button(screen, lay["quit"], "退出游戏(战局视为阵亡)",
                lay["quit"].collidepoint(mx, my), small=True)


# ---------- 结算 ----------
def _draw_result(raid, screen):
    r = raid.result
    dark = pygame.Surface((W, H), pygame.SRCALPHA)
    dark.fill((6, 7, 9, 225))
    screen.blit(dark, (0, 0))
    titles = {"extract": ("撤离成功", COL["good"]),
              "death": ("你已阵亡 — 带入装备已丢失", COL["bad"]),
              "mia": ("行动超时 — 按阵亡处理", COL["bad"])}
    title, col = titles[r["kind"]]
    t = get_font(42, bold=True).render(title, True, col)
    screen.blit(t, t.get_rect(center=(W // 2, 150)))

    mm, ss = int(r["time"]) // 60, int(r["time"]) % 60
    if r.get("mode") == "assault":
        line = (f"用时 {mm:02d}:{ss:02d}    击杀 {r['kills']}    "
                f"支援呼叫 {r.get('support_calls', 0)} 次")
    else:
        line = (f"用时 {mm:02d}:{ss:02d}    击杀 {r['kills']}    "
                f"搜刮 {r['n']} 件  价值 {fmt_rub(r['gained'])}")
    t = get_font(20).render(line, True, COL["text"])
    screen.blit(t, t.get_rect(center=(W // 2, 210)))
    if r.get("mode") == "hostage":
        ok = r.get("mission")
        obj = (f"人质解救 {r.get('rescued', 0)}/{r.get('hostages', 0)} —— "
               + ("任务完成!" if ok else "任务未完成"))
        t = get_font(20, bold=True).render(obj, True,
                                           COL["good"] if ok else COL["bad"])
        screen.blit(t, t.get_rect(center=(W // 2, 244)))
    elif r.get("mode") == "assault":
        ok = r.get("mission") and r["kind"] == "extract"
        obj = (f"指挥设施 {r.get('objectives_done', 0)}/{r.get('objectives', 0)}   "
               f"支援呼叫 {r.get('support_calls', 0)} 次 —— "
               + ("任务完成!要塞已被瘫痪" if ok else "任务失败"))
        t = get_font(20, bold=True).render(obj, True,
                                           COL["good"] if ok else COL["bad"])
        screen.blit(t, t.get_rect(center=(W // 2, 244)))
        t = get_font(15).render("系统配发装备与战利品已回收,仓库配置未变动",
                                True, COL["text_dim"])
        screen.blit(t, t.get_rect(center=(W // 2, 274)))

    if r["entries"] and r.get("mode") != "assault":
        f = get_font(16)
        y = 260
        for e in r["entries"][:12]:
            t = f.render(f"· {e['name']} ×{e['count']}", True, COL["text"])
            screen.blit(t, (W // 2 - 220, y))
            v = f.render(fmt_rub(e["value"]), True, COL["accent"])
            screen.blit(v, (W // 2 + 220 - v.get_width(), y))
            y += 26
    t = get_font(16).render("按任意键返回藏身处", True, COL["text_dim"])
    screen.blit(t, t.get_rect(center=(W // 2, H - 90)))
