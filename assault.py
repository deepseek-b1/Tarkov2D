# -*- coding: utf-8 -*-
"""突袭模式的系统配发装备。

进入突袭时随机发一套"满配件 + 全是高级配件"的装备;战局结束后(无论胜负)
把配发装备与战利品全部回收,并把玩家原来的出战配置原样还原 —— 不碰仓库。
"""
import random

from settings import (ASSAULT_RESERVE_AMMO, ISSUE_WEAPONS, ISSUE_ATTACH,
                      ISSUE_ARMORS, ISSUE_PACKS, ISSUE_MEDS,
                      ITEMS, pack_grid, weapon_slots, weapon_capacity,
                      weapon_ammo_ids)
from inventory import Container, Item


def snapshot(sd):
    """快照玩家当前的出战配置(用 JSON 结构,避免与战局共享可变对象)。"""
    return dict(
        weapon=sd.weapon.serialize() if sd.weapon else None,
        armor=sd.armor.serialize() if sd.armor else None,
        helmet=sd.helmet.serialize() if getattr(sd, "helmet", None) else None,
        pack=sd.pack.serialize() if sd.pack else None,
        bag=sd.bag.serialize(), bag_w=sd.bag.w, bag_h=sd.bag.h,
    )


def restore(sd, snap):
    """把快照原样还原回出战配置。"""
    if not snap:
        return
    sd.weapon = Item.from_dict(snap["weapon"]) if snap.get("weapon") else None
    sd.armor = Item.from_dict(snap["armor"]) if snap.get("armor") else None
    sd.helmet = Item.from_dict(snap["helmet"]) if snap.get("helmet") else None
    sd.pack = Item.from_dict(snap["pack"]) if snap.get("pack") else None
    sd.bag = Container.deserialize(int(snap.get("bag_w", 6)),
                                   int(snap.get("bag_h", 4)), snap.get("bag"))


def build(rng=random):
    """生成一套配发装备:(武器, 护甲, 背包, 背包物品列表)。"""
    wid = rng.choice(ISSUE_WEAPONS)
    weapon = Item.weapon(wid)
    attach = {s: ISSUE_ATTACH[s] for s in weapon_slots(wid) if s in ISSUE_ATTACH}
    if attach:
        weapon.state["attach"] = dict(attach)
    weapon.state["mag"] = weapon_capacity(weapon)      # 配件扩容后重新装满
    armor = Item(rng.choice(ISSUE_ARMORS))
    pack = Item(rng.choice(ISSUE_PACKS))
    items = []
    ammo_iid = weapon_ammo_ids(weapon)[0]
    left = ASSAULT_RESERVE_AMMO
    stack = ITEMS[ammo_iid].get("stack", 120)
    while left > 0:
        items.append(Item(ammo_iid, count=min(left, stack)))
        left -= min(left, stack)
    for mid in rng.sample(ISSUE_MEDS, 2):
        items.append(Item(mid))
    return weapon, armor, pack, items


def issue(sd, rng=random):
    """配发装备(就地替换出战配置)。返回快照,战局结束后交给 restore() 还原。"""
    snap = snapshot(sd)
    weapon, armor, pack, items = build(rng)
    sd.weapon, sd.armor, sd.pack = weapon, armor, pack
    sd.bag = Container(*pack_grid(pack.iid))
    for it in items:
        if not sd.bag.add_item(it):
            break
    return snap


def describe(sd):
    """配发装备的一句话说明(藏身处/HUD 提示用)。"""
    if sd.weapon is None:
        return "未配发"
    n = len(sd.weapon.state.get("attach") or {})
    return f"{sd.weapon.name} · 满配件({n} 件顶级配件) · {sd.armor.name if sd.armor else '无甲'}"
