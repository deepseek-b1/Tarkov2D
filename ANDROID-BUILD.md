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

## 3. 已经踩过并修好的 8 个坑（按出现顺序）

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
