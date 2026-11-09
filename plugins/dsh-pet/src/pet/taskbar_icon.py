# -*- coding: utf-8 -*-
"""任务栏「Laji Agent」图标在屏幕上的位置（Windows 11 / UI Automation）。

**存在理由**：桌宠「去开机」演出需要知道那颗图标在哪——她要走过去按一下。
本模块只回答「在哪」，不点、不抢鼠标、不模拟按键；真正的启动仍走
``agent_bridge`` 的 deep link（那条路已经有 force / run_id / workspace 全套语义，
拿 UIA 去 Invoke 会把它们全丢掉）。

为什么用 UIA 而不是截图找图
---------------------------
任务栏图标不是像素，是 UIA 按钮，且其 ``AutomationId`` 是 Windows 的
AppUserModelID（``Appid: com.nerve.laji.agent``）——**与窗口标题无关**：
dev 版的窗口标题是 "Electron"、生产版是 "Laji Agent"，两者的 AutomationId
完全相同。按标题匹配会在 dev/生产间漂移，按 Appid 不会。

实测（Win11 26100，本机 1280×720 @125%）：

* ``Shell_TrayWnd`` 矩形 L0 T672 R1280 B720，任务栏高 48；
* Laji 按钮 ``Appid: com.nerve.laji.agent`` → x 858..902（名字是 "Electron"）；
* 从根节点遍历整条任务栏 150 个节点、24 个按钮，耗时约 0.1～0.2s；
* typelib 首次生成（``GetModule``）约 0.2～0.6s，之后每次调用约 0.05s。

两条踩过的坑（都写进代码注释了，别回退）：

1. ``FindAll`` 在「一条都没匹配」时走 S_FALSE，comtypes 那条路会把整个进程
   带走（本机实测无声退出）；
2. ``FindFirst(class="Shell_SecondaryTrayWnd")`` 在**没有副屏任务栏**时要走
   **60 秒**超时才返回 null——所以任务栏窗口一律先用 Win32 的
   ``FindWindow`` / ``EnumWindows`` 拿句柄，再 ``ElementFromHandle`` 定向查询。

**一律失败关闭**：非 Windows / 缺 comtypes / UIA 抛异常 / 找不到图标 → 返回
``None``，调用方降级（原地按、或直接跳过走位），绝不在这里抛到 GUI 线程。
"""
from __future__ import annotations

import logging
import sys
import time

log = logging.getLogger(__name__)

#: AppUserModelID 候选（小写、子串匹配）。``com.nerve.laji.agent`` 是 dev 与生产
#: 共用的 appId；其余是历史/变体名，留着兜住老包。
_APPID_HINTS: tuple[str, ...] = (
    "com.nerve.laji.agent",
    "com.nerve.laji",
    "laji-agent",
)
#: 兜底：按按钮名匹配（本地化标题里带产品名时命中）。小写子串。
_NAME_HINTS: tuple[str, ...] = ("laji agent", "laji-agent", "拉吉")
#: 这些 Appid/名字属于桌宠自己或别的变体，命中也不能当成 Laji 主程序。
_EXCLUDE_HINTS: tuple[str, ...] = ("dsh-pet", "laji-pet", "桌宠", "dsh pet")
#: 找不到 Laji 按钮时的兜底落点：开始（优先）/ 搜索。
_START_HINTS: tuple[str, ...] = ("startbutton", "searchbutton")

#: 同一进程内连查时复用结果（演出期间会 2Hz 轮询「窗口出来了吗」）。
_CACHE_SECONDS = 1.6
_cache: tuple[float, "TaskbarIcon | None"] | None = None
_cache_start: tuple[float, "TaskbarIcon | None"] | None = None


