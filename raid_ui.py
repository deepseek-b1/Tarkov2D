# -*- coding: utf-8 -*-
"""战局渲染:世界+战争迷雾+HUD+背包/搜刮/暂停/结算界面。"""
import math
import os

import pygame

import audio
import bindings
from settings import (W, H, COL, BAG_W, BAG_H, RAID_TIME, EXTRACT_TIME,
                      HOSTAGE_RESCUE_TIME, REVIVE_TIME, C4_BLAST_RADIUS,
                      NIGHT_DARK_RGB, NIGHT_BEAM_RGB, PLAYER, fmt_rub, get_font,
                      weapon_beam, helmet_nvg, weapon_fire_mode,
                      weapon_fire_modes, fire_mode_name)
import uikit
from uikit import CELL, draw_grid, draw_item_icon, draw_tooltip, draw_button, draw_slot


# 全屏叠加层缓存:每帧新建 Surface 太贵(1280×720 SRCALPHA),复用一个
_overlay_cache = {}


# ---------- 玩家立绘 ----------
# art/player_front|side|back.png 由 tools/make_player_art.py 从角色设定图生成。
# 按瞄准方向用四个朝向绘制,右侧直接用左侧镜像。素材缺失(例如打包时忘了带
# art/)就自动退回原来的圆点绘制,所以任何平台上都不会因为没图而崩。
PLAYER_SPRITE_H = 42        # 立绘绘制高度(像素;宽度约等于碰撞圆直径)
PLAYER_SPRITE_FOOT = 16     # 立绘底边相对玩家坐标的偏移(越大越靠下)
_player_art = {}


def _player_art_frames():
    """懒加载并缩放的玩家立绘 {朝向: Surface};加载不了就是空 dict。"""
    if _player_art:
        return _player_art
    _player_art["_done"] = True          # 只尝试一次(失败也不每帧重试)
    here = os.path.dirname(os.path.abspath(__file__))
    root = None
    for sub in (os.path.join(here, "art"), os.path.join(here, "..", "art")):
        if os.path.isfile(os.path.join(sub, "player_front.png")):
            root = sub
            break
    if root is None:
        return _player_art
    for key, name in (("front", "player_front"), ("back", "player_back"),
                      ("side", "player_side")):
        try:
            s = pygame.image.load(os.path.join(root, name + ".png"))
            s = s.convert_alpha()
        except Exception:
            continue
        k = PLAYER_SPRITE_H / float(s.get_height())
        s = pygame.transform.smoothscale(
            s, (max(1, int(round(s.get_width() * k))), PLAYER_SPRITE_H))
        _player_art[key] = s
        if key == "side":
            _player_art["side_r"] = pygame.transform.flip(s, True, False)
    return _player_art


def _player_facing(aim):
    """按瞄准角选朝向:屏幕上 y 向下,所以 dy>0 是"面朝镜头"(正面)。"""
    dx = math.cos(aim)
    dy = math.sin(aim)
    if abs(dx) >= abs(dy):
        return "side_r" if dx > 0 else "side"
    return "front" if dy > 0 else "back"


def _draw_player(screen, p, px, py):
    """画玩家:立绘(四向)优先,没素材时退回原来的圆点。"""
    spr = _player_art_frames().get(_player_facing(p.aim))
    gun_len = 26 if p.weapon else 0
    if spr is None:
        if p.weapon:
            pygame.draw.line(screen, (235, 235, 240), (px, py),
                             (px + math.cos(p.aim) * gun_len,
                              py + math.sin(p.aim) * gun_len), 4)
        pygame.draw.circle(screen, COL["player"], (int(px), int(py)), PLAYER["radius"])
        pygame.draw.circle(screen, (20, 26, 34), (int(px), int(py)), PLAYER["radius"], 3)
    else:
        rect = spr.get_rect()
        rect.midbottom = (int(round(px)), int(round(py + PLAYER_SPRITE_FOOT)))
        screen.blit(spr, rect)
        if p.weapon:      # 枪画在立绘之上,不然看不出枪口指向
            pygame.draw.line(screen, (235, 235, 240),
                             (px, py - 8),
                             (px + math.cos(p.aim) * gun_len,
                              py - 8 + math.sin(p.aim) * gun_len), 4)
    if p.hurt_flash > 0:
        pygame.draw.circle(screen, (255, 60, 50), (int(px), int(py)),
                           PLAYER["radius"] + 6, 2)


def _overlay(key, size, color):
    key = (key, size)
    surf = _overlay_cache.get(key)
    if surf is None:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        _overlay_cache[key] = surf
    surf.fill(color)
    return surf


# 压暗层(战争迷雾):
# 原来是「全屏 SRCALPHA 压暗 + 用透明多边形打洞 + 整屏 alpha 混合」,
# 1280×720 实测 ~16ms(i5-4210U)。换成不透明表面做乘性压暗后只要 ~2ms:
#   * 不透明表面没有 alpha 通道要算,fill/polygon 都走快速路径;
#   * BLEND_RGB_MULT 是 SDL 的快路径,整屏只要 0.8ms(alpha 混合要 8.6ms)。
# 观感基本一致:亮部完全一样(255 → 75),暗部最多差 8/255(约 3%)。
_rgb_cache = {}


