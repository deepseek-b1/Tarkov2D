# -*- coding: utf-8 -*-
"""无头自检:全部核心系统逻辑验证,不弹窗口。
用法: python main.py --selftest  (或 Tarkov2D.exe --selftest)
结果写入 selftest_report.txt 并打印。"""
import math
import os
import random
import sys
import tempfile
import traceback


def run():
    import pygame
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    pygame.init()
    pygame.display.set_mode((1, 1))

    # 固定随机种子:保证自检可复现,避免偶发假失败
    random.seed(20260928)

    # 隔离存档目录,不碰真实存档
    import save as save_mod
    save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="tarkov2d_test_")
    save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")

    from settings import ITEMS, PLAYER
    from inventory import Item, Container, try_move

    results = []

    def check(name, fn):
        try:
            fn()
            results.append((name, True, ""))
            print(f"[PASS] {name}")
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"[FAIL] {name}: {e}")
            traceback.print_exc()

    # ---------- 容器 ----------
    def t_container():
        c = Container(6, 4)
        assert c.add_item(Item("bandage"))
        assert c.add_item(Item.weapon("ak74", mag=30))
        p = c.at(0, 0)
        assert p is not None and p.item.iid == "bandage"
        assert not c.add_item(Item("medkit")) or True  # 只验证不崩溃
        c.remove_placed(p)
        assert c.at(0, 0) is None

    def t_stacking():
        maxs = Item("a9").max_stack()
        c = Container(3, 1)
        assert c.add_item(Item("a9", count=20))
        assert len(c.items) == 1
        assert c.add_item(Item("a9", count=20))
        counts = sorted(p.item.count for p in c.items)
        assert counts == [40], counts
        # 满堆 + 无空间:放不下且不修改容器
        c2 = Container(1, 1)
        assert c2.add_item(Item("a9", count=maxs))
        assert not c2.add_item(Item("a9", count=maxs))
        assert len(c2.items) == 1 and c2.items[0].item.count == maxs

    def t_rotate():
        c = Container(2, 5)
        it = Item("ak74")   # 5×2 原始放不下,必须旋转成 2×5
        assert c.add_item(it)
        p = c.items[0]
        assert p.item.rot is True
        assert p.item.size() == (2, 5)
        assert not Container(1, 5).add_item(Item("ak74"))

    def t_trymove():
        maxs = Item("a9").max_stack()
        src = Container(1, 1)
        dst = Container(1, 1)
        assert dst.add_item(Item("a9", count=maxs - 1))
        assert src.add_item(Item("a9", count=10))
        placed = src.items[0]
        assert try_move(src, placed, dst) is True   # 部分合并
        assert dst.items[0].item.count == maxs
        assert src.items[0].item.count == 10 - 1

    def t_serialize():
        c = Container(6, 4)
        c.add_item(Item.weapon("ak74", mag=17))
        c.add_item(Item("a9", count=25))
        c2 = Container.deserialize(6, 4, c.serialize())
        assert len(c2.items) == 2
        w = c2.items[0].item
        assert w.iid == "ak74" and w.state.get("mag") == 17
        assert c2.items[1].item.count == 25

    # ---------- 地图 ----------
    def t_map():
        from world import GameMap
        from settings import MAPS
        for key in ("border", "tv", "port", "indoor"):
            m = GameMap(key)
            assert m.map_name == MAPS[key]["name"], key
            assert m.spawn is not None, key
            assert len(m.extracts) == 3, key
            assert len(m.loot) >= 20, (key, len(m.loot))
            assert len(m.scav_spawns) >= 6, (key, len(m.scav_spawns))
            sx, sy = m.spawn
            assert not m.collides(sx, sy, PLAYER["radius"]), key
            spawn_tile = (int(sx // 32), int(sy // 32))
            # 撤离点 / 保险箱 必须从出生点可达(防封死区域)
            for name, r in m.extracts:
                t = (int(r.centerx // 32), int(r.centery // 32))
                assert m.astar(spawn_tile, t) is not None, f"{key} 撤离点不可达:{name}"
            for lc in [c for c in m.loot if c.kind == "val"]:
                t = (int(lc.rect.centerx // 32), int(lc.rect.centery // 32))
                assert m.astar(spawn_tile, t) is not None, f"{key} 保险箱不可达"
            if key == "indoor":
                # 室内图(人质模式):没有头目/手下,但有人质与队友出生点
                assert m.boss_spawn is None and m.author_spawn is None, key
            else:
                assert m.boss_spawn is not None, key
                assert len(m.guard_spawns) >= 3, key
                bx, by = m.boss_spawn
                assert not m.collides(bx, by, 12), key
                assert m.astar(spawn_tile, (int(bx // 32), int(by // 32))) is not None, key
                for gx, gy in m.guard_spawns:
                    assert not m.collides(gx, gy, 12), key
            # 水域只在港口出现
            has_water = any("W" in row for row in MAPS[key]["rows"])
            assert has_water == (key == "port"), (key, has_water)
        m = GameMap()          # 默认地图
        assert m.map_key == "border"
        assert m.collides(16, 16, 10)   # 边界墙
        pts = m.visibility_polygon(*m.spawn, 560)
        assert len(pts) == 140
        for px, py in pts:
            assert math.hypot(px - m.spawn[0], py - m.spawn[1]) <= 560 + 40

    def t_los():
        from world import GameMap
        m = GameMap()
        # 兵营内隔墙 x=7 挡视线: 瓦片(3,2) 与 (9,2) 之间
        a = (3 * 32 + 16, 2 * 32 + 16)
        b = (9 * 32 + 16, 2 * 32 + 16)
        assert not m.los_clear(*a, *b)
        # 开阔地 y=12 行畅通
        assert m.los_clear(2 * 32 + 16, 12 * 32 + 16, 8 * 32 + 16, 12 * 32 + 16)

    def t_astar():
        from world import GameMap
        m = GameMap()
        path = m.astar((24, 17), (44, 20))
        assert path and len(path) > 2
        assert path[0] == (24, 17) and path[-1] == (44, 20)
        assert m.astar((24, 17), (0, 0)) is None  # 墙体不可达

    # ---------- 存档 ----------
    def t_save():
        sd = save_mod.load_data()
        n0 = sd.stash.item_count()
        sd.armor = Item("paca")
        sd.stash.add_item(Item("btc"))
        save_mod.save_data(sd)
        sd2 = save_mod.load_data()
        assert sd2.armor is not None and sd2.armor.iid == "paca"
        assert sd2.stash.item_count() == n0 + 1
        assert sd2.weapon is not None and sd2.weapon.iid == "pm"

    # ---------- 战局全流程 ----------
    def t_raid():
        from game import Game
        from enemy import Scav
        g = Game()
        g.start_raid()
        r = g.raid
        # 固定为手枪拾荒者(位置确定,行为稳定),避免随机抽取导致的偶发晃动
        r.scavs = [Scav("pistol", r.player.x + 60, r.player.y, r.diff)]
        s = r.scavs[0]
        for _ in range(120):
            r.update(1 / 60, [])
        # 敌人发现玩家进入追击
        s.x, s.y = r.player.x + 60, r.player.y
        for _ in range(30):
            r.update(1 / 60, [])
        assert s.state == "chase", s.state
        # 射击命中
        r.player.weapon = Item.weapon("ak74", mag=30)
        r.player.fire_cd = 0
        r.player.aim = math.atan2(s.y - r.player.y, s.x - r.player.x)
        r.try_fire(True)
        assert r.bullets and r.player.weapon.state["mag"] == 29
        for _ in range(30):
            r.update(1 / 60, [])
        assert s.hp < s.d["hp"]
        # 击杀 -> 尸体战利品
        s.hp = 1
        r.player.fire_cd = 0
        r.player.aim = math.atan2(s.y - r.player.y, s.x - r.player.x)
        r.try_fire(True)
        for _ in range(60):
            r.update(1 / 60, [])
        assert r.kills == 1
        assert any(c.kind == "corpse" for c in r.containers)
        # 医疗
        r.player.hp = 50
        r.player.bag.add_item(Item("bandage"))
        placed = r.player.bag.first_of_cat("med")
        r.use_med(placed)
        assert r.player.hp == 70, r.player.hp
        # 搜刮转移
        lc = next(c for c in r.containers
                  if c.kind in ("crate", "med", "gun", "val") and c.container.items)
        before = r.player.bag.item_count()
        assert try_move(lc.container, lc.container.items[0], r.player.bag)
        assert r.player.bag.item_count() > before
        # 装填
        r.player.weapon = Item.weapon("pm", mag=0)
        r.player.bag.add_item(Item("a9", count=30))
        r.start_reload()
        assert r.player.reloading
        r._finish_reload()
        assert r.player.weapon.state["mag"] == 8
        # 撤离结算
        r.finish("extract")
        assert r.over
        assert g.save.stats["extracts"] == 1
        assert os.path.exists(save_mod.SAVE_FILE)

    def t_death_wipe():
        from game import Game
        g = Game()
        assert g.save.weapon is not None
        g.start_raid()
        g.raid.scavs = []
        g.raid.finish("death")
        sd = g.save
        assert sd.weapon is None and sd.armor is None and not sd.bag.items
        assert sd.stats["deaths"] == 1
        # 仓库不受影响
        assert sd.stash.item_count() >= 4

    def t_difficulty():
        from game import Game
        from settings import SCAVS, DIFFICULTIES
        g = Game()
        assert g.save.difficulty == "lockdown"
        # 简单:更少敌人、属性全面弱化
        g.save.difficulty = "easy"
        g.start_raid()
        r = g.raid
        assert r.diff_key == "easy"
        # 普通拾荒者数量按难度;头目与手下额外另算
        normal = [x for x in r.scavs if x.tag is None]
        assert len(normal) == DIFFICULTIES["easy"]["scavs"]
        s = normal[0]
        base = SCAVS[s.kind]
        assert s.d["hp"] <= int(base["hp"] * 0.75), (s.d, base)
        assert s.d["dmg"] < base["dmg"]
        assert s.d["view"] < base["view"]
        # 强化封锁:更多敌人(含追加出生点)、属性强化
        g2 = Game()
        g2.save.difficulty = "hardened"
        g2.start_raid()
        r2 = g2.raid
        normal2 = [x for x in r2.scavs if x.tag is None]
        assert len(normal2) == DIFFICULTIES["hardened"]["scavs"]
        s2 = normal2[0]
        assert s2.d["hp"] >= SCAVS[s2.kind]["hp"]
        # 追加的出生点不能贴脸玩家
        px, py = r2.map.spawn
        for s3 in normal2[12:]:
            assert math.hypot(s3.x - px, s3.y - py) >= 300
        # 存档往返保留难度
        save_mod.save_data(g2.save)
        assert save_mod.load_data().difficulty == "hardened"

    def t_render_all_screens():
        """渲染层覆盖:藏身处 + 战局所有界面逐个真实绘制,抓 draw 时异常。"""
        from settings import W, H
        from game import Game
        screen = pygame.display.set_mode((W, H))
        g = Game()
        g.draw(screen)                       # 藏身处
        g.start_raid()
        r = g.raid
        r.scavs = r.scavs[:1]
        s = r.scavs[0]
        s.x, s.y = r.player.x + 60, r.player.y
        r.player.weapon = Item.weapon("ak74", mag=30)
        r.player.armor = Item("paca")
        r.player.aim = 0.0
        r.add_particles(r.player.x, r.player.y, 8, (255, 100, 60))
        r.add_toast("测试提示", (255, 255, 255))
        for _ in range(30):
            r.update(1 / 60, [])
        r.shake = 4.0
        r.extract_t = 1.5
        r.player.hurt_flash = 0.3
        g.draw(screen)                       # 战局世界+迷雾+HUD+撤离指示
        # 多弹种武器(霰弹枪 ammo 为列表:龙息弹/穿甲独头弹)也要能画 HUD
        r.player.weapon = Item.weapon("mp133", mag=4)
        r.player.weapon.state["loaded"] = "a12db"
        r.player.bag.add_item(Item("a12db", count=8))
        g.draw(screen)                       # 修复前:ITEMS_CAL 抛 TypeError 直接闪退
        r.inv_open = True
        g.draw(screen)                       # 背包界面
        r.inv_open = False
        r.loot_target = next(c for c in r.containers if c.container.items)
        r.loot_target.container.add_item(Item("gold"))
        g.draw(screen)                       # 搜刮窗口
        r.loot_target = None
        r.paused = True
        g.draw(screen)                       # 暂停菜单
        r.paused = False
        r.finish("extract")
        g.draw(screen)                       # 撤离结算页
        r.finish("death")
        g.draw(screen)                       # 阵亡结算页
        g.to_hideout()
        g.draw(screen)                       # 藏身处(战绩变化后)
        pygame.display.flip()

    check("容器-基础放置", t_container)
    check("容器-弹药堆叠", t_stacking)
    check("容器-自动旋转", t_rotate)
    check("容器-跨容器转移/部分堆叠", t_trymove)
    check("容器-序列化往返", t_serialize)
    check("地图-解析/碰撞/视野多边形", t_map)
    check("地图-视线遮挡", t_los)
    check("地图-A*寻路", t_astar)
    check("存档-往返", t_save)
    check("战局-全流程模拟(索敌/射击/击杀/医疗/搜刮/装填/撤离)", t_raid)
    check("战局-阵亡清空带入装备", t_death_wipe)
    check("渲染-藏身处与战局全部界面", t_render_all_screens)
    check("难度-三档强度与存档", t_difficulty)

    def t_bugfixes():
        """巡检回归:换装存档/装填卸枪/暂停死状态/空地面堆/反序列化/超堆叠/搜刮超距。"""
        from game import Game
        # 1) 换装撤离:装备写回存档,不复制不丢失
        g = Game()
        sd = g.save
        sd.stash.clear()
        sd.bag.clear()
        sd.pack = Item("pack_mid")     # 显式带上中型背包,避免沿用上一用例死亡后的口袋
        sd.apply_pack()
        sd.weapon = Item.weapon("pm", mag=8)
        sd.armor = None
        g.start_raid()
        r = g.raid
        r.scavs = []
        r.player.bag.add_item(Item.weapon("ak74", mag=30))
        r.equip_from_bag(r.player.bag.first_of_cat("weapon"))
        assert r.player.weapon.iid == "ak74"
        r.finish("extract")
        save_mod.save_data(sd)
        sd2 = save_mod.load_data()
        assert sd2.weapon is not None and sd2.weapon.iid == "ak74"
        pms = [p for c in (sd2.stash, sd2.bag) for p in c.items if p.item.iid == "pm"]
        assert len(pms) == 1, f"旧武器被复制:{len(pms)}"
        aks = [p for c in (sd2.stash, sd2.bag) for p in c.items if p.item.iid == "ak74"]
        assert len(aks) == 0, "新武器丢失进背包"
        # 2) 装填途中卸枪:不崩溃且装填取消
        r.player.weapon = Item.weapon("pm", mag=0)
        r.player.bag.add_item(Item("a9", count=30))
        r.start_reload()
        assert r.player.reloading
        r.player.weapon = None
        r._finish_reload()          # 修复前:AttributeError
        assert not r.player.reloading
        # 3) 弹药不超堆叠上限
        for lc in r.containers:
            for p in lc.container.items:
                if p.item.is_stackable():
                    assert p.item.count <= p.item.max_stack()
        # 4) 暂停时 TAB 不生效(防"暂停+背包"死状态)
        g2 = Game()
        g2.save.bag.clear()
        g2.start_raid()
        r2 = g2.raid
        r2.scavs = []
        r2.paused = True
        ev = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_TAB)
        r2.update(1 / 60, [ev])
        assert r2.inv_open is False
        r2.paused = False
        # 5) 地面堆放不下:不留空堆,物品回背包
        n_piles = len([c for c in r2.containers if c.kind == "ground"])
        r2.player.bag.clear()
        r2.player.bag.add_item(Item.weapon("ak74", mag=5))
        placed2 = r2.player.bag.first_of_cat("weapon")
        r2.drop_from_bag(placed2)
        assert len([c for c in r2.containers if c.kind == "ground"]) == n_piles
        assert placed2 in r2.player.bag.items
        # 6) 反序列化:非法条目(越界/未知iid)被丢弃
        bad = [dict(iid="a9", count=5, rot=False, state={}, x=9, y=0),
               dict(iid="zzz", count=1, rot=False, state={}, x=0, y=0),
               dict(iid="gold", count=1, rot=False, state={}, x=0, y=1)]
        c2 = Container.deserialize(3, 2, bad)
        assert len(c2.items) == 1 and c2.items[0].item.iid == "gold"
        # 7) 搜刮窗口超距自动关闭
        g3 = Game()
        g3.start_raid()
        r3 = g3.raid
        r3.scavs = []
        far = max(r3.containers,
                  key=lambda cn: math.hypot(cn.rect.centerx - r3.player.x,
                                            cn.rect.centery - r3.player.y))
        r3.loot_target = far
        r3.update(1 / 60, [])
        assert r3.loot_target is None

    check("回归-巡检bug修复", t_bugfixes)

    def t_loot_clicks():
        """回归:搜刮窗口点击背包物品(修复前 UnboundLocalError 闪退)。"""
        from game import Game
        import raid_ui
        g = Game()
        g.save.bag.clear()
        g.start_raid()
        r = g.raid
        r.scavs = []
        r.player.weapon = None
        r.player.armor = None
        lc = next(c for c in r.containers if c.kind in ("crate", "gun", "med", "val"))
        r.loot_target = lc
        lay = raid_ui.loot_layout(lc.container.w, lc.container.h)
        # 箱子侧全部物品点一遍(覆盖直接装备分支)
        for placed in list(lc.container.items):
            rect, cell = lay["src"]
            ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                    pos=(rect.x + placed.x * cell + 5,
                                         rect.y + placed.y * cell + 5), button=1)
            r._handle_loot_click(ev)
        # 背包侧全部物品点一遍(闪退路径)
        rect, cell = lay["dst"]
        for placed in list(r.player.bag.items):
            ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                    pos=(rect.x + placed.x * cell + 5,
                                         rect.y + placed.y * cell + 5), button=1)
            r._handle_loot_click(ev)
        # 点空格子 / 关闭按钮位置不崩溃
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                pos=(rect.x + 2, rect.y + 2), button=1)
        r._handle_loot_click(ev)
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=lay["close"].center, button=1)
        r._handle_loot_click(ev)

    def t_trade():
        from game import Game
        from settings import (TRADE_GOODS, TRADE_TABS, ITEMS, SPECIAL_WEAPONS,
                              trade_cat_match, trade_buy_price, trade_sell_price,
                              W as SW, H as SH)
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True          # 跳过玩法简介,直接测交易站
        h = g.hideout
        h.show_intro = False
        sd = g.save
        sd.rubles = 100000
        h.view = "trade"
        # 分区:每个分区都要有商品,且归类正确;「特殊枪械」= 头目专属枪械
        for label, key in TRADE_TABS:
            h.trade_cat = key
            goods = h.trade_goods()
            assert goods, f"分区「{label}」没有商品"
            assert all(trade_cat_match(iid, key) for iid, _c in goods), label
            if key == "special":
                have = [iid for iid, _c in goods]
                for s in SPECIAL_WEAPONS:
                    assert s in have, f"特殊枪械分区缺少 {s}"
            if key == "weapon":
                assert all(not ITEMS[iid].get("boss_only") for iid, _c in goods), "普通枪械不该含专属枪"
        h.trade_cat = None
        assert len(h.trade_goods()) == len(TRADE_GOODS)
        # 购买 AK74
        h.trade_scroll = 0.0
        goods, per, row_h = h.trade_rows()
        idx = next(i for i, (iid, _c) in enumerate(goods) if iid == "ak74")
        price = trade_buy_price("ak74", 1)
        h._trade_click(h.trade_row_rect(idx, per, row_h).center)
        assert sd.rubles == 100000 - price
        assert any(p.item.iid == "ak74" for p in sd.stash.items)
        # 余额不足买不起
        sd.rubles = 10
        h._trade_click(h.trade_row_rect(idx, per, row_h).center)
        assert sd.rubles == 10
        # 点击仓库物品出售
        placed = next(p for p in sd.stash.items if p.item.iid == "ak74")
        sell = trade_sell_price(placed.item)
        gx0, gy0 = h.trade_stash_grid
        h._trade_click((gx0 + placed.x * 40 + 5, gy0 + placed.y * 40 + 5))
        assert sd.rubles == 10 + sell
        assert not any(p.item.iid == "ak74" for p in sd.stash.items)
        # 滚轮:「全部」放不下时,滚到底能买到最后一件
        h.trade_cat = None
        h.trade_scroll = 0.0
        ms = h.trade_max_scroll()
        assert ms > 0, "「全部」应超出可见区,需要滚轮"
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=-5)])
        assert h.trade_scroll > 0
        h.trade_scroll = ms
        goods, per, row_h = h.trade_rows()
        last_i = len(goods) - 1
        r_last = h.trade_row_rect(last_i, per, row_h)
        assert r_last.bottom <= h.trade_view_bottom + 1, (r_last, h.trade_view_bottom)
        sid, scount = goods[last_i]
        s_price = trade_buy_price(sid, scount)
        sd.rubles = 1500000
        before = sd.rubles
        h._trade_click(r_last.center)
        assert sd.rubles == before - s_price, (sid, s_price)
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEWHEEL, x=0, y=5)])
        assert h.trade_scroll < ms
        # 分区标签点击
        h._trade_click(h.trade_tab_rects[1].center)
        assert h.trade_cat == "weapon" and h.trade_scroll == 0.0
        h._trade_click(h.trade_tab_rects[0].center)
        assert h.trade_cat is None
        # 存档往返保留余额
        sd.rubles = 12345
        save_mod.save_data(sd)
        assert save_mod.load_data().rubles == 12345
        # 渲染:分区 + 滚动条 + 交易站/藏身处
        screen = pygame.display.set_mode((SW, SH))
        h.trade_scroll = 40.0
        h.draw(screen)
        h.trade_cat = "ammo"
        h.trade_scroll = 0.0
        h.draw(screen)
        h.trade_cat = None
        h.view = "stash"
        h.draw(screen)
        pygame.display.flip()

    check("回归-搜刮窗点击背包物品", t_loot_clicks)
    check("交易所-分区/滚轮/买卖/余额", t_trade)

    def t_autoreload():
        """自动换弹:弹匣打空后自动装填;没备弹则不装填。"""
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        g.save.weapon = Item.weapon("mp5", mag=1)     # 只留 1 发
        g.save.bag.clear()
        g.save.bag.add_item(Item("a9", count=60))
        g.start_raid()
        r = g.raid
        r.scavs = []
        p = r.player
        r.try_fire(True)                              # 全自动,一枪打空
        assert p.weapon.state["mag"] == 0
        for _ in range(4):
            r.update(1 / 60, [])
        assert p.reloading, "弹匣空了应自动开始装填"
        for _ in range(130):
            r.update(1 / 60, [])
        assert p.weapon.state["mag"] > 0, p.weapon.state
        # 没有备弹时不自动装填
        p.weapon.state["mag"] = 0
        p.bag.clear()
        for _ in range(10):
            r.update(1 / 60, [])
        assert not p.reloading

    check("自动换弹-弹匣空自动装填", t_autoreload)

    def t_quickheal():
        """快捷打药(按 H):按缺口选药,不用开背包。"""
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        g.save.bag.clear()
        g.save.bag.add_item(Item("bandage"))
        g.save.bag.add_item(Item("medkit"))
        g.start_raid()
        r = g.raid
        r.scavs = []
        p = r.player
        p.hp = 50
        r.quick_heal()                          # 缺口 50 -> 医疗包(刚好够)
        assert p.hp == 100, p.hp
        assert not any(pl.item.iid == "medkit" for pl in p.bag.items)
        assert any(pl.item.iid == "bandage" for pl in p.bag.items)
        p.hp = 90
        r.quick_heal()                          # 缺口 10 -> 绷带(不浪费大药)
        assert p.hp == 100
        assert not any(pl.item.cat == "med" for pl in p.bag.items)
        p.hp = 80
        r.quick_heal()                          # 没药了:不崩、血量不变
        assert p.hp == 80
        # 按键绑定 H
        p.bag.add_item(Item("bandage"))
        p.hp = 80
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h)])
        assert p.hp == 100, p.hp
        assert not any(pl.item.cat == "med" for pl in p.bag.items)

    check("快捷打药-按H自动选用医疗品", t_quickheal)

    def t_merge_ammo():
        """弹药堆叠上限 120 + 整理弹药按钮/确认框流程。"""
        from game import Game
        from settings import ITEMS, W as SW, H as SH
        from inventory import Placed
        import raid_ui
        assert ITEMS["a9"]["stack"] == 120
        assert ITEMS["a545"]["stack"] == 120
        assert ITEMS["a12db"]["stack"] == 40
        g = Game()
        g.save.bag.clear()
        g.save.pack = Item("pack_mid")
        g.save.apply_pack()
        g.start_raid()
        r = g.raid
        r.scavs = []
        bag = r.player.bag
        # 手动摆成不紧凑状态(模拟搜刮后多组散弹)
        bag.items.append(Placed(Item("a9", count=50), 0, 0))
        bag.items.append(Placed(Item("a9", count=50), 1, 0))
        bag.items.append(Placed(Item("a9", count=50), 2, 0))
        assert len(bag.items) == 3
        n = r.merge_ammo()
        assert n == 1, n
        counts = sorted(p.item.count for p in bag.items if p.item.iid == "a9")
        assert counts == [30, 120], counts
        # 确认框:取消
        r.inv_open = True
        r.ask_merge = True
        lay = raid_ui.ask_layout()
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=lay["no"].center, button=1)
        r.update(1 / 60, [ev])
        assert r.ask_merge is False and r.inv_open is True
        # 再放一组散的,确认框:叠放
        bag.items.append(Placed(Item("a9", count=10), 3, 0))
        r.ask_merge = True
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, pos=lay["yes"].center, button=1)
        r.update(1 / 60, [ev])
        assert r.ask_merge is False
        total = sum(p.item.count for p in bag.items if p.item.iid == "a9")
        assert total == 160, total
        counts = sorted(p.item.count for p in bag.items if p.item.iid == "a9")
        assert counts == [40, 120], counts
        # 渲染确认框
        screen = pygame.display.set_mode((SW, SH))
        r.ask_merge = True
        raid_ui.draw_raid(r, screen)
        r.ask_merge = False
        r.inv_open = False
        pygame.display.flip()

    check("弹药-120堆叠/整理按钮", t_merge_ammo)

    def t_pack():
        """背包系统:不同背包不同格子/装卸/存档迁移。"""
        from game import Game
        from inventory import Placed
        from settings import ITEMS, pack_grid
        assert ITEMS["pack_xl"]["grid"] == (10, 6)
        g = Game()
        g.save = save_mod.reset_data()   # 用全新存档(含起始 pack_large)
        sd = g.save
        h = g.hideout
        # 新档默认装备中型背包 -> 6×4
        assert sd.pack is not None and sd.pack.iid == "pack_mid"
        assert (sd.bag.w, sd.bag.h) == (6, 4)
        assert pack_grid(None) == (4, 2)
        # 从仓库装备远征背包 -> 8×5,旧包回仓库
        idx = next(i for i, p in enumerate(sd.stash.items)
                   if p.item.iid == "pack_large")
        ok, msg = h._try_equip_pack(idx)
        assert ok, msg
        assert (sd.bag.w, sd.bag.h) == (8, 5)
        assert sd.pack.iid == "pack_large"
        assert any(p.item.iid == "pack_mid" for p in sd.stash.items)
        # 装满背包后卸包:放不下的回仓库,不丢东西
        sd.bag.items.clear()
        for i in range(8 * 5):
            sd.bag.items.append(Placed(Item("bandage"), i % 8, i // 8))
        assert sd.bag.item_count() == 40
        ok, msg = h._try_unequip_pack()
        assert ok, msg
        assert sd.pack is None
        assert (sd.bag.w, sd.bag.h) == (4, 2)
        assert sd.bag.item_count() <= 8
        total = sd.bag.item_count() + sum(1 for p in sd.stash.items
                                          if p.item.iid == "bandage")
        assert total == 40
        # 存档往返保留背包与容量
        save_mod.save_data(sd)
        sd2 = save_mod.load_data()
        assert sd2.pack is None and (sd2.bag.w, sd2.bag.h) == (4, 2)
        # 旧档迁移:缺 pack 字段 -> 补发中型背包且 6×4,物品不丢
        legacy = save_mod.SaveData()
        data = legacy.serialize()
        for k in ("pack", "bag_w", "bag_h"):
            data.pop(k, None)
        data["bag"] = [dict(iid="bandage", count=1, rot=False, state={}, x=5, y=3)]
        sd3 = save_mod.SaveData.deserialize(data)
        assert sd3.pack is not None and sd3.pack.iid == "pack_mid"
        assert (sd3.bag.w, sd3.bag.h) == (6, 4)
        assert sd3.bag.at(5, 3) is not None
        # 最大背包(10×6)下的三处界面渲染
        from settings import W as SW, H as SH
        import raid_ui
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.pack = Item("pack_xl")
        g2.save.apply_pack()
        assert (g2.save.bag.w, g2.save.bag.h) == (10, 6)
        screen = pygame.display.set_mode((SW, SH))
        g2.hideout.draw(screen)                  # 藏身处动态格子
        g2.start_raid()
        r = g2.raid
        r.scavs = []
        r.inv_open = True
        raid_ui.draw_raid(r, screen)             # 战局背包(10×6)
        r.inv_open = False
        r.loot_target = next(c for c in r.containers if c.container.items)
        raid_ui.draw_raid(r, screen)             # 搜刮窗口(大背包侧)
        r.loot_target = None
        pygame.display.flip()

    def t_revive():
        """6级甲:97%/99% 减伤 + 倒地自救(每局一次)+ 新枪械。"""
        from game import Game
        from settings import ITEMS
        assert ITEMS["b45"]["reduce"] == 0.97 and ITEMS["b45"]["level"] == 6
        assert ITEMS["bt201"]["reduce"] == 0.99 and ITEMS["bt201"]["revive"]
        assert ITEMS["m4a1"]["ammo"] == "a556"
        assert ITEMS["a54r"]["stack"] == 120
        g = Game()
        sd = g.save
        sd.stash.clear()
        sd.bag.clear()
        sd.weapon = Item.weapon("pm", mag=8)
        sd.armor = Item("b45")
        g.start_raid()
        r = g.raid
        r.scavs = []
        p = r.player
        # 97% 减伤:8 点伤害只吃 1 点
        hp0 = p.hp
        p.take_damage(8, r)
        assert p.hp == hp0 - 1, p.hp
        # 致死伤害 -> 触发倒地自救
        p.take_damage(9999, r)
        assert not r.over and r.revive_used
        assert p.hp == int(p.max_hp * 0.3), p.hp
        # 第二次致死 -> 真阵亡
        p.take_damage(9999, r)
        assert r.over and r.result["kind"] == "death"
        assert g.save.weapon is None   # 阵亡清空带入装备(含背包)
        assert g.save.pack is None and (g.save.bag.w, g.save.bag.h) == (4, 2)
        # 无自救的普通护甲:直接阵亡
        g2 = Game()
        g2.save.armor = Item("fort")
        g2.start_raid()
        r2 = g2.raid
        r2.scavs = []
        r2.player.take_damage(9999, r2)
        assert r2.over and r2.result["kind"] == "death"

    check("背包-容量/装卸/存档迁移", t_pack)
    check("护甲-6级减伤与倒地自救", t_revive)

    def t_misc_doc():
        """杂物价格梯度 + 机密文件仅在强化封锁的保险箱固定刷出。"""
        from game import Game
        from settings import (ITEMS, CLASSIFIED, DOC_HARDENED_COUNT,
                              W as SW, H as SH)
        import uikit
        # 杂物:价格不等的 11 种 + 机密文件
        misc_ids = [iid for iid, d in ITEMS.items() if d["cat"] == "misc"]
        assert len(misc_ids) >= 20, len(misc_ids)
        # 金色物品权重被杂物摊薄:补给箱里杂物总权重应远高于金货
        from settings import LOOT
        crate = {i: wt for i, _c, wt in LOOT["crate"]}
        junk_w = sum(wt for i, wt in crate.items() if ITEMS[i]["cat"] == "misc")
        gold_w = sum(wt for i, wt in crate.items()
                     if i in ("gold", "cpu", "btc", "vase"))
        assert junk_w > gold_w * 3, (junk_w, gold_w)
        prices = sorted(ITEMS[i]["price"] for i in misc_ids)
        assert prices[0] < prices[-1]
        assert ITEMS[CLASSIFIED]["price"] == 5000000
        assert prices[-1] == 5000000
        assert ITEMS["tools"]["price"] == 128000
        # 渲染杂物图标/提示
        screen = pygame.display.set_mode((SW, SH))
        c = Container(6, 4)
        for iid in misc_ids:
            c.add_item(Item(iid))
        uikit.draw_grid(screen, 10, 10, c, 40)
        uikit.draw_tooltip(screen, 200, 200, Item(CLASSIFIED))
        pygame.display.flip()
        # 强化封锁:机密文件固定刷在保险箱
        g = Game()
        g.save.difficulty = "hardened"
        g.start_raid()
        r = g.raid
        safes = [c for c in r.containers if c.kind == "val"]
        assert len(safes) >= 3
        found = [(c, p) for c in safes for p in c.container.items
                 if p.item.iid == CLASSIFIED]
        assert len(found) == DOC_HARDENED_COUNT, len(found)
        # 封锁/简单:不出机密文件,但保险箱仍是 9 个
        for diff in ("lockdown", "easy"):
            g2 = Game()
            g2.save.difficulty = diff
            g2.start_raid()
            r2 = g2.raid
            assert len([c for c in r2.containers if c.kind == "val"]) == 9
            assert not any(p.item.iid == CLASSIFIED
                           for c in r2.containers for p in c.container.items)

    check("杂物-价格梯度与机密文件(仅强化封锁)", t_misc_doc)

    def t_minigun():
        """M139 装轮机枪:500 弹容 / 7.62×45 / 需 6 级甲 / 架枪收拢散布。"""
        from game import Game
        from settings import ITEMS, armor_allows
        d = ITEMS["m139"]
        assert d["mag"] == 500 and d["ammo"] == "a762x45"
        assert d["req_armor_level"] == 6
        assert d["spread"] > d["spread_braced"] * 3     # 架枪明显更准
        assert ITEMS["a762x45"]["name"] == "7.62×45 子弹"
        assert ITEMS["a762x45"]["stack"] == 120
        # 持用条件
        assert not armor_allows(None, d)
        assert not armor_allows(Item("fort"), d)        # 4 级甲不够
        assert armor_allows(Item("b45"), d)
        assert armor_allows(Item("bt201"), d)
        # 藏身处:4 级甲装不上,换上 6 级甲才行
        g = Game()
        g.save = save_mod.reset_data()
        sd = g.save
        sd.stash.add_item(Item("m139"))
        sd.armor = Item("fort")
        placed = next(p for p in sd.stash.items if p.item.iid == "m139")
        pos = (66 + placed.x * 40 + 5, 176 + placed.y * 40 + 5)
        g.hideout._click(pos)
        assert sd.weapon is None or sd.weapon.iid != "m139", "低级甲不该能装备 M139"
        sd.armor = Item("b45")
        g.hideout._click(pos)
        assert sd.weapon is not None and sd.weapon.iid == "m139"
        # 带着机枪不能脱 6 级甲
        g.hideout._click(g.hideout.lay["armor"].center)
        assert sd.armor is not None
        # 战局:腰射 vs 架枪的散布统计
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.armor = Item("b45")
        g2.save.weapon = Item.weapon("m139", mag=500)
        g2.start_raid()
        r = g2.raid
        r.scavs = []
        p = r.player

        def avg_dev(braced):
            r.braced = braced
            p.aim = 0.0
            r.bullets = []
            for _ in range(60):
                p.fire_cd = 0
                p.weapon.state["mag"] = 500
                r.try_fire(True)
            devs = [abs(math.atan2(b["dy"], b["dx"])) for b in r.bullets]
            return sum(devs) / max(1, len(devs))

        hip = avg_dev(False)
        braced = avg_dev(True)
        assert len(r.bullets) > 0
        assert braced < hip * 0.4, (hip, braced)
        # 装填:500 发弹容按背包里的 7.62×45 逐步填
        p.weapon.state["mag"] = 0
        p.bag.add_item(Item("a762x45", count=120))
        r.start_reload()
        r._finish_reload()
        assert p.weapon.state["mag"] == 120
        r.braced = False

    check("武器-M139装轮机枪(弹容/持用限制/架枪)", t_minigun)

    def t_braced():
        """架枪规则:除狙击枪外全枪械可架枪;M139 架枪时不能移动。"""
        from game import Game
        from settings import ITEMS
        for iid, d in ITEMS.items():
            if d.get("cat") != "weapon":
                continue
            if iid == "m700":
                assert "spread_braced" not in d, "狙击枪不参与架枪"
            else:
                assert d.get("spread_braced") is not None, iid
                assert d["spread_braced"] < d["spread"], iid
        assert ITEMS["m139"].get("braced_immobile") is True
        assert not ITEMS["ak74"].get("braced_immobile")
        # 移动限制:仅 M139 架枪时锁步
        g = Game()
        g.save = save_mod.reset_data()
        g.save.armor = Item("b45")
        g.save.weapon = Item.weapon("m139", mag=500)
        g.start_raid()
        r = g.raid
        r.scavs = []
        p = r.player
        real = pygame.key.get_pressed

        class _Keys:
            """任意键码索引都安全(方向键键码很大,不能用固定长度列表伪造)。"""
            def __getitem__(self, i):
                return 1 if i == pygame.K_d else 0

        pygame.key.get_pressed = lambda: _Keys()
        try:
            r.braced = True
            x0 = p.x
            r.update(1 / 60, [])          # 该帧架枪 -> 不移动
            assert abs(p.x - x0) < 0.5, "M139 架枪时不该移动"
            for _ in range(30):           # 松开右键后恢复移动
                r.update(1 / 60, [])
            assert p.x > x0 + 50, p.x - x0
            # 普通步枪架枪仍可移动
            p.weapon = Item.weapon("ak74", mag=30)
            r.braced = True
            x1 = p.x
            r.update(1 / 60, [])
            assert p.x > x1 + 0.5, "AK-74 架枪时应可移动"
        finally:
            pygame.key.get_pressed = real
            r.braced = False

    check("架枪-全枪械精度与M139移动限制", t_braced)

    def t_updater():
        """更新检查:版本比较 + 清单读取(file:// 与本地 version.json 优先)。"""
        import json
        import updater
        import settings
        assert updater.is_newer("1.0.1", "1.0.0")
        assert not updater.is_newer("1.0.0", "1.0.0")
        assert not updater.is_newer("0.9.9", "1.0.0")
        assert updater.is_newer("1.10", "1.9")
        assert updater.is_newer("2.0.0.1", "2.0.0")
        assert updater.parse_version("1.2.3") == (1, 2, 3)
        d = tempfile.mkdtemp(prefix="tarkov_upd_")
        man_path = os.path.join(d, "version.json")
        with open(man_path, "w", encoding="utf-8") as f:
            json.dump({"version": "9.9.9", "url": "Tarkov2D.exe", "notes": "测试清单"}, f)
        old_local = updater.local_manifest_path
        old_url = settings.UPDATE_MANIFEST_URL
        updater.local_manifest_path = lambda: os.path.join(d, "none.json")
        settings.UPDATE_MANIFEST_URL = "file:///" + man_path.replace("\\", "/")
        try:
            man, src = updater.fetch_manifest()
            assert man and man["version"] == "9.9.9", (man, src)
            assert updater.is_newer(man["version"], settings.GAME_VERSION)
            assert updater._resolve_url(src, "Tarkov2D.exe").endswith("Tarkov2D.exe")
        finally:
            updater.local_manifest_path = old_local
            settings.UPDATE_MANIFEST_URL = old_url
        # 本地 version.json 优先于网络
        updater.local_manifest_path = lambda: man_path
        try:
            man2, src2 = updater.fetch_manifest()
            assert man2["version"] == "9.9.9" and "本地" in src2, (man2, src2)
        finally:
            updater.local_manifest_path = old_local

    check("更新-版本比较与清单读取", t_updater)

    def t_boss():
        """三张地图的头目系统:5 级甲(89/81/75%)+ 专属枪械掉落。"""
        from game import Game
        from settings import (BOSSES, GUARD_ARMORS, ITEMS, MAP_ORDER,
                              TRADE_GOODS, trade_cat_match)
        assert ITEMS["b23"]["level"] == 5 and abs(ITEMS["b23"]["reduce"] - 0.89) < 1e-9
        assert ITEMS["zhuk"]["level"] == 5 and abs(ITEMS["zhuk"]["reduce"] - 0.81) < 1e-9
        assert ITEMS["korund"]["level"] == 5 and abs(ITEMS["korund"]["reduce"] - 0.75) < 1e-9
        for iid in GUARD_ARMORS:
            assert ITEMS[iid]["cat"] == "armor" and ITEMS[iid]["level"] == 5
        for key, b in BOSSES.items():
            # 三张老图头目掉 5 级甲;突袭模式的要塞司令是最高档(掉 6 级甲)
            lv = ITEMS[b["armor"]]["level"]
            assert lv == (6 if key == "base" else 5), (key, lv)
            w = ITEMS[b["weapon"]]
            # 要塞司令的奖励是精英机枪 M139(靠 6 级甲门槛,不是 boss_only 货架)
            if key != "base":
                assert w.get("boss_only"), key
                assert trade_cat_match(b["weapon"], "special"), key
            assert w["cat"] == "weapon", key
            assert w["ammo"] in ITEMS, key
            assert b.get("guards", 0) >= 3, key
        # 实战:逐张有头目的地图击杀头目 -> 头目尸体必含 5 级甲 + 专属武器
        # (大本营(突袭)的司令由 t_assault 单独覆盖:那边是 50+ 守军的战场,跑一遍太慢)
        for key in [k for k in MAP_ORDER if BOSSES.get(k) and k != "base"]:
            g = Game()
            g.save = save_mod.reset_data()
            g.save.map_key = key
            g.start_raid()
            r = g.raid
            assert r.map_key == key
            boss = next(s for s in r.scavs if s.tag == "boss")
            assert boss.hp >= 200, (key, boss.hp)
            guards = [s for s in r.scavs if s.tag == "guard"]
            assert len(guards) >= 3, (key, len(guards))
            boss.x, boss.y = r.player.x + 40, r.player.y
            boss.hp = 1
            r.player.weapon = Item.weapon("ak74", mag=30)
            r.player.fire_cd = 0
            r.player.aim = math.atan2(boss.y - r.player.y, boss.x - r.player.x)
            r.try_fire(True)
            for _ in range(40):
                r.update(1 / 60, [])
            assert boss.dead, key
            corpse = next(c for c in r.containers if c.kind == "boss_corpse")
            ids = [p.item.iid for p in corpse.container.items]
            assert BOSSES[key]["armor"] in ids, (key, ids)
            assert BOSSES[key]["weapon"] in ids, (key, ids)
            # 手下:把掉落概率拉到 100% 后必掉 5 级甲
            import raid as _raid
            old_drop = _raid.GUARD_ARMOR_DROP
            _raid.GUARD_ARMOR_DROP = 1.0
            try:
                guard = guards[0]
                guard.x, guard.y = r.player.x + 40, r.player.y
                guard.hp = 1
                r.player.fire_cd = 0
                r.player.aim = math.atan2(guard.y - r.player.y, guard.x - r.player.x)
                r.try_fire(True)
                for _ in range(40):
                    r.update(1 / 60, [])
                assert guard.dead, key
                corpses = [c for c in r.containers if c.kind == "corpse"]
                gids = [p.item.iid for c in corpses for p in c.container.items]
                assert any(i in GUARD_ARMORS for i in gids), (key, gids)
            finally:
                _raid.GUARD_ARMOR_DROP = old_drop
        # 地图选择存档往返
        g = Game()
        g.save = save_mod.reset_data()
        g.save.map_key = "port"
        save_mod.save_data(g.save)
        assert save_mod.load_data().map_key == "port"
        # 藏身处地图选择器可点
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.map_key = "border"
        g2.hideout._click(g2.hideout.map_rects[1].center)
        assert g2.save.map_key == "tv"
        g2.hideout._click(g2.hideout.map_rects[2].center)
        assert g2.save.map_key == "port"

    check("头目-三图5级甲与专属枪械掉落", t_boss)

    def t_rpg():
        """隐藏头目「作者」+ RPG:右键架枪更准;火箭弹穿6甲半血、无6甲阵亡。"""
        from game import Game
        from settings import (ITEMS, AUTHOR_BOSS, RPG_HALF_HP_ARMOR_LEVEL,
                              TRADE_GOODS, trade_cat_match, W as SW, H as SH)
        import raid_ui
        d = ITEMS["rpg"]
        assert d["cat"] == "weapon" and d.get("boss_only")
        assert d["mag"] == 1 and d["ammo"] == "rocket"
        assert d["spread_braced"] < d["spread"]      # 右键架枪更准
        assert d["spread"] >= 0.2                    # 腰射很不准
        # 第二把 RPG:同样的弹药与伤害规则,四管弹仓
        d2 = ITEMS["rpg2"]
        assert d2["ammo"] == "rocket" and d2["dmg"] == d["dmg"]
        assert d2["mag"] == 4
        assert d2["spread_braced"] < d2["spread"]
        assert ITEMS["rocket"]["stack"] == 5
        assert RPG_HALF_HP_ARMOR_LEVEL == 6
        assert AUTHOR_BOSS["rpg"] is True and AUTHOR_BOSS["weapon"] == "rpg"
        # 两把 RPG 都在「特殊枪械」分区上架
        assert trade_cat_match("rpg", "special")
        assert trade_cat_match("rpg2", "special")
        assert any(iid == "rocket" for iid, _c in TRADE_GOODS)  # 火箭弹可买
        ran_combat = False
        for diff, expect in (("easy", False), ("lockdown", True), ("hardened", True)):
            g = Game()
            g.save = save_mod.reset_data()
            g.save.difficulty = diff
            g.save.armor = Item("b45")   # 打作者必须穿 6 级甲,否则会被 RPG 一炮带走
            g.start_raid()
            r = g.raid
            has = any(s.tag == "author" for s in r.scavs)
            assert has == expect, (diff, has)
            if not expect or ran_combat:
                continue
            ran_combat = True
            author = next(s for s in r.scavs if s.tag == "author")
            assert author.hp >= 300, author.hp
            author.x, author.y = r.player.x + 40, r.player.y
            author.hp = 1
            r.player.weapon = Item.weapon("ak74", mag=30)
            r.player.fire_cd = 0
            r.player.aim = math.atan2(author.y - r.player.y, author.x - r.player.x)
            r.try_fire(True)
            for _ in range(40):
                r.update(1 / 60, [])
            assert author.dead, diff
            corpse = next(c for c in r.containers if c.kind == "boss_corpse")
            ids = [p.item.iid for p in corpse.container.items]
            assert "rpg" in ids and "rocket" in ids, ids
            assert any(ITEMS[i].get("level") == 6 for i in ids), ids
            # 玩家端 RPG:架枪后一发带走普通拾荒者(RPG 是半自动,需 fire_edge)
            r.player.weapon = Item.weapon("rpg", mag=1)
            r.braced = True
            r.player.fire_cd = 0
            target = r.scavs[0]
            target.x, target.y = r.player.x + 60, r.player.y
            r.player.aim = 0.0
            r.fire_edge = True
            r.try_fire(True)
            r.fire_edge = False
            assert r.bullets, "RPG 应该打出一发火箭弹"
            for _ in range(60):
                r.update(1 / 60, [])
            assert target.dead, "RPG 应一发打死普通拾荒者"
            # 渲染火箭弹弹道
            screen = pygame.display.set_mode((SW, SH))
            r.bullets.append(dict(x=r.player.x, y=r.player.y, dx=500.0, dy=0.0,
                                  dmg=200, owner="scav", ttl=1.0, rpg=True))
            raid_ui.draw_raid(r, screen)
            pygame.display.flip()
        assert ran_combat
        # 火箭弹对玩家的伤害规则:无甲/5 级甲直接阵亡,6 级甲掉一半血
        for armor_id, expect_hp in ((None, 0), ("korund", 0), ("b45", 50)):
            g2 = Game()
            g2.save = save_mod.reset_data()
            g2.save.armor = Item(armor_id) if armor_id else None
            g2.start_raid()
            r2 = g2.raid
            r2.scavs = []
            p = r2.player
            p.take_damage(1, r2, rpg=True)
            if expect_hp == 0:
                assert r2.over and r2.result["kind"] == "death", armor_id
            else:
                assert not r2.over, armor_id
                assert p.hp == p.max_hp - expect_hp, (armor_id, p.hp)

    check("作者-RPG/火箭弹伤害规则", t_rpg)

    def t_blast():
        """火箭弹溅射(不必精确瞄准)+ 尸体盒子不重叠 + 头目尸体可见。"""
        from game import Game
        from settings import RPG_BLAST_RADIUS, W as SW, H as SH
        from world import LootContainer
        import raid_ui
        assert RPG_BLAST_RADIUS >= 64
        g = Game()
        g.save = save_mod.reset_data()
        g.save.armor = Item("b45")           # 6 级甲:溅射到自己只掉半血
        g.save.weapon = Item.weapon("rpg", mag=1)
        g.save.bag.clear()
        g.save.bag.add_item(Item("rocket", count=5))
        g.start_raid()
        r = g.raid
        p = r.player
        a, b2, c = r.scavs[0], r.scavs[1], r.scavs[2]
        bx, by = p.x + 300, p.y
        a.x, a.y = bx, by                    # 正中
        b2.x, b2.y = bx, by + 70             # 偏 70 < 96:只吃溅射
        c.x, c.y = bx, by + 200              # 偏 200 > 96:不受影响
        r.explode(bx, by, 200, "player")
        assert a.dead and b2.dead, "溅射应带走未直接命中的目标"
        assert not c.dead, "范围外不该受伤"
        # 玩家被自己的爆炸波及:6 级甲 -> 掉一半血
        hp0 = p.hp
        r.explode(p.x, p.y, 200, "player")
        assert p.hp == hp0 - 50 and not r.over, (hp0, p.hp, r.over)
        # 发射者不吃自己的爆炸(避免 NPC 自爆)
        d = r.scavs[0]
        d.hp = 500
        d.x, d.y = p.x + 500, p.y
        r.explode(d.x, d.y, 200, "scav", src=d)
        assert not d.dead and d.hp == 500
        # 同一位置连杀两个:尸体盒子必须错开
        e1, e2 = r.scavs[0], r.scavs[1]
        e1.x = e2.x = p.x + 600
        e1.y = e2.y = p.y + 600
        r.kill_scav(e1)
        r.kill_scav(e2)
        cs = [lc for lc in r.containers if lc.kind == "corpse"][-2:]
        assert len(cs) == 2
        assert math.hypot(cs[0].rect.centerx - cs[1].rect.centerx,
                          cs[0].rect.centery - cs[1].rect.centery) >= 32 * 0.9 - 1
        # 头目尸体也要画得出来(以前漏了这个 kind -> 看不到盒子)
        r.containers.append(LootContainer("boss_corpse", int(p.x), int(p.y)))
        screen = pygame.display.set_mode((SW, SH))
        raid_ui.draw_raid(r, screen)
        pygame.display.flip()

    check("爆炸-溅射范围/尸体不重叠/头目尸体可见", t_blast)

    def t_meds():
        """药品扩充 + 交易站「药品」分区可买。"""
        from game import Game
        from settings import ITEMS, TRADE_TABS, TRADE_GOODS, trade_cat_match
        meds = [iid for iid, d in ITEMS.items() if d["cat"] == "med"]
        assert len(meds) >= 7, meds
        for iid in ("painkiller", "tourniquet", "syringe", "ai2", "surgery"):
            assert ITEMS[iid]["cat"] == "med" and ITEMS[iid]["heal"] > 0, iid
        heals = sorted(ITEMS[i]["heal"] for i in meds)
        assert heals[0] < heals[-1] and heals[-1] >= 200, heals
        assert any(key == "med" for _label, key in TRADE_TABS), "缺少药品分区"
        goods = [g for g in TRADE_GOODS if trade_cat_match(g[0], "med")]
        assert goods and all(ITEMS[iid]["cat"] == "med" for iid, _c in goods)
        # 在药品分区买外科手术包
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        h = g.hideout
        h.show_intro = False
        sd = g.save
        sd.rubles = 200000
        h.view = "trade"
        h.trade_cat = "med"
        h.trade_scroll = 0.0
        gs, per, row_h = h.trade_rows()
        i = next(i for i, (iid, _c) in enumerate(gs) if iid == "surgery")
        before = sd.rubles
        h._trade_click(h.trade_row_rect(i, per, row_h).center)
        assert any(p.item.iid == "surgery" for p in sd.stash.items)
        assert sd.rubles < before

    check("药品-新增药品/药品分区购买", t_meds)

    def t_touch():
        """手机模式:摇杆移动 / 触屏按钮 / 自动锁敌;玩法简介可读可关。"""
        from game import Game
        from settings import W as SW, H as SH
        import intro
        import touch as touch_mod
        assert len(intro.PAGES) >= 3
        assert intro.advance(0) == 1
        assert intro.advance(len(intro.PAGES) - 1) is None
        # 摇杆状态机
        ui = touch_mod.TouchUI()
        assert ui.handle_event(pygame.event.Event(
            pygame.FINGERDOWN, finger_id=1, x=0.2, y=0.8)) is True
        assert ui.stick_id == 1
        ui.handle_event(pygame.event.Event(pygame.FINGERMOTION, finger_id=1,
                                           x=0.3, y=0.8))
        mx, my = ui.move_axis()
        assert mx > 0.2 and abs(my) < 0.01, (mx, my)
        ui.handle_event(pygame.event.Event(pygame.FINGERUP, finger_id=1, x=0.3, y=0.8))
        assert ui.move_axis() == (0.0, 0.0)
        # 开火按钮
        lay = ui.button_layout()
        fp = lay["fire"]["pos"]
        assert ui.handle_event(pygame.event.Event(
            pygame.FINGERDOWN, finger_id=2, x=fp[0] / SW, y=fp[1] / SH)) is True
        assert ui.hold("fire") and "fire" in ui.take_taps()
        ui.handle_event(pygame.event.Event(pygame.FINGERUP, finger_id=2,
                                           x=fp[0] / SW, y=fp[1] / SH))
        assert not ui.hold("fire")
        # 战局:自动锁敌 / 摇杆移动 / 打药 / 背包
        g = Game()
        g.save = save_mod.reset_data()
        g.save.weapon = Item.weapon("ak74", mag=30)
        g.save.bag.clear()
        g.save.bag.add_item(Item("bandage"))
        g.save.touch = True
        g.start_raid()
        r = g.raid
        assert r.touch_mode and r.touch is not None
        p = r.player
        s = r.scavs[0]
        for other in r.scavs[1:]:
            other.x, other.y = p.x + 4000, p.y + 4000
        s.x, s.y = p.x + 220, p.y + 40
        r.update(1 / 60, [])
        assert r.aim_locked is s, "自动锁敌应锁定最近的可见敌人"
        assert abs(p.aim - math.atan2(40, 220)) < 0.06, p.aim
        # 摇杆推动 -> 角色移动
        r.touch.stick_id = 9
        r.touch.stick_base = (100, 100)
        r.touch.stick_vec = (1.0, 0.0)
        x0 = p.x
        for _ in range(20):
            r.update(1 / 60, [])
        assert p.x > x0 + 30, p.x - x0
        # 触屏按钮:打药 / 背包
        p.hp = 60
        r.touch.just_pressed = ["heal"]
        r.update(1 / 60, [])
        assert p.hp == 80, p.hp
        r.touch.just_pressed = ["bag"]
        r.update(1 / 60, [])
        assert r.inv_open
        r.touch.just_pressed = ["bag"]
        r.update(1 / 60, [])
        assert not r.inv_open
        # 玩法简介:首次自动弹出,读完关闭并记录
        g2 = Game()
        g2.save = save_mod.reset_data()
        assert not g2.save.seen_intro and g2.hideout.show_intro
        for _ in range(len(intro.PAGES)):
            g2.hideout.update(1 / 60, [pygame.event.Event(
                pygame.MOUSEBUTTONDOWN, pos=(10, 10), button=1)])
        assert not g2.hideout.show_intro and g2.save.seen_intro
        # 手机模式开关
        g2.hideout._click(g2.hideout.lay["touch_btn"].center)
        assert g2.save.touch is True
        g2.hideout._click(g2.hideout.lay["touch_btn"].center)
        assert g2.save.touch is False

    check("手机-触屏/自动锁敌/玩法简介", t_touch)

    def t_hostage():
        """人质模式:室内大楼 / 4 人质 / 3 队友 / 20 敌人分房间 / 救援与拉起 / 任务判定。"""
        from game import Game
        from world import GameMap
        from settings import (MAPS, MAP_ORDER, MODE_ORDER, HOSTAGE_COUNT,
                              HOSTAGE_ENEMIES, ALLY_COUNT, W as SW, H as SH)
        import raid_ui
        # 1) 室内大楼结构
        m = GameMap("indoor")
        assert len(m.hostage_spawns) == HOSTAGE_COUNT
        assert len(m.ally_spawns) == ALLY_COUNT
        assert HOSTAGE_ENEMIES >= 20, HOSTAGE_ENEMIES
        assert len(m.scav_spawns) == HOSTAGE_ENEMIES
        assert len(m.corners) >= 20, len(m.corners)
        assert len(m.extracts) == 3
        sx, sy = m.spawn
        st = (int(sx // 32), int(sy // 32))
        assert not m.collides(sx, sy, PLAYER["radius"])
        for name, r in m.extracts:
            t = (int(r.centerx // 32), int(r.centery // 32))
            assert m.astar(st, t) is not None, f"撤离点不可达 {name}"
        for (hx, hy) in m.hostage_spawns:
            assert not m.collides(hx, hy, 12)
            assert m.astar(st, (int(hx // 32), int(hy // 32))) is not None, "人质不可达"
        for (ax, ay) in m.ally_spawns:
            assert not m.collides(ax, ay, 12)
        # 1b) 匪徒必须分散在八个房间里,不许挤在同一间
        rooms = {"西北上": (2, 2, 26, 8), "西北下": (2, 10, 26, 17),
                 "东北上": (32, 2, 57, 8), "东北下": (32, 10, 57, 17),
                 "西南上": (2, 23, 26, 29), "西南下": (2, 31, 26, 37),
                 "东南上": (32, 23, 57, 29), "东南下": (32, 31, 57, 37)}
        per_room = {k: 0 for k in rooms}
        for kind, (ex, ey) in m.scav_spawns:
            tx, ty = int(ex // 32), int(ey // 32)
            assert not m.tile_solid(tx, ty), f"匪徒刷新点在墙里 {kind} {tx},{ty}"
            in_room = [k for k, (x1, y1, x2, y2) in rooms.items()
                       if x1 <= tx <= x2 and y1 <= ty <= y2]
            assert len(in_room) == 1, f"刷新点不在任何房间内:{tx},{ty}"
            per_room[in_room[0]] += 1
            assert m.astar(st, (tx, ty)) is not None, "匪徒刷新点不可达"
        assert all(c >= 2 for c in per_room.values()), per_room
        # 95% 以上是房间/走廊:室外地面占比很低
        rows = MAPS["indoor"]["rows"]
        outdoor = sum(row.count(".") for row in rows)
        assert outdoor / (len(rows) * len(rows[0])) < 0.10, outdoor
        # 2) 模式选择与存档
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        h = g.hideout
        h.show_intro = False
        h._click(h.map_rects[MAP_ORDER.index("indoor")].center)
        assert g.save.mode == "hostage" and g.save.map_key == "indoor"
        h._click(h.mode_rects[MODE_ORDER.index("raid")].center)
        assert g.save.mode == "raid"
        h._click(h.mode_rects[MODE_ORDER.index("hostage")].center)
        assert g.save.mode == "hostage" and g.save.map_key == "indoor"
        save_mod.save_data(g.save)
        assert save_mod.load_data().mode == "hostage"
        # 3) 战局生成
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.mode = "hostage"
        g2.start_raid()
        r = g2.raid
        assert r.mode == "hostage" and r.map_key == "indoor"
        assert r.boss_cfg is None, "人质模式没有头目"
        assert len(r.scavs) == HOSTAGE_ENEMIES
        # 实际开局的敌人同样分散在多个房间,不是全挤在一间
        used_rooms = {k for s in r.scavs
                      for k, (x1, y1, x2, y2) in rooms.items()
                      if x1 <= int(s.x // 32) <= x2 and y1 <= int(s.y // 32) <= y2}
        assert len(used_rooms) == len(rooms), used_rooms
        assert len(r.allies) == ALLY_COUNT and len(r.hostages) == HOSTAGE_COUNT
        p = r.player
        # 4) 队友自动开火
        a = r.allies[0]
        enemy = r.scavs[0]
        for other in r.scavs[1:]:
            other.x, other.y = p.x + 4000, p.y + 4000
        a.x, a.y = p.x + 100, p.y
        enemy.x, enemy.y = p.x + 320, p.y
        hp0 = enemy.hp
        r.update(1 / 60, [])
        assert any(b["owner"] == "ally" for b in r.bullets), "队友应该开火"
        for _ in range(60):
            r.update(1 / 60, [])
        assert enemy.hp < hp0, (hp0, enemy.hp)
        # 5) 解救人质(站定读条)
        r.scavs = []
        host = r.hostages[0]
        host.x, host.y = p.x + 40, p.y
        r.interact()
        assert r.channel is not None and r.channel["kind"] == "rescue"
        for _ in range(200):
            r.update(1 / 60, [])
        assert host.rescued, "站定读条应完成解救"
        # 6) 队友倒地 -> 拉起
        a.take_damage(999, r)
        assert a.downed
        a.x, a.y = p.x + 30, p.y
        r.interact()
        assert r.channel is not None and r.channel["kind"] == "revive"
        for _ in range(200):
            r.update(1 / 60, [])
        assert not a.downed and a.hp > 0
        # 7) 全部救出 -> 任务完成;只救一半 -> 未完成
        for host in r.hostages:
            host.rescued = True
        r.finish("extract")
        assert r.result["mission"] is True
        assert r.result["rescued"] == HOSTAGE_COUNT
        g3 = Game()
        g3.save = save_mod.reset_data()
        g3.save.mode = "hostage"
        g3.start_raid()
        r3 = g3.raid
        r3.scavs = []
        r3.hostages[0].rescued = True
        r3.finish("extract")
        assert r3.result["mission"] is False
        # 8) 渲染(队友 / 人质 / 救援读条)
        screen = pygame.display.set_mode((SW, SH))
        g4 = Game()
        g4.save = save_mod.reset_data()
        g4.save.mode = "hostage"
        g4.start_raid()
        r4 = g4.raid
        r4.hostages[0].x, r4.hostages[0].y = r4.player.x + 40, r4.player.y
        r4.channel = dict(kind="rescue", ent=r4.hostages[0], t=1.0)
        raid_ui.draw_raid(r4, screen)
        r4.channel = None
        pygame.display.flip()

    check("人质模式-室内图/队友/救援/任务判定", t_hostage)

    def t_attach():
        """配件系统 + 枪械天赋 + 弹药分级(霰弹双弹种 / 步枪穿甲)。"""
        from game import Game
        from settings import (ITEMS, TRADE_TABS, TRADE_GOODS, trade_cat_match,
                              weapon_capacity, weapon_params, weapon_slots,
                              weapon_ammo_ids, TALENTS, ATTACH_SLOTS)
        # 1) 配件数据与分区
        attach_items = [i for i, d in ITEMS.items() if d["cat"] == "attach"]
        assert len(attach_items) >= 8, attach_items
        for iid in attach_items:
            d = ITEMS[iid]
            assert d.get("slot") in ATTACH_SLOTS, iid
            assert ("mag_bonus" in d) or ("brace_mul" in d) or ("hip_mul" in d), iid
        assert any(key == "attach" for _l, key in TRADE_TABS), "缺少配件分区"
        goods = [g for g in TRADE_GOODS if trade_cat_match(g[0], "attach")]
        assert goods and all(ITEMS[i]["cat"] == "attach" for i, _c in goods)
        # 2) 弹夹扩容(巨浪弹匣太小 -> 弹鼓)
        w = Item.weapon("asval", mag=20)
        assert weapon_capacity(w) == 20
        w.state.setdefault("attach", {})["mag"] = "mag_drum"
        assert weapon_capacity(w) == 40, weapon_capacity(w)
        # 3) 握把降架枪散布 / 激光降腰射散布
        w2 = Item.weapon("ak74", mag=30)
        hip0, braced0 = weapon_params(w2)[2], weapon_params(w2)[3]
        w2.state.setdefault("attach", {})["grip"] = "grip_ang"
        hip1, braced1 = weapon_params(w2)[2], weapon_params(w2)[3]
        assert braced1 < braced0 * 0.9, (braced0, braced1)
        assert abs(hip1 - hip0) < 1e-9, (hip0, hip1)      # 握把不影响腰射
        w2.state["attach"]["laser"] = "laser_ir"
        hip2 = weapon_params(w2)[2]
        assert hip2 < hip1 * 0.9, (hip1, hip2)
        # 4) 天赋
        assert TALENTS["akm"]["dmg_mul"] > 1
        assert weapon_params(Item.weapon("akm"))[0] > ITEMS["akm"]["dmg"]
        assert weapon_params(Item.weapon("vector"))[5] < 1.0      # 装填更快
        assert weapon_params(Item.weapon("m700"))[3] < ITEMS["m700"]["spread"]
        # 5) M139 不装配件
        assert weapon_slots("m139") == []
        # 6) 弹药分级
        assert "a12" not in ITEMS, "旧霰弹应被龙息/独头弹取代"
        assert set(weapon_ammo_ids(Item.weapon("mp133"))) == {"a12db", "a12ap"}
        assert weapon_params(Item.weapon("mp133"))[1] >= 5        # 龙息:多弹丸
        it_ap = Item.weapon("mp133")
        it_ap.state["loaded"] = "a12ap"
        ap = weapon_params(it_ap)
        assert ap[1] == 1 and ap[0] > 30, ap[:2]                  # 独头弹:单发高伤
        for rid in ("ak74", "akm", "m4a1", "m700"):
            for aid in weapon_ammo_ids(Item.weapon(rid)):
                assert ITEMS[aid].get("dmg_mul", 1.0) > 1.0, (rid, aid)
        # 7) 藏身处安装配件(含机枪拒绝)
        g = Game()
        g.save = save_mod.reset_data()
        sd = g.save
        h = g.hideout
        h.show_intro = False
        sd.stash.clear()
        sd.bag.clear()
        sd.weapon = Item.weapon("mp5", mag=30)
        sd.stash.add_item(Item("mag_drum_big"))
        pl = next(p for p in sd.stash.items if p.item.iid == "mag_drum_big")
        h._install_attachment(sd, pl)
        assert weapon_capacity(sd.weapon) == 60, weapon_capacity(sd.weapon)
        assert not sd.stash.items, "配件应从仓库装到枪上"
        sd.weapon = Item.weapon("m139", mag=500)
        sd.stash.add_item(Item("mag_drum_big"))
        pl = next(p for p in sd.stash.items if p.item.iid == "mag_drum_big")
        h._install_attachment(sd, pl)
        assert weapon_capacity(sd.weapon) == 500, "机枪不该装弹夹"
        # 8) 战局:装填记录弹种 + 龙息点燃
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.weapon = Item.weapon("mp133", mag=0)
        g2.save.bag.clear()
        g2.save.bag.add_item(Item("a12db", count=10))
        g2.start_raid()
        r = g2.raid
        s = r.scavs[0]
        for other in r.scavs[1:]:
            other.x, other.y = r.player.x + 4000, r.player.y + 4000
        w3 = r.player.weapon
        r.start_reload()
        r._finish_reload()
        assert w3.state.get("loaded") == "a12db", w3.state
        assert w3.state["mag"] == 4, w3.state
        s.x, s.y = r.player.x + 60, r.player.y
        s.hp = 400
        r.braced = True
        r.player.fire_cd = 0
        r.player.aim = 0.0
        r.fire_edge = True
        r.try_fire(True)
        r.fire_edge = False
        for _ in range(10):
            r.update(1 / 60, [])
        assert getattr(s, "burn_t", 0) > 0, "龙息弹应点燃敌人"
        hp_hit = s.hp
        for _ in range(60):
            r.update(1 / 60, [])
        assert s.hp < hp_hit, (hp_hit, s.hp)

    check("配件-弹夹/握把/激光/天赋/弹药分级", t_attach)

    def t_assault():
        """突袭模式:大本营 50 守军/10 队友/3 座设施/配发满配装备/友军支援/撤离限制。"""
        from game import Game
        from world import GameMap
        from raid import Objective
        from touch import TouchUI
        from settings import (MAPS, MAP_ORDER, MODE_ORDER, MODES, OBJECTIVES,
                              ALLY_STRUCTURES, STRUCT_INFO, ASSAULT_ENEMIES,
                              ASSAULT_ALLIES, ASSAULT_START_POINTS,
                              ASSAULT_PLANT_TIME, ASSAULT_KILL_POINTS,
                              C4_FUSE, C4_BLAST_RADIUS, C4_UNIT_DMG,
                              ENEMY_REINF_INTERVAL, ENEMY_REINF_SQUAD,
                              ALLY_REINF_INTERVAL, BOSSES,
                              SUPPORT, SUPPORT_ORDER, ISSUE_ATTACH, ISSUE_WEAPONS,
                              weapon_slots, weapon_capacity, weapon_ammo_ids,
                              TILE, DIFF_ORDER, EXTRACT_TIME, get_font,
                              W as SW, H as SH)
        import assault
        import raid_ui
        # 1) 大本营地图:50 个守军刷新点 / 10 个队友点 / 敌方 3 座设施 / 我方 2 座设施
        m = GameMap("base")
        assert len(m.scav_spawns) >= ASSAULT_ENEMIES, len(m.scav_spawns)
        assert len(m.ally_spawns) >= ASSAULT_ALLIES, len(m.ally_spawns)
        assert len(m.objectives) == len(OBJECTIVES), m.objectives
        assert len(m.friend_structures) == len(ALLY_STRUCTURES), m.friend_structures
        assert m.boss_spawn and len(m.guard_spawns) >= 5, (m.boss_spawn, m.guard_spawns)
        assert len(m.extracts) == 2
        sx, sy = m.spawn
        st = (int(sx // TILE), int(sy // TILE))
        assert not m.tile_solid(*st), "出生点在墙里"
        for name, (ox, oy), role in m.objectives:
            assert role in STRUCT_INFO, role
            assert not m.tile_solid(int(ox // TILE), int(oy // TILE))
            assert m.astar(st, (int(ox // TILE), int(oy // TILE))) is not None, name
            assert int(oy // TILE) <= 36, (name, "敌方设施应该在要塞内")
        for name, (ox, oy), role in m.friend_structures:
            assert role in ("command", "comms"), role
            assert not m.tile_solid(int(ox // TILE), int(oy // TILE))
            assert m.astar(st, (int(ox // TILE), int(oy // TILE))) is not None, name
            assert int(oy // TILE) >= 37, (name, "我方设施应该在要塞外")
        # 通讯设施两边都有(援兵开关),司令在要塞内
        assert any(r == "comms" for _n, _p, r in m.objectives)
        assert any(r == "comms" for _n, _p, r in m.friend_structures)
        assert any(r == "command" for _n, _p, r in m.friend_structures)
        bx, by = m.boss_spawn
        assert not m.tile_solid(int(bx // TILE), int(by // TILE))
        assert m.astar(st, (int(bx // TILE), int(by // TILE))) is not None, "司令不可达"
        assert BOSSES["base"]["armor"] == "bt201", BOSSES["base"]["armor"]
        for kind, (x, y) in m.scav_spawns:
            assert not m.tile_solid(int(x // TILE), int(y // TILE)), (kind, x, y)
            assert m.astar(st, (int(x // TILE), int(y // TILE))) is not None, kind
        for (x, y) in m.ally_spawns:
            assert not m.tile_solid(int(x // TILE), int(y // TILE))
        # 守军要铺开:东西南北四个方向都得有人,不能全堆在一个角
        tx = [int(x // TILE) for _k, (x, y) in m.scav_spawns]
        ty = [int(y // TILE) for _k, (x, y) in m.scav_spawns]
        for label, n in (("西", sum(1 for v in tx if v < 30)),
                         ("东", sum(1 for v in tx if v >= 30)),
                         ("北", sum(1 for v in ty if v < 18)),
                         ("南", sum(1 for v in ty if v >= 18))):
            assert n >= 10, (label, n)
        # 每个守军刷新点都独占一格(不和物资/队友/目标/撤离点重叠)
        seen = set()
        for _k, (x, y) in m.scav_spawns:
            seen.add((x // TILE, y // TILE))
        assert len(seen) == len(m.scav_spawns)
        # 侧栏文案不能超出面板宽度(font 13 下约 294px)
        f13 = get_font(13)
        for k in MODE_ORDER:
            assert f13.size(MODES[k]["desc"])[0] <= 294, (k, MODES[k]["desc"])
        for k in MAP_ORDER:
            w = f13.size(MAPS[k]["desc"])[0]
            assert w <= 294, (k, MAPS[k]["desc"], w)
        # 2) 藏身处接入:选突袭 -> 强制大本营;突袭下难度按钮不生效
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        h = g.hideout
        h.show_intro = False
        h._click(h.mode_rects[MODE_ORDER.index("assault")].center)
        assert g.save.mode == "assault" and g.save.map_key == "base"
        h._click(h.map_rects[MAP_ORDER.index("base")].center)
        assert g.save.mode == "assault" and g.save.map_key == "base"
        g.save.difficulty = "lockdown"
        h._click(h.diff_rects[DIFF_ORDER.index("hardened")].center)
        assert g.save.difficulty == "lockdown", "突袭模式不该能改难度档"
        h._click(h.map_rects[MAP_ORDER.index("border")].center)
        assert g.save.mode == "raid", "选普通地图应回到搜打撤"
        h._click(h.mode_rects[MODE_ORDER.index("hostage")].center)
        assert g.save.mode == "hostage" and g.save.map_key == "indoor"
        h._click(h.mode_rects[MODE_ORDER.index("assault")].center)
        assert g.save.mode == "assault" and g.save.map_key == "base"
        save_mod.save_data(g.save)
        assert save_mod.load_data().mode == "assault"
        # 3) 系统配发装备:随机 / 满配件 / 全是高级配件 / 大背包 / 足量备弹
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.save.mode = "assault"
        g2.save.difficulty = "easy"          # 固定强度:简单难度也应该是 50 名守军
        g2.save.stash.clear()
        g2.save.bag.clear()
        g2.save.weapon = Item.weapon("pm", mag=5)
        g2.save.armor = Item("paca")
        g2.save.pack = Item("pack_mid")
        g2.save.apply_pack()
        g2.save.bag.add_item(Item("a9", count=13))
        g2.save.stash.add_item(Item("gold"))
        g2.start_raid()
        r = g2.raid
        assert r.mode == "assault" and r.map_key == "base"
        assert r.diff_key == "assault" and r.diff["name"] == "突袭"
        assert len(r.scavs) >= ASSAULT_ENEMIES, len(r.scavs)
        assert len(r.allies) == ASSAULT_ALLIES
        assert len(r.objectives) == len(OBJECTIVES)
        assert len(r.friend_structs) == len(ALLY_STRUCTURES)
        # 要塞司令 + 5 名警卫,而且司令是硬点子
        boss = r.commander()
        assert boss is not None and boss.hp >= 400, boss
        assert len([s for s in r.scavs if s.tag == "guard"]) == 5
        assert len(r.scavs) == ASSAULT_ENEMIES + 6, len(r.scavs)
        assert r.support_points == ASSAULT_START_POINTS
        w = r.player.weapon
        assert w is not None and w.iid in ISSUE_WEAPONS, w.iid
        slots = weapon_slots(w.iid)
        att = w.state.get("attach") or {}
        assert slots and set(att) == set(slots), (w.iid, att, slots)
        for slot in slots:
            assert att[slot] == ISSUE_ATTACH[slot], (slot, att[slot])
        assert w.state["mag"] == weapon_capacity(w), w.state["mag"]
        assert r.player.armor.def_["level"] >= 5
        assert r.player.bag.w * r.player.bag.h >= 40
        ids = weapon_ammo_ids(w)
        assert sum(pl.item.count for pl in r.player.bag.items
                   if pl.item.iid in ids) >= 100, "备弹不足"
        assert any(pl.item.cat == "med" for pl in r.player.bag.items)
        rng = random.Random(7)
        for wp, ar, pk, its in (assault.build(rng) for _ in range(8)):
            assert set(wp.state.get("attach") or {}) == set(weapon_slots(wp.iid))
            assert wp.state["mag"] == weapon_capacity(wp)
        assert len({k[0].iid for k in (assault.build(rng) for _ in range(8))}) >= 2, \
            "配发武器应该随机"
        # 4) 友军支援:积分 / 冷却 / 呼叫 / 落弹杀敌 / 击杀涨积分
        r.support_points = 0
        ok, why = r.support_state("airstrike")
        assert not ok and "积分" in why, why
        assert not r.call_support("airstrike", r.player.x + 300, r.player.y)
        assert not r.strikes, "积分不足不该产生呼叫"
        r.support_points = 100
        tgt = (r.player.x + 380, r.player.y)
        assert r.call_support("airstrike", *tgt)
        assert r.support_points == 100 - SUPPORT["airstrike"]["cost"]
        ok, why = r.support_state("airstrike")
        assert not ok and "冷却" in why, why
        assert any(st["kind"] == "airstrike" for st in r.strikes)
        # 把一队守军堆到落点上,只留这队(顺便让用例跑得快)
        r.scavs = r.scavs[:12]
        for i, s in enumerate(r.scavs):
            s.x = tgt[0] + (i % 4) * 26 - 39
            s.y = tgt[1] + (i // 4) * 26 - 26
            s.state = "chase"
        r.player.hp = 100000          # 用例:玩家不会被打死,专心验证支援
        kills0, pts0 = r.kills, r.support_points
        for _ in range(int((SUPPORT["airstrike"]["delay"] + 4) * 60)):
            r.update(1 / 60, [])
            if r.kills > kills0:
                break
        assert r.kills > kills0, "空袭应该炸死落点上的守军"
        assert r.support_points > pts0, "击杀守军应该涨支援积分"
        assert r.support_points - pts0 >= 1 * (r.kills - kills0), "击杀守军必须涨积分"
        # 炮火覆盖:一发一发覆盖一片区域(不是一次性炸完)
        r.support_points = 100
        r.support_cd["barrage"] = 0.0
        assert r.call_support("barrage", r.player.x + 500, r.player.y)
        shells = 0
        for _ in range(int((SUPPORT["barrage"]["delay"] + 7) * 60)):
            r.update(1 / 60, [])
            shells = max(shells, sum(1 for st in r.strikes if st["kind"] == "shell"))
        assert shells >= 2, shells
        # 无人机侦察:延时后进入侦察状态
        r.support_cd["recon"] = 0.0
        r.support_points = 100
        assert r.call_support("recon", r.player.x, r.player.y)
        for _ in range(int((SUPPORT["recon"]["delay"] + 0.5) * 60)):
            r.update(1 / 60, [])
        assert r.recon_t > 0, r.recon_t
        assert r.support_calls >= 3, r.support_calls
        # 支援误伤自己人:不会像火箭弹那样一炮带走
        r.support_points = 100
        r.support_cd["airstrike"] = 0.0
        r.player.hp = 100
        r.player.armor = Item("b45")
        assert r.call_support("airstrike", r.player.x, r.player.y)
        for _ in range(int((SUPPORT["airstrike"]["delay"] + 1.5) * 60)):
            r.update(1 / 60, [])
        assert not r.over, "被自己的空袭打到不该直接阵亡(6 级甲)"
        assert r.player.hp < 100, "站在自己叫的空袭里应该受伤"
        # 5) 安放 C4 -> 25 秒起爆 -> 爆区半径内全灭、设施炸毁
        r.scavs = []
        r.player.armor = Item("b45")
        r.player.hp = 100
        for o in r.objectives:
            r.player.x, r.player.y = o.x, o.y + 24
            r.interact()
            assert r.channel is not None and r.channel["kind"] == "destroy", o.name
            assert r.channel_need() == ASSAULT_PLANT_TIME
            for _ in range(int((ASSAULT_PLANT_TIME + 0.8) * 60)):
                r.update(1 / 60, [])
                if r.channel is None:
                    break
            assert o.c4 is not None and o.c4["t"] > C4_FUSE - 0.5, (o.name, o.c4)
            assert not o.destroyed, "安好 C4 还没到点,设施不该已经没了"
            assert r.nearest_interactable()[1] is not o, "已安放 C4 的目标不该再提示安放"
            # 起爆
            for _ in range(int((C4_FUSE + 1.0) * 60)):
                r.update(1 / 60, [])
                if o.c4 is None:
                    break
            assert o.destroyed, f"{o.name} 应该被 C4 炸毁"
        assert r.objectives_done() and r.allows_extract()
        # 爆区半径:圈内必伤、圈外不伤
        g7 = Game()
        g7.save = save_mod.reset_data()
        g7.save.seen_intro = True
        g7.save.mode = "assault"
        g7.start_raid()
        r7 = g7.raid
        dep = next(s for s in r7.objectives if s.role == "depot")
        r7.scavs = r7.scavs[:3]
        r7.allies = []
        r7.player.hp = 100000
        r7.player.x, r7.player.y = dep.x + 900, dep.y
        near_s, far_s = r7.scavs[0], r7.scavs[1]
        near_s.x, near_s.y = dep.x + C4_BLAST_RADIUS - 20, dep.y
        far_s.x, far_s.y = dep.x + C4_BLAST_RADIUS + 140, dep.y
        midpoint_s = r7.scavs[2]
        midpoint_s.x, midpoint_s.y = dep.x, dep.y + C4_BLAST_RADIUS + 140
        for s in r7.scavs:
            s.hp = 100000
            s.d["speed"] = 0.0        # 用例:钉住他们,不然 25 秒里早跑出爆区了
            s.state = "idle"
        r7.plant_c4(dep)
        for _ in range(int((C4_FUSE + 1.0) * 60)):
            r7.update(1 / 60, [])
            if dep.c4 is None:
                break
        assert dep.destroyed
        assert near_s.hp < 100000, "半径内的守军必须吃到伤害"
        assert far_s.hp == 100000 and midpoint_s.hp == 100000, "半径外不该受伤"
        assert C4_FUSE == 25.0 and C4_BLAST_RADIUS == 170, (C4_FUSE, C4_BLAST_RADIUS)
        # 站在自己的 C4 爆区里:6 级甲掉一半血(没 6 级甲就会被带走)
        g8 = Game()
        g8.save = save_mod.reset_data()
        g8.save.seen_intro = True
        g8.save.mode = "assault"
        g8.start_raid()
        r8 = g8.raid
        r8.scavs = []
        r8.allies = []
        r8.player.armor = Item("bt201")
        cmd = next(s for s in r8.objectives if s.role == "command")
        r8.player.x, r8.player.y = cmd.x, cmd.y + 20
        r8.interact()
        for _ in range(int((ASSAULT_PLANT_TIME + 0.8) * 60)):
            r8.update(1 / 60, [])
            if r8.channel is None:
                break
        for _ in range(int((C4_FUSE + 1.0) * 60)):
            r8.update(1 / 60, [])
            if r8.over:
                break
        assert not r8.over and r8.player.hp == 50, (r8.over, r8.player.hp)
        # 5b) 设施能被打坏,而且会被各自一方派人修回来
        g9 = Game()
        g9.save = save_mod.reset_data()
        g9.save.seen_intro = True
        g9.save.mode = "assault"
        g9.start_raid()
        r9 = g9.raid
        r9.player.hp = 100000
        comms9 = next(s for s in r9.objectives if s.role == "comms")
        comms9.damage(comms9.max_hp * 0.5)
        assert comms9.damaged
        healed = False
        for _ in range(int(30 * 60)):
            r9.update(1 / 60, [])
            if not comms9.damaged:
                healed = True
                break
        assert healed, f"敌人应该派人把通讯站修回来({comms9.hp:.0f})"
        # 我方通讯室也一样(队友去修)
        fq9 = next(s for s in r9.friend_structs if s.role == "comms")
        fq9.damage(fq9.max_hp * 0.5)
        healed = False
        for _ in range(int(25 * 60)):
            r9.update(1 / 60, [])
            if not fq9.damaged:
                healed = True
                break
        assert healed, f"队友应该把前沿通讯室修回来({fq9.hp:.0f})"
        # 5c) 援兵:敌方靠 通讯站+司令,我方靠 指挥所+通讯室
        g10 = Game()
        g10.save = save_mod.reset_data()
        g10.save.seen_intro = True
        g10.save.mode = "assault"
        before10 = (g10.save.weapon.iid if g10.save.weapon else None,
                    g10.save.armor.iid if g10.save.armor else None,
                    g10.save.pack.iid if g10.save.pack else None,
                    sorted((pl.x, pl.y, pl.item.iid, pl.item.count)
                           for pl in g10.save.bag.items),
                    sorted((pl.x, pl.y, pl.item.iid, pl.item.count)
                           for pl in g10.save.stash.items))
        g10.start_raid()
        r10 = g10.raid
        r10.player.hp = 100000
        r10.scavs = [s for s in r10.scavs if s.tag in ("boss", "guard")]
        n0, a0, ew0 = len(r10.scavs), len(r10.allies), r10.enemy_waves
        for _ in range(int((ENEMY_REINF_INTERVAL + ALLY_REINF_INTERVAL + 2) * 60)):
            r10.update(1 / 60, [])
        assert r10.enemy_waves > ew0, "通讯站还在,敌方就该来援兵"
        assert len(r10.scavs) >= n0 + ENEMY_REINF_SQUAD
        assert r10.ally_waves >= 1 and len(r10.allies) > a0, "我方也该有援兵"
        # 打死司令:援兵照样来(剩下的兵自己会去呼叫总部)
        boss10 = r10.commander()
        assert boss10 is not None
        r10.kill_scav(boss10)
        assert r10.commander() is None
        ok, why = r10.reinforce_reason("enemy")
        assert ok, f"司令死了不该断援兵(总部按通讯站派人):{why}"
        ew = r10.enemy_waves
        r10.enemy_reinf_t = 0.1
        for _ in range(int(4 * 60)):
            r10.update(1 / 60, [])
        assert r10.enemy_waves > ew, "司令死后敌方援兵必须继续来"
        # 炸掉通讯站 -> 联系不上总部,援兵才断
        c10 = next(s for s in r10.objectives if s.role == "comms")
        c10.damage(c10.max_hp)
        ok, why = r10.reinforce_reason("enemy")
        assert not ok and "通讯" in why, why
        ew = r10.enemy_waves
        r10.enemy_reinf_t = 0.1
        for _ in range(int(3 * 60)):
            r10.update(1 / 60, [])
        assert r10.enemy_waves == ew, "通讯站炸了就不该再来敌援兵"
        # 我方通讯室被毁 -> 我援兵断
        f10 = next(s for s in r10.friend_structs if s.role == "comms")
        f10.damage(f10.max_hp)
        ok, why = r10.reinforce_reason("ally")
        assert not ok and "通讯" in why, why
        # 5d) 总指挥部反应:守军全灭(= 前沿失联)30 秒后察觉,派检修队查/修通讯站
        import raid as raid_mod
        from settings import HQ_REACTION_DELAY, HQ_REACTION_SQUAD
        g11 = Game()
        g11.save = save_mod.reset_data()
        g11.save.seen_intro = True
        g11.save.mode = "assault"
        g11.start_raid()
        r11 = g11.raid
        r11.player.hp = 100000
        comms11 = next(s for s in r11.objectives if s.role == "comms")
        comms11.damage(comms11.max_hp)
        assert comms11.destroyed
        r11.scavs = []                      # 守军全灭
        for _ in range(int((HQ_REACTION_DELAY - 3) * 60)):
            r11.update(1 / 60, [])
        assert r11.hq_t is not None and not r11.scavs, (r11.hq_t, len(r11.scavs))
        for _ in range(int(4 * 60)):
            r11.update(1 / 60, [])
        assert r11.hq_teams == 1, r11.hq_teams
        assert len(r11.scavs) == HQ_REACTION_SQUAD, len(r11.scavs)
        assert all(s.tag == "repair" for s in r11.scavs)
        assert all(s.repair_target is comms11 for s in r11.scavs), "检修队该直奔通讯站"
        # 到场开始抢修(把重建速度调快,免得用例跑太久)
        rate0 = raid_mod.REBUILD_RATE
        raid_mod.REBUILD_RATE = 300.0
        try:
            for s in r11.scavs:
                s.x, s.y = comms11.x + 20, comms11.y
            for _ in range(int(2 * 60)):
                r11.update(1 / 60, [])
                if comms11.rebuilding:
                    break
            assert comms11.rebuilding, (comms11.hp, comms11.destroyed)
            comms11.damage(comms11.max_hp)      # 抢修能被火力打断
            assert comms11.destroyed and comms11.hp == 0
            for _ in range(int(4 * 60)):
                r11.update(1 / 60, [])
                if not comms11.destroyed:
                    break
            assert not comms11.destroyed and comms11.hp == comms11.max_hp, \
                (comms11.destroyed, comms11.hp)
        finally:
            raid_mod.REBUILD_RATE = rate0
        # 修好 = 敌方援兵恢复
        ok, why = r11.reinforce_reason("enemy")
        assert ok, why
        w0 = r11.enemy_waves
        r11.enemy_reinf_t = 0.1
        for _ in range(int(3 * 60)):
            r11.update(1 / 60, [])
        assert r11.enemy_waves > w0, "通讯站修好后敌方援兵该恢复"
        # 通讯站完好时:检修队只是来看一眼,不修也不额外增援
        g12 = Game()
        g12.save = save_mod.reset_data()
        g12.save.seen_intro = True
        g12.save.mode = "assault"
        g12.start_raid()
        r12 = g12.raid
        r12.player.hp = 100000
        comms12 = next(s for s in r12.objectives if s.role == "comms")
        r12.scavs = []
        r12.enemy_reinf_t = 9999.0          # 冻结常规援兵波次,单独看这次反应
        for _ in range(int((HQ_REACTION_DELAY + 4) * 60)):
            r12.update(1 / 60, [])
        assert r12.hq_teams == 1 and len(r12.scavs) == HQ_REACTION_SQUAD
        assert all(s.repair_target is comms12 for s in r12.scavs)
        assert not comms12.destroyed and comms12.hp == comms12.max_hp
        assert r12.enemy_waves == 0, "通讯站没坏时不该因此增援"
        # 守军还在场 / 别的模式:都不触发
        g13 = Game()
        g13.save = save_mod.reset_data()
        g13.save.seen_intro = True
        g13.save.mode = "assault"
        g13.start_raid()
        r13 = g13.raid
        r13.player.hp = 100000
        for _ in range(int((HQ_REACTION_DELAY + 5) * 60)):
            r13.update(1 / 60, [])
        assert r13.hq_teams == 0 and r13.hq_t is None, (r13.hq_teams, r13.hq_t)
        g14 = Game()
        g14.save = save_mod.reset_data()
        g14.save.seen_intro = True
        g14.save.mode = "raid"
        g14.start_raid()
        r14 = g14.raid
        r14.scavs = []
        for _ in range(int(35 * 60)):
            r14.update(1 / 60, [])
        assert r14.hq_teams == 0 and r14.hq_t is None
        # 6) 撤离:设施没炸完,站撤离点也没用
        ex = r10.map.extracts[0][1]
        r10.player.x, r10.player.y = ex.centerx, ex.centery
        for _ in range(int((EXTRACT_TIME + 1) * 60)):
            r10.update(1 / 60, [])
        assert not r10.over, "设施没炸完不该能撤离"
        assert "locked" in r10.warned, "应该提示过要先炸设施"
        assert not r10.allows_extract()
        # 炸完之后可以撤(也顺便验证结算与存档还原)
        for o in r10.objectives:
            o.hp = 0.0
            o.destroyed = True
            o.c4 = None
        assert r10.allows_extract()
        for _ in range(int((EXTRACT_TIME + 1) * 60)):
            r10.update(1 / 60, [])
            if r10.over:
                break
        assert r10.over and r10.result["kind"] == "extract", r10.result
        assert r10.result["mission"] is True
        assert r10.result["objectives_done"] == len(r10.objectives)
        assert r10.result["enemy_waves"] >= 1 and r10.result["ally_waves"] >= 1
        assert r10.result["commander_killed"] is True
        assert r10.result["support_calls"] == r10.support_calls
        # 司令尸体:掉 6 级甲 + 专属枪械(M139)
        boss_corpse = [c for c in r10.containers if c.kind == "boss_corpse"]
        assert boss_corpse, "击杀司令应该有头目尸体"
        boss_ids = [p.item.iid for p in boss_corpse[0].container.items]
        assert "bt201" in boss_ids, boss_ids
        assert BOSSES["base"]["weapon"] == "m139" and "m139" in boss_ids, boss_ids
        # 撤离后:配发装备与战利品全部回收,玩家原配置原样还原
        sd = save_mod.load_data()
        def _loadout(s):
            return (s.weapon.iid if s.weapon else None,
                    s.armor.iid if s.armor else None,
                    s.pack.iid if s.pack else None,
                    sorted((pl.x, pl.y, pl.item.iid, pl.item.count)
                           for pl in s.bag.items),
                    sorted((pl.x, pl.y, pl.item.iid, pl.item.count)
                           for pl in s.stash.items))
        assert _loadout(sd) == before10, (_loadout(sd), before10)
        # 7) 阵亡也回收:系统装备不进存档,仓库不受影响
        g4 = Game()
        g4.save = save_mod.reset_data()
        g4.save.seen_intro = True
        g4.save.mode = "assault"
        stash_before = sorted((pl.x, pl.y, pl.item.iid) for pl in g4.save.stash.items)
        g4.start_raid()
        r4 = g4.raid
        assert r4.player.weapon.iid != "pm", "进突袭应该已经换成配发武器"
        r4.finish("death")
        sd4 = save_mod.load_data()
        assert sd4.weapon.iid == "pm" and sd4.armor is None
        assert sorted((pl.x, pl.y, pl.item.iid) for pl in sd4.stash.items) == stash_before
        # 8) 固定强度:三档难度都生成同样规模的守军(含司令与警卫)
        for diff in DIFF_ORDER:
            gd = Game()
            gd.save = save_mod.reset_data()
            gd.save.mode = "assault"
            gd.save.difficulty = diff
            gd.save.seen_intro = True
            gd.start_raid()
            assert gd.raid.diff_key == "assault", diff
            assert len(gd.raid.scavs) == ASSAULT_ENEMIES + 6, (diff, len(gd.raid.scavs))
            assert gd.raid.commander() is not None
        # 9) 渲染:突袭 HUD / 援兵行 / 支援面板 / 设施血条 / C4 爆区圈 / 结算页
        screen = pygame.display.set_mode((SW, SH))
        g5 = Game()
        g5.save = save_mod.reset_data()
        g5.save.seen_intro = True
        g5.save.mode = "assault"
        g5.start_raid()
        r5 = g5.raid
        r5.support_points = 12
        r5.recon_t = 5.0
        r5.objectives[0].destroyed = True
        r5.objectives[1].damage(r5.objectives[1].max_hp * 0.4)
        r5.objectives[2].c4 = dict(t=18.0)
        r5.friend_structs[1].damage(r5.friend_structs[1].max_hp * 0.5)
        r5.friend_structs[1].repair_workers = [r5.allies[0]]
        r5.strikes.append(dict(kind="airstrike", x=r5.player.x + 220, y=r5.player.y,
                               t=1.5, cfg=SUPPORT["airstrike"]))
        r5.strikes.append(dict(kind="barrage", x=r5.player.x - 220, y=r5.player.y,
                               t=1.0, cfg=SUPPORT["barrage"]))
        r5.strikes.append(dict(kind="shell", x=r5.player.x + 40, y=r5.player.y,
                               t=0.4, cfg=SUPPORT["barrage"]))
        r5.channel = dict(kind="destroy", ent=r5.objectives[1], t=1.0)
        g5.draw(screen)                       # 世界里:HUD/援兵/支援/设施/C4/落点/引导条
        r5.channel = None
        r5.over = False
        r5.paused = True
        g5.draw(screen)
        r5.paused = False
        r5.finish("extract")
        g5.draw(screen)                       # 突袭结算页
        pygame.display.flip()
        # 10) 触屏:突袭模式多出三个支援按钮,点了能呼叫
        g6 = Game()
        g6.save = save_mod.reset_data()
        g6.save.seen_intro = True
        g6.save.mode = "assault"
        g6.save.touch = True
        g6.start_raid()
        r6 = g6.raid
        assert r6.touch_mode and r6.touch.support
        lay = r6.touch.button_layout()
        assert {"sup1", "sup2", "sup3"} <= set(lay), lay.keys()
        assert "sup1" not in TouchUI().button_layout(), "普通模式不该有支援按钮"
        g6.draw(pygame.display.set_mode((SW, SH)))
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=lay["sup3"]["pos"])
        r6.update(1 / 60, [ev])
        assert (r6.recon_t > 0 or any(st["kind"] == "recon" for st in r6.strikes)), \
            "触屏支援按钮应该能呼叫"

    check("突袭模式-大本营/配发装备/友军支援/撤离限制", t_assault)

    def t_base():
        """基建:仓库扩容滚轮 / 背包卷起 / 我方弹药库 / 任务系统(教官·医疗·后勤)。"""
        from game import Game
        from world import GameMap
        from inventory import Placed
        from settings import (STASH_W, STASH_H, ITEMS as IT, STASH_VIEW_ROWS,
                              SUPPLY_RESERVE_CAP, SUPPLY_GIVE, SUPPLY_COOLDOWN,
                              PACK_ROLL_SMALL, PACK_ROLL_BIG, TASKS, DEPTS,
                              MODE_DIFF, HOSTAGE_ENEMIES, weapon_ammo_ids,
                              W as SW, H as SH)
        import quests
        # 1) 机密文件降到 500 万
        assert IT["doc"]["price"] == 5000000, IT["doc"]["price"]
        # 2) 人质模式固定强化封锁;室内图只留军械箱(弹药)与医疗箱
        im = GameMap("indoor")
        assert sorted({lc.kind for lc in im.loot}) == ["gun", "med"], \
            sorted({lc.kind for lc in im.loot})
        assert "indoor" not in MODE_DIFF or MODE_DIFF["indoor"] is not None
        assert MODE_DIFF.get("hostage") == "hardened"
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.mode = "hostage"
        g.save.difficulty = "easy"
        g.start_raid()
        assert g.raid.diff_key == "hardened", g.raid.diff_key
        assert g.raid.diff["name"] == "强化封锁"
        assert len(g.raid.scavs) == HOSTAGE_ENEMIES
        # 藏身处:人质模式点难度按钮不生效
        h = g.hideout
        h.show_intro = False
        h._click(h.diff_rects[0].center)
        assert g.save.difficulty == "easy"
        # 3) 仓库扩容 + 滚轮(命中要算上偏移)
        assert (STASH_W, STASH_H) == (10, 20), (STASH_W, STASH_H)
        sd = g.save
        sd.stash.clear()
        sd.stash.items.append(Placed(Item("gold"), 0, 0))
        sd.stash.items.append(Placed(Item("btc"), 0, 15))
        ox, oy = h.stash_grid
        h.stash_scroll = 0.0
        assert h.stash_hit((ox + 5, oy + 5)).item.iid == "gold"
        assert h.stash_hit((ox + 5, oy + 15 * 40 + 5)) is None
        h.stash_scroll = h.stash_max_scroll()
        assert h.stash_scroll > 0
        sy = oy + 15 * 40 - int(h.stash_scroll) + 5
        hit = h.stash_hit((ox + 5, sy))
        assert hit is not None and hit.item.iid == "btc", hit
        assert h.stash_view_h == 40 * STASH_VIEW_ROWS
        h.stash_scroll = 0.0
        # 4) 背包卷起 / 展开
        small, big = Item("pack_small"), Item("pack_xl")
        assert small.roll_size() == PACK_ROLL_SMALL and small.base_size() == (2, 2)
        assert big.roll_size() == PACK_ROLL_BIG and big.base_size() == (5, 4)
        c = Container(12, 8)
        assert c.add_item(small) and c.add_item(big)
        ps = c.at(0, 0)
        pb = next(p for p in c.items if p.item is big)
        ok, _m = h._toggle_roll(c, ps)
        assert ok and ps.item.is_rolled() and ps.item.size() == (1, 2)
        ok, _m = h._toggle_roll(c, pb)
        assert ok and pb.item.size() == (2, 2)
        # 展不开就保持卷起,不能把东西弄丢
        tight = Container(1, 2)
        rp = Item("pack_small")
        rp.state["rolled"] = True
        assert tight.add_item(rp)
        placed = tight.at(0, 0)
        ok, msg = h._toggle_roll(tight, placed)
        assert not ok and placed.item.is_rolled() and len(tight.items) == 1
        assert "展不开" in msg
        # 序列化保留卷起状态;装备时自动展开
        back = Item.from_dict(Item("pack_xl", state={"rolled": True}).serialize())
        assert back.is_rolled() and back.size() == (2, 2)
        sd.stash.clear()
        sd.bag.clear()
        sd.weapon = Item.weapon("pm", mag=8)
        sd.pack = None
        sd.apply_pack()
        rp2 = Item("pack_mid")
        rp2.state["rolled"] = True
        sd.stash.add_item(rp2)
        idx = next(i for i, p in enumerate(sd.stash.items)
                   if p.item.iid == "pack_mid")
        ok, _m = h._try_equip_pack(idx)
        assert ok and not sd.pack.is_rolled()
        # 5) 突袭我方弹药库:补弹 / 冷�ed却 / 上限
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.save.mode = "assault"
        g2.start_raid()
        r2 = g2.raid
        assert len(r2.supplies) == 1, r2.supplies
        sp = r2.supplies[0]
        assert sp.name == "前沿弹药库"
        r2.player.bag.clear()
        ids = weapon_ammo_ids(r2.player.weapon)
        iid = r2.player.weapon.state.get("loaded")
        if iid not in ids:
            iid = ids[0]
        assert r2.use_supply(sp) is True
        have = sum(pl.item.count for pl in r2.player.bag.items if pl.item.iid == iid)
        assert have == min(SUPPLY_GIVE, SUPPLY_RESERVE_CAP), have
        assert sp.cd > 0
        assert r2.use_supply(sp) is False, "冷却中不该能连点"
        for _ in range(int(SUPPLY_COOLDOWN * 60) + 2):
            r2.update(1 / 60, [])
        assert sp.cd == 0
        assert r2.use_supply(sp) is True
        # 补到上限就不再给
        r2.player.bag.clear()
        r2.player.bag.add_item(Item(iid, count=SUPPLY_RESERVE_CAP))
        sp.cd = 0.0
        assert r2.use_supply(sp) is False, "备弹满了不该再给"
        # 交互:E 能补弹(supply 交互不走引导)
        r2.player.bag.clear()
        sp.cd = 0.0
        r2.player.x, r2.player.y = sp.x, sp.y + 20
        r2.interact()
        assert r2.channel is None, "补弹应该立刻生效,不用读条"
        assert sp.cd > 0, "E 补弹应该生效"
        # 6) 任务系统
        g3 = Game()
        g3.save = save_mod.reset_data()
        sd3 = g3.save
        sd3.stash.clear()
        sd3.bag.clear()
        t1 = quests.task_by_id("t1")           # 击杀 5 -> 3 万 + 9mm 子弹
        assert quests.task_state(sd3, t1)[0] == "doing"
        quests.add_progress(sd3, "kills", 5)
        assert quests.task_state(sd3, t1)[0] == "ready"
        rub0 = sd3.rubles
        ok, msg = quests.claim(sd3, t1)
        assert ok and sd3.rubles == rub0 + 30000, msg
        assert any(p.item.iid == "a9" for p in sd3.stash.items)
        assert quests.task_state(sd3, t1)[0] == "done"
        assert not quests.claim(sd3, t1)[0], "一次性任务不该能领两次"
        # 可重复任务:结算后扣掉已用进度
        t7 = quests.task_by_id("t7")
        quests.add_progress(sd3, "kills", 25)
        st, p, _n = quests.task_state(sd3, t7)
        assert st == "ready"
        assert quests.claim(sd3, t7)[0]
        assert quests.progress(sd3, t7) == p - 10, (p, quests.progress(sd3, t7))
        # 奖励种类:钱 / 配件 / 子弹 / 枪
        for tid, key in (("t2", "attachments"), ("t5", "weapons"), ("t6", "ammo")):
            task = quests.task_by_id(tid)
            assert key in task["reward"], (tid, task["reward"])
        # 仓库放不下 -> 不发奖(也不吞进度)
        orig_stash = sd3.stash
        full = Container(sd3.stash.w, sd3.stash.h)
        for gy in range(sd3.stash.h):
            for gx in range(sd3.stash.w):
                full.items.append(Placed(Item("bandage"), gx, gy))
        sd3.stash = full
        sd3.tasks_done = [t for t in sd3.tasks_done if t != "t2"]
        quests.add_progress(sd3, "extracts", 3)
        assert quests.task_state(sd3, quests.task_by_id("t2"))[0] == "ready"
        rub1 = sd3.rubles
        ok, msg = quests.claim(sd3, quests.task_by_id("t2"))
        assert not ok and "放不下" in msg, msg
        assert sd3.rubles == rub1, "发不出去就不该给钱"
        assert quests.task_state(sd3, quests.task_by_id("t2"))[0] == "ready"
        sd3.stash = orig_stash
        # 医疗部门交货
        sd3.stash.clear()
        sd3.bag.clear()
        m1 = quests.barter_list("medical")[0]
        ok, msg = quests.barter(sd3, m1)
        assert not ok and "缺" in msg, msg
        sd3.stash.add_item(Item("bandage", count=2))
        ok, msg = quests.barter(sd3, m1)
        assert ok, msg
        assert not any(p.item.iid == "bandage" for p in sd3.stash.items)
        assert any(p.item.iid == "painkiller" for p in sd3.stash.items)
        # 后勤部门:材料在背包里也能交
        sd3.stash.clear()
        sd3.bag.clear()
        l4 = quests.barter_list("logistics")[3]
        sd3.bag.add_item(Item("fuelcan", count=2))
        sd3.bag.add_item(Item("tools"))
        ok, msg = quests.barter(sd3, l4)
        assert ok and any(p.item.iid == "korund" for p in sd3.stash.items), msg
        # 交货时仓库放不下 -> 不扣材料
        sd3.stash.clear()
        sd3.bag.clear()
        sd3.stash.add_item(Item("bandage", count=2))
        full2 = Container(sd3.stash.w, sd3.stash.h)
        for gy in range(sd3.stash.h):
            for gx in range(sd3.stash.w):
                full2.items.append(Placed(Item("bandage"), gx, gy))
        sd3.stash = full2
        before = quests.have_count(sd3, "bandage")
        ok, msg = quests.barter(sd3, m1)
        assert not ok and "放不下" in msg
        assert quests.have_count(sd3, "bandage") == before, "失败不该扣材料"
        # 战局结算累计进度(击杀/撤离/价值/人质/突袭)
        g4 = Game()
        g4.save = save_mod.reset_data()
        sd4 = g4.save
        sd4.tasks, sd4.tasks_done = {}, []
        g4.raid = None
        g4.phase = "raid"
        g4.rail_player = None
        class _FakeRaid:
            player = type("_P", (), {"weapon": None, "armor": None})()
        g4.raid = _FakeRaid()
        g4.raid_finished(dict(kind="extract", kills=7, gained=350000, n=2, time=60,
                              entries=[], mode="raid", rescued=0, hostages=0,
                              objectives=0, objectives_done=0, support_calls=0,
                              support_points=0, enemy_waves=0, ally_waves=0,
                              commander_killed=False, mission=True))
        assert quests.progress(sd4, quests.task_by_id("t1")) == 7
        assert quests.progress(sd4, quests.task_by_id("t2")) == 1
        assert quests.progress(sd4, quests.task_by_id("t3")) == 350000
        sd4.tasks = {}
        g4.raid_finished(dict(kind="extract", kills=0, gained=0, n=0, time=60,
                              entries=[], mode="hostage", rescued=4, hostages=4,
                              objectives=0, objectives_done=0, support_calls=0,
                              support_points=0, enemy_waves=0, ally_waves=0,
                              commander_killed=False, mission=True))
        assert quests.progress(sd4, quests.task_by_id("t4")) == 1
        sd4.tasks = {}
        g4.raid_finished(dict(kind="extract", kills=0, gained=0, n=0, time=60,
                              entries=[], mode="assault", rescued=0, hostages=0,
                              objectives=3, objectives_done=3, support_calls=1,
                              support_points=5, enemy_waves=2, ally_waves=1,
                              commander_killed=True, mission=True))
        assert quests.progress(sd4, quests.task_by_id("t5")) == 1
        assert quests.progress(sd4, quests.task_by_id("t3")) == 0, \
            "突袭不算物资价值"
        # 任务进度要能存进存档
        save_mod.save_data(sd3)
        sd5 = save_mod.load_data()
        assert sd5.tasks == sd3.tasks and sd5.tasks_done == sd3.tasks_done
        # 7) 渲染:藏身处(仓库滚动)/ 任务中心 / 交易所 / 突袭 HUD
        screen = pygame.display.set_mode((SW, SH))
        g5 = Game()
        g5.save = save_mod.reset_data()
        g5.save.seen_intro = True
        g5.save.stash.add_item(Item("pack_xl", state={"rolled": True}))
        g5.hideout.show_intro = False
        g5.draw(screen)                       # 藏身处(仓库滚动视图)
        g5.hideout.stash_scroll = g5.hideout.stash_max_scroll()
        g5.draw(screen)
        g5.hideout.view = "task"
        for dept in ("instructor", "medical", "logistics"):
            g5.hideout.task_dept = dept
            g5.draw(screen)                   # 任务中心三个部门
        g5.hideout.view = "trade"
        g5.draw(screen)                       # 交易所(仓库滚动)
        g5.hideout.view = "stash"
        pygame.display.flip()

    check("基建-仓库滚动/背包卷起/弹药库/任务系统", t_base)

    ok = all(r[1] for r in results)
    report = ["Tarkov2D selftest " + ("PASS" if ok else "FAIL"), ""]
    for name, passed, err in results:
        report.append(("  [PASS] " if passed else "  [FAIL] ") + name +
                       ("  -- " + err if err else ""))
    text = "\n".join(report)
    path = os.path.abspath("selftest_report.txt")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        print("report ->", path)
    except Exception:
        pass
    return ok


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
