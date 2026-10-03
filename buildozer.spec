[app]
# Tarkov2D 手机(安卓)打包配置 —— 用 Buildozer / python-for-android
# 在 Linux 或 WSL 里执行:  buildozer -v android debug
title = Tarkov2D
package.name = tarkov2d
package.domain = org.tarkov2d

source.dir = .
source.include_exts = py,png,jpg,json,ttf,otf,ttc
source.include_patterns = fonts/*
source.exclude_dirs = build, dist, update_server, webapp, .github, .codely-cli, __pycache__
source.exclude_exts = spec, bat, md, exe, log, zip

version = 1.0.8

# pygame 由 python-for-android 的 pygame 配方提供(SDL2)
#
# 版本必须钉住,原因:
#   * p4a 的 pygame 配方默认锁在 2.1.0(2021 年),它引用的 longintrepr.h 在
#     Python 3.11+ 已经换了位置 —— 直接编不过
#     (报错: src_c/_sdl2/sdl2.c: fatal error: 'longintrepr.h' file not found)
#   * p4a 的 python3 配方默认是 3.14,而 pygame 到 2.6.1 为止只支持到 3.13
# 所以钉成 Python 3.12 + pygame 2.6.1 这个互相兼容、且被广泛验证过的组合。
# 注意 hostpython3 必须和 python3 版本一致,否则 p4a 直接报
# "python3 should have same version as hostpython3"。
requirements = hostpython3==3.12.11,python3==3.12.11,pygame==2.6.1

orientation = landscape
fullscreen = 1
presplash.color = #101216
# 只出 arm64-v8a:
#   Python 3.12 的 Modules/grpmodule.c 在 armv7a(32 位)+ 新版 NDK 下编译不过
#   (make: *** [Makefile:3063: Modules/grpmodule.o] Error 1),p4a 上游也没有对应补丁。
#   2020 年以后的安卓机基本都是 arm64,只出 arm64 即可。
android.archs = arm64-v8a
android.api = 31
android.minapi = 21
android.accept_sdk_license = True
android.allow_backup = True

# 游戏内部已经用 sys.platform / ANDROID_ARGUMENT 判断平台,
# 安卓上会自动开启手机模式(触屏摇杆 + 按钮 + 自动锁敌)与全屏缩放。
# 不固定 p4a 分支 / NDK 版本,交给 buildozer 自动选兼容组合,减少构建失败。
