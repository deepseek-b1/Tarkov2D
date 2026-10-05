# -*- coding: utf-8 -*-
"""存档:JSON 持久化(Windows 用 %LOCALAPPDATA%,安卓用应用私有目录,网页版用虚拟盘)。"""
import json
import os
import sys
import time

from settings import STASH_W, STASH_H, BAG_W, BAG_H
from inventory import Container, Item


def _default_dir():
    """按平台选择可写的存档目录。"""
    if sys.platform == "emscripten":
        return os.environ.get("PYGBAG_SAVE_DIR") or "."
    android = os.environ.get("ANDROID_PRIVATE")
    if android:
        return os.path.join(android, "Tarkov2D")
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(base, "Tarkov2D")


SAVE_DIR = _default_dir()
SAVE_FILE = os.path.join(SAVE_DIR, "save.json")


class SaveData:
    def __init__(self):
        self.stash = Container(STASH_W, STASH_H)
        self.bag = Container(BAG_W, BAG_H)   # 容量由装备的背包决定
        self.weapon = None   # Item 或 None(出战武器槽)
        self.armor = None    # Item 或 None(出战护甲槽)
        self.helmet = None   # Item 或 None(出战头盔槽:夜视头盔)
        self.pack = None     # Item 或 None(出战背包,决定 bag 格子容量)
        self.difficulty = "lockdown"   # easy / lockdown / hardened
        self.map_key = "border"        # 出战地图(border / tv / port / indoor / base)
        self.mode = "raid"             # raid 搜打撤 / hostage 人质解救 / assault 突袭
        self.touch = False             # 手机(触屏)模式:虚拟摇杆 + 按钮 + 自动锁敌
        self.seen_intro = False        # 是否看过玩法简介
        self.rubles = 20000  # 货币
        self.stats = {"raids": 0, "extracts": 0, "deaths": 0, "kills": 0, "value": 0}
        self.tasks = {}        # 教官任务进度:{task_id: 已累计数量}
        self.tasks_done = []   # 已领取的一次性任务 id(可重复任务不记这里)
        self.story = None      # 剧情模式《灰区二日》进度(story.py 维护)
        # ---- 设置(bindings.py / touch.py / main.py 用) ----
        self.bindings = {}        # 键位覆盖:{action: [键码]}(只记玩家改过的)
        self.touch_layout = {}    # 触屏按键位置覆盖:{name: [rx, ry, r]}
        self.fps_cap = 120        # 帧率上限(0 = 不限)
        self.show_fps = True      # 画面右上角显示帧率
        self.scale_filter = "linear"   # 全屏缩放滤镜:linear 柔和 / nearest 锐利

    def apply_pack(self):
        """按当前背包调整出战背包容量(先尽量扩容,收窄时放不下的退回仓库)。"""
        from settings import pack_grid, POCKETS
        gw, gh = pack_grid(self.pack.iid) if self.pack else POCKETS
        if (self.bag.w, self.bag.h) == (gw, gh):
            return True
        new, overflow = self.bag.resized(gw, gh)
        for it in overflow:
            if not self.stash.add_item(it):
                return False   # 仓库也塞不下:放弃收窄(保留原容量,不丢东西)
        self.bag = new
        return True

    def default_fill(self):
        """新玩家初始配置:手枪 + 中型背包 + 少量物资;仓库有一点家底。"""
        self.pack = Item("pack_mid")
        self.bag = Container(6, 4)
        self.weapon = Item.weapon("pm", mag=8)
        self.bag.add_item(Item("a9", count=30))
        self.bag.add_item(Item("bandage", count=1))
        self.stash.add_item(Item.weapon("mp5", mag=30))
        self.stash.add_item(Item("a9", count=30))
        self.stash.add_item(Item("medkit", count=1))
        self.stash.add_item(Item("gold", count=1))
        self.stash.add_item(Item("paca", count=1))
        self.stash.add_item(Item("pack_large", count=1))   # 一个扩容目标

    def any_weapon(self):
        if self.weapon:
            return True
        for p in self.stash.items:
            if p.item.cat == "weapon":
                return True
        for p in self.bag.items:
            if p.item.cat == "weapon":
                return True
        return False

    def wipe_loadout(self):
        """阵亡:丢失带入战局的所有装备(含背包,退回口袋容量)。"""
        self.weapon = None
        self.armor = None
        self.helmet = None
        self.pack = None
        self.bag = Container(BAG_W, BAG_H)

    # ---- 序列化 ----
    def serialize(self):
        return {
            "v": 1,
            "stash": self.stash.serialize(),
            "bag": self.bag.serialize(),
            "bag_w": self.bag.w,
            "bag_h": self.bag.h,
            "weapon": self.weapon.serialize() if self.weapon else None,
            "armor": self.armor.serialize() if self.armor else None,
            "helmet": self.helmet.serialize() if self.helmet else None,
            "pack": self.pack.serialize() if self.pack else None,
            "difficulty": self.difficulty,
            "map": self.map_key,
            "mode": self.mode,
            "touch": bool(self.touch),
            "seen_intro": bool(self.seen_intro),
            "rubles": int(self.rubles),
            "stats": dict(self.stats),
            "tasks": dict(self.tasks),
            "tasks_done": list(self.tasks_done),
            "story": self.story,
            "bindings": dict(self.bindings),
            "touch_layout": {k: list(v) for k, v in self.touch_layout.items()},
            "fps_cap": int(self.fps_cap),
            "show_fps": bool(self.show_fps),
            "scale_filter": str(self.scale_filter),
        }

    @staticmethod
    def deserialize(data):
        sd = SaveData()
        # repair=True:玩家自己的仓库/背包读档时,越界/重叠的物品挪到空位而不是丢掉
        sd.stash = Container.deserialize(STASH_W, STASH_H, data.get("stash"),
                                         repair=True)
        # 存了容器尺寸(新档)就按存的来,否则旧档按 6×4 兼容
        try:
            bw = int(data.get("bag_w", 6) or 6)
            bh = int(data.get("bag_h", 4) or 4)
        except (TypeError, ValueError):
            bw, bh = 6, 4
        sd.bag = Container.deserialize(bw, bh, data.get("bag"), repair=True)
        if data.get("weapon"):
            sd.weapon = Item.from_dict(data["weapon"])
        if data.get("armor"):
            sd.armor = Item.from_dict(data["armor"])
        if data.get("helmet"):
            sd.helmet = Item.from_dict(data["helmet"])
        if "pack" in data:
            if data.get("pack"):
                sd.pack = Item.from_dict(data["pack"])
        else:
            # 旧档没有背包字段:补发中型背包(保持 6×4 体验不变)
            sd.pack = Item("pack_mid")
        sd.apply_pack()
        from settings import DIFFICULTIES, MAPS, MODES
        if data.get("difficulty") in DIFFICULTIES:
            sd.difficulty = data["difficulty"]
        if data.get("map") in MAPS:
            sd.map_key = data["map"]
        if data.get("mode") in MODES:
            sd.mode = data["mode"]
        sd.touch = bool(data.get("touch", False))
        sd.seen_intro = bool(data.get("seen_intro", False))
        try:
            sd.rubles = max(0, int(data.get("rubles", 20000)))
        except (TypeError, ValueError):
            sd.rubles = 20000
        sd.stats.update(data.get("stats") or {})
        tasks = data.get("tasks") or {}
        sd.tasks = {k: int(v) for k, v in tasks.items()
                    if isinstance(v, (int, float))}
        done = data.get("tasks_done") or []
        sd.tasks_done = [str(t) for t in done]
        story = data.get("story")
        sd.story = story if isinstance(story, dict) else None
        # 设置:键位覆盖 / 触屏布局 / 帧率 / FPS 显示 / 缩放滤镜(全部带校验)
        bind = data.get("bindings") or {}
        sd.bindings = {}
        for k, v in bind.items():
            if isinstance(k, str) and isinstance(v, (list, tuple)) and v:
                try:
                    sd.bindings[k] = [int(x) for x in v]
                except (TypeError, ValueError):
                    pass
        tl = data.get("touch_layout") or {}
        sd.touch_layout = {}
        for k, v in tl.items():
            if isinstance(k, str) and isinstance(v, (list, tuple)) and len(v) == 3:
                try:
                    sd.touch_layout[k] = [float(v[0]), float(v[1]), int(v[2])]
                except (TypeError, ValueError):
                    pass
        try:
            sd.fps_cap = int(data.get("fps_cap", 120))
        except (TypeError, ValueError):
            sd.fps_cap = 120
        if sd.fps_cap < 0:
            sd.fps_cap = 0
        sd.show_fps = bool(data.get("show_fps", True))
        sf = str(data.get("scale_filter", "linear"))
        sd.scale_filter = sf if sf in ("linear", "nearest") else "linear"
        return sd


def save_data(sd):
    os.makedirs(SAVE_DIR, exist_ok=True)
    tmp = SAVE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(sd.serialize(), f, ensure_ascii=False)
    os.replace(tmp, SAVE_FILE)


def load_data():
    if not os.path.exists(SAVE_FILE):
        sd = SaveData()
        sd.default_fill()
        return sd
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return SaveData.deserialize(data)
    except Exception:
        # 损坏存档备份后重置
        try:
            os.replace(SAVE_FILE, SAVE_FILE + ".broken-" + str(int(time.time())))
        except OSError:
            pass
        sd = SaveData()
        sd.default_fill()
        return sd


def reset_data():
    sd = SaveData()
    sd.default_fill()
    save_data(sd)
    return sd
