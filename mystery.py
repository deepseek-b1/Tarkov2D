# -*- coding: utf-8 -*-
"""礼品:神秘人的长线收集任务 + 全装包。

规则(与用户确认过的形态):
  * 每次启动游戏重抽一份"要收集的东西"清单(任务难度 10 星,一大堆东西);
  * 清单看的是"仓库+背包里有没有",所以刷新清单不会让玩家白攒进度;
  * 凑齐交给神秘人,换 MYSTERY_KIT_COUNT 套「全装包」;
  * 每轮还会掷一次"额外送你一张机密文件",概率与强化封锁刷机密文件一致;
  * 一轮只能交一次,交完等下次启动游戏换新清单;
  * 全装包本身是 2×2 物品,右键(电脑)/长按面板点「打开」(手机)才展开成一套装备。

所有"先扣材料还是先发东西"的顺序都遵守项目规矩:**先在克隆容器上试算,
全部放得下才动真身**,绝不让玩家白交材料或白丢包。
"""
import random

from inventory import Container, Item
from settings import (ITEMS, KIT_CONTENTS, MYSTERY_DOC_CHANCE, MYSTERY_KINDS,
                      MYSTERY_KIT_COUNT, MYSTERY_KITS, MYSTERY_POOL,
                      weapon_capacity, weapon_slots)
from quests import consume, have_count

# 专用随机源:抽清单不能动全局 random 的序列 —— 全局那条被战局生成
# (刷怪/掉落/散布)和自检的固定种子共用,这里多抽几个数会让整套随机全部错位。
_rng = random.Random()


# ---------- 存档里的礼品状态 ----------
def state(sd):
    m = getattr(sd, "mystery", None)
    return m if isinstance(m, dict) else {}


def round_no(sd):
    try:
        return int(state(sd).get("round", 0))
    except (TypeError, ValueError):
        return 0


def need_list(sd):
    """当前清单 [(iid, 数量)];存档里的脏数据(不存在的物品/非法数量)直接忽略。"""
    out = []
    for entry in state(sd).get("need") or []:
        try:
            iid, n = entry[0], int(entry[1])
        except (TypeError, ValueError, IndexError):
            continue
        if iid in ITEMS and n > 0:
            out.append((iid, n))
    return out


def claimed(sd):
    return bool(state(sd).get("claimed"))


def doc_bonus(sd):
    """本轮是否额外送机密文件(在 roll 时就掷好了,避免反复点交付刷概率)。"""
    return bool(state(sd).get("doc"))


def missing(sd):
    """还差哪些:[(iid, 差多少)]。"""
    out = []
    for iid, n in need_list(sd):
        have = have_count(sd, iid)
        if have < n:
            out.append((iid, n - have))
    return out


def ready(sd):
    return bool(need_list(sd)) and not claimed(sd) and not missing(sd)


def prepared_count(sd):
    """已备齐的物品种数 / 总种数(右上角进度用)。"""
    need = need_list(sd)
    ok = sum(1 for iid, n in need if have_count(sd, iid) >= n)
    return ok, len(need)


def reward_text():
    return f"全装包 ×{MYSTERY_KIT_COUNT}"


# ---------- 每轮刷新 ----------
def roll(sd, rng=None):
    """新的一轮:重抽清单 + 掷一次机密文件(每次启动游戏调用)。

    默认用本模块自己的随机源,不碰全局 random(见文件头说明)。
    """
    rng = rng or _rng
    pool = list(MYSTERY_POOL)
    kinds = rng.randint(*MYSTERY_KINDS)
    need = []
    for _ in range(min(kinds, len(pool))):
        iid, span = _pick(pool, rng)
        need.append([iid, rng.randint(span[0], span[1])])
    sd.mystery = dict(need=need, round=round_no(sd) + 1,
                      doc=bool(rng.random() < MYSTERY_DOC_CHANCE), claimed=False)
    return sd.mystery


