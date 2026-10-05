# -*- coding: utf-8 -*-
"""键位自定义:动作 -> 键位。

默认值写死在 DEFAULTS;玩家改过的项存进存档 sd.bindings(action -> [键码]),
解析时"玩家覆盖优先,否则用默认",旧存档不需要迁移。
战局里一律通过 keys_for/is_down/key_matches 取键,不要直接写死 K_xxx。
"""
import pygame

# (action, 设置页显示名) —— 设置页按这个顺序列出
ACTIONS = [
    ("up", "向上移动"),
    ("down", "向下移动"),
    ("left", "向左移动"),
    ("right", "向右移动"),
    ("walk", "慢走(静步)"),
    ("interact", "交互 / 搜刮 / 对白继续"),
    ("reload", "装填"),
    ("heal", "快捷打药"),
    ("bag", "背包"),
    ("support1", "友军支援 1(空袭)"),
    ("support2", "友军支援 2(炮火覆盖)"),
    ("support3", "友军支援 3(无人机侦察)"),
]

DEFAULTS = {
    "up": (pygame.K_w, pygame.K_UP),
    "down": (pygame.K_s, pygame.K_DOWN),
    "left": (pygame.K_a, pygame.K_LEFT),
    "right": (pygame.K_d, pygame.K_RIGHT),
    "walk": (pygame.K_LSHIFT, pygame.K_RSHIFT),
    "interact": (pygame.K_e,),
    "reload": (pygame.K_r,),
    "heal": (pygame.K_h,),
    "bag": (pygame.K_TAB,),
    "support1": (pygame.K_1,),
    "support2": (pygame.K_2,),
    "support3": (pygame.K_3,),
}

# 固定键说明(设置页脚注)
FIXED_NOTES = "固定键:ESC 菜单/关闭 · 对白选项用数字键 1-4 · 移动改绑后只认新键"


def _overrides(sd):
    ov = getattr(sd, "bindings", None)
    return ov if isinstance(ov, dict) else {}


def keys_for(sd, action):
    """该动作当前生效的键位元组(玩家覆盖优先,否则默认)。"""
    ov = _overrides(sd).get(action)
    if ov:
        try:
            ks = tuple(int(k) for k in ov)
            if ks:
                return ks
        except (TypeError, ValueError):
            pass
    return DEFAULTS.get(action, ())


def is_down(keys, sd, action):
    """pygame.key.get_pressed() 的快照里,该动作是否被按住。

    自检里 get_pressed() 会被换成 dict 式假对象(支持超大方向键码),
    所以这里不假设长度/类型,取不到就当作没按。
    """
    for k in keys_for(sd, action):
        try:
            if keys[k]:
                return True
        except (IndexError, KeyError, TypeError):
            continue
    return False


def key_matches(ev_key, sd, action):
    """KEYDOWN 事件的键是否触发该动作。"""
    return ev_key in keys_for(sd, action)


def find_conflicts(sd, action, key):
    """这个键当前还绑在哪些别的动作上(含默认绑定)。"""
    out = []
    for act, _name in ACTIONS:
        if act != action and key in keys_for(sd, act):
            out.append(act)
    return out


def assign(sd, action, key):
    """改绑(单键)。键已被别的动作占用时拒绝并返回冲突列表,不做修改。"""
    if action not in DEFAULTS or not isinstance(key, int) or key <= 0:
        return False, []
    conflicts = find_conflicts(sd, action, key)
    if conflicts:
        return False, conflicts
    b = dict(_overrides(sd))
    b[action] = [int(key)]
    sd.bindings = b
    return True, []


def clear(sd, action):
    """单个动作恢复默认。"""
    b = dict(_overrides(sd))
    b.pop(action, None)
    sd.bindings = b


def reset_all(sd):
    sd.bindings = {}


def is_modified(sd, action):
    return action in _overrides(sd)


def action_label(action):
    for a, name in ACTIONS:
        if a == action:
            return name
    return action


_KEY_NAMES = {
    pygame.K_UP: "↑", pygame.K_DOWN: "↓", pygame.K_LEFT: "←", pygame.K_RIGHT: "→",
    pygame.K_LSHIFT: "左Shift", pygame.K_RSHIFT: "右Shift",
    pygame.K_LCTRL: "左Ctrl", pygame.K_RCTRL: "右Ctrl",
    pygame.K_LALT: "左Alt", pygame.K_RALT: "右Alt",
    pygame.K_TAB: "Tab", pygame.K_SPACE: "空格", pygame.K_RETURN: "回车",
    pygame.K_ESCAPE: "ESC", pygame.K_BACKSPACE: "退格",
    pygame.K_KP_ENTER: "小键盘回车", pygame.K_KP0: "小0", pygame.K_KP1: "小1",
    pygame.K_KP2: "小2", pygame.K_KP3: "小3", pygame.K_KP4: "小4",
    pygame.K_KP5: "小5", pygame.K_KP6: "小6", pygame.K_KP7: "小7",
    pygame.K_KP8: "小8", pygame.K_KP9: "小9",
}


def key_label(key):
    """键码 -> 界面可读名。"""
    if key in _KEY_NAMES:
        return _KEY_NAMES[key]
    try:
        name = pygame.key.name(key) or "?"
    except Exception:
        return "?"
    if len(name) == 1:
        return name.upper()
    return name


def label_for(sd, action):
    """该动作当前键位的可读串(多键位用 / 连接),HUD 提示文案用它。"""
    return " / ".join(key_label(k) for k in keys_for(sd, action))
