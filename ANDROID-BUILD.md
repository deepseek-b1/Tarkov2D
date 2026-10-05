# Tarkov2D 安卓原生 APK 构建交接说明

> 目的：把 pygame 版 Tarkov2D 打成**原生 Android APK**（Python + pygame 编译进 APK，
> 离线可玩，不依赖任何 CDN / WebView / WebAssembly）。
>
> 这份文档是 10 次失败构建后整理出来的，**所有参数都有依据，坑和修法都在下面**。
> 接手的人按「下一步怎么做」那一节改两处，基本就能出包。

---

## 1. 当前状态（截至本次交接）

| 项 | 状态 |
| --- | --- |
| 仓库 | https://github.com/deepseek-b1/Tarkov2D （public，账号 `deepseek-b1`） |
| 本地源码 | `C:\Users\Administrator\.codely\Default\Tarkov2D`（已 git 初始化并推送到 main） |
| 工作流 | `.github/workflows/android.yml` |
| 构建方式 | GitHub Actions + buildozer + python-for-android（免费额度足够） |
| **已攻克的阶段** | libffi ✅ → CPython 3.11.9 本体编译 ✅ → **只剩 pygame 的 Cython 依赖** |
| 最后一次失败 | run `37159553326`：预热阶段没能在 20 分钟内建出 hostpython3，导致补装 Cython 的命令为空 → `exit 127` |

**失败不是代码问题，是 CI 步骤编排问题**：预热和补装放在同一个 step 里，预热被 20 分钟
上限掐断，hostpython3 还没生成。修法见第 4 节（拆成两步）。

---

## 2. 当前钉住的参数（`buildozer.spec`）

每一项都是踩坑后钉的，**不要随意改回默认值**：

```ini
title = Tarkov2D
package.name = tarkov2d
package.domain = org.tarkov2d
source.dir = .
source.include_exts = py,png,jpg,json,ttf,otf,ttc
source.include_patterns = fonts/*

version = 1.0.8

# Python 3.11 + pygame 2.5.2 + NDK 25c —— 互相兼容且被大量项目验证过的组合
requirements = hostpython3==3.11.9,python3==3.11.9,pygame==2.5.2

orientation = landscape
fullscreen = 1
presplash.color = #101216
android.archs = arm64-v8a
android.api = 31
android.minapi = 21
android.accept_sdk_license = True
android.allow_backup = True
android.ndk = 25c
```

系统依赖（工作流里 apt 安装，**`libltdl-dev` 不能少**）：

```
git zip unzip openjdk-17-jdk autoconf automake libtool libtool-bin libltdl-dev
pkg-config zlib1g-dev libncurses5-dev libncursesw5-dev libtinfo6 cmake libffi-dev libssl-dev gettext
```

---

## 3. 已经踩过并修好的 9 个坑（按出现顺序）

| # | 报错 | 根因 | 修法 |
| --- | --- | --- | --- |
| 1 | `configure.ac:215: error: possibly undefined macro: LT_SYS_SYMBOL_USCORE` | p4a 的 libffi 配方源码注释里写明需要 `libltdl-dev` 提供该宏；Ubuntu 的 libtool 2.4.7 里没有它 | apt 安装 **`libltdl-dev`** |
| 2 | 同上（换 ubuntu-22.04 也一样） | 该宏在新版 libtool 中已移除，换 runner 无用 | 与 #1 同 |
| 3 | 同上（加 autoreconf shim 后仍失败） | p4a 的 libffi 用 GitHub **源码包**（无预生成 configure） | shim 保留做兜底，真正修法是 #1 |
| 4 | `src_c/_sdl2/sdl2.c:211: fatal error: 'longintrepr.h' file not found` | p4a 的 pygame 配方锁在 **2.1.0（2021）**，不认识 Python 3.11+ 的头文件新位置 | `requirements` 里覆盖为 **`pygame==2.5.2`** |
| 5 | `python3 should have same version as hostpython3, 3.12.11 != 3.14.2` | p4a 强制两者一致 | `requirements` 里 **`hostpython3` 与 `python3` 钉同一版本** |
| 6 | `Modules/grpmodule.c:281: error: ...` + `make: *** [Modules/grpmodule.o] Error 1` | p4a 默认 Python 3.14 配 buildozer 自动拉的 **NDK r28c**，CPython 配方尚未适配（3.12/3.13 同样中招；armv7a/arm64 都会） | **`android.ndk = 25c`** + Python 退到 **3.11.9** |
| 7 | `You need cython. https://cython.org/` | pygame 的 `setup.py` 由 **p4a 自带的 hostpython3** 执行；Cython 装在 runner 系统 Python 里没用。p4a 的检查是 `python3 -m cython --help` | 把 Cython 装进**那个** hostpython3（见第 4 节） |
| 8 | `line 12: : command not found` / `exit 127` | 预热与补装写在同一个 step，预热被 20 分钟上限掐断，hostpython3 未生成 → `$HP` 为空 | **拆成两个 step**（见第 4 节） |
| 9 | 装机后**点开就闪退**，无任何提示（1.0.8） | Android 链接器在 `dlopen` 时会解析**全部**重定位，`surface.so` 里有一个符号在 APK 内没有任何库定义 → 整个模块加载失败 → `import pygame` 抛 `ImportError` → 进程立刻退出 | 见第 8 节：weak 桩 + CI 全量符号校验 |

