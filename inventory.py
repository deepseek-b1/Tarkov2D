# -*- coding: utf-8 -*-
"""塔科夫式格子背包:物品占多格、可旋转自动放置、弹药堆叠。"""


class Item:
    __slots__ = ("iid", "count", "rot", "state")

    def __init__(self, iid, count=1, rot=False, state=None):
        self.iid = iid
        self.count = count
        self.rot = rot
        self.state = state if state is not None else {}

    @property
    def def_(self):
        from settings import ITEMS
        return ITEMS[self.iid]

    @property
    def name(self):
        return self.def_["name"]

    @property
    def price(self):
        return self.def_["price"]

    @property
    def cat(self):
        return self.def_["cat"]

    def is_rolled(self):
        """背包是否已卷起(卷起来占格变小,方便塞进仓库)。"""
        return bool(self.state.get("rolled"))

    def roll_size(self):
        """卷起后的占格:展开不超过 4×4 -> 1×2;5×5 及以上 -> 2×2。"""
        from settings import PACK_ROLL_SMALL, PACK_ROLL_BIG, PACK_ROLL_MAX_DIM
        d = self.def_
        if max(d["w"], d["h"]) <= PACK_ROLL_MAX_DIM:
            return PACK_ROLL_SMALL
        return PACK_ROLL_BIG

    def size(self):
        w, h = self.base_size()
        return (h, w) if self.rot else (w, h)

    def base_size(self):
        if self.cat == "pack" and self.is_rolled():
            return self.roll_size()
        d = self.def_
        return d["w"], d["h"]

    def is_stackable(self):
        return self.def_.get("stack", 1) > 1

    def max_stack(self):
        return self.def_.get("stack", 1)

    def total_price(self):
        return self.price * self.count

    def clone(self):
        return Item(self.iid, self.count, self.rot, dict(self.state))

    def serialize(self):
        return {"iid": self.iid, "count": self.count, "rot": bool(self.rot),
                "state": dict(self.state)}

    @staticmethod
    def from_dict(d):
        return Item(d["iid"], d.get("count", 1), bool(d.get("rot", False)),
                    dict(d.get("state") or {}))

    @staticmethod
    def weapon(iid, mag=None):
        """新建武器实例;mag 默认为满弹匣。"""
        it = Item(iid)
        cap = it.def_["mag"]
        it.state["mag"] = cap if mag is None else max(0, min(cap, int(mag)))
        return it


class Placed:
    __slots__ = ("item", "x", "y")

    def __init__(self, item, x, y):
        self.item = item
        self.x = x
        self.y = y

    def cells(self):
        w, h = self.item.size()
        for dy in range(h):
            for dx in range(w):
                yield self.x + dx, self.y + dy


