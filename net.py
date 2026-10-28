# -*- coding: utf-8 -*-
"""局域网联机:主机权威模拟 + 客户端镜像渲染。

设计
----
* 主机(host):跑完整战局模拟。P1 = 本机玩家,P2 = 联网玩家(输入来自网络)。
* 客户端(client):不跑模拟,只接收主机发来的状态补丁,按**自己的视角**渲染;
  本机操作(移动/瞄准/开火/换弹/打药/交互)打包上传给主机执行。
* 两侧都沿用 raid.coop 的双人模型:本机玩家在 raid.player,队友在 raid.player2。
  主机快照里的 player / player2 在客户端侧**对调**(见 _SWAP / _PAIR)。

同步方式
--------
把 raid 的指定属性编码成一棵可 JSON 的树,和上一帧的树做 diff,
只把变化的叶子(路径 + 新值)发出去,zlib 压缩。一帧几 KB,30Hz 很轻松。
对象的跨引用(比如拾荒者的目标指向某位玩家)按"树内路径"传递。

协议(TCP,4 字节大端长度 + 载荷)
--------------------------------
  C->H  {"t":"hello","name":..,"ver":..}
  C->H  {"t":"in", ...}                     每帧输入
  C->H  {"t":"bye"}
  H->C  {"t":"welcome","host":..}
  H->C  {"t":"start","cfg":{...}}
  H->C  {"t":"p","d":<zlib 压缩的补丁 JSON>}
  H->C  {"t":"ev","k":"extract"/"over"/"msg","data":{...}}
  H->C  {"t":"bye"}
发现(UDP 广播):C 广播 b"T2D?"  ->  H 回 b"T2D!<房间名>|<tcp端口>|<状态>"
"""
import json
import math
import os
import queue
import socket
import struct
import sys
import threading
import time
import zlib

import pygame

PROTO = 1
TCP_PORT = 27511
UDP_PORT = 27512
HDR = struct.Struct("!I")
SNAP_HZ = 30.0            # 主机发快照的频率
COLD_EVERY = 1.0          # 结构类数据(箱子内容等)多久发一次
DEBUG = bool(os.environ.get("T2D_NET_DEBUG"))

# --------------------------------------------------------------------------
# 序列化:对象图 <-> 可 JSON 的树
# --------------------------------------------------------------------------
# 节点形式:
#   标量                -> 原样
#   {"__t__":[...]}     -> 元组
#   {"__s__":[...]}     -> 集合
#   {"__d__":[[k,v]..]} -> 字典(键可能不是字符串)
#   {"__rc__":[x,y,w,h]}-> pygame.Rect
#   {"__r__":[路径]}    -> 指向树内另一个对象的引用
#   {"__o__":"类名", 字段: 值, ...} -> 游戏对象(其余键就是它的字段)
_REF = "__r__"
_OBJ = "__o__"

# 一个对象最多递归多深(防止意外自引用造成爆炸)
_MAX_DEPTH = 8


def _registry():
    """已加载游戏模块里的类名 -> 类(只收本模块定义的类)。缓存起来,别每帧重扫。"""
    global _REG_CACHE
    if _REG_CACHE:
        return _REG_CACHE
    reg = {}
    for modname in ("raid", "world", "enemy", "npc", "inventory", "story", "uikit"):
        mod = sys.modules.get(modname)
        if mod is None:
            continue
        for name, val in list(vars(mod).items()):
            if isinstance(val, type) and getattr(val, "__module__", "") == modname:
                reg.setdefault(name, val)
    if reg:
        _REG_CACHE = reg
    return reg


_REG_CACHE = None


# 这些字段只在模拟里有意义(客户端不跑模拟),传过去纯粹浪费带宽。
# 注意:凡是渲染/界面会读的字段(比如 Scav.d 这种配置)都不能跳,
# 否则客户端一画就 AttributeError(自检里的渲染用例抓到过一次)。
_FIELD_SKIP = {
    "Scav": {"path", "path_i", "think", "repath_t", "search_t",
             "tgt_t", "tgt_see", "lod_phase", "view2", "wander_t"},
}
# 这些类整个不传
_CLASS_SKIP = {"Game", "Raid", "TouchUI", "Hold"}


def _obj_fields(obj):
    """取一个对象的可序列化字段(支持 __slots__)。"""
    cls = type(obj)
    skip = _FIELD_SKIP.get(cls.__name__, ())
    slots = getattr(cls, "__slots__", None)
    if slots:
        return {s: getattr(obj, s, None) for s in slots if s not in skip}
    d = getattr(obj, "__dict__", None)
    if d is None:
        return None
    return {k: v for k, v in d.items() if k not in skip and not k.startswith("_")}