补充：armv7a（32 位）在 #6 上同样失败且上游无补丁，故只出 `arm64-v8a`（2020 年后的手机基本都是 arm64）。

---

## 4. 下一步怎么做（照这个改，基本就能出包）

### 唯一需要改的地方：`.github/workflows/android.yml`

把现在的「构建 APK」这**一个** step 拆成**两个** step：

```yaml
      # 第一趟:让 buildozer 把工具链和 hostpython3 建出来(会在 pygame 处失败,用 continue-on-error 兜住)
      - name: 预热(建 hostpython3)
        continue-on-error: true
        run: buildozer -v android debug

      # 第二趟:把 Cython 装进 p4a 的 hostpython3,再正式构建
      - name: 装 Cython 到 hostpython3 并构建
        run: |
          HP=$(find "$HOME/.buildozer" "$PWD/.buildozer" -type f -path "*hostpython3*" -name "python3*" 2>/dev/null | head -1)
          echo "hostpython3: $HP"
          test -n "$HP" || { echo "!! 仍没找到 hostpython3"; exit 1; }
          "$HP" -m pip install -q "cython<3.1" wheel setuptools
          "$HP" -c "import Cython; print('Cython', Cython.__version__)"
          "$HP" -m cython --help >/dev/null && echo "OK: hostpython3 已具备 Cython"
          buildozer -v android debug
```

关键点（前两次都栽在这里）：

1. **必须分两个 step**：第一个 step 要给足时间把 hostpython3 建出来，
   `continue-on-error: true` 让它在 pygame 处失败也不算整体失败。
2. **`find` 要同时搜 `$HOME/.buildozer` 和 `$PWD/.buildozer`** —— buildozer 的
   工作目录是前者，之前只搜了后者所以为空。
3. 找到的必须是可以执行 `-m pip` / `-m cython` 的**解释器**（文件名形如 `python3`
   或 `python3.11`），不要用 `pip3` 包装脚本。
4. 第一趟如果因为「spec 变更导致缓存作废」而重新下载全部工具链，会接近 20 分钟上限；
   真遇到就给第一个 step 单独设 `timeout-minutes: 60`。

### 验证产物

构建成功后（约 40 分钟）：

```powershell
# 1) 从 Actions 页面下载 artifact，或命令行:
& "C:\Users\Administrator\gh\bin\gh.exe" run download <run-id> --repo deepseek-b1/Tarkov2D --name Tarkov2D-apk --dir C:\Users\Administrator\Documents\HBuilderProjects\_Tarkov2D打包工具
# 2) 解压得到 bin/tarkov2d-1.0.8-*-debug.apk
# 3) 验证签名(用 HBuilderX 自带的 apksigner 和 JDK,不需要额外安装):
& "E:\HBuilderX.5.26.2026091802\HBuilderX\plugins\amazon-corretto\bin\java.exe" `
  -jar "E:\HBuilderX.5.26.2026091802\HBuilderX\plugins\app-safe-pack\apksigner.jar" `
  verify --verbose <apk路径>
```

装到手机：传过去点开安装，允许「未知来源」。
**这次是原生包，不需要联网、不依赖 CDN**，装完直接可玩。

---

## 5. 反例：不要再走的弯路（已证伪）

### 5.1 DCloud / HBuilderX WebView 路线（已彻底排死）

用 HBuilderX 5+App 云打包 + pygbag 网页版做出来的 APK **装到手机上会永久卡在
"Loading, please wait ..."**。已用日志证实，与手机、网络、DCloud 配置都无关：

