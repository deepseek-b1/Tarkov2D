# -*- coding: utf-8 -*-
"""剧情模式《灰区二日》:剧本数据 + 状态机。

两天 × 四个时段(黎明/正午/黄昏/午夜),每个时段出击一次;
第一天收集三块数据板,第二天才有资格选边站。状态存在 sd.story(dict),
由 save.py 一起序列化;与坐标相关的关键点全部取自 maps.CITY_AT / CITY_NPC,
地图打点和剧本共用一份数据,不会写岔。
"""
from maps import CITY_AT, CITY_NPC

PERIODS = ["黎明", "正午", "黄昏", "午夜"]
WOLF_TRUST = 2              # 灰狼信任到这个值 = "信任"(解锁下水道/铁路隧道)
WANTED_MAX = 2              # 通缉等级上限(越高路上守军越多)
ENDING_ORDER = ["F", "A", "B", "C", "D", "E"]


# ---------------- 状态 ----------------
def init_state():
    return dict(day=1, period=0, done=[], flags={}, boards=0, tapes=0,
                wolf=0, erin=0, wanted=0, sophia_alive=True, route=None,
                final=None, ending=None, endings=[], deployments=0)


def st(sd):
    """取(必要时建立)剧情状态。"""
    s = getattr(sd, "story", None)
    if not isinstance(s, dict) or "day" not in s:
        sd.story = init_state()
        s = sd.story
    # 老档补字段
    for k, v in init_state().items():
        s.setdefault(k, v)
    return s


def flag(sd, key):
    return bool(st(sd)["flags"].get(key))


# ---------------- 开局补给 ----------------
# 剧情模式的最低保障:按原设定"开局只有手枪",但绝不能让你空手进封锁区
STARTER_WEAPON = "pm"
STARTER_AMMO = 30
STARTER_MED = "bandage"

# ---------------- 剧情模式的系统配发 ----------------
# 进封锁区由系统配发:突击步枪 + 6 级甲 + 背包 + 弹药 + 药品;
# 撤离/阵亡后一律回收(玩家自己的仓库与出战配置原样还原,互不影响)。
ISSUE_WEAPON = "m4a1"
ISSUE_AMMO = "a556"
ISSUE_AMMO_COUNT = 180
ISSUE_ARMOR = "b45"
ISSUE_PACK = "pack_mid"
ISSUE_MEDS = ["medkit", "medkit", "bandage"]


def issue_kit(sd):
    """系统配发剧情装备(覆盖当前出战配置)。返回配发清单(给提示用)。"""
    from inventory import Container, Item
    from settings import ITEMS, pack_grid
    weapon = Item.weapon(ISSUE_WEAPON)          # 满弹匣
    armor = Item(ISSUE_ARMOR)
    pack = Item(ISSUE_PACK)
    sd.weapon, sd.armor, sd.pack = weapon, armor, pack
    sd.bag = Container(*pack_grid(pack.iid))
    got = [weapon.name, armor.name, pack.name]
    left = int(ISSUE_AMMO_COUNT)
    stack = ITEMS[ISSUE_AMMO].get("stack", 120)
    while left > 0:
        take = min(left, stack)
        if not sd.bag.add_item(Item(ISSUE_AMMO, count=take)):
            break
        left -= take
    got.append(f"{ITEMS[ISSUE_AMMO]['name']} ×{ISSUE_AMMO_COUNT - max(0, left)}")
    for mid in ISSUE_MEDS:
        sd.bag.add_item(Item(mid))
    return got


def bank_loot(sd):
    """撤离结算:把背包里的东西尽量塞进仓库。返回 (进仓库件数, 放不下件数)。"""
    kept = lost = 0
    for placed in list(sd.bag.items):
        if sd.stash.add_item(placed.item):
            sd.bag.remove_placed(placed)
            kept += 1
        else:
            lost += 1
    return kept, lost


