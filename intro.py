# -*- coding: utf-8 -*-
"""玩法简介:启动时(首次)与藏身处「玩法简介」按钮都会打开。"""
import pygame

from settings import W, H, COL, get_font

PAGES = [
    ("怎么玩?—— 搜打撤!",
     ["① 藏身处整备:把仓库里的枪/甲/弹药/药品放进出战栏",
      "② 右侧选「出战地图」和「战局难度」,点「开始战局」进图",
      "③ 局内搜刮补给箱 / 保险箱(靠近按 E 搜刮),小心拾荒者",
      "④ 走到任意撤离点(画面边缘箭头指引),站定 3 秒撤离",
      "⑤ 撤离成功 = 物资带回仓库;阵亡/超时 = 带入装备全丢!",
      "",
      "赚到的杂物/贵重品去「交易所」卖钱,再买更好的装备。"]),
    ("电脑操作",
     ["WASD 移动      Shift 慢走      鼠标瞄准",
      "左键开火(可长按)      长按右键 = 架枪,精度大幅提升",
      "弹匣打空会自动换弹;R 可提前补弹",
      "H 快捷打药(自动挑最合适的药,不用开背包)",
      "E 搜刮      TAB 背包(用医疗/换装备,右键丢弃)      ESC 暂停",
      "",
      "交易所:点顶部分区(枪械/护甲/背包/子弹/药品),滚轮翻看"]),
    ("手机操作(触屏)",
     ["左半屏拖动 = 移动(推一半距离就是半速)",
      "右侧按钮:开火 / 架枪 / 装填 / 打药 / 搜刮 / 背包",
      "★ 自动锁敌:自动瞄准视野内最近的敌人,瞄准框会套住他",
      "  —— 手机不用自己瞄准,专心走位和开火即可",
      "打开背包 / 搜刮窗口时,直接用手指点格子即可操作",
      "",
      "在藏身处点「手机模式:开/关」可以随时切换(电脑上也能试)"]),
    ("人质模式(室内近战)",
     ["藏身处「游戏模式」切到「人质解救」,会进入专门的人质大楼",
      "★ 目标:找到并解救 4 名人质(靠近按 E,站定读条),全部救出后撤离",
      "★ 你有 3 名队友 AI 一起推进:自动开火,倒地后靠近按 E 拉起",
      "★ 敌人最多 6 个,但整张图 95% 是房间和走廊,拐角都有死角",
      "  (地上有暗色死角标记):进门前贴墙排点,别直接从正面冲",
      "",
      "提示:室内别站在走廊正中,靠墙推进,听枪声判断敌人"]),
    ("头目与发财路",
     ["三张地图各有一位头目 + 手下:击杀必掉 5 级甲和他的专属枪械",
      "强化封锁难度会有「作者」扛 RPG:火箭弹穿 6 级甲只掉一半血,",
      "没穿 6 级甲会被一炮带走 —— 弹药溅射范围很大,别贴脸",
      "机密文件(¥100 亿)只在强化封锁的保险箱里,摸到就发财",
      "",
      "越高难度物资越肥,但敌人也越多越强。祝好运!"]),
]


def draw(screen, page):
    title, lines = PAGES[page]
    screen.fill((16, 18, 22))
    t = get_font(32, bold=True).render(title, True, COL["accent"])
    screen.blit(t, t.get_rect(center=(W // 2, 90)))
    f = get_font(19)
    y = 170
    for ln in lines:
        if ln:
            col = COL["text"] if not ln.startswith("★") else COL["good"]
            s = f.render(ln, True, col)
            screen.blit(s, (170, y))
        y += 34
    # 页码与操作提示
    dots = "  ".join("●" if i == page else "○" for i in range(len(PAGES)))
    d = get_font(20).render(dots, True, COL["accent"])
    screen.blit(d, d.get_rect(center=(W // 2, H - 80)))
    tip = "点击 / 按空格 继续" if page < len(PAGES) - 1 else "点击 / 按空格 开始游戏"
    s = get_font(17, bold=True).render(tip, True, COL["text"])
    screen.blit(s, s.get_rect(center=(W // 2, H - 44)))


def advance(page):
    """翻页;返回新页码(读完了返回 None)。"""
    if page >= len(PAGES) - 1:
        return None
    return page + 1
