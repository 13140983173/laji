"""桌面图标定位与双击：桌宠真的走到桌面上的 Laji 图标去点开它。

为什么不复用 ``taskbar_icon``：任务栏和桌面是两套 UIA 树（任务栏是 XAML，桌面是
``SysListView32`` 传统 ListView），判定逻辑也不同（桌面按图标名，任务栏按 Appid）。
混在一个模块里只会让两边都变难读。

坐标口径：UIA 在 DPI-aware 进程里给**物理像素**，而 sprite 用逻辑像素；调用方要
自己换算（``work_choreo`` 里统一走 ``screen_scale``）。
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

_CACHE_SECONDS = 3.0
_cache: tuple[float, "DesktopIcon | None"] | None = None


@dataclass(frozen=True)
class DesktopIcon:
    name: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2


def _uia():
    from .taskbar_icon import _uia as inner

    return inner()


def _visible_at(x: int, y: int) -> bool:
    """这个点上最顶层的是不是桌面（被窗口盖住就点不到）。

    ``WindowFromPoint`` 会跳过 ``WS_EX_TRANSPARENT`` 窗口，所以桌宠自己的 overlay
    不会把桌面判成"被遮挡"。实测：WorkBuddy 最大化时，桌面图标坐标上其实是聊天
    区，双击只会点进窗口——走过去也是白走。
    """
    try:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.WindowFromPoint.argtypes = [wintypes.POINT]
        u32.WindowFromPoint.restype = wintypes.HWND
        u32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        hwnd = u32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not hwnd:
            return False
        cls = ctypes.create_unicode_buffer(128)
        u32.GetClassNameW(hwnd, cls, 128)
        name = cls.value
        if name in ("Progman", "WorkerW", "SysListView32", "SHELLDLL_DefView"):
            return True
        # 兜底：再看它的父窗口链，桌面图标有时挂在 WorkerW 的子窗口下。
        parent = u32.GetParent(hwnd)
        for _ in range(3):
            if not parent:
                break
            u32.GetClassNameW(parent, cls, 128)
            if cls.value in ("Progman", "WorkerW", "SHELLDLL_DefView"):
                return True
            parent = u32.GetParent(parent)
        return False
    except Exception:
        return True          # 判不了就当可见，别因为探测失败把功能关掉


def locate(hints: tuple[str, ...] = ("laji",), use_cache: bool = True) -> DesktopIcon | None:
    """在桌面上按名字找图标（找不到、或被窗口盖住时返回 None）。"""
    global _cache
    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if use_cache and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    icon = None
    try:
        found = _locate_uncached(hints)
        if found is not None and _visible_at(found.center_x, found.center_y):
            icon = found
        elif found is not None:
            log.debug("desktop_icon: %r 被窗口盖住，跳过", found.name)
    except Exception:
        log.debug("desktop_icon: 定位失败", exc_info=True)
    _cache = (now, icon)
    return icon


def invalidate() -> None:
    global _cache
    _cache = None


def _desktop_listview() -> int:
    """桌面图标那个 ListView 的 HWND（找到返回句柄，否则 0）。

    直接问 Win32 要句柄，不要在 ``GetRootElement()`` 上递归：桌面整棵树里塞着
    几十个窗口，递归一遍 2.4 秒；拿句柄再 ``ElementFromHandle`` 只要 0.2 毫秒。
    """
    try:
        import ctypes
        from ctypes import wintypes

        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                      wintypes.LPCWSTR, wintypes.LPCWSTR]
        u32.FindWindowExW.restype = wintypes.HWND
        progman = u32.FindWindowExW(0, 0, "Progman", None)
        view = u32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
        if not view:
            # 开了"滚动壁纸"之类特性时，DefView 会被挪到某个 WorkerW 下面。
            worker = u32.FindWindowExW(0, 0, "WorkerW", None)
            while worker and not view:
                view = u32.FindWindowExW(worker, 0, "SHELLDLL_DefView", None)
                worker = u32.FindWindowExW(0, worker, "WorkerW", None)
        if not view:
            return 0
        return int(u32.FindWindowExW(view, 0, "SysListView32", "FolderView"))
    except Exception:
        log.debug("desktop_icon: 拿 ListView 句柄失败", exc_info=True)
        return 0


def _locate_uncached(hints: tuple[str, ...]) -> DesktopIcon | None:
    uia, UIA = _uia()
    hwnd = _desktop_listview()
    if not hwnd:
        return None
    walker = uia.RawViewWalker
    view = uia.ElementFromHandle(hwnd)
    if view is None:
        return None
    try:
        child = walker.GetFirstChildElement(view)
    except Exception:
        return None
    seen = 0
    while child is not None and seen < 300:
        seen += 1
        try:
            if child.CurrentControlType == UIA.UIA_ListItemControlTypeId:
                name = child.CurrentName or ""
                if any(h.lower() in name.lower() for h in hints):
                    r = child.CurrentBoundingRectangle
                    if r.right > r.left and r.bottom > r.top:
                        return DesktopIcon(name, r.left, r.top, r.right, r.bottom)
        except Exception:
            pass
        try:
            child = walker.GetNextSiblingElement(child)
        except Exception:
            child = None
    return None


def mouse_scale() -> float:
    """UIA 坐标 → ``SetCursorPos`` 需要的倍率。

    UIA 的坐标系随进程的 DPI awareness 变：DPI-unaware 进程拿到的是**逻辑像素**
    （1920×1080 屏、150% 缩放下是 1280×720），而 ``SetCursorPos`` 只认物理像素。
    不换算就会点到完全不相干的地方——实测双击"点到了图标"，进程却一个都没起来。
    """
    if sys.platform != "win32":
        return 1.0
    try:
        import ctypes
        from ctypes import wintypes

        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        awareness = ctypes.c_int()
        # 0 = UNAWARE（UIA 给逻辑像素），1 = SYSTEM，2 = PER_MONITOR（都给物理）
        shcore.GetProcessDpiAwareness(None, ctypes.byref(awareness))
        if awareness.value != 0:
            return 1.0
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        dc = u32.GetDC(0)
        dpi = ctypes.WinDLL("gdi32", use_last_error=True).GetDeviceCaps(dc, 88)  # LOGPIXELSX
        u32.ReleaseDC(0, dc)
        return max(1.0, float(dpi) / 96.0)
    except Exception:
        log.debug("desktop_icon: 读 DPI 失败", exc_info=True)
        return 1.0


def double_click(x: int, y: int) -> bool:
    """在屏幕坐标双击。``x/y`` 用 **UIA 坐标系**（内部按 DPI 换算成物理像素）。

    会移动鼠标——用户点了「打工」，这算预期动作。
    """
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        scale = mouse_scale()
        px, py = int(round(x * scale)), int(round(y * scale))
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.SetCursorPos(px, py)
        time.sleep(0.08)
        for _ in range(2):
            u32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
            time.sleep(0.03)
            u32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
            time.sleep(0.08)
        log.debug("desktop_icon: 双击 (%d,%d) → 物理 (%d,%d) scale=%.2f",
                  x, y, px, py, scale)
        return True
    except Exception:
        log.debug("desktop_icon: 双击失败", exc_info=True)
        return False