- pygbag 加载器只请求 `index.html` + `pythons.js` + `main.js`，
  **从不请求 `main.data`(6.6MB)、`main.wasm`(13MB) 和游戏包** —— Python VM 每次初始化中途重启；
- 本机 Edge（本地 HTTP 服务 + 完整运行时文件 + COOP/COEP 两种模式）**全部复现同一卡点**；
- CDN 上的运行时文件是好的（我 5 秒就下完 21MB），排除了网络因素；
- `main.wasm` 是无 pthread 构建，所以也不是 SharedArrayBuffer 隔离问题。

相关残留文件（可删）：`C:\Users\Administrator\Documents\HBuilderProjects\Tarkov2D`
（那个 18.66MB、SHA256 `2659E827...` 的 `Tarkov2D-1.0.8.apk` 就是这条路线的产物，**不可用**）。

### 5.2 不要试图改回 p4a 的默认版本

`requirements` 和 `android.ndk` 一旦放开默认值，第 3 节表格里的坑会全部复现。

---

## 6. 相关路径速查

| 内容 | 路径 |
| --- | --- |
| 游戏源码 / git 仓库 | `C:\Users\Administrator\.codely\Default\Tarkov2D` |
| 构建工作流 | 同上 `.github\workflows\android.yml` |
| 本机 git | `C:\Program Files\Git\cmd\git.exe` |
| 本机 GitHub CLI | `C:\Users\Administrator\gh\bin\gh.exe`（便携版，账号 deepseek-b1 已登录） |
| APK 交付目录 | `C:\Users\Administrator\Documents\HBuilderProjects\_Tarkov2D打包工具` |
| HBuilderX（apksigner/JDK 来源） | `E:\HBuilderX.5.26.2026091802\HBuilderX` |

## 7. 一条命令重跑构建

```powershell
& "C:\Users\Administrator\gh\bin\gh.exe" workflow run "Build Android APK" `
  --repo deepseek-b1/Tarkov2D --ref main
