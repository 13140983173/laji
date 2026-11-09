#!/usr/bin/env python3
"""伙伴的手：把 cua-driver 收敛成 5 个语义工具的 stdio MCP server。

为什么要有这一层，而不是直接把 `cua-driver mcp` 挂进 Laji：

* 那套 MCP 有 60 多个工具（录制、光标主题、配置、跨平台拖拽…），schema 每轮都在
  system prompt 里；这里只留 5 个，几百 token。
* 它的工具名是 `get_window_state` / `element_token` 这类驱动器词汇，模型要现学；
  这里换成 `look` / `act`，它一看就知道该不该用。
* 它返回的截图是 base64 内联，动辄几万 token；这里一律落盘、只回路径。

底层一切仍走 `cua-driver call <tool> <json>`，与 MCP 入口是同一条代码路径
（官方 CLI 文档：invoke an MCP tool through the running daemon），所以 daemon
只有一份状态，宿主侧和模型侧看到的是同一个桌面。

协议：JSON-RPC 2.0，行分隔（与 `crates/laji-mcp` 的 LinesCodec 一致），
protocolVersion 回 2025-03-26。自守约束：
* stdin EOF 即退出（daemon 的 kill_on_drop 会关掉管道）；
* 只认 tools/list / tools/call / initialize / ping，其余回 -32601；
* 绝不向 stderr 打噪音——Laji 会把 stderr 拼进模型看到的内容里。
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "pet-hands"
SERVER_VERSION = "0.1.0"

# 单条工具返回给模型的字符上限。超过就截断并告诉模型怎么拿全量——这比让它一次
# 吃下整棵 UIA 树便宜得多（1440x900 的一张全屏截图在 Laji 的估算里是 1728 token，
# 而一棵没裁剪的窗口树可以到上万）。
MAX_RESULT_CHARS = 12_000
# 超过这个长度的字符串按 base64 处理：一律落盘，绝不内联进上下文。
BASE64_HINT_CHARS = 8_192
CALL_TIMEOUT_SECONDS = 60
LONG_CALL_TIMEOUT_SECONDS = 180

# 每次 `cua-driver call` 不指定 session 就是一次性 session，**返回时快照连同
# element_token 一起作废**。而本插件的核心流程就是 look 拿 token → act 用 token，
# 两条命令两次 call，不固定 label 就必然 stale_element_token。
SESSION_LABEL = "laji-pet-hands"


# ---------------------------------------------------------------------------
# cua-driver 定位与调用
# ---------------------------------------------------------------------------


def driver_bin() -> str:
    """按 PET_HANDS_CUA_BIN → PATH → 常见安装位置找可执行文件。"""
    override = os.environ.get("PET_HANDS_CUA_BIN", "").strip()
    if override:
        return override
    found = shutil.which("cua-driver")
    if found:
        return found
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA", str(home)))
    candidates = [
        home / ".local" / "bin" / "cua-driver",
        home / ".local" / "bin" / "cua-driver.exe",
        local / "Programs" / "cua-driver" / "cua-driver.exe",
        local / "Programs" / "Cua" / "cua-driver" / "cua-driver.exe",
        local / "Programs" / "Cua" / "cua-driver" / "bin" / "cua-driver.exe",
        local / "cua-driver" / "cua-driver.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    # 官方安装器把 exe 放在 ``<品牌>/cua-driver/bin/`` 这种多一层的目录里，品牌名与版本
    # 都会变；写死的候选没命中时扫一层 `Programs/*`，比再加一条写死路径更耐改。
    for pattern in ("*/cua-driver/cua-driver.exe", "*/cua-driver/bin/cua-driver.exe"):
        hits = sorted((local / "Programs").glob(pattern))
        if hits:
            return str(hits[0])
    return "cua-driver"


class DriverError(RuntimeError):
    """给模型看的失败原因，不是给日志看的。"""


# daemon 重启、空闲回收、或上次进程被强杀之后，固定 label 会变成「已结束」。
# 这时每条 call 都返回 exit 1，而官方的 exit 1 同时也是「daemon 没在跑」，
# 直接按后者报错会让模型以为自己没有手（她就会说「家伙什没装好」）。
_SESSION_ENDED_HINTS = (
    "session has ended",
    "unknown session",
    "no such session",
    "session expired",
    "session not found",
)


def _invoke(tool: str, payload: dict[str, Any], timeout: float) -> subprocess.CompletedProcess:
    argv = [driver_bin(), "call", tool, json.dumps(payload, ensure_ascii=False)]
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # 抛出前先给出人能照做的下一步
        raise DriverError(
            f"找不到 cua-driver（{driver_bin()}）。先安装 Cua Driver，用 "
            "`cua-driver doctor` 确认；或用环境变量 PET_HANDS_CUA_BIN 指向它。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DriverError(f"{tool} 超过 {timeout:.0f}s 未返回，已放弃。") from exc


def _session_ended(proc: subprocess.CompletedProcess) -> bool:
    text = f"{proc.stderr or ''}\n{proc.stdout or ''}".lower()
    return any(hint in text for hint in _SESSION_ENDED_HINTS)


def start_session() -> None:
    """重开固定 label 的会话；失败也不抛——让跟下来的那次真调用去报错。"""
    _invoke("start_session", {"session": SESSION_LABEL}, CALL_TIMEOUT_SECONDS)


def _driver_error_text(proc: subprocess.CompletedProcess) -> str:
    """从驱动的双重输出里挤出真正的错因。

    驱动拒绝时把 JSON 写到 stdout（`{"refusal": {"message": ...}}`，或干脆只有
    `{"code": "screenshot_context_missing", "reason": "window_never_read"}`），stderr 只剩
    花括号，取“最后一行”只会拿到一个 `}`，模型看到的就是无从下手的空错误。
    """
    for chunk in (proc.stdout, proc.stderr):
        text = (chunk or "").strip()
        if not text.startswith("{"):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        parts: list[str] = []
        refusal = data.get("refusal")
        if isinstance(refusal, dict):
            parts.append(str(refusal.get("message") or refusal.get("code") or ""))
        for key in ("code", "reason", "message", "hint"):
            value = data.get(key)
            if value and str(value) not in parts:
                parts.append(str(value))
        joined = "；".join(p for p in parts if p)
        if joined:
            return joined
    blob = f"{proc.stderr or ''}\n{proc.stdout or ''}".strip()
    for pattern in (r'"message"\s*:\s*"([^"]+)"', r"Missing required [^\"\n]+"):
        match = re.search(pattern, blob)
        if match:
            return (match.group(1) if match.groups() else match.group(0)).strip()
    lines = [line.strip() for line in blob.splitlines() if line.strip()]
    return lines[-1] if lines else "无输出"


def call_driver(tool: str, arguments: dict[str, Any] | None = None,
                timeout: float = CALL_TIMEOUT_SECONDS) -> Any:
    payload = dict(arguments or {})
    # 统一会话：读到的 token / 坐标上下文在后续 act 里仍然有效。
    payload.setdefault("session", SESSION_LABEL)
    proc = _invoke(tool, payload, timeout)
    if proc.returncode == 1 and _session_ended(proc):
        # 旧 label 作废：重开一次再重试。被拒的调用没有副作用，重试是安全的。
        start_session()
        proc = _invoke(tool, payload, timeout)
    if proc.returncode == 1:
        tail = _driver_error_text(proc)
        low = tail.lower()
        if any(hint in low for hint in ("daemon", "not running", "connect", "socket", "session")):
            raise DriverError(
                "cua-driver daemon 没在运行，或拒绝了这次调用。执行 "
                "`cua-driver autostart enable`，再用 `cua-driver status` 确认是 running。"
                f"（{tail}）"
            )
        # 参数猜错时把驱动原话直接给模型：以前一律说「daemon 没在运行」，
        # 她照这句就答「我连不上」，明明只是少了一个字段。
        raise DriverError(f"{tool} 被驱动拒绝：{tail}")
    if proc.returncode != 0:
        raise DriverError(
            f"{tool} 失败（exit {proc.returncode}）：{_driver_error_text(proc)}"
        )

    text = (proc.stdout or "").strip()
    if not text:
        return {"ok": True}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


# ---------------------------------------------------------------------------
# 落盘与压缩
# ---------------------------------------------------------------------------


def shots_dir() -> Path:
    root = os.environ.get("PET_HANDS_SHOT_DIR", "").strip()
    if root:
        path = Path(root)
    else:
        base = (
            os.environ.get("LOCALAPPDATA")
            or os.environ.get("XDG_CACHE_HOME")
            or str(Path.home())
        )
        path = Path(base) / "laji" / "pet-hands" / "shots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _looks_like_base64(value: str) -> bool:
    if len(value) < BASE64_HINT_CHARS:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
    return all(ch in allowed for ch in value[:64])


def park_blobs(value: Any, _depth: int = 0) -> Any:
    """把长 base64 落盘并换成路径。截图绝不能内联进模型的上下文。"""
    if _depth > 8:
        return value
    if isinstance(value, dict):
        return {k: park_blobs(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [park_blobs(v, _depth + 1) for v in value]
    if isinstance(value, str) and _looks_like_base64(value):
        try:
            raw = base64.b64decode(value, validate=False)
        except Exception:
            return value
        if raw[:8] == b"\x89PNG\r\n\x1a\n":
            suffix = ".png"
        elif raw[:2] == b"\xff\xd8":
            suffix = ".jpg"
        else:
            return f"<{len(value)} chars of base64 omitted>"
        path = shots_dir() / f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}{suffix}"
        path.write_bytes(raw)
        return {"saved_to": str(path), "bytes": len(raw)}
    return value


def _clip_strings(value: Any, limit: int) -> Any:
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"…（共 {len(value)} 字符）"
    if isinstance(value, dict):
        return {k: _clip_strings(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_clip_strings(v, limit) for v in value]
    return value


def render(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(text) <= MAX_RESULT_CHARS:
        return text
    # 硬切会在 JSON 中间断开，模型拿到的是半截对象。按字段长度逐级收窄，
    # 结构始终完整，最后才兑底硬切。
    for limit in (4000, 1200, 400, 120, 40):
        text = json.dumps(_clip_strings(payload, limit), ensure_ascii=False, separators=(",", ":"))
        if len(text) <= MAX_RESULT_CHARS:
            return text
    return (
        text[:MAX_RESULT_CHARS]
        + f"\n…（结果 {len(text)} 字符，已截断到 {MAX_RESULT_CHARS}。"
        "要更小的范围：look 先用 scope=windows 定位窗口，或 raw 精确取单个字段。）"
    )


# ---------------------------------------------------------------------------
# 工具实现
# ---------------------------------------------------------------------------


def _process_name(pid: int) -> str | None:
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            size = wintypes.DWORD(1024)
            buf = ctypes.create_unicode_buffer(1024)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return None
    return None


def _win32_foreground() -> dict[str, Any] | None:
    """前台窗口直接问 Win32（微秒级）。

    `list_windows` 实测 3.0–3.8s，而「谁在前台」每轮都要问一次——look 和 act
    各一次，光找窗口就 6-7s。Win32 拿 hwnd/pid/标题是系统调用，不走向查。
    """
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return {
            "window_id": int(hwnd),
            "pid": int(pid.value),
            "title": buf.value,
            "app_name": _process_name(int(pid.value)),
        }
    except Exception:
        return None


_WINDOWS_CACHE: dict[str, Any] = {"ts": 0.0, "data": None}
WINDOWS_TTL = 8.0


def _fast_windows() -> list[dict[str, Any]]:
    """顶层可见窗口的轻量枚举，用于 app 匹配。

    驱动的 list_windows 要 3.0–3.8s，而按 app 找窗口是每轮 act 都要做的事。
    EnumWindows + GetWindowText 是本地系统调用，实测量级差千倍。
    """
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return []

    user32 = ctypes.windll.user32
    out: list[dict[str, Any]] = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        out.append(
            {
                "window_id": int(hwnd),
                "pid": int(pid.value),
                "title": buf.value,
                "app_name": _process_name(int(pid.value)),
            }
        )
        return True

    try:
        user32.EnumWindows(proc(_cb), 0)
    except Exception:
        return []
    return out


def _visible_windows(extra: dict[str, Any]) -> list[dict[str, Any]]:
    # list_windows 实测 3.4s，而一次 look → act 要解析两次目标；不缓存的话
    # 光“找窗口”就吃掉 7s。TTL 短到用户切窗口不至于指错，1.5s 够一轮往返用。
    now = time.monotonic()
    if not extra and _WINDOWS_CACHE["data"] is not None:
        if now - _WINDOWS_CACHE["ts"] < WINDOWS_TTL:
            return _WINDOWS_CACHE["data"]
    data = call_driver("list_windows", extra)
    wins = [w for w in (data.get("windows") or data.get("_legacy_windows") or []) if w.get("is_on_screen") and not w.get("minimized")]
    if not extra:
        _WINDOWS_CACHE["ts"] = now
        _WINDOWS_CACHE["data"] = wins
    return wins


# 桌面壳层不是「他在用的窗口」：z 顺序最靠前，但没有可操作内容。
_SHELL_TITLES = {"Program Manager", "Windows 输入体验", "Default IME"}


def _front_window(wins: list[dict[str, Any]]) -> dict[str, Any] | None:
    def z(w: dict[str, Any]) -> int:
        v = w.get("z_index")
        return 999 if v is None else int(v)

    for w in sorted(wins, key=z):
        title = str(w.get("title") or "").strip()
        if not title or title in _SHELL_TITLES or "AgentCursorOverlay" in title:
            continue
        return w
    return None


def _resolve_target(extra: dict[str, Any]) -> dict[str, Any]:
    """`get_window_state` 要 `pid` + `window_id` 两个整数，缺一个就报

    「Missing required integer field pid」——而这句话被上层当成「daemon 没在跑」，
    于是她会答「我连不上」。这里补齐：给了 pid 就找它的窗口，给了 window_id
    就找它的进程，两个都没给就用前台窗口（跳过桌面壳层）。
    """
    payload = dict(extra)
    # 驱动只认 pid / window_id：把 app 原样下发会被整批拒掉
    # （"click: unknown argument app"）。在这里解析掉，永远不往下传。
    app = payload.pop("app", None)
    pid = payload.get("pid")
    wid = payload.get("window_id")
    if pid is not None and wid is not None:
        return payload

    if app not in (None, ""):
        wins = _fast_windows() or _visible_windows({})
        needle = str(app).lower()
        hits = [
            w
            for w in wins
            if needle in str(w.get("app_name") or "").lower()
            or needle in str(w.get("title") or "").lower()
        ]
        if hits:
            payload["pid"] = int(hits[0]["pid"])
            payload["window_id"] = int(hits[0]["window_id"])
            payload["app_name"] = hits[0].get("app_name")
            payload["title"] = hits[0].get("title")
            return payload
        raise DriverError(
            f"没有匹配 app={app} 的窗口：先 look(scope=windows) 看现在开着哪些窗口。"
        )

    fg = _win32_foreground()
    if fg:
        payload.update(fg)
        return payload
    if wid is not None:
        for w in wins:
            if w.get("window_id") == wid:
                payload["pid"] = int(w["pid"])
                return payload
        # 指定了窗口却找不到：**绝不能**静默换成前台窗口，那是点到别人头上。
        raise DriverError(
            f"window_id={wid} 现在没有可见窗口：先 look(scope=windows) 看一眼再点。"
        )
    if pid is not None:
        own = [w for w in wins if w.get("pid") == pid]
        if own:
            payload["window_id"] = int(own[0]["window_id"])
            return payload
        raise DriverError(
            f"pid={pid} 现在没有可见窗口（可能已关、最小化或在后台）：先 look(scope=windows)。"
        )

    front = _front_window(wins)
    if front is None:
        raise DriverError(
            "找不到可操作的前台窗口：先用 look(scope=windows) 看现在有哪些窗口。"
        )
    payload["pid"] = int(front["pid"])
    payload["window_id"] = int(front["window_id"])
    payload["app_name"] = front.get("app_name")
    payload["title"] = front.get("title")
    return payload


def _target_missing(extra: dict[str, Any]) -> dict[str, int]:
    """只补 `extra` 里缺的 `pid` / `window_id`：`type_text`、`press_key`、`run_steps`

    都要求这两个字段，缺一个驱动就整批拒掉。
    """
    target = _resolve_target(extra)
    ids = {"pid": int(target["pid"]), "window_id": int(target["window_id"])}
    return {k: v for k, v in ids.items() if k not in extra}


def _split_chord(chord: str) -> tuple[str, list[str]]:
    """`ctrl+shift+s` → (`s`, [`ctrl`, `shift`])：驱动要 `key` + `modifiers`，不收 `keys`。"""
    parts = [p.strip().lower() for p in chord.replace("+", " ").split() if p.strip()]
    if not parts:
        raise DriverError("keys 需要组合键，例如 ctrl+s、alt+f4、enter。")
    return parts[-1], parts[:-1]


def tool_look(args: dict[str, Any]) -> Any:
    scope = str(args.get("scope") or "front").lower()
    extra = dict(args.get("extra") or {})
    if scope in ("front", "tree") and args.get("app") and "app" not in extra:
        extra["app"] = args["app"]
    if scope == "windows":
        result = call_driver("list_windows", extra)
    elif scope == "apps":
        result = call_driver("list_apps", extra)
    elif scope == "tree":
        # 0.35 起 get_window_state 默认只回 tree_markdown（最多 250 节点），
        # 拿不到 element_token；要点击必须显式要 elements。
        target = _resolve_target(extra)
        payload = {"tree_format": "elements"}
        payload.update(extra)
        payload["pid"] = target["pid"]
        payload["window_id"] = target["window_id"]
        result = call_driver("get_window_state", payload)
        # 这个分支是退路（正常路径用 element_index），但 elements 单窗口实测能到
        # 78062 字符，不封顶一样会把回包撑爆。
        if isinstance(result, dict) and isinstance(result.get("elements"), list):
            total_elements = len(result["elements"])
            if total_elements > MAX_TREE_ELEMENTS:
                result["elements"] = result["elements"][:MAX_TREE_ELEMENTS]
                result["elements_truncated"] = (
                    f"只列了前 {MAX_TREE_ELEMENTS}/{total_elements} 个元素："
                    '用 extra={"query":"<名字片段>"} 收窄。'
                )
        if isinstance(result, dict) and not result.get("element_count"):
            # 微信 / 企业微信 / 雀嫆 这类 Chromium 自绘界面 UIA 树是空的：
            # 不告诉她改走像素，她会一直重试 look 然后说“看不到”。
            bounds = result.get("window_bounds") or {}
            result["px_fallback"] = {
                "why": result.get("degraded_reason")
                or "这个窗口没有可读控件（自绘界面）",
                "how": "改用 screen 截图看画面，再 act click(x, y) 点坐标；坐标 = 窗口原点 + 截图内坐标。",
                "window_origin": {"x": bounds.get("x"), "y": bounds.get("y")},
                "window_size": {"w": bounds.get("width"), "h": bounds.get("height")},
            }
    else:  # front：**前台那一个窗口**的轻量树
        # 不能再用 get_accessibility_tree：它给的是整桌面，12000 字符预算在
        # 「进程列表 + 窗口列表」就用光了，控件一个都轮不到——她只能看见窗口标题，
        # 自然说不出「这个按钮在哪」。
        target = _resolve_target(extra)
        payload = {
            "pid": target["pid"],
            "window_id": target["window_id"],
        }
        # 默认抓图要多花 ~0.6s 并把 base64 写盘；模型的日常动作是靠编号点，
        # 不是看图。要图就用 screen（它才真落盘并返回路径）。
        if "include_screenshot" not in extra:
            payload["include_screenshot"] = False
        tree = call_driver("get_window_state", payload)
        if isinstance(tree, dict) and isinstance(tree.get("tree_markdown"), str):
            tree["tree_markdown"] = _shrink_markdown(tree["tree_markdown"])
        if isinstance(tree, dict) and tree.get("truncated"):
            # 默认 250 节点的预算在大窗口（Electron / WebView）上会把树切断：
            # 实测 Laji 窗口只读到 173/500 个元素。模型看不见就以为没这个按钮，
            # 所以必须把“你看到的不是全部”写在回包里。
            # 驱动自带一个英文 truncation_hint，保留中文这份（含具体退路），别两份都发。
            tree.pop("truncation_hint", None)
            tree["incomplete"] = (
                f"控件树被截断（{tree.get('truncation_reason')}）：还有节点没走完，"
                "你没看到的按钮不代表不存在。要看更多：look 带 "
                'extra={"max_elements":800,"timeout_ms":3000}，或用 '
                'extra={"query":"<按钮名>"} 直接找那一个。'
            )
        result = {
            "window": {
                "app_name": target.get("app_name"),
                "title": target.get("title"),
                "pid": target["pid"],
                "window_id": target["window_id"],
            },
            "tree": tree,
        }
    _remember_snapshot(result)
    return park_blobs(result)


# 每个窗口最近一次的 snapshot_id。`[3]` 只是 markdown 的行号，驱动要的是
# `<snapshot_id>:3`；不记下来，模型就只能改要 elements（同一个窗口 78062 字符）
# 才能拿到 token。“看一眼再点”变成两次往返，这就是“不流畅”的来源。
_LAST_SNAPSHOT: dict[tuple[int, int], str] = {}


MAX_MD_CONT_LINES = 60
MAX_MD_LINE_CHARS = 200
MD_BUDGET_CHARS = 9000
MAX_TREE_ELEMENTS = 200
ROW_RE = re.compile(r"^\s*-?\s*\[\d+\]")


def _shrink_markdown(text: str, budget: int = MD_BUDGET_CHARS) -> str:
    """按字符预算收尾：编号行优先，续行与超长行让位。

    预算必须在这里管：交给 render() 的字符串裁剪去削，会把 markdown 从中间切断，
    后面的 `[N]` 全丢，编号直接定位不到。

    * 记事本 / 编辑器 / 日志窗口会把整篇文档当成一个 Document 节点的 value 内联：
      实测 1278 行 → 75860 字符，而真正可点的只有 74 个元素。按行数从头截断会把
      [71]/[72]/[73] 这些标题栏按钮切掉，所以核心是“编号行一个不少，续行限流”。
    * 单个节点也能很长：Laji 窗口的 `[37] Button "admin@… % nc -vz …"` 一条就是
      2KB 终端回显。行内必须先截，并且**保住 `[N]` 行首**，否则编号定位就废了。
    """
    if not text:
        return text
    kept: list[str] = []
    used = 0
    cont = 0
    dropped_cont = 0
    dropped_rows = 0
    for raw in text.splitlines():
        is_row = bool(ROW_RE.match(raw))
        line = raw
        if len(line) > MAX_MD_LINE_CHARS:
            line = f"{line[:MAX_MD_LINE_CHARS]}…（本行共 {len(raw)} 字符）"
        if is_row:
            if used + len(line) > budget:
                dropped_rows += 1
                continue
            kept.append(line)
            used += len(line)
            continue
        if cont < MAX_MD_CONT_LINES and used + len(line) <= budget:
            cont += 1
            kept.append(line)
            used += len(line)
        else:
            dropped_cont += 1
    if dropped_rows:
        kept.append(
            f"…（还有 {dropped_rows} 个可点元素超出本次预算没列出，**不代表不存在**。"
            '用 look extra={"query":"<名字片段>"} 或 extra={"max_elements":1000} 继续看。）'
        )
    elif dropped_cont:
        kept.append(
            f"…（已省降 {dropped_cont} 行正文，可点元素一个没少。要看全文用 read_file / screen，"
            "或 raw get_window_state(query=…)。）"
        )
    return "\n".join(kept)


def _remember_snapshot(result: Any) -> None:
    if not isinstance(result, dict):
        return
    sid = result.get("snapshot_id")
    pid = result.get("pid")
    window_id = result.get("window_id")
    if isinstance(sid, str) and isinstance(pid, int) and isinstance(window_id, int):
        _LAST_SNAPSHOT[(pid, window_id)] = sid
    for key in ("tree", "structuredContent"):
        _remember_snapshot(result.get(key))


def _target_key(extra: dict[str, Any]) -> tuple[int, int]:
    target = _resolve_target(extra)
    return target["pid"], target["window_id"]


def _read_window_tree(extra: dict[str, Any]) -> None:
    """补一次轻量读取（markdown，1.3KB），拿最新 snapshot_id 与行号。"""
    pid, window_id = _target_key(extra)
    _remember_snapshot(
        call_driver(
            "get_window_state",
            {"pid": pid, "window_id": window_id, "include_screenshot": False},
        )
    )


def _token_for_index(extra: dict[str, Any], index: Any) -> str:
    """把 markdown 里的 `[n]` 变成驱动认识的 `element_token`。"""
    try:
        row = int(index)
    except (TypeError, ValueError):
        raise DriverError("element_index 要是 markdown 里 [n] 的那个整数。") from None
    key = _target_key(extra)
    if key not in _LAST_SNAPSHOT:
        _read_window_tree(extra)
    snapshot = _LAST_SNAPSHOT.get(key)
    if not snapshot:
        raise DriverError(
            "这个窗口还没有可用的读取结果。先 look 一次，再用它里面的 [n]。"
        )
    return f"{snapshot}:{row}"


def _read_window_once(extra: dict[str, Any]) -> None:
    """驱动要求「先看过这个窗口」才允许按坐标点，否则回 screenshot_context_missing。

    这条前置她看不出来：报错只有一个 code，所以在她注意不到的地方补一次。
    """
    pid, window_id = _target_key(extra)
    _remember_snapshot(
        call_driver(
            "get_window_state",
            {"pid": pid, "window_id": window_id, "include_screenshot": True},
        )
    )


def tool_act(args: dict[str, Any]) -> Any:
    action = str(args.get("action") or "").lower()
    extra = dict(args.get("extra") or {})
    if args.get("app") and "app" not in extra:
        extra["app"] = args["app"]
    if args.get("delivery_mode"):
        # background 在 WinUI3 / XAML 标题栏上会被静默吞掉（effect=unverifiable，
        # 不报 background_unavailable），所以得让这事能被显式升级成 foreground。
        extra["delivery_mode"] = str(args["delivery_mode"]).lower()
    if "app" in extra:
        # 只把解析出的 pid / window_id 补上，app_name / title 这些是给 look 看的；
        # 其余透传字段（delivery_mode 等）必须留着，否则会被默默换成默认值。
        resolved = _resolve_target(extra)
        extra = {k: v for k, v in extra.items() if k != "app"}
        extra["pid"] = int(resolved["pid"])
        extra["window_id"] = int(resolved["window_id"])
    token = args.get("element_token")
    role = args.get("role")
    name = args.get("name")

    if (role or name) and args.get("element_index") is None and token in (None, "") and args.get("x") is None:
        # 按 role/name 定位：驱动自己读窗口、等元素出现、点完再报结果，不用先 look。
        # `run_steps` 支持这种 step（官方描述里叫 TARGET BY NAME），所以「点保存」
        # 这种已知动作从 look + act 两次往返压成一次。
        step_args: dict[str, Any] = {}
        if role:
            step_args["role"] = str(role).lower()
        if name:
            step_args["name"] = str(name)
        if args.get("nth") is not None:
            step_args["nth"] = int(args["nth"])
        if extra.get("delivery_mode"):
            step_args["delivery_mode"] = extra["delivery_mode"]

        if action in ("click", "double_click", "right_click"):
            step_tool = action
        elif action == "type":
            if args.get("text") in (None, ""):
                raise DriverError("type 需要 text；只按键用 action=key。")
            step_tool = "type_text"
            step_args["text"] = args["text"]
        else:
            raise DriverError(
                f"action={action} 不支持按名字定位；能用 name/role 的是 "
                "click / double_click / right_click / type。"
            )
        ids = _resolve_target(extra)
        pid_value = int(ids["pid"])
        wid_value = int(ids["window_id"])
        if extra.get("delivery_mode") == "foreground":
            # run_steps 的前台投递要求目标已经是前台，否则直接回
            # foreground_unavailable；而直接 click 会自己切，两者不一致。
            call_driver("bring_to_front", {"pid": pid_value, "window_id": wid_value})
        payload = {
            "steps": [{step_tool: step_args}],
            "pid": pid_value,
            "window_id": wid_value,
            # Electron / LibreOffice 这类工具包会明确拒后台输入，靠这个自动升级一次；
            # 后台能成功时它不触发，所以当默认值无害。
            "foreground_fallback": True,
        }
        return park_blobs(call_driver("run_steps", payload))

    if action in ("click", "double_click", "right_click"):
        payload = dict(extra)
        if token in (None, "") and args.get("element_index") is not None:
            # markdown 里的 `[3]` 就是行号；不用再要一遍 elements。
            token = _token_for_index(extra, args["element_index"])
        if token not in (None, ""):
            payload["element_token"] = token
            # 驱动文档：给了 element_token 就别再给 window_id（token 自己带着）。
            # 两个一起下发会被当成坐标点击走 synthetic_events，WinUI3 上实测就是
            # 点了没反应；只给 pid + token 时才是 global_input 的真点击。
            payload.pop("window_id", None)
        for axis in ("x", "y"):
            if args.get(axis) is not None:
                payload[axis] = args[axis]
        if str(args.get("space") or "").lower() == "screen":
            # 驱动的 x/y 本来就是窗口内截图坐标（scope 默认 window）；
            # 只有明确要屏幕绝对坐标时才切到 desktop。
            payload = {
                "scope": "desktop",
                "target": {"kind": "desktop", "display_id": "primary"},
                "x": args.get("x"),
                "y": args.get("y"),
            }
        tool = "click"
        if action == "double_click":
            payload["count"] = 2
        elif action == "right_click":
            payload["button"] = "right"
    elif action == "scroll":
        tool = "scroll"
        payload = {"direction": str(args.get("direction") or "down").lower()}
        if args.get("amount") is not None:
            payload["amount"] = args["amount"]
        if args.get("element_index") is not None:
            payload["element_token"] = _token_for_index(extra, args["element_index"])
        payload.update(_target_missing(extra))
        payload.update(extra)
        if payload.get("element_token"):
            payload.pop("window_id", None)
    elif action == "drag":
        tool = "drag"
        payload = {
            "from_x": args.get("from_x"),
            "from_y": args.get("from_y"),
            "to_x": args.get("to_x"),
            "to_y": args.get("to_y"),
        }
        missing = [name for name, value in payload.items() if value is None]
        if missing:
            raise DriverError(
                f"drag 需要 from_x / from_y / to_x / to_y（窗口内截图坐标），缺 {', '.join(missing)}。"
            )
        payload.update(_target_missing(extra))
        payload.update(extra)
    elif action == "type":
        tool = "type_text"
        text = args.get("text")
        if text in (None, ""):
            raise DriverError("type 需要 text；只按键用 action=key。")
        payload = {"text": text}
        # 驱动要求 pid：以前只传 text，一律被拒（“Missing required integer field: pid”），
        # 于是她“打了字但什么都没发生”。
        payload.update(_target_missing(extra))
        payload.update(extra)
    elif action == "key":
        key, modifiers = _split_chord(str(args.get("keys") or args.get("key") or ""))
        if modifiers:
            # 组合键走 hotkey：它按目标分流（XAML 走 UIA accelerator，Win32 走
            # SendInput，且只做一次短暂的前台交换、随后把前台还给用户）。
            # 以前用 press_key + delivery_mode=foreground 硬顶：PostMessage 不更新
            # 修饰键状态，`ctrl+a` 只会打出字符 `a`，而代价是整轮永久抢走焦点。
            tool = "hotkey"
            payload = {"keys": [*modifiers, key]}
        else:
            tool, payload = "press_key", {"key": key}
        payload.update(_target_missing(extra))
        payload.update(extra)
    else:
        raise DriverError(
            "action 只能是 click / double_click / right_click / scroll / drag / type / key。"
            "多步操作用 run_steps。"
        )
    try:
        result = park_blobs(call_driver(tool, payload))
    except DriverError as exc:
        if "stale" in str(exc) and args.get("element_index") is not None:
            # 行号来自上一次读取，界面换过一轮就作废：补读一次，重新拼 token。
            _read_window_tree(extra)
            payload["element_token"] = _token_for_index(extra, args["element_index"])
            return park_blobs(call_driver(tool, payload))
        if tool == "click" and "screenshot_context_missing" in str(exc):
            # “先读过窗口才能按坐标点”这条前置不必让她知道：自动补一次再重点。
            _read_window_once(extra)
            return park_blobs(call_driver(tool, payload))
        if tool == "hotkey" and "background_unavailable" in str(exc):
            # 驱动的规矩：background 必须先试，被拒才升级；只升一次。
            payload["delivery_mode"] = "foreground"
            return park_blobs(call_driver(tool, payload))
        raise

    if tool == "click" and isinstance(result, dict):
        if result.get("effect") == "unverifiable" and payload.get("delivery_mode") != "foreground":
            # 驱动不会把这个当错误：WinUI3 / XAML 自定义标题栏上后台 Invoke 是
            # 静默 no-op。实测记事本「最大化」→ 后台点击边界不动、
            # foreground 同 token 单击就变 1920x1010。所以把逃生出口写进回包。
            result["next"] = (
                "effect=unverifiable：驱动没能确认这次点击生效（WinUI3 / XAML 标题栏常见）。"
                "先 look 一眼；界面没变就重发同一次 act，加 delivery_mode=foreground。"
            )
    return result


STEP_TOOLS = {
    "click",
    "double_click",
    "right_click",
    "set_value",
    "type_text",
    "press_key",
    "hotkey",
    "scroll",
    "drag",
    "move_cursor",
}

_STEP_ALIASES = {
    "click": "click",
    "double_click": "double_click",
    "right_click": "right_click",
    "set_value": "set_value",
    "type_text": "type_text",
    "text": "type_text",
    "type": "type_text",
    "press_key": "press_key",
    "key": "press_key",
    "keys": "press_key",
    "hotkey": "hotkey",
    "scroll": "scroll",
    "drag": "drag",
    "move_cursor": "move_cursor",
}


def _normalize_steps(steps: list[Any]) -> list[dict[str, Any]]:
    """把随手写的步骤拉回驱动要求的 `{tool, args}`。

    驱动对 `steps` 做整批校验：一步写错，整批一个都不执行。而“自然”的写法
    （`{"type":"key","key":"end"}`）恰好是错的，报错又只有一个 `}`。
    与其让模型背格式，不如在这里翻译。
    """
    out: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise DriverError(f"第 {index} 步不是对象。")
        if "tool" in step:
            tool = str(step["tool"]).strip().lower()
            args = {k: v for k, v in step.items() if k not in ("tool", "args")}
            args.update(step.get("args") or {})
        elif set(step) & STEP_TOOLS:
            tool = next(iter(set(step) & STEP_TOOLS))
            args = step.get(tool) or {}
            if not isinstance(args, dict):
                raise DriverError(f"第 {index} 步的 {tool} 不是对象。")
        else:
            alias = step.get("action") or step.get("type") or step.get("tool_name")
            if not alias:
                raise DriverError(
                    f"第 {index} 步看不出是什么动作。写成 {{\"tool\":\"press_key\",\"args\":{{\"key\":\"end\"}}}}，"
                    '或 {"click": {"role": "button", "name": "OK"}}。'
                )
            tool = _STEP_ALIASES.get(str(alias).strip().lower()) or ""
            if not tool:
                raise DriverError(
                    f"第 {index} 步的动作 {alias!r} 不认识。可用：{', '.join(sorted(STEP_TOOLS))}。"
                )
            args = {k: v for k, v in step.items() if k not in ("type", "action", "tool_name")}
        tool, args = _promote_hotkey(tool, args)
        out.append({"tool": tool, "args": args})
    return out


def _promote_hotkey(tool: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """`key="ctrl+a"` 升级成 hotkey。

    press_key 走 PostMessage，不更新修饰键状态（实测只打出一个 `a`）；hotkey 才按
    目标分流。以前靠 `delivery_mode: foreground` 硬顶，代价是整步抢用户焦点。
    """
    if tool != "press_key":
        return tool, args
    chord = args.pop("keys", None) or args.get("key") or ""
    key, modifiers = _split_chord(str(chord))
    mods = [str(m).strip().lower() for m in (args.get("modifiers") or [])]
    for modifier in modifiers:
        if modifier not in mods:
            mods.append(modifier)
    args.pop("modifiers", None)
    if not mods:
        args["key"] = key
        return tool, args
    promoted = {k: v for k, v in args.items() if k != "key"}
    promoted["keys"] = [*mods, key]
    return "hotkey", promoted


def tool_run_steps(args: dict[str, Any]) -> Any:
    steps = args.get("steps")
    if not isinstance(steps, list) or not steps:
        raise DriverError(
            "steps 必须是非空数组，每步写 {tool, args}，例如 "
            '{"tool":"press_key","args":{"key":"ctrl+s"}}。'
        )
    extra = dict(args.get("extra") or {})
    payload: dict[str, Any] = {"steps": _normalize_steps(steps)}
    if "pid" not in extra or "window_id" not in extra:
        # 每步都不带 pid 时驱动整批拒掉；这里统一补在顶层。
        payload.update(_target_missing(extra))
    payload.update(extra)
    return park_blobs(
        call_driver("run_steps", payload, timeout=LONG_CALL_TIMEOUT_SECONDS)
    )


def find_saved_path(value: Any) -> str | None:
    if isinstance(value, dict):
        saved = value.get("saved_to")
        if isinstance(saved, str):
            return saved
        for inner in value.values():
            found = find_saved_path(inner)
            if found:
                return found
    elif isinstance(value, list):
        for inner in value:
            found = find_saved_path(inner)
            if found:
                return found
    return None


def tool_screen(args: dict[str, Any]) -> Any:
    extra = dict(args.get("extra") or {})
    for key in ("pid", "window_id", "app", "title"):
        if args.get(key) not in (None, ""):
            extra.setdefault(key, args[key])
    # 以前这里只塞 window_id / app，`pid` 永远缺一个 → get_window_state 被拒，
    # “看看屏幕”实际上一直是废的。
    target = _resolve_target(extra)
    payload: dict[str, Any] = {
        "include_screenshot": True,
        "pid": target["pid"],
        "window_id": target["window_id"],
    }
    result = park_blobs(call_driver("get_window_state", payload))
    if isinstance(result, dict):
        bounds = result.get("window_bounds") or {}
        if bounds:
            # 截图是窗口内坐标，click(x,y) 要的是屏幕坐标；不写清楚她会直接把
            # 截图里的数字交给 click，然后点到窗口外面去。
            result["px_hint"] = (
                "截图是窗口内像素。要点的屏幕坐标 = 窗口原点"
                f"({bounds.get('x')}, {bounds.get('y')}) + 截图内坐标。"
            )
    saved = find_saved_path(result)
    if saved is None:
        return {
            "note": "这次没拿到图片（目标窗口可能不支持截图，或树信息已经够用）。",
            "result": result,
        }
    return {"saved_to": saved, "note": "用 read_file 打开这个 PNG；别重复截图，先看这张。"}


def tool_raw(args: dict[str, Any]) -> Any:
    tool = str(args.get("tool") or "").strip()
    if not tool:
        raise DriverError("raw 需要 tool 名（cua-driver 的原生工具名）。")
    payload = args.get("arguments") or {}
    if not isinstance(payload, dict):
        raise DriverError("arguments 必须是一个对象；没参数就整个省掉。")
    # 曾经这里只有上面两行赋值、没有 return：`raw` 一律回 null，
    # launch_app / browser_navigate / bring_to_front 全是空操作，她“点了没反应”。
    return park_blobs(call_driver(tool, payload))


def tool_open(args: dict[str, Any]) -> Any:
    """启动一个程序，并把「可以操作的目标窗口」直接找出来。

    `launch_app` 对 Store 打包应用（记事本、计算器）不可靠：它回的是激活器
    进程的 pid，`windows` 是空数组。实测记事本回 pid 16252，而窗口实际属于
    14788；计算器回 15988、窗口 21912。照返回的 pid 去 act 只会白跑一趟，
    所以这里用启动前后的窗口差分把真窗口捞回来。
    """
    target = str(args.get("app") or args.get("path") or "").strip()
    if not target:
        raise DriverError("open 需要 app（程序名，比如 excel / notepad）或 path（exe 全路径）。")
    wait_s = float(args.get("wait_s") or 15)

    payload: dict[str, Any] = {}
    lowered = target.lower()
    if "\\" in target or "/" in target or lowered.endswith(".exe"):
        payload["path"] = target
    else:
        payload["name"] = target
    if args.get("file"):
        payload["files"] = [str(args["file"])]
    if args.get("arguments"):
        payload["additional_arguments"] = str(args["arguments"])

    before = {(w["pid"], w["window_id"]) for w in _fast_windows()}
    started = time.monotonic()
    result = call_driver("launch_app", payload)
    launch_ms = int((time.monotonic() - started) * 1000)

    needle = lowered.rsplit("\\", 1)[-1].rsplit("/", 1)[-1].removesuffix(".exe")
    hits: list[dict[str, Any]] = []
    deadline = time.monotonic() + wait_s
    while True:
        fresh = [w for w in _fast_windows() if (w["pid"], w["window_id"]) not in before]
        named = [
            w
            for w in fresh
            if needle in str(w.get("app_name") or "").lower()
            or needle in str(w.get("title") or "").lower()
        ]
        # 中文程序名（「记事本」）匹配不上进程名，这时新窗口只有一个就直接收下。
        hits = named or (fresh if len(fresh) == 1 else [])
        if hits or time.monotonic() >= deadline:
            break
        time.sleep(0.15)

    total_ms = int((time.monotonic() - started) * 1000)
    if not hits:
        return {
            "ok": False,
            "launch_ms": launch_ms,
            "note": (
                f"{target} 已经启动（驱动回的 pid {result.get('pid')}），但 {wait_s:.0f}s 内没等到它的窗口。"
                "Store 应用的启动可能更慢；过一会用 look(scope=windows) 再找，别重复 open。"
            ),
            "launched": result,
        }

    win = hits[0]
    return {
        "ok": True,
        "launch_ms": launch_ms,
        "total_ms": total_ms,
        "target": {"pid": win["pid"], "window_id": win["window_id"]},
        "app_name": win.get("app_name"),
        "title": win.get("title"),
        "windows": hits[:5],
        "note": "窗口已在后台打开，没抢用户焦点。接下来 act 直接带 app 名（或这个 pid/window_id）即可。",
    }


# ---------------------------------------------------------------------------
# 工具清单
# ---------------------------------------------------------------------------

_READ_ONLY = {"readOnlyHint": True, "destructiveHint": False}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "look",
        "description": (
            "看这台电脑现在长什么样：前台应用、窗口、可交互控件。要动界面前先用它，"
            "不要靠猜。回答「我现在在干嘛」「这个窗口里有什么」这类问题时也用它。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["front", "windows", "apps", "tree"],
                    "description": (
                        "front=前台窗口的控件树（默认，最省，带可直接点击的 [n]）；"
                        "windows=窗口列表；apps=运行中的应用；"
                        "tree=完整树（控件多到摘要不够时才用）。"
                    ),
                },
                "extra": {
                    "type": "object",
                    "description": "透传给底层驱动的额外参数（一般不用）。",
                },
            },
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "act",
        "description": (
            "在当前界面上做一个动作：点击控件、滚动、拖拽、输入文字、按键。点击优先用"
            " look 里看到的 [n]（写进 element_index，后台点击、不抢用户鼠标）；"
            "自绘界面才用 x/y 坐标。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "click",
                        "double_click",
                        "right_click",
                        "scroll",
                        "drag",
                        "type",
                        "key",
                    ],
                },
                "element_index": {
                    "type": "integer",
                    "description": "look 结果里控件前面的那个数字，比如 `[3] Button \"关闭\"` 就写 3。最稳的表达方式。",
                },
                "element_token": {
                    "type": "string",
                    "description": "驱动原生标识（形如 s00000002:3）。一般用 element_index 就够。",
                },
                "x": {"type": "number", "description": "屏幕绝对横坐标，或配合 space=window 时用截图内坐标。"},
                "y": {"type": "number", "description": "同上。"},
                "space": {
                    "type": "string",
                    "enum": ["screen", "window"],
                    "description": "window = x/y 按截图内像素算，自动加窗口原点。自绘界面（微信/企业微信）用这个。",
                },
                "text": {"type": "string", "description": "action=type 时要输入的文字。"},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "action=scroll 时的方向，默认 down。",
                },
                "amount": {"type": "integer", "description": "action=scroll 时滚多少格，默认 3。"},
                "from_x": {"type": "number", "description": "action=drag 的起点（窗口内截图坐标）。"},
                "from_y": {"type": "number", "description": "同上。"},
                "to_x": {"type": "number", "description": "action=drag 的终点横坐标。"},
                "to_y": {"type": "number", "description": "action=drag 的终点纵坐标。"},
                "keys": {
                    "type": "string",
                    "description": "action=key 时的组合键，如 ctrl+s / ctrl+shift+t（自动走 hotkey）。",
                },
                "nth": {
                    "type": "integer",
                    "description": "多个元素同名时取第几个（从 0 数），配合 name/role 用。",
                },
                "role": {
                    "type": "string",
                    "description": (
                        "按角色定位，如 button / textfield / menuitem / checkbox。"
                        "配合 name 一起用可以不先 look 直接点，常见动作只花一次往返。"
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "元素标签（控件树里的引号内文字），如 \"保存\"。给 name 就不用 element_index。",
                },
                "app": {"type": "string", "description": "目标应用名，省略则用前台应用。"},
                "delivery_mode": {
                    "type": "string",
                    "enum": ["background", "foreground"],
                    "description": (
                        "默认 background（不抢焦点）。WinUI3 / XAML 标题栏上后台点击会被静默吃掉，"
                        "回包里 effect=unverifiable 且界面没变时，用 foreground 重发一次。"
                    ),
                },
                "extra": {"type": "object", "description": "透传参数（一般不用）。"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "run_steps",
        "description": (
            "一次执行多步动作，只回一次结果。要连续点、输入好几下时用它，"
            "比来回多次 act 便宜得多。每步写成 {tool, args}，例如 "
            '{"tool":"press_key","args":{"key":"ctrl+s"}} 或 '
            '{"tool":"click","args":{"role":"button","name":"OK"}}；'
            '输入文字用 {"tool":"type_text","args":{"text":"..."}}，'
            "回车是 press_key key=enter。`{\"type\":\"key\",\"key\":\"end\"}` 这种随手写法也会自动翻译。"
            "不确定字段时先用单步 act 走一步，不要瞎猜一步就发十步。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "object"},
                    "description": (
                        "每项是 {tool, args}，如 {\"tool\":\"press_key\",\"args\":{\"key\":\"enter\"}}。"
                    ),
                },
                "extra": {"type": "object", "description": "透传参数（一般不用）。"},
            },
            "required": ["steps"],
        },
    },
    {
        "name": "screen",
        "description": (
            "截当前窗口的图，存成 PNG 只回路径（落在你工作区的 .laji/shots）。控件树说不清的时候用"
            "（Canvas、游戏、微信/企业微信这类自绘界面）。拿到路径用 read_file 看它；"
            "要按图上的位置点击，用 act {action:\"click\", space:\"window\", x, y}，不要自己加偏移。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {"type": "string"},
                "pid": {"type": "integer", "description": "目标进程号；省略则用前台窗口。"},
                "window_id": {"type": "integer"},
                "extra": {"type": "object"},
            },
        },
        "annotations": _READ_ONLY,
    },
    {
        "name": "open",
        "description": (
            "打开一个程序（excel / notepad / mspaint / 浏览器…），也可以顺带打开一个文件。"
            "窗口在后台起来，不抢用户焦点；返回可直接操作的目标（pid + window_id）。"
            "用户说「打开 X」时用它，不要用 raw。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "app": {
                    "type": "string",
                    "description": "程序名（不是标题）：excel、notepad、mspaint、chrome。",
                },
                "path": {"type": "string", "description": "exe 全路径（app 不知道时用）。"},
                "file": {"type": "string", "description": "顺带打开的文件全路径，比如一个 xlsx。"},
                "arguments": {"type": "string", "description": "传给程序的命令行参数。"},
                "wait_s": {
                    "type": "integer",
                    "description": "等窗口出现的最长秒数（默认 15）。Store 应用启动慢，别设太小。",
                },
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    {
        "name": "raw",
        "description": "透传任意 cua-driver 原生工具。look/act/run_steps 盖不到时才用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "description": "驱动器原生工具名。"},
                "arguments": {"type": "object"},
            },
            "required": ["tool"],
        },
    },
]

HANDLERS = {
    "look": tool_look,
    "act": tool_act,
    "run_steps": tool_run_steps,
    "screen": tool_screen,
    "open": tool_open,
    "raw": tool_raw,
}


# ---------------------------------------------------------------------------
# JSON-RPC 主循环
# ---------------------------------------------------------------------------


def send(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_request(method: str, params: dict[str, Any], req_id: Any) -> None:
    if method == "initialize":
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }})
        return
    if method == "ping":
        send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        return
    if method == "tools/list":
        send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return
    if method != "tools/call":
        send({"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32601, "message": f"method not found: {method}"}})
        return

    name = str(params.get("name") or "")
    handler = HANDLERS.get(name)
    if handler is None:
        send({"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32602, "message": f"unknown tool: {name}"}})
        return
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        send({"jsonrpc": "2.0", "id": req_id,
              "error": {"code": -32602, "message": "arguments must be an object"}})
        return

    try:
        result = handler(arguments)
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": render(result)}],
            "isError": False,
        }})
    except DriverError as exc:
        # 工具级失败回 isError，不是协议错误：模型读到的是可照做的下一步。
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": str(exc)}],
            "isError": True,
        }})
    except Exception as exc:  # noqa: BLE001 - 兜底，绝不让 server 崩掉
        send({"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": f"内部错误：{exc}"}],
            "isError": True,
        }})


def main() -> int:
    for stream in (sys.stdin, sys.stdout):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(message, dict):
            continue
        method = message.get("method")
        if method is None:
            continue  # 客户端对本 server 请求的响应；本 server 从不主动发请求
        if "id" not in message:
            continue  # 通知不回包
        params = message.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        handle_request(str(method), params, message.get("id"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
