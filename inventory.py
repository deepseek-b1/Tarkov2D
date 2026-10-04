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
                # 越界格直接忽略:个别数据异常不该把整局游戏打崩
                if 0 <= cx < self.w and 0 <= cy < self.h:
                    grid[cy][cx] = True
        return grid

    def out_of_bounds(self):
        """列出放不进当前容器的物品(自检/修复用)。"""
        bad = []
        for p in self.items:
            w, h = p.item.size()
            if p.x < 0 or p.y < 0 or p.x + w > self.w or p.y + h > self.h:
                bad.append(p)
        return bad

    def repair_layout(self):
        """把越界/重叠的物品挪到空位,尽量保住玩家的东西。

        用于读档时拯救异常状态(例如背包卷起/展开出错留下的越界物品):
        能放下的都留下并挪好,实在放不下的才丢弃。返回是否全部安置好。
        无论如何,调用后容器一定是合法状态(不会留越界物品)。
        """
        grid = [[False] * self.w for _ in range(self.h)]
        keep, need = [], []
        for p in self.items:
            w, h = p.item.size()
            if (0 <= p.x and 0 <= p.y and p.x + w <= self.w and p.y + h <= self.h
                    and _rect_free(grid, p.x, p.y, w, h)):
                _fill_rect(grid, p.x, p.y, w, h)
                keep.append(p)
            else:
                need.append(p.item)
        all_ok = True
        for it in need:
            bw, bh = it.base_size()
            rots = [it.rot] if bw == bh else [it.rot, not it.rot]
            done = False
            for rot in rots:
                iw, ih = (bh, bw) if rot else (bw, bh)
                if iw > self.w or ih > self.h:
                    continue
                for y in range(self.h - ih + 1):
                    for x in range(self.w - iw + 1):
                        if _rect_free(grid, x, y, iw, ih):
                            it.rot = rot
                            _fill_rect(grid, x, y, iw, ih)
                            keep.append(Placed(it, x, y))
                            done = True
                            break
                    if done:
                        break
                if done:
                    break
            if not done:
                all_ok = False
        self.items = keep
        return all_ok

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
        budget = 200000 // max(1, bw) // max(1, bh)     # 迭代上限,防病态数据卡死
        for rot in rots:
            w, h = (bh, bw) if rot else (bw, bh)
            if w <= 0 or h <= 0 or w > self.w or h > self.h:
                continue                       # 放不进去的朝向直接跳过
            grid = self.occupied()
            for y in range(self.h - h + 1):
                for x in range(self.w - w + 1):
                    ok = True
                    for cy in range(y, y + h):
                        for cx in range(x, x + w):
                            budget -= 1
                            if budget <= 0:
                                # 病态数据(尺寸/容器不对劲)只当作"放不下",
                                # 绝不能在这里死循环 —— 卡死比失败更糟
                                return None
                            if grid[cy][cx]:
                                ok = False
                                break
                        if not ok:
                            break
                    if ok:
                        return x, y, rot
        return None

    def at(self, gx, gy):
        if gx < 0 or gy < 0 or gx >= self.w or gy >= self.h:
            return None
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
    def deserialize(w, h, data, repair=False):
        """校验每条记录(坐标/尺寸/iid/重叠),非法条目直接丢弃,
        防止旧档或损坏档在游戏内崩溃或静默回绕。

        repair=True 时(玩家自己的仓库/背包读档):越界或重叠的物品不丢,
        而是就近挪到空位(挪不下才丢),尽量保住玩家的东西。
        """
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
                    if repair and not c._place_anywhere(it):
                        continue
                    continue
                # 与已存在的物品重叠则丢弃(repair 时改为另找位置)
                clash = False
                for p in c.items:
                    for cx, cy in p.cells():
                        if x <= cx < x + iw and y <= cy < y + ih:
                            clash = True
                            break
                    if clash:
                        break
                if clash:
                    if repair:
                        c._place_anywhere(it)
                    continue
                c.items.append(Placed(it, x, y))
            except Exception:
                continue
        return c

    def _place_anywhere(self, item):
        """把物品塞进任意空位(找不到就返回 False,不修改容器)。"""
        pos = self.find_space(item)
        if pos is None:
            return False
        item.rot = pos[2]
        self.items.append(Placed(item, pos[0], pos[1]))
        return True


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