& "C:\Users\Administrator\gh\bin\gh.exe" run list --repo deepseek-b1/Tarkov2D --limit 3
```

改完代码后：`git add -A; git commit -m "..."; git push`，再执行上面的命令即可。

---

## 8. 1.0.8「点开就闪退」的根因与修复

### 现象
装上后点图标立刻退回桌面：没有报错框，presplash 之后没有任何画面。

### 根因
`libpybundle.so`（真实身份是 **gzip 过的 tar**，p4a 把整个 Python 运行时塞在里面）里的
`_python_bundle/site-packages/pygame/surface.so` 引用了符号 `pg_avx2_at_runtime_but_uncompiled`，
而 APK 里**没有任何库定义它**。

Android 链接器和桌面 Linux 不同：它不接受「用到才解析」。`dlopen` 阶段就会把所有重定位解完，
缺一个就整库加载失败：

```
ImportError: dlopen failed: cannot locate symbol
"pg_avx2_at_runtime_but_uncompiled" referenced by ".../pygame/surface.so"
```

`pygame/__init__.py` 启动时就会 `import pygame.surface`，于是进程在开窗之前就退出——
表现出来就是「闪退」。旧的 CI 校验只写死两个符号名、而且只看 `surface.so`，正好漏掉它。

同一族的三个符号（每个都是修好前一个才暴露下一个）：

| 符号 | 谁定义 | 状态 |
| --- | --- | --- |
| `alphablit_alpha_sse2_argb_surf_alpha` | `src_c/simd_blitters_sse2.c`（模板漏编） | 已修：加进 surface 模块 |
| `pg_has_avx2` | `src_c/simd_blitters_avx2.c`（arm64 从不编译） | 已修：weak 桩 |
| **`pg_avx2_at_runtime_but_uncompiled`** | 同上 | **1.0.8 就是死在这个符号上** |

补充证据：该符号在 `surface.so` 里只有**一个**调用者 `pg_warn_simd_at_runtime_but_uncompiled()`，
作用是判断「CPU 支持 AVX2 但本次构建没编进去」要不要打提示。arm64 上正确答案就是 `0`，
所以桩函数 `return 0` 对渲染没有任何影响。

### 修复内容（已写进仓库）
1. `p4a-recipes/pygame/__init__.py`
   - 把 `src_c/simd_blitters_sse2.c` 加进 `surface` 模块的编译列表；
   - 生成 `src_c/tarkov2d_avx2_stubs.c` 一起编译，用 **weak** 定义兜住整个 AVX2 族
     （`pg_has_avx2`、`pg_avx2_at_runtime_but_uncompiled`、10 个 `blit_blend_*_avx2`）。
     weak 符号遇到真定义自动让位，因此永远不会破坏正常构建；
   - **不再**用正则去改 `src_c/simd_blitters.h`（上一版就是正则没匹配到才漏符号）。
     Setup 模板里找不到 `surface src_c/surface.c ...` 那一行时直接抛错，不再默默出包。
2. `tools/check_android_symbols.py`（新增，纯标准库）
   - 遍历 APK 里**每一个** `.so`（包括 `libpybundle.so` 内部的 99 个），把未定义符号与
     APK 内其它库的定义求差集；
   - 凡是 `pg_ / blit_ / alphablit / _PGSLOTS / SDL_ / Py` 这类**本该由 APK 内库提供**的符号
     仍未解决，就 `exit 1`；同时校验所有库都是 aarch64（防交叉编译又编出 x86_64）；
   - 自测：对 1.0.8 旧包 → `RESULT: FAIL`（准确点名该符号）；对修好的包 → `RESULT: PASS`。
3. `.github/workflows/android.yml`
   - 原来的 `nm` 硬编码校验换成上面这个脚本，**符号没解决就不许上传产物**。

### 已交付的应急包
`...\default-workspace\apkfix\fixed\tarkov2d-1.0.8-arm64-v8a-debug-fixed.apk`
—— 二进制原地修好 `surface.so` 后重新签名（v1+v2，debuggable，targetSdk 31）。除
`libpybundle.so` 与签名文件外，其余 31 个条目与原包逐字节相同，versionCode 不变（102110008）。

> 签名 key 与 CI 的 debug key 不同，**装之前必须先卸载旧版**。
> 建议以后固定签名 keystore（CI 每次跑的 `~/.android/debug.keystore` 都是新生成的，
> 导致每次构建都得先卸载才能装）：把 keystore 放进 secret，构建后再用 `apksigner` 定点签名。

---

## 9. 帧率优化（2026-10，1.0.9）

### 实测（同一台 i5-4210U，固定随机种子，场景交叉重复取最小值）

| 场景 | 优化前 | 优化后 |
| --- | --- | --- |
| 藏身处 | 11.9 ms (84 fps) | **3.6 ms (277 fps)** |
| 战局 | 19.7 ms (51 fps) | **11.2 ms (89 fps)** |
| 战局 + 背包 | 32.9 ms (30 fps) | **7.7 ms (130 fps)** |
| 战局 + 搜刮窗 | 24.4 ms (41 fps) | **7.1 ms (141 fps)** |
| 战局 + 交火 | 24.0 ms (42 fps) | **8.3 ms (121 fps)** |

### 三处根因

1. **`get_font()` 每帧重复光栅化文字**（占藏身处 ~85%）。HUD 每帧画十几串文字，
   大部分每帧完全一样。→ `settings._CachedFont` 按 (文字, 抗锯齿, 颜色, 底色) 缓存
   `render()` 结果。全工程没有对 `render()` 结果做原地修改的代码，所以复用同一个
   Surface 是安全的。

2. **战争迷雾每帧算 140 条射线、每条每 12px 采一次样**（占战局 draw 的 ~45%）。
   → `world.visibility_polygon` 改成逐格 DDA：步数是「实际跨越的格数」而不是固定的
   `radius/12`，每步只有一次比较+一次加法；方向向量按角度缓存。
   顺带修正了「迷雾渗进墙里最多 12px」的问题（现在取进入墙格的精确距离）。
   `los_clear` 同样改 DDA（原来每 10px 采样，既慢又会漏掉细墙）。

3. **迷雾合成**：原来是「全屏 SRCALPHA fill + 透明多边形打洞 + 整屏 alpha 混合」，
   1280×720 实测 16.3ms。→ 改成「不透明表面乘性压暗 + `BLEND_RGB_MULT`」，2.2ms。
   亮部完全一致（255 → 75），暗部最多差 8/255。

### 两个必须记住的 SDL2 坑

| 写法 | 1280×720 实测 |
| --- | --- |
| `surf.fill(color)`（不带 flags） | 0.5 ms |
| `surf.fill(color, None, special_flags=BLEND_RGB_ADD)` | **70 ms** ← 千万别用 |
| `screen.blit(opaque, (0,0), special_flags=BLEND_RGB_MULT)` | 0.8 ms |
| `screen.blit(srcalpha, (0,0))`（逐像素 alpha 混合） | 2.4–8.6 ms |

即：**要混合就 blit，不要 fill**；`draw.polygon` 画在 SRCALPHA 表面上会走混合慢路径
（6.4ms），画在不透明表面上只要 1.0ms。

### 怎么复测

需要一台能跑 pygame 的机器（代码电脑/安卓同一套）：

```powershell
# 固定种子 + 场景交叉重复取最小值，避免热降频和后台进程干扰
python tools/bench_frames.py            # 若已加入仓库
```

对比时**必须**用「同一进程、场景交叉、多遍取最小值」，直接逐帧计时会被后台负载和
CPU 降频带偏（同一段代码前后能差一倍）。

---

## 10. 2.3.0：手机操作修复 + 冲 120fps（2026-10-05）

用户反馈：**手机端帧率很低**、**字迹有点模糊**、**不好操作**，要求「改键位 + 保存并应用」，
并把帧率做到 120 以上稳定。

### 10.1 输入层：手机上「点哪都没反应」的真凶

`main.py` 在触屏模式会设 `SDL_TOUCH_MOUSE_EVENTS=0`（避免虚拟摇杆和界面点击双触发），
而藏身处 / 背包 / 搜刮 / 暂停面板**全是鼠标点击驱动**的。第一次启动时存档里 `touch=False`，
SDL 还能把触摸合成鼠标事件；一旦退出过一次（`touch=True` 写进存档），下次启动就彻底
没有鼠标事件了 —— 表现就是「**手机上第二次进去点什么都没反应**」。

修法（`game.synth_mouse_events`）：触屏模式下把每个 `FINGER*` 事件**再合成一份鼠标事件**，
带上 `synthetic=True` 标记：

* 战局操作：原始 FINGER 交给 TouchUI（多指摇杆 + 按钮），**合成的鼠标事件被忽略**（否则双触发）；
* 界面弹窗 / 藏身处：合成事件就是点击 —— 手机能点所有界面（含设置页、触屏布局编辑器）；
* 电脑上 `--touch` 测试用的**真**鼠标事件仍走 TouchUI（靠 `synthetic` 标记区分）。

顺带修的三个手机体验问题：

| 问题 | 修法 |
| --- | --- |
| 手机没有 ESC，**无法暂停** | TouchUI 增加「菜单」按钮（右上角，可自定义位置） |
| 手机没有滚轮，**仓库/交易所/任务列表翻不了页** | 触屏模式在列表右侧画 ▲▼ 翻页按钮（`hideout._scroll_buttons/_scroll_click`） |
| 弹窗开合时残留「按住开火」 | 弹窗打开的瞬间 `TouchUI.reset_hold()`（只清按住态，保留本帧点按队列） |

### 10.2 改键 + 触屏布局（`bindings.py` / `touch.py` / 设置页）

* `bindings.py`：10+ 个动作 → 键位；默认值写死，玩家改动存 `sd.bindings`（只存改过的）；
  `is_down / key_matches / label_for` 是唯一取键入口（别再写死 `K_xxx`）；冲突键**拒绝**并回报占用者。
* `touch.py`：`sd.touch_layout = {name: [rx, ry, r]}` 覆盖默认位置；`merged_layout()` 合并；
  `apply_layout()` 在开战局时生效。
* 设置页在 `hideout.py`（`view="options"`，三标签页 + 「保存并应用」「恢复默认」）：
  控制页点键位按钮改键（ESC 取消）、触屏页**拖动 + −/+ 改大小**（摸屏直接拖）、画质页改帧率/滤镜。
* 教训：新增视图必须同时接进**点击分发**与 **ESC 处理**（见第 6 节记忆），否则返回键没用还会误触。

### 10.3 性能：把「每帧每个敌人一条射线」消灭掉

原实现里 `raid_ui.draw_raid` 每帧对**每个**拾荒者调用一次 `los_clear`（DDA 射线），
`enemy.sees_player` 与 `raid.threat_for` 又各调一次 —— 50 人的突袭图每帧上百条射线。

现在改成**两级缓存**（`raid.refresh_fog`）：

1. **视野多边形**（140 条射线）只在玩家移动 `>= FOG_MOVE_STEP(6px)` 时重算；
2. **可见敌人集合** `raid.fog_vis`：跟随(1)刷新，并且**至少每 `FOG_VIS_REFRESH(0.1s)` 刷一次**
   （玩家站着不动时敌人自己走动也能判定），半径 `FOG_VIS_RADIUS(840) > 最大视距(620)`。

`sees_player`（目标是玩家时）、`threat_for`（玩家可见性）、绘制可见判定全部读这个集合 ——
射线只在需要时打，且每次只打附近的一小撮敌人。

另外三处：

* **迷雾合成层按 `raid.fog_version` 缓存**：玩家不动时每帧只剩一次 `BLEND_RGB_MULT` 整屏 blit；
* **屏幕裁剪**：屏外敌人直接跳过（以前先算视线再画）；
* **HUD 小面板 / 对话框暗幕复用 Surface**（`_hud_bg` / `_overlay`），不再每帧分配；
* **粒子阻尼改成 `0.9 ** (dt*60)`**：帧率无关，120fps 下衰减速度和 60fps 一致（原来每帧 *0.9）。

### 10.4 帧率上限 / FPS 显示 / 缩放滤镜

* `main.py` 每帧读 `game.save.fps_cap`（默认 **120**，0 = 不锁），设置页可改；
* 右上角实时 FPS（`show_fps`，默认开）；
* `SDL_RENDER_SCALE_QUALITY` 在 `set_mode` 前按 `sd.scale_filter` 设（`linear` 柔和 / `nearest` 锐利）。

> **关于「字迹模糊」**：游戏内部分辨率固定 1280×720，手机屏幕（1080p/2K）是全屏**放大**显示的，
> 放大到非整数倍率时文字必然发虚。上面那个滤镜只能选「平滑」还是「硬边」，**做不到像素级清晰**；
> 真正清晰要按手机原生分辨率重做整套界面（所有坐标/字号按比例缩放），属于后续大工程。

### 10.5 CI 缓存：别再让版本号作废工具链

缓存 key 原来是 `buildozer-${{ runner.os }}-${{ hashFiles('buildozer.spec') }}`，
**每次改版本号都会 cache miss** → 工具链全量重建（约 60 分钟，而不是 10 分钟）。
改成固定 key + `restore-keys: buildozer-Linux-`：

```yaml
          key: buildozer-Linux-toolchain-v1
          restore-keys: |
            buildozer-Linux-