def ensure_kit(sd):
    """保证这一局能打:没武器就给手枪,缺弹就补弹,没药就发绷带,没包就给小包。

    只在"缺"的时候补,所以不会每局白送;返回本次补了什么(给提示用)。
    """
    from inventory import Item
    from settings import (weapon_ammo_ids, ITEMS, POCKETS, pack_grid)
    got = []
    if sd.weapon is None:
        sd.weapon = Item.weapon(STARTER_WEAPON)      # 满弹匣
        got.append(sd.weapon.name)
    if sd.pack is None:
        sd.pack = Item("pack_small")
        sd.apply_pack()
        got.append(sd.pack.name)
    ids = weapon_ammo_ids(sd.weapon) if sd.weapon is not None else []
    have = sum(pl.item.count for pl in sd.bag.items if pl.item.iid in ids)
    if ids and have < 10:
        iid = ids[0]
        want = int(STARTER_AMMO)
        while want > 0:
            take = min(want, ITEMS[iid].get("stack", 120))
            if not sd.bag.add_item(Item(iid, count=take)):
                break
            want -= take
        got.append(f"{ITEMS[iid]['name']} ×{STARTER_AMMO - max(0, want)}")
    if not any(pl.item.cat == "med" for pl in sd.bag.items):
        if sd.bag.add_item(Item(STARTER_MED)):
            got.append(ITEMS[STARTER_MED]["name"])
    return got


def set_flag(sd, key, val=True):
    st(sd)["flags"][key] = bool(val)


def wolf_trust(sd):
    return st(sd)["wolf"]


def wolf_state(sd):
    w = wolf_trust(sd)
    if w < 0:
        return "敌对"
    return "信任" if w >= WOLF_TRUST else "中立"


def wanted_state(sd):
    return ["无", "低", "高"][max(0, min(WANTED_MAX, st(sd)["wanted"]))]


# ---------------- 12 份录音的内容 ----------------
# 捡到录音时会在屏幕下方出一串字幕(像无线电里放出来的原话)
TAPES = [
    "录音 1:「……黎明协议第一阶段启动,撤离通道只对名单内人员开放。」",
    "录音 2:「样本编号 07 在志愿者身上生效,受试者 40 分钟后停止反抗。」",
    "录音 3:「艾琳医生要求把先遣小队送进去。她说这是必要的代价。」",
    "录音 4:「灰狼带着两百多人堵在北检查站,放他们进来会失控。」",
    "录音 5:「维克托指挥官下令:名单外人员一律按污染源处理。」",
    "录音 6:「我们不是救人,我们是在清点。别问了。」",
    "录音 7:「索菲亚把原始数据藏了一份 —— 她说总有人要记得。」",
    "录音 8:「信使又在两头跑了。这种人不该知道协议的事。」",
    "录音 9:「地下的东西会模仿声音。听到自己的声音时,别回答。」",
    "录音 10:「平民的撤离申请全部驳回。理由:无编号。」",
    "录音 11:「高层要的是样本,不是真相。真相会跟着这座城市一起封掉。」",
    "录音 12:「如果你听到这段,说明你已经到过地下。快走,别回头。」",
]

# 选择对应的剧情演出(按写下的标记匹配:救/杀/给药/拒绝/抢夺…)
CHOICE_FX = {
    "saved_captives": ("rescue", "灰狼信任 +1 · 下水道情报到手"),
    "left_captives": ("shoot", "黑曜石暂时不会通缉你"),
    "gave_meds": ("aid", "灰狼信任 +2 · 解锁救援线"),
    "refused_meds": ("refuse", "医疗物资留在了你手里"),
    "robbed_wolf": ("rob", "灰狼敌对 · 第二天可能被伏击"),
    "killed_courier": ("shoot", "黑曜石线断裂 · 索菲亚存活"),
    "freed_courier": ("track", "你悄悄跟上了信使"),
    "handed_wolf": ("aid", "灰狼信任 +3 · 艾琳敌对"),
    "handed_erin": ("refuse", "艾琳线继续 · 灰狼敌对"),
}


def tape_line(i):
    """第 i 份录音(0 起)的字幕。"""
    return TAPES[max(0, min(len(TAPES) - 1, i))]


def erin_state(sd):
    return "怀疑" if st(sd)["erin"] < 0 else "正常"


def mark_done(sd, oid):
    s = st(sd)
    if oid not in s["done"]:
        s["done"].append(oid)


def is_done(sd, oid):
    return oid in st(sd)["done"]


# ---------------- 目标 ----------------
def obj(oid, name, at, kind="search", **kw):
    """一个剧情目标。at = CITY_AT 的键;kind = take/search/download/plant/talk/kill。"""
    d = dict(id=oid, name=name, at=at, kind=kind, need=2.0)
    d.update(kw)
    return d


