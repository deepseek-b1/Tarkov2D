# -*- coding: utf-8 -*-
"""按键诊断 v3:
  raw       游戏默认行为
  ime_dis   窗口创建后 ImmAssociateContext(hwnd, 0)
  ime_full  窗口创建前 ImmDisableIME(0) 线程级禁用
注入对比:W(字母) vs LEFT/UP(方向键,IME 不拦截)。"""
import json
import os
import sys
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame

MODE = sys.argv[1] if len(sys.argv) > 1 else "raw"
ime_info = "n/a"

if MODE == "ime_full":
    try:
        import ctypes
        ok = ctypes.windll.imm32.ImmDisableIME(0)
        ime_info = f"ImmDisableIME(0) -> {ok}"
    except Exception as e:
        ime_info = f"fail {e}"

pygame.init()
screen = pygame.display.set_mode((420, 200))
pygame.display.set_caption("DIAG-KEY3")

if MODE == "ime_dis":
    try:
        import ctypes
        hwnd = pygame.display.get_wm_info().get("window")
        old = ctypes.windll.imm32.ImmAssociateContext(hwnd, 0) if hwnd else -1
        ime_info = f"disassociate old_ctx={old}"
    except Exception as e:
        ime_info = f"fail {e}"

events = []
seen_pressed = set()
focused_min = 1
start = time.time()
font = pygame.font.SysFont("consolas", 16)
while time.time() - start < 7.0:
    for ev in pygame.event.get():
        if ev.type == pygame.KEYDOWN:
            events.append(["down", ev.key, ev.scancode, pygame.key.name(ev.key)])
        elif ev.type == pygame.KEYUP:
            events.append(["up", ev.key, ev.scancode, ""])
        elif ev.type == pygame.QUIT:
            break
    k = pygame.key.get_pressed()
    for i, v in enumerate(k):
        if v:
            seen_pressed.add(i)
    if not pygame.key.get_focused():
        focused_min = 0
    screen.fill((30, 32, 42))
    screen.blit(font.render(f"{MODE} ev={len(events)}", True, (230, 230, 240)), (10, 80))
    pygame.display.flip()

res = dict(mode=MODE, ime=ime_info, events=events, seen_pressed=sorted(seen_pressed),
           focused_all=bool(focused_min))
with open("diag_result.txt", "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
pygame.quit()