def encode_value(v, path, seen, reg, depth=0):
    """把一个值编码成树节点;无法/不该传的返回 _SKIP。"""
    if v is None or v is True or v is False:
        return v
    t = type(v)
    if t is int or t is str:
        return v
    if t is float:
        if v != v or v in (float("inf"), float("-inf")):
            return 0.0
        return v
    if t is pygame.Rect:
        return {"__rc__": [v.x, v.y, v.w, v.h]}
    if t is list or t is tuple or t is set or t is frozenset:
        # 只有「可变容器」才做跨引用。tuple/frozenset 是颜色、坐标这类不可变小值,
        # 而且经常被大量对象共用**同一个对象**(比如 COL["text"] 被几十条提示共用)。
        # 给它们发 {"__r__": 路径} 会在客户端埋雷:路径是按列表下标解析的,
        # 列表一变(提示过期、粒子消失、敌人被击杀)就指到别的元素或 None ——
        # 颜色变 None 后字体渲染直接 TypeError("invalid color argument") 闪退。
        # 所以不可变容器一律**内联**编码。
        mutable = (t is list)
        oid = id(v)
        if mutable:
            if oid in seen:
                return {_REF: list(seen[oid])}
            if depth >= _MAX_DEPTH:
                return _SKIP
            seen[oid] = path
        elif depth >= _MAX_DEPTH:
            return _SKIP
        items = [encode_value(x, path + [i], seen, reg, depth + 1)
                 for i, x in enumerate(v)]
        if t is list:
            return items
        if t is tuple:
            return {"__t__": items}
        return {"__s__": items}
    if t is dict:
        oid = id(v)
        if oid in seen:
            return {_REF: list(seen[oid])}
        if depth >= _MAX_DEPTH:
            return _SKIP
        seen[oid] = path
        pairs = []
        for k, val in v.items():
            kn = encode_value(k, path + ["k"], seen, reg, depth + 1)
            if kn is _SKIP:
                continue
            vn = encode_value(val, path + [k if isinstance(k, str) else "k"],
                              seen, reg, depth + 1)
            if vn is _SKIP:
                continue
            pairs.append([kn, vn])
        return {"__d__": pairs}
    # 游戏对象
    cls = t
    if cls.__name__ in _CLASS_SKIP or cls.__name__ not in reg:
        return _SKIP
    oid = id(v)
    if oid in seen:
        return {_REF: list(seen[oid])}
    if depth >= _MAX_DEPTH:
        return _SKIP
    fields = _obj_fields(v)
    if fields is None:
        return _SKIP
    seen[oid] = path
    node = {_OBJ: cls.__name__}
    for k, val in fields.items():
        vn = encode_value(val, path + [k], seen, reg, depth + 1)
        if vn is not _SKIP:
            node[k] = vn
    return node


_SKIP = object()


def encode_state(root, keys):
    """把 root 的若干属性编码成一棵树。"""
    reg = _registry()
    seen = {}
    out = {}
    for k in keys:
        if not hasattr(root, k):
            continue
        node = encode_value(getattr(root, k), [k], seen, reg)
        if node is not _SKIP:
            out[k] = node
    return out


def decode_value(node, root, depth=0, existing=None):
    """树节点 -> 值(需要 root 来解析引用)。

    existing 是本地该位置上已有的对象:类型对得上就**就地改**,
    这样没传过来的字段(纯 AI 内部状态)不会被抹掉,对象引用也不会失效。
    """
    if node is None or node is True or node is False:
        return node
    t = type(node)
    if t is int or t is float or t is str:
        return node
    if t is list:
        return [decode_value(x, root, depth + 1) for x in node]
    if t is dict:
        if "__rc__" in node:
            x, y, w, h = node["__rc__"]
            return pygame.Rect(int(x), int(y), int(w), int(h))
        if _REF in node:
            got = get_path(root, node[_REF])
            if got is None and existing is not None:
                # 路径失效(列表元素被删/挪位):保留本地值,别把字段写成 None
                return existing
            return got
        if "__t__" in node:
            return tuple(decode_value(x, root, depth + 1) for x in node["__t__"])
        if "__s__" in node:
            return set(decode_value(x, root, depth + 1) for x in node["__s__"])
        if "__d__" in node:
            out = {}
            for k, v in node["__d__"]:
                out[decode_value(k, root, depth + 1)] = decode_value(v, root, depth + 1)
            return out
        if _OBJ in node:
            cls = _registry().get(node[_OBJ])
            if cls is None:
                return existing
            if existing is not None and type(existing) is cls:
                obj = existing
            else:
                obj = cls.__new__(cls)
            for k, v in node.items():
                if k == _OBJ:
                    continue
                sub = None
                try:
                    sub = getattr(obj, k)
                except Exception:
                    sub = None
                try:
                    setattr(obj, k, decode_value(v, root, depth + 1, sub))
                except AttributeError:
                    pass
            return obj
    return None


