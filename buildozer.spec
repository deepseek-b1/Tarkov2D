[app]
# Tarkov2D - Android packaging config (buildozer / python-for-android)
# Build with:  buildozer -v android debug
#
# KEEP THIS FILE PURE ASCII. buildozer reads it with encoding="utf-8", so a spec
# written in GBK (Windows default for open(...,'w')) makes buildozer die before
# the build starts:
#   UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd3 in position 1905
title = Tarkov2D
package.name = tarkov2d
package.domain = org.tarkov2d

source.dir = .
source.include_exts = py,png,jpg,json,ttf,otf,ttc
source.include_patterns = fonts/*
source.exclude_dirs = build, dist, update_server, webapp, .github, .codely-cli, __pycache__, p4a-recipes
source.exclude_exts = spec, bat, md, exe, log, zip

version = 1.0.8

# Pinned on purpose - each line below is a fix for a real build failure:
#   * p4a stock pygame recipe is stuck at 2.1.0 (2021) and uses the old
#     longintrepr.h location -> "fatal error: 'longintrepr.h' file not found"
#   * p4a stock python3 recipe is 3.14 while pygame supports up to 3.13
#   * Python 3.12/3.13 with NDK r28 dies in Modules/grpmodule.c (unfixed upstream)
# So: Python 3.11 + pygame 2.5.2 + NDK 25c - a widely used working combo.
# hostpython3 must match python3 exactly or p4a aborts with
#   "python3 should have same version as hostpython3".
requirements = hostpython3==3.11.9,python3==3.11.9,pygame==2.5.2

orientation = landscape
fullscreen = 1
presplash.color = #101216

# arm64 only: Python 3.12 grpmodule.c fails on armv7a + newer NDK, no p4a patch.
# Every phone from ~2020 on is arm64 anyway.
android.archs = arm64-v8a
android.api = 31
android.minapi = 21
android.accept_sdk_license = True
android.allow_backup = True

# Pin the NDK: buildozer default (r28c) is not handled by p4a's CPython recipe
# yet (fails in Modules/grpmodule.c). 25c is what p4a CI uses.
android.ndk = 25c

p4a.local_recipes = ./p4a-recipes

# Project-local pygame recipe: disables the x86 SIMD blitter path, which
# otherwise makes surface.so unloadable on arm64.

# The game already detects Android (sys.platform / ANDROID_ARGUMENT) and turns
# on touch controls, auto-aim and fullscreen scaling by itself.