def at_pos(key):
    """关键点像素坐标(地图上的 K 点);也认 NPC 站位。

    'tapes' 是一串坐标,不支持整串取位置(要用 CITY_AT['tapes'][i])。
    """
    if key not in CITY_AT:
        x, y = CITY_NPC[key]
    else:
        val = CITY_AT[key]
        if isinstance(val, list):
            raise ValueError(f"'{key}' 是一串坐标,别用 at_pos;取 CITY_AT['{key}'][i]")
        x, y = val
    return x * 32 + 16, y * 32 + 16


# 每个时段都能顺手收集的 12 份录音
def tape_objectives(sd):
    out = []
    for i, (x, y) in enumerate(CITY_AT["tapes"]):
        oid = f"tape{i + 1}"
        if is_done(sd, oid):
            continue
        out.append(obj(oid, f"录音 {i + 1}/12", "tapes", kind="take",
                       need=1.2, tape_index=i, effects=dict(tapes=1)))
    return out


MISSIONS = {
    (1, 0): dict(
        id="d1_1", title="D1-1 残骸", place="北检查站 · 坠机点",
        brief=[("艾琳", "渡鸦,如果你还活着,听好。你只有两天。"),
               ("艾琳", "第一天找到三块数据板,第二天你才有资格选择站在哪一边。")],
        objects=[
            obj("d1_1_squad", "搜索先遣小队尸体", "squad", kind="search", need=2.5,
                effects=dict(dialogue="d1_1_squad")),
            obj("d1_1_blue", "找到蓝卡", "bluecard", kind="take", need=1.5,
                effects=dict(items=["蓝卡"])),
            obj("d1_1_radio", "修复初级电台", "radio_broken", kind="download",
                need=4.0, effects=dict(dialogue="d1_1_radio")),
            obj("d1_1_captives", "处理被俘的拾荒者", "captives", kind="talk",
                dialogue="d1_1_captives"),
        ]),
    (1, 1): dict(
        id="d1_2", title="D1-2 旧医院", place="卡斯卡德旧医院",
        brief=[("艾琳", "医院里还有疫苗原料和医疗记录,去把它们带出来。")],
        objects=[
            obj("d1_2_rec", "取得医疗记录", "records", kind="take", need=2.0,
                effects=dict(dialogue="d1_2_rec")),
            obj("d1_2_vac", "找到疫苗原料", "vaccine", kind="take", need=2.0,
                effects=dict(items=["疫苗原料"])),
            obj("d1_2_wolf", "与灰狼手下接触", "wolf_men", kind="talk",
                dialogue="d1_2_wolf"),
        ]),
    (1, 2): dict(
        id="d1_3", title="D1-3 港口仓库", place="卡斯卡德港口",
        brief=[("艾琳", "黑曜石正在仓库转移样本。把第一块数据板拿回来。")],
        objects=[
            obj("d1_3_radio", "取得加密电台", "encrypted_radio", kind="take",
                need=2.0, effects=dict(items=["加密电台"])),
            obj("d1_3_board", "获取第一块数据板", "board1", kind="download",
                need=4.5, effects=dict(boards=1, dialogue="d1_3_board")),
            obj("d1_3_safe", "支线:铁钉的保险箱", "safe_iron", kind="search",
                need=3.0, effects=dict(dialogue="d1_3_safe")),
        ]),
    (1, 3): dict(
        id="d1_4", title="D1-4 地下实验室入口", place="地铁隧道深处",
        brief=[("索菲亚", "黎明协议不是撤离计划。样本不是武器,是控制工具。")],
        objects=[
            obj("d1_4_b2", "下载第二块数据板", "board2", kind="download",
                need=4.5, effects=dict(boards=1)),
            obj("d1_4_b3", "下载第三块数据板", "board3", kind="download",
                need=4.5, effects=dict(boards=1)),
            obj("d1_4_tape", "找到索菲亚的录音", "sophia_tape", kind="take",
                need=2.0, effects=dict(tapes=1, dialogue="d1_4_tape")),
            obj("d1_4_echo", "处理变异体「回声体」", "echo", kind="kill",
                boss="echo"),
        ]),
    (2, 0): dict(
        id="d2_1", title="D2-1 路线选择", place="卡斯卡德 · 第二天黎明",
        brief=[("艾琳", "把数据带到天线阵列。广播出去,整座城才有救。"),
               ("灰狼", "别听她的……学校里有三百个平民。你先来救人。"),
               ("维克托", "渡鸦,把样本交给我。我给你钱、直升机、新身份。"),
               ("索菲亚", "他们都骗了你。来实验室,我告诉你黎明协议真正的目标。")],
        objects=[
            obj("d2_1_a", "路线A:前往黑曜石指挥中心", "pass_card", kind="talk",
                dialogue="d2_1_routeA"),
            obj("d2_1_b", "路线B:前往灰区营地", "tnt", kind="talk",
                dialogue="d2_1_routeB"),
            obj("d2_1_c", "路线C:前往地下实验室", "sample", kind="talk",
                dialogue="d2_1_routeC"),
        ]),
    (2, 1): dict(
        id="d2_2", title="D2-2 旧教堂会谈", place="卡斯卡德旧教堂",
        brief=[("信使", "每个人都想当英雄,直到看见名单上有自己的名字。")],
        objects=[
            obj("d2_2_talk", "参加旧教堂会谈", "church_meet", kind="talk",
                dialogue="d2_2_church"),
        ]),
    (2, 2): dict(
        id="d2_3", title="D2-3 天线阵列", place="电视塔与天线阵列",
        brief=[("艾琳", "天线阵列到了。这一次,由你决定该怎么用那三块数据。")],
        objects=[
            obj("d2_3_antenna", "在阵列前做最后决定", "antenna", kind="talk",
                dialogue="d2_3_final"),
        ]),
    (2, 3): dict(
        id="d2_4", title="D2-4 最终撤离", place="最后十分钟",
        brief=[("艾琳", "最后十分钟,撤离点开放。别死在这里。")],
        objects=[
            obj("d2_4_go", "从任一开放的撤离点离开", "antenna", kind="extract"),
        ]),
}


