# -*- coding: utf-8 -*-
"""把角色设定图(多视图白底)加工成游戏用的玩家立绘。

输入:一张白底的三视图设定图(正面 / 侧面 / 背面,横向排开)。
输出:art/player_front.png、player_side.png、player_back.png(透明底),
      以及 art/_preview.png(缩放预览,人工确认抠图效果)。

处理步骤(纯 pygame,不依赖 Pillow / numpy):
  1. 按"整列全白"把画面切成若干个视图区块;
  2. 从图像四边做 flood fill 认背景(不是"所有白色"都抠掉,围裙/头纱等
     被轮廓线包住的白色区域会保留 —— 这点很关键);
  3. 贴着背景的浅色像素按亮度给半透明,消掉锯齿白边;
  4. 裁紧边界后,按"脚底中心"(底部 8% 行里不透明像素的平均 x)水平对齐,
     让三个视图换方向时人不会左右跳。

用法:
    python tools/make_player_art.py <设定图路径> [--height 160]
"""
import os
import sys

import pygame

# 背景判定:三个通道都亮到这个值以上才算"背景白"
BG_HARD = 238
# 边缘柔化:通道最小值低于此值就是实心,介于中间按比例给 alpha
BG_SOFT = 190
MIN_VIEW_W = 24          # 宽于此值才算一个视图(远小于正常人形宽度)


def load_rgb(path):
    surf = pygame.image.load(path)
    if surf.get_bitsize() != 24 and surf.get_alpha() is not None:
        # 已经是带透明的输入:先铺白底再处理
        base = pygame.Surface(surf.get_size())
        base.fill((255, 255, 255))
        base.blit(surf, (0, 0))
        base = base.convert(24)
        return base.get_width(), base.get_height(), pygame.image.tostring(base, "RGB")
    surf = surf.convert(24)
    return surf.get_width(), surf.get_height(), pygame.image.tostring(surf, "RGB")


def background_mask(w, h, rgb):
    """返回 bytearray:1 = 背景候选(够白)。"""
    bg = bytearray(w * h)
    for i in range(w * h):
        j = i * 3
        r = rgb[j]
        g = rgb[j + 1]
        b = rgb[j + 2]
        m = r if r < g else g
        if b < m:
            m = b
        if m >= BG_HARD:
            bg[i] = 1
    return bg


