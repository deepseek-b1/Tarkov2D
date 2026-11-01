# -*- coding: utf-8 -*-
"""准备 Win7 32 位构建目录(把仓库根的 .py 拷到临时目录,再交给 Python 3.8 32 位打包)。

用法: python tools/prepare_win7_build.py <目标目录>
"""
import os
import shutil
import sys

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.environ.get("TEMP", "."), "tk2d_win7")

if os.path.isdir(dst):
    shutil.rmtree(dst, ignore_errors=True)
os.makedirs(dst)
os.makedirs(os.path.join(dst, "src"))

copied = []
for name in sorted(os.listdir(repo)):
    if not name.endswith(".py"):
        continue
    # 打包用的脚本/工具不需要进游戏源码
    if name.startswith("_") or name in ("diag_move.py",):
        continue
    shutil.copy2(os.path.join(repo, name), os.path.join(dst, "src", name))
    copied.append(name)
print("复制 %d 个 .py 到 %s" % (len(copied), os.path.join(dst, "src")))