def get_path(root, path):
    """按路径取值(取不到返回 None)。"""
    cur = root
    for k in path:
        if cur is None:
            return None
        try:
            if isinstance(k, int):
                if not isinstance(cur, (list, tuple)) or k >= len(cur) or k < 0:
                    return None
                cur = cur[k]
            else:
                if isinstance(cur, (list, tuple)):
                    return None
                cur = getattr(cur, k, None) if not isinstance(cur, dict) else cur.get(k)
        except Exception:
            return None
    return cur


_WRAP = ("__d__", "__t__", "__s__")


def _wrap_seq(node):
    """编码包装节点 -> 它的成员列表(__d__/__t__/__s__),不是包装就返回 None。"""
    if not isinstance(node, dict):
        return None
    for w in _WRAP:
        if w in node:
            return node[w]
    return None


def live_path(root, path):
    """把**编码树路径**翻译成**活对象图路径**。

    为什么要翻译:diff_tree 的叶子路径是顺着编码树走的,里面夹着
    {"__d__": [[k, v], ...]} 这类包装 —— 路径会变成
    ["particles", 0, "__d__", 6, 1],而活对象那边其实是 ["particles", 0, "color"]。
    规则:每走一步先看**活对象**的类型,再按编码树的形状把这一步翻译过去:
      * 活 list/tuple -> 编码树这里是列表,下标可以直接用;
      * 活 dict -> 编码树这里是 {"__d__": [[键, 值], ...]},所以路径里会多出
        "__d__" 和一个**键位**下标,真正的键名要从包装里取出来;
      * 活对象是 dict 而编码树那里装的是元组/集合包装(不透明字典)
        -> 编码路径多一个 "__t__"/"__s__" 层级,顺延一位即可。
    不翻译的话「列表里的字典」(粒子、子弹这些)一条补丁也写不进去:
    客户端收到补丁但值一直是 None,画面就会崩成没有颜色的粒子。
    取不到就返回 None(调用方按"路径失效"处理)。
    """
    cur = root            # 活对象图上的位置
    new = None            # 编码树上对应的节点
    out = []
    for k in path:
        if cur is None:
            return None
        if isinstance(cur, (list, tuple)):
            if not isinstance(k, int) or k < 0 or k >= len(cur):
                return None
            out.append(k)
            cur = cur[k]
            new = new[k] if isinstance(new, list) and k < len(new) else None
        elif isinstance(cur, dict):
            if k in cur:
                # 活对象是不透明字典:键名照旧(编码路径多一层 __t__/__s__ 也无妨)
                out.append(k)
                cur = cur[k]
                new = new.get(k) if isinstance(new, dict) else None
                continue
            if k == "__d__" or not (isinstance(new, dict) and "__d__" in new):
                return None
            pairs = new["__d__"]
            if not isinstance(k, int) or k < 0 or k >= len(pairs):
                return None
            item = pairs[k]
            if not (isinstance(item, (list, tuple)) and len(item) == 2):
                return None
            key = item[0]                      # 真正的键名(编码后仍是 str/int)
            if key not in cur:
                return None
            out.append(key)
            cur = cur[key]
            new = item[1]
        else:
            out.append(k)
            cur = getattr(cur, k, None)
            new = new.get(k) if isinstance(new, dict) else None
    return out


def set_path(root, path, value):
    """按路径写值(只写已存在的结构;列表长度变化由整表替换处理)。

    路径是**活对象图路径**(diff_tree 已经把编码树里的 __d__/__t__ 包装
    翻译掉了),所以这里只管老老实实往下走。
    """
    if not path:
        return False
    cur = root
    for k in path[:-1]:
        if cur is None:
            return False
        try:
            if isinstance(k, int):
                cur = cur[k]
            elif isinstance(cur, dict):
                cur = cur.get(k)
            else:
                cur = getattr(cur, k)
        except Exception:
            return False
    last = path[-1]
    try:
        if isinstance(last, int):
            cur[last] = value
        elif isinstance(cur, dict):
            cur[last] = value
        else:
            setattr(cur, last, value)
        return True
    except Exception:
        return False


