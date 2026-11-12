# -*- coding: utf-8 -*-
"""等级与经验:每升一级都有一份独立奖励,而不是只在几个固定阶段发奖。

和合并版的区别(用户要求):
    合并版是「到几个阶段(比如 10/25/50 级)领一次大奖」;
    这里改成 **每一级都有自己的一份奖励**,从 1 级到 150 级都能逐级领。

经验来源:
    击杀守军(按难度)× 每杀经验;撤离成功按带出物资的净值折算。
"""
import settings

MAX_LEVEL = 150

# 经验
XP_PER_KILL = 25           # 每击杀一名守军
XP_PER_VALUE = 4000        # 每 4000 卢布净收益折 1 点经验
XP_EXTRACT_BONUS = 60      # 撤离成功额外奖励(鼓励活着出来)


def xp_to_next(level):
    """从 level 升到 level+1 需要多少经验(Lv150 封顶返回 0)。"""
    level = max(1, int(level))
    if level >= MAX_LEVEL:
        return 0
    return 100 + level * 40


def level_of(xp):
    """总经验 -> 当前等级(1 级起步,封顶 MAX_LEVEL)。"""
    xp = max(0, int(xp or 0))
    level = 1
    rest = xp
    while level < MAX_LEVEL:
        need = xp_to_next(level)
        if rest < need:
            break
        rest -= need
        level += 1
    return level


def xp_into_level(xp):
    """当前等级内已获得的经验(0 ~ xp_to_next)。"""
    xp = max(0, int(xp or 0))
    level = 1
    rest = xp
    while level < MAX_LEVEL:
        need = xp_to_next(level)
        if rest < need:
            break
        rest -= need
        level += 1
    return rest


def total_xp_for_level(level):
    """升到该等级需要的累计经验(level=1 时为 0)。"""
    level = max(1, min(MAX_LEVEL, int(level)))
    return sum(xp_to_next(i) for i in range(1, level))


# ---------- 每一级的奖励 ----------
_KIT_BY_BAND = [
    (1, "kit_marksman"), (30, "kit_ak"), (60, "kit_assault"),
    (90, "kit_close"), (120, "kit_machine"),
]
_AMMO_BY_BAND = [
    (1, "a9"), (20, "a545"), (50, "a762x51"), (90, "m966"),
]
_MED_POOL = ["bandage", "medkit", "painkiller", "tourniquet", "syringe"]
_SPECIAL_BY_TIER = ["asval", "vector", "pkp", "rpg2"]


def _band(table, level, default):
    pick = default
    for start, iid in table:
        if level >= start:
            pick = iid
    return pick


def reward_of(level):
    """第 level 级那份奖励(每级都有,内容随等级递增)。"""
    level = max(1, min(MAX_LEVEL, int(level)))
    reward = {"rubles": 2000 + level * 1200}

    # 每级都给点弹药,按等级换口径
    ammo_id = _band(_AMMO_BY_BAND, level, "a9")
    stack = settings.ITEMS[ammo_id].get("stack", 30)
    reward["ammo"] = [(ammo_id, max(10, stack // 3))]

    # 每 3 级:一份医疗品
    if level % 3 == 0:
        reward.setdefault("items", []).append(
            (_MED_POOL[(level // 3) % len(_MED_POOL)], 1))

    # 每 5 级:一件护甲/头盔(按等级挑同级别的货)
    if level % 5 == 0:
        reward.setdefault("items", []).append((_armor_for_level(level), 1))

    # 每 10 级:一个全装包
    if level % 10 == 0:
        reward.setdefault("items", []).append(
            (_band(_KIT_BY_BAND, level, "kit_marksman"), 1))

    # 每 25 级:一把特种枪
    if level % 25 == 0:
        reward.setdefault("weapons", []).append(
            _SPECIAL_BY_TIER[min(len(_SPECIAL_BY_TIER) - 1, level // 25 - 1)])

    # 每 50 级:额外一大笔钱
    if level % 50 == 0:
        reward["rubles"] += 500000 * (level // 50)
    return reward


def _armor_for_level(level):
    """给一件和当前等级相称的护甲(取该等级里最便宜的,避免奖励强过头)。"""
    want = max(1, min(6, 1 + level // 25))
    pool = [iid for iid, d in settings.ITEMS.items()
            if d.get("cat") == "armor" and int(d.get("level", 0) or 0) == want]
    if not pool:
        pool = [iid for iid, d in settings.ITEMS.items()
                if d.get("cat") == "armor"]
    if not pool:
        return "paca"
    return min(pool, key=lambda i: settings.ITEMS[i]["price"])


def reward_text(level):
    """奖励的一句话描述(给手册行用)。"""
    r = reward_of(level)
    parts = [f"{int(r['rubles']):,} 卢布"]
    for iid, cnt in r.get("ammo", []):
        parts.append(f"{settings.ITEMS[iid]['name']} ×{cnt}")
    for iid, cnt in r.get("items", []):
        parts.append(settings.ITEMS[iid]["name"] + (f" ×{cnt}" if cnt > 1 else ""))
    for iid in r.get("weapons", []):
        parts.append(settings.ITEMS[iid]["name"])
    return " + ".join(parts)


# ---------- 存档交互 ----------
def current_level(sd):
    return level_of(getattr(sd, "xp", 0))


def claimed_levels(sd):
    return set(int(x) for x in (getattr(sd, "level_claimed", []) or []))


def is_claimed(sd, level):
    return int(level) in claimed_levels(sd)


def claimable(sd):
    """所有「已达成但还没领」的等级,从小到大。"""
    lv = current_level(sd)
    done = claimed_levels(sd)
    return [i for i in range(1, lv + 1) if i not in done]


def add_xp(sd, amount):
    """加经验;返回 (旧等级, 新等级)。不写盘,由调用方 save。"""
    amount = int(amount or 0)
    if amount <= 0:
        return current_level(sd), current_level(sd)
    old = current_level(sd)
    sd.xp = max(0, int(getattr(sd, "xp", 0)) + amount)
    return old, current_level(sd)


def claim(sd, level):
    """领取第 level 级的奖励。返回 (成功, 提示)。"""
    import quests
    level = int(level)
    if not (1 <= level <= MAX_LEVEL):
        return False, "等级超出范围"
    if level > current_level(sd):
        return False, f"还没到 {level} 级"
    if is_claimed(sd, level):
        return False, f"{level} 级奖励已领过"
    ok, why = quests.grant(sd, reward_of(level))
    if not ok:
        return False, why
    sd.level_claimed = sorted(claimed_levels(sd) | {level})
    return True, f"已领取 Lv.{level} 奖励:{reward_text(level)}"


def claim_all(sd):
    """一键领取所有可领的等级奖励。返回 (领取数, 提示)。"""
    todo = claimable(sd)
    if not todo:
        return 0, "没有可领的等级奖励"
    n = 0
    last = ""
    for lv in todo:
        ok, why = claim(sd, lv)
        if not ok:
            if n == 0:
                return 0, why
            break
        n += 1
        last = why
    return n, f"一键领取 {n} 级奖励(最后:{last})"


def xp_from_raid(kills, gained, extracted):
    """战局结算经验:击杀 + 撤离净值 + 撤离奖励。"""
    xp = int(kills) * XP_PER_KILL
    if extracted:
        xp += max(0, int(gained)) // XP_PER_VALUE + XP_EXTRACT_BONUS
    return int(xp)
