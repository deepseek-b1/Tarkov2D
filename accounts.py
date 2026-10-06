# -*- coding: utf-8 -*-
"""本地账号:一个「名字 + 密码」= 一份独立存档。

存档文件在 <存档目录>/accounts/<名字>/save.json,账号表在 accounts/index.json。
密码只存 PBKDF2-HMAC-SHA256 的加盐哈希(不存明文;忘了密码无法找回,只能删号重来)。
单档时代的 save.json 会在**第一次建号**时自动并入该账号(不丢进度)。
"""
import hashlib
import hmac
import json
import os
import re
import time

import save as save_mod

ITERATIONS = 120_000          # PBKDF2 迭代次数(哈希写在 index.json 里,以后可改)
NAME_MAX = 12
NAME_RE = re.compile(r"^[A-Za-z0-9_\-]{1,%d}$" % NAME_MAX)
LEGACY_MARKER = "legacy_imported"     # 老档只并入一次


def accounts_dir():
    """账号目录(跟着当前存档目录走,自检里换了 SAVE_DIR 也不会写错地方)。"""
    return os.path.join(save_mod.SAVE_DIR, "accounts")


def index_path():
    return os.path.join(accounts_dir(), "index.json")


def legacy_save_path():
    """单档时代的存档文件(<存档目录>/save.json)。"""
    return os.path.join(save_mod.SAVE_DIR, "save.json")


def slug(name):
    """名字 -> 目录名/索引键(大小写不敏感,Windows 文件系统本来也不区分)。"""
    return str(name).strip().lower()


def valid_name(name):
    return bool(NAME_RE.match(str(name or "").strip()))


def name_reason(name):
    """名字不合法的原因(给界面提示用);合法返回 None。"""
    n = str(name or "").strip()
    if not n:
        return "先输入名字"
    if len(n) > NAME_MAX:
        return f"名字最多 {NAME_MAX} 个字符"
    if not NAME_RE.match(n):
        return "名字只能用字母 / 数字 / 下划线 _ / 横杠 -"
    return None


def _read_index():
    path = index_path()
    if not os.path.exists(path):
        return {"accounts": {}, "last": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("bad index")
        data.setdefault("accounts", {})
        data.setdefault("last", "")
        if not isinstance(data["accounts"], dict):
            data["accounts"] = {}
        return data
    except Exception:
        # 索引损坏:备份后重建(存档文件本身还在各自的目录里,不会丢)
        try:
            os.replace(path, path + ".broken-" + str(int(time.time())))
        except OSError:
            pass
        return {"accounts": {}, "last": ""}


def _write_index(data):
    os.makedirs(accounts_dir(), exist_ok=True)
    tmp = index_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, index_path())


def _hash_password(password, salt, iterations=ITERATIONS, dklen=32):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                               iterations, dklen)


def list_names():
    """已有账号的名字(按创建时间,旧的在前)。"""
    data = _read_index()
    items = []
    for key, ent in data["accounts"].items():
        if not isinstance(ent, dict):
            continue
        items.append((float(ent.get("created", 0) or 0), str(ent.get("name", key))))
    items.sort(key=lambda t: (t[0], t[1]))
    return [n for _c, n in items]


def last_name():
    """上次进过的账号名(登录界面默认填上,少打一次字)。"""
    return str(_read_index().get("last") or "")


def exists(name):
    return slug(name) in _read_index()["accounts"]


def profile_dir(name):
    return os.path.join(accounts_dir(), slug(name))


def profile_save_path(name):
    return os.path.join(profile_dir(name), "save.json")


def has_legacy():
    """还有没被并入任何账号的老存档吗?"""
    if os.path.exists(os.path.join(accounts_dir(), LEGACY_MARKER)):
        return False
    return os.path.exists(legacy_save_path())


def _claim_legacy(name):
    """把老存档搬进这个账号(只做一次)。返回是否搬了。"""
    if not has_legacy():
        return False
    dst = profile_save_path(name)
    src = legacy_save_path()
    if os.path.exists(dst):
        return False
    os.makedirs(profile_dir(name), exist_ok=True)
    try:
        os.replace(src, dst)
    except OSError:
        return False
    try:
        with open(os.path.join(accounts_dir(), LEGACY_MARKER), "w",
                  encoding="utf-8") as f:
            f.write(f"{name}\n{int(time.time())}\n")
    except OSError:
        pass
    return True


def register(name, password):
    """建号。返回 (ok, 说明)。名字必须合法且没被占用,密码至少 3 位。"""
    name = str(name or "").strip()
    why = name_reason(name)
    if why:
        return False, why
    if not password or len(password) < 3:
        return False, "密码至少 3 位"
    data = _read_index()
    key = slug(name)
    if key in data["accounts"]:
        return False, "这个名字已经有人用了,换个名字(或直接输密码进入)"
    salt = os.urandom(16)
    data["accounts"][key] = {
        "name": name,
        "salt": salt.hex(),
        "hash": _hash_password(password, salt).hex(),
        "iter": ITERATIONS,
        "created": time.time(),
        "logins": 0,
    }
    _write_index(data)
    return True, ""


def verify(name, password):
    """名字 + 密码是否正确。"""
    data = _read_index()
    ent = data["accounts"].get(slug(name))
    if not isinstance(ent, dict):
        return False
    try:
        salt = bytes.fromhex(str(ent.get("salt", "")))
        want = str(ent.get("hash", ""))
        it = int(ent.get("iter", ITERATIONS) or ITERATIONS)
    except (TypeError, ValueError):
        return False
    got = _hash_password(password or "", salt, it).hex()
    return hmac.compare_digest(got, want)


def use(name):
    """切到该账号的存档(之后 load_data/save_data 都读写这份)。返回是否成功。"""
    name = str(name or "").strip()
    if slug(name) not in _read_index()["accounts"]:
        return False
    save_mod.use_profile(slug(name))
    data = _read_index()
    ent = data["accounts"].get(slug(name))
    if isinstance(ent, dict):
        ent["logins"] = int(ent.get("logins", 0) or 0) + 1
        ent["last_login"] = time.time()
    data["last"] = ent.get("name", name) if isinstance(ent, dict) else name
    _write_index(data)
    return True


def login(name, password):
    """登录:校验密码 -> 切存档。返回 (ok, 说明, 是否并入了老存档)。"""
    name = str(name or "").strip()
    why = name_reason(name)
    if why:
        return False, why, False
    if not exists(name):
        return False, "没有这个账号", False
    if not verify(name, password):
        return False, "密码不对", False
    migrated = _claim_legacy(name)
    use(name)
    return True, "", migrated


def register_and_login(name, password):
    """建号并直接进入。返回 (ok, 说明, 是否并入了老存档)。"""
    ok, why = register(name, password)
    if not ok:
        return False, why, False
    migrated = _claim_legacy(name)
    use(name)
    return True, "", migrated


def remove(name, password):
    """删号(要密码)。返回 (ok, 说明);存档文件改成 .deleted-<时间> 备份。"""
    name = str(name or "").strip()
    if not verify(name, password):
        return False, "密码不对,不能删除"
    path = profile_save_path(name)
    if os.path.exists(path):
        try:
            os.replace(path, path + ".deleted-" + str(int(time.time())))
        except OSError:
            return False, "存档删除失败(文件被占用?)"
    data = _read_index()
    data["accounts"].pop(slug(name), None)
    _write_index(data)
    return True, "账号已删除(存档文件备份为 .deleted-*)"
