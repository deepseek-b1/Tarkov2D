# -*- coding: utf-8 -*-
"""局域网联机压测(回环):主机 + 客户端在同一个进程里跑几千帧。

用途:联机改动之后手工验一遍 —— 客户端每帧都渲染,任何 update/draw 异常
都会像玩家那边一样冒出来(那边就是"闪退")。

    python tools/lan_stress.py            # 默认 3 分钟左右的流程
    python tools/lan_stress.py --quick    # 只跑一小段,冒烟用

自检(she --selftest)里的「局域网联机」那条是精简版;这里会把夜战、无人机、
客户端界面点击、两局连打都走一遍,更接近真人对局。
"""
import os
import random
import sys
import tempfile
import time
import traceback

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
pygame.init()

import save as save_mod
save_mod.SAVE_DIR = tempfile.mkdtemp(prefix="tk2d_lan_stress_")
save_mod.SAVE_FILE = os.path.join(save_mod.SAVE_DIR, "save.json")

from settings import W, H
scr = pygame.display.set_mode((W, H))

from game import Game
from inventory import Item

PORT = 27661
QUICK = "--quick" in sys.argv


def make_game(mode="raid"):
    g = Game(scr)
    g.save = save_mod.reset_data()
    g.save.seen_intro = True
    g.hideout.show_intro = False
    g.save.mode = mode
    g.save.touch = False
    return g


def connect(mode="raid"):
    host = make_game(mode)
    assert host.net.host_room("压测房", port=PORT), host.net.error
    client = make_game(mode)
    assert client.net.join("127.0.0.1", PORT), client.net.error
    t0 = time.time()
    while time.time() - t0 < 8 and not host.net._client_ready:
        host.update(1 / 60.0, [])
        client.update(1 / 60.0, [])
        time.sleep(1 / 240.0)
    assert host.net._client_ready, host.net.status_text()
    return host, client


def pump(host, client, n, dt=1 / 60.0):
    for i in range(n):
        host.update(dt, [])
        client.update(dt, [])
        if client.raid is not None:
            client.draw(scr)
        if i % 4 == 0 and host.raid is not None:
            host.draw(scr)


def round_trip(host, client, tag, frames=600):
    pump(host, client, 60)
    for k in range(frames // 60):
        if client.raid is None or host.raid is None:
            print("  回合 %-18s 结束(phase=%s/%s)" % (tag, host.phase, client.phase))
            return
        hr, cr = host.raid, client.raid
        pump(host, client, 60)
        if hr.scavs:
            s = hr.scavs[-1]
            s.x, s.y = hr.player.x + random.randint(-60, 60), hr.player.y + 40
        if k % 3 == 0:
            hr.bullets.append(dict(x=hr.player.x + 30, y=hr.player.y,
                                   dx=700.0, dy=0.0, dmg=5, owner="scav",
                                   ttl=0.25))
        if k % 4 == 1:                    # 客户端开背包 + 乱点
            cr.inv_open = True
            for _ in range(6):
                pos = (random.randint(0, W - 1), random.randint(0, H - 1))
                client.update(1 / 60.0, [pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, pos=pos, button=1)])
                client.draw(scr)
            cr.inv_open = False
        if k % 5 == 2:                    # 客户端暂停/恢复
            for _ in range(2):
                client.update(1 / 60.0, [pygame.event.Event(
                    pygame.KEYDOWN, key=pygame.K_ESCAPE, unicode="")])
    print("  回合 %-18s ok  scavs=%d/%d" % (tag, len(hr.scavs), len(cr.scavs)))


def main():
    host, client = connect("night")
    assert host.lan_start_raid(), "夜战开局失败"
    t0 = time.time()
    while time.time() - t0 < 10 and client.phase != "raid":
        host.update(1 / 60.0, [])
        client.update(1 / 60.0, [])
        time.sleep(1 / 240.0)
    assert client.phase == "raid", "客户端没进夜战战局"
    print("夜战开局 OK")
    round_trip(host, client, "夜战静止", 180 if QUICK else 300)
    hr = host.raid
    hr.player2.weapon = Item.weapon("drone")
    hr.player2.piloting = False
    hr.drone_cd = 0.0
    if hr.deploy_drone(hr.player2):
        print("  无人机已放出")
        round_trip(host, client, "夜战+无人机", 180 if QUICK else 420)
        if hr.drone is not None:
            hr.drone["battery"] = 0.6
        round_trip(host, client, "无人机电量耗尽", 120 if QUICK else 240)
    if hr.player2 is not None and not hr.player2.dead and not hr.player2.out:
        zone = hr.map.extracts[0][1]
        hr.player2.x, hr.player2.y = zone.centerx, zone.centery
        pump(host, client, int(60 * 4.5))
    print("  P2 extracted=%s" % getattr(hr.player2, "extracted", None))
    hr.player.armor = None
    hr.player.take_damage(99999, hr)
    pump(host, client, 90)
    for g in (host, client):
        g.update(1 / 60.0, [pygame.event.Event(pygame.KEYDOWN,
                                              key=pygame.K_SPACE, unicode="")])
    print("  结算后 phase=%s/%s" % (host.phase, client.phase))
    if host.phase == "hideout" and not QUICK:
        assert host.lan_start_raid(), "第二局开不起来"
        t0 = time.time()
        while time.time() - t0 < 10 and client.phase != "raid":
            host.update(1 / 60.0, [])
            client.update(1 / 60.0, [])
            time.sleep(1 / 240.0)
        round_trip(host, client, "第二局", 240)
    host.net.close()
    pump(host, client, 60)
    client.net.close()
    print("LAN STRESS OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        print("LAN STRESS FAILED")
        sys.exit(1)
