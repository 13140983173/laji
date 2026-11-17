# -*- coding: utf-8 -*-
"""Laji 主窗**真的出现了吗**（进程起来 ≠ 门开了）。

**为什么不能只问进程**：``agent_bridge.laji_running()`` 在 spawn 后 1 秒内就为真，
而 Electron 从进程创建到主窗可交互在本机要 8～19 秒（AV 挂钩税 + Vite 冷优化）。
拿它当"开机完成"的信号，桌宠会在 1 秒后就开始庆祝，然后干等十几秒——比不演更怪。

这里换个**面向用户可见结果**的判据：目标进程名下有一个**可见的、非工具窗的、
够大的、且真的落在屏幕上**的顶层窗口（Electron 主窗在 ``did-finish-load``
之后才有）。判据不含标题文字，因此与中英文/程序标题无关；dev 版标题是
"Electron" 也命中。

"落在屏幕上"这一条是实测补的：Laji 收进托盘时，Electron 会把主窗搬到
``(-21333, -21333)`` 再缩到 158×134（本机实测），只查"可见 + 尺寸"会把
这个幽灵窗口当成"门已经开了"。

全程 ctypes（``user32``/``kernel32``），不引入新依赖，可安全跑在 GUI 线程上：
实测这台机器 200 个顶层窗口扫一遍 ~3ms，故再加 0.4s 缓存，轮询不心疼。
"""
from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes

log = logging.getLogger(__name__)

#: 与 ``agent_bridge._LAJI_PROCESS_NAMES`` 同口径（进程名去掉 .exe 后比较）。
EXE_NAMES: tuple[str, ...] = ("laji", "lajiagent", "laji-agent", "laji agent")

#: 比这个小的窗口不算"主窗"（启动时 Electron 会先有 0×0 / 小托盘窗）。
MIN_W, MIN_H = 320, 240

_CACHE_SECONDS = 0.4
_cache: tuple[float, bool] | None = None

_GWL_EXSTYLE = -20
_WS_EX_TOOLWINDOW = 0x00000080
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def visible(*, use_cache: bool = True) -> bool:
    """Laji 主窗是否已经可见（缓存 0.4s）。"""
    global _cache
    if sys.platform != "win32":
        return False
    now = time.monotonic()
    if use_cache and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        value = bool(_scan())
    except Exception:
        log.debug("agent_window: 扫描失败", exc_info=True)
        value = False
    _cache = (now, value)
    return value


def invalidate() -> None:
    global _cache
    _cache = None


def _scan() -> bool:
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    found = {"hit": False}
    # 虚拟桌面范围（多显示器合并后的整体）；窗口必须与它有交集
    vx = u32.GetSystemMetrics(76)
    vy = u32.GetSystemMetrics(77)
    vw = u32.GetSystemMetrics(78)
    vh = u32.GetSystemMetrics(79)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        try:
            if not u32.IsWindowVisible(hwnd):
                return True
            style = u32.GetWindowLongW(hwnd, _GWL_EXSTYLE)
            if style & _WS_EX_TOOLWINDOW:
                return True          # 托盘/悬浮工具窗不算主窗
            rect = wintypes.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rect))
            w = rect.right - rect.left
            h = rect.bottom - rect.top
            if w < MIN_W or h < MIN_H:
                return True
            # 托盘幽灵窗：坐标为 -21333 且缩得很小——不在屏幕上就不算
            if (rect.right <= vx or rect.left >= vx + vw
                    or rect.bottom <= vy or rect.top >= vy + vh):
                return True
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if _exe_matches(k32, pid.value):
                found["hit"] = True
                return False         # 找到就停
        except Exception:
            pass
        return True

    u32.EnumWindows(_cb, 0)
    return found["hit"]


def _exe_matches(k32, pid: int) -> bool:
    if not pid:
        return False
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        return False
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return False
        name = buf.value.rsplit("\\", 1)[-1].lower()
        if name.endswith(".exe"):
            name = name[:-4]
        return name in EXE_NAMES
    finally:
        k32.CloseHandle(handle)
