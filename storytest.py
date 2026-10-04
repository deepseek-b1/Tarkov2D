# -*- coding: utf-8 -*-
"""剧情模式《灰区二日》的自检(由 selftest.py 调用)。

单独成文件,免得 selftest.py 继续膨胀。
"""
import pygame

from inventory import Item
from settings import TILE
from world import GameMap
import story as story_mod


def run():
    """跑完整套剧情自检,失败就抛 AssertionError(交给 selftest 的 check 捕获)。"""
    from game import Game
    import save as save_mod
    from settings import W as SW, H as SH

    # ---- 1) 城区大图:比老图大,8 个街区都有剧情内容,关键点全可达 ----
    m = GameMap("city")
    assert m.mw >= 80 and m.mh >= 55, (m.mw, m.mh)
    assert len(m.story_points) >= 30, len(m.story_points)
    assert len(m.story_npcs) == 5, len(m.story_npcs)
    assert len(m.extracts) == 7, [n for n, _r in m.extracts]
    for want in ("铁路桥", "下水道", "黑曜石检查站", "直升机坪",
                 "铁路隧道", "港口船只", "地下管道"):
        assert want in {n for n, _r in m.extracts}, want
    st0 = (int(m.spawn[0] // TILE), int(m.spawn[1] // TILE))
    assert not m.tile_solid(*st0)
    for p in m.story_points + m.story_npcs:
        t = (int(p[0] // TILE), int(p[1] // TILE))
        assert not m.tile_solid(*t), ("关键点在墙里", t)
        assert m.astar(st0, t) is not None, ("关键点不可达", t)
    for _k, p in m.scav_spawns:
        assert m.astar(st0, (int(p[0] // TILE), int(p[1] // TILE))) is not None
    zones = set()
    for p in m.story_points + m.story_npcs:
        tx, ty = int(p[0] // TILE), int(p[1] // TILE)
        zones.add((0 if tx < 20 else 1 if tx < 41 else 2 if tx < 62 else 3,
                   0 if ty < 27 else 1))
    assert len(zones) >= 8, zones
    assert (GameMap("border").mw, GameMap("border").mh) == (60, 44), "老图尺寸不该变"

    # ---- 2) 撤离点规则 ----
    g = Game()
    sd = g.save = save_mod.reset_data()
    sd.seen_intro = True
    sd.mode = "story"
    sd.weapon = Item.weapon("ak74", mag=30)
    sd.pack = Item("pack_large")
    sd.apply_pack()
    sd.bag.add_item(Item("a545", count=120))
    assert story_mod.mission_title(sd) == "D1-1 残骸"
    assert story_mod.can_use_extract(sd, "铁路桥")[0]
    for name in ("下水道", "黑曜石检查站", "直升机坪", "铁路隧道",
                 "港口船只", "地下管道"):
        assert not story_mod.can_use_extract(sd, name)[0], name
    story_mod.apply_effects(sd, dict(wolf=2, flags=["saved_captives"]))
    assert story_mod.can_use_extract(sd, "下水道")[0]
    story_mod.apply_effects(sd, dict(items=["黑曜石通行证"]))
    assert story_mod.can_use_extract(sd, "黑曜石检查站")[0]
    assert story_mod.can_use_extract(sd, "直升机坪")[0]
    story_mod.apply_effects(sd, dict(tapes=12))
    assert story_mod.can_use_extract(sd, "地下管道")[0]

    # ---- 3) 八个时段推进 + 结算 + 归档 ----
    for i in range(8):
        mm = story_mod.mission(sd)
        assert mm is not None, i
        g.start_raid()
        r = g.raid
        assert r.mode == "story" and r.map_key == "city"
        assert r.diff_key == "story"
        assert r.story_mission["id"] == mm["id"]
        if mm["id"] != "d2_4":
            assert len(r.story_targets) >= 1
        if mm["id"] == "d1_4":
            assert any(s.tag == "echo" for s in r.scavs), "该刷回声体"
        for o in story_mod.objectives(sd):
            if o["kind"] == "extract" or o["at"] == "tapes":
                continue
            if story_mod.is_done(sd, o["id"]):
                continue
            if o["kind"] == "kill":
                for s in list(r.scavs):
                    if getattr(s, "tag", None) == o.get("boss"):
                        r.kill_scav(s)
                r._update_story(1 / 60)
                continue
            if o["kind"] == "talk":
                if o.get("dialogue"):
                    for c in story_mod.DIA[o["dialogue"]].get("choices", []):
                        story_mod.apply_effects(sd, c.get("effects", {}))
                story_mod.mark_done(sd, o["id"])
                continue
            story_mod.mark_done(sd, o["id"])
            story_mod.apply_effects(sd, o.get("effects", {}))
        story_mod.set_flag(sd, "saved_captives")
        story_mod.set_flag(sd, "cooling_off")
        story_mod.set_flag(sd, "tracked_courier")
        story_mod.apply_effects(
            sd, dict(tapes=max(0, 12 - story_mod.st(sd)["tapes"])))
        if mm["id"] == "d2_3":
            story_mod.apply_effects(sd, dict(final="truth"))
        r.finish("extract")
        assert r.result.get("story_note"), "结算要写剧情说明"
    assert story_mod.st(sd)["ending"] in ("A", "F"), story_mod.st(sd)["ending"]
    assert story_mod.st(sd)["endings"]
    save_mod.save_data(sd)
    sd_loaded = save_mod.load_data()
    assert sd_loaded.story["ending"] == story_mod.st(sd)["ending"]
    assert sd_loaded.story["tapes"] == 12
    assert story_mod.ENDINGS[sd_loaded.story["ending"]]["line"]

    # ---- 4) 六个结局判定 ----
    def _mk(**kw):
        gg = Game()
        s = gg.save = save_mod.reset_data()
        s.mode = "story"
        story_mod.st(s)
        story_mod.apply_effects(s, kw)
        story_mod.set_flag(s, "saved_captives")
        return s

    assert story_mod.ending_for(
        _mk(tapes=12, flags=["cooling_off", "tracked_courier"]))[0] == "F"
    assert story_mod.ending_for(_mk(tapes=12, flags=["cooling_off"]))[0] != "F"
    for final, want in (("trade", "B"), ("rescue", "C"), ("scorch", "D"),
                        ("selfish", "E"), ("truth", "A")):
        assert story_mod.ending_for(_mk(final=final))[0] == want, final
    for k, d in story_mod.ENDINGS.items():
        assert d["name"] and d["line"] and d["text"], k

    # ---- 5) 局内交互 / 对白分支 / 撤离限制 / 渲染 ----
    g2 = Game()
    sd2 = g2.save = save_mod.reset_data()
    sd2.seen_intro = True
    sd2.mode = "story"
    sd2.weapon = Item.weapon("ak74", mag=30)
    sd2.pack = Item("pack_mid")
    sd2.apply_pack()
    sd2.bag.add_item(Item("a545", count=120))
    g2.start_raid()
    r2 = g2.raid
    o = story_mod.objectives(sd2)[0]
    px, py = story_mod.at_pos(o["at"])
    r2.player.x, r2.player.y = px, py - 30
    r2.interact()
    assert r2.channel is not None and r2.channel["kind"] == "story"
    for _ in range(400):
        r2.update(1 / 60, [])
        if r2.channel is None:
            break
    assert story_mod.is_done(sd2, o["id"])
    assert r2.dialogue is not None
    while r2.dialogue is not None:
        r2.dialogue_next()
    cap = next(x for x in story_mod.objectives(sd2) if x["id"] == "d1_1_captives")
    px, py = story_mod.at_pos(cap["at"])
    r2.player.x, r2.player.y = px, py - 30
    r2.interact()
    assert r2.dialogue is not None and r2.dialogue["choices"]
    while r2.dialogue["idx"] < len(r2.dialogue["lines"]) - 1:
        r2.dialogue_next()
    assert r2.dialogue_choose(0)
    assert story_mod.flag(sd2, "saved_captives")
    assert story_mod.wolf_trust(sd2) == 1
    r2.dialogue_next()
    assert r2.dialogue is None
    ex = next(rr for n, rr in r2.map.extracts if n == "黑曜石检查站")
    r2.player.x, r2.player.y = ex.centerx, ex.centery
    for _ in range(int(5 * 60)):
        r2.update(1 / 60, [])
    assert not r2.over, "没通行证不该能从检查站撤离"
    assert "黑曜石检查站" in r2.warned
    ex2 = next(rr for n, rr in r2.map.extracts if n == "铁路桥")
    r2.player.x, r2.player.y = ex2.centerx, ex2.centery
    for _ in range(int(5 * 60)):
        r2.update(1 / 60, [])
        if r2.over:
            break
    assert r2.over and r2.result["kind"] == "extract"
    assert r2.result["story_note"]
    scr2 = pygame.display.set_mode((SW, SH))
    g2.draw(scr2)                                  # 剧情 HUD + 关键点标记
    g3 = Game()
    g3.save = save_mod.reset_data()
    g3.save.seen_intro = True
    g3.save.mode = "story"
    g3.start_raid()
    r3 = g3.raid
    r3.dialogue = dict(speaker="艾琳", lines=["测试台词一", "测试台词二"],
                       idx=1, choices=[dict(text="选项甲"), dict(text="选项乙")],
                       reply=None)
    g3.draw(scr2)                                  # 对白面板 + 选项
    r3.dialogue["reply"] = "回复"
    g3.draw(scr2)
    r3.dialogue = None
    r3.finish("death")
    g3.draw(scr2)                                  # 剧情结算页
    g3.to_hideout()
    h3 = g3.hideout
    h3.show_intro = False
    from settings import MODE_ORDER
    h3._click(h3.mode_rects[MODE_ORDER.index("story")].center)
    assert g3.save.mode == "story" and g3.save.map_key == "city"
    h3._click(h3.lay["story"].center)
    assert h3.view == "story"
    g3.draw(scr2)                                  # 剧情简报页
    # 返回按钮必须真的能退(以前 story 视图的点击没接上,点了没反应)
    ev_back = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                 pos=h3.task_close.center)
    h3.update(0.0, [ev_back])
    assert h3.view == "stash", "剧情简报的返回按钮必须能退回仓库"
    h3._click(h3.lay["story"].center)
    assert h3.view == "story"
    g3.draw(scr2)
    ev_out = pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=(20, 20))
    h3.update(0.0, [ev_out])                       # 点面板外的空白处也能退
    assert h3.view == "stash"
    h3.view = "stash"
    g3.draw(scr2)
    pygame.display.flip()

    # ---- 6) 开局补给:空手进剧情必须发枪(不然没法玩),阵亡只丢战利品 ----
    from settings import POCKETS
    g4 = Game()
    s4 = g4.save = save_mod.reset_data()
    s4.seen_intro = True
    s4.stash.clear()
    s4.bag.clear()
    s4.weapon = Item.weapon("pm", mag=5)      # 玩家自己的旧配置(应当被原样还原)
    s4.armor = Item("paca")
    s4.pack = Item("pack_small")
    s4.apply_pack()
    s4.bag.add_item(Item("a9", count=13))
    s4.mode = "story"
    g4.start_raid()
    r4 = g4.raid
    assert r4.player.weapon is not None and r4.player.weapon.iid == "m4a1", \
        "剧情模式该配发 M4A1"
    assert r4.player.weapon.state.get("mag", 0) > 0, "枪要满弹匣"
    assert r4.player.armor is not None and r4.player.armor.def_["level"] >= 5, \
        "要配发护甲"
    assert r4.player.reserve_count() >= 60, "备弹要够打"
    assert any(pl.item.cat == "med" for pl in r4.player.bag.items), "要配发药品"
    assert r4.story_issued, "配发清单要能提示玩家"
    # 捡两件战利品再撤离:战利品进仓库、配发装备回收、旧配置原样还原
    r4.player.bag.add_item(Item("gold"))
    r4.player.bag.add_item(Item("cpu"))
    r4.finish("extract")
    s4b = save_mod.load_data()
    assert s4b.weapon.iid == "pm" and s4b.weapon.state["mag"] == 5, \
        s4b.weapon.serialize()
    assert s4b.armor.iid == "paca" and s4b.pack.iid == "pack_small", "旧配置要还原"
    stash_ids = [pl.item.iid for pl in s4b.stash.items]
    assert "gold" in stash_ids and "cpu" in stash_ids, stash_ids
    assert "m4a1" not in stash_ids and "b45" not in stash_ids, \
        "配发装备要被回收,不能留在仓库"
    assert [pl.item.iid for pl in s4b.bag.items] == ["a9"]
    # 阵亡:配发装备同样回收,旧配置仍还原(战利品随尸体丢掉)
    g5 = Game()
    g5.save = s4b
    g5.save.mode = "story"
    g5.start_raid()
    assert g5.raid.player.weapon.iid == "m4a1"
    g5.raid.finish("death")
    s5 = save_mod.load_data()
    assert s5.weapon.iid == "pm" and s5.armor.iid == "paca"
    assert not any(pl.item.iid == "m4a1"
                   for c in (s5.stash, s5.bag) for pl in c.items)
    assert (s5.bag.w, s5.bag.h) == (5, 3), (s5.bag.w, s5.bag.h)
    # 别的模式不受影响:搜打撤空手进就是空手
    g6 = Game()
    s6 = g6.save = save_mod.reset_data()
    s6.seen_intro = True
    s6.weapon = None
    s6.pack = None
    s6.apply_pack()
    s6.bag.clear()
    s6.mode = "raid"
    g6.start_raid()
    assert g6.raid.player.weapon is None, "只有剧情模式才配发"

    # ---- 7) 剧情演出与录音字幕:选择有动画、捡录音有字幕 ----
    g7 = Game()
    s7 = g7.save = save_mod.reset_data()
    s7.seen_intro = True
    s7.mode = "story"
    g7.start_raid()
    r7 = g7.raid
    cap7 = next(o for o in story_mod.objectives(s7) if o["id"] == "d1_1_captives")
    px7, py7 = story_mod.at_pos(cap7["at"])
    r7.player.x, r7.player.y = px7, py7 - 30
    r7.interact()
    assert r7.dialogue is not None and r7.dialogue["at"]
    while r7.dialogue["idx"] < len(r7.dialogue["lines"]) - 1:
        r7.dialogue_next()
    assert r7.dialogue_choose(0)             # 救俘虏
    assert r7.cutscene is not None and r7.cutscene["kind"] == "rescue"
    assert r7.captive_state == "freed"
    assert any("灰狼信任" in f["text"] for f in r7.floaters), r7.floaters
    assert (r7.cutscene["x"], r7.cutscene["y"]) == r7.dialogue["at"]
    for _ in range(40):                      # 演出推进 + 渲染
        r7.update(1 / 60, [])
        g7.draw(scr2)
    assert r7.cutscene is not None and r7.cutscene["t"] > 0
    for _ in range(int(3.5 * 60)):
        r7.update(1 / 60, [])
    assert r7.cutscene is None and not r7.floaters, "演出/飘字要自己收尾"
    while r7.dialogue is not None:
        r7.dialogue_next()
    # 另一个选项:处决演出 + 尸体
    g8 = Game()
    s8 = g8.save = save_mod.reset_data()
    s8.seen_intro = True
    s8.mode = "story"
    g8.start_raid()
    r8 = g8.raid
    r8.player.x, r8.player.y = px7, py7 - 30
    r8.interact()
    while r8.dialogue["idx"] < len(r8.dialogue["lines"]) - 1:
        r8.dialogue_next()
    assert r8.dialogue_choose(1)             # 不管他们
    assert r8.cutscene["kind"] == "shoot" and r8.captive_state == "dead"
    # 12 份录音的台词齐全且不重复
    assert len(set(story_mod.tape_line(i) for i in range(12))) == 12
    for i in range(12):
        assert story_mod.tape_line(i).startswith(f"录音 {i + 1}:")
    while r8.dialogue is not None:
        r8.dialogue_next()
    tape7 = next(o for o in story_mod.objectives(s8) if o["at"] == "tapes")
    ttx, tty = story_mod.CITY_AT["tapes"][tape7["tape_index"]]
    r8.player.x, r8.player.y = ttx * 32 + 16, tty * 32 + 16 - 30
    r8.interact()
    for _ in range(400):
        r8.update(1 / 60, [])
        if r8.channel is None:
            break
    assert r8.subtitle is not None, "捡到录音要在屏幕下方出字幕"
    assert story_mod.tape_line(tape7["tape_index"]) == r8.subtitle["text"]
    assert story_mod.st(s8)["tapes"] == 1
    for _ in range(60):
        r8.update(1 / 60, [])
        g8.draw(scr2)                        # 字幕要能画出来
    # 给药:aid 演出
    g9 = Game()
    s9 = g9.save = save_mod.reset_data()
    s9.seen_intro = True
    s9.mode = "story"
    story_mod.st(s9)["period"] = 1
    g9.start_raid()
    r9 = g9.raid
    wolf7 = next(o for o in story_mod.objectives(s9) if o["id"] == "d1_2_wolf")
    wx7, wy7 = story_mod.at_pos(wolf7["at"])
    r9.player.x, r9.player.y = wx7, wy7 - 30
    r9.interact()
    while r9.dialogue["idx"] < len(r9.dialogue["lines"]) - 1:
        r9.dialogue_next()
    assert r9.dialogue_choose(0)             # 给药
    assert r9.cutscene["kind"] == "aid"
    for _ in range(30):
        r9.update(1 / 60, [])
        g9.draw(scr2)


