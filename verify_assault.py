# -*- coding: utf-8 -*-
"""临时验证:突袭模式全流程(配发装备/50 守军/支援/目标/撤离/存档还原/性能)。用完即删。"""
import os
import time
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame
pygame.init()

import random
random.seed(11)
import tempfile
import save as save_mod
save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="assault_verify_")
save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")

from settings import (W, H, ASSAULT_ENEMIES, ASSAULT_ALLIES, SUPPORT,
                      SUPPORT_ORDER, ASSAULT_DESTROY_TIME, weapon_slots)
from inventory import Item
from game import Game

screen = pygame.display.set_mode((W, H))
g = Game()
sd = g.save
# 玩家原本的配置(用来验证战后还原)
sd.stash.clear(); sd.bag.clear()
sd.weapon = Item.weapon("pm", mag=8)
sd.armor = Item("paca")
sd.pack = Item("pack_mid")
sd.apply_pack()
sd.bag.add_item(Item("a9", count=17))
sd.bag.add_item(Item("bandage"))
sd.mode = "assault"
sd.seen_intro = True
before = (sd.weapon.iid, sd.armor.iid, sd.pack.iid, sd.bag.item_count(),
          [(p.x, p.y, p.item.iid, p.item.count) for p in sd.bag.items])

g.start_raid()
r = g.raid
print("mode:", r.mode, "map:", r.map_key, "diff:", r.diff["name"], r.diff_key)
print("守军:", len(r.scavs), "队友:", len(r.allies), "目标:", len(r.objectives),
      "撤离点:", len(r.map.extracts))
assert len(r.scavs) == ASSAULT_ENEMIES
assert len(r.allies) == ASSAULT_ALLIES
assert len(r.objectives) == 3 and len(r.map.extracts) == 2
assert r.boss_cfg is None
assert r.support_points == 10
print("配发装备:", r.player.weapon.name, r.player.weapon.state.get("attach"),
      "| 护甲", r.player.armor.name, "| 背包", sd.pack.name,
      r.player.bag.w, "x", r.player.bag.h)
w = r.player.weapon
assert w.state["attach"], "配发武器必须满配件"
assert set(w.state["attach"]) == set(weapon_slots(w.iid)), (w.state["attach"], w.iid)
from settings import weapon_capacity
assert w.state["mag"] == weapon_capacity(w), (w.state["mag"], weapon_capacity(w))
assert r.player.armor.def_["level"] >= 5