class TaskbarIcon:
    """任务栏上那颗图标的屏幕矩形（物理像素，含任务栏自身坐标）。"""

    __slots__ = ("name", "automation_id", "left", "top", "right", "bottom")

    def __init__(self, name: str, automation_id: str,
                 left: int, top: int, right: int, bottom: int) -> None:
        self.name = str(name or "")
        self.automation_id = str(automation_id or "")
        self.left = int(left)
        self.top = int(top)
        self.right = int(right)
        self.bottom = int(bottom)

    # ---- 派生几何 -------------------------------------------------------
    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def center_x(self) -> int:
        return (self.left + self.right) // 2

    @property
    def center_y(self) -> int:
        return (self.top + self.bottom) // 2

    def __bool__(self) -> bool:  # 有实例就算找到了
        return self.width > 0 and self.height > 0

    def __repr__(self) -> str:
        return (f"TaskbarIcon(name={self.name!r}, aid={self.automation_id!r}, "
                f"x={self.left}..{self.right}, y={self.top}..{self.bottom})")


def available() -> bool:
    """UIA 后端是否可用（只查依赖，不查图标；给设置页/诊断用）。"""
    if sys.platform != "win32":
        return False
    try:
        import comtypes.client  # noqa: F401
    except Exception:
        return False
    return True


def locate(*, near: tuple[float, float] | None = None,
           use_cache: bool = True) -> TaskbarIcon | None:
    """找到 Laji 的任务栏按钮；找不到返回 ``None``。

    ``near``（屏幕坐标，通常传桌宠自己的位置）用来在多显示器、多任务栏时选
    **离桌宠最近的那条**任务栏——副屏也有自己的 ``Shell_SecondaryTrayWnd``。
    """
    global _cache
    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if use_cache and _cache is not None and now - _cache[0] < _CACHE_SECONDS:
        return _cache[1]
    try:
        icon = _locate_uncached(near)
    except Exception:  # UIA 任何异常都不许冒到 GUI 线程
        log.debug("taskbar_icon: 查询失败", exc_info=True)
        icon = None
    _cache = (now, icon)
    return icon


def invalidate() -> None:
    """丢掉缓存（演出开始前调一次：要的是"现在"的图标位置）。"""
    global _cache, _cache_start
    _cache = None
    _cache_start = None


# --------------------------------------------------------------------- 内部
def _tray_hwnds() -> list[int]:
    """所有任务栏窗口句柄（主 + 副屏）。

    为什么不用 UIA 的 ``FindFirst(class="Shell_SecondaryTrayWnd")``：**它会走
    60 秒超时**再返回 null（实测 Windows 11 26100：副屏任务栏不存在时单次调用
    60352ms，整条演出会被拖死）。Win32 的 ``FindWindow`` / ``EnumWindows`` 是
    本地调用，全程 <5ms，拿到句柄再 ``ElementFromHandle`` 是毫秒级的定向查询。
    """
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.WinDLL("user32", use_last_error=True)
    u32.FindWindowW.restype = wintypes.HWND
    u32.FindWindowW.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR)
    u32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)

    handles: list[int] = []
    primary = u32.FindWindowW("Shell_TrayWnd", None)
    if primary:
        handles.append(int(primary))

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        buf = ctypes.create_unicode_buffer(64)
        u32.GetClassNameW(hwnd, buf, 64)
        if buf.value == "Shell_SecondaryTrayWnd":
            handles.append(int(hwnd))
        return True

    u32.EnumWindows(_cb, 0)
    return handles


def _locate_uncached(near: tuple[float, float] | None) -> TaskbarIcon | None:
    hwnds = _tray_hwnds()
    if not hwnds:
        return None
    uia, UIA = _uia()
    trays = []
    for hwnd in hwnds:
        el = uia.ElementFromHandle(hwnd)
        if el is None:
            continue
        rect = el.CurrentBoundingRectangle
        trays.append((el, rect.left, rect.top, rect.right, rect.bottom))
    if not trays:
        return None
    if near is not None and len(trays) > 1:
        nx, ny = float(near[0]), float(near[1])
        trays.sort(key=lambda t: abs((t[1] + t[3]) / 2 - nx) + abs((t[2] + t[4]) / 2 - ny))

    walker = uia.RawViewWalker
    for el, _l, _t, _r, _b in trays:
        best = _best_in(el, walker, UIA)
        if best is not None:
            return best
    return None


