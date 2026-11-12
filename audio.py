# -*- coding: utf-8 -*-
"""程序化音效:全部用原始采样合成,无外部文件。
需要 mixer 以 44100Hz / 16bit / 单声道 初始化。"""
import array
import math
import random

import pygame

SR = 44100
_enabled = False
_snd = {}

# ---------- 音量(仿合并版:总音量 / 枪声 / 界面 三档 + 静音) ----------
VOL_DEFAULT = {"master": 0.8, "gun": 1.0, "ui": 1.0}
# 音效分组:枪声类吃「枪声」音量,其余(打药/拾取/界面/受击)吃「界面」音量
SFX_GROUP = {
    "pm": "gun", "sg": "gun", "ar": "gun", "mp5": "gun",
    "epm": "gun", "esg": "gun", "ear": "gun", "reload": "gun", "empty": "gun",
    "hit": "ui", "hurt": "ui", "pickup": "ui", "heal": "ui",
    "extract": "ui", "death": "ui", "click": "ui", "kill": "ui",
}
_vol = dict(VOL_DEFAULT)
_muted = False


def _clamp01(v):
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


def set_volumes(master=None, gun=None, ui=None, muted=None):
    """改音量;只传要改的那几项。返回改完的快照。"""
    global _muted
    if master is not None:
        _vol["master"] = _clamp01(master)
    if gun is not None:
        _vol["gun"] = _clamp01(gun)
    if ui is not None:
        _vol["ui"] = _clamp01(ui)
    if muted is not None:
        _muted = bool(muted)
    return get_volumes()


def get_volumes():
    d = dict(_vol)
    d["muted"] = _muted
    return d


def apply_from_save(sd):
    """把存档里的音量设置套上(启动/读档/保存并应用时调)。"""
    if sd is None:
        return get_volumes()
    return set_volumes(
        master=getattr(sd, "vol_master", VOL_DEFAULT["master"]),
        gun=getattr(sd, "vol_gun", VOL_DEFAULT["gun"]),
        ui=getattr(sd, "vol_ui", VOL_DEFAULT["ui"]),
        muted=getattr(sd, "vol_muted", False))


def effective_volume(name):
    """某个音效此刻的最终音量(0~1)。"""
    if _muted:
        return 0.0
    group = SFX_GROUP.get(name, "ui")
    return _clamp01(_vol.get("master", 0.8) * _vol.get(group, 1.0))


def group_of(name):
    """这个音效属于哪一组(枪声 / 界面与提示)。"""
    return SFX_GROUP.get(name, "ui")


def preview(group="gun"):
    """试听:枪声 / 界面提示音各放一个(音量页用)。"""
    play("ar" if group == "gun" else "click")


def _samples_to_sound(fn, dur):
    n = int(SR * dur)
    a = array.array("h")
    for i in range(n):
        t = i / SR
        s = fn(t, dur)
        if s > 1:
            s = 1
        elif s < -1:
            s = -1
        a.append(int(s * 32767))
    return pygame.mixer.Sound(buffer=a.tobytes())


def _tone(freq, dur, vol=0.5, decay=5.0, noise=0.0, sweep_to=None, noise_decay=None):
    def fn(t, d):
        env = math.exp(-decay * t)
        f = freq if sweep_to is None else freq + (sweep_to - freq) * (t / d)
        s = math.sin(2 * math.pi * f * t) * env
        if noise:
            ne = env if noise_decay is None else math.exp(-noise_decay * t)
            s = s * (1 - noise) + (random.random() * 2 - 1) * noise * ne
        return s * vol
    return _samples_to_sound(fn, dur)


def init():
    global _enabled
    try:
        if pygame.mixer.get_init() is None:
            pygame.mixer.init(frequency=SR, size=-16, channels=1, buffer=512)
        _enabled = True
    except Exception:
        _enabled = False
        return
    try:
        _build()
    except Exception:
        _enabled = False


def _build():
    # 枪声:噪声爆响 + 低频冲击
    _snd["pm"] = _tone(150, 0.16, vol=0.55, decay=26, noise=0.85, noise_decay=42)
    _snd["sg"] = _tone(85, 0.30, vol=0.7, decay=15, noise=0.9, noise_decay=20)
    _snd["ar"] = _tone(120, 0.16, vol=0.6, decay=30, noise=0.8, noise_decay=48)
    _snd["mp5"] = _tone(160, 0.12, vol=0.5, decay=30, noise=0.75, noise_decay=55)
    # 敌方枪声(更闷更远)
    _snd["epm"] = _tone(130, 0.16, vol=0.30, decay=22, noise=0.8, noise_decay=38)
    _snd["esg"] = _tone(75, 0.30, vol=0.38, decay=13, noise=0.85, noise_decay=18)
    _snd["ear"] = _tone(105, 0.15, vol=0.32, decay=26, noise=0.75, noise_decay=42)
    # 反馈音
    _snd["hit"] = _tone(220, 0.10, vol=0.4, decay=30, noise=0.35)
    _snd["hurt"] = _tone(160, 0.30, vol=0.55, decay=8, sweep_to=60)
    _snd["reload"] = _tone(700, 0.09, vol=0.25, decay=40, noise=0.5)
    _snd["empty"] = _tone(1200, 0.05, vol=0.22, decay=70)
    _snd["pickup"] = _tone(620, 0.09, vol=0.3, decay=22, sweep_to=880)
    _snd["heal"] = _tone(520, 0.22, vol=0.3, decay=10, sweep_to=760)
    _snd["extract"] = _tone(440, 0.5, vol=0.35, decay=4, sweep_to=880)
    _snd["death"] = _tone(220, 0.7, vol=0.5, decay=4, sweep_to=55)
    _snd["click"] = _tone(900, 0.04, vol=0.2, decay=80)
    _snd["kill"] = _tone(330, 0.14, vol=0.35, decay=14, sweep_to=440)


def play(name):
    if _enabled and name in _snd:
        v = effective_volume(name)
        if v <= 0.0:
            return
        try:
            s = _snd[name]
            s.set_volume(min(1.0, v))
            s.play()
        except Exception:
            pass
