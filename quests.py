# -*- coding: utf-8 -*-
"""任务系统:教官发任务(进度由战局结算累计),医疗/后勤用局内材料交货换东西。

奖励/交货都是"先试算再落盘":仓库放不下就不发,绝不让玩家白交材料或白领奖励。
保险承包商:40 个长线任务,全部完成后保险箱(阵亡不丢)从 2 格升为 4 格。
"""
from settings import (TASKS, DEPARTMENT_BARTERS, ITEMS, SAFE_CONTRACT,
                      SAFE_UPGRADED, SAFE_BASE)
from inventory import Container, Item


def task_by_id(tid):
    for t in TASKS:
        if t["id"] == tid:
            return t
    return None


def progress(sd, task):
    return int(sd.tasks.get(task["id"], 0))


def task_state(sd, task):
    """返回 (状态, 进度, 需求)。状态:done / ready / doing。"""
    need = int(task["need"])
    if not task.get("repeat") and task["id"] in sd.tasks_done:
        return "done", need, need
    p = progress(sd, task)
    return ("ready" if p >= need else "doing"), p, need


def add_progress(sd, kind, amount):
    """战局结算时累计进度(击杀/撤离/价值/人质/突袭)。教官与承包商任务一起涨。"""
    if amount <= 0:
        return
    for t in TASKS + SAFE_CONTRACT:
        if t["kind"] == kind:
            sd.tasks[t["id"]] = progress(sd, t) + int(amount)


# ---------- 保险承包商(保险箱扩容) ----------
def safe_done_count(sd):
    """已完成(已领取)的承包商任务数。"""
    done = set(sd.tasks_done)
    return sum(1 for t in SAFE_CONTRACT if t["id"] in done)


def safe_upgraded(sd):
    """40 个承包商任务是否全部完成(保险箱 4 格)。"""
    return safe_done_count(sd) >= len(SAFE_CONTRACT)


def check_safe_upgrade(sd):
    """全部完成 -> 把保险箱从 2 格升为 4 格(2×2)。幂等;返回提示或 ""。"""
    if not safe_upgraded(sd):
        return ""
    if (sd.safe.w, sd.safe.h) == tuple(SAFE_UPGRADED):
        return ""
    new_safe, overflow = sd.safe.resized(SAFE_UPGRADED[0], SAFE_UPGRADED[1])
    for it in overflow:
        # 2×1 -> 2×2 是超集,理论上不会放不下;万一放不下退回仓库
        if not sd.stash.add_item(it):
            sd.safe = new_safe
            return "★ 保险箱扩容完成,但有物品没能安置(仓库也满)"
    sd.safe = new_safe
    return "★ 保险承包商 40 项任务全部完成:保险箱已扩为 4 格(2×2,阵亡不丢)!"


def reward_text(reward):
    parts = []
    if reward.get("rubles"):
        parts.append(f"{int(reward['rubles']):,} 卢布")
    for iid in reward.get("weapons", []):
        parts.append(ITEMS[iid]["name"])
    for iid in reward.get("attachments", []):
        parts.append(ITEMS[iid]["name"])
    for iid, cnt in reward.get("ammo", []):
        parts.append(f"{ITEMS[iid]['name']} ×{cnt}")
    return " + ".join(parts) if parts else "无"


def grant(sd, reward):
    """发奖励(先克隆仓库试算,放不下就整体不发)。返回 (成功, 提示)。"""
    stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
    items = []
    for iid in reward.get("weapons", []):
        items.append(Item.weapon(iid, mag=ITEMS[iid]["mag"]))
    for iid in reward.get("attachments", []):
        items.append(Item(iid))
    for iid, cnt in reward.get("ammo", []):
        items.append(Item(iid, count=int(cnt)))
    for it in items:
        if not stash.add_item(it):
            return False, f"仓库放不下 {it.name},先清点空间再来领"
    sd.stash = stash
    if reward.get("rubles"):
        sd.rubles += int(reward["rubles"])
    return True, ""


def claim(sd, task):
    """领取任务奖励(教官/承包商)。返回 (成功, 提示)。"""
    state, p, need = task_state(sd, task)
    if state == "done":
        return False, f"「{task['name']}」已结算过了"
    if state != "ready":
        return False, f"「{task['name']}」还没完成({p}/{need})"
    ok, why = grant(sd, task["reward"])
    if not ok:
        return False, why
    if task.get("repeat"):
        sd.tasks[task["id"]] = p - need          # 可重复任务:扣掉已结算的部分
    else:
        sd.tasks_done.append(task["id"])
    msg = f"「{task['name']}」奖励已发放:{reward_text(task['reward'])}"
    extra = check_safe_upgrade(sd)               # 承包商 40 项齐全 -> 保险箱扩容
    return True, (msg + "  " + extra) if extra else msg


# ---------- 部门交货 ----------
def barter_list(dept):
    return DEPARTMENT_BARTERS.get(dept, [])


def have_count(sd, iid):
    return (sum(pl.item.count for pl in sd.stash.items if pl.item.iid == iid)
            + sum(pl.item.count for pl in sd.bag.items if pl.item.iid == iid))


def missing_materials(sd, entry):
    """还差哪些材料:[(iid, 差多少)]。"""
    out = []
    for iid, n in entry["need"]:
        have = have_count(sd, iid)
        if have < n:
            out.append((iid, n - have))
    return out


def need_text(entry):
    return " + ".join(f"{ITEMS[iid]['name']}×{n}" for iid, n in entry["need"])


def out_text(entry):
    return " + ".join(f"{ITEMS[iid]['name']}×{n}" for iid, n in entry["out"])


def consume(container, iid, n):
    """从容器里扣掉 n 个某物品,返回实际扣掉的数量(交货类操作共用)。"""
    left = n
    for pl in list(container.items):
        if left <= 0:
            break
        if pl.item.iid != iid:
            continue
        take = min(left, pl.item.count)
        pl.item.count -= take
        left -= take
        if pl.item.count <= 0:
            container.remove_placed(pl)
    return n - left


def can_barter(sd, entry):
    return not missing_materials(sd, entry)


def barter(sd, entry):
    """交货:扣材料换物资(先克隆试算,任何一步失败都不动存档)。"""
    miss = missing_materials(sd, entry)
    if miss:
        lack = "、".join(f"{ITEMS[iid]['name']}×{n}" for iid, n in miss)
        return False, f"材料不够,还缺:{lack}"
    stash = Container.deserialize(sd.stash.w, sd.stash.h, sd.stash.serialize())
    bag = Container.deserialize(sd.bag.w, sd.bag.h, sd.bag.serialize())
    # 先试输出,放不下就别扣材料
    outs = []
    for iid, n in entry["out"]:
        it = Item(iid, count=int(n))
        if not stash.add_item(it):
            return False, f"仓库放不下 {ITEMS[iid]['name']},先清点空间"
        outs.append(iid)
    # 再从仓库/背包扣材料
    for iid, n in entry["need"]:
        left = n - consume(stash, iid, n)
        if left > 0:
            consume(bag, iid, left)
    sd.stash, sd.bag = stash, bag
    return True, f"交货完成:交出 {need_text(entry)},拿到 {out_text(entry)}"
