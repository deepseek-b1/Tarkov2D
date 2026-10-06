# -*- coding: utf-8 -*-
"""同机双人合作(同一台电脑、一个键盘两个人玩):第二位玩家 P2。

设计取舍(都写在游戏内「玩法简介」里):
* P2 只用键盘 —— 方向键移动 + 自动瞄准视野内最近的敌人,动作键开火/交互/换弹/打药;
  鼠标仍然只属于 P1,所以 P2 不打开背包/搜刮面板;
* P2 靠近箱子按交互 = 自动逐件搜出并收进自己背包(search 读条照旧,不跳过机制);
* 两位玩家都由系统配发装备(和突袭模式同一套回收机制):撤离时背包里的战利品
  并进仓库,阵亡只丢这一局 —— 账号里的仓库与出战配置永远不受影响。
"""
import random

from inventory import Container, Item
from settings import COOP, pack_grid


def keys():
    return COOP["keys"]


def p2_key_set():
    """P2 独占的按键集合(双人模式下 P1 要让出这些键,免得两人一起动)。"""
    out = set()
    for ks in COOP["keys"].values():
        out.update(ks)
    return out


_hint_cache = {}


def key_hint(short=False):
    """P2 操作提示(藏身处提示、开局 toast 用全版;局内 HUD 用短版省地方)。

    结果缓存 —— HUD 每帧都要它,而键位是固定的(改键只影响 P1)。
    """
    cached = _hint_cache.get(short)
    if cached is not None:
        return cached
    import bindings
    k = COOP["keys"]

    def lab(action, alt=False):
        joiner = "或" if alt else "/"
        return joiner.join(bindings.key_label(x) for x in k[action])

    move = "".join(bindings.key_label(x) for x in
                   (k["up"][0], k["left"][0], k["down"][0], k["right"][0]))
    if short:
        # 局内 HUD 的那一行:只写主键位(面板窄,别挡住中间的通知条)
        text = (f"P2:{move} 移动 · {bindings.key_label(k['fire'][0])} 开火 · "
                f"{bindings.key_label(k['interact'][0])} 交互 · "
                f"{bindings.key_label(k['reload'][0])} 换弹 · "
                f"{bindings.key_label(k['heal'][0])} 打药")
    else:
        text = (f"P2:{move} 移动 · {lab('fire')} 开火(自动瞄准) · "
                f"{lab('interact', True)} 交互/自动搜刮 · "
                f"{lab('reload', True)} 换弹 · {lab('heal', True)} 打药")
    _hint_cache[short] = text
    return text


class P2Kit:
    """P2 的随身装备:属性名和存档一样(weapon/armor/helmet/bag/safe),但不落盘。"""

    def __init__(self, rng=random):
        import assault
        weapon, armor, pack, items = assault.build(rng)
        self.weapon = weapon
        self.armor = armor
        self.helmet = None
        self.pack = pack
        self.bag = Container(*pack_grid(pack.iid))
        self.safe = Container(2, 1)      # P2 不用保险箱(占位,保持接口一致)
        for it in items:
            if not self.bag.add_item(it):
                break


def bag_value(kit):
    """P2 背包里东西的总价值(结算收益用)。"""
    return kit.bag.total_value() if kit is not None else 0


def bank_player(sd, raid, p):
    """把某位玩家这一局捡到的战利品并进仓库(配发装备不带走)。

    用 raid.loot_log(拾取时记 id,放回/丢弃会撤销)过滤,免得把系统配发的
    弹药药品也一起存进仓库;局内捡到并当场换上的枪/甲/头盔也算战利品。
    双人合作是**各自撤离**:谁撤出去就立刻结算他这一份(另一个继续打)。
    返回 (进仓库件数, 放不下件数)。
    """
    ids = {e.get("id") for e in getattr(raid, "loot_log", ())}
    kept = lost = 0
    for placed in list(p.bag.items):
        if id(placed.item) not in ids:
            continue
        if sd.stash.add_item(placed.item):
            p.bag.remove_placed(placed)
            kept += 1
        else:
            lost += 1
    # 局内捡到并换上的装备(不在背包里,直接算战利品)
    for slot in ("weapon", "armor", "helmet"):
        it = getattr(p, slot, None)
        if it is None or id(it) not in ids:
            continue
        if sd.stash.add_item(it):
            kept += 1
        else:
            lost += 1
        setattr(p, slot, None)
    return kept, lost