```

工具链只取决于 `requirements` / `android.ndk` 这些很少变的行，版本号改动不该影响它。

### 10.6 自检

41 项全过（新增 6 项）：键位自定义（含冲突拒绝/存档往返/战局生效）、触屏布局自定义
（含非法值忽略/开战局应用）、**触屏事件合成**（藏身处真实 FINGER 点击路径 + 战局不双触发）、
**迷雾缓存与暴力重算一致性**、设置页交互（三页切换/改键捕获/保存/恢复默认/渲染）、手机翻页按钮。

基准脚本已进仓库：`python tools/bench_frames.py`（无头、固定种子、交叉重复取最小值）。

### 10.7 实测（i5-4210U，120fps 目标，触屏模式，固定种子）

| 场景 | 2.2.0 | 2.3.0 | 说明 |
| --- | --- | --- | --- |
| 藏身处 | 3.6 ms · 277 fps | **0.65 ms · 1541 fps** | 触摸按钮改贴图缓存后几乎没有开销 |
| 战局静止/搜刮 | 11.2 ms · 89 fps | **3.17 ms · 315 fps** | 迷雾不重算,只剩一次 MULT blit |
| 战局持续移动 | — | **6.17 ms · 162 fps** | 最坏路径:多边形每次移动重算 |
| 战局 + 背包 | 7.7 ms · 130 fps | **3.89 ms · 257 fps** | |
| 战局 + 交火 | 8.3 ms · 121 fps | **5.46 ms · 183 fps** | |
| 战局 + 搜刮窗 | 7.1 ms · 141 fps | **3.29 ms · 304 fps** | |

最坏 6.17 ms/帧（162 fps），120 fps 的预算是 8.3 ms —— 这台 2014 年的 i5 都留了 25% 余量。

profile 显示优化后瓶颈已经变成**纯 blit**（整屏地图 blit + 迷雾 MULT blit 占 46%），
再往下就只能动「分块脏矩形渲染」这类架构改动，收益递减，先到这里。

> 测量注意：同一台机器上先后两次跑同样的场景，可能因为后台进程/降频差出 2 倍
> （实测遇到过一次：同一份代码 6.3 ms 与 15.0 ms）。所以脚本是「场景交叉重复 4 遍取最小值」，
> 并且跑之前先 burn 3 秒让 CPU 到稳定频率。