class Container:
    """w×h 格子容器。items: [Placed]"""

    def __init__(self, w, h):
        self.w = w
        self.h = h
        self.items = []

    # ---- 查询 ----
    def occupied(self):
        grid = [[False] * self.w for _ in range(self.h)]
        for p in self.items:
            for cx, cy in p.cells():
                grid[cy][cx] = True
        return grid

    def fits(self, item, x, y, rot=None):
        w, h = item.size() if rot is None else item.base_size() if not rot else \
            (item.base_size()[1], item.base_size()[0])
        if x < 0 or y < 0 or x + w > self.w or y + h > self.h:
            return False
        grid = self.occupied()
        for cy in range(y, y + h):
            for cx in range(x, x + w):
                if grid[cy][cx]:
                    return False
        return True

    def find_space(self, item):
        """自动寻找空位,自动尝试两种朝向(优先原始朝向)。返回 (x, y, rot) 或 None。"""
        bw, bh = item.base_size()
        rots = [False, True] if (bw != bh or item.rot) else [False]
        if item.rot and bw != bh:
            rots = [True, False]
        for rot in rots:
            w, h = (bh, bw) if rot else (bw, bh)
            grid = self.occupied()
            for y in range(self.h - h + 1):
                for x in range(self.w - w + 1):
                    ok = True
                    for cy in range(y, y + h):
                        for cx in range(x, x + w):
                            if grid[cy][cx]:
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        return x, y, rot
        return None

    def at(self, gx, gy):
        for p in self.items:
            if p.x <= gx < p.x + p.item.size()[0] and p.y <= gy < p.y + p.item.size()[1]:
                return p
        return None

    def can_fit(self, item):
        """物品能否放入(含堆叠合并可能)。"""
        if item.is_stackable():
            for p in self.items:
                if p.item.iid == item.iid and p.item.count < p.item.max_stack():
                    return True
        return self.find_space(item) is not None

    def total_value(self):
        return sum(p.item.total_price() for p in self.items)

    def item_count(self):
        return sum(p.item.count for p in self.items)

    def resized(self, w, h):
        """尝试改尺寸(背包扩容/收窄)。返回 (新容器, 放不下的物品列表)。
        物品尽量保留原坐标与原朝向;不修改自身。"""
        new = Container(w, h)
        overflow = []
        for p in self.items:
            it = p.item
            iw, ih = it.size()
            if p.x + iw <= w and p.y + ih <= h and new.fits(it, p.x, p.y):
                new.items.append(Placed(it, p.x, p.y))
                continue
            pos = new.find_space(it)
            if pos is not None:
                it.rot = pos[2]
                new.items.append(Placed(it, pos[0], pos[1]))
            else:
                overflow.append(it)
        return new, overflow

    # ---- 修改 ----
    def add_item(self, item):
        """自动放置(可堆叠先尝试合并)。
        成功返回 True;失败返回 False 且【不修改】物品与容器。"""
        orig_count = item.count
        if item.is_stackable():
            remaining = orig_count
            touched = []
            for p in self.items:
                if remaining <= 0:
                    break
                if p.item.iid == item.iid and p.item.count < p.item.max_stack():
                    room = p.item.max_stack() - p.item.count
                    take = min(room, remaining)
                    p.item.count += take
                    remaining -= take
                    touched.append((p, take))
            if remaining <= 0:
                return True
            item.count = remaining
            pos = self.find_space(item)
            if pos is not None:
                item.rot = pos[2]
                self.items.append(Placed(item, pos[0], pos[1]))
                return True
            # 放不下:回滚已合并的部分,保持物品原样
            for p, take in touched:
                p.item.count -= take
            item.count = orig_count
            return False
        pos = self.find_space(item)
        if pos is None:
            return False
        item.rot = pos[2]
        self.items.append(Placed(item, pos[0], pos[1]))
        return True

    def place_at(self, item, x, y, rot=None):
        if not self.fits(item, x, y, rot):
            return False
        if rot is not None:
            item.rot = rot
        self.items.append(Placed(item, x, y))
        return True

    def remove_placed(self, placed):
        if placed in self.items:
            self.items.remove(placed)
            return True
        return False

    def take_placed(self, placed):
        self.remove_placed(placed)
        return placed.item

    def clear(self):
        self.items.clear()

    def first_of_cat(self, cat):
        for p in self.items:
            if p.item.cat == cat:
                return p
        return None

    # ---- 序列化 ----
    def serialize(self):
        return [dict(x=p.x, y=p.y, **p.item.serialize()) for p in self.items]

    @staticmethod
    def deserialize(w, h, data):
        """校验每条记录(坐标/尺寸/iid/重叠),非法条目直接丢弃,
        防止旧档或损坏档在游戏内崩溃或静默回绕。"""
        from settings import ITEMS
        c = Container(w, h)
        for d in data or []:
            try:
                it = Item.from_dict(d)
                if it.iid not in ITEMS or it.count < 1:
                    continue
                x, y = int(d["x"]), int(d["y"])
                iw, ih = it.size()
                if x < 0 or y < 0 or x + iw > w or y + ih > h:
                    continue
                # 与已存在的物品重叠则丢弃
                clash = False
                for p in c.items:
                    for cx, cy in p.cells():
                        if x <= cx < x + iw and y <= cy < y + ih:
                            clash = True
                            break
                    if clash:
                        break
                if clash:
                    continue
                c.items.append(Placed(it, x, y))
            except Exception:
                continue
        return c


def try_move(src, placed, dst):
    """把 src 中的物品移入 dst(自动旋转、跨容器堆叠)。
    返回 True 表示全部或部分成功。"""
    it = placed.item
    start_count = it.count

    if it.is_stackable() and it.count > 0:
        remaining = it.count
        for p in list(dst.items):
            if p.item.iid == it.iid and p.item.count < p.item.max_stack():
                room = p.item.max_stack() - p.item.count
                take = min(room, remaining)
                p.item.count += take
                remaining -= take
                if remaining <= 0:
                    break
        if remaining <= 0:
            src.remove_placed(placed)
            return True
        if remaining < it.count:
            it.count = remaining
            pos = dst.find_space(it)
            if pos is None:
                return True  # 部分已堆叠成功,剩余留在原地
            it.rot = pos[2]
            src.remove_placed(placed)
            dst.items.append(Placed(it, pos[0], pos[1]))
            return True

    pos = dst.find_space(it)
    if pos is None:
        return False
    it.rot = pos[2]
    src.remove_placed(placed)
    dst.items.append(Placed(it, pos[0], pos[1]))
    return True
