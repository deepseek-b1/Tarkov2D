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
requirements = python3,pygame

orientation = landscape
fullscreen = 1
presplash.color = #101216
android.archs = arm64-v8a,armeabi-v7a
android.api = 31
android.minapi = 21
android.accept_sdk_license = True
android.allow_backup = True

# 游戏内部已经用 sys.platform / ANDROID_ARGUMENT 判断平台,
# 安卓上会自动开启手机模式(触屏摇杆 + 按钮 + 自动锁敌)与全屏缩放。
# 不固定 p4a 分支 / NDK 版本,交给 buildozer 自动选兼容组合,减少构建失败。
