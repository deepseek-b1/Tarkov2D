# -*- coding: utf-8 -*-
"""Tarkov2D 全局配置:常量、物品定义、地图、拾荒者定义。"""
import pygame

# ---------- 版本与更新 ----------
GAME_VERSION = "2.8.0"
# 更新清单地址(可换成自建服务器 / GitHub raw;留空则只认 EXE 同目录的 version.json)
UPDATE_MANIFEST_URL = "http://127.0.0.1:8765/version.json"
UPDATE_TIMEOUT = 3   # 检查 / 下载超时(秒)

# ---------- 基础常量 ----------
W, H = 1280, 720
FPS = 60
# 帧率上限可选项(设置页循环切换;0 = 不限)。游戏实际用存档里的 fps_cap。
FPS_CAP_CHOICES = [60, 90, 120, 0]
TILE = 32
# 战争迷雾/可见性缓存(性能关键,见 raid.refresh_fog):
# 玩家移动超过 FOG_MOVE_STEP 像素才重算视野多边形;
# 可见敌人集合最短每 FOG_VIS_REFRESH 秒刷一次(兜住敌人自己走动);
# 集合计算半径 FOG_VIS_RADIUS 要大于最大视距(620)。
FOG_MOVE_STEP = 6.0
FOG_VIS_REFRESH = 0.10
FOG_VIS_RADIUS = 840
RAID_TIME = 12 * 60          # 战局时长(秒)
EXTRACT_TIME = 3.0           # 撤离引导(秒)
INTERACT_DIST = 56           # 搜刮交互距离(像素)
# 搜刮/打药读条(秒):以前是瞬发,现在要花时间
LOOT_TAKE_TIME = 1.0         # 搜刮单件的基础时间
LOOT_TAKE_PER_CELL = 0.16    # 每多占一格多花的时间(大件更慢)
LOOT_TAKE_MIN = 0.8
LOOT_TAKE_MAX = 2.6
HEAL_TIME = 1.6              # 打药基础时间
HEAL_TIME_PER_HP = 0.010     # 每点治疗量额外时间
HEAL_TIME_MIN = 1.0
HEAL_TIME_MAX = 3.0
STASH_W, STASH_H = 10, 20    # 藏身处仓库(格子多了,藏身处用滚轮上下翻)
STASH_VIEW_ROWS = 8          # 仓库面板一次能看到几行(其余靠滚轮)
BAG_W, BAG_H = 4, 2          # 无背包时的口袋容量(装备背包后按 grid 扩容)

PLAYER = dict(hp=100, speed=235, walk=115, radius=12)

# 动作对移动速度的影响(乘在基础速度上)
MOVE_AIM_MUL = 0.20          # 架枪/瞄准时只剩 20% 速度(减 80%)
MOVE_RELOAD_MUL = 0.40       # 换弹时 40% 速度(大幅减速)
# 换弹/架枪时完全不能动的枪:用同一个标记 braced_immobile(如 M139 机枪)

# ---------- 枪械分类(暗区式标注) ----------
WEAPON_CLASS = {
    "pm": "手枪",
    "mp5": "冲锋枪",
    "vector": "冲锋枪",
    "mp133": "霰弹枪",
    "ak74": "突击步枪",
    "akm": "突击步枪",
    "m4a1": "突击步枪",
    "asval": "特种步枪",
    "m700": "狙击步枪",
    "m139": "轻机枪",
    "pkp": "轻机枪",
    "rpg": "火箭筒",
    "rpg2": "火箭筒",
}
WEAPON_CLASS_COL = {
    "手枪": (196, 176, 120), "冲锋枪": (150, 200, 150), "霰弹枪": (200, 150, 110),
    "突击步枪": (150, 180, 230), "特种步枪": (180, 150, 220),
    "精确射手步枪": (200, 200, 150),
    "狙击步枪": (230, 190, 120), "轻机枪": (220, 130, 120),
    "火箭筒": (230, 110, 90),
}


def weapon_class(iid):
    """武器的分类名(和物品槽位 cat 不是一回事);非武器返回 None。"""
    return WEAPON_CLASS.get(iid)

COL = {
    "bg": (18, 20, 24),
    "panel": (38, 42, 50),
    "panel_hi": (52, 58, 68),
    "border": (90, 96, 108),
    "text": (222, 226, 232),
    "text_dim": (150, 156, 166),
    "hp": (200, 60, 60),
    "hp_bg": (60, 30, 30),
    "accent": (255, 176, 32),
    "good": (110, 200, 110),
    "bad": (220, 90, 80),
    "grid": (55, 60, 70),
    "grid_bg": (30, 33, 38),
    "fog": (8, 9, 12, 185),
    "ground": (66, 74, 62),
    "ground2": (58, 66, 55),
    "indoor": (88, 84, 78),
    "indoor2": (80, 76, 70),
    "wall": (42, 44, 50),
    "wall_edge": (70, 74, 84),
    "tree": (46, 92, 52),
    "crate": (146, 100, 52),
    "med": (206, 212, 216),
    "gun": (94, 116, 88),
    "safe": (120, 118, 126),
    "extract": (40, 170, 150),
    "player": (120, 190, 255),
    "scav": (200, 120, 70),
}

# ---------- 字体 ----------
_font_cache = {}


class _CachedFont(pygame.font.Font):
    """带 render 缓存的字体。

    HUD 每帧要画十几串文字,其中多数(标签、单位、快捷键、坐标)每帧都一样。
    pygame 的 font.render 每次都要重新光栅化字形,在手机上尤其贵,所以这里按
    (文字, 抗锯齿, 颜色, 底色) 记住已经渲染好的 Surface。

    只缓存「只读」表面是安全的:全工程没有对 render() 结果做原地修改的代码
    (没有 set_alpha / fill / PixelArray / subsurface 之类用法)。
    """

    _CACHE_MAX = 320      # 条数上限:超了整批清空(缓存本来就该整批失效)
    _CACHE_MAX_H = 96     # 过大的文字不缓存,免得白占内存

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._rcache = {}

    def render(self, text, antialias=True, color=(255, 255, 255), background=None):
        cache = self._rcache
        try:
            key = (text, antialias, color, background)
            hit = cache.get(key)
        except TypeError:          # color 传了 list 之类不可哈希的东西
            return super().render(text, antialias, color, background)
        if hit is not None:
            return hit
        surf = super().render(text, antialias, color, background)
        if surf.get_height() <= self._CACHE_MAX_H:
            if len(cache) >= self._CACHE_MAX:
                cache.clear()
            cache[key] = surf
        return surf