def _pick(pool, rng):
    """按权重从池里挑一个并移除(清单里不出现重复物品)。"""
    total = sum(p[1] for p in pool)
    r = rng.uniform(0, total)
    acc = 0.0
    chosen = len(pool) - 1
    for i, p in enumerate(pool):
        acc += p[1]
        if r <= acc:
            chosen = i
            break
    iid, _weight, span = pool.pop(chosen)
    return iid, span


# ---------- 交货 ----------
def turn_in(sd):
    """把清单交给神秘人:扣材料 + 发全装包(可能含机密文件)。"""
    if not need_list(sd):
        return False, "神秘人还没给你清单(重开一次游戏就会刷新)"
    if claimed(sd):
        return False, "这一轮已经交过货了 —— 下次启动游戏他会给你新的清单"
    miss = missing(sd)
    if miss:
        lack = "、".join(f"{ITEMS[iid]['name']}×{n}" for iid, n in miss)
        return False, f"清单还没凑齐,还缺:{lack}"
    # 先克隆仓库试算:放得下才动真身(和任务奖励同一条规矩)
    stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
    bag = Container.deserialize(sd.bag.w, sd.bag.h, sd.bag.serialize())
    items = [Item(kid) for kid in MYSTERY_KITS]
    if doc_bonus(sd):
        items.append(Item("doc"))
    for it in items:
        if not stash.add_item(it):
            return False, f"仓库放不下 {it.name},先清点空间再来交货"
    for iid, n in need_list(sd):
        left = n - consume(stash, iid, n)
        if left > 0:
            consume(bag, iid, left)
    sd.stash, sd.bag = stash, bag
    state(sd)["claimed"] = True
    msg = f"神秘人收下了货:给你 {MYSTERY_KIT_COUNT} 套全装包"
    if doc_bonus(sd):
        msg += " —— 他还额外塞给你一张机密文件!"
    return True, msg


# ---------- 全装包 ----------
def kit_items(kid):
    """打开全装包能拿到的东西(武器按配件槽过滤,避免装上不支持的配件)。"""
    cfg = KIT_CONTENTS.get(kid)
    if not cfg:
        return []
    out = []
    w = Item.weapon(cfg["weapon"])
    slots = weapon_slots(cfg["weapon"])
    attach = {s: a for s, a in (cfg.get("attach") or {}).items() if s in slots}
    if attach:
        w.state["attach"] = dict(attach)
        w.state["mag"] = weapon_capacity(w)      # 配件扩容后重新装满
    out.append(w)
    for key in ("armor", "helmet", "pack"):
        if cfg.get(key):
            out.append(Item(cfg[key]))
    for iid, n in cfg.get("ammo", []):
        out.append(Item(iid, count=int(n)))
    for iid, n in cfg.get("meds", []):
        out.append(Item(iid, count=int(n)))
    return out


def kit_summary(kid):
    """一句话说明包里有什么(提示行/详情用)。"""
    cfg = KIT_CONTENTS.get(kid)
    if not cfg:
        return ""
    names = [ITEMS[cfg["weapon"]]["name"]]
    for key in ("armor", "helmet"):
        if cfg.get(key):
            names.append(ITEMS[cfg[key]]["name"])
    return " + ".join(names)


def open_kit(container, placed):
    """在容器里把全装包展开成一套装备(放不下就整包不动)。"""
    it = placed.item
    if it.cat != "kit":
        return False, ""
    contents = kit_items(it.iid)
    if not contents:
        return False, f"{it.name} 是空的(数据缺失)"
    clone = Container.deserialize(container.w, container.h, container.serialize())
    target = None
    for pl in clone.items:      # 克隆里的物品是新对象:按 (iid, x, y) 认人
        if pl.item.iid == it.iid and pl.x == placed.x and pl.y == placed.y:
            target = pl
            break
    if target is None:
        return False, "全装包不见了,先整理一下再开"
    clone.remove_placed(target)
    for c in contents:
        if not clone.add_item(c):
            return False, (f"空间不够,展不开 {it.name}"
                           f"(要腾出 {it.def_['w']}×{it.def_['h']} 格以上的地方)")
    container.items = clone.items
    return True, f"{it.name} 已打开:{kit_summary(it.iid)} 等 {len(contents)} 件装备"