def flood_from_border(out, bg, w, h):
    """从四边漫水填充,只在 bg 里扩散;结果写到 out(1 = 确实是背景)。"""
    stack = []
    push = stack.append
    for x in range(w):
        for y in (0, h - 1):
            i = y * w + x
            if bg[i] and not out[i]:
                push(i)
    for y in range(h):
        for x in (0, w - 1):
            i = y * w + x
            if bg[i] and not out[i]:
                push(i)
    while stack:
        i = stack.pop()
        if out[i] or not bg[i]:
            continue
        row = (i // w) * w
        x0 = i - row
        while x0 > 0 and bg[row + x0 - 1] and not out[row + x0 - 1]:
            x0 -= 1
        x1 = i - row
        while x1 < w - 1 and bg[row + x1 + 1] and not out[row + x1 + 1]:
            x1 += 1
        for x in range(x0, x1 + 1):
            out[row + x] = 1
        if row >= w:
            up = row - w
            for x in range(x0, x1 + 1):
                j = up + x
                if bg[j] and not out[j]:
                    push(j)
        if row < (h - 1) * w:
            dn = row + w
            for x in range(x0, x1 + 1):
                j = dn + x
                if bg[j] and not out[j]:
                    push(j)


def build_rgba(w, h, rgb, out):
    """背景 -> 全透明;紧贴背景的浅色像素按亮度给半透明(去白边)。"""
    alpha = bytearray(b"\xff" * (w * h))
    for i in range(w * h):
        if out[i]:
            alpha[i] = 0
    rgba = bytearray(w * h * 4)
    rgba[0::4] = rgb[0::3]
    rgba[1::4] = rgb[1::3]
    rgba[2::4] = rgb[2::3]
    rgba[3::4] = alpha
    span = float(BG_HARD - BG_SOFT)
    for y in range(h):
        for x in range(w):
            i = y * w + x
            if out[i]:
                continue
            near_bg = ((x > 0 and out[i - 1]) or (x < w - 1 and out[i + 1])
                       or (y > 0 and out[i - w]) or (y < h - 1 and out[i + w]))
            if not near_bg:
                continue
            j = i * 3
            m = min(rgb[j], rgb[j + 1], rgb[j + 2])
            if m <= BG_SOFT:
                continue
            a = int(255 * (BG_HARD - m) / span)
            rgba[i * 4 + 3] = 0 if a < 0 else (255 if a > 255 else a)
    return bytes(rgba)


def crop_centered(rgba, w, label, labels, box, cx):
    """裁到 bbox(不属于本视图的像素抹掉),左右补透明使锚点落在图宽正中。"""
    x0, y0, x1, y1 = box
    cw = x1 - x0 + 1
    ch = y1 - y0 + 1
    left = int(round(cx - x0))              # 锚点在原 bbox 里的列号
    half = max(left, cw - 1 - left)         # 两侧留出同样的余量
    out_w = half * 2 + 3
    buf = bytearray(out_w * ch * 4)
    ox = half - left + 1
    for y in range(ch):
        src_row = (y0 + y) * w
        dst = (y * out_w + ox) * 4
        x = 0
        while x < cw:
            j = src_row + x0 + x
            if label[j] in labels:
                k = x
                while k + 1 < cw and label[src_row + x0 + k + 1] in labels:
                    k += 1
                n = (k - x + 1) * 4
                src = j * 4
                buf[dst:dst + n] = rgba[src:src + n]
                dst += n
                x = k + 1
            else:
                dst += 4          # 异视图的像素留透明
                x += 1
    return out_w, ch, bytes(buf)


def components(w, h, alpha):
    """不透明像素的连通域(扫描线漫水)。

    返回 (comps, label):comps[i] = (面积, x0, y0, x1, y1);
    label 是整幅图的 bytearray,值为该像素所属连通域编号(1 起;0 = 背景)。
    label 用来在裁剪时把"不属于本视图"的像素抹掉 —— 三视图的矩形范围
    可能互相重叠(比如侧视图的尾巴伸进了背视图的矩形里)。
    """
    seen = bytearray(w * h)
    label = bytearray(w * h)
    comps = []
    for start in range(w * h):
        if seen[start] or not alpha[start]:
            continue
        seen[start] = 1
        label[start] = len(comps) + 1
        stack = [start]
        n = 0
        x0 = x1 = start % w
        y0 = y1 = start // w
        while stack:
            i = stack.pop()
            n += 1
            row = (i // w) * w
            xa = i - row
            ya = i // w
            if xa < x0:
                x0 = xa
            if xa > x1:
                x1 = xa
            if ya < y0:
                y0 = ya
            if ya > y1:
                y1 = ya
            lo = xa
            while lo > 0 and alpha[row + lo - 1] and not seen[row + lo - 1]:
                lo -= 1
            hi = xa
            while hi < w - 1 and alpha[row + hi + 1] and not seen[row + hi + 1]:
                hi += 1
            for x in range(lo, hi + 1):
                j = row + x
                if not seen[j]:
                    seen[j] = 1
                    label[j] = len(comps) + 1
            for nb in (row - w, row + w):
                if nb < 0 or nb >= w * h:
                    continue
                for x in range(lo, hi + 1):
                    j = nb + x
                    if alpha[j] and not seen[j]:
                        seen[j] = 1
                        label[j] = len(comps) + 1
                        stack.append(j)
        comps.append((n, x0, y0, x1, y1, len(comps) + 1))
    comps.sort(reverse=True)
    return comps, label


def group_views(comps, w, h):
    """挑出三个视图:按连通域面积取最大的三个,横向排序。

    小的零碎连通域(飘出去的发丝、单独画的小配件)如果落在某个视图的
    矩形范围内,就并进那个视图。设定图基本就是"三个独立人形",这样最稳。
    """
    big = [c for c in comps if c[0] >= max(300, comps[0][0] * 0.02)]
    if len(big) < 3:
        raise SystemExit(f"只找到 {len(big)} 个视图,请检查设定图是否横向排开三视图")
    views = sorted(big[:3], key=lambda c: c[1])
    views = [dict(x0=c[1], y0=c[2], x1=c[3], y1=c[4], area=c[0], labels={c[5]})
             for c in views]
    for c in comps[3:]:
        n, cx0, cy0, cx1, cy1, cid = c
        mx = (cx0 + cx1) // 2
        my = (cy0 + cy1) // 2
        for g in views:
            if g["x0"] <= mx <= g["x1"] and g["y0"] <= my <= g["y1"]:
                g["x0"] = min(g["x0"], cx0)
                g["y0"] = min(g["y0"], cy0)
                g["x1"] = max(g["x1"], cx1)
                g["y1"] = max(g["y1"], cy1)
                g["area"] += n
                g["labels"].add(cid)
                break
    print("视图(面积 左 上 右 下): "
          f"{[(g['area'], g['x0'], g['y0'], g['x1'], g['y1']) for g in views]}")
    return views


def anchor_x(alpha, w, box):
    """视图锚点:不透明像素 x 的中位数(对单侧伸出的尾巴/披风不敏感)。"""
    x0, y0, x1, y1 = box
    xs = []
    for y in range(y0, y1 + 1):
        row = y * w
        for x in range(x0, x1 + 1):
            if alpha[row + x] > 128:
                xs.append(x)
    if not xs:
        return (x0 + x1) / 2.0
    xs.sort()
    return float(xs[len(xs) // 2])


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python tools/make_player_art.py <设定图路径> [--height 160]")
        return 1
    src = args[0]
    height = 160
    for a in sys.argv[1:]:
        if a.startswith("--height"):
            height = int(a.split("=", 1)[1]) if "=" in a else 160
    here = os.path.dirname(os.path.abspath(__file__))
    out_dir = os.path.join(os.path.dirname(here), "art")
    os.makedirs(out_dir, exist_ok=True)

    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pygame.init()
    pygame.display.set_mode((1, 1))

    w, h, rgb = load_rgb(src)
    print(f"输入 {src} {w}x{h}")
    bg = background_mask(w, h, rgb)
    out = bytearray(w * h)
    flood_from_border(out, bg, w, h)
    kept = w * h - sum(out)
    print(f"背景像素 {sum(out)} / 保留 {kept}")
    rgba = build_rgba(w, h, rgb, out)
    alpha = rgba[3::4]
    comps, label = components(w, h, alpha)
    print(f"连通域 {len(comps)} 个,前 8 大: "
          f"{[(c[0], c[1], c[2], c[3], c[4]) for c in comps[:8]]}")
    views = group_views(comps, w, h)
    print(f"切出 {len(views)} 个视图: "
          f"{[(v['x0'], v['y0'], v['x1'], v['y1']) for v in views]}")
    names = ["player_front", "player_side", "player_back"]
    previews = []
    for idx, view in enumerate(views[:3]):
        box = (view["x0"], view["y0"], view["x1"], view["y1"])
        cx = anchor_x(alpha, w, box)
        cw, ch, buf = crop_centered(rgba, w, label, view["labels"], box, cx)
        surf = pygame.image.fromstring(bytes(buf), (cw, ch), "RGBA")
        scale = height / float(ch)
        surf = pygame.transform.smoothscale(surf, (max(1, int(cw * scale)), height))
        name = names[idx] if idx < len(names) else f"player_extra{idx}"
        path = os.path.join(out_dir, name + ".png")
        pygame.image.save(surf, path)
        print(f"{name}: 源 {cw}x{ch} -> {surf.get_size()}  {path}")
        previews.append((name, surf))

    # 预览拼图:三种视图并排放在一列,黑底白底各一半便于看边缘
    ph = max(s.get_height() for _, s in previews)
    pw = sum(s.get_width() for _, s in previews) + 20 * (len(previews) + 1)
    sheet = pygame.Surface((pw, ph + 40))
    sheet.fill((255, 255, 255))
    pygame.draw.rect(sheet, (70, 70, 78), (0, 0, pw, (ph + 40) // 2))
    x = 20
    for name, s in previews:
        sheet.blit(s, (x, (ph + 40 - s.get_height()) // 2))
        x += s.get_width() + 20
    prev = os.path.join(out_dir, "_preview.png")
    pygame.image.save(sheet, prev)
    print(f"预览 {prev}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