# 目标必须可达(从出生点)
st = (int(r.player.x // 32), int(r.player.y // 32))
for o in r.objectives:
    assert r.map.astar(st, (int(o.x // 32), int(o.y // 32))) is not None, o.name

# ---- 支援:积分不足 / 正常呼叫 / 冷却 ----
ok, why = r.support_state("airstrike")
assert ok, why
assert r.call_support("airstrike", r.player.x + 500, r.player.y)
assert r.support_points == 2, r.support_points
assert not r.call_support("barrage", r.player.x, r.player.y), "积分不足不该叫出来"
assert r.support_points == 2
r.support_points = 40
assert r.call_support("barrage", r.player.x + 600, r.player.y)
assert not r.call_support("barrage", r.player.x + 600, r.player.y), "冷却中不该能再叫"
before_kills = r.kills
# 把一部分守军堆到落点上,验证支援能杀敌
tgt = None
for stx in r.strikes:
    if stx["kind"] in ("airstrike", "barrage"):
        tgt = stx
for i, s in enumerate(r.scavs[:14]):
    s.x = tgt["x"] + (i % 4) * 30 - 45
    s.y = tgt["y"] + (i // 4) * 30 - 30
for _ in range(int(12 / (1 / 60))):
    r.update(1 / 60, [])
    g.draw(screen)
print("支援后击杀:", r.kills - before_kills, "积分:", r.support_points,
      "剩余守军:", len(r.scavs))
assert r.kills - before_kills >= 5, "支援火力应该炸死一片守军"
assert r.support_points > 2, "击杀应该涨积分"

# 无人机侦察
assert r.call_support("recon", r.player.x, r.player.y)
for _ in range(100):
    r.update(1 / 60, [])
assert r.recon_t > 0, r.recon_t
g.draw(screen)

# ---- 炸目标 ----
r.scavs = []
for o in r.objectives:
    r.player.x, r.player.y = o.x, o.y + 20
    r.interact()
    assert r.channel is not None and r.channel["kind"] == "destroy"
    need = r.channel_need()
    for _ in range(int((need + 0.6) * 60)):
        r.update(1 / 60, [])
        if r.channel is None:
            break
    assert o.destroyed, o.name
assert r.objectives_done()

# ---- 炸完目标 -> 撤离 -> 存档还原(突袭不带走任何东西) ----
ex = r.map.extracts[0][1]
r.player.x, r.player.y = ex.centerx, ex.centery
for _ in range(int(5 / (1 / 60))):
    r.update(1 / 60, [])
assert r.over and r.result["kind"] == "extract", r.result
print("结算:", {k: r.result[k] for k in ("kind", "kills", "mission",
                                          "objectives_done", "support_calls")})
assert r.result["mission"] is True
sd2 = save_mod.load_data()
after = (sd2.weapon.iid, sd2.armor.iid, sd2.pack.iid, sd2.bag.item_count(),
         sorted((p.x, p.y, p.item.iid, p.item.count) for p in sd2.bag.items))
print("战前:", before[0], before[1], before[2], before[3])
print("战后:", after[0], after[1], after[2], after[3])
assert after[0] == "pm" and after[1] == "paca" and after[2] == "pack_mid", after
assert after[3] == before[3] and after[4] == sorted(before[4]), (before[4], after[4])
assert len(sd2.stash.items) == 0
assert sd2.mode == "assault"
r2_game = Game()
r2_game.save = save_mod.reset_data()
r2_game.save.mode = "assault"
r2_game.save.seen_intro = True
r2_game.start_raid()
r2 = r2_game.raid
ex = r2.map.extracts[0][1]
r2.player.x, r2.player.y = ex.centerx, ex.centery
for _ in range(int(5 / (1 / 60))):
    r2.update(1 / 60, [])
assert not r2.over, "目标没炸完不该能撤离"
assert "locked" in r2.warned, "应该提示过必须先炸设施"
for o in r2.objectives:
    o.destroyed = True
r2.player.x, r2.player.y = ex.centerx, ex.centery
for _ in range(int(5 / (1 / 60))):
    r2.update(1 / 60, [])
assert r2.over and r2.result["kind"] == "extract", r2.result
assert r2.result["mission"] is True

# 阵亡也要还原:死一次看看仓库是否干净
g4 = Game()
g4.save = save_mod.reset_data()
g4.save.mode = "assault"
g4.save.seen_intro = True
g4.save.stash.add_item(Item("gold"))
stash_before = sorted((p.x, p.y, p.item.iid, p.item.count) for p in g4.save.stash.items)
g4.start_raid()
r4 = g4.raid
assert r4.player.weapon.iid != "pm", "应该已换成配发武器"
r4.finish("death")
sd4 = save_mod.load_data()
assert sd4.weapon.iid == "pm" and sd4.armor is None, (sd4.weapon, sd4.armor)
stash_after = sorted((p.x, p.y, p.item.iid, p.item.count) for p in sd4.stash.items)
assert stash_after == stash_before, (stash_before, stash_after)
print("阵亡后仓库与配置也已还原")

# ---- 性能:50 名守军全部追击 + 全屏绘制 ----
g3 = Game()
g3.save = save_mod.reset_data()
g3.save.mode = "assault"
g3.save.seen_intro = True
g3.start_raid()
r3 = g3.raid
for s in r3.scavs:
    s.state = "chase"
    s.alert = (r3.player.x, r3.player.y)
for i, o in enumerate(r3.objectives):
    o.destroyed = True
frames = 300
t0 = time.perf_counter()
for i in range(frames):
    if i % 30 == 0:
        for s in r3.scavs:
            s.state = "chase"
            s.alert = (r3.player.x, r3.player.y)
    r3.fire_edge = True
    r3.try_fire(True); r3.fire_edge = False
    r3.player.fire_cd = 0
    r3.update(1 / 60, [])
    g3.draw(screen)
dt = (time.perf_counter() - t0) / frames
print(f"50 守军: {dt * 1000:.2f} ms/帧 (~{1 / dt:.0f} FPS 上限)")
print("OK")