def mission(sd):
    """当前时段的出击任务(全部时段走完则返回 None)。"""
    s = st(sd)
    if s["ending"]:
        return None
    return MISSIONS.get((s["day"], s["period"]))


def mission_title(sd):
    m = mission(sd)
    if m is None:
        return "剧情已完成"
    return m["title"]


def objectives(sd):
    """当前时段要做的目标(含可选的录音收集)。"""
    m = mission(sd)
    out = []
    if m is not None:
        out.extend(m["objects"])
        if m["id"] in ("d1_1", "d1_2", "d1_3", "d1_4"):
            out.extend(tape_objectives(sd))
    return out


def objective_by_point(sd, x, y):
    """按坐标找当前时段的关键点目标(找不到 = 这里没东西)。"""
    for o in objectives(sd):
        if o["kind"] == "extract":
            continue
        if o["at"] == "tapes":
            tx, ty = CITY_AT["tapes"][o["tape_index"]]
            px, py = tx * 32 + 16, ty * 32 + 16
        else:
            px, py = at_pos(o["at"])
        if abs(px - x) < 20 and abs(py - y) < 20:
            return o
    return None


def dialogues_at(sd, x, y):
    """按坐标找当前时段的 NPC 对白(灰狼/维克托/索菲亚/信使/艾琳会随剧情移动)。"""
    for name, pos in CITY_NPC.items():
        px, py = pos[0] * 32 + 16, pos[1] * 32 + 16
        if abs(px - x) < 20 and abs(py - y) < 20:
            m = mission(sd)
            if m and m["id"] == "d2_1":
                return DIA.get(f"d2_1_npc_{name}")
            return DIA.get(f"npc_{name}")
    return None


def apply_effects(sd, eff):
    """套用目标/选项的效果。"""
    s = st(sd)
    for flag_key in eff.get("flags", []):
        set_flag(sd, flag_key)
    for it in eff.get("items", []):
        if it not in s["flags"].setdefault("items", []):
            s["flags"].setdefault("items", []).append(it)
    s["boards"] = min(3, s["boards"] + int(eff.get("boards", 0)))
    s["tapes"] = min(12, s["tapes"] + int(eff.get("tapes", 0)))
    s["wolf"] = max(-3, min(6, s["wolf"] + int(eff.get("wolf", 0))))
    s["erin"] = max(-2, min(3, s["erin"] + int(eff.get("erin", 0))))
    s["wanted"] = max(0, min(WANTED_MAX, s["wanted"] + int(eff.get("wanted", 0))))
    if eff.get("sophia_alive") is not None:
        s["sophia_alive"] = bool(eff["sophia_alive"])
    if eff.get("route"):
        s["route"] = eff["route"]
    if eff.get("final"):
        s["final"] = eff["final"]