def locate_start(use_cache: bool = True) -> TaskbarIcon | None:
    """兜底目标：开始 / 搜索按钮。

    为什么需要：**Laji 收在托盘、或者干脆没开的时候，任务栏上根本没有它的
    按钮**（窗口一 hide，按钮就没了）。这时"走过去点图标"没有目标，演出只能
    原地按一下——看着像假动作。退而求其次走去开始菜单翻一翻，既有真实位移，
    也符合"找东西"的直觉。
    """
    global _cache_start
    if sys.platform != "win32":
        return None
    now = time.monotonic()
    if use_cache and _cache_start is not None and now - _cache_start[0] < _CACHE_SECONDS:
        return _cache_start[1]
    icon = None
    try:
        uia, UIA = _uia()
        walker = uia.RawViewWalker
        for hwnd in _tray_hwnds():
            el = uia.ElementFromHandle(hwnd)
            if el is None:
                continue
            icon = _find_by_aid(el, walker, UIA, _START_HINTS)
            if icon is not None:
                break
    except Exception:  # UIA 任何异常都不许冒到 GUI 线程
        log.debug("taskbar_icon: 开始按钮定位失败", exc_info=True)
        icon = None
    _cache_start = (now, icon)
    return icon


def _find_by_aid(tray_el, walker, UIA, aids: tuple[str, ...]) -> TaskbarIcon | None:
    """按 Appid 子串在任务栏树里找按钮（找不到返回 None，不抛）。"""
    btn = _find_button_by_aid(tray_el, walker, UIA, aids)
    return _button_to_icon(btn) if btn is not None else None


def _find_button_by_aid(tray_el, walker, UIA, aids: tuple[str, ...]):
    """返回命中的 UIA 按钮**元素**（按下去要用它，光有坐标不够）。"""
    stack = [tray_el]
    visited = 0
    while stack:
        el = stack.pop()
        visited += 1
        try:
            child = walker.GetFirstChildElement(el)
        except Exception:
            child = None
        while child is not None:
            stack.append(child)
            try:
                if child.CurrentControlType == UIA.UIA_ButtonControlTypeId:
                    icon = _button_to_icon(child)
                    if icon is not None:
                        aid = icon.automation_id.lower()
                        if any(h.lower() in aid for h in aids):
                            return child
            except Exception:
                pass
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                child = None
        if visited > 4000:
            break
    return None


def press_start() -> bool:
    """真的按一下开始按钮（UIA，不动鼠标），返回是否按到。

    为什么要真按：走过去却只是原地做个动作，用户一眼就看穿是假戏。按下去让
    开始菜单真的弹出来，再配合真实启动，整条链才立得住。

    开始按钮在 Win11 上是 ``ToggleButton``：**Invoke 模式的指针是空的**，只认
    Toggle。先试 Toggle，再退 Invoke（老版本/第三方任务栏仍是普通按钮）。
    """
    return _press_by_aid(_START_HINTS, exclude_self=False)


def press_laji() -> bool:
    """真的按一下任务栏上的 Laji 按钮（窗口收着时它不存在，返回 False）。"""
    return _press_by_aid((), exclude_self=True)


def _press_by_aid(aids: tuple[str, ...], *, exclude_self: bool) -> bool:
    """在任务栏按钮里找目标并"按下去"；``aids`` 为空 = 按 Laji 的匹配规则找。"""
    if sys.platform != "win32":
        return False
    try:
        uia, UIA = _uia()
        walker = uia.RawViewWalker
        for hwnd in _tray_hwnds():
            el = uia.ElementFromHandle(hwnd)
            if el is None:
                continue
            btn = _find_button_by_aid(el, walker, UIA, aids) if aids \
                else _find_laji_button(el, walker, UIA, exclude_self)
            if btn is None:
                continue
            for pid, iface, call in (
                (UIA.UIA_TogglePatternId, "IUIAutomationTogglePattern", "Toggle"),
                (UIA.UIA_InvokePatternId, "IUIAutomationInvokePattern", "Invoke"),
            ):
                try:
                    raw = btn.GetCurrentPattern(pid)
                    if not raw:
                        continue
                    obj = raw.QueryInterface(getattr(UIA, iface))
                    getattr(obj, call)()
                    log.debug("taskbar_icon: 已按下（%s）", call)
                    return True
                except Exception:
                    continue
    except Exception:
        log.debug("taskbar_icon: 按下失败", exc_info=True)
    return False