def _darken_layer(key, size, rgba):
    surf = _rgb_cache.get(key)
    if surf is None:
        surf = pygame.Surface(size)
        _rgb_cache[key] = surf
    a = rgba[3]
    surf.fill(tuple(min(255, (255 - a) + (rgba[i] * a) // 255) for i in range(3)))
    return surf


def _mask_surface(key, size):
    """取/建压暗层缓存表面(不填充)。

    关键:填充(整屏压暗)与"打洞"(亮区/视野多边形)**必须在同一帧完成**。
    以前是每帧 fill、只在版本变化时打洞 —— 版本没变的那些帧里洞被填掉,
    表现就是亮区一闪一闪(夜里尤其明显:整屏几乎全黑)。
    """
    surf = _rgb_cache.get(key)
    if surf is None:
        surf = pygame.Surface(size)
        _rgb_cache[key] = surf
    return surf


def _darken_fill(surf, rgba):
    a = rgba[3]
    surf.fill(tuple(min(255, (255 - a) + (rgba[i] * a) // 255) for i in range(3)))


# 撤离区呼吸边框:每帧给每个撤离点新建 Surface + 重画圆角框太浪费。
# 按尺寸复用一个,只有呼吸亮度跨过一档才重画。
_extract_cache = {}
_EXTRACT_STEP = 6


def _extract_border(size, rgb, alpha):
    step = alpha // _EXTRACT_STEP
    ent = _extract_cache.get(size)
    if ent is None:
        ent = [-1, pygame.Surface(size, pygame.SRCALPHA)]
        _extract_cache[size] = ent
    if ent[0] != step:
        s = ent[1]
        s.fill((0, 0, 0, 0))
        pygame.draw.rect(s, (*rgb, step * _EXTRACT_STEP), s.get_rect(), 4, border_radius=6)
        ent[0] = step
    return ent[1]


# 粒子:按 (颜色, 半径, 透明度档) 缓存小图,别每颗每帧都新建 Surface + 画圆
_particle_cache = {}


def _particle_sprite(color, radius, alpha):
    key = (color, radius, alpha // 16)
    s = _particle_cache.get(key)
    if s is None:
        d = radius * 2 + 2
        s = pygame.Surface((d, d), pygame.SRCALPHA)
        pygame.draw.circle(s, (*color, key[2] * 16), (radius + 1, radius + 1), radius)
        if len(_particle_cache) > 256:
            _particle_cache.clear()
        _particle_cache[key] = s
    return s


# HUD 小面板背景:按尺寸复用表面(每帧十几个 Surface 分配是白扔的性能),
# 内容透明度每帧都可能变,所以 fill 每次都做,只省掉创建
_hudbg_cache = {}


def _hud_bg(w, h, rgba):
    key = (int(w), int(h))
    s = _hudbg_cache.get(key)
    if s is None:
        if len(_hudbg_cache) > 96:
            _hudbg_cache.clear()
        s = pygame.Surface(key, pygame.SRCALPHA)
        _hudbg_cache[key] = s
    s.fill(rgba)
    return s


# ---------- 布局(与 raid.py 交互命中区) ----------
def inv_layout(bag_w=6, bag_h=4, safe_w=2, safe_h=1):
    panel = pygame.Rect(W // 2 - 420, 120, 840, 470)
    cell = 44
    bag = (pygame.Rect(panel.right - 40 - bag_w * cell, panel.y + 80,
                       bag_w * cell, bag_h * cell), cell)
    weapon = pygame.Rect(panel.x + 30, panel.y + 80, 300, 88)
    armor = pygame.Rect(panel.x + 30, panel.y + 180, 300, 88)
    helmet = pygame.Rect(panel.x + 30, panel.y + 280, 300, 58)
    close = pygame.Rect(panel.right - 50, panel.y + 16, 34, 34)
    merge = pygame.Rect(panel.x + 30, panel.bottom - 104, 168, 38)
    drop = pygame.Rect(panel.x + 208, panel.bottom - 104, 132, 38)
    safe_mode = pygame.Rect(panel.x + 360, panel.bottom - 104, 150, 38)
    safe = (pygame.Rect(panel.x + 520, panel.bottom - 110, safe_w * 28,
                        safe_h * 28), 28)
    return dict(panel=panel, bag=bag, weapon=weapon, armor=armor, helmet=helmet,
                close=close, merge=merge, drop=drop,
                safe=safe, safe_mode=safe_mode)


def ask_layout():
    """整理弹药确认框布局。"""
    panel = pygame.Rect(W // 2 - 270, H // 2 - 120, 540, 240)
    yes = pygame.Rect(panel.x + 44, panel.bottom - 76, 210, 48)
    no = pygame.Rect(panel.right - 254, panel.bottom - 76, 210, 48)
    return dict(panel=panel, yes=yes, no=no)


def loot_layout(cw, ch, bag_w=6, bag_h=4, safe_w=2, safe_h=1):
    cell = 34
    cont_w, cont_h = cw * cell, ch * cell
    bag_wp, bag_hp = bag_w * cell, bag_h * cell
    panel_w = max(40 + cont_w + 60 + bag_wp + 40, 560)
    panel = pygame.Rect(W // 2 - panel_w // 2, 140, panel_w,
                        max(cont_h, bag_hp) + 170)
    src = (pygame.Rect(panel.x + 40, panel.y + 90, cont_w, cont_h), cell)
    dst = (pygame.Rect(src[0].right + 60, panel.y + 90, bag_wp, bag_hp), cell)
    half = max(90, (cont_w - 8) // 2)
    searchall = pygame.Rect(src[0].x, src[0].bottom + 14, half, 36)
    takeall = pygame.Rect(src[0].x + half + 8, src[0].bottom + 14,
                          max(90, cont_w - half - 8), 36)
    close = pygame.Rect(panel.right - 50, panel.y + 16, 34, 34)
    safe = (pygame.Rect(dst[0].right - safe_w * 28, dst[0].bottom + 12,
                        safe_w * 28, safe_h * 28), 28)
    return dict(panel=panel, src=src, dst=dst, searchall=searchall,
                takeall=takeall, close=close, safe=safe)


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
        s = _extract_border(r.size, COL["extract"], int(90 + 100 * pulse))
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

    # 我方弹药库(突袭模式:局内补弹,免得子弹打光)
    for sp in getattr(raid, "supplies", []):
        x, y = sp.x + ox, sp.y + oy
        ready = sp.cd <= 0
        col = (150, 220, 140) if ready else (120, 120, 110)
        pygame.draw.rect(screen, (44, 66, 52), (x - 18, y - 18, 36, 36), border_radius=4)
        pygame.draw.rect(screen, col, (x - 18, y - 18, 36, 36), 3, border_radius=4)
        t = get_font(14, bold=True).render("弹", True, col)
        screen.blit(t, t.get_rect(center=(int(x), int(y))))
        lab = get_font(12, bold=True).render(sp.name, True, (160, 225, 170))
        screen.blit(lab, lab.get_rect(center=(x, y - 30)))
        if not ready:
            cd = get_font(12, bold=True).render(f"{int(sp.cd) + 1}s", True, (200, 190, 150))
            screen.blit(cd, cd.get_rect(center=(x, y + 30)))

    # 突袭目标:敌方指挥设施(未摧毁 = 高亮工事;被打坏 = 血条;已摧毁 = 废墟)
    for o in getattr(raid, "objectives", []):
        x, y = o.x + ox, o.y + oy
        if o.destroyed:
            if o.rebuilding:
                # 总指挥部检修队正在抢修:显示进度条,提示玩家赶紧打断
                pygame.draw.rect(screen, (92, 80, 50), (x - 20, y - 20, 40, 40),
                                 border_radius=4)
                pygame.draw.rect(screen, (235, 200, 110), (x - 20, y - 20, 40, 40),
                                 2, border_radius=4)
                _struct_hp_bar(screen, x, y + 28, o, (235, 200, 110))
                t = get_font(13, bold=True).render("抢修中!", True, (255, 200, 110))
                screen.blit(t, t.get_rect(center=(x, y - 34)))
            else:
                pygame.draw.rect(screen, (58, 56, 54), (x - 20, y - 20, 40, 40),
                                 border_radius=4)
                pygame.draw.line(screen, (26, 26, 28), (x - 14, y - 14),
                                 (x + 14, y + 14), 5)
                pygame.draw.line(screen, (26, 26, 28), (x - 14, y + 14),
                                 (x + 14, y - 14), 5)
                t = get_font(12, bold=True).render(f"{o.name} 已摧毁", True,
                                                   (150, 150, 156))
                screen.blit(t, t.get_rect(center=(x, y - 32)))
            continue
        pygame.draw.rect(screen, (120, 96, 58), (x - 20, y - 20, 40, 40),
                         border_radius=4)
        pygame.draw.rect(screen, COL["accent"], (x - 20, y - 20, 40, 40), 3,
                         border_radius=4)
        pygame.draw.circle(screen, COL["accent"], (int(x), int(y)), 6)
        t = get_font(13, bold=True).render(o.name, True, COL["accent"])
        screen.blit(t, t.get_rect(center=(x, y - 34)))
        _struct_hp_bar(screen, x, y + 28, o, (240, 140, 60))

    # 我方前沿设施(指挥所/通讯室):被敌人打坏会停我方援兵
    for o in getattr(raid, "friend_structs", []):
        x, y = o.x + ox, o.y + oy
        if o.destroyed:
            pygame.draw.rect(screen, (52, 54, 58), (x - 18, y - 18, 36, 36),
                             border_radius=4)
            t = get_font(12, bold=True).render(f"{o.name} 已毁", True, (200, 120, 120))
            screen.blit(t, t.get_rect(center=(x, y - 30)))
            continue
        pygame.draw.rect(screen, (48, 78, 62), (x - 18, y - 18, 36, 36),
                         border_radius=4)
        pygame.draw.rect(screen, (110, 200, 120), (x - 18, y - 18, 36, 36), 3,
                         border_radius=4)
        pygame.draw.circle(screen, (200, 240, 200), (int(x), int(y)), 5)
        t = get_font(13, bold=True).render(o.name, True, (150, 230, 160))
        screen.blit(t, t.get_rect(center=(x, y - 32)))
        _struct_hp_bar(screen, x, y + 26, o, (120, 220, 120))
        if o.repair_workers:
            rt = get_font(12, bold=True).render("修理中", True, (235, 220, 130))
            screen.blit(rt, rt.get_rect(center=(x, y + 42)))

    # 已安放的 C4:爆区圈 + 闪烁标记 + 起爆倒计时
    for st in getattr(raid, "structures", []):
        if st.c4 is None:
            continue
        x, y = st.x + ox, st.y + oy
        blink = int(pygame.time.get_ticks() / 240) % 2 == 0
        col = (255, 70, 60) if blink else (255, 195, 90)
        rad = C4_BLAST_RADIUS
        ring = _ring_surface(rad)
        pygame.draw.circle(ring, (*col, 40), (rad, rad), rad)
        pygame.draw.circle(ring, (*col, 200), (rad, rad), rad, 3)
        screen.blit(ring, (x - rad, y - rad))
        pygame.draw.rect(screen, col, (x - 12, y - 12, 24, 24), border_radius=3)
        pygame.draw.line(screen, (20, 20, 20), (x - 8, y - 8), (x + 8, y + 8), 3)
        pygame.draw.line(screen, (20, 20, 20), (x - 8, y + 8), (x + 8, y - 8), 3)
        t = get_font(15, bold=True).render(f"C4 {max(0.0, st.c4['t']):.1f}s", True, col)
        screen.blit(t, t.get_rect(center=(x, y - rad - 14)))

    # 剧情模式:关键点与 NPC 标记
    if raid.mode == "story":
        import story as story_mod
        # 待决定的俘虏:画三个小人;选完之后变成"被放走(往南走)/被处决(尸体)"
        cap = story_mod.CITY_AT.get("captives")
        if cap and raid.story_mission is not None \
                and raid.story_mission["id"] == "d1_1":
            cx = cap[0] * 32 + 16 + ox
            cy = cap[1] * 32 + 16 + oy
            st_cap = getattr(raid, "captive_state", None)
            cs_now = getattr(raid, "cutscene", None)
            for dx, dy in ((-14, 6), (0, -6), (14, 8)):
                fx, fy = cx + dx, cy + dy
                if st_cap == "freed":
                    prog = min(1.0, cs_now["t"] / cs_now["dur"]) \
                        if (cs_now and cs_now["kind"] == "rescue") else 1.0
                    fx, fy = fx + 52 * prog, fy + 46 * prog
                    pygame.draw.circle(screen, (120, 220, 130), (int(fx), int(fy)), 7)
                    pygame.draw.circle(screen, (30, 50, 34), (int(fx), int(fy)), 7, 2)
                elif st_cap == "dead":
                    pygame.draw.ellipse(screen, (120, 40, 40),
                                        (fx - 12, fy - 6, 24, 13))
                    pygame.draw.line(screen, (60, 24, 24),
                                     (fx - 8, fy), (fx + 8, fy), 3)
                else:
                    pygame.draw.circle(screen, (196, 200, 210), (int(fx), int(fy)), 7)
                    pygame.draw.circle(screen, (50, 52, 60), (int(fx), int(fy)), 7, 2)
            if st_cap is None:
                lab0 = get_font(12, bold=True).render("被俘的拾荒者", True,
                                                     (214, 218, 228))
                screen.blit(lab0, lab0.get_rect(center=(cx, cy - 30)))

        for t in raid.story_targets:
            x, y = t.x + ox, t.y + oy
            if x < -60 or x > W + 60 or y < -60 or y > H + 60:
                continue
            done = (t.obj is not None
                    and story_mod.is_done(raid.game.save, t.obj["id"]))
            if t.dia is not None or t.kind == "talk":
                col = (120, 210, 255)              # NPC / 对话点
            else:
                col = COL["good"] if done else COL["accent"]
            if done:
                pygame.draw.circle(screen, col, (int(x), int(y)), 7, 2)
                pygame.draw.line(screen, col, (x - 4, y), (x + 4, y), 2)
            else:
                pts = [(x, y - 9), (x + 9, y), (x, y + 9), (x - 9, y)]
                pygame.draw.polygon(screen, col, pts)
                pygame.draw.polygon(screen, (20, 22, 26), pts, 2)
            lab = get_font(12, bold=True).render(t.name, True, col)
            screen.blit(lab, lab.get_rect(center=(x, y - 20)))

        # 剧情演出:扩散光环 + 中心特效(救人/处决/给药/抢夺)
        cs = getattr(raid, "cutscene", None)
        if cs is not None:
            prog = min(1.0, cs["t"] / max(0.01, cs["dur"]))
            fx, fy = cs["x"] + ox, cs["y"] + oy
            col = {"rescue": (120, 220, 130), "shoot": (230, 90, 70),
                   "aid": (130, 220, 150), "rob": (230, 150, 70),
                   "refuse": (170, 175, 185),
                   "track": (130, 210, 240)}.get(cs["kind"], COL["accent"])
            for k in range(3):
                q = (prog + k * 0.28) % 1.0
                rr = int(14 + 62 * q)
                ring = _ring_surface(rr)
                pygame.draw.circle(ring, (*col, int(200 * (1 - q))), (rr, rr), rr, 3)
                screen.blit(ring, (fx - rr, fy - rr))
            if cs["kind"] == "shoot":
                fl = _ring_surface(28)
                pygame.draw.circle(fl, (255, 240, 190, int(230 * (1 - prog))),
                                   (28, 28), int(10 + 18 * (1 - prog)))
                screen.blit(fl, (fx - 28, fy - 28))
            elif cs["kind"] == "aid":
                cross = pygame.Surface((28, 28), pygame.SRCALPHA)
                pygame.draw.rect(cross, (*col, 235), (10, 3, 8, 22), border_radius=2)
                pygame.draw.rect(cross, (*col, 235), (3, 10, 22, 8), border_radius=2)
                screen.blit(cross, (fx - 14, fy - 14 - int(prog * 28)))

        # 飘字:信任变化 / 选择结果
        for f in getattr(raid, "floaters", []):
            a = max(0.0, 1.0 - f["t"] / f["dur"])
            txt = get_font(16, bold=True).render(f["text"], True, f["col"])
            bg = _hud_bg(txt.get_width() + 14, 24, (10, 12, 14, int(190 * a)))
            fx, fy = f["x"] + ox, f["y"] + oy - int(f["t"] * 22)
            screen.blit(bg, (fx - bg.get_width() // 2, fy))
            screen.blit(txt, txt.get_rect(center=(fx, fy + 12)))

        # 录音字幕:屏幕下方那串字幕
        sub = getattr(raid, "subtitle", None)
        if sub is not None:
            a = min(1.0, sub["t"] / 1.2)
            txt = get_font(18, bold=True).render(sub["text"], True, (238, 240, 246))
            bw = min(W - 120, txt.get_width() + 40)
            bar = _hud_bg(bw, 40, (8, 10, 12, int(210 * a)))
            screen.blit(bar, (W // 2 - bw // 2, H - 150))
            screen.blit(txt, txt.get_rect(center=(W // 2, H - 130)))
            t2 = get_font(13, bold=True).render("▶ 录音", True,
                                               (240, 190, 90))
            screen.blit(t2, (W // 2 - bw // 2 + 12, H - 146))

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

    # 拾荒者(仅玩家视线内可见;无人机侦察期间全图标记)。
    # 可见判定读 raid.fog_vis 缓存(不再每帧每敌人一条射线),先裁掉屏外的。
    recon = getattr(raid, "recon_t", 0.0) > 0
    vis = raid.fog_vis
    for s in raid.scavs:
        if not recon and id(s) not in vis:
            continue
        x, y = s.x + ox, s.y + oy
        if x < -50 or x > W + 50 or y < -50 or y > H + 50:
            continue
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

    # 粒子:整批交给 Surface.blits() 一次贴完。
    # 原来每颗一次 screen.blit(...) —— 一场交火里每帧 180+ 颗,就是 180+ 次
    # Python→C 调用;blits() 让 C 循环跑完整批,顺带把屏幕外的裁掉
    # (爆炸大半发生在视野外,原来也照样逐颗 blit)。
    if raid.particles:
        batch = []
        add = batch.append
        for pt in raid.particles:
            a = pt["ttl"] / pt["max_ttl"]
            rad = int(pt["size"] * a + 1)
            sx = pt["x"] + ox - rad - 1
            sy = pt["y"] + oy - rad - 1
            if sx < -8.0 or sy < -8.0 or sx > W + 8.0 or sy > H + 8.0:
                continue
            add((_particle_sprite(pt["color"], rad, int(255 * a)), (sx, sy)))
        if batch:
            screen.blits(batch, 0)

    # 玩家
    px, py = p.x + ox, p.y + oy
    _draw_player(screen, p, px, py)

    # 战争迷雾 / 夜战光照(乘性压暗,见文件头的 _mask_surface 说明)。
    # 缓存表面只在 fog_version 变化(移动/转头)时"填充 + 打洞",
    # 其它帧只做一次 MULT blit —— 亮区必须保持常亮,不能每帧被填掉。
    dark_mode = getattr(raid, "dark", False)
    layer = _mask_surface("night" if dark_mode else "fog", (W, H))
    if raid._fog_drawn_ver != raid.fog_version:
        raid._fog_drawn_ver = raid.fog_version
        _darken_fill(layer, (*NIGHT_DARK_RGB, 255) if dark_mode else COL["fog"])
        cx, cy = raid.cam[0], raid.cam[1]
        if dark_mode:
            for shape in getattr(raid, "light_shapes", ()):
                if shape[0] == "circle":
                    _, (sx, sy, r, tint) = shape
                    pygame.draw.circle(layer, tint,
                                       (int(sx - cx), int(sy - cy)), int(r))
                else:
                    pts = [(x - cx, y - cy) for x, y in shape[1]]
                    if len(pts) >= 3:
                        pygame.draw.polygon(layer, NIGHT_BEAM_RGB, pts)
        else:
            pts = [(x - cx, y - cy) for x, y in (raid.fog_polygon or ())]
            if len(pts) >= 3:
                pygame.draw.polygon(layer, (255, 255, 255), pts)
    screen.blit(layer, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    # 受击红屏(保持原来的红色蒙版观感:
    # 试过改成加色闪光只快 1.3ms,不值得动画面)
    if p.hurt_flash > 0:
        vs = _overlay("hurt", (W, H), (180, 20, 20, int(90 * p.hurt_flash)))
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

    # 搜刮 / 打药读条(玩家头顶一条,和引导条同一位置逻辑)
    tk = getattr(raid, "take", None)
    hc = getattr(raid, "heal_ch", None)
    if tk is not None or hc is not None:
        if tk is not None:
            ratio = min(1.0, tk["t"] / max(0.01, tk["need"]))
            label, col = "搜索中", COL["good"]
        else:
            ratio = min(1.0, hc["t"] / max(0.01, hc["need"]))
            label, col = "治疗中", (120, 220, 160)
        bw = 110
        bx = px - bw / 2
        by = py - 54
        pygame.draw.rect(screen, (30, 30, 36), (bx, by, bw, 10), border_radius=4)
        pygame.draw.rect(screen, col, (bx, by, bw * ratio, 10), border_radius=4)
        t = get_font(13, bold=True).render(f"{label} {int(ratio * 100)}%", True, col)
        screen.blit(t, t.get_rect(center=(px, by - 12)))

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
    if raid.dialogue is not None:
        _draw_dialogue(raid, screen)
    if raid.over:
        _draw_result(raid, screen)


def _draw_dialogue(raid, screen):
    """对白面板:说话人名字牌 + 台词 + 分支选项(没有立绘,只有名字)。"""
    import bindings
    d = raid.dialogue
    panel = pygame.Rect(W // 2 - 460, H - 300, 920, 210)
    dark = _overlay("dlg_dark", (W, H), (0, 0, 0, 90))
    screen.blit(dark, (0, 0))
    uikit.draw_panel(screen, panel, None)
    # 名字牌
    name = get_font(20, bold=True).render(d["speaker"], True, (18, 20, 24))
    plate = pygame.Rect(panel.x + 26, panel.y - 16, name.get_width() + 34, 34)
    pygame.draw.rect(screen, COL["accent"], plate, border_radius=8)
    screen.blit(name, name.get_rect(center=plate.center))
    f = get_font(19)
    y = panel.y + 30
    if d["reply"] is not None:
        lines = [d["reply"]]
    else:
        lines = d["lines"][:d["idx"] + 1]
    for ln in lines[-3:]:
        t = f.render(ln, True, COL["text"])
        screen.blit(t, (panel.x + 30, y))
        y += 30
    mx, my = pygame.mouse.get_pos()
    next_tip = "点击 / 按 %s 继续" % bindings.label_for(raid.game.save, "interact")
    if d["reply"] is not None:
        t = get_font(16, bold=True).render(next_tip, True, COL["text_dim"])
        screen.blit(t, (panel.right - t.get_width() - 26, panel.bottom - 34))
        return
    if d["idx"] < len(d["lines"]) - 1:
        t = get_font(16, bold=True).render(next_tip, True, COL["text_dim"])
        screen.blit(t, (panel.right - t.get_width() - 26, panel.bottom - 34))
        return
    if d["choices"]:
        t = get_font(15, bold=True).render("选择(按数字键或点击):", True, COL["accent"])
        screen.blit(t, (panel.x + 30, panel.bottom - 118))
        for i, c in enumerate(d["choices"]):
            r = pygame.Rect(panel.x + 30, panel.bottom - 96 + i * 30,
                            panel.w - 60, 26)
            hover = r.collidepoint(mx, my)
            pygame.draw.rect(screen, COL["panel_hi"] if hover else COL["panel"],
                             r, border_radius=5)
            pygame.draw.rect(screen, COL["accent"] if hover else COL["border"],
                             r, 1, border_radius=5)
            ft = get_font(15).render(f"{i + 1}. {c['text']}", True,
                                     COL["accent"] if hover else COL["text"])
            screen.blit(ft, (r.x + 10, r.y + 4))
    else:
        t = get_font(16, bold=True).render(
            "点击 / 按 %s 结束对话" % bindings.label_for(raid.game.save, "interact"),
            True, COL["text_dim"])
        screen.blit(t, (panel.right - t.get_width() - 26, panel.bottom - 34))


def dialogue_layout(raid):
    """对白选项的命中区(点击选择用)。"""
    d = raid.dialogue
    if d is None or d["reply"] is not None or not d["choices"]:
        return []
    panel = pygame.Rect(W // 2 - 460, H - 300, 920, 210)
    return [pygame.Rect(panel.x + 30, panel.bottom - 96 + i * 30, panel.w - 60, 26)
            for i in range(len(d["choices"]))]


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
    # 快捷打药提示(血量过半以下且有医疗品时显示;键名跟玩家改键走)
    if p.hp < p.max_hp * 0.5 and any(pl.item.cat == "med" for pl in p.bag.items):
        t = get_font(14, bold=True).render(
            "按 %s 打药(读条 1~3 秒)" % bindings.label_for(raid.game.save, "heal"),
            True, COL["good"])
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
        # 射击模式(按 G / 手机「模式」按钮切换):全自动武器才有得切
        mode = weapon_fire_mode(p.weapon)
        mcol = {"semi": COL["text_dim"], "burst": (255, 190, 90),
                "auto": COL["good"]}.get(mode, COL["text_dim"])
        mtext = fire_mode_name(mode)
        if len(weapon_fire_modes(p.weapon)) > 1 and not getattr(raid, "touch_mode", False):
            mtext += "(%s 切)" % bindings.label_for(raid.game.save, "firemode")
        mt = get_font(16, bold=True).render(mtext, True, mcol)
        screen.blit(mt, (W - big.get_width() - 26 - mt.get_width() - 16, H - 58))
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

    # 黑暗行动:当前光源状态(没带光源就红字提醒)
    if getattr(raid, "dark", False) and not raid.over:
        beam = weapon_beam(getattr(p, "weapon", None))
        nvg = helmet_nvg(getattr(p, "helmet", None))
        parts = []
        if beam:
            parts.append(f"枪灯 {int(beam[0])}")
        if nvg:
            parts.append(f"夜视 {int(nvg[0])}")
        txt = "黑暗行动 · 光源:" + ("＋".join(parts) if parts else "无")
        if not parts:
            txt += "(只看得见脚边)"
        t = get_font(17, bold=True).render(
            txt, True, COL["good"] if parts else COL["bad"])
        bg = _hud_bg(t.get_width() + 20, 32, (10, 12, 14, 175))
        screen.blit(bg, (20, 16))
        screen.blit(t, (30, 22))

    # 人质模式:任务进度面板
    if raid.mode == "hostage" and not raid.over:
        done = sum(1 for h in raid.hostages if h.rescued)
        alive = sum(1 for a in raid.allies if not a.downed)
        info = f"人质 {done}/{len(raid.hostages)}    队友 {alive}/{len(raid.allies)}"
        t = get_font(18, bold=True).render(info, True, COL["accent"])
        bg = _hud_bg(t.get_width() + 20, 32, (10, 12, 14, 175))
        screen.blit(bg, (20, 16))
        screen.blit(t, (30, 22))

    # 突袭模式:目标进度 + 援兵状态 + 友军支援积分
    if raid.mode == "assault" and not raid.over:
        done = sum(1 for o in raid.objectives if o.destroyed)
        alive = sum(1 for a in raid.allies if not a.downed)
        info = (f"设施 {done}/{len(raid.objectives)}    "
                f"守军 {len(raid.scavs)}   队友 {alive}/{len(raid.allies)}")
        t = get_font(18, bold=True).render(
            info, True, COL["good"] if done >= len(raid.objectives) else COL["accent"])
        bg = _hud_bg(t.get_width() + 20, 32, (10, 12, 14, 175))
        screen.blit(bg, (20, 16))
        screen.blit(t, (30, 22))
        h = _draw_reinf_line(raid, screen, 20, 50)
        _draw_support_panel(raid, screen, 20, 54 + h)

    # 剧情模式:第几天/时段 + 目标勾选 + 状态
    if raid.mode == "story" and not raid.over:
        import story as story_mod
        sd = raid.game.save
        s = story_mod.st(sd)
        m = story_mod.mission(sd)
        head = (f"第 {s['day']} 天 · {story_mod.PERIODS[min(3, s['period'])]} · "
                f"{story_mod.mission_title(sd)}")
        lines = [head]
        if m is not None:
            for o in m["objects"]:
                if o["kind"] == "extract":
                    continue
                mark = "✓" if story_mod.is_done(sd, o["id"]) else "□"
                lines.append(f"  {mark} {o['name']}")
        lines.append(f"数据板 {s['boards']}/3 · 录音 {s['tapes']}/12 · "
                     f"灰狼{story_mod.wolf_state(sd)} · 艾琳{story_mod.erin_state(sd)} · "
                     f"通缉{story_mod.wanted_state(sd)}")
        items = s["flags"].get("items", [])
        if items:
            lines.append("携带:" + "、".join(items))
        f = get_font(15)
        w = max(f.size(ln)[0] for ln in lines) + 24
        bh = 22 * len(lines) + 12
        bg = _hud_bg(w, bh, (10, 12, 14, 180))
        screen.blit(bg, (20, 96))
        yy = 102
        for i, ln in enumerate(lines):
            col = (COL["accent"] if i == 0 else
                   (COL["good"] if "✓" in ln[:4] else COL["text"]))
            t = f.render(ln, True, col)
            screen.blit(t, (32, yy))
            yy += 22

    # 提示(交互键名跟玩家改键走)
    if not (raid.inv_open or raid.loot_target or raid.paused or raid.over):
        prompt = None
        ik = bindings.label_for(raid.game.save, "interact")
        for name, r in raid.map.extracts:
            if r.collidepoint(raid.player.x, raid.player.y):
                prompt = ("撤离区:保持不动完成撤离" if raid.allows_extract()
                          else "先炸掉全部指挥设施才能撤离")
                break
        if prompt is None and raid.channel is not None:
            need = raid.channel_need()
            label = raid.channel_label()
            prompt = f"{label}…{int(min(1.0, raid.channel['t'] / need) * 100)}%"
        if prompt is None and raid.mode in ("hostage", "assault", "story"):
            kind, _ent = raid.nearest_interactable()
            if kind == "rescue":
                prompt = f"{ik}  解救人质"
            elif kind == "revive":
                prompt = f"{ik}  拉起队友"
            elif kind == "destroy":
                prompt = f"{ik}  安放炸药(摧毁设施)"
            elif kind == "supply":
                prompt = f"{ik}  补充弹药(弹药库)"
            elif kind == "story":
                o = _ent.obj
                if o is None or o["kind"] == "talk":
                    prompt = f"{ik}  与 {_ent.name} 交谈"
                elif o["kind"] == "kill":
                    prompt = f"{ik}  {o['name']}(先清掉守军)"
                elif o["kind"] == "download":
                    prompt = f"{ik}  下载:{o['name']}"
                elif o["kind"] == "take":
                    prompt = f"{ik}  取得:{o['name']}"
                else:
                    prompt = f"{ik}  {o['name']}"
        if prompt is None:
            lc = raid.nearest_container()
            if lc is not None:
                prompt = f"{ik}  搜刮 {lc.name}"
        if prompt:
            t = get_font(17, bold=True).render(prompt, True, COL["accent"])
            bg = _hud_bg(t.get_width() + 20, 30, (10, 10, 12, 170))
            screen.blit(bg, (W // 2 - bg.get_width() // 2, H - 120))
            screen.blit(t, (W // 2 - t.get_width() // 2, H - 105))

    # 通知
    y = 56
    for text, ttl, maxttl, color in raid.toasts:
        a = min(1.0, ttl / 0.4)
        t = get_font(15, bold=True).render(text, True, color)
        surf = _hud_bg(t.get_width() + 14, 24, (12, 13, 16, int(180 * a)))
        screen.blit(surf, (W // 2 - surf.get_width() // 2, y))
        screen.blit(t, (W // 2 - t.get_width() // 2, y + 4))
        y += 28


_ring_cache = {}


def _ring_surface(rad):
    """C4 爆区圈的复用表面(每帧新建太贵)。"""
    surf = _ring_cache.get(rad)
    if surf is None:
        surf = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
        _ring_cache[rad] = surf
    surf.fill((0, 0, 0, 0))
    return surf


def _struct_hp_bar(screen, cx, cy, st, color):
    """设施血条(只在被打坏后显示,满血不占画面)。"""
    if st.destroyed or st.hp >= st.max_hp:
        return
    bw = 44
    ratio = max(0.0, st.hp / st.max_hp)
    pygame.draw.rect(screen, (30, 30, 34), (cx - bw / 2, cy, bw, 6), border_radius=3)
    pygame.draw.rect(screen, color, (cx - bw / 2, cy, bw * ratio, 6), border_radius=3)


def _draw_reinf_line(raid, screen, x, y):
    """援兵状态:敌方(通讯站+司令)与我方(指挥所+通讯室)各一行 + C4 倒计时。"""
    f = get_font(14)
    rows = []
    ok, why = raid.reinforce_reason("enemy")
    cnt = max(0, int(raid.enemy_reinf_t))
    rows.append(("敌援兵:" + (f"{cnt:2d}s" if ok else "已切断") + f"({why})",
                 (225, 120, 110) if ok else COL["good"]))
    ok2, why2 = raid.reinforce_reason("ally")
    cnt2 = max(0, int(raid.ally_reinf_t))
    rows.append(("我援兵:" + (f"{cnt2:2d}s" if ok2 else "已切断") + f"({why2})",
                 (150, 210, 150) if ok2 else (225, 120, 110)))
    c4s = [st for st in raid.structures if st.c4 is not None]
    if c4s:
        soon = min(st.c4["t"] for st in c4s)
        rows.append((f"C4 ×{len(c4s)}  最近起爆 {soon:.1f}s  爆区 ±{C4_BLAST_RADIUS}",
                     (255, 120, 90)))
    # 总指挥部反应:前沿失联后的察觉倒计时 / 检修队
    if getattr(raid, "hq_t", None) is not None:
        rows.append((f"总指挥部 {int(max(0, raid.hq_t))}s 后察觉异常(前沿失联)",
                     (255, 150, 120)))
    elif getattr(raid, "hq_team", None):
        com = next((st for st in raid.objectives if st.role == "comms"), None)
        if com is not None and com.rebuilding:
            rows.append(("⚠ 敌方检修队正在抢修通讯站!(打退他们)",
                         (255, 120, 90)))
        else:
            rows.append((f"敌方检修队在场({len(raid.hq_team)} 人)— 去查通讯站",
                         (255, 170, 120)))
    # 面板宽度直接量渲染结果的宽度:Font.size() 要把整串字重新过一遍字形
    # (实测约 0.7ms/次,这里每帧 2~5 次),而 render() 本来就有缓存。
    rendered = [(f.render(txt, True, col), col) for txt, col in rows]
    w = max(t.get_width() for t, _c in rendered) + 20
    h = 22 * len(rows) + 8
    screen.blit(_hud_bg(w, h, (10, 12, 14, 175)), (x, y))
    yy = y + 4
    for t, col in rendered:
        screen.blit(t, (x + 10, yy))
        yy += 22
    return h


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
    lay = inv_layout(p.bag.w, p.bag.h, p.safe.w, p.safe.h)
    uikit.draw_panel(screen, lay["panel"], "背包  (TAB 关闭)")
    _close_button(screen, lay["close"])
    mx, my = pygame.mouse.get_pos()

    uikit.draw_slot(screen, lay["weapon"], p.weapon, "武器",
                    hover=lay["weapon"].collidepoint(mx, my))
    uikit.draw_slot(screen, lay["armor"], p.armor, "护甲",
                    hover=lay["armor"].collidepoint(mx, my))
    uikit.draw_slot(screen, lay["helmet"], p.helmet, "头盔",
                    hover=lay["helmet"].collidepoint(mx, my))
    bag_rect, cell = lay["bag"]
    draw_grid(screen, bag_rect.x, bag_rect.y, p.bag, cell,
              f"出战背包 {p.bag.w}×{p.bag.h}")
    # 携行/自救状态(挪到背包网格下面,别和头盔槽打架)
    ry = get_font(14)
    ty = bag_rect.bottom + 8
    t = ry.render(f"携行容量 {p.bag.w}×{p.bag.h} 格(战局内不可换包)",
                  True, COL["text_dim"])
    screen.blit(t, (bag_rect.x, ty))
    if p.armor is not None and p.armor.def_.get("revive"):
        rv = "已用" if raid.revive_used else "可用"
        col = COL["text_dim"] if raid.revive_used else COL["good"]
        t = ry.render(f"倒地自救:{rv}(每局一次)", True, col)
        screen.blit(t, (bag_rect.x, ty + 22))
    if p.helmet is not None and p.helmet.def_.get("nvg"):
        t = ry.render(f"夜视仪:半径 {int(p.helmet.def_['nvg'][0])}", True,
                      (140, 220, 160))
        screen.blit(t, (bag_rect.x, ty + 44))
    elif p.helmet is not None and p.helmet.def_.get("reduce"):
        t = ry.render(f"头盔额外减伤:{int(p.helmet.def_['reduce'] * 100)}%",
                      True, COL["text_dim"])
        screen.blit(t, (bag_rect.x, ty + 44))
    # 打药读条(在面板上也显示一条,免得只看画面顶部)
    hc = getattr(raid, "heal_ch", None)
    if hc is not None:
        ratio = min(1.0, hc["t"] / max(0.01, hc["need"]))
        bar = pygame.Rect(bag_rect.x, ty + 68, bag_rect.w, 14)
        pygame.draw.rect(screen, COL["grid_bg"], bar, border_radius=4)
        pygame.draw.rect(screen, COL["good"],
                         (bar.x, bar.y, int(bar.w * ratio), bar.h), border_radius=4)
        tt = get_font(13, bold=True).render(
            f"治疗中 {int(ratio * 100)}%", True, (240, 240, 240))
        screen.blit(tt, tt.get_rect(center=bar.center))
    # 整理弹药 / 丢弃模式 / 保险箱存入
    draw_button(screen, lay["merge"], "整理弹药(叠至 120 发/组)",
                hover=lay["merge"].collidepoint(mx, my), small=True)
    drop_on = getattr(raid, "drop_mode", False)
    draw_button(screen, lay["drop"],
                "丢弃模式:开" if drop_on else "丢弃模式:关",
                hover=lay["drop"].collidepoint(mx, my), small=True)
    sm_on = getattr(raid, "safe_mode", False)
    draw_button(screen, lay["safe_mode"],
                "保险箱存入:开" if sm_on else "保险箱存入:关",
                hover=lay["safe_mode"].collidepoint(mx, my), small=True)
    # 保险箱网格(阵亡不丢)
    safe_rect, safe_cell = lay["safe"]
    draw_grid(screen, safe_rect.x, safe_rect.y, p.safe, safe_cell)
    t = get_font(13, bold=True).render("保险箱", True,
                                       COL["good"] if sm_on else COL["text_dim"])
    screen.blit(t, (safe_rect.right + 8, safe_rect.y + 1))
    t = get_font(12).render("阵亡不丢", True, COL["text_dim"])
    screen.blit(t, (safe_rect.right + 8, safe_rect.y + 17))
    hint = ("丢弃模式已开:点物品/装备槽 = 丢在脚边" if drop_on else
            "保险箱存入已开:点背包物品 = 存进保险箱" if sm_on else
            "左键:使用/装备   右键:丢弃   点装备槽:卸下")
    if raid.touch_mode and not drop_on and not sm_on:
        hint += "   手机:开「丢弃模式」再点物品 · 长按看详情"
    t = get_font(14).render(hint, True,
                            COL["accent"] if (drop_on or sm_on) else COL["text_dim"])
    screen.blit(t, (lay["panel"].x + 30, lay["panel"].bottom - 34))

    hovered = grid_hit_px(p.bag, lay["bag"], (mx, my))
    if hovered is None:
        hovered = grid_hit_px(p.safe, lay["safe"], (mx, my))
    if hovered is None and lay["weapon"].collidepoint(mx, my) and p.weapon:
        draw_tooltip(screen, mx, my, p.weapon)
    elif hovered is None and lay["armor"].collidepoint(mx, my) and p.armor:
        draw_tooltip(screen, mx, my, p.armor)
    elif hovered is None and lay["helmet"].collidepoint(mx, my) and p.helmet:
        draw_tooltip(screen, mx, my, p.helmet)
    if hovered is not None:
        draw_tooltip(screen, mx, my, hovered.item)
    # 触屏长按信息面板(最上层)
    uikit.draw_hold(screen, getattr(raid, "hold", None))


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
    lay = loot_layout(lc.container.w, lc.container.h, p.bag.w, p.bag.h,
                      p.safe.w, p.safe.h)
    uikit.draw_panel(screen, lay["panel"], f"搜刮:{lc.name}  (E/ESC 关闭)")
    _close_button(screen, lay["close"])
    mx, my = pygame.mouse.get_pos()

    src_rect, cell = lay["src"]
    draw_grid(screen, src_rect.x, src_rect.y, lc.container, cell)
    # 没搜过的物品:盖一块灰板,只露出它占的形状(玩家搜出来才知道是什么)
    unknown = [pl for pl in lc.container.items if not raid.is_known(pl)]
    for pl in unknown:
        iw, ih = pl.item.size()
        r = pygame.Rect(src_rect.x + pl.x * cell, src_rect.y + pl.y * cell,
                        iw * cell, ih * cell)
        pygame.draw.rect(screen, (58, 62, 70), r)
        pygame.draw.rect(screen, (94, 100, 112), r, 2)
        q = get_font(20, bold=True).render("?", True, (150, 156, 168))
        screen.blit(q, q.get_rect(center=r.center))
    dst_rect, cell2 = lay["dst"]
    draw_grid(screen, dst_rect.x, dst_rect.y, p.bag, cell2, "你的背包")
    # 保险箱(阵亡不丢):背包满时「拿走」会自动塞进来
    srect, scell = lay["safe"]
    draw_grid(screen, srect.x, srect.y, p.safe, scell)
    t = get_font(13, bold=True).render("保险箱", True, COL["text_dim"])
    screen.blit(t, (srect.right + 6, srect.y + 1))

    draw_button(screen, lay["searchall"], "全部搜出",
                hover=lay["searchall"].collidepoint(mx, my), small=True)
    n_known = sum(1 for pl in lc.container.items if raid.is_known(pl))
    draw_button(screen, lay["takeall"],
                f"全部拿走({n_known})" if n_known else "全部拿走",
                hover=lay["takeall"].collidepoint(mx, my) and n_known > 0,
                small=True)
    # 搜刮读条:正在搜的那件物品上画进度
    tk = getattr(raid, "take", None)
    if tk is not None and tk["lc"] is lc and tk["item"] in lc.container.items:
        placed = tk["item"]
        iw, ih = placed.item.size()
        r = pygame.Rect(src_rect.x + placed.x * cell, src_rect.y + placed.y * cell,
                        iw * cell, ih * cell)
        hl = _hud_bg(r.w, r.h, (120, 200, 120, 70))
        screen.blit(hl, r)
        pygame.draw.rect(screen, COL["good"], r, 3)
        ratio = min(1.0, tk["t"] / max(0.01, tk["need"]))
        bar = pygame.Rect(r.x, r.bottom + 4, r.w, 5)
        pygame.draw.rect(screen, COL["grid_bg"], bar, border_radius=3)
        pygame.draw.rect(screen, COL["good"],
                         (bar.x, bar.y, int(bar.w * ratio), bar.h), border_radius=3)
        tt = get_font(13, bold=True).render(
            f"搜索中 {int(ratio * 100)}%", True, COL["good"])
        screen.blit(tt, tt.get_rect(center=(r.centerx, r.y - 12)))
        if tk.get("queue"):
            tq = get_font(13).render(f"队列中还有 {len(tk['queue'])} 件",
                                     True, COL["text_dim"])
            screen.blit(tq, (src_rect.x, src_rect.bottom + 12))
    elif unknown:
        tq = get_font(13).render(f"还有 {len(unknown)} 件没搜(点它开始搜索,"
                                 f"1~2 秒/件)", True, COL["text_dim"])
        screen.blit(tq, (src_rect.x, src_rect.bottom + 12))
    hint = ("左键未知物品:搜索(1~2 秒)   左键已知物品:直接拿走   空手时武器/护甲会装备"
            "   背包满时会自动塞进保险箱"
            if tk is None else "搜索中…走远或关窗会中断")
    t = get_font(14).render(hint, True, COL["text_dim"])
    screen.blit(t, (lay["panel"].x + 30, lay["panel"].bottom - 34))

    h1 = grid_hit_px(lc.container, lay["src"], (mx, my))
    h2 = grid_hit_px(p.bag, lay["dst"], (mx, my))
    h3 = grid_hit_px(p.safe, lay["safe"], (mx, my))
    if h1 is not None:
        if raid.is_known(h1):
            draw_tooltip(screen, mx, my, h1.item)
        else:
            tt = get_font(14, bold=True).render("未知物品(点它搜索)", True,
                                               (176, 182, 194))
            screen.blit(tt, (mx + 14, my + 6))
    elif h2 is not None:
        draw_tooltip(screen, mx, my, h2.item)
    elif h3 is not None:
        draw_tooltip(screen, mx, my, h3.item)
    # 触屏长按信息面板(最上层)
    uikit.draw_hold(screen, getattr(raid, "hold", None))


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
                f"支援呼叫 {r.get('support_calls', 0)} 次   "
                f"我方援兵 {r.get('ally_waves', 0)} 波")
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
        obj = (f"设施 {r.get('objectives_done', 0)}/{r.get('objectives', 0)}   "
               f"司令{'已击毙' if r.get('commander_killed') else '逃脱'}   "
               f"敌援兵 {r.get('enemy_waves', 0)} 波 —— "
               + ("任务完成!要塞已被瘫痪" if ok else "任务失败"))
        t = get_font(20, bold=True).render(obj, True,
                                           COL["good"] if ok else COL["bad"])
        screen.blit(t, t.get_rect(center=(W // 2, 244)))
        t = get_font(15).render("系统配发装备与战利品已回收,仓库配置未变动",
                                True, COL["text_dim"])
        screen.blit(t, t.get_rect(center=(W // 2, 274)))

    elif r.get("mode") == "story":
        sd = raid.game.save
        import story as story_mod
        s = story_mod.st(sd)
        note = r.get("story_note", "")
        if note:
            t = get_font(16).render(note, True, COL["accent"])
            screen.blit(t, t.get_rect(center=(W // 2, 244)))
        if s.get("ending"):
            data = story_mod.ENDINGS[s["ending"]]
            t = get_font(22, bold=True).render(data["name"], True, COL["good"])
            screen.blit(t, t.get_rect(center=(W // 2, 286)))
            for i, ln in enumerate(story_mod.wrap(data["text"], 46)[:3]):
                t = get_font(16).render(ln, True, COL["text"])
                screen.blit(t, t.get_rect(center=(W // 2, 318 + i * 24)))
            t = get_font(18, bold=True).render(f"「{data['line']}」", True,
                                               COL["accent"])
            screen.blit(t, t.get_rect(center=(W // 2, 404)))
        else:
            t = get_font(15).render(
                f"数据板 {s['boards']}/3 · 录音 {s['tapes']}/12 · "
                f"灰狼{story_mod.wolf_state(sd)} · 艾琳{story_mod.erin_state(sd)} · "
                f"通缉{story_mod.wanted_state(sd)}", True, COL["text_dim"])
            screen.blit(t, t.get_rect(center=(W // 2, 276)))
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