def has_item(sd, name):
    return name in st(sd)["flags"].get("items", [])


# ---------------- 撤离点规则 ----------------
EXTRACT_RULES = {
    "铁路桥": dict(always=True, risk="风险中等"),
    "下水道": dict(need="wolf", risk="风险低"),
    "黑曜石检查站": dict(need="pass", risk="风险高但可伪装"),
    "直升机坪": dict(need="pass_or_viktor", risk="需要通行证或维克托死亡"),
    "铁路隧道": dict(need="wolf_or_tnt", risk="需要灰狼信任或炸药"),
    "港口船只": dict(need="sample", risk="需要索菲亚的样本或伪造文件"),
    "地下管道": dict(need="hidden", risk="隐藏撤离点"),
}


def can_use_extract(sd, name):
    """能不能从这个撤离点走:返回 (是否可用, 原因)。"""
    rule = EXTRACT_RULES.get(name)
    if rule is None:
        return True, ""
    if rule.get("always"):
        return True, rule["risk"]
    need = rule.get("need")
    if need == "wolf":
        ok = wolf_trust(sd) >= WOLF_TRUST
        return ok, "需要灰狼信任" if not ok else "灰狼的人接应"
    if need == "pass":
        ok = has_item(sd, "黑曜石通行证")
        return ok, "需要黑曜石通行证" if not ok else "用通行证伪装通过"
    if need == "pass_or_viktor":
        ok = has_item(sd, "黑曜石通行证") or flag(sd, "viktor_dead")
        return ok, "需要通行证或先干掉维克托"
    if need == "wolf_or_tnt":
        ok = wolf_trust(sd) >= WOLF_TRUST or has_item(sd, "炸药")
        return ok, "需要灰狼信任或炸药"
    if need == "sample":
        ok = has_item(sd, "黎明样本") or flag(sd, "fake_papers")
        return ok, "需要黎明样本或伪造文件"
    if need == "hidden":
        ok = flag(sd, "saved_captives") and st(sd)["tapes"] >= 12
        return ok, "需要第一天救过俘虏并集齐 12 份录音"
    return True, ""


# ---------------- 结局 ----------------
ENDINGS = {
    "A": dict(name="结局A:真相广播",
              line="真相没有救下所有人,但它让这座城不再无名。",
              text="你把三块数据板通过天线阵列广播出去,外界介入。黑曜石撤退,"
                   "城市被国际封锁。平民开始撤离,但你被全球通缉。艾琳失踪,"
                   "灰狼建立起安全区。"),
    "B": dict(name="结局B:黑曜石交易",
              line="你活着离开了。只是名单上多了很多名字。",
              text="你把黎明样本交给维克托,换来巨额报酬和新身份。封锁继续,"
                   "平民被清理,艾琳被处决。你成了黑曜石的承包商。"),
    "C": dict(name="结局C:灰狼救援",
              line="他们叫你英雄。只有你知道,地下的东西还在呼吸。",
              text="你用炸药炸开封锁线,带着平民撤出。样本没有销毁,实验室仍然存在。"
                   "你成了拾荒者口中的英雄,但污染可能扩散。"),
    "D": dict(name="结局D:焦土",
              line="你烧掉了真相,也烧掉了出口。",
              text="你炸毁实验室和天线阵列。样本销毁,数据丢失,维克托死亡。"
                   "城市彻底封锁,幸存者困在灰区,你独自活了下来。"),
    "E": dict(name="结局E:自私撤离",
              line="你卖掉了这座城的最后一天。",
              text="你带着样本独自去了港口,把它卖给神秘买家。所有阵营都在追杀你,"
                   "而买家的身份暗示着更高层的公司。"),
    "F": dict(name="隐藏结局F:黎明之后",
              line="第二天结束了。但黎明之后,才是真正的灰区。",
              text="你救下俘虏、集齐了全部录音、保住了索菲亚、放走信使并一路跟踪他。"
                   "索菲亚告诉你:样本不是病毒,而是神经控制药剂,艾琳才是幕后推手。"
                   "你接管了联络网,成为新的中间人。"),
}


