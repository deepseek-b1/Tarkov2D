# -*- coding: utf-8 -*-
"""把 Tarkov2D 发布到 GitHub,并触发云端 APK 构建。

用法(PowerShell):
    $env:GITHUB_TOKEN='你的令牌'; python publish_to_github.py 仓库名

令牌需要权限:classic 令牌勾选 repo + workflow;或用 fine-grained 令牌授予
该仓库的 Contents: Read and write 与 Workflows: Read and write。
脚本不会把令牌写入任何文件(推送时通过临时 askpass 传递)。
"""
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

API = "https://api.github.com"
ROOT = os.path.dirname(os.path.abspath(__file__))
GITIGNORE = """__pycache__/
*.pyc
build/
dist/
webapp/
update_server/Tarkov2D.exe
*.spec
selftest_report.txt
version_info.txt
gitasset.txt
diag_result.txt
.codely-cli/
"""


def git_exe():
    for p in (os.path.join(os.environ.get("USERPROFILE", ""),
                           "PortableGit", "cmd", "git.exe"),
              os.path.join(os.environ.get("ProgramFiles", ""), "Git", "cmd", "git.exe"),
              "git"):
        try:
            subprocess.run([p, "--version"], capture_output=True, check=True)
            return p
        except Exception:
            continue
    raise SystemExit("找不到 git,请先安装 Git 或 PortableGit")


def api(method, path, data=None, token=""):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(API + path, data=body, method=method, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "Tarkov2D-publisher",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            text = r.read().decode()
            return r.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}
    except Exception as e:
        return 0, {"error": f"{type(e).__name__}: {e}"}


def main():
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise SystemExit("请先设置环境变量 GITHUB_TOKEN(你的 GitHub 令牌)")
    repo = (sys.argv[1] if len(sys.argv) > 1 else "Tarkov2D").strip()
    git = git_exe()

    status, me = api("GET", "/user", token=token)
    if status != 200:
        raise SystemExit(f"令牌无效或网络不通: {status} {me}")
    user = me["login"]
    print(f"[1/5] 已认证:{user},目标仓库:{repo}")

    status, res = api("POST", "/user/repos", {
        "name": repo, "private": False,
        "description": "Tarkov2D 类塔科夫 2D 搜打撤(pygame,电脑/手机/网页)",
    }, token=token)
    print("[2/5] 创建仓库:", "成功" if status == 201 else f"已存在/跳过({status})")

    # 本地提交
    with open(os.path.join(ROOT, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(GITIGNORE)
    def run(*args, **kw):
        return subprocess.run([git, *args], cwd=ROOT, capture_output=True, text=True, **kw)
    if not os.path.isdir(os.path.join(ROOT, ".git")):
        run("init", "-b", "main")
    run("config", "user.name", user)
    run("config", "user.email", f"{user}@users.noreply.github.com")
    run("add", "-A")
    run("commit", "-m", "Tarkov2D: 电脑/手机/网页三端版本(自动更新 + 头目/装备/多地图)")
    print("[3/5] 本地提交完成")

    # 推送:令牌只短暂存在于远程地址中,推完立刻改回干净地址;输出里也会打码
    clean_url = f"https://github.com/{user}/{repo}.git"
    auth_url = f"https://{user}:{token}@github.com/{user}/{repo}.git"

    def sanitize(text):
        return (text or "").replace(token, "***")

    run("remote", "remove", "origin")
    run("remote", "add", "origin", auth_url)
    push = subprocess.run([git, "-c", "credential.helper=", "push", "-u",
                           "origin", "main", "--force"],
                          cwd=ROOT, capture_output=True, text=True)
    run("remote", "set-url", "origin", clean_url)      # 立刻抹掉令牌
    if push.returncode != 0:
        print(sanitize(push.stdout[-400:]))
        print(sanitize(push.stderr[-800:]))
        raise SystemExit("推送失败:检查令牌是否有 repo + workflow 权限")
    print(f"[4/5] 已推送到 {clean_url}")

    status, _ = api("POST",
                    f"/repos/{user}/{repo}/actions/workflows/android.yml/dispatches",
                    {"ref": "main"}, token=token)
    print("[5/5] 触发云端构建:", "已触发" if status in (204, 200) else f"失败({status})")
    print(f"\n打开下面地址查看/下载 APK:\n  https://github.com/{user}/{repo}/actions")


if __name__ == "__main__":
    main()