# ---------- 一键整理 ----------
# 分区顺序:枪 / 甲 / 配件 / 背包 / 子弹 / 药 / 杂物 / 值钱货
CATEGORY_ORDER = ("weapon", "armor", "attach", "pack", "ammo", "med", "misc",
                  "valuable")


def merge_stacks(items):
    """把容器里的可堆叠物(子弹等)合并成满组,总数不变。"""
    out, groups = [], {}
    for it in items:
        if it.is_stackable():
            groups.setdefault(it.iid, []).append(it)
        else:
            out.append(it)
    for iid, plist in groups.items():
        maxs = max(1, plist[0].max_stack())
        total = sum(p.count for p in plist)
        while total > 0:
            take = min(maxs, total)
            out.append(Item(iid, count=take))
            total -= take
    return out


def _rect_free(occ, x, y, w, h):
    for yy in range(y, y + h):
        row = occ[yy]
        for xx in range(x, x + w):
            if row[xx]:
                return False
    return True


def _fill_rect(occ, x, y, w, h, val=True):
    for yy in range(y, y + h):
        row = occ[yy]
        for xx in range(x, x + w):
            row[xx] = val


def _pack_items(w, h, items):
    """把 items 按顺序紧凑摆放(行优先、不回退到更早的行)。

    用一张本地布尔网格试算(比反复用 Container.occupied() 快几十倍,
    仓库装满 200 件时也不会卡)。返回 ([(item, x, y)], 放不下的)。
    """
    occ = [[False] * w for _ in range(h)]
    out, overflow = [], []
    start_x, start_y = 0, 0
    for it in items:
        bw, bh = it.base_size()
        rots = [it.rot] if bw == bh else [it.rot, not it.rot]
        found = None
        for rot in rots:
            iw, ih = (bh, bw) if rot else (bw, bh)
            if iw > w or ih > h:
                continue
            for y in range(start_y, h - ih + 1):
                x0 = start_x if y == start_y else 0
                for x in range(x0, w - iw + 1):
                    if _rect_free(occ, x, y, iw, ih):
                        found = (x, y, rot, iw, ih)
                        break
                if found is not None:
                    break
            if found is not None:
                break
        if found is None:
            overflow.append(it)
            continue
        x, y, rot, iw, ih = found
        it.rot = rot
        _fill_rect(occ, x, y, iw, ih)
        out.append((it, x, y))
        start_x, start_y = x + iw, y
    return out, overflow


def organize(container, merge=True):
    """一键整理容器:合并同类堆叠 -> 卷起背包 -> 按类别分片摆放。

    成功后容器内容就地更新并返回 (True, []);
    有东西实在放不下时【不改动容器】,返回 (False, [放不下的物品])。
    """
    items = [p.item for p in container.items]
    if merge:
        items = merge_stacks(items)
    for it in items:
        if it.cat == "pack":
            it.state["rolled"] = True      # 能卷起来的背包一律卷起来
    order = {k: i for i, k in enumerate(CATEGORY_ORDER)}

    def key(it):
        d = it.def_
        ci = order.get(d.get("cat"), len(CATEGORY_ORDER))
        same_zone = it.iid if d.get("cat") == "ammo" else ""
        return (ci, same_zone, -d.get("height", d["h"]), -d["w"] * d["h"],
                -d.get("price", 0), d["name"])

    items.sort(key=key)
    placed, overflow = _pack_items(container.w, container.h, items)
    packed = Container(container.w, container.h)
    packed.items = [Placed(it, x, y) for it, x, y in placed]
    if overflow:
        # 落单的塞进剩下的空隙(不挑位置);还塞不下就整体放弃
        still = [it for it in overflow if not packed.add_item(it)]
        if still:
            return False, still
    container.items = packed.items
    return True, []


def zone_of(iid):
    """物品属于哪个分区(整理按钮提示用)。"""
    from settings import ITEMS
    cat = ITEMS[iid].get("cat")
    return CATEGORY_ORDER.index(cat) if cat in CATEGORY_ORDER else len(CATEGORY_ORDER)