def ending_for(sd):
    """按当前状态判定结局:返回 (键, 结局数据)。"""
    s = st(sd)
    hidden = (flag(sd, "saved_captives") and s["tapes"] >= 12
              and s["sophia_alive"] and not flag(sd, "killed_surrender")
              and flag(sd, "cooling_off") and flag(sd, "tracked_courier"))
    if hidden:
        return "F", ENDINGS["F"]
    final = s.get("final")
    if final == "trade":
        return "B", ENDINGS["B"]
    if final == "rescue":
        return "C", ENDINGS["C"]
    if final == "scorch":
        return "D", ENDINGS["D"]
    if final == "selfish":
        return "E", ENDINGS["E"]
    if final == "truth":
        return "A", ENDINGS["A"]
    return "A", ENDINGS["A"]


# ---------------- 时段结算 ----------------
def settle_period(sd, result):
    """一次出击结束(撤离或阵亡)后的推进:写入剧情进度,切到下一个时段。

    返回本次结算的说明文字(给结算页/简报用)。
    """
    s = st(sd)
    m = mission(sd)
    notes = []
    if m is not None:
        notes.append(f"{m['title']} {'完成撤离' if result.get('kind') == 'extract' else '未能撤离'}")
    if result.get("kind") != "extract":
        set_flag(sd, "failed_extract")
        notes.append("丢失了部分装备(进度保留)")
    # 被黑曜石发现:击杀过多 / 触发过警报
    if result.get("kills", 0) >= 8 and s["wanted"] < WANTED_MAX:
        s["wanted"] += 1
        notes.append(f"行动太张扬,通缉等级升到「{wanted_state(sd)}」")
    s["period"] += 1
    if s["period"] > 3:
        s["period"] = 0
        if s["day"] == 1:
            s["day"] = 2
            notes.append(_day1_summary(sd))
        else:
            key, data = ending_for(sd)
            s["ending"] = key
            if key not in s["endings"]:
                s["endings"].append(key)
            notes.append(f"故事结束:{data['name']}")
    return " · ".join(notes)


def _day1_summary(sd):
    s = st(sd)
    return (f"第一天结算 —— 数据板 {s['boards']}/3 · 灰狼{wolf_state(sd)} · "
            f"艾琳{erin_state(sd)} · 通缉{wanted_state(sd)} · "
            f"录音 {s['tapes']}/12 · 索菲亚{'存活' if s['sophia_alive'] else '未知'}")


def brief_lines(sd):
    """藏身处「剧情简报」要显示的内容。"""
    s = st(sd)
    out = [f"第 {s['day']} 天 · {PERIODS[min(3, s['period'])]} · {mission_title(sd)}"]
    m = mission(sd)
    if m is not None:
        out.append(f"地点:{m['place']}")
        for speaker, line in m["brief"]:
            out.append(f"{speaker}:{line}")
    out.append(_day1_summary(sd) if s["day"] == 2 else
               f"数据板 {s['boards']}/3 · 录音 {s['tapes']}/12")
    if s["route"]:
        out.append(f"已选路线:{s['route']}")
    if s["endings"]:
        out.append("已解锁结局:" + "、".join(ENDINGS[k]["name"] for k in s["endings"]))
    if s.get("ending"):
        data = ENDINGS[s["ending"]]
        out.append(f"★ {data['name']}")
        out.extend(wrap(data["text"], 38)[:3])
        out.append(f"「{data['line']}」")
    return out


def wrap(text, n=44):
    """把中文按每行 n 个字折行(结算页/结局页用)。"""
    out, line = [], ""
    for ch in text:
        line += ch
        if len(line) >= n:
            out.append(line)
            line = ""
    if line:
        out.append(line)
    return out


