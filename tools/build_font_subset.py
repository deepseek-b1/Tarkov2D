# -*- coding: utf-8 -*-
"""把随包发布的中文字体裁剪成「游戏真正会用到的字」子集。

为什么必须做
------------
`pygame.font.Font(path, size)` 每次都会把整个字体文件重新解析一遍。原来随包的
NotoSansSC-Regular.otf 是 **CFF/PostScript 轮廓的 .otf**(8.33 MB,约 3 万个字形),
实测**每次创建要 115 ms**;游戏用到 15 种字号 × 常规/粗体,合计约 2.7 秒。

这 2.7 秒不是集中在启动,而是散落在「第一次用到某个字号」的那一帧上:

  * 进藏身处第一帧  ~0.6 秒
  * 进战局第一帧    ~1.2 秒
  * 之后打到一半,某个新字号第一次出现时再顿 0.1~0.19 秒

而且字体对象和渲染缓存都是**进程级**的 —— 每次重启进程(比如装完更新)全部重来,
所以表现就是「更新完以后莫名其妙掉帧」。

裁剪之后(保留 GB2312 一级字库 + 仓库里出现的全部字符,共约 3900 字):
  8.33 MB -> 1.03 MB,每次创建 115 ms -> 1.08 ms,渲染逐像素一致。

用法
----
    python tools/build_font_subset.py            # 就地覆盖 fonts/NotoSansSC-Regular.otf
    python tools/build_font_subset.py --check    # 只检查覆盖够不够,不改文件

新增了大量文案之后请重跑一次(否则新字可能显示成方框)。
"""
import glob
import os
import sys

# Windows 控制台默认是 GBK,打印特殊符号会炸
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "fonts", "NotoSansSC-Regular.otf")
CHECK = "--check" in sys.argv

# 文本可能出现的文件类型(所有展示文案都写在这些源码/数据里)
EXTS = (".py", ".md", ".json", ".txt", ".spec", ".bat", ".cmd", ".yml", ".yaml")


def needed_chars():
    chars = set()
    for path in glob.glob(os.path.join(ROOT, "**", "*"), recursive=True):
        if os.path.isfile(path) and path.lower().endswith(EXTS):
            try:
                chars.update(open(path, encoding="utf-8", errors="replace").read())
            except Exception:
                pass
    # ASCII 与 UI 用到的符号
    chars.update(chr(c) for c in range(0x20, 0x7F))
    chars.update("　、。〈〉《》「」『』【】〔〕・ー―…‥★☆✓✔□■▲▼◀▶●○◆◇※"
                 "→←↑↓⚠℃±×÷°％＋－／：；（）！？，．·—～￥０１２３４５６７８９")
    chars.discard("\x00")
    # GB2312 一级字库(3755 个常用简体字)作为安全余量
    for hi in range(0xB0, 0xD8):
        for lo in range(0xA1, 0xFF):
            try:
                c = bytes((hi, lo)).decode("gb2312")
            except UnicodeDecodeError:
                continue
            if len(c) == 1:
                chars.add(c)
    return chars


def main():
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        print("需要 fonttools:pip install fonttools brotli")
        return 1

    chars = needed_chars()
    cmap = TTFont(FONT).getBestCmap()
    missing = sorted(c for c in chars if ord(c) not in cmap)
    print("需要 %d 个字;字体里有 %d 个;字体本身缺 %d 个 %s"
          % (len(chars), len(cmap), len(missing),
             "".join(missing[:20]) if missing else ""))

    if CHECK:
        have = sum(1 for c in chars if ord(c) in cmap)
        print("覆盖检查:%d/%d" % (have, len(chars)))
        if len(cmap) > 20000:
            print("提示:这个字体还是完整字库(未裁剪),建议跑一次不带 --check 的裁剪")
        return 0

    if len(cmap) < 20000:
        print("看起来已经是裁剪过的子集了,跳过(要强制重建请先还原完整字体)")
        return 0

    tmp = FONT + ".subset"
    subset.main([FONT, "--output-file=%s" % tmp, "--text=%s" % "".join(sorted(chars)),
                 "--layout-features=*", "--name-IDs=*", "--recalc-bounds",
                 "--drop-tables+=DSIG"])
    before, after = os.path.getsize(FONT), os.path.getsize(tmp)
    os.replace(tmp, FONT)
    print("裁剪完成:%.2f MB -> %.2f MB (%.0f%%)"
          % (before / 1e6, after / 1e6, 100.0 * after / before))
    return 0


if __name__ == "__main__":
    sys.exit(main())
