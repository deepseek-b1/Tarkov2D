# -*- coding: utf-8 -*-
"""玩家立绘预览(开发用):把八方向立绘和一张完整战局截图存到 art/_*.png。

用法: python tools/preview_player.py
"""
import math
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame

pygame.init()
from settings import W, H                      # noqa: E402
from game import Game                          # noqa: E402
from inventory import Item                     # noqa: E402

ART = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "art")
screen = pygame.display.set_mode((W, H))
g = Game()
g.start_raid()
r = g.raid
r.scavs = r.scavs[:1]
if r.scavs:
    r.scavs[0].x = r.player.x + 90
    r.scavs[0].y = r.player.y
r.player.weapon = Item.weapon("ak74", mag=30)
r.player.armor = Item("paca")

tiles = []
for i in range(8):
    r.player.aim = i * math.pi / 4
    g.draw(screen)
    px = int(r.player.x - r.cam[0])
    py = int(r.player.y - r.cam[1])
    x0 = min(max(px - 26, 0), W - 52)
    y0 = min(max(py - 34, 0), H - 60)
    t = screen.subsurface(pygame.Rect(x0, y0, 52, 60)).copy()
    tiles.append(pygame.transform.scale(t, (156, 180)))

sheet = pygame.Surface((len(tiles) * 160 + 4, 184))
sheet.fill((48, 52, 58))
for i, t in enumerate(tiles):
    sheet.blit(t, (4 + i * 160, 2))
pygame.image.save(sheet, os.path.join(ART, "_ingame_dirs.png"))

r.player.aim = math.pi / 2          # 朝下(正面)
g.draw(screen)
pygame.image.save(screen, os.path.join(ART, "_ingame_full.png"))
print("saved art/_ingame_dirs.png, art/_ingame_full.png")