def bosses(sd):
    """当前时段该出场的剧情 Boss:[(名字, 坐标键, 属性, 标记)]。"""
    s = st(sd)
    m = mission(sd)
    out = []
    if m is None:
        return out
    if m["id"] == "d1_4":
        out.append(dict(name="回声体", at="echo", tag="echo",
                        stats=dict(hp=520, speed=150, dmg=22, pellets=1,
                                   spread=0.06, rof=0.12, auto=True, burst=6,
                                   pause=0.9, range=760, view=560),
                        armor="bt201"))
    if m["id"] == "d2_3":
        # 天线阵列前的 Boss:按路线与之前的选择决定
        if s["route"] in ("A", None) or s.get("final") == "trade":
            out.append(dict(name="黑曜石指挥官维克托", at="antenna", tag="viktor",
                            stats=dict(hp=560, speed=146, dmg=24, pellets=1,
                                       spread=0.05, rof=0.11, auto=True, burst=7,
                                       pause=0.85, range=880, view=580),
                            armor="bt201"))
        if not flag(sd, "cooling_off"):
            out.append(dict(name="巨型回声体", at="tower", tag="echo",
                            stats=dict(hp=680, speed=132, dmg=28, pellets=1,
                                       spread=0.07, rof=0.16, auto=True, burst=5,
                                       pause=1.0, range=700, view=540),
                            armor="b45"))
        if s["wolf"] < 0:
            out.append(dict(name="灰狼(被背叛)", at="tnt", tag="wolf",
                            stats=dict(hp=420, speed=158, dmg=18, pellets=1,
                                       spread=0.06, rof=0.13, auto=True, burst=5,
                                       pause=1.0, range=760, view=560),
                            armor="b23"))
        if flag(sd, "freed_courier") and not flag(sd, "killed_courier"):
            out.append(dict(name="信使", at="antenna", tag="courier",
                            stats=dict(hp=380, speed=162, dmg=16, pellets=1,
                                       spread=0.055, rof=0.12, auto=True, burst=6,
                                       pause=0.9, range=820, view=580),
                            armor="zhuk"))
    return out


