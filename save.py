# -*- coding: utf-8 -*-
"""存档:JSON 持久化(Windows 用 %LOCALAPPDATA%,安卓用应用私有目录,网页版用虚拟盘)。"""
import json
import os
import shutil
import sys
import time

from settings import STASH_W, STASH_H, BAG_W, BAG_H, SAFE_BASE
from inventory import Container, Item


def _writable(d):
    """这个目录能不能**真的写文件**(存在 ≠ 可写 —— 这正是"登录闪退"的根因)。"""
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".t2d_write_test")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("x")
        try:
            os.remove(probe)
        except OSError:
            pass
        return True
    except Exception:
        return False


def _app_dir():
    """EXE(或脚本)所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _migrate_accounts(first, cand):
    """便携回退时:把首选目录里已有的账号表和存档**拷**一份过来(只补缺,不覆盖)。

    否则玩家换到便携目录会看到"一个账号都没有",以为进度没了。
    """
    try:
        src_accounts = os.path.join(first, "accounts")
        if not os.path.exists(os.path.join(src_accounts, "index.json")):
            return
        dst_accounts = os.path.join(cand, "accounts")
        if not os.path.exists(os.path.join(dst_accounts, "index.json")):
            shutil.copytree(src_accounts, dst_accounts)
        for name in ("save.json", "save.json.bak", "legacy_imported"):
            src = os.path.join(first, name)
            dst = os.path.join(cand, name)
            if os.path.exists(src) and not os.path.exists(dst):
                shutil.copy2(src, dst)
    except Exception:
        pass


def _default_dir():
    """按平台选择**可写**的存档目录。

    首选 %LOCALAPPDATA%\\Tarkov2D。如果它不可写(权限受限的运行环境、被安全
    软件盯着、目录被锁……),就退到 EXE 旁边的 Tarkov2D-save(便携模式),并把
    原来的账号/存档一起带过去。
    **绝不能因为"选不出能写的目录"就让游戏在登录那一步崩掉。**
    """
    if sys.platform == "emscripten":
        return os.environ.get("PYGBAG_SAVE_DIR") or "."
    android = os.environ.get("ANDROID_PRIVATE")
    if android:
        return os.path.join(android, "Tarkov2D")
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    first = os.path.join(base, "Tarkov2D")
    if _writable(first):
        return first
    for cand in (os.path.join(_app_dir(), "Tarkov2D-save"),
                 os.path.join(os.getcwd(), "Tarkov2D-save")):
        if _writable(cand):
            _migrate_accounts(first, cand)
            try:
                with open(os.path.join(cand, "PORTABLE.txt"), "w",
                          encoding="utf-8") as f:
                    f.write("首选存档目录不可写,已改用便携存档目录。\n")
                    f.write("  首选: %s\n" % first)
                    f.write("  现用: %s\n" % cand)
                    f.write("(把游戏放到有写权限的目录,或用正常方式双击运行,"
                            "就会回到首选目录)\n")
            except Exception:
                pass
            return cand
    return first


SAVE_DIR = _default_dir()
SAVE_FILE = os.path.join(SAVE_DIR, "save.json")

# 当前登录的账号目录名(None = 还没登录/单档)。多账号见 accounts.py:
# 每个账号一份 <SAVE_DIR>/accounts/<名字>/save.json,切账号就是换 SAVE_FILE。
PROFILE = None


def use_profile(slug=None):
    """把存档文件切到某个账号(名字为空 = 回到 <SAVE_DIR>/save.json)。"""
    global SAVE_FILE, PROFILE
    if not slug:
        PROFILE = None
        SAVE_FILE = os.path.join(SAVE_DIR, "save.json")
        return SAVE_FILE
    d = os.path.join(SAVE_DIR, "accounts", str(slug))
    os.makedirs(d, exist_ok=True)
    PROFILE = str(slug)
    SAVE_FILE = os.path.join(d, "save.json")
    return SAVE_FILE


class SaveData:
    def __init__(self):
        self.stash = Container(STASH_W, STASH_H)
        self.bag = Container(BAG_W, BAG_H)   # 容量由装备的背包决定
        # 保险箱:贴身安全格(阵亡不丢);默认 2 格,40 个承包商任务全完成升 4 格
        self.safe = Container(SAFE_BASE[0], SAFE_BASE[1])
        self.weapon = None   # Item 或 None(出战武器槽)
        self.armor = None    # Item 或 None(出战护甲槽)
        self.helmet = None   # Item 或 None(出战头盔槽:夜视头盔)
        self.pack = None     # Item 或 None(出战背包,决定 bag 格子容量)
        self.difficulty = "lockdown"   # easy / lockdown / hardened
        self.map_key = "border"        # 出战地图(border / tv / port / indoor / base)
        self.mode = "raid"             # raid 搜打撤 / hostage 人质解救 / assault 突袭
        self.coop = False              # 双人合作(同一台电脑两人玩,只对搜打撤生效)
        self.touch = False             # 手机(触屏)模式:虚拟摇杆 + 按钮 + 自动锁敌
        self.seen_intro = False        # 是否看过玩法简介
        self.rubles = 20000  # 货币
        self.stats = {"raids": 0, "extracts": 0, "deaths": 0, "kills": 0, "value": 0}
        self.tasks = {}        # 教官任务进度:{task_id: 已累计数量}
        self.tasks_done = []   # 已领取的一次性任务 id(可重复任务不记这里)
        self.mystery = None    # 礼品-神秘人:本轮的收集清单/回合/机密文件(mystery.py)
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
        """阵亡:丢失带入战局的所有装备(含背包,退回口袋容量)。

        注意:保险箱(self.safe)是贴身安全格,【故意不算】—— 阵亡不丢。
        """
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
            "safe": self.safe.serialize(),
            "safe_w": self.safe.w,
            "safe_h": self.safe.h,
            "weapon": self.weapon.serialize() if self.weapon else None,
            "armor": self.armor.serialize() if self.armor else None,
            "helmet": self.helmet.serialize() if self.helmet else None,
            "pack": self.pack.serialize() if self.pack else None,
            "difficulty": self.difficulty,
            "map": self.map_key,
            "mode": self.mode,
            "coop": bool(self.coop),
            "touch": bool(self.touch),
            "seen_intro": bool(self.seen_intro),
            "rubles": int(self.rubles),
            "stats": dict(self.stats),
            "tasks": dict(self.tasks),
            "tasks_done": list(self.tasks_done),
            "mystery": self.mystery,
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
        # 保险箱:旧档没有这个字段 -> 给一个空的 2 格保险箱,不影响老玩家
        try:
            sw = int(data.get("safe_w", SAFE_BASE[0]) or SAFE_BASE[0])
            sh = int(data.get("safe_h", SAFE_BASE[1]) or SAFE_BASE[1])
        except (TypeError, ValueError):
            sw, sh = SAFE_BASE
        sd.safe = Container.deserialize(sw, sh, data.get("safe"), repair=True)
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
        sd.coop = bool(data.get("coop", False))
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
        # 承包商 40 项已完成但保险箱还是 2 格(旧档/异常)→ 自动升到 4 格
        from quests import check_safe_upgrade
        check_safe_upgrade(sd)
        mystery = data.get("mystery")
        # 清单条目在 mystery.need_list() 里还会再过一遍校验,这里只认 dict
        sd.mystery = mystery if isinstance(mystery, dict) else None
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


_backup_t = 0.0        # 上次滚动备份的时刻(进程内)

# 存档被覆盖(清档 / 出 bug / 手滑)时的最后一道保险:每个进程第一次写盘前、
# 以及之后每 10 分钟,把上一次的存档留一份 save.json.bak —— 至少能退回
# "这次启动之前"的状态(比 save.json.broken-* 的"读到坏档才备份"更主动)。
BACKUP_INTERVAL = 600.0
BACKUP_KEEP = 30       # 滚动备份最多留几份(≈最近 30 个备份点)


def _backup_dir():
    d = os.path.join(os.path.dirname(SAVE_FILE) or ".", "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _prune_backups(d, keep=BACKUP_KEEP):
    """只保留最近 keep 份滚动备份(按修改时间)。"""
    try:
        files = [f for f in os.listdir(d) if f.endswith(".json")]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(d, f)))
        for f in files[:-keep]:
            try:
                os.remove(os.path.join(d, f))
            except OSError:
                pass
    except OSError:
        pass


def backup_due(force=False):
    global _backup_t
    now = time.time()
    if not force and _backup_t and now - _backup_t < BACKUP_INTERVAL:
        return False
    if not os.path.exists(SAVE_FILE):
        return False        # 还没有旧档可备份(不占用 10 分钟时间窗)
    try:
        shutil.copy2(SAVE_FILE, SAVE_FILE + ".bak")
    except OSError:
        return False
    # 再留一份带时间戳的滚动备份(只保留最近 BACKUP_KEEP 份)。
    # 光有 save.json.bak 只能退回"上一次";仓库被清空/被 bug 吃掉时,
    # 需要能翻回任意一个历史时间点 —— 这就是那道保险。
    try:
        d = _backup_dir()
        dst = os.path.join(d, "save-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
        if not os.path.exists(dst):
            shutil.copy2(SAVE_FILE, dst)
        _prune_backups(d)
    except OSError:
        pass
    _backup_t = now
    return True


def save_data(sd):
    """写存档。**失败返回 False,绝不抛异常** —— 存档目录不可写时也要让游戏能跑,
    不能像旧版那样在登录那一步直接把窗口搞闪退。"""
    try:
        os.makedirs(SAVE_DIR, exist_ok=True)
        backup_due()
        tmp = SAVE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sd.serialize(), f, ensure_ascii=False)
        os.replace(tmp, SAVE_FILE)
        return True
    except OSError:
        try:
            import traceback
            with open(os.path.join(_app_dir(), "save_error.log"), "a",
                      encoding="utf-8") as f:
                f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {SAVE_FILE}\n")
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        return False


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
