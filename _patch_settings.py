# -*- coding: utf-8 -*-
"""临时脚本:把 settings.py 里旧的地图构建段替换为 maps.py 引用 + 头目/新装备定义。"""
import io

p = "settings.py"
src = io.open(p, encoding="utf-8").read()

start = src.index("# ---------- 地图 ----------")
end_anchor = src.index("EXTRACT_NAMES = {")
end = src.index("\n", src.index("}", end_anchor)) + 1

new_block = '''# ---------- 地图(三张地图见 maps.py) ----------
from maps import MAPS, MAP_ORDER, MAP_W, MAP_H

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
})

# 交易所新增:5 级甲与头目弹种(专属枪械不上架,只能打头目爆)
TRADE_GOODS += [("b23", 1), ("zhuk", 1), ("korund", 1),
                ("a939", 30), ("a45", 30)]

'''

out = src[:start] + new_block + src[end:]
io.open(p, "w", encoding="utf-8", newline="").write(out)
print(f"patched: {len(src)} -> {len(out)} chars")