# ---------------- 对白 ----------------
DIA = {
    "d1_1_squad": dict(speaker="渡鸦", lines=[
        "先遣小队不是死于坠机 —— 他们都是被处决的,一枪一个。",
        "队长尸体旁有半张名单,上面有艾琳的名字。"]),
    "d1_1_radio": dict(speaker="艾琳", lines=[
        "电台能用了。很好,至少你还没死。",
        "记住:三块数据板。第一块在港口仓库。"]),
    "d1_1_captives": dict(speaker="被俘的拾荒者", lines=[
        "别开枪!我们是灰狼的人……黑曜石把我们都抓了。",
        "放了我们,灰狼会记你这份情。"], choices=[
        dict(text="放他们走(灰狼信任 +1,拿到下水道情报)",
             effects=dict(wolf=1, flags=["saved_captives"]),
             reply="他们把下水道的位置告诉了你。"),
        dict(text="不管他们(黑曜石暂时不会通缉你)",
             effects=dict(flags=["left_captives"]),
             reply="你转身离开。身后传来一声枪响。")]),
    "d1_2_rec": dict(speaker="渡鸦", lines=[
        "医疗记录:所谓「污染」不是普通病毒,而是一种神经控制药剂。"]),
    "d1_2_wolf": dict(speaker="灰狼的手下", lines=[
        "医院里挤满伤员。求你了,把你的止痛药和抗生素给我们。",
        "灰狼说过,谁救过我们的人,谁就是灰区的朋友。"], choices=[
        dict(text="给药(灰狼信任 +2,解锁第二天救援线)",
             effects=dict(wolf=2, flags=["gave_meds"]),
             reply="他握着你的手,说了声谢谢。"),
        dict(text="拒绝(留下医疗物资,灰狼线关闭)",
             effects=dict(wolf=-1, flags=["refused_meds"]),
             reply="他沉默着退开了。"),
        dict(text="抢夺(灰狼敌对,第二天可能伏击你)",
             effects=dict(wolf=-3, flags=["robbed_wolf"]),
             reply="你抢走了物资。有人在暗处记住了你的脸。")]),
    "d1_3_board": dict(speaker="维克托(偷听)", lines=[
        "黎明协议不是撤离,是清理。名单上的人一个都不能出去。"]),
    "d1_3_safe": dict(speaker="渡鸦", lines=[
        "铁钉的保险箱:里面是武器改装件,还有一张写着「别信艾琳」的纸条。"]),
    "d1_4_tape": dict(speaker="索菲亚(录音)", lines=[
        "黎明协议不是撤离计划。样本不是武器,是控制工具。",
        "艾琳医生……她不是来救人的。"]),
    "d2_1_routeA": dict(speaker="黑曜石哨兵", lines=[
        "通行证和信使都在指挥中心。选这条路,你就是替维克托办事了。"],
        choices=[dict(text="潜入指挥中心(路线A)",
                      effects=dict(route="A", flags=["route_a"]),
                      reply="你摸进了指挥楼。")]),
    "d2_1_routeB": dict(speaker="灰狼", lines=[
        "学校里有三百个平民,还有我的孩子。炸药和车我都能给你。"],
        choices=[dict(text="帮助灰狼(路线B)",
                      effects=dict(route="B", flags=["route_b"]),
                      reply="灰狼把炸药和车钥匙塞进你手里。")]),
    "d2_1_routeC": dict(speaker="索菲亚", lines=[
        "来实验室。我告诉你黎明协议真正的目标 —— 但动作要快,信使在找我。"],
        choices=[dict(text="前往地下实验室(路线C)",
                      effects=dict(route="C", flags=["route_c"]),
                      reply="你走向地铁隧道深处。")]),
    "d2_2_church": dict(speaker="信使", lines=[
        "艾琳曾是黎明协议设计者之一。灰狼的孩子已经被黑曜石带走。",
        "索菲亚手里的样本可以控制感染者。而你的先遣小队 —— 是艾琳故意送进来的。"],
        choices=[
            dict(text="杀信使(黑曜石线断裂,索菲亚存活)",
                 effects=dict(flags=["killed_courier", "killed_surrender"]),
                 reply="信使倒下前笑了一下:「名单上也有你。」"),
            dict(text="放信使(黑曜石线继续,但灰狼可能死)",
                 effects=dict(flags=["freed_courier"]),
                 reply="你先放了他,然后悄悄跟上去 —— 记住他去了哪。"),
            dict(text="交给灰狼(灰狼信任大增,艾琳敌对)",
                 effects=dict(wolf=3, erin=-1, flags=["handed_wolf"]),
                 reply="灰狼的人把信使拖走了。"),
            dict(text="交给艾琳(艾琳线继续,灰狼敌对)",
                 effects=dict(erin=1, wolf=-2, flags=["handed_erin"]),
                 reply="艾琳的人接走了信使,灰狼冷冷看了你一眼。")]),
    "npc_wolf": dict(speaker="灰狼", lines=[
        "他们叫我们拾荒者,可我们只是没赶上撤离车的人。",
        "学校里有三百个平民……还有我的孩子。"]),
    "npc_viktor": dict(speaker="维克托", lines=[
        "封锁不是残忍,是必要。名单上的人一个都不能出去。"]),
    "npc_sophia": dict(speaker="索菲亚", lines=[
        "黎明协议不是撤离计划,是清理名单。",
        "别信艾琳 —— 她不是来救人的。"]),
    "npc_courier": dict(speaker="信使", lines=[
        "每个人都想当英雄,直到看见名单上有自己的名字。"]),
    "npc_erin": dict(speaker="艾琳", lines=[
        "你不是来救这座城的。你是来确认它死透没有。",
        "把数据带到天线阵列,广播出去 —— 整座城才有救。"]),
    "d2_3_final": dict(speaker="渡鸦", lines=[
        "天线阵列就在眼前。数据板、样本、炸药 —— 决定权在你手里。"],
        choices=[
            dict(text="上传数据,广播「黎明协议」(需 3 块数据板 + 加密电台)",
                 effects=dict(final="truth", flags=["final_truth"]),
                 reply="你把三块数据板接上阵列。整座城都能听到了。"),
            dict(text="把样本交给维克托,换直升机",
                 effects=dict(final="trade", flags=["final_trade"]),
                 reply="维克托的直升机螺旋桨已经开始转动。"),
            dict(text="启动撤离广播,带平民炸开封锁线",
                 effects=dict(final="rescue", flags=["final_rescue"]),
                 reply="灰狼的人在港口等着你的信号。"),
            dict(text="炸毁实验室和天线阵列(焦土)",
                 effects=dict(final="scorch", flags=["final_scorch"]),
                 reply="你按下了起爆器。"),
            dict(text="带上样本,独自去港口",
                 effects=dict(final="selfish", flags=["final_selfish"]),
                 reply="你谁也没告诉,独自走向港口。")]),
}