def _font_files():
    """可用字体:优先项目自带 fonts/ 目录(网页版必须),再找系统中文 TTF。"""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    paths = []
    for sub in (os.path.join(here, "fonts"), os.path.join(here, "..", "fonts")):
        try:
            for name in sorted(os.listdir(sub)):
                if name.lower().endswith((".ttf", ".otf", ".ttc")):
                    paths.append(os.path.join(sub, name))
        except Exception:
            pass
    paths += [r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyhbd.ttc",
              r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"]
    return paths


def get_font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        f = None
        for path in _font_files():
            try:
                f = _CachedFont(path, size)
                break
            except Exception:
                f = None
        if f is None:
            try:
                f = pygame.font.SysFont("microsoftyahei,microsoftyaheiui,simhei,dengxian",
                                        size, bold=bold)
            except Exception:
                f = None
        if f is None:
            f = _CachedFont(None, size)
        if bold:
            f.set_bold(True)
        _font_cache[key] = f
    return _font_cache[key]

def fmt_rub(n):
    return f"¥{int(n):,}"

# ---------- 物品定义 ----------
# cat: weapon/armor/med/ammo/valuable/misc/pack
# 武器:spread=腰射散布,spread_braced=长按右键架枪散布(狙击枪不参与架枪)
ITEMS = {
    "pm": dict(name="PM 手枪", cat="weapon", w=2, h=1, color=(185, 185, 195), price=8000,
               ammo="a9", dmg=14, pellets=1, spread=0.045, spread_braced=0.022,
               rof=0.26, auto=False, mag=8, range=680, loud=520, sfx="pm"),
    "mp5": dict(name="MP5 冲锋枪", cat="weapon", w=3, h=1, color=(86, 132, 78), price=28000,
                ammo="a9", dmg=12, pellets=1, spread=0.075, spread_braced=0.036,
                rof=0.105, auto=True, mag=30, range=760, loud=760, sfx="mp5"),
    "mp133": dict(name="MP-133 霰弹枪", cat="weapon", w=4, h=1, color=(152, 96, 52), price=22000,
                  ammo=["a12db", "a12ap"], dmg=9, pellets=7, spread=0.20,
                  spread_braced=0.115,
                  rof=0.95, auto=False, mag=4, range=430, loud=880, sfx="sg"),
    "ak74": dict(name="AK-74 突击步枪", cat="weapon", w=5, h=2, color=(124, 84, 58), price=52000,
                 ammo="a545", dmg=20, pellets=1, spread=0.095, spread_braced=0.045,
                 rof=0.115, auto=True, mag=30, range=900, loud=920, sfx="ar"),
    "a9": dict(name="9×19mm 子弹", cat="ammo", w=1, h=1, color=(232, 182, 62), price=60, stack=120),
    "a545": dict(name="5.45×39 穿甲弹", cat="ammo", w=1, h=1, color=(208, 66, 66),
                 price=120, stack=120, dmg_mul=1.30),
    "a12db": dict(name="12号龙息弹", cat="ammo", w=1, h=1, color=(226, 120, 40),
                  price=260, stack=40, pellets=6, dmg_mul=0.80, spread_add=0.06, burn=9),
    "a12ap": dict(name="12号穿甲独头弹", cat="ammo", w=1, h=1, color=(140, 160, 200),
                  price=420, stack=30, pellets=1, dmg_mul=5.00, spread_add=-0.14,
                  range_mul=1.25),
    "bandage": dict(name="绷带", cat="med", w=1, h=1, color=(238, 238, 238), price=1200, heal=20),
    "medkit": dict(name="军用医疗包", cat="med", w=2, h=1, color=(232, 74, 74), price=7500, heal=55),
    # 更多药品(价格 / 治疗量阶梯)
    "painkiller": dict(name="止痛药", cat="med", w=1, h=1, color=(226, 226, 236),
                       price=900, heal=15),
    "tourniquet": dict(name="止血带", cat="med", w=1, h=1, color=(198, 150, 150),
                       price=2600, heal=35),
    "syringe": dict(name="肾上腺素注射器", cat="med", w=1, h=1, color=(150, 210, 190),
                    price=4800, heal=45),
    "ai2": dict(name="AI-2 医疗包", cat="med", w=2, h=1, color=(236, 128, 96),
                price=12000, heal=100),
    "surgery": dict(name="外科手术包", cat="med", w=2, h=2, color=(240, 240, 248),
                    price=28000, heal=200),
    "paca": dict(name="PACA 软质背心", cat="armor", w=2, h=2, color=(96, 116, 146), price=26000,
                 reduce=0.28, slow=0.0, level=3),
    "fort": dict(name="6B43 重装背心", cat="armor", w=3, h=2, color=(74, 74, 86), price=68000,
                 reduce=0.45, slow=0.12, level=4),
    # 6级重甲:倒地自救(每局一次)
    "b45": dict(name="6B45 重装型防弹衣", cat="armor", w=3, h=2, color=(88, 90, 100), price=180000,
                reduce=0.97, slow=0.18, level=6, revive=True),
    "bt201": dict(name="BT201 全护甲防弹衣", cat="armor", w=3, h=2, color=(58, 60, 70), price=280000,
                  reduce=0.99, slow=0.22, level=6, revive=True),
    # 背包:决定出战背包格子容量
    "pack_small": dict(name="小型战术背包", cat="pack", w=2, h=2, color=(112, 96, 68),
                       price=12000, grid=(5, 3)),
    "pack_mid": dict(name="中型突击背包", cat="pack", w=3, h=3, color=(96, 108, 76),
                     price=28000, grid=(6, 4)),
    "pack_large": dict(name="远征背包", cat="pack", w=4, h=3, color=(84, 96, 112),
                       price=58000, grid=(8, 5)),
    "pack_xl": dict(name="空降兵重型背包", cat="pack", w=5, h=4, color=(70, 74, 88),
                    price=98000, grid=(10, 6)),
    "gold": dict(name="金链子", cat="valuable", w=1, h=1, color=(255, 202, 44), price=18000),
    "cpu": dict(name="CPU 处理器", cat="valuable", w=2, h=1, color=(122, 182, 232), price=34000),
    "btc": dict(name="实体比特币", cat="valuable", w=1, h=1, color=(242, 152, 32), price=95000),
    "vase": dict(name="古董花瓶", cat="valuable", w=2, h=2, color=(202, 142, 172), price=62000),
}

# 高阶枪械(与 6 级甲同档)
ITEMS.update({
    "m4a1": dict(name="M4A1 卡宾枪", cat="weapon", w=5, h=2, color=(70, 78, 62), price=78000,
                 ammo="a556", dmg=22, pellets=1, spread=0.085, spread_braced=0.040,
                 rof=0.10, auto=True, mag=30, range=880, loud=780, sfx="ar"),
    "akm": dict(name="AKM 突击步枪", cat="weapon", w=5, h=2, color=(120, 74, 48), price=68000,
                ammo="a762", dmg=27, pellets=1, spread=0.11, spread_braced=0.055,
                rof=0.12, auto=True, mag=30, range=820, loud=950, sfx="ar"),
    # 狙击枪:精度本来就高,不参与架枪(无 spread_braced)
    "m700": dict(name="M700 狙击步枪", cat="weapon", w=6, h=2, color=(96, 70, 52), price=96000,
                 ammo="a54r", dmg=78, pellets=1, spread=0.02, rof=1.5, auto=False, mag=5,
                 range=1400, loud=1050, sfx="sg"),
    "a556": dict(name="5.56×45 穿甲弹", cat="ammo", w=1, h=1, color=(226, 140, 60),
                 price=140, stack=120, dmg_mul=1.30),
    "a762": dict(name="7.62×39 穿甲弹", cat="ammo", w=1, h=1, color=(180, 96, 44),
                 price=120, stack=120, dmg_mul=1.30),
    "a54r": dict(name="7.62×54R 穿甲弹", cat="ammo", w=1, h=1, color=(150, 60, 90),
                 price=200, stack=120, dmg_mul=1.35),
    # M139 装轮机枪:500 发弹容,需 6 级甲才能持用;腰射散布大,长按右键架枪大幅收拢
    "m139": dict(name="M139 装轮机枪", cat="weapon", w=5, h=3, color=(76, 82, 92),
                 price=320000, ammo="a762x45", dmg=24, pellets=1,
                 spread=0.155, spread_braced=0.032, rof=0.06, auto=True,
                 mag=500, range=760, loud=1080, sfx="ar",
                 req_armor_level=6, braced_immobile=True),
    "a762x45": dict(name="7.62×45 子弹", cat="ammo", w=1, h=1,
                    color=(196, 108, 66), price=130, stack=120),
})


def armor_allows(armor_item, weapon_def):
    """武器是否被当前护甲许可持用(带 req_armor_level 的重型武器需要 6 级甲)。"""
    lv = weapon_def.get("req_armor_level", 0)
    if not lv:
        return True
    return armor_item is not None and armor_item.def_.get("level", 0) >= lv

# 无背包时的口袋容量;装备背包后按其 grid
POCKETS = (4, 2)

# ---------- 杂物(价格不等,主要用来卖钱) ----------
ITEMS.update({
    "screwdriver": dict(name="螺丝刀", cat="misc", w=1, h=1, color=(180, 186, 196), price=2500),
    "tape": dict(name="布基胶带", cat="misc", w=1, h=1, color=(120, 128, 138), price=3500),
    "plug": dict(name="火花塞", cat="misc", w=1, h=1, color=(196, 172, 120), price=4200),
    "wrench": dict(name="扳手", cat="misc", w=1, h=2, color=(150, 154, 164), price=5800),
    "wire": dict(name="电线卷", cat="misc", w=1, h=1, color=(178, 120, 84), price=7600),
    "shampoo": dict(name="洗发水", cat="misc", w=1, h=2, color=(118, 168, 186), price=9000),
    "battery": dict(name="汽车电池", cat="misc", w=2, h=2, color=(88, 96, 106), price=24000),
    "fuelcan": dict(name="燃油罐", cat="misc", w=2, h=2, color=(160, 72, 60), price=33000),
    "motor": dict(name="电动机", cat="misc", w=2, h=2, color=(132, 136, 148), price=46000),
    "gpu": dict(name="显卡", cat="misc", w=2, h=1, color=(96, 150, 120), price=88000),
    "tools": dict(name="精密工具组", cat="misc", w=2, h=2, color=(180, 150, 96), price=128000),
    # 第二批杂物(更多廉价小件,摊薄金色物品产出)
    "coffee": dict(name="咖啡罐", cat="misc", w=1, h=1, color=(126, 90, 62), price=1800),
    "lighter": dict(name="打火机", cat="misc", w=1, h=1, color=(190, 130, 90), price=2200),
    "screws": dict(name="螺丝盒", cat="misc", w=1, h=1, color=(140, 146, 156), price=3000),
    "flashlight": dict(name="手电筒", cat="misc", w=1, h=1, color=(160, 168, 120), price=4500),
    "hose": dict(name="橡胶管", cat="misc", w=1, h=2, color=(72, 74, 80), price=6500),
    "relay": dict(name="继电器", cat="misc", w=1, h=1, color=(130, 124, 100), price=8200),
    "canteen": dict(name="军用水壶", cat="misc", w=1, h=2, color=(96, 116, 96), price=11000),
    "calculator": dict(name="计算器", cat="misc", w=1, h=1, color=(110, 118, 132), price=14000),
    "clock": dict(name="石英钟", cat="misc", w=2, h=1, color=(150, 120, 88), price=18000),
    "filter": dict(name="军用滤毒罐", cat="misc", w=1, h=1, color=(104, 110, 96), price=26000),
    "oscilloscope": dict(name="示波器", cat="misc", w=2, h=2, color=(92, 108, 124), price=38000),
    "solar": dict(name="太阳能板", cat="misc", w=3, h=2, color=(70, 96, 132), price=72000),
})

# 机密文件:孤品,仅在「强化封锁」的保险箱里固定刷出
CLASSIFIED = "doc"
ITEMS[CLASSIFIED] = dict(name="机密文件", cat="misc", w=1, h=1,
                         color=(240, 232, 190), price=5000000)
DOC_HARDENED_COUNT = 1   # 每局强化封锁刷几份机密文件(9=每个保险箱各一份)


def pack_grid(iid):
    """背包物品对应的格容量(非背包返回口袋容量)。"""
    return ITEMS.get(iid, {}).get("grid", POCKETS)

# ---------- 拾荒者(AI 敌人) ----------
SCAVS = {
    "melee": dict(name="刀匪", hp=45, speed=210, dmg=13, atk_range=34, atk_cd=0.8, view=310),
    "pistol": dict(name="拾荒枪手", hp=50, speed=145, dmg=8, pellets=1, spread=0.17, rof=1.2,
                   range=540, view=430, sfx="epm"),
    "shotgun": dict(name="霰弹拾荒者", hp=60, speed=125, dmg=7, pellets=6, spread=0.24, rof=1.8,
                    range=320, view=400, sfx="esg"),
    "ar": dict(name="突击拾荒者", hp=70, speed=160, dmg=9, pellets=1, spread=0.15, rof=0.18,
               burst=3, pause=1.5, range=720, view=460, sfx="ear"),
}
# 击杀掉落:武器 -> (武器iid, 弹药iid, 弹药min, 弹药max)
SCAV_DROPS = {
    "pistol": ("pm", "a9", 8, 16),
    "shotgun": ("mp133", "a12db", 4, 8),
    "ar": ("ak74", "a545", 10, 25),
}

# 拾荒者 AI 降级距离:超过这个距离又没在追击的敌人不算视线/寻路(省算力,迷雾里看不见)
SCAV_LOD_DIST = 1300

# ---------- 难度档位(作用于拾荒者属性与物资) ----------
# hp/dmg/speed/view:倍率; spread/rof:倍率(越大越不准/越慢); scavs:数量; rolls:搜刮次数; loot:弹药量倍率
DIFFICULTIES = {
    "easy": dict(name="简单", hp=0.70, dmg=0.55, spread=1.7, rof=1.6,
                 view=0.65, speed=0.85, scavs=8, rolls=2, loot=0.8,
                 desc="敌人孱弱迟钝,适合搜刮跑刀", loot_desc="物资一般"),
    "lockdown": dict(name="封锁", hp=0.90, dmg=0.80, spread=1.25, rof=1.25,
                     view=0.85, speed=0.95, scavs=11, rolls=2, loot=1.0,
                     desc="标准强度,有一定威胁", loot_desc="物资标准"),
    "hardened": dict(name="强化封锁", hp=1.15, dmg=1.00, spread=1.0, rof=1.0,
                     view=1.10, speed=1.05, scavs=14, rolls=3, loot=1.35,
                     desc="敌人凶猛敏锐,人多势众", loot_desc="物资丰富,肥得流油"),
}
DIFF_ORDER = ["easy", "lockdown", "hardened"]

# ---------- 交易所 ----------
SELL_RATE = 0.6          # 回收价 = 原价 × 0.6
BUY_MARKUP = 1.15         # 售价 = 原价 × 1.15(弹药按整盒计)
# 商品目录:(iid, 单次购买数量)
TRADE_GOODS = [
    # 枪械
    ("pm", 1), ("mp133", 1), ("mp5", 1), ("ak74", 1),
    ("m4a1", 1), ("akm", 1), ("m700", 1), ("m139", 1),
    # 弹药(按盒)
    ("a9", 30), ("a545", 30), ("a12db", 30), ("a12ap", 20),
    ("a556", 30), ("a762", 30), ("a54r", 20), ("a762x45", 30),
    # 医疗 / 护甲 / 背包
    ("bandage", 1), ("medkit", 1),
    ("paca", 1), ("fort", 1), ("b45", 1), ("bt201", 1),
    ("pack_mid", 1), ("pack_large", 1), ("pack_xl", 1),
]


def trade_buy_price(iid, count):
    """商品售价(弹药按盒计)。"""
    d = ITEMS[iid]
    if d["cat"] == "ammo":
        return int(d["price"] * count * BUY_MARKUP)
    return int(d["price"] * BUY_MARKUP)


def trade_sell_price(item):
    """回收价。"""
    return max(1, int(item.total_price() * SELL_RATE))

# ---------- 地图(三张地图见 maps.py) ----------
from maps import MAPS, MAP_ORDER, MODE_MAP, MAP_W, MAP_H

MW, MH = MAP_W, MAP_H
MAP_ROWS = MAPS["border"]["rows"]      # 兼容:默认地图行数据

# ---------- 头目(Boss)与手下 ----------
# 每张地图一个头目:击杀必掉 5 级甲 + 他的专属枪械;手下有概率掉 5 级甲
BOSSES = {
    "border": dict(name="指挥官 谢尔盖", hp=340, speed=152, dmg=16, pellets=1,
                   spread=0.055, rof=0.15, auto=True, burst=5, pause=1.1,
                   range=780, view=540, armor="b23", weapon="asval",
                   guard_weapon="ak74", guards=3, guard_hp=95, guard_dmg=11),
    "tv": dict(name="台长 卡尔波夫", hp=320, speed=158, dmg=14, pellets=1,
               spread=0.06, rof=0.12, auto=True, burst=6, pause=1.0,
               range=720, view=560, armor="zhuk", weapon="vector",
               guard_weapon="m4a1", guards=4, guard_hp=90, guard_dmg=10),
    "port": dict(name="港务长 马卡罗夫", hp=380, speed=146, dmg=18, pellets=1,
                 spread=0.075, rof=0.13, auto=True, burst=4, pause=1.3,
                 range=900, view=520, armor="korund", weapon="pkp",
                 guard_weapon="akm", guards=4, guard_hp=110, guard_dmg=13),
    # 突袭模式:大本营的「要塞司令」。他不死 + 通讯站没炸 -> 敌人援兵源源不断
    "base": dict(name="要塞司令 沃罗宁", hp=460, speed=150, dmg=20, pellets=1,
                 spread=0.05, rof=0.11, auto=True, burst=6, pause=0.9,
                 range=880, view=580, armor="bt201", weapon="m139",
                 guard_weapon="akm", guards=5, guard_hp=120, guard_dmg=14),
}
GUARD_ARMOR_DROP = 0.4                  # 手下掉 5 级甲的概率
GUARD_ARMORS = ["b23", "zhuk", "korund"]

# ---------- 隐藏 Boss「作者」(扛 RPG) ----------
# 火箭弹命中玩家:穿 6 级甲只掉一半血;<6 级直接阵亡
AUTHOR_BOSS = dict(name="作者", hp=420, speed=118, dmg=1, pellets=1,
                   spread=0.05, rof=3.0, auto=False, burst=1, pause=0.0,
                   range=900, view=620, armor="bt201", weapon="rpg", rpg=True)
AUTHOR_MIN_DIFFICULTY = ("lockdown", "hardened")   # 作者只在封锁及以上难度出现
RPG_HALF_HP_ARMOR_LEVEL = 6             # 被火箭弹命中时需要的护甲等级
RPG_BLAST_RADIUS = 96                   # 火箭弹溅射半径(像素):范围内都吃伤害,不必精确瞄准

# ---------- 5 级甲(减伤 89% / 81% / 75%)与头目专属枪械 ----------
ITEMS.update({
    "b23": dict(name="6B23-1 防弹衣", cat="armor", w=3, h=2, color=(96, 104, 84),
                price=95000, reduce=0.89, slow=0.14, level=5),
    "zhuk": dict(name="Zhuk-3 防弹衣", cat="armor", w=3, h=2, color=(104, 92, 78),
                 price=78000, reduce=0.81, slow=0.10, level=5),
    "korund": dict(name="Korund VM 防弹衣", cat="armor", w=3, h=2, color=(84, 96, 108),
                   price=66000, reduce=0.75, slow=0.08, level=5),
    # 头目专属(仅掉落,不上架):
    "asval": dict(name="AS VAL 特种步枪", cat="weapon", w=5, h=2, color=(68, 72, 78),
                  price=210000, ammo="a939", dmg=26, pellets=1,
                  spread=0.08, spread_braced=0.038, rof=0.09, auto=True, mag=20,
                  range=640, loud=300, sfx="mp5", boss_only=True),
    "vector": dict(name="Vector 冲锋枪", cat="weapon", w=4, h=2, color=(70, 84, 76),
                   price=190000, ammo="a45", dmg=17, pellets=1,
                   spread=0.09, spread_braced=0.042, rof=0.055, auto=True, mag=33,
                   range=620, loud=700, sfx="mp5", boss_only=True),
    "pkp": dict(name="PKP 佩切涅格机枪", cat="weapon", w=6, h=3, color=(88, 82, 66),
                price=260000, ammo="a54r", dmg=28, pellets=1,
                spread=0.13, spread_braced=0.05, rof=0.085, auto=True, mag=100,
                range=950, loud=1100, sfx="ar", req_armor_level=5, boss_only=True),
    "a939": dict(name="9×39mm 子弹", cat="ammo", w=1, h=1, color=(150, 160, 120),
                 price=150, stack=120),
    "a45": dict(name=".45 ACP 子弹", cat="ammo", w=1, h=1, color=(196, 140, 92),
                price=95, stack=120),
    # 作者专属:RPG-7 火箭筒(腰射很不准,长按右键架枪才打得准)
    "rpg": dict(name="RPG-7 火箭筒", cat="weapon", w=6, h=2, color=(92, 86, 66),
                price=400000, ammo="rocket", dmg=200, pellets=1,
                spread=0.25, spread_braced=0.10, rof=2.0, auto=False, mag=1,
                range=900, loud=1200, sfx="sg", boss_only=True),
    # 第二把火箭筒:四管连发,伤害与"命中玩家"规则和 RPG-7 完全一致
    "rpg2": dict(name="M202 四管火箭发射器", cat="weapon", w=6, h=3, color=(74, 80, 70),
                 price=620000, ammo="rocket", dmg=200, pellets=1,
                 spread=0.22, spread_braced=0.08, rof=1.2, auto=False, mag=4,
                 range=980, loud=1260, sfx="sg", boss_only=True),
    "rocket": dict(name="PG-7V 火箭弹", cat="ammo", w=2, h=1, color=(158, 124, 72),
                   price=8000, stack=5),
})

# 特殊枪械(头目专属)全部上架到交易站的「特殊枪械」分区
SPECIAL_WEAPONS = ["asval", "vector", "pkp", "rpg", "rpg2"]

# 交易所新增:5 级甲、头目枪械与弹种、火箭弹、更多药品
TRADE_GOODS += [("pack_small", 1), ("b23", 1), ("zhuk", 1), ("korund", 1),
                ("mag_ext", 1), ("mag_drum", 1), ("mag_drum_big", 1),
                ("grip_vert", 1), ("grip_ang", 1), ("laser_tac", 1), ("laser_ir", 1),
                ("stock_tac", 1), ("stock_heavy", 1),
                ("a939", 30), ("a45", 30), ("rocket", 1),
                ("painkiller", 1), ("tourniquet", 1), ("syringe", 1),
                ("ai2", 1), ("surgery", 1)]
TRADE_GOODS += [(iid, 1) for iid in SPECIAL_WEAPONS]
# 黑暗模式装备:枪上照明 + 夜视头盔(夜视很贵,不然夜战太简单)
TRADE_GOODS += [("flashlight", 1), ("flashlight_pro", 1),
                ("nvg_pnv", 1), ("nvg_gpnvg", 1)]

# 交易站分区:(标签名, 分区键;None = 全部)
TRADE_TABS = [("全部", None), ("枪械", "weapon"), ("特殊枪械", "special"), ("配件", "attach"),
              ("护甲", "armor"), ("头盔", "helmet"), ("背包", "pack"), ("子弹", "ammo"),
              ("药品", "med")]
TRADE_PAGE_H = 450      # 商品区可见高度(像素);超出时用滚轮翻看

# ---------- 枪械配件 ----------
# slot: mag 弹夹 / grip 前握把 / laser 激光 / stock 后握把 / light 照明(手电)
# 效果:mag_bonus 加弹容;brace_mul 架枪散布倍率(越小越准);hip_mul 腰射散布倍率
ATTACH_SLOTS = {"mag": "弹夹", "grip": "前握把", "laser": "激光", "stock": "后握把",
                "light": "照明"}
ITEMS.update({
    "mag_ext": dict(name="加长弹夹", cat="attach", slot="mag", w=1, h=1,
                    color=(150, 150, 160), price=6000, mag_bonus=10, desc="弹容 +10"),
    "mag_drum": dict(name="弹鼓", cat="attach", slot="mag", w=1, h=2,
                     color=(120, 124, 134), price=14000, mag_bonus=20, desc="弹容 +20"),
    "mag_drum_big": dict(name="大弹鼓", cat="attach", slot="mag", w=2, h=2,
                         color=(96, 100, 110), price=26000, mag_bonus=30, desc="弹容 +30"),
    "grip_vert": dict(name="垂直握把", cat="attach", slot="grip", w=1, h=1,
                      color=(88, 92, 100), price=5000, brace_mul=0.88, desc="架枪散布 -12%"),
    "grip_ang": dict(name="斜角握把", cat="attach", slot="grip", w=1, h=1,
                     color=(76, 84, 96), price=12000, brace_mul=0.80, desc="架枪散布 -20%"),
    "laser_tac": dict(name="战术激光", cat="attach", slot="laser", w=1, h=1,
                      color=(200, 90, 90), price=6000, hip_mul=0.90, desc="腰射散布 -10%"),
    "laser_ir": dict(name="红外激光", cat="attach", slot="laser", w=1, h=1,
                     color=(190, 60, 70), price=15000, hip_mul=0.82, desc="腰射散布 -18%"),
    "stock_tac": dict(name="战术枪托", cat="attach", slot="stock", w=2, h=1,
                      color=(96, 92, 84), price=7000, brace_mul=0.92, hip_mul=0.96,
                      desc="架枪 -8% · 腰射 -4%"),
    "stock_heavy": dict(name="重型枪托", cat="attach", slot="stock", w=2, h=1,
                        color=(80, 78, 72), price=18000, brace_mul=0.85, hip_mul=0.92,
                        desc="架枪 -15% · 腰射 -8%"),
    # 照明配件(黑暗模式的核心):装在枪上,朝准星方向打出一道亮锥
    "flashlight": dict(name="战术手电", cat="attach", slot="light", w=1, h=1,
                       color=(230, 226, 180), price=16000,
                       beam=(430, 26), desc="夜战照明:锥形亮区 430 内可见"),
    "flashlight_pro": dict(name="强光探照灯", cat="attach", slot="light", w=2, h=1,
                           color=(238, 236, 200), price=45000,
                           beam=(580, 32), desc="夜战照明:锥形亮区 580 内可见"),
})

# ---------- 夜视头盔(黑暗模式) ----------
# cat="helmet":占用新增的「头盔」装备槽(和护甲不冲突);nvg=(半径, 亮度) 自带夜视仪
ITEMS.update({
    "nvg_pnv": dict(name="PNV-10T 夜视头盔", cat="helmet", w=2, h=2,
                    color=(84, 104, 76), price=180000, level=3,
                    nvg=(300, 150), desc="夜视:周围 300 全向可见(微光)"),
    "nvg_gpnvg": dict(name="GPNVG-18 四眼夜视头盔", cat="helmet", w=3, h=2,
                      color=(74, 96, 72), price=480000, level=4,
                      nvg=(440, 205), desc="夜视:周围 440 全向可见(更亮更远)"),
})


def helmet_nvg(item):
    """头盔的夜视参数 (半径, 亮度);没有夜视仪返回 None。"""
    if item is None or item.def_.get("cat") != "helmet":
        return None
    return item.def_.get("nvg")


def weapon_beam(item):
    """枪上照明配件的光锥 (射程, 半角°);没装返回 None。"""
    for iid in weapon_attach(item).values():
        b = ITEMS.get(iid, {}).get("beam")
        if b:
            return b
    return None

# ---------- 枪械天赋(每把枪自带) ----------
# dmg_mul 伤害倍率; spread_mul 全部散布; brace_mul 架枪散布; reload_mul 装填时间; loud_mul 枪声; blast_mul 爆炸半径
TALENTS = {
    "pm": dict(name="顺手", desc="无特殊效果"),
    "mp5": dict(name="扫射专精", desc="散布 -10%", spread_mul=0.90),
    "mp133": dict(name="近身压制", desc="架枪散布 -10%", brace_mul=0.90),
    "ak74": dict(name="老伙计", desc="散布 -8%", spread_mul=0.92),
    "m4a1": dict(name="战术本能", desc="装填速度 +35%", reload_mul=0.65),
    "akm": dict(name="重弹头", desc="伤害 +10%", dmg_mul=1.10),
    "m700": dict(name="一枪入魂", desc="架枪散布 -40%", brace_mul=0.60),
    "m139": dict(name="金属风暴", desc="机枪不装配件", spread_mul=1.0),
    "asval": dict(name="潜行刺客", desc="枪声 -60% · 架枪 -15%",
                  loud_mul=0.40, brace_mul=0.85),
    "vector": dict(name="狂飙", desc="装填速度 +50%", reload_mul=0.50),
    "pkp": dict(name="弹链供给", desc="装填速度 +40%", reload_mul=0.60),
    "rpg": dict(name="轰天雷", desc="爆炸溅射更远", blast_mul=1.25),
    "rpg2": dict(name="四连轰", desc="爆炸溅射更远", blast_mul=1.25),
}

# 武器可装的配件槽(M139 机枪按需求不装任何配件)
WEAPON_SLOTS = {
    "pm": ["light"], "mp5": ["mag", "grip", "laser", "stock", "light"],
    "mp133": ["mag", "grip", "laser", "light"],
    "ak74": ["mag", "grip", "laser", "stock", "light"],
    "m4a1": ["mag", "grip", "laser", "stock", "light"],
    "akm": ["mag", "grip", "laser", "stock", "light"],
    "m700": ["mag", "laser", "stock", "light"],
    "m139": [], "asval": ["mag", "grip", "laser", "light"],
    "vector": ["mag", "grip", "laser", "stock", "light"],
    "pkp": ["laser", "light"], "rpg": [], "rpg2": [],
}


def weapon_slots(iid):
    return WEAPON_SLOTS.get(iid, [])


# ---------- 扩展枪械库(暗区式:型号 + 分类 + 口径) ----------
# (iid, 名称, 分类, 弹药, 伤害, 弹匣, 射速s, 腰射散布, 架枪散布(None=狙击枪不架枪),
#  射程, 价格, 占格宽, 占格高, 颜色, 全自动, 弹丸数, 需护甲等级)
EXTRA_WEAPONS = [
    # ===== 突击步枪(5.56×45) =====
    ("hk416", "HK416 突击步枪", "突击步枪", "a556", 23, 30, 0.095, 0.085, 0.040, 900, 105000, 5, 2, (104, 96, 78), True),
    ("scar_l", "SCAR-L 突击步枪", "突击步枪", "a556", 23, 30, 0.095, 0.086, 0.041, 900, 108000, 5, 2, (110, 102, 82), True),
    ("mdr", "沙漠科技 MDR", "突击步枪", "a556", 24, 30, 0.100, 0.088, 0.042, 900, 115000, 5, 2, (98, 100, 88), True),
    ("aug", "AUG A3 突击步枪", "突击步枪", "a556", 22, 30, 0.095, 0.085, 0.042, 880, 98000, 5, 2, (92, 98, 86), True),
    ("f2000", "FN F2000 突击步枪", "突击步枪", "a556", 22, 30, 0.090, 0.088, 0.044, 860, 92000, 5, 2, (88, 94, 92), True),
    ("g36", "G36C 突击步枪", "突击步枪", "a556", 22, 30, 0.090, 0.088, 0.043, 860, 92000, 5, 2, (86, 90, 88), True),
    ("sg550", "SIG SG550 突击步枪", "突击步枪", "a556", 24, 30, 0.100, 0.084, 0.040, 920, 118000, 5, 2, (100, 96, 84), True),
    ("mcx", "SIG MCX 突击步枪", "突击步枪", "a556", 24, 30, 0.090, 0.084, 0.040, 880, 118000, 5, 2, (94, 94, 86), True),
    ("arx160", "Beretta ARX160", "突击步枪", "a556", 22, 30, 0.095, 0.088, 0.043, 860, 88000, 5, 2, (96, 98, 90), True),
    ("ar15", "AR-15 卡宾枪", "突击步枪", "a556", 21, 30, 0.100, 0.092, 0.045, 820, 62000, 5, 2, (88, 90, 84), True),
    ("m16", "M16A4 突击步枪", "突击步枪", "a556", 22, 30, 0.085, 0.078, 0.038, 950, 86000, 5, 2, (84, 88, 82), False),
    ("ak102", "AK-102 短突击步枪", "突击步枪", "a556", 21, 30, 0.105, 0.100, 0.048, 780, 88000, 5, 2, (122, 86, 58), True),
    # ===== 突击步枪(5.45×39 / 5.8×42) =====
    ("ak12", "AK-12 突击步枪", "突击步枪", "a545", 23, 30, 0.095, 0.085, 0.041, 900, 108000, 5, 2, (118, 88, 62), True),
    ("a545r", "A-545 突击步枪", "突击步枪", "a545", 23, 30, 0.100, 0.088, 0.042, 900, 118000, 5, 2, (112, 92, 66), True),
    ("aek", "AEK-971 突击步枪", "突击步枪", "a545", 23, 30, 0.100, 0.092, 0.045, 880, 96000, 5, 2, (116, 90, 60), True),
    ("an94", "AN-94 突击步枪", "突击步枪", "a545", 24, 30, 0.090, 0.082, 0.040, 900, 132000, 5, 2, (106, 86, 64), True),
    ("ak74u", "AK-74U 短突击步枪", "突击步枪", "a545", 18, 30, 0.090, 0.110, 0.055, 620, 42000, 4, 2, (124, 92, 60), True),
    ("aks74u", "AKS-74U 短突击步枪", "突击步枪", "a545", 18, 30, 0.090, 0.110, 0.055, 620, 44000, 4, 2, (110, 84, 58), True),
    ("t951", "T951 突击步枪", "突击步枪", "a58", 23, 30, 0.100, 0.095, 0.046, 850, 92000, 5, 2, (96, 106, 92), True),
    ("t03", "T03 突击步枪", "突击步枪", "a58", 23, 30, 0.105, 0.098, 0.048, 850, 84000, 5, 2, (92, 102, 90), True),
    ("qbz191", "QBZ-191 突击步枪", "突击步枪", "a58", 25, 30, 0.095, 0.086, 0.041, 920, 128000, 5, 2, (90, 100, 88), True),
    # ===== 战斗步枪(7.62×51 / 7.62×39) =====
    ("fal", "FAL 战斗步枪", "突击步枪", "a762x51", 34, 20, 0.110, 0.100, 0.050, 950, 120000, 5, 2, (108, 92, 70), True),
    ("g3", "G3A3 战斗步枪", "突击步枪", "a762x51", 33, 20, 0.120, 0.100, 0.052, 950, 112000, 5, 2, (78, 82, 82), True),
    ("scar_h", "SCAR-H 战斗步枪", "突击步枪", "a762x51", 33, 20, 0.110, 0.098, 0.048, 960, 148000, 5, 2, (112, 104, 82), True),
    ("scar_hamr", "SCAR-H AMR 战斗步枪", "突击步枪", "a762x51", 35, 20, 0.120, 0.092, 0.044, 1050, 186000, 6, 2, (104, 98, 78), True),
    ("ace31", "IWI ACE 31", "突击步枪", "a762", 25, 30, 0.105, 0.100, 0.050, 850, 86000, 5, 2, (102, 96, 76), True),
    # ===== 特种步枪(9×39 微声) =====
    ("groza", "OTs-14 狗杂", "特种步枪", "a939", 26, 30, 0.090, 0.100, 0.048, 640, 128000, 5, 2, (92, 88, 74), True),
    ("9a91", "9A-91 突击步枪", "特种步枪", "a939", 24, 20, 0.085, 0.100, 0.048, 620, 78000, 4, 2, (84, 86, 80), True),
    ("vss", "VSS 微声狙击步枪", "特种步枪", "a939", 42, 20, 0.160, 0.045, 0.028, 700, 118000, 5, 2, (84, 88, 78), True),
    # ===== 冲锋枪 =====
    ("mpx", "SIG MPX 冲锋枪", "冲锋枪", "a9", 13, 30, 0.085, 0.072, 0.034, 720, 62000, 3, 1, (92, 96, 104), True),
    ("p90", "FN P90 冲锋枪", "冲锋枪", "a57", 14, 50, 0.070, 0.078, 0.036, 700, 78000, 4, 2, (98, 100, 106), True),
    ("ump45", "UMP45 冲锋枪", "冲锋枪", "a45", 17, 25, 0.100, 0.080, 0.038, 680, 58000, 4, 2, (86, 88, 92), True),
    ("pp19", "PP-19 野牛冲锋枪", "冲锋枪", "a9", 13, 53, 0.080, 0.078, 0.036, 660, 68000, 4, 2, (88, 94, 88), True),
    ("t79", "T79 冲锋枪", "冲锋枪", "a762x25", 14, 20, 0.090, 0.095, 0.045, 560, 38000, 3, 2, (90, 92, 96), True),
    ("mp40", "MP40 冲锋枪", "冲锋枪", "a9", 14, 32, 0.090, 0.088, 0.042, 600, 32000, 4, 2, (76, 78, 82), True),
    ("uzi", "UZI 冲锋枪", "冲锋枪", "a9", 12, 32, 0.075, 0.092, 0.044, 580, 30000, 3, 2, (80, 82, 86), True),
    ("mp9", "Steyr MP9 冲锋枪", "冲锋枪", "a9", 12, 30, 0.070, 0.082, 0.038, 620, 52000, 3, 1, (70, 74, 78), True),
    ("mac10", "MAC-10 冲锋枪", "冲锋枪", "a45", 15, 30, 0.065, 0.105, 0.052, 520, 34000, 3, 1, (74, 76, 80), True),
    ("m3a1", "M3A1 注油枪", "冲锋枪", "a45", 16, 30, 0.100, 0.098, 0.048, 560, 26000, 4, 2, (96, 98, 100), True),
    ("qc61", "QC61 微声冲锋枪", "冲锋枪", "a58", 19, 30, 0.080, 0.080, 0.036, 640, 72000, 4, 2, (84, 90, 86), True),
    # ===== 霰弹枪(弹丸数在倒数第二位) =====
    ("m870", "M870 泵动霰弹枪", "霰弹枪", ["a12db", "a12ap"], 10, 7, 1.30, 0.220, 0.130, 420, 38000, 5, 2, (128, 84, 52), False, 8),
    ("s12k", "S12K 半自动霰弹枪", "霰弹枪", ["a12db", "a12ap"], 8, 8, 0.50, 0.240, 0.140, 400, 68000, 5, 2, (112, 78, 50), True, 7),
    ("usas12", "USAS-12 自动霰弹枪", "霰弹枪", ["a12db", "a12ap"], 8, 20, 0.28, 0.260, 0.150, 420, 148000, 5, 3, (98, 74, 52), True, 8, 5),
    ("spr310", "SPR310 半自动霰弹枪", "霰弹枪", ["a12db", "a12ap"], 9, 5, 0.70, 0.230, 0.135, 430, 52000, 5, 2, (118, 82, 54), True, 7),
    # ===== 精确射手步枪(半自动,可架枪) =====
    ("m14", "M14 战斗步枪", "精确射手步枪", "a762x51", 60, 20, 0.30, 0.045, 0.030, 1200, 98000, 6, 2, (104, 86, 62), False),
    ("mk14", "Mk14 EBR", "精确射手步枪", "a762x51", 62, 20, 0.30, 0.045, 0.030, 1200, 148000, 6, 2, (92, 88, 80), False),
    ("m110", "M110 SASS", "精确射手步枪", "a762x51", 64, 20, 0.35, 0.040, 0.026, 1250, 168000, 6, 2, (86, 88, 84), False),
    ("bm59", "BM59 战斗步枪", "精确射手步枪", "a762x51", 63, 20, 0.32, 0.048, 0.030, 1150, 118000, 6, 2, (108, 90, 66), False),
    ("m96", "M96 半自动步枪", "精确射手步枪", "a762x51", 58, 20, 0.35, 0.050, 0.032, 1100, 88000, 6, 2, (98, 92, 74), False),
    ("sks", "SKS 半自动步枪", "精确射手步枪", "a762", 42, 10, 0.40, 0.055, 0.035, 1000, 42000, 6, 2, (126, 96, 62), False),
    ("sa85m", "SA-85M 半自动步枪", "精确射手步枪", "a762", 43, 30, 0.28, 0.060, 0.036, 950, 62000, 5, 2, (118, 92, 64), False),
    ("mini14", "Mini-14 半自动步枪", "精确射手步枪", "a556", 40, 20, 0.30, 0.055, 0.034, 1000, 58000, 5, 2, (96, 94, 86), False),
    ("adar215", "ADAR 2-15 半自动步枪", "精确射手步枪", "a556", 41, 30, 0.28, 0.050, 0.030, 1050, 72000, 5, 2, (90, 92, 86), False),
    ("t88", "T88 精确射手步枪", "精确射手步枪", "a556", 46, 20, 0.25, 0.048, 0.030, 1150, 118000, 5, 2, (94, 102, 90), False),
    ("svtu", "SVT-40 半自动步枪", "精确射手步枪", "a54r", 60, 10, 0.35, 0.045, 0.030, 1200, 88000, 6, 2, (112, 88, 62), False),
    ("hunter", "Hunter 猎枪", "精确射手步枪", "a762x51", 70, 10, 0.90, 0.030, 0.020, 1200, 62000, 5, 2, (116, 96, 68), False),
    # ===== 狙击步枪(不参与架枪) =====
    ("svds", "SVD-S 狙击步枪", "狙击步枪", "a54r", 68, 10, 1.20, 0.030, None, 1300, 128000, 6, 2, (108, 84, 60), False),
    ("mosin", "莫辛-纳甘 M91/30", "狙击步枪", "a54r", 92, 5, 1.60, 0.018, None, 1500, 68000, 6, 2, (120, 92, 62), False),
    ("m24", "M24 狙击步枪", "狙击步枪", "a762x51", 88, 5, 1.50, 0.018, None, 1450, 138000, 6, 2, (100, 94, 78), False),
    ("sj16", "SJ-16 狙击步枪", "狙击步枪", "a54r", 95, 10, 1.40, 0.020, None, 1500, 158000, 6, 2, (96, 98, 88), False),
    ("ax50", "AX-50 反器材狙击步枪", "狙击步枪", "a50", 180, 5, 1.70, 0.015, None, 1800, 320000, 6, 3, (88, 90, 94), False),
    # ===== 轻机枪 =====
    ("rpk16", "RPK-16 轻机枪", "轻机枪", "a545", 24, 45, 0.085, 0.110, 0.045, 900, 168000, 5, 3, (116, 88, 60), True),
    ("evolys", "FN EVOLYS 轻机枪", "轻机枪", "a556", 25, 100, 0.075, 0.100, 0.040, 950, 218000, 5, 3, (92, 96, 92), True, 1, 5),
    ("negev7", "Negev NG7 轻机枪", "轻机枪", "a762x51", 30, 100, 0.080, 0.120, 0.048, 1000, 248000, 6, 3, (86, 88, 90), True, 1, 5),
    # ===== 手枪 =====
    ("g17", "G17 手枪", "手枪", "a9", 16, 17, 0.16, 0.045, 0.028, 640, 18000, 2, 1, (152, 152, 158), False),
    ("g18c", "G18C 全自动手枪", "手枪", "a9", 15, 33, 0.06, 0.075, 0.045, 600, 42000, 2, 1, (136, 138, 144), True),
    ("m9a3", "M9A3 手枪", "手枪", "a9", 15, 17, 0.17, 0.048, 0.030, 620, 16000, 2, 1, (140, 142, 150), False),
    ("deagle", "沙漠之鹰", "手枪", "a50", 60, 7, 0.35, 0.070, 0.040, 700, 128000, 2, 1, (168, 150, 120), False),
    ("deagle_gold", "黄金沙鹰", "手枪", "a50", 62, 7, 0.33, 0.066, 0.038, 720, 480000, 2, 1, (232, 196, 80), False),
    ("f57", "FN Five-seveN", "手枪", "a57", 18, 20, 0.14, 0.045, 0.028, 660, 68000, 2, 1, (146, 150, 160), False),
    ("t54", "T54 手枪", "手枪", "a762x25", 20, 8, 0.25, 0.055, 0.034, 620, 22000, 2, 1, (132, 128, 124), False),
    ("t05", "T05 微声手枪", "手枪", "a58", 19, 20, 0.20, 0.050, 0.030, 600, 48000, 2, 1, (110, 118, 116), False),
    ("m1911", "M1911 手枪", "手枪", "a45", 21, 7, 0.24, 0.055, 0.034, 600, 20000, 2, 1, (150, 142, 130), False),
    ("m45a1", "M45A1 手枪", "手枪", "a45", 22, 8, 0.22, 0.052, 0.032, 620, 36000, 2, 1, (138, 134, 126), False),
    ("cz52", "CZ52 手枪", "手枪", "a762x25", 19, 8, 0.24, 0.058, 0.036, 640, 18000, 2, 1, (124, 122, 128), False),
    ("m300", "M300 转轮手枪", "手枪", "a45", 28, 6, 0.45, 0.060, 0.038, 620, 42000, 2, 1, (140, 132, 120), False),
]

_WEAPON_SLOTS_BY_CLASS = {
    "手枪": ["mag", "laser", "light"],
    "冲锋枪": ["mag", "grip", "laser", "stock", "light"],
    "霰弹枪": ["mag", "grip", "laser", "light"],
    "突击步枪": ["mag", "grip", "laser", "stock", "light"],
    "特种步枪": ["mag", "grip", "laser", "light"],
    "精确射手步枪": ["mag", "grip", "laser", "stock", "light"],
    "狙击步枪": ["mag", "laser", "stock", "light"],
    "轻机枪": ["laser", "light"],
    "火箭筒": [],
}
_WEAPON_SFX_BY_CLASS = {"手枪": "pm", "冲锋枪": "mp5", "霰弹枪": "sg"}
_WEAPON_LOUD_BY_CLASS = {"手枪": 520, "冲锋枪": 720, "霰弹枪": 900,
                         "狙击步枪": 1100, "轻机枪": 1150}

for _spec in EXTRA_WEAPONS:
    _iid, _name, _cls, _ammo, _dmg, _mag, _rof, _spread, _braced = _spec[:9]
    _rng, _price, _w, _h, _col, _auto = _spec[9:15]
    _pellets = _spec[15] if len(_spec) > 15 else 1
    _req = _spec[16] if len(_spec) > 16 else 0
    _d = dict(name=_name, cat="weapon", w=_w, h=_h, color=_col, price=_price,
              ammo=_ammo, dmg=_dmg, pellets=_pellets, spread=_spread, rof=_rof,
              auto=_auto, mag=_mag, range=_rng,
              sfx=_WEAPON_SFX_BY_CLASS.get(_cls, "ar"),
              loud=_WEAPON_LOUD_BY_CLASS.get(_cls, 950))
    if _braced is not None:
        _d["spread_braced"] = _braced
    if _req:
        _d["req_armor_level"] = _req
    ITEMS[_iid] = _d
    WEAPON_CLASS[_iid] = _cls
    WEAPON_SLOTS[_iid] = list(_WEAPON_SLOTS_BY_CLASS[_cls])

# 新弹种(5.8×42 / 7.62×51 / 7.62×25 / 5.7×28 / .50)
ITEMS.update({
    "a762x51": dict(name="7.62×51 穿甲弹", cat="ammo", w=1, h=1,
                    color=(152, 122, 88), price=180, stack=120, dmg_mul=1.30),
    "a58": dict(name="5.8×42 弹", cat="ammo", w=1, h=1,
                color=(120, 200, 170), price=170, stack=120, dmg_mul=1.30),
    "a762x25": dict(name="7.62×25 弹", cat="ammo", w=1, h=1,
                    color=(182, 152, 92), price=60, stack=120, dmg_mul=1.05),
    "a57": dict(name="5.7×28 弹", cat="ammo", w=1, h=1,
                color=(190, 172, 212), price=150, stack=120, dmg_mul=1.15),
    "a50": dict(name=".50 大口径弹", cat="ammo", w=1, h=1,
                color=(232, 190, 62), price=900, stack=60, dmg_mul=1.60),
})

# 新枪械与新弹种全部上架交易站
TRADE_GOODS += [(s[0], 1) for s in EXTRA_WEAPONS]
TRADE_GOODS += [("a762x51", 30), ("a58", 30), ("a762x25", 30),
                ("a57", 30), ("a50", 10)]


def weapon_talent(iid):
    return TALENTS.get(iid)


def weapon_attach(item):
    return (item.state.get("attach") or {}) if item is not None else {}


def weapon_capacity(item):
    """有效弹容 = 基础弹容 + 配件加成。"""
    if item is None:
        return 0
    cap = item.def_["mag"]
    for iid in weapon_attach(item).values():
        cap += ITEMS.get(iid, {}).get("mag_bonus", 0)
    return cap


def weapon_params(item):
    """(伤害, 弹丸数, 腰射散布, 架枪散布, 射程, 装填时间, 枪声, 燃烧伤害)。
    综合武器基础值 + 当前装填的弹种 + 配件 + 天赋。"""
    d = item.def_
    ammo_ids = d["ammo"] if isinstance(d["ammo"], list) else [d["ammo"]]
    loaded = item.state.get("loaded")
    if loaded not in ammo_ids:
        loaded = ammo_ids[0] if ammo_ids else None
    a = ITEMS.get(loaded, {})
    tal = TALENTS.get(item.iid, {})
    dmg = d["dmg"] * a.get("dmg_mul", 1.0) * tal.get("dmg_mul", 1.0)
    pellets = a.get("pellets", d.get("pellets", 1))
    spread_add = a.get("spread_add", 0.0)
    hip = d["spread"] + spread_add
    braced = d.get("spread_braced", d["spread"]) + max(0.0, spread_add * 0.4)
    hip_mul = tal.get("spread_mul", 1.0)
    braced_mul = tal.get("spread_mul", 1.0)
    for iid in weapon_attach(item).values():
        att = ITEMS.get(iid, {})
        hip_mul *= att.get("hip_mul", 1.0)
        braced_mul *= att.get("brace_mul", 1.0)
    braced_mul *= tal.get("brace_mul", 1.0)
    hip *= hip_mul
    braced *= braced_mul
    return (dmg, pellets, hip, braced, d["range"] * a.get("range_mul", 1.0),
            1.6 * tal.get("reload_mul", 1.0), d["loud"] * tal.get("loud_mul", 1.0),
            a.get("burn", 0.0))


def weapon_ammo_ids(item):
    if item is None:
        return []
    a = item.def_["ammo"]
    return list(a) if isinstance(a, list) else [a]


def weapon_blast_mul(item):
    tal = TALENTS.get(item.iid, {}) if item is not None else {}
    return tal.get("blast_mul", 1.0)


# ---------- 射击模式(按 G 切换) ----------
# 全自动枪械:单发 → 三连发 → 全自动 循环;半自动/栓动/泵动枪只有单发。
# 当前模式存在武器 state["fire_mode"] 里,所以换枪、存档都跟着武器走。
FIRE_MODE_NAMES = {"semi": "单发", "burst": "三连发", "auto": "全自动"}
FIRE_MODE_ORDER = ["semi", "burst", "auto"]
BURST_COUNT = 3          # 三连发:扣一次扳机打几发


def weapon_fire_modes(item_or_def):
    """这把枪支持的射击模式(按切换顺序)。"""
    d = item_or_def.def_ if hasattr(item_or_def, "def_") else item_or_def
    return list(FIRE_MODE_ORDER) if d.get("auto") else ["semi"]


def weapon_default_fire_mode(item_or_def):
    """默认模式:全自动枪用全自动(与老版本行为一致),其余单发。"""
    d = item_or_def.def_ if hasattr(item_or_def, "def_") else item_or_def
    return "auto" if d.get("auto") else "semi"


def weapon_fire_mode(item):
    """当前射击模式(存档里的旧武器没有该项时回落到默认值)。"""
    if item is None:
        return "semi"
    modes = weapon_fire_modes(item)
    m = item.state.get("fire_mode")
    if m in modes:
        return m
    dflt = weapon_default_fire_mode(item)
    return dflt if dflt in modes else modes[0]


def cycle_fire_mode(item):
    """切到下一个射击模式并写回武器 state;只有一种模式时返回 None。"""
    if item is None:
        return None
    modes = weapon_fire_modes(item)
    if len(modes) < 2:
        return None
    nxt = modes[(modes.index(weapon_fire_mode(item)) + 1) % len(modes)]
    item.state["fire_mode"] = nxt
    return nxt


def fire_mode_name(mode):
    return FIRE_MODE_NAMES.get(mode, FIRE_MODE_NAMES["semi"])

# ---------- 游戏模式 ----------
MODES = {
    "raid": dict(name="搜打撤", short="搜打撤", desc="自由搜刮 · 找撤离点撤离"),
    "hostage": dict(name="人质解救", short="人质", desc="室内近战 · 20 名匪徒分守八间房 · 救出 4 名人质"),
    "assault": dict(name="突袭", short="突袭", desc="强攻敌巢 · 50 守军 · 友军空袭支援"),
    "story": dict(name="剧情", short="剧情", desc="灰区二日 · 两天两夜 · 有分支与结局"),
    "night": dict(name="黑暗行动", short="夜战",
                  desc="漆黑一片 · 要自带光源 · 默认强化封锁"),
}
MODE_ORDER = ["raid", "hostage", "assault", "story", "night"]

# ---------- 黑暗模式(夜战) ----------
# 全图压成漆黑:只有「光源范围」内能看见东西(敌人也只有亮区里才显示)。
# 光源两种:枪上的照明配件(锥形,跟准星方向) / 夜视头盔(全向圆,贵)。
NIGHT_AMBIENT = 92          # 无光源时脚边这一小圈还是能看见(像素)
NIGHT_DARK_RGB = (20, 22, 28)   # 亮区外乘性压暗后的颜色(越小越黑)
NIGHT_BEAM_RGB = (240, 236, 205)  # 手电光锥的颜色(暖白)
NIGHT_TINT = (150, 235, 170)  # 夜视仪亮区的偏色(微绿)
NIGHT_AMBIENT_TINT = (120, 126, 140)   # 脚边微光的颜色(偏冷灰)
NIGHT_BEAM_STEPS = 26       # 光锥圆弧的采样点数
HOSTAGE_COUNT = 4          # 人质数量
HOSTAGE_ENEMIES = 20       # 人质模式的敌人数量下限(地图上的刷新点按房间均匀布置)
ALLY_COUNT = 3             # 队友数量
ALLY_HP = 130
ALLY_DMG = 13
ALLY_RANGE = 520
HOSTAGE_RESCUE_TIME = 2.5  # 解救人质引导时间(秒)
REVIVE_TIME = 2.0          # 拉起倒地球友的引导时间(秒)
INTERACT_RANGE = 64        # 人质/队友交互距离(像素)

# ---------- 突袭模式(强攻敌人老巢) ----------
# 独立模式:固定强度(不走 简单/封锁/强化封锁 三档),系统配发装备,友军支援要花积分
ASSAULT_ENEMIES = 50       # 大本营守军数量(固定)
ASSAULT_ALLIES = 10        # 突击队队友数量
ASSAULT_PLANT_TIME = 3.5   # 安放 C4 的引导时间(秒)
ASSAULT_START_POINTS = 10  # 开局支援积分
ASSAULT_RESERVE_AMMO = 240 # 配发装备的备弹
# 击杀守军获得支援积分(按兵种给分)
ASSAULT_KILL_POINTS = {"melee": 1, "pistol": 1, "shotgun": 2, "ar": 2}
# 突袭模式固定强度(不是给玩家选的难度档;name 只用于 HUD 显示)
ASSAULT_DIFF = dict(name="突袭", hp=1.0, dmg=0.85, spread=1.15, rof=1.15,
                    view=0.95, speed=0.95, scavs=ASSAULT_ENEMIES, rolls=2,
                    loot=1.0, desc="大本营守军(固定强度)", loot_desc="弹药补给")

# ---------- C4(突袭模式拆设施用的炸药) ----------
C4_FUSE = 25.0             # 安放后 25 秒起爆
C4_BLAST_RADIUS = 170      # 起爆半径(像素,约 5 格):范围内单位一律吃伤害
C4_UNIT_DMG = 420          # 对人员的伤害(按爆炸规则:没 6 级甲会被一炮带走)
C4_STRUCT_DMG = 1400       # 对设施的伤害(一次就够炸毁)
C4_PLANT_RANGE = 64        # 能安放 C4 的距离

# ---------- 设施(指挥所/通讯室/弹药库):能炸也能修 ----------
STRUCT_INFO = {
    "command": dict(label="指挥所", hp=900),
    "comms": dict(label="通讯", hp=900),
    "depot": dict(label="弹药库", hp=900),
}
ALLY_STRUCT_HP = 600       # 我方前沿设施血量(被打坏会停援兵)
STRUCT_BULLET_DMG = 1.0    # 枪弹对设施的基础伤害(效率远不如 C4)
STRUCT_BULLET_MUL = 0.10   # 再按子弹伤害加成
REPAIR_RATE = 14.0         # 每个修理单位每秒修多少血
REPAIR_RANGE = 60          # 站多近才能修
REPAIR_MAX_WORKERS = 2     # 一座设施最多几个人同时修
REPAIR_SEARCH = 900        # 只派这个距离内的人去修

# ---------- 援兵(突袭模式) ----------
# 敌方:通讯塔 + 指挥官 都还在 -> 援兵源源不断;任意一个没了就断
ENEMY_REINF_INTERVAL = 22.0
ENEMY_REINF_SQUAD = 4
ENEMY_REINF_CAP = 62       # 场上守军上限(含头目/手下)
ENEMY_REINF_MIN_DIST = 620 # 援兵不会空降在玩家脸上
# 我方:前沿指挥所 + 前沿通讯室 都还在 -> 队友也不断补进来
ALLY_REINF_INTERVAL = 26.0
ALLY_REINF_SQUAD = 1
ALLY_REINF_CAP = 14
# 敌方总指挥部的反应:前沿守军全灭(= 前沿失联)后多久察觉异常,然后派检修队来查/修
HQ_REACTION_DELAY = 30.0     # 守军全灭后 30 秒,总指挥部察觉异常
HQ_REACTION_SQUAD = 3        # 检修队人数(带枪的工兵)
HQ_REACTION_COOLDOWN = 30.0  # 两次反应之间的最短间隔
REBUILD_RATE = 40.0          # 检修队重建被炸毁设施的速度(每秒回多少血)

# 需要摧毁的指挥设施:地图标记 -> 名称
OBJECTIVES = {"O": "指挥所", "P": "弹药库", "Q": "通讯站"}
# 我方的前沿设施(突袭模式):通讯室被打坏,队友会去修
ALLY_STRUCTURES = {"o": "前沿指挥所", "q": "前沿通讯室"}
# 设施角色(决定谁是"援兵开关")
STRUCT_ROLE = {"O": "command", "P": "depot", "Q": "comms",
               "o": "command", "q": "comms"}
# 系统配发装备(突袭模式):武器池 / 顶级配件 / 护甲 / 背包 / 药品
# 只挑配件槽位齐全的枪,保证"满配件";每种槽位都给最好的那件
ISSUE_WEAPONS = ["m4a1", "akm", "ak74", "mp5", "vector", "asval", "m700"]
ISSUE_ATTACH = {"mag": "mag_drum_big", "grip": "grip_ang",
                "laser": "laser_ir", "stock": "stock_heavy",
                "light": "flashlight_pro"}
ISSUE_ARMORS = ["bt201", "b45", "b23", "zhuk", "korund"]
ISSUE_PACKS = ["pack_xl", "pack_large"]
ISSUE_MEDS = ["surgery", "ai2", "syringe", "medkit"]
# 友军支援:花钱(积分)呼叫,延迟后落在指定区域
SUPPORT_ORDER = ["airstrike", "barrage", "recon"]
SUPPORT = {
    "airstrike": dict(name="空袭", cost=8, cd=50.0, delay=3.2, radius=210,
                      dmg=260, bombs=3, scatter=80,
                      desc="航空炸弹 · 大范围高伤"),
    "barrage": dict(name="炮火覆盖", cost=6, cd=35.0, delay=2.2, radius=165,
                    shells=10, gap=0.34, dmg=115, scatter=115,
                    desc="持续炮击一片区域"),
    "recon": dict(name="无人机侦察", cost=4, cd=30.0, delay=1.2, dur=14.0,
                  desc="短时标记全部守军"),
}

# ---------- 固定强度的模式(不给难度档) ----------
# 人质解救 = 强化封锁强度;夜战 = 强化封锁(用户要求:太亮/太简单就没意思)
MODE_DIFF = {"hostage": "hardened", "night": "hardened"}

# ---------- 剧情模式《灰区二日》 ----------
# 独立模式:固定强度,两天 × 四时段,每个时段出击一次
STORY_DIFF = dict(name="剧情", hp=0.95, dmg=0.85, spread=1.15, rof=1.15,
                  view=0.95, speed=0.95, scavs=22, rolls=2, loot=1.05,
                  desc="封锁区守军(固定强度)", loot_desc="城区物资")
STORY_TIMES = [12 * 60, 12 * 60, 10 * 60, 8 * 60]   # 各时段出击时限(按 period 取)
STORY_FINAL_TIME = 10 * 60      # 最终撤离:最后十分钟
STORY_WANTED_BONUS = 6          # 每级通缉给敌人数量加多少
STORY_INTERACT = 64             # 剧情交互距离(和搜刮一致)

# ---------- 背包卷起(省仓库格子) ----------
# 展开占格不超过 4×4 的包,卷起来只占 1×2;5×5 及以上的占 2×2
PACK_ROLL_SMALL = (1, 2)
PACK_ROLL_BIG = (2, 2)
PACK_ROLL_MAX_DIM = 4        # 展开时最大边长 <= 这个值 -> 卷成 1×2

# ---------- 我方弹药库(突袭模式前沿补给) ----------
ALLY_SUPPLY = {"A": "前沿弹药库"}
SUPPLY_RESERVE_CAP = 240     # 弹药库最多给你攒到多少发备弹
SUPPLY_GIVE = 120            # 每次补给给多少发(受上限限制)
SUPPLY_COOLDOWN = 5.0        # 补给冷却(秒)
SUPPLY_RANGE = 76            # 站多近才能补给

# ---------- 任务系统(教官 / 医疗部门 / 后勤部门) ----------
DEPTS = [("instructor", "教官"), ("medical", "医疗部门"), ("logistics", "后勤部门")]
# 教官的任务:kind 决定进度怎么涨(在 game.py 的战局结算里累计)
# reward: rubles 给钱 / weapons 给枪 / attachments 给配件 / ammo 给子弹
TASKS = [
    dict(id="t1", name="清剿行动", desc="击杀 5 名拾荒者", kind="kills", need=5,
         reward=dict(rubles=30000, ammo=[("a9", 60)])),
    dict(id="t2", name="活着回来", desc="成功撤离 3 次", kind="extracts", need=3,
         reward=dict(rubles=40000, attachments=["mag_ext"])),
    dict(id="t3", name="深入敌后", desc="累计带回价值 30 万的物资", kind="value", need=300000,
         reward=dict(rubles=50000, attachments=["grip_vert"])),
    dict(id="t4", name="救出人质", desc="完成 1 次人质解救(救满 4 人并撤离)",
         kind="hostage_win", need=1, reward=dict(rubles=80000, weapons=["m4a1"])),
    dict(id="t5", name="要塞攻坚", desc="完成 1 次突袭(炸毁 3 座设施并撤离)",
         kind="assault_win", need=1,
         reward=dict(rubles=150000, weapons=["pkp"], attachments=["stock_heavy"])),
    dict(id="t6", name="弹如雨下", desc="累计击杀 30 名拾荒者", kind="kills", need=30,
         reward=dict(rubles=120000, ammo=[("a545", 120), ("a12db", 40)])),
    dict(id="t7", name="长期合同", desc="每击杀 10 名拾荒者就能结一次账", kind="kills",
         need=10, reward=dict(rubles=25000), repeat=True),
]
# 医疗部门:把局内捡到的材料交上去换药品
MED_BARTERS = [
    dict(id="m1", name="绷带 ×2 → 止痛药", need=[("bandage", 2)], out=[("painkiller", 1)]),
    dict(id="m2", name="胶带 ×2 + 螺丝刀 → 军用医疗包",
         need=[("tape", 2), ("screwdriver", 1)], out=[("medkit", 1)]),
    dict(id="m3", name="止血带 + 绷带 ×3 → 肾上腺素",
         need=[("tourniquet", 1), ("bandage", 3)], out=[("syringe", 1)]),
    dict(id="m4", name="滤毒罐 + 继电器 → AI-2 医疗包",
         need=[("filter", 1), ("relay", 1)], out=[("ai2", 1)]),
    dict(id="m5", name="精密工具组 + 肾上腺素 → 外科手术包",
         need=[("tools", 1), ("syringe", 1)], out=[("surgery", 1)]),
]
# 后勤部门:材料换装备 / 弹药 / 配件
LOG_BARTERS = [
    dict(id="l1", name="螺丝盒 ×2 + 扳手 → 加长弹夹",
         need=[("screws", 2), ("wrench", 1)], out=[("mag_ext", 1)]),
    dict(id="l2", name="电线卷 ×2 + 继电器 → 战术激光",
         need=[("wire", 2), ("relay", 1)], out=[("laser_tac", 1)]),
    dict(id="l3", name="电动机 + 汽车电池 → 弹鼓",
         need=[("motor", 1), ("battery", 1)], out=[("mag_drum", 1)]),
    dict(id="l4", name="燃油罐 ×2 + 精密工具组 → 5 级甲(钴蓝)",
         need=[("fuelcan", 2), ("tools", 1)], out=[("korund", 1)]),
    dict(id="l5", name="军用水壶 + 咖啡罐 ×2 → 5.45 穿甲弹 ×120",
         need=[("canteen", 1), ("coffee", 2)], out=[("a545", 120)]),
    dict(id="l6", name="示波器 + 显卡 → 空降兵重型背包",
         need=[("oscilloscope", 1), ("gpu", 1)], out=[("pack_xl", 1)]),
]
DEPARTMENT_BARTERS = {"medical": MED_BARTERS, "logistics": LOG_BARTERS}

# ---------- 手机(触屏)模式 ----------
TOUCH = dict(
    stick_zone=0.52,        # 屏幕左侧多少比例是移动摇杆区
    stick_radius=118,       # 摇杆最大拖动半径(像素)
    aim_assist_range=560,   # 辅助瞄准:自动锁敌范围(像素)
    aim_assist=True,        # 触屏模式默认开启自动锁敌
)


def trade_cat_match(iid, key):
    """商品是否属于某个分区。"""
    d = ITEMS[iid]
    if key is None:
        return True
    if key == "special":
        return bool(d.get("boss_only"))
    if key == "weapon":
        return d["cat"] == "weapon" and not d.get("boss_only")
    return d["cat"] == key


# ---------- 拾荒战利品表 (iid, 最大数量, 权重) ----------
LOOT = {
    # 补给箱:以杂物为主,金色物品概率被摊薄
    "crate": [("a9", 30, 10), ("a545", 30, 8), ("a12db", 20, 8), ("bandage", 1, 10),
              ("medkit", 1, 4), ("gold", 1, 3), ("cpu", 1, 2), ("pm", 1, 3),
              ("mp5", 1, 3), ("paca", 1, 2), ("pack_small", 1, 3), ("pack_mid", 1, 2),
              # 杂物(权重高,产出多)
              ("coffee", 1, 12), ("lighter", 1, 11), ("screwdriver", 1, 12),
              ("tape", 1, 11), ("screws", 1, 10), ("plug", 1, 10),
              ("flashlight", 1, 9), ("wire", 1, 9), ("hose", 1, 8),
              ("wrench", 1, 8), ("relay", 1, 7), ("shampoo", 1, 6),
              ("canteen", 1, 6), ("calculator", 1, 6), ("clock", 1, 5),
              ("battery", 1, 5), ("filter", 1, 4), ("fuelcan", 1, 3),
              ("oscilloscope", 1, 3), ("motor", 1, 3), ("solar", 1, 1)],
    "med": [("bandage", 1, 16), ("medkit", 1, 9), ("a9", 30, 5),
            ("painkiller", 1, 10), ("tourniquet", 1, 8), ("syringe", 1, 6),
            ("ai2", 1, 3), ("surgery", 1, 1),
            ("shampoo", 1, 10), ("coffee", 1, 8), ("screwdriver", 1, 6),
            ("filter", 1, 5), ("wire", 1, 5), ("canteen", 1, 4)],
    "gun": [("pm", 1, 6), ("mp133", 1, 7), ("mp5", 1, 6), ("ak74", 1, 5),
            ("m4a1", 1, 3), ("akm", 1, 3), ("m700", 1, 2), ("m139", 1, 1),
            ("a9", 30, 6), ("a545", 30, 7), ("a12db", 20, 5), ("a12ap", 20, 4),
            ("a556", 30, 4), ("a762", 30, 4), ("a54r", 20, 3), ("a762x45", 30, 2),
            ("a939", 30, 2), ("a45", 30, 2),
            ("mag_ext", 1, 4), ("grip_vert", 1, 4), ("laser_tac", 1, 3),
            ("stock_tac", 1, 3), ("mag_drum", 1, 2), ("grip_ang", 1, 2),
            ("fort", 1, 2), ("wrench", 1, 6), ("tape", 1, 6), ("screws", 1, 6),
            ("relay", 1, 5), ("flashlight", 1, 5), ("flashlight_pro", 1, 2),
            ("hose", 1, 4),
            # 扩展枪械:军械箱里只少量出(权重压低,别把老枪/弹药稀释掉)
            ("g17", 1, 2), ("m9a3", 1, 2), ("t54", 1, 2), ("m1911", 1, 2),
            ("m3a1", 1, 2), ("mp40", 1, 2), ("uzi", 1, 2), ("t79", 1, 2),
            ("mac10", 1, 1), ("mp9", 1, 1), ("mpx", 1, 1), ("ump45", 1, 1),
            ("pp19", 1, 1), ("p90", 1, 1), ("g18c", 1, 1), ("f57", 1, 1),
            ("m45a1", 1, 1), ("m300", 1, 1), ("t05", 1, 1), ("cz52", 1, 1),
            ("m870", 1, 2), ("spr310", 1, 1), ("s12k", 1, 1), ("usas12", 1, 1),
            ("ar15", 1, 2), ("ak74u", 1, 2), ("aks74u", 1, 2), ("g36", 1, 1),
            ("ak102", 1, 1), ("sks", 1, 2), ("sa85m", 1, 1), ("mini14", 1, 1),
            ("adar215", 1, 1), ("m96", 1, 1), ("svtu", 1, 1), ("hunter", 1, 1),
            ("arx160", 1, 1), ("t03", 1, 1), ("qc61", 1, 1), ("9a91", 1, 1),
            ("t951", 1, 1), ("vss", 1, 1), ("svds", 1, 1), ("mosin", 1, 1),
            ("m14", 1, 1), ("m24", 1, 1), ("t88", 1, 1), ("bm59", 1, 1),
            ("hk416", 1, 1), ("ak12", 1, 1), ("aug", 1, 1), ("f2000", 1, 1),
            ("scar_l", 1, 1), ("mdr", 1, 1), ("sg550", 1, 1), ("mcx", 1, 1),
            ("a545r", 1, 1), ("an94", 1, 1), ("qbz191", 1, 1), ("aek", 1, 1),
            ("ace31", 1, 1), ("fal", 1, 1), ("g3", 1, 1), ("scar_h", 1, 1),
            ("scar_hamr", 1, 1), ("groza", 1, 1), ("mk14", 1, 1), ("m110", 1, 1),
            ("sj16", 1, 1), ("ax50", 1, 1), ("rpk16", 1, 1), ("evolys", 1, 1),
            ("negev7", 1, 1), ("deagle", 1, 1), ("deagle_gold", 1, 1),
            # 新弹种
            ("a762x51", 30, 4), ("a58", 30, 4), ("a762x25", 30, 5),
            ("a57", 30, 3), ("a50", 5, 2)],
    # 保险箱:值钱货与高阶杂物(金色物品仍是最稀有的);5 级甲小概率开出
    "val": [("gold", 1, 5), ("cpu", 1, 4), ("btc", 1, 1), ("vase", 1, 2),
            ("b45", 1, 2), ("bt201", 1, 1), ("pack_large", 1, 2), ("pack_xl", 1, 1),
            ("b23", 1, 2), ("zhuk", 1, 2), ("korund", 1, 2),
            ("gpu", 1, 4), ("motor", 1, 4), ("oscilloscope", 1, 4), ("tools", 1, 2),
            ("solar", 1, 2), ("filter", 1, 3), ("fuelcan", 1, 3),
            ("nvg_pnv", 1, 2), ("nvg_gpnvg", 1, 1),
            ("clock", 1, 4), ("calculator", 1, 3), ("battery", 1, 3)],
}

CONTAINER_INFO = {
    # kind -> (名称, 容器格宽, 格高)
    "crate": ("补给箱", 5, 3),
    "med": ("医疗箱", 3, 2),
    "gun": ("军械箱", 4, 3),
    "val": ("保险箱", 3, 2),
    "corpse": ("尸体", 4, 3),
    "boss_corpse": ("头目尸体", 8, 5),
    "ground": ("地面", 8, 5),   # 丢在地上的东西:要放得下大枪/重甲
}