def _find_laji_button(tray_el, walker, UIA, exclude_self: bool):
    """按"是不是 Laji"的既有规则找按钮元素（判定与定位共用一套，别两套）。"""
    stack = [tray_el]
    visited = 0
    while stack:
        el = stack.pop()
        visited += 1
        try:
            child = walker.GetFirstChildElement(el)
        except Exception:
            child = None
        while child is not None:
            stack.append(child)
            try:
                if child.CurrentControlType == UIA.UIA_ButtonControlTypeId:
                    icon = _button_to_icon(child)
                    if icon is not None:
                        if exclude_self and _excluded(icon):
                            pass
                        elif _appid_hit(icon) or _name_hit(icon):
                            return child
            except Exception:
                pass
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                child = None
        if visited > 4000:
            break
    return None


def dismiss_start() -> None:
    """发一个 Esc：把开始菜单收回去（Laji 一起来就盖住它，别留在那儿）。"""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.keybd_event(0x1B, 0, 0, 0)          # VK_ESCAPE down
        user32.keybd_event(0x1B, 0, 2, 0)          # KEYEVENTF_KEYUP
    except Exception:
        log.debug("taskbar_icon: 收开始菜单失败", exc_info=True)


def _best_in(tray_el, walker, UIA) -> TaskbarIcon | None:
    """遍历一条任务栏下的所有按钮，按 Appid → 名字 的优先级挑出 Laji。"""
    by_name: list[TaskbarIcon] = []
    stack = [tray_el]
    visited = 0
    while stack:
        el = stack.pop()
        visited += 1
        try:
            child = walker.GetFirstChildElement(el)
        except Exception:
            child = None
        while child is not None:
            stack.append(child)
            try:
                if child.CurrentControlType == UIA.UIA_ButtonControlTypeId:
                    icon = _button_to_icon(child)
                    if icon is not None:
                        if _appid_hit(icon):
                            return icon      # 最强证据：直接收工
                        if _name_hit(icon):
                            by_name.append(icon)
            except Exception:
                pass
            try:
                child = walker.GetNextSiblingElement(child)
            except Exception:
                child = None
        if visited > 4000:  # 病态树的兜底，正常任务栏 ~150 个节点
            break
    return by_name[0] if by_name else None


def _button_to_icon(el) -> TaskbarIcon | None:
    try:
        rect = el.CurrentBoundingRectangle
        if rect.right <= rect.left or rect.bottom <= rect.top:
            return None
        try:
            aid = el.CurrentAutomationId or ""
        except Exception:
            aid = ""
        try:
            name = el.CurrentName or ""
        except Exception:
            name = ""
        return TaskbarIcon(name, aid, rect.left, rect.top, rect.right, rect.bottom)
    except Exception:
        return None


def _excluded(icon: TaskbarIcon) -> bool:
    blob = f"{icon.name} {icon.automation_id}".lower()
    return any(h in blob for h in _EXCLUDE_HINTS)


def _appid_hit(icon: TaskbarIcon) -> bool:
    if _excluded(icon):
        return False
    aid = icon.automation_id.lower()
    return any(h in aid for h in _APPID_HINTS)


def _name_hit(icon: TaskbarIcon) -> bool:
    if _excluded(icon):
        return False
    name = icon.name.lower()
    return any(h in name for h in _NAME_HINTS)


def _uia():
    """建一个 IUIAutomation（**每次调用新建**：不跨线程共享 COM 对象）。"""
    import comtypes
    import comtypes.client

    try:
        comtypes.CoInitialize()  # 工作线程里必须先初始化单元
    except Exception:
        pass
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen import UIAutomationClient as UIA

    uia = comtypes.client.CreateObject(
        UIA.CUIAutomation._reg_clsid_, interface=UIA.IUIAutomation)
    return uia, UIA