def diff_tree(old, new, path, out, live=None):
    """比较两棵编码树,把变化收进 out(每项是 (路径, 新节点))。

    live 是**活对象图路径**:编码树里 {"__d__": [[键, 值], ...]} 这层包装在活
    对象上并不存在,所以 (path, live) 要分头记 —— 补丁路径必须是活的,客户端
    set_path 才写得进去。否则「列表里的字典」(粒子、子弹这些)一条也过不去:
    客户端收到补丁但值一直是 None,画面就会崩成没有颜色的粒子。
    """
    if live is None:
        live = path
    if type(old) is not type(new):
        out.append((live, new))
        return
    if isinstance(new, list):
        if not isinstance(old, list) or len(old) != len(new):
            out.append((live, new))
            return
        for i, (a, b) in enumerate(zip(old, new)):
            diff_tree(a, b, path + [i], out, live + [i])
        return
    if isinstance(new, dict):
        if _OBJ in new:
            if old.get(_OBJ) != new.get(_OBJ):
                out.append((live, new))
                return
            for k, b in new.items():
                if k == _OBJ:
                    continue
                if k not in old:
                    out.append((live + [k], b))
                else:
                    diff_tree(old[k], b, path + [k], out, live + [k])
            return
        if "__rc__" in new or _REF in new:
            if old != new:
                out.append((live, new))
            return
        if "__d__" in new:
            if "__d__" not in old or len(old["__d__"]) != len(new["__d__"]):
                out.append((live, new))
                return
            for i, (a, b) in enumerate(zip(old["__d__"], new["__d__"])):
                # a / b 是 [键, 值];键只有"改了名"才算变化,活路径上只留键名
                if not (isinstance(a, (list, tuple)) and len(a) == 2
                        and isinstance(b, (list, tuple)) and len(b) == 2):
                    out.append((live, new))
                    return
                if a[0] != b[0]:
                    out.append((live, new))
                    return
                diff_tree(a[1], b[1], path + ["__d__", i, 1], out, live + [b[0]])
            return
        if "__t__" in new or "__s__" in new:
            if old != new:
                out.append((live, new))
            return
        out.append((live, new))
        return
    if old != new:
        out.append((live, new))


def _patch_writable(root, path, node):
    """这条叶子补丁在**本地对象图**(主机这边的 raid)上落得下去吗?

    主机和客户端的对象图结构是一样的,所以主机自己走得通,客户端就走得通;
    列表长度/结构已经变了的时候,叶子补丁会全部写不进去 —— 那就得整棵子树重发。
    """
    cur = root
    for k in path[:-1]:
        if cur is None:
            return False
        if isinstance(k, int):
            if not isinstance(cur, (list, tuple)) or not (0 <= k < len(cur)):
                return False
            cur = cur[k]
            continue
        if isinstance(cur, dict):
            if k not in cur:
                return False
            cur = cur[k]
            continue
        return False
    if cur is None:
        return False
    last = path[-1]
    if isinstance(last, int):
        return isinstance(cur, (list, tuple)) and 0 <= last < len(cur)
    if isinstance(cur, dict):
        return last in cur
    return True


def _old_sub(old_node, new_node):
    """在上一帧的编码树里,取出与 new_node 形状对应的那棵子树。

    为什么需要它:客户端 apply 时会把 player/player2、fire_edge/p2_fire_edge
    这类字段对调(Patcher.map_path),所以服务器这边的 diff 必须按**补丁路径**
    去取旧节点,而不是按属性名去缓存树里取 —— 否则 P2 的字段会拿 P1 的旧值
    去比,生成一堆假补丁(颜色/坐标被反复写成 None 就是这么来的)。
    """
    if new_node is None or isinstance(new_node, (bool, int, float, str)):
        return old_node
    if isinstance(new_node, list):
        if not isinstance(old_node, list):
            return None
        out = []
        for i, sub in enumerate(new_node):
            got = _old_sub(old_node[i] if i < len(old_node) else None, sub)
            if got is None and not (sub is None or sub is False):
                return None
            out.append(got)
        return out
    if isinstance(new_node, dict):
        if not isinstance(old_node, dict):
            return None
        out = {}
        for k, sub in new_node.items():
            got = _old_sub(old_node.get(k), sub)
            if got is None and not (sub is None or sub is False):
                return None
            out[k] = got
        return out
    return old_node


class Patcher:
    """把补丁应用到本地对象图(路径可整体对调 P1/P2)。"""

    def __init__(self, swap=False):
        self.swap = swap

    def map_path(self, path):
        if isinstance(path, str):        # 兜底:单个属性名也算一条路径
            path = [path]
        if not self.swap or not path:
            return path
        p = list(path)
        if p[0] == "player":
            p[0] = "player2"
        elif p[0] == "player2":
            p[0] = "player"
        elif len(p) == 1 and p[0] in _PAIR:
            p[0] = _PAIR[p[0]]
        return p

    def map_node(self, node):
        if not self.swap:
            return node
        if isinstance(node, dict):
            if _REF in node:
                return {_REF: self.map_path(node[_REF])}
            return {k: self.map_node(v) for k, v in node.items()}
        if isinstance(node, list):
            return [self.map_node(x) for x in node]
        return node

    def apply(self, root, patches):
        n = 0
        for path, node in patches:
            p = self.map_path(path)
            if p is None or not p:
                continue
            node = self.map_node(node)
            cur = get_path(root, p)
            val = decode_value(node, root, 0, cur)
            if set_path(root, p, val):
                n += 1
        return n


