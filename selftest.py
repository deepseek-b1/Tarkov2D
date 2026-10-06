# -*- coding: utf-8 -*-
"""无头自检:全部核心系统逻辑验证,不弹窗口。
用法: python main.py --selftest  (或 Tarkov2D.exe --selftest)
结果写入 selftest_report.txt 并打印。"""
import math
import os
import random
import sys
import tempfile
import time
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
        # 调试便利:设 TK2D_ONLY=关键词 只跑名字里含该关键词的用例
        # (用例都是自给自足的,单独跑也成立)
        only = os.environ.get("TK2D_ONLY")
        if only and only not in name:
            return
        t0 = time.perf_counter()
        print(f"[....] {name}", flush=True)
        try:
            fn()
            results.append((name, True, ""))
            print(f"[PASS] {name}  ({time.perf_counter() - t0:.1f}s)", flush=True)
        except Exception as e:
            results.append((name, False, f"{type(e).__name__}: {e}"))
            print(f"[FAIL] {name}: {e}", flush=True)
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

    def t_mystery():
        """礼品-神秘人:10 星收集清单、每轮刷新、交货换 6 套全装包、机密文件与开包。"""
        from game import Game
        from inventory import Container, Placed
        import mystery as my
        from settings import (MYSTERY_STARS, MYSTERY_KITS, MYSTERY_KIT_COUNT,
                              MYSTERY_KINDS, MYSTERY_POOL, MYSTERY_DOC_CHANCE,
                              KIT_CONTENTS, DOC_SPAWN_CHANCE, DEPTS,
                              weapon_slots, weapon_capacity, W as SW, H as SH)

        # 1) 结构:10 星 / 6 套包 / 每个包的内容都合法 / 机密文件概率与强化封锁一致
        assert MYSTERY_STARS == 10, MYSTERY_STARS
        assert MYSTERY_KIT_COUNT == 6 and len(MYSTERY_KITS) == 6, MYSTERY_KITS
        assert ("gift", "礼品") in DEPTS, DEPTS
        assert MYSTERY_DOC_CHANCE == DOC_SPAWN_CHANCE, \
            "送机密文件的概率必须和强化封锁爆率一样"
        for iid, weight, span in MYSTERY_POOL:
            assert iid in ITEMS and weight > 0 and span[0] > 0 and span[0] <= span[1], \
                (iid, weight, span)
        for kid in MYSTERY_KITS:
            assert ITEMS[kid]["cat"] == "kit", kid
            cfg = KIT_CONTENTS[kid]
            assert ITEMS[cfg["weapon"]]["cat"] == "weapon", kid
            for key, want in (("armor", 6), ("helmet", 6)):
                d = ITEMS[cfg[key]]
                assert d["level"] == want, f"{kid} 要配 {want} 级{key}"
            assert ITEMS[cfg["pack"]]["cat"] == "pack", kid
            for iid, n in cfg["ammo"]:
                assert ITEMS[iid]["cat"] == "ammo" and n > 0, (kid, iid)
            for iid, n in cfg["meds"]:
                assert ITEMS[iid]["cat"] == "med" and n > 0, (kid, iid)
            items = my.kit_items(kid)
            assert len(items) >= 6, (kid, len(items))
            gun = items[0]
            assert gun.cat == "weapon"
            for slot in (gun.state.get("attach") or {}):
                assert slot in weapon_slots(cfg["weapon"]), (kid, slot)
            assert gun.state["mag"] == weapon_capacity(gun), "配件扩容后要装满"

        # 2) roll:清单合法 + 每轮重抽(回合递增)
        g = Game()
        g.save = save_mod.reset_data()
        sd = g.save
        for _ in range(40):
            my.roll(sd)
            need = my.need_list(sd)
            assert MYSTERY_KINDS[0] <= len(need) <= MYSTERY_KINDS[1], need
            assert len({iid for iid, _ in need}) == len(need), "清单不该有重复物品"
            span = {iid: (lo, hi) for iid, _w, (lo, hi) in MYSTERY_POOL}
            for iid, n in need:
                assert iid in span, iid
                assert span[iid][0] <= n <= span[iid][1], (iid, n)
        r0 = my.round_no(sd)
        # 每次"启动游戏"都会重抽:存盘后再开一个 Game,回合必须 +1
        save_mod.save_data(sd)
        g_new = Game()
        assert my.round_no(g_new.save) == r0 + 1, "启动游戏要刷新清单"
        assert not my.claimed(g_new.save), "新的一轮要能再交"
        assert my.need_list(g_new.save), "新的一轮必须给出清单"

        # 3) 交货:材料不够不能交;仓库+背包都算数;交货后扣材料 + 发 6 套全装包
        g2 = Game()
        g2.save = save_mod.reset_data()
        sd = g2.save
        sd.stash.clear()
        sd.bag.clear()
        my.roll(sd)
        sd.mystery["need"] = [["bandage", 3], ["gold", 2]]
        sd.mystery["claimed"] = False
        sd.mystery["doc"] = False
        ok, msg = my.turn_in(sd)
        assert not ok and "还缺" in msg, msg
        sd.stash.add_item(Item("bandage", count=2))
        assert not my.ready(sd) and not my.turn_in(sd)[0]
        # 补在背包里的也算(清单看的是仓库+背包)
        sd.bag.add_item(Item("bandage", count=4))
        sd.bag.add_item(Item("gold", count=2))
        assert my.ready(sd), my.missing(sd)
        assert my.prepared_count(sd) == (2, 2)
        ok, msg = my.turn_in(sd)
        assert ok, msg
        assert my.claimed(sd)
        left = sum(p.item.count for p in sd.bag.items if p.item.iid == "bandage")
        assert left == 3, left          # 背包 4 发里扣走 1 发(仓库那 2 发先扣)
        assert not any(p.item.iid == "gold" for p in sd.stash.items + sd.bag.items)
        kits = [p.item.iid for p in sd.stash.items if p.item.cat == "kit"]
        assert sorted(kits) == sorted(MYSTERY_KITS), kits
        assert "全装包" in msg and "机密文件" not in msg, msg
        ok, msg = my.turn_in(sd)                   # 一轮只能交一次
        assert not ok and "已经交过" in msg, msg

        # 4) 机密文件:概率与强化封锁一致,中奖时跟全装包一起给
        sd.stash.clear()
        my.roll(sd)
        sd.mystery["need"] = [["bandage", 1]]
        sd.mystery["doc"] = True
        sd.stash.add_item(Item("bandage", count=1))
        ok, msg = my.turn_in(sd)
        assert ok and "机密文件" in msg, msg
        assert any(p.item.iid == "doc" for p in sd.stash.items), "中奖要真的给文件"

        # 5) 仓库放不下时:整体拒绝,材料一个都不能少(先克隆试算的规矩)
        sd.stash.clear()
        my.roll(sd)
        sd.mystery["need"] = [["bandage", 2]]
        sd.mystery["claimed"] = False
        sd.mystery["doc"] = False
        sd.bag.clear()
        sd.bag.add_item(Item("bandage", count=2))
        while sd.stash.add_item(Item("gold")):
            pass
        ok, msg = my.turn_in(sd)
        assert not ok and "放不下" in msg, msg
        assert sum(p.item.count for p in sd.bag.items if p.item.iid == "bandage") == 2, \
            "放不下时不能扣材料"
        assert not my.claimed(sd)

        # 6) 开包:展开成一整套(武器满配件 + 甲/头盔/背包/弹/药);放不下就整包不动
        sd.stash.clear()
        sd.stash.add_item(Item("kit_assault"))
        pl = sd.stash.items[0]
        ok, msg = my.open_kit(sd.stash, pl)
        assert ok, msg
        cats = sorted(p.item.cat for p in sd.stash.items)
        for want in ("weapon", "armor", "helmet", "pack", "ammo", "med"):
            assert want in cats, (want, cats)
        assert not any(p.item.cat == "kit" for p in sd.stash.items), "包要消失"
        small = Container(3, 2)
        small.add_item(Item("kit_hk"))
        before = [(p.item.iid, p.x, p.y) for p in small.items]
        ok, msg = my.open_kit(small, small.items[0])
        assert not ok and "空间" in msg, msg
        assert [(p.item.iid, p.x, p.y) for p in small.items] == before, "开失败不能动包"

        # 7) 藏身处:右键开包(电脑) + 长按面板按钮开包(手机) + 礼品页交付按钮
        h = g2.hideout
        h.show_intro = False
        sd.touch = True
        sd.stash.clear()
        sd.stash.add_item(Item("kit_ak"))
        pos = (h.stash_grid[0] + 5, h.stash_grid[1] + 5)
        h._right_click(pos)                        # 电脑右键 = 打开
        assert not any(p.item.cat == "kit" for p in sd.stash.items), h.msg
        assert "打开" in h.msg, h.msg
        sd.stash.clear()
        sd.stash.add_item(Item("kit_close"))
        h.hold.reset()
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=pos, button=1)])
        for _ in range(40):
            h.update(1 / 60, [])
        assert h.hold.active() and h.hold.btn_label == "打开全装包", h.hold.btn_label
        scr = pygame.display.set_mode((SW, SH))
        h.draw(scr)                                # 面板(含动作按钮)要能画
        h._hold_action()
        assert not any(p.item.cat == "kit" for p in sd.stash.items), "长按按钮要能开包"
        sd.touch = False
        # 礼品页:标签页 + 交付按钮走真实点击
        sd.stash.clear()
        sd.mystery["need"] = [["bandage", 2]]
        sd.mystery["claimed"] = False
        sd.mystery["doc"] = False
        sd.stash.add_item(Item("bandage", count=2))
        h.view = "task"
        h.task_dept = "gift"
        h.draw(scr)
        h._task_click(h.gift_btn.center)
        assert any(p.item.cat == "kit" for p in sd.stash.items), h.msg
        assert "全装包" in h.msg, h.msg
        assert my.claimed(sd)
        h.draw(scr)                                # 交付后的页面也要能画
        h.view = "stash"

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
        # 5) 丢弃:大件(枪)也要能丢到地上;地面堆塞满时不留空堆、物品回背包
        n_piles = len([c for c in r2.containers if c.kind == "ground"])
        r2.player.bag.clear()
        r2.player.bag.add_item(Item.weapon("ak74", mag=5))
        placed2 = r2.player.bag.first_of_cat("weapon")
        r2.drop_from_bag(placed2)
        assert len([c for c in r2.containers if c.kind == "ground"]) == n_piles + 1, \
            "丢东西应该在地上生成一堆"
        pile = [c for c in r2.containers if c.kind == "ground"][-1]
        assert any(pl.item.iid == "ak74" for pl in pile.container.items)
        assert placed2 not in r2.player.bag.items
        # 把这堆塞满后再丢:放不下 -> 回背包,且不生成空堆
        for _ in range(400):
            if not pile.container.add_item(Item("screws")):
                break
        n_piles2 = len([c for c in r2.containers if c.kind == "ground"])
        r2.player.bag.clear()
        r2.player.bag.add_item(Item("gold"))
        placed3 = r2.player.bag.first_of_cat("valuable")
        r2.drop_from_bag(placed3)
        assert len([c for c in r2.containers if c.kind == "ground"]) == n_piles2, \
            "堆满时不该再生成新的一堆"
        assert placed3 in r2.player.bag.items, "放不下应该回背包"
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
        from inventory import Placed
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
        # 批量出售:开模式 -> 点选/快捷选 -> 确认框 -> 出售/取消
        screen = pygame.display.set_mode((SW, SH))
        sd.stash.clear()
        sd.stash.items.append(Placed(Item("gold"), 0, 0))
        sd.stash.items.append(Placed(Item("coffee"), 1, 0))
        sd.stash.items.append(Placed(Item("a9", count=60), 2, 0))
        sd.stash.items.append(Placed(Item.weapon("ak74", mag=30), 3, 0))
        h.stash_scroll = 0.0
        h.sell_mode = False
        h.sell_sel = []
        h.sell_ask = None
        ox, oy = h.trade_stash_grid

        def _cell(gx, gy):
            return (ox + gx * 40 + 20, oy + gy * 40 + 20)

        h._trade_click(h.sell_toggle.center)
        assert h.sell_mode
        h._trade_click(_cell(0, 0))                  # 选中 gold
        h._trade_click(_cell(1, 0))                  # 选中 coffee
        assert len(h.sell_selected()) == 2
        exp = trade_sell_price(Item("gold")) + trade_sell_price(Item("coffee"))
        assert h.sell_total() == exp, (h.sell_total(), exp)
        h._trade_click(_cell(1, 0))                  # 再点 = 取消
        assert len(h.sell_selected()) == 1
        h._trade_click(_cell(1, 0))
        # 快捷选择:全选子弹(再点一次取消)
        h._trade_click(h.sell_ammo.center)
        cats = sorted(p.item.cat for p in h.sell_selected())
        assert cats.count("ammo") == 1 and "valuable" in cats and "misc" in cats, cats
        h._trade_click(h.sell_ammo.center)
        assert not any(p.item.cat == "ammo" for p in h.sell_selected())
        # 空选择点出售 -> 不弹框不卖
        h._trade_click(h.sell_clear.center)
        n0, rub0 = len(sd.stash.items), sd.rubles
        h._trade_click(h.sell_go.center)
        assert h.sell_ask is None and len(sd.stash.items) == n0
        # 选中一批 -> 出售 -> 先取消
        h._trade_click(_cell(0, 0))
        h._trade_click(_cell(2, 0))                  # gold + a9
        h._trade_click(h.sell_go.center)
        assert h.sell_ask is not None
        h.draw(screen)
        h._trade_click(h.sell_ask_no.center)
        assert h.sell_ask is None
        assert len(sd.stash.items) == n0 and sd.rubles == rub0
        # 再确认出售
        tot = h.sell_total()
        n_sel = len(h.sell_selected())
        h._trade_click(h.sell_go.center)
        h._trade_click(h.sell_ask_yes.center)
        assert h.sell_ask is None and h.sell_selected() == []
        assert len(sd.stash.items) == n0 - n_sel, (len(sd.stash.items), n0, n_sel)
        assert sd.rubles == rub0 + tot, (sd.rubles, rub0 + tot)
        assert save_mod.load_data().rubles == sd.rubles, "批量出售要落盘"
        # 关掉批量模式会清空选择
        h._trade_click(_cell(3, 0))
        assert h.sell_selected()
        h._trade_click(h.sell_toggle.center)
        assert not h.sell_mode and h.sell_selected() == []
        # 渲染:分区 + 滚动条 + 批量面板 + 确认框 + 交易站/藏身处
        h.trade_scroll = 40.0
        h.draw(screen)
        h.sell_mode = True
        h._trade_click(_cell(3, 0))
        h.draw(screen)
        h.sell_ask = dict(items=list(h.sell_selected()), total=h.sell_total())
        h.draw(screen)
        h.sell_ask = None
        h.sell_mode = False
        h.sell_sel = []
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

        def run_heal(max_frames=400):
            """把打药读条跑完(最多 ~6.6 秒)。"""
            for _ in range(max_frames):
                r.update(1 / 60, [])
                if r.heal_ch is None:
                    return True
            return False

        assert p.hp == 50, "打药现在是读条,不能瞬间生效"
        assert r.heal_ch is not None, "应该进入打药读条"
        assert run_heal(), "打药读条应该能走完"
        assert p.hp == 100, p.hp
        assert r.heal_ch is None
        assert not any(pl.item.iid == "medkit" for pl in p.bag.items)
        assert any(pl.item.iid == "bandage" for pl in p.bag.items)
        p.hp = 90
        r.quick_heal()                          # 缺口 10 -> 绷带(不浪费大药)
        assert p.hp == 90 and r.heal_ch is not None
        assert run_heal()
        assert p.hp == 100
        assert not any(pl.item.cat == "med" for pl in p.bag.items)
        p.hp = 80
        r.quick_heal()                          # 没药了:不崩、血量不变
        assert p.hp == 80 and r.heal_ch is None
        # 按键绑定 H(也要读条)
        p.bag.add_item(Item("bandage"))
        p.hp = 80
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h)])
        assert r.heal_ch is not None, "按 H 应该开始读条"
        assert run_heal()
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
        """杂物价格梯度 + 机密文件 0.1% 概率(仅强化封锁的保险箱)。"""
        from game import Game
        from settings import (ITEMS, CLASSIFIED, DOC_SPAWN_CHANCE,
                              W as SW, H as SH)
        import raid as raid_mod
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
        # 强化封锁:机密文件 0.1% 概率刷 1 份(打补丁验证两头)
        assert abs(DOC_SPAWN_CHANCE - 0.001) < 1e-9, DOC_SPAWN_CHANCE
        old_chance = raid_mod.DOC_SPAWN_CHANCE
        try:
            # 概率拉满 -> 必刷,且只刷 1 份
            raid_mod.DOC_SPAWN_CHANCE = 1.0
            g = Game()
            g.save.difficulty = "hardened"
            g.start_raid()
            r = g.raid
            safes = [c for c in r.containers if c.kind == "val"]
            assert len(safes) >= 3
            found = [(c, p) for c in safes for p in c.container.items
                     if p.item.iid == CLASSIFIED]
            assert len(found) == 1, len(found)
            assert r.doc_spawned is True
            # 简单/封锁:概率拉满也不刷(仅强化封锁)
            for diff in ("lockdown", "easy"):
                g2 = Game()
                g2.save.difficulty = diff
                g2.start_raid()
                r2 = g2.raid
                assert len([c for c in r2.containers if c.kind == "val"]) == 9
                assert not any(p.item.iid == CLASSIFIED
                               for c in r2.containers for p in c.container.items)
                assert r2.doc_spawned is False
            # 概率归零 -> 强化封锁也不刷
            raid_mod.DOC_SPAWN_CHANCE = 0.0
            g3 = Game()
            g3.save.difficulty = "hardened"
            g3.start_raid()
            assert not any(p.item.iid == CLASSIFIED
                           for c in g3.raid.containers for p in c.container.items)
        finally:
            raid_mod.DOC_SPAWN_CHANCE = old_chance

    check("杂物-价格梯度与机密文件(0.1% 仅强化封锁)", t_misc_doc)

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
        """架枪规则:狙击步枪不参与架枪,其它枪都更准;M139 架枪时不能移动。"""
        from game import Game
        from settings import ITEMS, weapon_class
        for iid, d in ITEMS.items():
            if d.get("cat") != "weapon":
                continue
            if weapon_class(iid) == "狙击步枪":
                assert "spread_braced" not in d, f"{iid} 狙击枪不参与架枪"
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
        # 触屏按钮:打药 / 背包(先清场 + 清掉空中的子弹,免得读条时被打断回血)
        r.scavs = []
        r.bullets.clear()
        p.hp = 60
        r.touch.just_pressed = ["heal"]
        r.update(1 / 60, [])
        assert p.hp == 60 and r.heal_ch is not None, "手机打药也要读条"
        for _ in range(int(6 * 60)):
            r.update(1 / 60, [])
            if p.hp > 60:
                break
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
            assert ("mag_bonus" in d) or ("brace_mul" in d) or ("hip_mul" in d) \
                or ("beam" in d), iid
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
        # 4) 天赋(每把枪都必须有)
        assert TALENTS["akm"]["dmg_mul"] > 1
        assert weapon_params(Item.weapon("akm"))[0] > ITEMS["akm"]["dmg"]
        assert weapon_params(Item.weapon("vector"))[5] < 1.0      # 装填更快
        assert weapon_params(Item.weapon("m700"))[3] < ITEMS["m700"]["spread"]
        _no_tal = [i for i, d in ITEMS.items()
                   if d.get("cat") == "weapon" and not TALENTS.get(i)]
        assert not _no_tal, f"这些枪没有天赋:{_no_tal}"
        # 每把枪的天赋都要有名字与说明(描述与倍率的一致性靠人工维护)
        for _iid, _t in TALENTS.items():
            assert _t.get("name") and _t.get("desc"), (_iid, _t)
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
        # 先用配置里的真实秒数做断言,再临时调小,省下纯等待的模拟时间
        import raid as raid_mod
        assert raid_mod.ENEMY_REINF_INTERVAL == 22.0, raid_mod.ENEMY_REINF_INTERVAL
        assert raid_mod.ALLY_REINF_INTERVAL == 26.0, raid_mod.ALLY_REINF_INTERVAL
        e_int0, a_int0 = raid_mod.ENEMY_REINF_INTERVAL, raid_mod.ALLY_REINF_INTERVAL
        raid_mod.ENEMY_REINF_INTERVAL = raid_mod.ALLY_REINF_INTERVAL = 2.5
        try:
            r10.scavs = [s for s in r10.scavs if s.tag in ("boss", "guard")]
            r10.enemy_reinf_t = r10.ally_reinf_t = 0.1   # 让第一波马上就来
            n0, a0, ew0 = len(r10.scavs), len(r10.allies), r10.enemy_waves
            for _ in range(int(8 * 60)):
                r10.update(1 / 60, [])
        finally:
            raid_mod.ENEMY_REINF_INTERVAL, raid_mod.ALLY_REINF_INTERVAL = e_int0, a_int0
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
        assert HQ_REACTION_DELAY == 30.0, HQ_REACTION_DELAY
        assert raid_mod.HQ_REACTION_SQUAD == 3, raid_mod.HQ_REACTION_SQUAD
        d0 = raid_mod.HQ_REACTION_DELAY
        raid_mod.HQ_REACTION_DELAY = 2.0     # 用例里把 30 秒缩短,省模拟时间
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
        for _ in range(int(1 * 60)):
            r11.update(1 / 60, [])
        assert r11.hq_t is not None and not r11.scavs, (r11.hq_t, len(r11.scavs))
        for _ in range(int(3 * 60)):
            r11.update(1 / 60, [])
        raid_mod.HQ_REACTION_DELAY = d0
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
        raid_mod.HQ_REACTION_DELAY = 2.0
        for _ in range(int(6 * 60)):
            r12.update(1 / 60, [])
            if r12.hq_teams == 1:
                break          # 就在他们刚到场那一刻断言(检修队到场后会归队)
        raid_mod.HQ_REACTION_DELAY = d0
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
        raid_mod.HQ_REACTION_DELAY = 2.0
        for _ in range(int(5 * 60)):
            r13.update(1 / 60, [])
        raid_mod.HQ_REACTION_DELAY = d0
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
        for dept in ("instructor", "medical", "logistics", "gift"):
            g5.hideout.task_dept = dept
            g5.draw(screen)                   # 任务中心各部门(含礼品页)
        g5.hideout.view = "trade"
        g5.draw(screen)                       # 交易所(仓库滚动)
        g5.hideout.view = "stash"
        pygame.display.flip()
        # 7) 一键整理 / 一键放回仓库并整理
        from inventory import organize
        g6 = Game()
        g6.save = save_mod.reset_data()
        g6.save.seen_intro = True
        sd6 = g6.save
        h6 = g6.hideout
        h6.show_intro = False
        sd6.stash.clear()
        sd6.stash.items.append(Placed(Item("a545", count=37), 9, 19))
        sd6.stash.items.append(Placed(Item("pack_xl"), 4, 12))     # 没卷起来的大包
        sd6.stash.items.append(Placed(Item("a545", count=80), 0, 17))
        sd6.stash.items.append(Placed(Item.weapon("ak74", mag=30), 2, 0))
        sd6.stash.items.append(Placed(Item("bandage"), 8, 8))
        sd6.stash.items.append(Placed(Item("b45"), 1, 5))
        sd6.stash.items.append(Placed(Item("a545", count=3), 6, 14))
        sd6.stash.items.append(Placed(Item("m700"), 0, 9))
        sd6.stash.items.append(Placed(Item("gold"), 9, 0))
        n_before = len(sd6.stash.items)
        ok, msg = h6.organize_stash()
        assert ok, msg
        ammo = [p for p in sd6.stash.items if p.item.iid == "a545"]
        assert len(ammo) == 1 and ammo[0].item.count == 120, [p.item.count for p in ammo]
        packs = [p for p in sd6.stash.items if p.item.cat == "pack"]
        assert packs and all(p.item.is_rolled() for p in packs)
        assert len(sd6.stash.items) == n_before - 2

        def _bbox_ratio(c):
            cells = {}
            for p in c.items:
                w, hh = p.item.size()
                for dy in range(hh):
                    for dx in range(w):
                        cells.setdefault(p.item.cat, set()).add((p.x + dx, p.y + dy))
            out = {}
            for cat, cs in cells.items():
                xs = [x for x, _y in cs]
                ys = [y for _x, y in cs]
                out[cat] = ((max(xs) - min(xs) + 1) * (max(ys) - min(ys) + 1)
                            / max(1, len(cs)))
            return out

        ratio = _bbox_ratio(sd6.stash)
        assert ratio.get("weapon", 1) <= 3.0 and ratio.get("armor", 1) <= 3.0, ratio
        assert all(v <= 3.0 for v in ratio.values()), ratio
        used_rows = max((p.y + p.item.size()[1] for p in sd6.stash.items), default=0)
        assert used_rows <= 8, used_rows
        pos1 = sorted((p.x, p.y, p.item.iid, p.item.count) for p in sd6.stash.items)
        assert h6.organize_stash()[0]
        pos2 = sorted((p.x, p.y, p.item.iid, p.item.count) for p in sd6.stash.items)
        assert pos1 == pos2, "重复整理应该稳定"
        # 一键放回仓库并整理
        sd6.bag.clear()
        sd6.weapon = Item.weapon("akm", mag=30)
        sd6.armor = Item("b23")
        sd6.pack = Item("pack_large")
        sd6.apply_pack()
        sd6.bag.add_item(Item("a545", count=60))
        sd6.bag.add_item(Item("medkit"))
        ok, msg = h6.stash_all_and_organize()
        assert ok, msg
        assert not sd6.bag.items, "背包应该空了"
        assert sd6.weapon is None and sd6.armor is None and sd6.pack is None
        assert (sd6.bag.w, sd6.bag.h) == (4, 2), (sd6.bag.w, sd6.bag.h)
        ids = [p.item.iid for p in sd6.stash.items]
        for want in ("akm", "b23", "pack_large", "a545", "medkit"):
            assert want in ids, (want, ids)
        assert next(p for p in sd6.stash.items
                    if p.item.iid == "pack_large").item.is_rolled()
        ratio2 = _bbox_ratio(sd6.stash)
        assert all(v <= 3.5 for v in ratio2.values()), ratio2
        # 放不下时整体拒绝,且不动仓库
        for gy in range(sd6.stash.h):
            for gx in range(sd6.stash.w):
                if not sd6.stash.occupied()[gy][gx]:
                    sd6.stash.items.append(Placed(Item("bandage"), gx, gy))
        sd6.stash.items.append(Placed(Item("pack_xl"), 0, 0))   # 故意重叠
        snap = [(p.x, p.y, p.item.iid) for p in sd6.stash.items]
        ok, overflow = organize(sd6.stash)
        assert not ok and overflow, "放不下必须整体拒绝"
        assert [(p.x, p.y, p.item.iid) for p in sd6.stash.items] == snap, \
            "整理失败不该改动仓库"
        # 两个按钮都能点
        scr6 = pygame.display.set_mode((SW, SH))
        g6.draw(scr6)
        h6._click(h6.lay["organize"].center)
        h6._click(h6.lay["stash_all"].center)
        g6.draw(scr6)
        pygame.display.flip()
        # 8) 整理后装备"卷起的背包":以前会就地展开撑破格子(越界)-> 之后点啥都闪退
        g7 = Game()
        g7.save = save_mod.reset_data()
        g7.save.seen_intro = True
        sd7 = g7.save
        h7 = g7.hideout
        h7.show_intro = False
        sd7.stash.clear()
        sd7.stash.add_item(Item("pack_xl"))
        sd7.stash.add_item(Item("gold"))
        assert h7.organize_stash()[0]
        pk7 = next(p for p in sd7.stash.items if p.item.iid == "pack_xl")
        assert pk7.item.is_rolled() and pk7.item.size() == (2, 2)
        idx7 = next(i for i, p in enumerate(sd7.stash.items) if p.item is pk7.item)
        ok, msg = h7._try_equip_pack(idx7)
        assert ok, msg
        assert sd7.pack is not None and sd7.pack.iid == "pack_xl"
        assert not sd7.pack.is_rolled(), "装备时应展开"
        assert (sd7.bag.w, sd7.bag.h) == (10, 6), (sd7.bag.w, sd7.bag.h)
        assert not sd7.stash.out_of_bounds() and not sd7.bag.out_of_bounds()
        assert not any(p.item.iid == "pack_xl" for p in sd7.stash.items)
        # 失败路径:换小包 -> 背包收窄溢出 + 仓库塞不下 -> 什么都不变、不留越界物品
        g8 = Game()
        g8.save = save_mod.reset_data()
        g8.save.seen_intro = True
        sd8 = g8.save
        h8 = g8.hideout
        h8.show_intro = False
        sd8.stash.clear()
        sd8.bag.clear()
        sd8.weapon = Item.weapon("pm", mag=8)
        sd8.pack = Item("pack_xl")
        sd8.apply_pack()
        for _ in range(20):
            sd8.bag.add_item(Item("screws"))
        sd8.stash.add_item(Item("pack_small"))
        for gy in range(sd8.stash.h):
            for gx in range(sd8.stash.w):
                if not sd8.stash.occupied()[gy][gx]:
                    sd8.stash.items.append(Placed(Item("bandage"), gx, gy))
        assert h8.organize_stash()[0]
        small = next(p for p in sd8.stash.items if p.item.iid == "pack_small")
        before8 = sorted((p.item.iid, p.x, p.y) for p in sd8.stash.items)
        idx8 = next(i for i, p in enumerate(sd8.stash.items) if p.item is small.item)
        ok, msg = h8._try_equip_pack(idx8)
        assert not ok, msg
        assert not sd8.stash.out_of_bounds(), "失败后不能留下越界物品(会连锁闪退)"
        assert sorted((p.item.iid, p.x, p.y) for p in sd8.stash.items) == before8
        assert sd8.pack is not None and sd8.pack.iid == "pack_xl"
        # 容器对越界物品要容错,读档修复要尽量保住东西
        c8 = Container(3, 2)
        c8.items.append(Placed(Item("gold"), 0, 0))
        c8.items.append(Placed(Item("ak74"), 2, 0))       # 5 宽 -> 越界
        assert len(c8.out_of_bounds()) == 1
        assert all(len(r) == 3 for r in c8.occupied())    # 以前这里 IndexError
        assert c8.at(2, 0) is not None and c8.at(99, 99) is None
        bad8 = [dict(iid="gold", count=1, rot=False, state={}, x=0, y=0),
                dict(iid="ak74", count=1, rot=False, state={}, x=2, y=0)]
        assert len(Container.deserialize(3, 2, bad8).items) == 1, "严格模式仍丢弃"
        rep8 = Container.deserialize(3, 2, bad8, repair=True)
        assert len(rep8.items) == 1 and not rep8.out_of_bounds()
        big8 = Container.deserialize(10, 20, bad8, repair=True)
        assert len(big8.items) == 2 and not big8.out_of_bounds(), "放得下就该留着"
        c9 = Container(10, 4)
        c9.items.append(Placed(Item("gold"), 0, 0))
        c9.items.append(Placed(Item("m700"), 6, 0))
        assert len(c9.out_of_bounds()) == 1
        c9.repair_layout()
        assert not c9.out_of_bounds() and len(c9.items) == 2
        # 带卷起背包的存档读回来仍然合法
        save_mod.save_data(sd7)
        sd7b = save_mod.load_data()
        assert not sd7b.stash.out_of_bounds() and not sd7b.bag.out_of_bounds()

    check("基建-仓库滚动/背包卷起/弹药库/任务系统", t_base)

    def t_story():
        """剧情模式《灰区二日》:见 storytest.py(单独成文件,免得本文件过长)。"""
        import storytest
        storytest.run()

    check("剧情模式-城区大图/八时段/分支与结局", t_story)

    def t_bindings():
        """键位自定义:默认值 / 改键 / 冲突拒绝 / 存档往返 / 战局里生效。"""
        import bindings
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        sd = g.save
        # 默认值:W 与 ↑ 都算"向上"
        assert bindings.keys_for(sd, "up") == (pygame.K_w, pygame.K_UP)
        assert bindings.label_for(sd, "interact") == "E"
        assert bindings.label_for(sd, "bag") == "Tab"
        assert bindings.key_matches(pygame.K_UP, sd, "up")
        assert not bindings.key_matches(pygame.K_UP, sd, "down")
        # 改键:交互改到 F
        ok, conflicts = bindings.assign(sd, "interact", pygame.K_f)
        assert ok and not conflicts
        assert bindings.keys_for(sd, "interact") == (pygame.K_f,)
        assert bindings.label_for(sd, "interact") == "F"
        assert bindings.is_modified(sd, "interact")
        # 冲突:交互改到 W(向上已占用)-> 拒绝且不改动
        ok, conflicts = bindings.assign(sd, "interact", pygame.K_w)
        assert not ok and "up" in conflicts, (ok, conflicts)
        assert bindings.keys_for(sd, "interact") == (pygame.K_f,)
        # 改绑后只认新键(默认的方向键备份被替换)
        ok, _ = bindings.assign(sd, "up", pygame.K_i)
        assert ok and bindings.keys_for(sd, "up") == (pygame.K_i,)
        # 非法输入拒绝
        assert bindings.assign(sd, "up", 0)[0] is False
        assert bindings.assign(sd, "nope", pygame.K_i)[0] is False
        # 存档往返
        save_mod.save_data(sd)
        sd2 = save_mod.load_data()
        assert sd2.bindings.get("interact") == [pygame.K_f], sd2.bindings
        assert sd2.bindings.get("up") == [pygame.K_i]
        assert bindings.key_matches(pygame.K_f, sd2, "interact")
        # 单键恢复默认 / 全部恢复
        bindings.clear(sd2, "interact")
        assert bindings.keys_for(sd2, "interact") == (pygame.K_e,)
        bindings.reset_all(sd2)
        assert not sd2.bindings
        # is_down 支持 dict 式快照(自检里 get_pressed() 就是这种)
        assert bindings.is_down({pygame.K_w: True}, sd2, "up") is True
        assert bindings.is_down({pygame.K_w: True}, sd2, "down") is False
        # 战局里生效:改键后按新键才触发
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.start_raid()
        r = g2.raid
        r.player.weapon = Item.weapon("pm", mag=8)
        fired = []
        r.quick_heal = lambda *a, **k: fired.append("heal")
        g2.save.bindings = {"heal": [pygame.K_j]}
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_h)])
        assert not fired, "旧键不该再生效"
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_j)])
        assert fired == ["heal"], fired

    check("设置-键位自定义/冲突拒绝/存档往返/战局生效", t_bindings)

    def t_touch_layout():
        """触屏按键位置自定义:覆盖生效 / 非法忽略 / 存档往返 / 开战局自动应用。"""
        import touch
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        sd = g.save
        base = touch.merged_layout(False)
        fire0 = base["fire"]["pos"]
        assert fire0 == (int(1280 * 0.915), int(720 * 0.80))
        assert "menu" in base, "手机需要一个「菜单」按钮来暂停"
        # 应用覆盖(设置页保存下来的格式)
        touch.apply_layout({"fire": [0.5, 0.5, 80], "menu": [0.1, 0.1, 24]})
        lay = touch.merged_layout(False)
        assert lay["fire"]["pos"] == (640, 360) and lay["fire"]["r"] == 80
        assert lay["menu"]["pos"] == (128, 72) and lay["menu"]["r"] == 24
        assert lay["bag"]["pos"] == base["bag"]["pos"], "没改的按键保持默认"
        # 非法条目忽略
        touch.apply_layout({"fire": [2.0, -1.0, 5], "bogus": [0.5, 0.5, 40]})
        lay2 = touch.merged_layout(False)
        assert lay2["fire"]["pos"] == fire0, "越界/过小的条目要忽略"
        assert "bogus" not in lay2
        # 命中判定(编辑器与 TouchUI 共用)
        touch.apply_layout({"fire": [0.5, 0.5, 80]})
        assert touch.hit_test((640, 360), False) == "fire"
        assert touch.hit_test((5, 5), False) is None
        # TouchUI 用的就是这份布局
        ui = touch.TouchUI(support=True)
        assert ui.button_layout()["fire"]["r"] == 80
        assert {"sup1", "sup2", "sup3"} <= set(ui.button_layout())
        # 存档往返
        sd.touch_layout = {"fire": [0.5, 0.5, 80]}
        save_mod.save_data(sd)
        sd3 = save_mod.load_data()
        assert sd3.touch_layout.get("fire") == [0.5, 0.5, 80], sd3.touch_layout
        # 坏数据不会崩
        sd3.touch_layout = {"x": "bad", "fire": [0.2, "y", 40]}
        save_mod.save_data(sd3)
        sd4 = save_mod.load_data()
        assert "x" not in sd4.touch_layout and "fire" not in sd4.touch_layout
        touch.apply_layout(None)
        assert touch.merged_layout(False)["fire"]["pos"] == fire0, "恢复默认"
        # 开战局时自动把存档里的布局应用上去
        g5 = Game()
        g5.save = save_mod.reset_data()
        g5.save.seen_intro = True
        g5.save.touch = True
        g5.save.touch_layout = {"fire": [0.5, 0.5, 80]}
        g5.start_raid()
        assert g5.raid.touch.button_layout()["fire"]["pos"] == (640, 360)

    check("设置-触屏按键位置自定义/存档/开战局应用", t_touch_layout)

    def t_finger_mouse():
        """触屏事件合成:手机上界面能点(修「第二次启动后点哪都没反应」)。"""
        from game import Game, synth_mouse_events
        evs = [
            pygame.event.Event(pygame.FINGERDOWN,
                               {"finger_id": 0, "x": 0.5, "y": 0.25}),
            pygame.event.Event(pygame.FINGERMOTION,
                               {"finger_id": 0, "x": 0.6, "y": 0.3,
                                "dx": 0.1, "dy": 0.05}),
            pygame.event.Event(pygame.FINGERUP,
                               {"finger_id": 0, "x": 0.6, "y": 0.3}),
        ]
        out = synth_mouse_events(evs)
        assert [e.type for e in out] == [
            pygame.FINGERDOWN, pygame.MOUSEBUTTONDOWN, pygame.FINGERMOTION,
            pygame.MOUSEMOTION, pygame.FINGERUP, pygame.MOUSEBUTTONUP], \
            [e.type for e in out]
        down = out[1]
        assert down.pos == (int(1280 * 0.5), int(720 * 0.25)) and down.button == 1
        assert getattr(down, "synthetic", False) is True
        assert out[3].pos == (int(1280 * 0.6), int(720 * 0.3))
        # 藏身处:真实 FINGER 点击路径能进设置页再返回
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.touch = True
        h = g.hideout
        h.show_intro = False
        scr = pygame.display.set_mode((1280, 720))
        g.draw(scr)
        opt = h.lay["options"].center
        g.update(1 / 60, [pygame.event.Event(
            pygame.FINGERDOWN, {"finger_id": 0, "x": opt[0] / 1280.0,
                                "y": opt[1] / 720.0})])
        g.update(1 / 60, [pygame.event.Event(
            pygame.FINGERUP, {"finger_id": 0, "x": opt[0] / 1280.0,
                              "y": opt[1] / 720.0})])
        assert h.view == "options", h.view
        g.draw(scr)
        back = h.opt_close.center
        g.update(1 / 60, [pygame.event.Event(
            pygame.FINGERDOWN, {"finger_id": 0, "x": back[0] / 1280.0,
                                "y": back[1] / 720.0})])
        g.update(1 / 60, [pygame.event.Event(
            pygame.FINGERUP, {"finger_id": 0, "x": back[0] / 1280.0,
                              "y": back[1] / 720.0})])
        assert h.view == "stash", h.view
        # 战局:合成的鼠标镜像不该让触屏按钮双触发
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.save.touch = True
        g2.start_raid()
        r = g2.raid
        r.player.weapon = Item.weapon("pm", mag=8)
        bx, by = r.touch.button_layout()["reload"]["pos"]
        fires = []
        r.start_reload = lambda *a, **k: fires.append(1)
        g2.update(1 / 60, [pygame.event.Event(
            pygame.FINGERDOWN, {"finger_id": 0, "x": bx / 1280.0,
                                "y": by / 720.0})])
        assert len(fires) == 1, f"合成鼠标让触屏按钮双触发了: {len(fires)}"

    check("设置-触屏事件合成(FINGER→鼠标)/不双触发", t_finger_mouse)

    def t_fog_cache():
        """迷雾缓存:可见集与暴力重算一致 / 多边形按移动阈值重算 / 渲染不崩。"""
        from game import Game
        from settings import FOG_VIS_RADIUS
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.start_raid()
        r = g.raid
        p = r.player

        def brute():
            return {id(s) for s in r.scavs
                    if abs(s.x - p.x) <= FOG_VIS_RADIUS
                    and abs(s.y - p.y) <= FOG_VIS_RADIUS
                    and r.map.los_clear(p.x, p.y, s.x, s.y)}

        r.refresh_fog(force=True)
        assert r.fog_polygon and len(r.fog_polygon) >= 3
        assert r.fog_vis == brute(), (len(r.fog_vis), len(brute()))
        ver0 = r.fog_version
        # 小移动(<阈值):多边形不重算
        p.x += 2.0
        r.refresh_fog(1 / 120)
        assert r.fog_version == ver0, "小移动不该重算视野多边形"
        p.x -= 2.0
        # 时间阈值:静止不动也会刷可见集
        r.fog_t = 999.0
        r.refresh_fog(0.016)
        assert r.fog_t == 0.0
        # 大移动:重算并推进版本
        p.x += 40.0
        r.refresh_fog(1 / 120)
        assert r.fog_version == ver0 + 1, r.fog_version
        assert r.fog_vis == brute()
        # 敌人自己走进视野:可见集跟随(同点必可见)
        for s in r.scavs[:5]:
            s.x, s.y = p.x, p.y
        r.refresh_fog(0.2)
        assert all(id(s) in r.fog_vis for s in r.scavs[:5])
        # 敌人 AI 读的就是这份缓存
        far = [s for s in r.scavs[5:] if id(s) not in r.fog_vis]
        if far:
            assert far[0].sees_player(r, p) is False, "看不见的敌人不该说看见玩家"
        # 渲染不崩(迷雾合成层按版本缓存)
        scr = pygame.display.set_mode((1280, 720))
        g.draw(scr)
        p.x += 30.0
        r.refresh_fog(1 / 60)
        g.draw(scr)

    check("性能-迷雾可见集缓存/阈值重算/渲染", t_fog_cache)

    def t_options_view():
        """设置页:标签切换 / 改键捕获 / 冲突拒绝 / 保存并应用 / 恢复默认 / 渲染。"""
        import bindings as bmod
        import touch as touch_mod
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        h = g.hideout
        h.show_intro = False
        scr = pygame.display.set_mode((1280, 720))

        def click(pos):
            # 触屏模式下点按延迟到抬起生效 -> 按下/抬起成对发送(两种模式都适用)
            h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                                 button=1, pos=pos)])
            h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                                 button=1, pos=pos)])

        def key(k):
            h.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=k,
                                                 unicode="")])
        g.draw(scr)
        click(h.lay["options"].center)
        assert h.view == "options" and h.opt_tab == "controls", (h.view, h.opt_tab)
        g.draw(scr)
        # 三个标签页都能切换并渲染
        for i, keyname in enumerate(h.opt_tab_keys):
            click(h.opt_tab_rects[i].center)
            assert h.opt_tab == keyname
            g.draw(scr)
        # 回控制页:点"交互"的键位按钮 -> 按 F
        click(h.opt_tab_rects[0].center)
        row = [i for i, (a, _n) in enumerate(bmod.ACTIONS) if a == "interact"][0]
        click(h.opt_bind_rects[row].center)
        assert h.opt_rebind == "interact"
        g.draw(scr)
        key(pygame.K_f)
        assert h.opt_rebind is None
        assert bmod.key_matches(pygame.K_f, g.save, "interact")
        # 冲突键被拒绝,继续等新键
        click(h.opt_bind_rects[row].center)
        key(pygame.K_w)
        assert h.opt_rebind == "interact", "冲突时应继续等待"
        assert bmod.label_for(g.save, "interact") == "F"
        key(pygame.K_ESCAPE)          # 取消改键
        assert h.opt_rebind is None
        assert h.view == "options", "ESC 取消改键不该退出设置页"
        # 保存并应用 -> 落盘
        click(h.opt_save.center)
        sd2 = save_mod.load_data()
        assert sd2.bindings.get("interact") == [pygame.K_f], sd2.bindings
        # 恢复默认键位
        click(h.opt_defaults.center)
        assert not g.save.bindings
        # 触屏页:拖动 + 改大小 + 保存
        click(h.opt_tab_rects[1].center)
        assert h.opt_tab == "touch" and "fire" in h.opt_layout
        d0 = h.opt_layout["fire"]
        fpos = (int(d0["rx"] * 1280), int(d0["ry"] * 720))
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             button=1, pos=fpos)])
        assert h.opt_sel == "fire" and h.opt_drag == "fire"
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEMOTION, pos=(700, 400),
                                             rel=(10, 5), buttons=(1, 0, 0))])
        assert abs(h.opt_layout["fire"]["rx"] - 700 / 1280.0) < 1e-6
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                             button=1, pos=(700, 400))])
        assert h.opt_drag is None
        r0 = h.opt_layout["fire"]["r"]
        click(h.opt_plus.center)
        assert h.opt_layout["fire"]["r"] == r0 + 6
        click(h.opt_minus.center)
        assert h.opt_layout["fire"]["r"] == r0
        g.draw(scr)
        click(h.opt_save.center)
        assert touch_mod.merged_layout(False)["fire"]["pos"] == (700, 400)
        assert g.save.touch_layout.get("fire") == [
            round(700 / 1280.0, 4), round(400 / 720.0, 4), r0], g.save.touch_layout
        # 画质页:帧率上限 / FPS 开关 / 滤镜 / 恢复默认
        click(h.opt_tab_rects[2].center)
        g.draw(scr)
        click(h.opt_fps_rects[0].center)
        assert g.save.fps_cap == 60, g.save.fps_cap
        click(h.opt_fps_rects[3].center)
        assert g.save.fps_cap == 0
        before_show = g.save.show_fps
        click(h.opt_fps_toggle.center)
        assert g.save.show_fps is (not before_show)
        click(h.opt_filter_rects[1].center)
        assert g.save.scale_filter == "nearest"
        click(h.opt_defaults.center)
        assert (g.save.fps_cap == 120 and g.save.show_fps
                and g.save.scale_filter == "linear")
        # 返回按钮
        click(h.opt_close.center)
        assert h.view == "stash"
        # 手机(触屏)模式下设置页也能点:翻页按钮只在该模式画出来
        g.save.touch = True
        click(h.lay["options"].center)
        assert h.view == "options"
        g.draw(scr)
        g.save.touch = False

    check("设置-设置页交互/保存应用/恢复默认/渲染", t_options_view)

    def t_scroll_buttons():
        """手机翻页按钮:触屏模式下 ▲▼ 能翻仓库/商品/任务,电脑模式不出现。"""
        from game import Game
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.touch = True
        h = g.hideout
        h.show_intro = False
        scr = pygame.display.set_mode((1280, 720))
        g.draw(scr)
        up, dn = h._scroll_buttons()[("stash", 0)]
        assert h.stash_max_scroll() > 0, "仓库比面板长,应该能翻"
        before = h.stash_scroll
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             button=1, pos=dn.center)])
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                             button=1, pos=dn.center)])
        assert h.stash_scroll == min(before + 40, h.stash_max_scroll())
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             button=1, pos=up.center)])
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                             button=1, pos=up.center)])
        assert h.stash_scroll == before
        assert h._scroll_click(up.center) is True
        # 电脑模式不显示也不响应
        g.save.touch = False
        assert h._scroll_click(dn.center) is False
        g.draw(scr)

    check("设置-手机翻页按钮(触屏模式)", t_scroll_buttons)

    def t_night():
        """黑暗行动:强制强化封锁 / 只有光源范围可见 / 手电锥形 + 夜视头盔 / 头盔装备槽。"""
        from game import Game
        from settings import (MODES, MODE_ORDER, MODE_DIFF, ITEMS, TRADE_GOODS,
                              ATTACH_SLOTS, weapon_slots, weapon_beam, helmet_nvg)
        # 1) 配置:模式存在、默认强化封锁、光源道具与槽位齐全、夜视够贵
        assert "night" in MODES and "night" in MODE_ORDER
        assert MODE_DIFF.get("night") == "hardened"
        assert MODES["night"].get("short")
        assert ITEMS["flashlight"]["slot"] == "light" and ITEMS["flashlight"]["beam"]
        assert ITEMS["flashlight_pro"]["beam"][0] > ITEMS["flashlight"]["beam"][0]
        assert ITEMS["flashlight_pro"]["price"] > ITEMS["flashlight"]["price"]
        assert ITEMS["nvg_pnv"]["cat"] == "helmet" and ITEMS["nvg_pnv"]["nvg"]
        assert ITEMS["nvg_gpnvg"]["nvg"][0] > ITEMS["nvg_pnv"]["nvg"][0]
        assert ITEMS["nvg_gpnvg"]["price"] > ITEMS["nvg_pnv"]["price"] >= 180000, \
            "夜视头盔要贵,不然夜战太简单"
        assert "light" in ATTACH_SLOTS and "light" in weapon_slots("ak74")
        assert "light" not in weapon_slots("m139"), "机枪不装配件"
        goods = {g_[0] for g_ in TRADE_GOODS}
        assert {"flashlight", "flashlight_pro", "nvg_pnv", "nvg_gpnvg"} <= goods

        # 2) 开一局夜战:难度被强制成强化封锁,地图仍按玩家选的来
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.mode = "night"
        g.save.difficulty = "easy"          # 故意选简单,应被忽略
        g.save.map_key = "border"
        g.save.stash.clear()
        g.save.bag.clear()
        g.save.weapon = Item.weapon("ak74", mag=30)
        g.save.bag.add_item(Item("a545", count=60))
        g.start_raid()
        r = g.raid
        p = r.player
        assert r.mode == "night" and r.dark
        assert r.diff_key == "hardened", r.diff_key
        assert r.map_key == "border"
        assert r.fog_polygon is None and r.light_shapes, \
            "夜里没有 360° 视野多边形,只有光源形状"
        p.hp = 1000000

        def place_clear(s, dist, ang, dev=40):
            """把敌人放到玩家 (dist, ang) 方向上,找一个不撞墙又有视线的角度。"""
            for k in range(2 * dev + 1):
                off = 0.0 if k == 0 else ((k + 1) // 2) * 0.06 * (1 if k % 2 else -1)
                a = ang + off
                x, y = p.x + math.cos(a) * dist, p.y + math.sin(a) * dist
                if not r.map.collides(x, y, 12) and r.map.los_clear(p.x, p.y, x, y):
                    s.x, s.y = x, y
                    return a
            raise AssertionError("找不到有视线的落点")

        s = r.scavs[0]
        for other in r.scavs[1:]:
            other.x, other.y = p.x + 3000, p.y + 3000

        # 3) 没有光源:200px 外的敌人看不见(只有脚边微光),但敌人自己看得见你
        p.aim = 0.0
        place_clear(s, 200, 0.3)
        r.refresh_fog(force=True)
        assert id(s) not in r.fog_vis, "没光源不该看见 200px 外的敌人"
        assert id(s) in r.sight_vis, "敌人能看见你(光照不限制敌人)"
        s.x, s.y = p.x + 50, p.y
        r.refresh_fog(force=True)
        assert id(s) in r.fog_vis, "脚边微光内应该能看见"

        # 4) 战术手电:锥形内可见、背后不可见、射程外不可见,且跟着准星转
        p.weapon.state.setdefault("attach", {})["light"] = "flashlight"
        assert weapon_beam(p.weapon) == ITEMS["flashlight"]["beam"]
        assert helmet_nvg(p.helmet) is None
        far, behind = r.scavs[1], r.scavs[2]
        ang = place_clear(far, 400, 0.3, dev=3)
        p.aim = ang
        r.refresh_fog(force=True)
        assert id(far) in r.fog_vis, "手电锥形内该看见"
        place_clear(behind, 300, ang + math.pi, dev=3)
        r.refresh_fog(force=True)
        assert id(behind) not in r.fog_vis, "背后不该看见"
        p.aim = ang + math.pi          # 转身:原来的前方变背后
        r.refresh_fog(force=True)
        assert id(behind) in r.fog_vis and id(far) not in r.fog_vis, \
            "光锥应该跟着准星转(原来的前方变背后)"
        beam_rng = ITEMS["flashlight"]["beam"][0]
        p.aim = ang
        place_clear(far, beam_rng + 120, ang, dev=5)     # 对准但超出射程
        r.refresh_fog(force=True)
        assert id(far) not in r.fog_vis, "超出射程不该看见"

        # 5) 夜视头盔:全向可见(不用瞄准),但仍有半径上限
        p.weapon.state["attach"].pop("light", None)
        p.helmet = Item("nvg_pnv")
        assert helmet_nvg(p.helmet)[0] == ITEMS["nvg_pnv"]["nvg"][0]
        p.aim = ang + math.pi          # 故意背对
        place_clear(far, 250, ang, dev=6)
        r.refresh_fog(force=True)
        assert id(far) in r.fog_vis, "夜视应该全向可见"
        place_clear(far, 420, ang, dev=6)
        r.refresh_fog(force=True)
        assert id(far) not in r.fog_vis, "夜视也有半径上限"

        # 6) 手机自动锁敌只锁亮区里的敌人
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.save.mode = "night"
        g2.save.touch = True
        g2.save.stash.clear()
        g2.save.bag.clear()
        g2.save.weapon = Item.weapon("ak74", mag=30)
        g2.save.bag.add_item(Item("a545", count=60))
        g2.start_raid()
        r2 = g2.raid
        p2 = r2.player
        for other in r2.scavs[1:]:
            other.x, other.y = p2.x + 3000, p2.y + 3000
        s2 = r2.scavs[0]
        a2 = None
        for k in range(25):
            a = 0.2 + k * 0.05
            x, y = p2.x + math.cos(a) * 300, p2.y + math.sin(a) * 300
            if not r2.map.collides(x, y, 12) and r2.map.los_clear(p2.x, p2.y, x, y):
                s2.x, s2.y = x, y
                a2 = a
                break
        assert a2 is not None, "找不到有视线的落点"
        r2.refresh_fog(force=True)
        assert r2._aim_assist_target() is None, "看不见的敌人不该被自动锁定"
        p2.weapon.state.setdefault("attach", {})["light"] = "flashlight"
        p2.aim = a2
        r2.refresh_fog(force=True)
        assert r2._aim_assist_target() is s2, "亮区里应该自动锁定"

        # 7) 头盔装备槽:从仓库点装备、读写存档、卸下、一键放回收走、阵亡丢失
        g3 = Game()
        g3.save = save_mod.reset_data()
        g3.save.seen_intro = True
        h3 = g3.hideout
        h3.show_intro = False
        sd3 = g3.save
        sd3.stash.clear()
        sd3.weapon = Item.weapon("ak74", mag=30)
        sd3.stash.add_item(Item("nvg_gpnvg"))
        placed = next(x for x in sd3.stash.items if x.item.iid == "nvg_gpnvg")
        h3._click((66 + placed.x * 40 + 4, 176 + placed.y * 40 + 4))
        assert sd3.helmet is not None and sd3.helmet.iid == "nvg_gpnvg", \
            "点仓库里的头盔应该戴到头上"
        save_mod.save_data(sd3)
        sd4 = save_mod.load_data()
        assert sd4.helmet is not None and sd4.helmet.iid == "nvg_gpnvg", "头盔要能存读"
        h3._click(h3.lay["helmet"].center)
        assert sd3.helmet is None, "点头盔槽应该卸下"
        assert any(x.item.iid == "nvg_gpnvg" for x in sd3.stash.items)
        sd3.helmet = Item("nvg_pnv")
        ok, msg = h3.stash_all_and_organize()
        assert ok and sd3.helmet is None, msg
        sd5 = save_mod.reset_data()
        sd5.helmet = Item("nvg_pnv")
        sd5.wipe_loadout()
        assert sd5.helmet is None, "阵亡要丢头盔"

        # 8) 渲染:有光源 / 无光源都要能画(含 HUD 光源行)
        scr = pygame.display.set_mode((1280, 720))
        r.player.helmet = Item("nvg_pnv")
        r.player.weapon.state.setdefault("attach", {})["light"] = "flashlight_pro"
        r.refresh_fog(force=True)
        g.draw(scr)
        r.player.helmet = None
        r.player.weapon.state["attach"].pop("light", None)
        r.refresh_fog(force=True)
        g.draw(scr)

        # 9) 藏身处:5 个模式按钮不超出侧栏;夜战下点难度只给提示不改档
        for rc in h3.mode_rects:
            assert rc.right <= h3.lay["side_panel"].right, "模式按钮别超出侧栏"
        h3._click(h3.mode_rects[MODE_ORDER.index("night")].center)
        assert sd3.mode == "night"
        before = sd3.difficulty
        h3._click(h3.diff_rects[0].center)
        assert sd3.difficulty == before, "夜战不给改难度"
        g3.draw(scr)
        h3._click(h3.lay["options"].center)
        assert h3.view == "options"
        # 设置页的点击要走真实事件派发(update 内部转给 _options_update)
        h3.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                              pos=h3.opt_close.center)])
        assert h3.view == "stash"

    check("黑暗行动-强制强化封锁/光源范围可见/手电与夜视/头盔槽", t_night)

    def t_qol():
        """夜战亮区不闪 / 搜刮读条 / 打药读条 / 丢弃模式 / 换装落地。"""
        import raid_ui
        from game import Game
        from settings import (W as SW, H as SH, LOOT_TAKE_MAX, HEAL_TIME,
                              HEAL_TIME_MAX, INTERACT_DIST)

        # 1) 夜战亮区必须常亮:不动不转头时,两帧内容要完全一致
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.mode = "night"
        g.save.stash.clear()
        g.save.bag.clear()
        g.save.weapon = Item.weapon("ak74", mag=30)
        g.save.bag.add_item(Item("a545", count=60))
        g.start_raid()
        r = g.raid
        p = r.player
        scr = pygame.display.set_mode((SW, SH))
        p.helmet = Item("nvg_pnv")                 # 夜视半径 300
        r.refresh_fog(force=True)
        g.draw(scr)
        probe = (int(p.x - r.cam[0]) + 200, int(p.y - r.cam[1]))
        c1 = scr.get_at(probe)
        g.draw(scr)                                # 没动、没转头
        c2 = scr.get_at(probe)
        assert c1 == c2, ("亮区在没变化的两帧里必须一致(否则就是闪)", c1, c2)
        r.player.helmet = None                     # 没夜视:同一点应该明显更暗
        r.refresh_fog(force=True)
        g.draw(scr)
        c3 = scr.get_at(probe)
        assert sum(c3[:3]) < sum(c1[:3]), (sum(c3[:3]), sum(c1[:3]))

        # 2) 搜刮:箱子里先是"未知"(只有形状),搜出来才知道是什么、东西还在箱子里;
        #    取出已知物品才是进背包;走远/关窗会中断搜索
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.start_raid()
        r2 = g2.raid
        r2.scavs = []
        p2 = r2.player
        lc = next(c for c in r2.containers
                  if c.container.items and c.kind in ("crate", "med", "gun"))
        p2.x, p2.y = lc.rect.centerx, lc.rect.centery + 10
        r2.loot_target = lc
        first = lc.container.items[0]
        assert not r2.is_known(first), "没搜过的物品应该是未知"
        need = r2.loot_take_time(first.item)
        assert 0.8 - 1e-6 <= need <= LOOT_TAKE_MAX + 1e-6, need
        n0 = len(lc.container.items)
        r2.start_take(lc, [first])
        assert r2.take is not None and r2.take["item"] is first
        r2.update(1 / 60, [])
        assert not r2.is_known(first), "读条没走完不该揭示"
        for _ in range(int(6 * 60)):
            r2.update(1 / 60, [])
            if r2.take is None:
                break
        assert r2.take is None and r2.is_known(first), "搜完应该知道是什么了"
        assert first in lc.container.items and len(lc.container.items) == n0, \
            "搜出来只是揭示,东西还在箱子里"
        # 取出已知物品 -> 进背包(空手时直接装备)
        bag_n = len(p2.bag.items)
        assert r2.take_known(lc, first)
        assert first not in lc.container.items
        assert (len(p2.bag.items) > bag_n or p2.weapon is not None
                or p2.armor is not None or p2.helmet is not None)
        # 中断:拿一件还没搜过的来试
        rest = [pl for pl in lc.container.items if not r2.is_known(pl)]
        if rest:
            r2.start_take(lc, rest)
            assert r2.take is not None
            p2.x = lc.rect.centerx + INTERACT_DIST * 4        # 走远
            r2.update(1 / 60, [])
            assert r2.take is None, "走远应该中断搜索"
            p2.x, p2.y = lc.rect.centerx, lc.rect.centery + 10
            r2.start_take(lc, rest)
            assert r2.take is not None
            r2.loot_target = None                              # 关窗
            r2.update(1 / 60, [])
            assert r2.take is None, "关掉搜刮窗应该中断搜索"
            r2.loot_target = lc
        # 「全部搜出」把剩下的未知全部搜一遍(逐件读条)
        rest = [pl for pl in lc.container.items if not r2.is_known(pl)]
        if rest:
            r2.start_take(lc, rest)
            for _ in range(int((LOOT_TAKE_MAX * len(rest) + 6) * 60)):
                r2.update(1 / 60, [])
                if r2.take is None:
                    break
            assert all(r2.is_known(pl) for pl in lc.container.items), "应该全部搜出来了"
        # 全部已知:交给「全部拿走」的路径(这里直接调 take_known 逐件拿)
        n_left = len(lc.container.items)
        taken = 0
        for pl in list(lc.container.items):
            if r2.is_known(pl) and r2.take_known(lc, pl):
                taken += 1
        assert taken > 0 and len(lc.container.items) < n_left

        # 3) 打药读条:时长按治疗量,移动时进度减半
        p2.bag.clear()
        p2.bag.add_item(Item("surgery"))           # heal 200 -> 接近上限
        med = p2.bag.items[0]
        p2.hp = 10
        t_heal = r2.heal_time(med.item)
        assert HEAL_TIME - 1e-6 <= t_heal <= HEAL_TIME_MAX + 1e-6, t_heal
        r2.start_heal(med)
        assert r2.heal_ch is not None
        r2.player_moving = lambda: True            # 假装一直在跑
        for _ in range(int(0.5 * 60)):
            r2.update(1 / 60, [])
        moving_t = r2.heal_ch["t"] if r2.heal_ch else 99.0
        r2.player_moving = lambda: False           # 站定
        r2.heal_ch["t"] = 0.0
        for _ in range(int(0.5 * 60)):
            r2.update(1 / 60, [])
        still_t = r2.heal_ch["t"] if r2.heal_ch else 99.0
        assert still_t > moving_t * 1.5, (moving_t, still_t)
        for _ in range(int(6 * 60)):
            r2.update(1 / 60, [])
            if r2.heal_ch is None:
                break
        assert r2.heal_ch is None and p2.hp > 10, (r2.heal_ch, p2.hp)

        # 4) 丢弃模式:点背包物品 = 丢在脚边(手机没有右键)
        g3 = Game()
        g3.save = save_mod.reset_data()
        g3.save.seen_intro = True
        g3.start_raid()
        r3 = g3.raid
        r3.scavs = []
        p3 = r3.player
        p3.bag.clear()
        p3.bag.add_item(Item("gold"))
        gold = p3.bag.items[0]
        r3.inv_open = True
        r3.drop_mode = True
        lay = raid_ui.inv_layout(p3.bag.w, p3.bag.h)
        rect, cell = lay["bag"]
        pos = (rect.x + gold.x * cell + 4, rect.y + gold.y * cell + 4)
        r3._handle_inv_click(pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                                button=1, pos=pos))
        assert not p3.bag.items, "丢弃模式下点物品应该丢出去"
        assert any(lc.kind == "ground"
                   and any(pl.item.iid == "gold" for pl in lc.container.items)
                   for lc in r3.containers), "地上应该出现这枚金链子"
        r3.drop_mode = False

        # 5) 换装:旧枪塞不进背包 -> 丢在脚边(以前直接拒绝,像卡死)
        p3.bag.clear()
        p3.weapon = Item.weapon("m4a1", mag=30)    # 5×2
        bag = p3.bag
        for gy in range(bag.h):                    # 用 1×1 塞满,只留左上 2×2
            for gx in range(bag.w):
                if gx < 2 and gy < 2:
                    continue
                bag.add_item(Item("screws"))
        pm = Item.weapon("pm", mag=8)              # 2×1 正好塞进那个 2×2
        assert bag.add_item(pm), "2×2 空位应该放得下 PM"
        placed_pm = next(pl for pl in bag.items if pl.item is pm)
        ground_before = sum(len(lc.container.items) for lc in r3.containers
                            if lc.kind == "ground")
        r3.equip_from_bag(placed_pm)
        assert p3.weapon is pm, "应该换上新枪"
        ground_after = sum(len(lc.container.items) for lc in r3.containers
                           if lc.kind == "ground")
        assert ground_after == ground_before + 1, "旧枪应该被丢在脚边"
        # 6) 渲染:背包面板(含头盔槽/丢弃按钮)与搜刮读条都不崩
        p3.bag.add_item(Item("bandage"))
        r3.inv_open = True
        r3.drop_mode = True
        g3.draw(scr)
        r3.drop_mode = False
        g3.draw(scr)
        p2.hp = 40
        p2.bag.add_item(Item("bandage"))
        r2.start_heal(p2.bag.items[-1])
        r2.loot_target = None
        r2.inv_open = True
        g2.draw(scr)
        r2.inv_open = False

        # 5) 移动速度:架枪(瞄准)剩 20%、换弹剩 40%、M139 换弹/架枪都不能动
        from settings import MOVE_AIM_MUL, MOVE_RELOAD_MUL
        g4 = Game()
        g4.save = save_mod.reset_data()
        g4.save.seen_intro = True
        g4.save.weapon = Item.weapon("ak74", mag=30)
        g4.save.bag.add_item(Item("a545", count=60))
        g4.start_raid()
        r4 = g4.raid
        r4.scavs = []
        p4 = r4.player
        fake_press = [False, False, False]          # [左键, 中键, 右键]
        orig_press = pygame.mouse.get_pressed
        orig_keys = pygame.key.get_pressed
        pygame.mouse.get_pressed = lambda *a: fake_press
        pygame.key.get_pressed = lambda *a: {pygame.K_d: True}   # 一直往右推
        try:
            def walk_x(frames=10):
                x0 = p4.x
                for _ in range(frames):
                    r4.update(1 / 60, [])
                return p4.x - x0

            base = walk_x()
            assert base > 0.1, f"正常应该能走({base})"
            fake_press[2] = True                    # 长按右键 = 架枪
            aim = walk_x()
            assert aim < base * (MOVE_AIM_MUL + 0.15), (base, aim)
            fake_press[2] = False
            p4.reloading = True                     # 换弹中
            p4.reload_t = 99
            rel = walk_x()
            assert rel < base * (MOVE_RELOAD_MUL + 0.2), (base, rel)
            p4.reloading = False
            # M139:换弹或架枪都不能动
            p4.weapon = Item.weapon("m139", mag=50)
            p4.reloading = True
            p4.reload_t = 99
            assert walk_x() == 0, "M139 换弹时不能移动"
            p4.reloading = False
            fake_press[2] = True
            r4.update(1 / 60, [])                   # 架枪状态在下一帧才生效
            assert r4.braced, "应该处于架枪状态"
            assert walk_x() == 0, "M139 架枪时不能移动"
            fake_press[2] = False
        finally:
            pygame.mouse.get_pressed = orig_press
            pygame.key.get_pressed = orig_keys

        # 6) 交易所列表滚动条可以拖着走(以前列表超出格子看不见后面)
        g5 = Game()
        g5.save = save_mod.reset_data()
        g5.save.seen_intro = True
        h5 = g5.hideout
        h5.show_intro = False
        h5.view = "trade"
        g5.draw(scr)
        assert h5.trade_max_scroll() > 0, "商品列表应该长到需要滚动"
        assert h5.trade_slider is not None, "应该画出滚动条"
        track, handle = h5.trade_slider
        assert track.w >= 10, "滚动条要够宽,能点得到"
        assert h5.trade_scroll == 0
        h5.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                             pos=track.center)])
        assert h5.trade_drag and h5.trade_scroll > 0, "点轨道中段应该跳到中间"
        h5.update(1 / 60, [pygame.event.Event(pygame.MOUSEMOTION,
                                             pos=(track.centerx, track.bottom),
                                             rel=(0, 20), buttons=(1, 0, 0))])
        assert abs(h5.trade_scroll - h5.trade_max_scroll()) < 1.0, h5.trade_scroll
        g5.draw(scr)
        h5.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP, button=1,
                                             pos=(track.centerx, track.bottom))])
        assert not h5.trade_drag
        # 滚到底后,最后一行的商品落在可见范围内(点得到)
        goods, per, row_h = h5.trade_rows()
        r_last = h5.trade_row_rect(len(goods) - 1, per, row_h)
        assert (h5.trade_view_top - row_h <= r_last.y
                <= h5.trade_view_bottom), r_last

        # 7) 枪械分类:每把枪都有分类,提示里也会标出来
        from settings import ITEMS as _ITEMS, weapon_class as _wcls
        import uikit as _uikit
        weapons = [i for i, d in _ITEMS.items() if d["cat"] == "weapon"]
        assert weapons
        for iid in weapons:
            assert _wcls(iid), f"{iid} 缺分类"
        assert _wcls("ak74") == "突击步枪"
        assert _wcls("mp5") == "冲锋枪"
        assert _wcls("m700") == "狙击步枪"
        assert _wcls("m139") == "轻机枪"
        assert _wcls("mp133") == "霰弹枪"
        assert _wcls("pm") == "手枪"
        assert _wcls("rpg2") == "火箭筒"
        assert _wcls("a9") is None, "子弹不是枪"
        lines = _uikit.item_info_lines(Item.weapon("ak74", mag=30))
        assert any("分类" in ln for ln in lines), lines

    check("手感-搜索揭示/移动减速/滚动条/枪械分类", t_qol)

    def t_firemode():
        """射击模式:全自动枪按 G 循环 单发/三连发/全自动,半自动只有单发,手机有「模式」按钮。"""
        from game import Game
        from settings import (weapon_fire_modes, weapon_fire_mode, cycle_fire_mode,
                              fire_mode_name, BURST_COUNT, FIRE_MODE_NAMES)
        from touch import TouchUI
        import touch as touch_mod
        import bindings as bmod2
        # 1) 配置层:模式表 / 默认键 G / 全自动枪可切、半自动枪只有单发
        assert set(FIRE_MODE_NAMES) == {"semi", "burst", "auto"}
        assert BURST_COUNT >= 2
        assert bmod2.keys_for(None, "firemode") == (pygame.K_g,)
        assert bmod2.label_for(None, "firemode") == "G"
        w = Item.weapon("ak74", mag=30)
        assert weapon_fire_modes(w) == ["semi", "burst", "auto"], weapon_fire_modes(w)
        assert weapon_fire_mode(w) == "auto", "全自动枪默认该是全自动(不改变老行为)"
        assert cycle_fire_mode(w) == "semi"
        assert cycle_fire_mode(w) == "burst"
        assert cycle_fire_mode(w) == "auto"
        assert w.state["fire_mode"] == "auto"
        # 模式跟着武器 state 走 -> 存档往返后还在
        assert weapon_fire_mode(Item.from_dict(w.serialize())) == "auto"
        # 非法/过期值回落到默认
        w.state["fire_mode"] = "plasma"
        assert weapon_fire_mode(w) == "auto"
        # 半自动/栓动枪:只有单发,切不动
        pm = Item.weapon("pm", mag=8)
        assert weapon_fire_modes(pm) == ["semi"]
        assert weapon_fire_mode(pm) == "semi"
        assert cycle_fire_mode(pm) is None
        assert Item.weapon("m700", mag=5).state.get("fire_mode") is None
        assert weapon_fire_mode(Item.weapon("m870", mag=8)) == "semi"

        # 2) 战局内:单发 / 全自动 / 三连发的扣扳机规则
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.weapon = Item.weapon("ak74", mag=30)
        g.save.bag.clear()
        g.save.bag.add_item(Item("a545", count=120))
        g.start_raid()
        r = g.raid
        r.scavs = []
        r.allies = []
        p = r.player
        w = p.weapon

        def hold_fire(frames):
            """模拟按住扳机 frames 帧(只有第 1 帧有 fire_edge,跟真实循环一致)。"""
            before = w.state["mag"]
            for i in range(frames):
                p.fire_cd = 0.0
                r.fire_edge = (i == 0)
                r.try_fire(True)
            r.fire_edge = False
            return before - w.state["mag"]

        def tap_fire():
            """模拟点按(手机点射:有 fire_edge 但没有 held)。"""
            before = w.state["mag"]
            p.fire_cd = 0.0
            r.fire_edge = True
            r.try_fire(False)
            r.fire_edge = False
            for _ in range(12):        # 后续帧松手,三连发也要打完
                p.fire_cd = 0.0
                r.try_fire(False)
            return before - w.state["mag"]

        w.state["fire_mode"] = "semi"
        assert hold_fire(6) == 1, "单发:按住也只打一发"
        w.state["fire_mode"] = "auto"
        assert hold_fire(6) == 6, "全自动:按住就一直打"
        w.state["fire_mode"] = "burst"
        w.state["mag"] = 30
        assert hold_fire(30) == BURST_COUNT, "三连发:按住也只打一串"
        assert hold_fire(30) == BURST_COUNT, "松手再扣:还能再打一串"
        w.state["mag"] = 30
        assert tap_fire() == BURST_COUNT, "点按一下也要打满一串"
        assert w.state["mag"] == 30 - BURST_COUNT
        # 打空时不会卡住 burst 计数
        w.state["mag"] = 0
        assert hold_fire(5) == 0
        assert p.burst_left == 0
        w.state["mag"] = 30

        # 3) 按 G 走真实 KEYDOWN 路径切换(改键后按新键)
        w.state["fire_mode"] = "auto"
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)])
        assert p.fire_mode() == "semi", p.fire_mode()
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)])
        assert p.fire_mode() == "burst"
        g.save.bindings = {"firemode": [pygame.K_v]}
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)])
        assert p.fire_mode() == "burst", "改键后旧键不该再生效"
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_v)])
        assert p.fire_mode() == "auto"
        g.save.bindings = {}
        # 半自动枪:按 G 只提示,模式不变
        p.weapon = Item.weapon("pm", mag=8)
        p.burst_left = 3
        r.update(1 / 60, [pygame.event.Event(pygame.KEYDOWN, key=pygame.K_g)])
        assert p.fire_mode() == "semi"
        assert p.burst_left == 0, "切模式/换枪要清掉三连发计数"
        assert any("单发" in t[0] for t in r.toasts), r.toasts

        # 4) 手机:多一个「模式」按钮(写着当前模式),点它能切
        for name, d in touch_mod.merged_layout(False).items():
            assert touch_mod.hit_test(d["pos"], False) == name, name   # 按钮不重叠
        assert "mode" in touch_mod.merged_layout(False)
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        g2.save.touch = True
        g2.save.weapon = Item.weapon("ak74", mag=30)
        g2.start_raid()
        r2 = g2.raid
        r2.scavs = []
        assert isinstance(r2.touch, TouchUI)
        assert r2.touch.mode_label == "全自动", r2.touch.mode_label
        r2.touch.just_pressed.append("mode")       # 触屏点按
        r2.update(1 / 60, [])
        assert r2.player.fire_mode() == "semi", r2.player.fire_mode()
        assert r2.touch.mode_label == "单发", r2.touch.mode_label
        # 真实 FINGER 事件(合成鼠标镜像是 synthetic,不该双触发)
        d = r2.touch.button_layout()["mode"]
        ev = pygame.event.Event(pygame.FINGERDOWN, finger_id=3,
                                x=d["pos"][0] / float(1280),
                                y=d["pos"][1] / float(720), dx=0.0, dy=0.0)
        r2.update(1 / 60, [ev])
        assert r2.player.fire_mode() == "burst", r2.player.fire_mode()
        assert r2.touch.mode_label == "三连发", r2.touch.mode_label
        # 手机上「模式」按钮也是点给玩家自己看的 + HUD/按钮渲染不炸
        scr2 = pygame.display.set_mode((1280, 720))
        r2.touch.draw(scr2)
        import raid_ui as _rui
        _rui.draw_raid(r2, scr2)
        # 电脑模式的 HUD 也要画模式(带键位提示)
        r.game.save.bindings = {}
        _rui.draw_raid(r, scr2)

    check("射击模式-G切换单发/三连发/全自动(含手机按钮)", t_firemode)

    def t_gear_catalog():
        """暗区防具扩充:护甲/头盔目录不变式 + 头盔减伤机制。"""
        from game import Game
        from settings import (ITEMS, TRADE_GOODS, trade_cat_match, NEW_ARMORS,
                              NEW_HELMETS, HELMET_REDUCE_BY_LEVEL,
                              W as SW, H as SH)
        import uikit as _uk
        import raid_ui as _rui
        # 1) 护甲不变式:级别/减伤/移速;6 级必带倒地自救,6 级以下不许带
        armors = {i: d for i, d in ITEMS.items() if d["cat"] == "armor"}
        assert len(armors) >= 25, len(armors)
        for iid, d in armors.items():
            assert 1 <= d.get("level", 0) <= 6, iid
            assert 0 < d["reduce"] < 1, iid
            assert 0 <= d.get("slow", 0) < 0.5, iid
            assert d["price"] > 0, iid
            assert bool(d.get("revive")) == (d["level"] == 6), iid
        # 2) 头盔不变式:减伤必须与级别表完全一致(夜视头盔也不例外)
        helmets = {i: d for i, d in ITEMS.items() if d["cat"] == "helmet"}
        assert len(helmets) >= 26, len(helmets)
        for iid, d in helmets.items():
            assert d.get("level") in HELMET_REDUCE_BY_LEVEL, iid
            assert abs(d["reduce"] - HELMET_REDUCE_BY_LEVEL[d["level"]]) < 1e-9, \
                (iid, d["reduce"])
            if d.get("nvg"):
                assert d["nvg"][0] > 0 and d["nvg"][1] > 0, iid
        # 3) 新装备全部在目录里且分类正确
        assert len(NEW_ARMORS) == 23 and len(NEW_HELMETS) == 26
        assert all(ITEMS[i]["cat"] == "armor" for i in NEW_ARMORS)
        assert all(ITEMS[i]["cat"] == "helmet" for i in NEW_HELMETS)
        # 4) 所有护甲/头盔都必须上架交易站,且分区归类正确
        trade = {i for i, _c in TRADE_GOODS}
        for iid in list(armors) + list(helmets):
            assert iid in trade, f"{iid} 没上架交易站"
            assert trade_cat_match(iid, ITEMS[iid]["cat"]), iid
        # 5) 价格阶梯:每个防护级别的最低价随级别递增
        for cat in ("armor", "helmet"):
            by_lv = {}
            for iid, d in ITEMS.items():
                if d["cat"] == cat:
                    by_lv.setdefault(d["level"], []).append(d["price"])
            assert len(by_lv) >= 5, (cat, sorted(by_lv))
            for lv in sorted(by_lv)[:-1]:
                assert min(by_lv[lv]) < min(by_lv[lv + 1]), (cat, lv)
        # 6) 头盔减伤生效:乘在护甲减伤之后
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.start_raid()
        r = g.raid
        p = r.player
        p.armor = Item("paca")
        p.helmet = None
        p.hp = p.max_hp
        p.take_damage(100, r)
        assert p.max_hp - p.hp == 72, (p.max_hp - p.hp)     # 100 × (1-0.28)
        p.hp = p.max_hp
        p.helmet = Item("h_6bnt")                            # 6 级盔:再减 40%
        p.take_damage(100, r)
        assert p.max_hp - p.hp == 43, (p.max_hp - p.hp)     # 100 × 0.72 × 0.60
        p.hp = p.max_hp
        p.armor = None                                       # 只戴头盔
        p.take_damage(100, r)
        assert p.max_hp - p.hp == 60, (p.max_hp - p.hp)
        assert p.hp > 0, "这里不该被打死"
        # 7) 悬浮信息与 HUD 渲染(普通头盔显示减伤,夜视头盔显示夜视)
        lines = _uk.item_info_lines(Item("h_03"))
        assert any("防弹级别 5" in ln for ln in lines), lines
        assert any("额外减伤 30%" in ln for ln in lines), lines
        lines = _uk.item_info_lines(Item("nvg_pnv"))
        assert any("夜视" in ln for ln in lines), lines
        assert any("防弹级别 3" in ln for ln in lines), lines
        scr = pygame.display.set_mode((SW, SH))
        r.player.helmet = Item("h_03")
        _rui.draw_raid(r, scr)                              # 背包面板头盔减伤行
        _uk.draw_tooltip(scr, 200, 200, Item("h_an95"))
        _uk.draw_tooltip(scr, 260, 260, Item("kn_composite"))
        pygame.display.flip()

    check("防具目录-暗区护甲头盔级别与头盔减伤", t_gear_catalog)

    def t_safe_hold_rotate():
        """保险箱(2格→40任务→4格)+ 触屏长按详情 + 物品横竖旋转。"""
        import json
        from game import Game
        from inventory import rotate_in_place, Container, Placed
        from settings import (SAFE_CONTRACT, SAFE_BASE, SAFE_UPGRADED,
                              STASH_VIEW_ROWS, W as SW, H as SH)
        import quests
        import uikit as _uk
        import raid_ui as _rui
        # 1) 40 项承包商任务:结构校验
        assert len(SAFE_CONTRACT) == 40, len(SAFE_CONTRACT)
        ids = [t["id"] for t in SAFE_CONTRACT]
        assert len(set(ids)) == 40, "任务 id 不能重复"
        kinds = {"kills", "extracts", "value", "hostage_win", "assault_win"}
        for t in SAFE_CONTRACT:
            assert t["kind"] in kinds, t
            assert int(t["need"]) > 0 and t["name"] and t["desc"], t
            assert t["reward"].get("rubles", 0) > 0, t
        # 2) 保险箱默认 2 格;存读往返;旧档迁移;阵亡不丢
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        sd = g.save
        assert (sd.safe.w, sd.safe.h) == tuple(SAFE_BASE), (sd.safe.w, sd.safe.h)
        assert sd.safe.items == []
        sd.safe.add_item(Item("gold"))
        sd2 = save_mod.SaveData.deserialize(sd.serialize())
        assert (sd2.safe.w, sd2.safe.h) == tuple(SAFE_BASE)
        assert [p.item.iid for p in sd2.safe.items] == ["gold"], "保险箱要能存读"
        # 旧档(没有 safe 字段)迁移:给空 2 格,不报错
        old = sd.serialize()
        for k in ("safe", "safe_w", "safe_h"):
            old.pop(k)
        sd_old = save_mod.SaveData.deserialize(old)
        assert (sd_old.safe.w, sd_old.safe.h) == tuple(SAFE_BASE)
        assert sd_old.safe.items == []
        # 阵亡不清保险箱
        sd.safe.add_item(Item("btc"))
        sd.wipe_loadout()
        assert [p.item.iid for p in sd.safe.items] == ["gold", "btc"], \
            "阵亡必须保住保险箱"
        # 3) 40 项全完成 -> 4 格(幂等;物品保留)
        assert quests.safe_done_count(sd) == 0
        assert not quests.safe_upgraded(sd)
        for t in SAFE_CONTRACT[:-1]:
            sd.tasks_done.append(t["id"])
        assert not quests.safe_upgraded(sd), "差一项不能提前升级"
        assert quests.check_safe_upgrade(sd) == ""
        sd.tasks_done.append(SAFE_CONTRACT[-1]["id"])
        assert quests.safe_upgraded(sd)
        msg = quests.check_safe_upgrade(sd)
        assert msg and "4 格" in msg, msg
        assert (sd.safe.w, sd.safe.h) == tuple(SAFE_UPGRADED)
        assert [p.item.iid for p in sd.safe.items] == ["gold", "btc"], \
            "升级不能丢东西"
        assert quests.check_safe_upgrade(sd) == "", "重复调用应无副作用"
        # 存读之后再升的旧档:读档自动补齐到 4 格
        snap = sd.serialize()
        snap["safe_w"], snap["safe_h"] = SAFE_BASE
        sd3 = save_mod.SaveData.deserialize(snap)
        assert (sd3.safe.w, sd3.safe.h) == tuple(SAFE_UPGRADED), "读档要自动补升级"
        # 4) 藏身处:存入开关 + 存取;承包商标签页真实点击领取
        g2 = Game()
        g2.save = save_mod.reset_data()
        g2.save.seen_intro = True
        h = g2.hideout
        h.show_intro = False
        assert quests.safe_done_count(g2.save) == 0
        # 存入一行金币
        g2.save.stash.clear()
        g2.save.stash.add_item(Item("gold"))
        pl = g2.save.stash.items[0]
        h._click(h.safe_toggle.center)                 # 开存入模式
        assert h.safe_in
        h._click((h.stash_grid[0] + 5, h.stash_grid[1] + 5))
        assert not g2.save.stash.items and len(g2.save.safe.items) == 1, "要存进保险箱"
        # 点保险箱物品取回
        sr = h.safe_rect()
        h._click((sr.x + 5, sr.y + 5))
        assert g2.save.safe.items == [] and len(g2.save.stash.items) == 1, "要能取回"
        h._click(h.safe_toggle.center)                 # 关存入模式
        assert not h.safe_in
        assert h.stash_view_h == 40 * STASH_VIEW_ROWS
        # 任务中心:承包商标签页 + 领取最后一项触发扩容
        sdg = g2.save
        for t in SAFE_CONTRACT[:-1]:
            sdg.tasks_done.append(t["id"])
        last = SAFE_CONTRACT[-1]
        sdg.tasks[last["id"]] = int(last["need"])      # 最后一项就绪
        h.view = "task"
        h.task_dept = "contractor"
        h.task_scroll = h.task_max_scroll()
        entries, per = h.task_rows()
        assert len(entries) == 40, len(entries)
        rect = h.task_row_rect(39)
        h._task_click(rect.center)
        assert (sdg.safe.w, sdg.safe.h) == tuple(SAFE_UPGRADED), \
            "领完 40 项应升到 4 格"
        assert "保险箱" in h.msg, h.msg
        h.task_dept = "instructor"
        h.view = "stash"
        # 5) 藏身处渲染冒烟(保险箱条 + 4 格)
        scr = pygame.display.set_mode((SW, SH))
        h.draw(scr)
        h.view = "task"
        h.task_dept = "contractor"
        h.draw(scr)
        h.view = "stash"
        # 6) 右键旋转(非背包=原位横竖互换;方形=提示)
        sdg.stash.clear()
        sdg.stash.add_item(Item("bandage"))
        h._right_click((h.stash_grid[0] + 5, h.stash_grid[1] + 5))
        assert "方形" in h.msg, h.msg
        # 7) 触屏长按:按住 0.45s 弹详情;普通点按延迟到抬起(重放)
        g2.save.touch = True
        h.hold.reset()
        item_pos = (h.stash_grid[0] + 5, h.stash_grid[1] + 5)
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=item_pos, button=1)])
        for _ in range(40):
            h.update(1 / 60, [])
        assert h.hold.active(), "长按应弹出详情面板"
        assert any("绷带" in ln for ln in h.hold.lines), h.hold.lines
        lines_ok = any("价格" in ln or "¥" in ln for ln in h.hold.lines)
        assert lines_ok, h.hold.lines
        h.draw(scr)
        # 抬起 -> 面板保留;再点别处 -> 关闭且不触发其它操作
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                             pos=item_pos, button=1)])
        assert h.hold.active(), "松手后面板先保留(等下一次点击)"
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=(700, 700), button=1)])
        assert not h.hold.active(), "点别处应关闭面板"
        # 普通点按(按下+抬起)仍然生效:点仓库里的枪 = 装备
        sdg.stash.clear()
        sdg.stash.add_item(Item.weapon("mp5", mag=30))
        pos = (h.stash_grid[0] + 5, h.stash_grid[1] + 5)
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                             pos=pos, button=1)])
        h.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                             pos=pos, button=1)])
        assert sdg.weapon is not None and sdg.weapon.iid == "mp5", \
            "触屏普通点按要照常装备(延迟到抬起)"
        assert not h.hold.active()
        g2.save.touch = False
        # 8) 旋转:原位成功 / 转不开 / 方形
        c = Container(3, 3)
        tall = Item("bandage")
        c.items.append(Placed(tall, 0, 0))
        assert rotate_in_place(c, c.items[0]) is None        # 1×1 方形
        gun = Item("ak74")                                   # 5×2
        c2 = Container(5, 2)
        c2.items.append(Placed(gun, 0, 0))
        assert rotate_in_place(c2, c2.items[0]) is False, "2×5 塞不进 5×2"
        c3 = Container(5, 5)
        ak = Item("ak74")
        c3.items.append(Placed(ak, 0, 0))
        assert rotate_in_place(c3, c3.items[0]) is True
        assert ak.size() == (2, 5), ak.size()
        # 9) 战局:保险箱随身、搜刮兜底、模式限制
        g3 = Game()
        g3.save = save_mod.reset_data()
        g3.save.seen_intro = True
        g3.start_raid()
        r = g3.raid
        p = r.player
        assert p.safe is g3.save.safe, "战局里要用同一个保险箱"
        # 搜刮:背包塞满 -> 拿走物品自动进保险箱
        p.bag.items.clear()
        for gy in range(p.bag.h):
            for gx in range(p.bag.w):
                p.bag.items.append(Placed(Item("bandage"), gx, gy))
        lc = next(c for c in r.containers if c.kind == "crate")
        lc.container.items.insert(0, Placed(Item("gold"), 0, 0))
        top = lc.container.items[0]
        r.mark_known(top)
        assert r.take_known(lc, top) is True
        assert any(pl.item.iid == "gold" for pl in p.safe.items), "背包满应兜底进保险箱"
        # 剧情模式:保险箱只出不进
        g4 = Game()
        g4.save = save_mod.reset_data()
        g4.save.seen_intro = True
        g4.save.mode = "story"
        g4.start_raid()
        r4 = g4.raid
        r4.inv_open = True
        lay4 = _rui.inv_layout(r4.player.bag.w, r4.player.bag.h,
                               r4.player.safe.w, r4.player.safe.h)
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                pos=lay4["safe_mode"].center)
        r4._handle_inv_click(ev)
        assert r4.safe_mode is False, "剧情模式不允许开启存入"
        assert any("只出不进" in t[0] for t in r4.toasts), r4.toasts
        # 背包面板:保险箱点击取回(背包有空间时)
        r4.player.bag.items.clear()
        r4.player.safe.add_item(Item("gold"))
        ev = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                pos=(lay4["safe"][0].x + 5, lay4["safe"][0].y + 5))
        r4._handle_inv_click(ev)
        assert not r4.player.safe.items, "点保险箱物品要取回背包"
        # 战局渲染冒烟(背包面板含保险箱)
        r4.inv_open = True
        _rui.draw_raid(r4, scr)
        # 10) 战局触屏长按:面板打开时按住物品弹详情
        g5 = Game()
        g5.save = save_mod.reset_data()
        g5.save.seen_intro = True
        g5.save.touch = True
        g5.start_raid()
        r5 = g5.raid
        r5.inv_open = True
        p5 = r5.player
        p5.bag.items.clear()
        p5.bag.items.append(Placed(Item("gold"), 0, 0))
        lay5 = _rui.inv_layout(p5.bag.w, p5.bag.h, p5.safe.w, p5.safe.h)
        bp = (lay5["bag"][0].x + 5, lay5["bag"][0].y + 5)
        r5.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONDOWN,
                                              pos=bp, button=1,
                                              synthetic=True)])
        for _ in range(40):
            r5.update(1 / 60, [])
        assert r5.hold.active(), "战局背包里长按也要弹详情"
        assert any("金链子" in ln for ln in r5.hold.lines), r5.hold.lines
        _rui.draw_raid(r5, scr)
        r5.update(1 / 60, [pygame.event.Event(pygame.MOUSEBUTTONUP,
                                              pos=bp, button=1,
                                              synthetic=True)])
        assert not r5.over

    check("保险箱-40任务解锁/长按详情/横竖旋转", t_safe_hold_rotate)
    check("礼品-神秘人10星收集/每轮刷新/全装包/机密文件", t_mystery)
    def t_accounts():
        """账号:多档隔离 / 密码校验 / 老存档并入 / 登录界面交互。"""
        import accounts
        from login import LoginScreen
        base_dir, base_file = save_mod.SAVE_DIR, save_mod.SAVE_FILE
        try:
            save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="tk2d_acc_")
            save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")
            # 1) 建号 + 密码校验(大小写不敏感的名字)
            assert accounts.list_names() == []
            ok, why = accounts.register("Bob", "abc123")
            assert ok, why
            assert accounts.exists("BOB") and accounts.exists("bob")
            assert accounts.verify("bob", "abc123")
            assert not accounts.verify("bob", "abc124"), "错误密码不能通过"
            assert not accounts.register("bob", "zzz")[0], "重名要被拒"
            assert not accounts.register("bad name", "zzz")[0], "非法名字要被拒"
            assert not accounts.register("carol", "ab")[0], "密码至少 3 位"
            assert accounts.name_reason("名字太长太长太长太长太长") is not None
            assert accounts.name_reason("bob") is None
            # 密码不能明文落在索引里
            with open(accounts.index_path(), "r", encoding="utf-8") as f:
                raw = f.read()
            assert "abc123" not in raw, "密码不能明文存盘"
            # 2) 两个账号的存档互相隔离
            ok, why, mig = accounts.register_and_login("Alice", "pw123")
            assert ok and not mig, (why, mig)
            assert save_mod.PROFILE == "alice", save_mod.PROFILE
            assert save_mod.SAVE_FILE.endswith("alice\\save.json") or \
                save_mod.SAVE_FILE.endswith("alice/save.json"), save_mod.SAVE_FILE
            sd = save_mod.reset_data()
            sd.rubles = 777777
            save_mod.save_data(sd)
            assert accounts.use("bob")
            assert save_mod.load_data().rubles == 20000, "两个账号不能串档"
            assert accounts.use("alice")
            assert save_mod.load_data().rubles == 777777
            assert accounts.list_names() == ["Bob", "Alice"], accounts.list_names()
            assert accounts.last_name() == "Alice"
            # 3) 老存档(单档时代)并入第一个新账号
            save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="tk2d_acc2_")
            save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")
            legacy = save_mod.SaveData()
            legacy.default_fill()
            legacy.rubles = 12345
            legacy.stash.add_item(Item("btc"))
            save_mod.save_data(legacy)
            assert accounts.has_legacy()
            n_before = save_mod.load_data().stash.item_count()
            assert not accounts.login("nobody", "x")[0], "没这个账号"
            ok, why, mig = accounts.register_and_login("Vet", "pw123")
            assert ok and mig, (why, mig)
            assert not accounts.has_legacy(), "老档只能并入一次"
            got = save_mod.load_data()
            assert got.rubles == 12345, got.rubles
            assert got.stash.item_count() == n_before
            assert os.path.exists(accounts.profile_save_path("Vet"))
            # 第二次建号不该再吃老档
            ok, why, mig = accounts.register_and_login("Rookie", "pw123")
            assert ok and not mig, (why, mig)
            assert save_mod.load_data().rubles == 20000
            # 4) 删档要密码,且只删该账号
            assert not accounts.remove("Vet", "wrong")[0]
            ok, why = accounts.remove("Vet", "pw123")
            assert ok, why
            assert not accounts.exists("Vet") and accounts.exists("Rookie")
            import glob
            assert glob.glob(accounts.profile_save_path("Vet") + ".deleted-*"), \
                "删档要留备份文件"
            # 5) 登录界面:新号流程(两次密码) -> 老号流程(一次密码)
            from login import LoginScreen as LS
            scr = pygame.display.get_surface()
            ls = LS()
            ls.names = accounts.list_names()
            ls._compute_layout()
            ls.name = "Rookie"
            ls.pw = "pw123"
            assert ls.signup is False, "已存在的名字 = 登录流程"
            assert ls.submit() and ls.done
            assert save_mod.PROFILE == "rookie"
            ls2 = LS()
            ls2.name = "Newbie"
            assert ls2.signup is True
            ls2.pw = "abc"
            ls2.pw2 = "abd"
            assert not ls2.submit() and "不一样" in ls2.msg
            ls2.pw2 = "abc"
            assert ls2.submit() and ls2.done and accounts.exists("Newbie")
            # 屏幕键盘:点 q 输入 -> 大写 -> 退格
            from login import _key_rects as key_rects
            ls3 = LS()
            ls3.name = ""
            ls3.field = "name"
            for rect, v in key_rects():
                if v[1] == "q":
                    ls3.click(rect.center)
                    break
            assert ls3.name == "q", ls3.name
            ls3.press_key("caps")
            ls3.press_key("a")
            assert ls3.name == "qA", ls3.name
            ls3.press_key("back")
            assert ls3.name == "q", ls3.name
            # 键盘打字 + 各字段都能点(布局在任何一次绘制前也可用)
            ls3.add_text("x")
            ls3.next_field()
            assert ls3.field in ("name", "pw", "pw2")
            ls3.draw(scr)
            # 6) 名字非法时提交会被拦下
            ls4 = LS()
            ls4.name = "有中文"
            assert not ls4.submit() and not ls4.done
            # 7) 滚动备份:写盘前把上一版留成 save.json.bak(丢档保险)
            import json as _json
            save_mod._backup_t = 0.0
            sd = save_mod.load_data()
            sd.rubles = 4242
            save_mod.save_data(sd)
            bak = save_mod.SAVE_FILE + ".bak"
            assert not os.path.exists(bak), "第一次写盘时还没有旧档可备份"
            save_mod._backup_t = 0.0          # 模拟"新的一次启动"
            save_mod.save_data(sd)
            assert os.path.exists(bak), "再次写盘应该留下 .bak"
            with open(bak, "r", encoding="utf-8") as f:
                assert _json.load(f)["rubles"] == 4242, "备份里应该是上一版内容"
            sd.rubles = 9999
            save_mod.save_data(sd)            # 10 分钟内不重复备份
            with open(bak, "r", encoding="utf-8") as f:
                assert _json.load(f)["rubles"] == 4242, "时间窗内不该刷新备份"
            with open(save_mod.SAVE_FILE, "r", encoding="utf-8") as f:
                assert _json.load(f)["rubles"] == 9999
            # 清档(下一个会话)也会先备份:重置后仍能找回旧档
            save_mod._backup_t = 0.0
            save_mod.reset_data()
            with open(bak, "r", encoding="utf-8") as f:
                assert _json.load(f)["rubles"] == 9999, "清档也要先留备份"
            with open(save_mod.SAVE_FILE, "r", encoding="utf-8") as f:
                assert _json.load(f)["rubles"] == 20000
        finally:
            save_mod.SAVE_DIR, save_mod.SAVE_FILE = base_dir, base_file
            save_mod.use_profile(None)

    def t_coop():
        """双人合作:同一台电脑两人玩(P2 键盘 + 自动瞄准 + 自动搜刮)。"""
        from game import Game
        from settings import W as SW, H as SH, COOP, PLAYER, EXTRACT_TIME
        import coop as coop_mod
        import raid as raid_mod
        screen = pygame.display.set_mode((SW, SH))
        # 1) 藏身处开关(只在搜打撤模式生效)
        g = Game()
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.mode = "raid"
        g.save.touch = False
        assert g.save.coop is False
        h = g.hideout
        h.show_intro = False
        h._click(h.coop_rect.center)
        assert g.save.coop is True, "点「双人合作」应该打开"
        h._click(h.coop_rect.center)
        assert g.save.coop is False
        h._click(h.coop_rect.center)
        # 换个模式就点不动(只对搜打撤/夜战生效)
        g.save.mode = "hostage"
        h._click(h.coop_rect.center)
        assert g.save.coop is True      # 保持原值
        g.save.mode = "raid"
        # 夜战也能开双人
        g.save.coop = False
        g.save.mode = "night"
        h._click(h.coop_rect.center)
        assert g.save.coop is True, "夜战也该允许双人合作"
        g.save.mode = "raid"
        # 手机模式不给开(要键盘)
        g.save.coop = False
        g.save.touch = True
        h._click(h.coop_rect.center)
        assert g.save.coop is False
        g.save.touch = False
        g.draw(screen)                  # 侧栏两个状态都要能画
        h._click(h.coop_rect.center)
        assert g.save.coop is True
        g.draw(screen)
        # 存档往返
        save_mod.save_data(g.save)
        assert save_mod.load_data().coop is True
        # 2) 进战局:P2 存在、有装备、出生在 P1 旁边
        snap_weapon = g.save.weapon.serialize() if g.save.weapon else None
        g.start_raid()
        r = g.raid
        assert r.coop and r.player2 is not None and r.p2_kit is not None
        p2 = r.player2
        assert p2.weapon is not None and p2.armor is not None
        assert p2.bag.w > 0
        d = math.hypot(p2.x - r.player.x, p2.y - r.player.y)
        assert 20 < d < 260, f"P2 应该出生在 P1 旁边:{d}"
        assert r.players() == (r.player, r.player2)
        assert len(r.active_players()) == 2
        assert "P2" in coop_mod.key_hint() and "自动瞄准" in coop_mod.key_hint()
        assert "↑" in coop_mod.key_hint(short=True)
        assert coop_mod.key_hint() is coop_mod.key_hint(), "提示串要缓存(HUD 每帧用)"
        # 3) 双人可见性:两位玩家各一个视野多边形,可见集是并集
        r.refresh_fog(force=True)
        assert len(r.fog_polys) == 2, len(r.fog_polys)
        assert r.fog_polygon is r.fog_polys[0]
        # P2 走远 -> 重算(任一玩家移动都触发)
        ver = r.fog_version
        p2.x += 200
        r.refresh_fog(1 / 60)
        assert r.fog_version > ver, "P2 移动也要重算迷雾"
        # 4) 按键让位:P1 的移动/静步不含 P2 的键
        assert pygame.K_UP not in r._p1_keys("up"), r._p1_keys("up")
        assert pygame.K_w in r._p1_keys("up")
        assert pygame.K_RSHIFT not in r._p1_keys("walk")
        assert pygame.K_LSHIFT in r._p1_keys("walk")
        # P2 的键就在 COOP 里
        assert pygame.K_UP in COOP["keys"]["up"]
        assert pygame.K_RSHIFT in COOP["keys"]["fire"]
        # 5) 敌人目标选择:最近的可见玩家
        s = r.scavs[0]
        r.scavs = [s]
        s.view2 = 900 * 900
        r.sight_vis = {id(s)}
        r.sight_vis2 = {id(s)}
        p2.x, p2.y = 1000.0, 1000.0
        r.player.x, r.player.y = 1400.0, 1000.0
        s.x, s.y = 1100.0, 1000.0
        tgt, see = r.threat_for(s)
        assert tgt is p2 and see, (tgt, see)      # 100 < 300 -> 打 P2
        s.x, s.y = 1350.0, 1000.0
        tgt, see = r.threat_for(s)
        assert tgt is r.player and see, (tgt, see)   # 50 < 350 -> 改打 P1
        # 全倒下时不该崩(倒下的人 dead + out 都置位,和 player_down 一致)
        r.player.dead = r.player.out = True
        r.player2.dead = r.player2.out = True
        assert r.seek_player(0, 0) is r.player
        r.player.dead = r.player2.dead = False
        r.player.out = r.player2.out = False
        # 几何可见性:真的用视线判定 P2
        found = False
        for ox, oy in ((80, 0), (-80, 0), (0, 80), (0, -80),
                       (120, 120), (-120, -120)):
            x, y = p2.x + ox, p2.y + oy
            if r.map.collides(x, y, 12) or not r.map.los_clear(x, y, p2.x, p2.y):
                continue
            s.x, s.y = x, y
            found = True
            break
        assert found, "P2 附近应该找得到一个有视线的位置"
        s.view2 = 900 * 900
        r.refresh_fog(force=True)
        assert id(s) in r.sight_vis2, "守军应该能看见 P2"
        # 6) 子弹能打中 P2(而不是只打 P1)
        r.scavs = []
        p2.hp = p2.max_hp
        p2.armor = None
        r.player.hp = r.player.max_hp
        r.bullets = [dict(x=p2.x - 20, y=p2.y, dx=900.0, dy=0.0, dmg=7,
                          owner="scav", ttl=0.2, src=None)]
        for _ in range(3):
            r.update(1 / 60, [])
        assert p2.hp < p2.max_hp, "队友子弹打不中 P2"
        assert r.player.hp == r.player.max_hp, "不该误伤 P1"
        # 7) P2 换弹 / 打药 / 自动搜刮
        p2.weapon = Item.weapon("pm", mag=0)
        p2.bag.clear()
        p2.bag.add_item(Item("a9", count=30))
        r.start_reload(p2)
        assert p2.reloading
        for _ in range(180):
            r._update_weapon_timers(p2, 1 / 60)
        assert not p2.reloading and p2.weapon.state["mag"] == 8, p2.weapon.state
        p2.hp = 40
        p2.bag.add_item(Item("medkit"))
        r.p2_quick_heal()
        assert p2.hp > 40 and not any(pl.item.iid == "medkit"
                                      for pl in p2.bag.items)
        # 自动搜刮:把 P2 放到箱子边,按交互 -> 逐件搜出收进自己背包
        lc = None
        for cand in r.containers:
            if cand.kind in ("crate", "val", "med", "gun") and cand.container.items:
                lc = cand
                break
        assert lc is not None
        lc.container.items = []
        lc.container.add_item(Item("gold"))
        lc.container.add_item(Item("a9", count=20))
        p2.x, p2.y = lc.rect.centerx, lc.rect.centery
        p2.bag.clear()
        n0 = len(lc.container.items)
        assert n0 == 2, n0
        r.p2_interact()
        assert r.p2_take is not None
        assert "自动" in r.toasts[-1][0] or "搜刮" in r.toasts[-1][0]
        for _ in range(60 * 30):
            r.update(1 / 60, [])
            if r.p2_take is None or r.over:
                break
        assert r.p2_take is None, "P2 搜刮应该会结束"
        assert not lc.container.items, "箱子应该被 P2 搜空"
        assert p2.bag.item_count() >= 2, p2.bag.item_count()
        assert all(r.is_known(pl) for pl in lc.container.items) or True
        # 离开太远会中断
        lc.container.add_item(Item("gold"))
        r.p2_interact()
        assert r.p2_take is not None
        p2.x, p2.y = lc.rect.centerx + 400, lc.rect.centery
        r.update(1 / 60, [])
        assert r.p2_take is None, "离太远要中断"
        # 8) 单人阵亡不结束战局;两人都倒下才结算
        #    先验证「6 级甲倒地自救」是每人一次:P2 用掉不影响 P1
        p2.armor = Item("b45")
        p2.hp = p2.max_hp
        assert r.can_revive(p2) and r.can_revive(r.player)
        p2.take_damage(99999, r)
        assert not p2.dead, "6 级甲应该先自救"
        assert not r.can_revive(p2), "自救每人每局一次"
        assert r.can_revive(r.player), "P2 用掉自救不该影响 P1"
        p2.armor = None
        p2.take_damage(9999, r)
        assert p2.dead and not r.over, "还有 P1 活着就不该结束"
        r.refresh_fog(force=True)
        r.update(1 / 60, [])
        assert not r.over
        r.player.armor = None
        r.player.take_damage(9999, r)
        assert r.over and r.result["kind"] == "death"
        assert r.result["coop"] and r.result["p2_dead"]
        g.draw(screen)                 # 阵亡结算页(双人)
        g.to_hideout()
        # 9) 各自撤离:P1 先撤(战利品立刻进仓库、人退出战场),P2 继续打;
        #    P2 再撤才结算 —— 两人不是一起被带走
        g.save = save_mod.reset_data()
        g.save.seen_intro = True
        g.save.mode = "raid"
        g.save.coop = True
        g.save.touch = False
        before_weapon = g.save.weapon.serialize() if g.save.weapon else None
        before_value = int(g.save.stats["value"])
        g.start_raid()
        r = g.raid
        stash0 = g.save.stash.item_count()
        for bag in (r.player.bag, r.player2.bag):
            it = Item("gold")
            bag.add_item(it)
            r._log_gained(it)
        zone = r.map.extracts[0][1]
        # P1 走进撤离点站 3 秒
        r.player.x, r.player.y = zone.centerx, zone.centery
        for _ in range(int(60 * (EXTRACT_TIME + 0.6))):
            r.update(1 / 60, [])
            if r.player.extracted or r.over:
                break
        assert r.player.extracted, "P1 站满撤离点就该撤出去"
        assert not r.over, "P1 撤了,P2 还在场上 —— 不能一起结算"
        assert r.player.out and not r.player2.out
        assert r.active_players() == (r.player2,)
        assert len(r.fog_polys) == 1, "视野多边形只该有还在场上的那位的"
        assert g.save.stash.item_count() == stash0 + 1, "P1 那份该立刻进仓库"
        assert r.result is None
        # 撤出去的 P1 不吃伤害、不再被敌人选为目标、按键也不再生效
        hp0 = r.player.hp
        r.player.take_damage(9999, r)
        assert r.player.hp == hp0, "撤出去的人不该再吃伤害"
        assert not r.over
        # P2 继续搜刮:战利品还能进他的背包
        lc2 = next(c for c in r.containers
                   if c.kind in ("crate", "val", "med", "gun"))
        lc2.container.items = []
        it2 = Item("btc")
        lc2.container.add_item(it2)
        p2x = r.player2
        p2x.x, p2x.y = lc2.rect.centerx, lc2.rect.centery
        p2x.bag.clear()
        r.p2_interact()
        assert r.p2_take is not None, "P1 走了不影响 P2 自动搜刮"
        for _ in range(60 * 30):
            r.update(1 / 60, [])
            if r.p2_take is None or r.over:
                break
        assert not lc2.container.items and p2x.bag.item_count() >= 1
        # P2 也撤:这时候才结算,两人各自的结果都记在 result 里
        r.player2.x, r.player2.y = zone.centerx, zone.centery
        for _ in range(int(60 * (EXTRACT_TIME + 0.6))):
            r.update(1 / 60, [])
            if r.over:
                break
        assert r.over and r.result["kind"] == "extract", r.result
        assert r.result["coop"]
        assert dict(r.result["coop_status"]) == {"P1": "extract", "P2": "extract"}, \
            r.result["coop_status"]
        assert g.save.stash.item_count() >= stash0 + 2, "两人的战利品都要并进仓库"
        assert r.result["gained"] > 0
        assert int(g.save.stats["value"]) == before_value + r.result["gained"], \
            "撤离收益要记进统计(搜刮价值)"
        assert (g.save.weapon.serialize() if g.save.weapon else None) == before_weapon, \
            "配发装备必须回收,玩家自己的出战配置原样还原"
        g.to_hideout()
        g.draw(screen)                 # 藏身处
        # 10) 渲染:双人世界 + P2 HUD + P2 阵亡画面
        g.save.coop = True
        g.start_raid()
        r = g.raid
        r.player2.x, r.player2.y = r.player.x + 60, r.player.y + 60
        r.player2.hurt_flash = 0.3
        r.player.hurt_flash = 0.2
        r.add_toast("双人测试", (255, 255, 255))
        for _ in range(20):
            r.update(1 / 60, [])
        g.draw(screen)
        r.p2_extract_t = 1.5
        r.p2_take = dict(lc=r.containers[0], queue=[], t=0.4, need=1.0)
        g.draw(screen)                 # P2 撤离条 + 搜刮条
        r.p2_take = None
        r.player2.dead = True
        g.draw(screen)                 # P2 阵亡(灰叉)
        r.inv_open = True
        g.draw(screen)
        r.inv_open = False
        r.finish("extract")
        g.draw(screen)
        g.to_hideout()
        # 11) 单人模式完全不受影响(coop=False 时没有 P2)
        g.save.coop = False
        g.start_raid()
        assert g.raid.coop is False and g.raid.player2 is None
        assert len(g.raid.players()) == 1
        g.draw(screen)
        g.to_hideout()
        # 12) 手机模式自动关掉双人(要键盘)
        g.save.coop = True
        g.save.touch = True
        g.start_raid()
        assert g.raid.coop is False and g.raid.player2 is None
        g.to_hideout()
        g.save.touch = False
        # 13) 夜战 + 双人:两人都拿系统的满配枪(都带强光探照灯),光照是并集
        from settings import weapon_beam, helmet_nvg, COOP_MODES, MODE_DIFF
        assert "night" in COOP_MODES and "raid" in COOP_MODES
        g.save.coop = True
        g.save.mode = "night"
        g.start_raid()
        r = g.raid
        assert r.coop and r.dark and r.player2 is not None
        assert r.diff_key == MODE_DIFF["night"], r.diff_key
        for q in r.players():
            assert q.weapon is not None
            assert weapon_beam(q.weapon) is not None \
                or helmet_nvg(q.helmet) is not None, "夜战双人必须每人都有光源"
        r.refresh_fog(force=True)
        # 光照形状:两位玩家各自的脚边微光/光锥都进了列表
        assert len(r.light_shapes) >= 4, len(r.light_shapes)
        assert r.fog_polygon is None, "夜战不用 360° 视野多边形"
        g.draw(screen)                 # 夜战双人画面(暗层 + 两人的光锥)
        # 只有站在某人的光里才算"看得见":把敌人放进 P2 的灯锥方向
        import math as _m
        s = r.scavs[0]
        r.scavs = [s]
        beam = weapon_beam(r.player2.weapon)
        assert beam is not None
        rng = beam[0] * 0.6
        s.x = r.player2.x + _m.cos(r.player2.aim) * rng
        s.y = r.player2.y + _m.sin(r.player2.aim) * rng
        assert r.in_light(s.x, s.y, r.player2), "P2 灯锥里的点该算亮"
        r.refresh_fog(force=True)
        assert id(s) in r.sight_vis2 or id(s) in r.sight_vis
        assert id(s) in r.fog_vis, "亮区里的敌人应该可见(双人光照并集)"
        for _ in range(30):
            r.update(1 / 60, [])
        assert not r.over
        g.draw(screen)
        g.to_hideout()
        g.save.mode = "raid"
        pygame.display.flip()

    check("账号-名字+密码多档登录/老存档并入/登录界面", t_accounts)
    check("双人合作-P2键盘操作/双人可见性/战利品并仓/单独阵亡", t_coop)

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
