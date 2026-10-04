# -*- coding: utf-8 -*-
"""Tarkov2D 全局配置:常量、物品定义、地图、拾荒者定义。"""
import pygame

# ---------- 版本与更新 ----------
GAME_VERSION = "1.1.2"
# 更新清单地址(可换成自建服务器 / GitHub raw;留空则只认 EXE 同目录的 version.json)
UPDATE_MANIFEST_URL = "http://127.0.0.1:8765/version.json"
UPDATE_TIMEOUT = 3   # 检查 / 下载超时(秒)

# ---------- 基础常量 ----------
W, H = 1280, 720
FPS = 60
TILE = 32
RAID_TIME = 12 * 60          # 战局时长(秒)
EXTRACT_TIME = 3.0           # 撤离引导(秒)
INTERACT_DIST = 56           # 搜刮交互距离(像素)
STASH_W, STASH_H = 10, 8     # 藏身处仓库
BAG_W, BAG_H = 4, 2          # 无背包时的口袋容量(装备背包后按 grid 扩容)

PLAYER = dict(hp=100, speed=235, walk=115, radius=12)

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
                f = pygame.font.Font(path, size)
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
            f = pygame.font.Font(None, size)
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

# 机密文件:天价孤品,仅在「强化封锁」的保险箱里固定刷出
CLASSIFIED = "doc"
ITEMS[CLASSIFIED] = dict(name="机密文件", cat="misc", w=1, h=1,
                         color=(240, 232, 190), price=10000000000)
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

# 交易站分区:(标签名, 分区键;None = 全部)
TRADE_TABS = [("全部", None), ("枪械", "weapon"), ("特殊枪械", "special"), ("配件", "attach"),
              ("护甲", "armor"), ("背包", "pack"), ("子弹", "ammo"),
              ("药品", "med")]
TRADE_PAGE_H = 450      # 商品区可见高度(像素);超出时用滚轮翻看

# ---------- 枪械配件 ----------
# slot: mag 弹夹 / grip 前握把 / laser 激光 / stock 后握把
# 效果:mag_bonus 加弹容;brace_mul 架枪散布倍率(越小越准);hip_mul 腰射散布倍率
ATTACH_SLOTS = {"mag": "弹夹", "grip": "前握把", "laser": "激光", "stock": "后握把"}
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
})

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
    "pm": [], "mp5": ["mag", "grip", "laser", "stock"],
    "mp133": ["mag", "grip", "laser"],
    "ak74": ["mag", "grip", "laser", "stock"],
    "m4a1": ["mag", "grip", "laser", "stock"],
    "akm": ["mag", "grip", "laser", "stock"],
    "m700": ["mag", "laser", "stock"],
    "m139": [], "asval": ["mag", "grip", "laser"],
    "vector": ["mag", "grip", "laser", "stock"],
    "pkp": ["laser"], "rpg": [], "rpg2": [],
}


def weapon_slots(iid):
    return WEAPON_SLOTS.get(iid, [])


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

# ---------- 游戏模式 ----------
MODES = {
    "raid": dict(name="搜打撤", desc="自由搜刮 · 找撤离点撤离"),
    "hostage": dict(name="人质解救", desc="室内近战 · 20 名匪徒分守八间房 · 救出 4 名人质"),
}
MODE_ORDER = ["raid", "hostage"]
HOSTAGE_COUNT = 4          # 人质数量
HOSTAGE_ENEMIES = 20       # 人质模式的敌人数量下限(地图上的刷新点按房间均匀布置)
ALLY_COUNT = 3             # 队友数量
ALLY_HP = 130
ALLY_DMG = 13
ALLY_RANGE = 520
HOSTAGE_RESCUE_TIME = 2.5  # 解救人质引导时间(秒)
REVIVE_TIME = 2.0          # 拉起倒地球友的引导时间(秒)
INTERACT_RANGE = 64        # 人质/队友交互距离(像素)

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
            ("relay", 1, 5), ("flashlight", 1, 5), ("hose", 1, 4)],
    # 保险箱:值钱货与高阶杂物(金色物品仍是最稀有的);5 级甲小概率开出
    "val": [("gold", 1, 5), ("cpu", 1, 4), ("btc", 1, 1), ("vase", 1, 2),
            ("b45", 1, 2), ("bt201", 1, 1), ("pack_large", 1, 2), ("pack_xl", 1, 1),
            ("b23", 1, 2), ("zhuk", 1, 2), ("korund", 1, 2),
            ("gpu", 1, 4), ("motor", 1, 4), ("oscilloscope", 1, 4), ("tools", 1, 2),
            ("solar", 1, 2), ("filter", 1, 3), ("fuelcan", 1, 3),
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
    "ground": ("地面", 3, 2),
}