# 客户端侧 P1/P2 专属字段对调(本机在 raid.player,队友在 raid.player2)
_PAIR = {
    "extract_t": "p2_extract_t", "p2_extract_t": "extract_t",
    "revive_used": "p2_revive_used", "p2_revive_used": "revive_used",
    "fire_edge": "p2_fire_edge", "p2_fire_edge": "fire_edge",
    "start_value": "p2_start_value", "p2_start_value": "start_value",
    "sight_vis": "sight_vis2", "sight_vis2": "sight_vis",
    "fog_px": "fog2_px", "fog2_px": "fog_px",
    "fog_py": "fog2_py", "fog2_py": "fog_py",
    "fog_aim": "fog2_aim", "fog2_aim": "fog_aim",
}

# 每帧都要发的(视觉/操作相关)
HOT_KEYS = (
    "player", "player2", "scavs", "allies", "hostages", "bullets", "particles",
    "toasts", "floaters", "channel", "time_left", "over", "result", "shake",
    "structures", "objectives", "friend_structs", "supplies", "strikes",
    "support_points", "recon_t", "extract_t", "p2_extract_t", "fire_edge",
    "p2_fire_edge", "banked", "bank_lost", "kills", "loot_log", "warned",
    "dialogue", "subtitle", "cutscene", "story_targets", "captive_state",
    "enemy_waves", "ally_waves", "hq_teams", "hq_t", "support_calls",
    "revive_used", "p2_revive_used", "start_value", "p2_start_value",
    "fog_dirty", "fog_version", "move_mul",
    # 侦察无人机:主机模拟,客户端镜像(视野多边形由各自本地算)
    "drone", "drone_marks", "drone_cd",
)
# 变化较慢但客户端也要用的(箱子内容/地面掉落等)
COLD_KEYS = ("containers", "map_key", "mode", "dark")


# --------------------------------------------------------------------------
# 传输层
# --------------------------------------------------------------------------
def _pack(obj, compress=False):
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if compress:
        data = b"\x01" + zlib.compress(data, 3)
    else:
        data = b"\x00" + data
    return HDR.pack(len(data)) + data


def _unpack(raw):
    if raw[:1] == b"\x01":
        raw = zlib.decompress(raw[1:])
    else:
        raw = raw[1:]
    return json.loads(raw.decode("utf-8"))


class _Link:
    """一条 TCP 连接:收包线程 + 发包线程。"""

    def __init__(self, sock, on_msg, on_close=None):
        self.sock = sock
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except Exception:
            pass
        self.on_msg = on_msg
        self.on_close = on_close
        self.alive = True
        self._out = queue.Queue(maxsize=240)
        self._send_t = threading.Thread(target=self._send_loop, daemon=True)
        self._recv_t = threading.Thread(target=self._recv_loop, daemon=True)
        self._send_t.start()
        self._recv_t.start()

    def send(self, obj, compress=False, droppable=False):
        if not self.alive:
            return
        try:
            self._out.put_nowait((obj, compress))
        except queue.Full:
            if not droppable:
                try:
                    self._out.get_nowait()      # 丢最旧的,别把控制消息卡死
                    self._out.put_nowait((obj, compress))
                except Exception:
                    pass

    def _send_loop(self):
        while self.alive:
            try:
                obj, comp = self._out.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.sock.sendall(_pack(obj, comp))
            except Exception:
                self._close()
                return

    def _recv_loop(self):
        buf = b""
        try:
            self.sock.settimeout(0.5)
            while self.alive:
                try:
                    chunk = self.sock.recv(65536)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if not chunk:
                    break
                buf += chunk
                while len(buf) >= 4:
                    (n,) = HDR.unpack_from(buf, 0)
                    if n > 8 * 1024 * 1024:
                        raise ValueError("bad frame")
                    if len(buf) < 4 + n:
                        break
                    raw = buf[4:4 + n]
                    buf = buf[4 + n:]
                    try:
                        self.on_msg(_unpack(raw))
                    except Exception:
                        pass
        except Exception:
            pass
        self._close()

    def _close(self):
        if not self.alive:
            return
        self.alive = False
        try:
            self.sock.close()
        except Exception:
            pass
        if self.on_close:
            try:
                self.on_close()
            except Exception:
                pass

    def close(self):
        self._close()


# --------------------------------------------------------------------------
# 主体
# --------------------------------------------------------------------------
class Net:
    def __init__(self, game):
        self.game = game
        self.role = None                 # None / "host" / "client"
        self.room_name = ""
        self.link = None                 # _Link
        self.peer_name = ""
        self.error = ""
        self.msg = "未联机"
        self._srv = None
        self._acc_t = None
        self._udp = None
        self._udp_t = None
        self._stop = False
        self._inbox = []                 # 收包线程写入,主线程取走
        self._lock = threading.Lock()
        self._hosts = {}                 # ip -> {ip,name,port,ts}
        self._scan_until = 0.0
        self._last_hot = 0.0
        self._last_cold = 0.0
        self._old_hot = None
        self._old_cold = None
        self._bytes_out = 0
        self._input = {}                 # 主机侧:客户端最新输入
        self._acts = []                  # 主机侧:待执行动作
        self._client_ready = False
        # 主机侧要发给客户端的开局配置
        self._cfg = {}

    # ---------------- 状态 ----------------
    def status_text(self):
        if self.role is None:
            return "未联机 —— 两台电脑连同一个 Wi-Fi/路由器即可"
        if self.role == "host":
            if self.link is None:
                return "房间已开:%s(%s)· 等待对方点「搜索并加入」" % (
                    self.room_name, _local_ip())
            if self._client_ready:
                return "已连接:%s · 在藏身处点「开始联机战局」" % self.peer_name
            return "对方已连上(%s)· 握手…" % self.peer_name
        if self.link is None:
            return "连接中…" if not self.error else ("连接失败:" + self.error)
        if self.game.phase == "raid":
            return "联机中 · 队友:%s" % (self.peer_name or "房主")
        return "已连接房主:%s · 等房主开始战局" % (self.peer_name or "?")

    def found_hosts(self):
        now = time.time()
        out = []
        for ip, h in list(self._hosts.items()):
            if now - h["ts"] > 4.0:
                del self._hosts[ip]
                continue
            out.append(dict(h))
        out.sort(key=lambda h: h["ip"])
        return out

    def request_scan(self):
        """广播一次"谁在开房",结果 1 秒内陆续进 found_hosts()。"""
        self._scan_until = time.time() + 1.2
        if self._udp is None:
            self._start_udp(respond=False)      # 客户端第一次扫描时现开 UDP
        if self._udp is None:
            return
        pkt = b"T2D?"
        for addr in ("255.255.255.255", _bcast_addr()):
            if not addr:
                continue
            try:
                self._udp.sendto(pkt, (addr, UDP_PORT))
            except Exception:
                pass

    # ---------------- 主机 ----------------
    def host_room(self, name=None, port=None):
        if self.role == "client":
            self.close()
        if self.role == "host":
            return True
        port = int(port or TCP_PORT)
        self.room_name = name or ("%s 的房间" % _local_ip())
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("", port))
            srv.listen(2)
            srv.settimeout(0.5)
        except Exception as e:
            self.error = "%s(端口 %d 可能被占用)" % (e, port)
            self.msg = self.error
            return False
        self.port = port
        self._srv = srv
        self.role = "host"
        self.msg = "房间已开"
        if DEBUG:
            print("[net] 开房成功 %s:%d" % (_local_ip(), port), flush=True)
        self._start_udp(respond=True)
        self._acc_t = threading.Thread(target=self._accept_loop, daemon=True)
        self._acc_t.start()
        return True

    def _accept_loop(self):
        while self.role == "host" and not self._stop:
            try:
                conn, addr = self._srv.accept()
            except socket.timeout:
                continue
            except Exception:
                break
            if self.link is not None:
                try:
                    conn.close()
                except Exception:
                    pass
                continue
            self.link = _Link(conn, self._on_msg, self._on_link_down)
            self.peer_name = addr[0]
            self.link.send({"t": "welcome", "host": self.room_name, "ver": PROTO})
        self._srv = None

    def _on_link_down(self):
        self.link = None
        self._client_ready = False
        self._input = {}
        self._old_hot = None
        self._old_cold = None
        with self._lock:
            self._inbox.append({"t": "_down"})

    def host_start(self, cfg):
        """主机开局:把配置发给客户端。"""
        self._cfg = dict(cfg)
        self._old_hot = None
        self._old_cold = None
        self._last_hot = 0.0
        self._last_cold = 0.0
        if self.link is not None:
            self.link.send({"t": "start", "cfg": cfg})

    def host_event(self, kind, data=None):
        if self.link is not None:
            self.link.send({"t": "ev", "k": kind, "data": data or {}})

    def host_after_update(self, raid, dt):
        """每帧末:把战局状态发给客户端。"""
        if self.role != "host" or self.link is None or not self._client_ready:
            return
        now = time.time()
        try:
            if now - self._last_hot >= 1.0 / SNAP_HZ:
                self._last_hot = now
                patches = self._snapshot(raid, HOT_KEYS, "_old_hot")
                if patches:
                    self.link.send({"t": "p", "d": patches}, compress=True,
                                   droppable=True)
            if now - self._last_cold >= COLD_EVERY:
                self._last_cold = now
                patches = self._snapshot(raid, COLD_KEYS, "_old_cold")
                if patches:
                    self.link.send({"t": "p", "d": patches}, compress=True,
                                   droppable=True)
        except Exception as e:
            if DEBUG:
                print("[net] snapshot fail:", e)

    def _snapshot(self, raid, keys, cache_attr):
        """编码 + 和上一帧比,返回 (路径, 节点) 列表。

        顶层是"属性名 -> 节点"的普通字典,必须按属性名逐个 diff ——
        直接把它当节点 diff 会生成一条空路径的补丁,客户端只能丢掉。
        另外:补丁路径必须**真的能落到客户端对象图上**。列表长度对不上时
        (客户端那边还是空的/短的),叶子补丁会全部写不进去,画面就会卡在
        旧值上 —— 所以这里逐条校验,写不进去就整棵子树重发。
        """
        old = getattr(self, cache_attr)
        tree = encode_state(raid, keys)
        patches = []
        if old is None:
            patches = [([k], v) for k, v in tree.items()]
        else:
            for k, v in tree.items():
                if k not in old:
                    patches.append(([k], v))
                    continue
                old_k = _old_sub(old[k], v)
                sub = []
                if old_k is None:
                    sub = [([k], v)]
                else:
                    diff_tree(old_k, v, [k], sub)
                if sub and not all(_patch_writable(raid, lp, node)
                                   for lp, node in sub):
                    sub = [([k], v)]        # 形状对不上:整棵子树重发
                patches.extend(sub)
            if set(old) - set(tree):
                patches = [([k], v) for k, v in tree.items()]
        setattr(self, cache_attr, tree)
        return patches

    def take_input(self):
        """主机侧:取走客户端最新输入,返回 (输入字典, 动作列表)。"""
        with self._lock:
            inp = dict(self._input)
            acts = self._acts
            self._acts = []
        return inp, acts

    # ---------------- 客户端 ----------------
    def join(self, ip=None, port=None):
        if self.role == "host":
            return False
        if self.role == "client" and self.link is not None:
            return True
        port = int(port or TCP_PORT)
        if not ip:
            hosts = self.found_hosts()
            if not hosts:
                self.request_scan()
                time.sleep(0.7)
                hosts = self.found_hosts()
            if not hosts:
                self.error = "没找到房间"
                self.msg = self.error
                return False
            ip = hosts[0]["ip"]
        self.error = ""
        try:
            sock = socket.create_connection((ip, port), timeout=4.0)
        except Exception as e:
            self.error = "连不上 %s:%d (%s)" % (ip, port, e)
            self.msg = self.error
            return False
        self.port = port
        self._stop = False
        self.role = "client"
        self.msg = "已连接"
        self.link = _Link(sock, self._on_msg, self._on_link_down)
        name = ""
        try:
            name = getattr(self.game.save, "name", "") or ""
        except Exception:
            pass
        self.link.send({"t": "hello", "name": name or "玩家2", "ver": PROTO})
        return True

    def client_send_input(self, payload):
        if self.role == "client" and self.link is not None:
            self.link.send({"t": "in", "d": payload})

    # ---------------- 收包 ----------------
    def _on_msg(self, msg):
        with self._lock:
            self._inbox.append(msg)

    def _start_udp(self, respond=False):
        try:
            u = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            u.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            u.bind(("", UDP_PORT))
            u.settimeout(0.5)
        except Exception:
            return
        self._udp = u

        def loop():
            while not self._stop:
                try:
                    data, addr = u.recvfrom(1024)
                except socket.timeout:
                    continue
                except Exception:
                    return
                if not respond:
                    if data.startswith(b"T2D!"):
                        try:
                            parts = data[4:].decode("utf-8", "replace").split("|")
                            if len(parts) >= 2:
                                with self._lock:
                                    self._hosts[addr[0]] = dict(
                                        ip=addr[0], name=parts[0],
                                        port=int(parts[1]), ts=time.time())
                        except Exception:
                            pass
                    continue
                if data == b"T2D?" and self.role == "host":
                    info = "T2D!%s|%d|%s" % (self.room_name, TCP_PORT,
                                            "ingame" if self.link is not None else "open")
                    try:
                        u.sendto(info.encode("utf-8"), addr)
                    except Exception:
                        pass

        self._udp_t = threading.Thread(target=loop, daemon=True)
        self._udp_t.start()

    def tick(self, dt=0.0):
        """主线程每帧调用:处理收到的消息 + 客户端侧触发开局。"""
        if self._udp is None and self.role is None:
            return
        with self._lock:
            msgs, self._inbox = self._inbox, []
        for msg in msgs:
            try:
                self._handle(msg)
            except Exception as e:
                if DEBUG:
                    print("[net] handle fail:", msg.get("t"), e)
        if self._scan_until and time.time() > self._scan_until:
            self._scan_until = 0.0

    def _handle(self, msg):
        t = msg.get("t")
        if t == "hello" and self.role == "host":
            self.peer_name = str(msg.get("name") or "玩家2")[:16]
            self._client_ready = True
            if DEBUG:
                print("[net] 客户端握手:", self.peer_name, flush=True)
            self.link.send({"t": "welcome", "host": self.room_name, "ver": PROTO})
        elif t == "in" and self.role == "host":
            d = msg.get("d") or {}
            with self._lock:
                self._input = d
                for a in d.get("acts", ()):
                    self._acts.append(a)
        elif t == "welcome" and self.role == "client":
            self.peer_name = str(msg.get("host") or "房主")[:24]
            self.msg = "已连接"
        elif t == "start" and self.role == "client":
            if DEBUG:
                print("[net] 收到开局指令:", msg.get("cfg"), flush=True)
            self._client_start(msg.get("cfg") or {})
        elif t == "p" and self.role == "client":
            self._client_apply(msg.get("d") or [])
        elif t == "ev" and self.role == "client":
            self._client_event(msg.get("k"), msg.get("data") or {})
        elif t == "bye":
            self.close(notify=False)
            self.msg = "对方已断开"
        elif t == "_down":
            if self.role == "host":
                self.peer_name = ""
                self.msg = "对方已断开"
            else:
                self.role = None
                self.msg = "与主机断开"
                if self.game.phase == "raid":
                    self.game.lan_abort()

    # ---------------- 客户端:应用主机状态 ----------------
    def _patcher(self):
        if not hasattr(self, "_patch_obj"):
            self._patch_obj = Patcher(swap=True)
        return self._patch_obj

    def _client_apply(self, patches):
        raid = getattr(self.game, "raid", None)
        if raid is None:
            return
        try:
            self._patcher().apply(raid, patches)
        except Exception as e:
            if DEBUG:
                print("[net] apply fail:", e)

    def _client_start(self, cfg):
        try:
            self.game.lan_client_begin(cfg)
        except Exception as e:
            self.error = "开局失败:%s" % e
            if DEBUG:
                import traceback
                traceback.print_exc()

    def _client_event(self, kind, data):
        if kind == "extract":
            try:
                self.game.lan_client_extract(data)
            except Exception:
                if DEBUG:
                    import traceback
                    traceback.print_exc()
        elif kind == "over":
            try:
                self.game.lan_client_over(data)
            except Exception:
                if DEBUG:
                    import traceback
                    traceback.print_exc()
        elif kind == "msg":
            raid = getattr(self.game, "raid", None)
            if raid is not None and hasattr(raid, "add_toast"):
                raid.add_toast(str(data.get("text", "")), None, 3.0)

    # ---------------- 关闭 ----------------
    def close(self, notify=True):
        self._stop = True
        was_client = (self.role == "client")
        if notify and self.link is not None:
            try:
                self.link.send({"t": "bye"})
                time.sleep(0.05)
            except Exception:
                pass
        if self.link is not None:
            self.link.close()
            self.link = None
        if self._srv is not None:
            try:
                self._srv.close()
            except Exception:
                pass
            self._srv = None
        if self._udp is not None:
            try:
                self._udp.close()
            except Exception:
                pass
            self._udp = None
        self.role = None
        self.peer_name = ""
        self._client_ready = False
        self._old_hot = None
        self._old_cold = None
        self._stop = False
        self.msg = "未联机"
        # 联机中的客户端断了(主机关房 / 自己退出):别留在一个没人管的战局里
        if was_client and getattr(self.game, "phase", None) == "raid":
            try:
                self.game.lan_abort()
            except Exception:
                pass


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def _local_ip():
    """本机在局域网里的地址(拿不到就给回环)。"""
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def _bcast_addr():
    """按本机 IP 猜一个子网广播地址(255.255.255.255 有时被系统拦)。"""
    ip = _local_ip()
    if ip.count(".") == 3 and not ip.startswith("127."):
        return ip.rsplit(".", 1)[0] + ".255"
    return ""
