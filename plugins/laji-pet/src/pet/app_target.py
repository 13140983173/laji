"""任意应用的「找到它 / 点亮它」。

和 :mod:`agent_locator` 的分工：

* ``agent_locator`` 是**给 Laji 自己用的**，只要能拿到一条能拉起的路径（lnk 明文
  11ms → 安装根目录 → 运行中进程），不管界面长什么样。
* 本模块是**给演出用的**：它必须回答"她该走向哪里、按哪里"，所以除了路径，还要
  一个**屏幕上的落点**和一次**真的点得动的动作**。

三级落点（越靠前越像"人真的去找"）：

1. ``desktop``  —— 桌面图标可见：走过去双击。最快也最直观，但会被窗口挡住。
2. ``startmenu``—— 开始菜单「所有应用」里有：走过去按开始 → 所有应用 → 滚到它 →
   ``Invoke``。**已实测**：豆包 527ms 命中、Invoke 9ms、0.4s 后进程起来。
3. 兜底 —— 菜单里翻不到就直接 ``Popen``（把 lnk 指向的 exe 拉起来），保证"真的
   打开了"，只是少了"翻到它"那一下。

为什么不走搜索框：Win11 的搜索框是 RichEditBox（TSF 宿主），``SetFocus`` 后
``HasKeyboardFocus=1``，但 ``SendInput`` 发 Unicode 字符**界面毫无反应**——实测
四次探针都是这个结果。所以打字那条路在这里是死的，别回头再试。
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import desktop_icon

log = logging.getLogger(__name__)

#: 开始菜单里"所有应用"页的控件锚点（Win11 实测，见模块 docstring）。
_AID_SHOW_ALL = "ShowAllAppsButton"
_AID_APPS_LIST = "AppsList"
_AID_SEARCH_BOX = "StartMenuSearchBox"


@dataclass
class AppGoal:
    """一次"去把她要找的东西点亮"的全部所需。"""

    label: str                       # 用户嘴里的名字，用来念台词
    kind: str                        # desktop / startmenu
    exe: str = ""                    # lnk 里读到的真实 exe（兜底 Popen 用）
    lnk: str = ""
    left: float = 0.0                # 屏幕落点（物理像素，与 UIA 同口径）
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0
    activate: Callable[[], bool] | None = field(default=None, repr=False)

    @property
    def center_x(self) -> float:
        return (self.left + self.right) / 2.0

    @property
    def center_y(self) -> float:
        return (self.top + self.bottom) / 2.0

    def activate_quiet(self) -> bool:
        """**不弹任何界面**的最短路径：直接拉 exe，退一步用 shell 打开 lnk。

        只给"安静不演"这一档用：那一档不走路、不播按，再让她去翻开始菜单就是
        "没有演出的等待"——用户在等一个看不见的过程。翻不到 exe/lnk 时返回
        False，调用方退回正常路径（宁慢不假）。
        """
        if self.exe and _spawn(self.exe):
            log.debug("app_target: 安静档直拉 %s", self.exe)
            return True
        lnk = self.lnk or _start_menu_link(self.label)
        if lnk:
            ok = _shell_open(lnk)
            log.debug("app_target: 安静档 shell 打开 %s → %s", lnk, ok)
            return ok
        return False


# ---------------------------------------------------------------- 开始菜单
def _uia():
    """拿 UIA 对象；调用方负责兜异常（UIA 任何错误都不许冒到 GUI 线程）。"""
    import comtypes.client
    from comtypes.gen import UIAutomationClient as UIA

    uia = comtypes.client.CreateObject(
        "{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=UIA.IUIAutomation
    )
    return uia, UIA


def _pattern(el, UIA, pid: int, iface: str):
    raw = el.GetCurrentPattern(pid)
    return raw.QueryInterface(getattr(UIA, iface)) if raw else None


def _invoke(el, UIA) -> bool:
    """点一下元素；先 Invoke 再退 Legacy 默认动作（开始菜单项两种都有）。"""
    for pid, iface, call in (
        (UIA.UIA_InvokePatternId, "IUIAutomationInvokePattern", "Invoke"),
        (UIA.UIA_LegacyIAccessiblePatternId, "IUIAutomationLegacyIAccessiblePattern", "DoDefaultAction"),
    ):
        try:
            obj = _pattern(el, UIA, pid, iface)
            if obj is None:
                continue
            getattr(obj, call)()
            return True
        except Exception:
            continue
    return False


def _start_menu_window(uia, UIA, tries: int = 12, gap: float = 0.1):
    """等开始菜单窗口出现（XAML 有出场动画，handle 不会立刻可枚举）。"""
    cond = uia.CreatePropertyCondition(
        UIA.UIA_ClassNamePropertyId, "Windows.UI.Core.CoreWindow"
    )
    for _ in range(tries):
        try:
            win = uia.GetRootElement().FindFirst(UIA.TreeScope_Children, cond)
        except Exception:
            win = None
        if win is not None:
            return win
        time.sleep(gap)
    return None


def _find_item(win, uia, name: str, attempts: int = 18, step: float = 0.2):
    """在「所有应用」里按名字找条目：逐屏扫，扫完一屏往下滚一屏。

    列表是虚拟化的——只有滚进视口的那批才有 UIA 元素，所以"一次全量枚举"永远
    找不到中段的应用。滚动挂在 ``AppsList`` 上（挂在窗口上取不到 ScrollPattern）。
    """
    UIA = None
    from comtypes.gen import UIAutomationClient as _UIA

    UIA = _UIA
    walker = uia.RawViewWalker

    def scan() -> Any:
        stack = [win]
        visited = 0
        while stack:
            el = stack.pop()
            visited += 1
            if visited > 6000:
                return None
            try:
                if name in (el.CurrentName or ""):
                    return el
            except Exception:
                pass
            try:
                child = walker.GetFirstChildElement(el)
            except Exception:
                child = None
            kids = []
            while child is not None:
                kids.append(child)
                try:
                    child = walker.GetNextSiblingElement(child)
                except Exception:
                    break
            stack.extend(reversed(kids))
        return None

    apps = None
    try:
        aid = uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, _AID_APPS_LIST)
        lst = win.FindFirst(UIA.TreeScope_Descendants, aid)
        if lst is not None:
            apps = _pattern(lst, UIA, UIA.UIA_ScrollPatternId, "IUIAutomationScrollPattern")
    except Exception:
        apps = None

    hit = scan()
    if hit is not None:
        return hit
    if apps is None:
        return None
    for i in range(attempts):
        try:
            apps.SetScrollPercent(-1.0, float(min(100, 5 + i * 6)))
        except Exception:
            return None
        time.sleep(step)
        hit = scan()
        if hit is not None:
            return hit
    return None


def open_from_start_menu(name: str, *, dismiss_on_fail: bool = True) -> bool:
    """真按开始 → 所有应用 → 滚到 ``name`` → 点它。

    返回 False 时菜单已经被收回（不留半截现场）。调用方可以直接落兜底。
    """
    if sys.platform != "win32":
        return False
    from . import taskbar_icon

    if not taskbar_icon.press_start():
        return False
    ok = False
    try:
        uia, UIA = _uia()
        win = _start_menu_window(uia, UIA)
        if win is None:
            return False
        aid = uia.CreatePropertyCondition(UIA.UIA_AutomationIdPropertyId, _AID_SHOW_ALL)
        btn = win.FindFirst(UIA.TreeScope_Descendants, aid)
        if btn is None:
            return False
        if not _invoke(btn, UIA):          # 进「所有应用」
            return False
        time.sleep(0.9)                     # 页面切换动画
        item = _find_item(win, uia, name)
        if item is None:
            log.debug("app_target: 所有应用里没有 %s", name)
            return False
        ok = _invoke(item, UIA)
        log.debug("app_target: 开始菜单点中 %s → %s", name, ok)
        return ok
    except Exception:
        log.debug("app_target: 开始菜单路径失败", exc_info=True)
        return False
    finally:
        if not ok and dismiss_on_fail:
            try:
                taskbar_icon.dismiss_start()
            except Exception:
                pass


# ---------------------------------------------------------------- 解析
def _start_menu_link(name: str) -> str:
    """在开始菜单里按名字找 lnk（1~2ms，只读文件，不弹任何 UI）。"""
    from . import agent_locator

    needle = name.lower()
    roots = [
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("ProgramData", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for path in _walk_links(root):
            stem = os.path.splitext(os.path.basename(path))[0]
            if needle in stem.lower():
                return path
    return ""


def _walk_links(root: str):
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith(".lnk"):
                yield os.path.join(dirpath, fn)


def resolve(name: str, *, desktop_first: bool = True) -> AppGoal | None:
    """名字 → 一次可演的打开动作；找不到返回 ``None``（调用方演"没找到"）。

    这一层**只做决策、不碰界面**：桌面图标是读 UIA 缓存（~180ms），开始菜单是读
    lnk 文件（~2ms）。真正弹菜单发生在 ``activate()`` 里，也就是她"走过去按下"
    那一刻——不然戏还没开演，界面先自己动起来了。
    """
    label = str(name or "").strip()
    if not label:
        return None
    from . import agent_locator

    # ① 桌面图标（可见才可用：被窗口盖住时双击会点到别的程序）
    if desktop_first:
        icon = desktop_icon.locate(_hints(label), use_cache=True)
        if icon is not None:
            def _desk(icon=icon) -> bool:
                return bool(desktop_icon.double_click(
                    int(icon.center_x), int(icon.center_y)))

            return AppGoal(label=label, kind="desktop",
                           left=float(icon.left), top=float(icon.top),
                           right=float(icon.right), bottom=float(icon.bottom),
                           activate=_desk)

    # ② 开始菜单：先确认"它在那儿"（读 lnk，不弹界面），再决定演哪一出
    lnk = _start_menu_link(label)
    exe = agent_locator.exe_from_link(lnk) if lnk else ""
    if lnk:
        # 落点 = 开始按钮（左下角）。没有这个坐标，走位会算到屏幕 (0,0)，
        # 看起来像"往左上角发呆"。取不到就退回任务栏左上角附近，仍比 0 好。
        from . import taskbar_icon

        start = None
        try:
            start = taskbar_icon.locate_start()
        except Exception:
            start = None
        left = float(getattr(start, "left", 0) or 0)
        right = float(getattr(start, "right", 0) or 0)
        top = float(getattr(start, "top", 0) or 0)
        bottom = float(getattr(start, "bottom", 0) or 0)
        if not right:
            left, right, top, bottom = 8.0, 68.0, 900.0, 960.0

        def _menu(label=label, exe=exe) -> bool:
            if open_from_start_menu(label):
                return True
            # 菜单里翻不到（名字和显示名不一致、或条目在折叠文件夹里）：
            # 直接拉 exe，别让"按了半天没反应"发生在用户眼前。
            return bool(exe) and _spawn(exe)

        return AppGoal(label=label, kind="startmenu", exe=exe, lnk=lnk,
                       left=left, top=top, right=right, bottom=bottom,
                       activate=_menu)

    log.debug("app_target: 桌面和开始菜单都没有 %s", label)
    return None


def _hints(label: str) -> tuple[str, ...]:
    """桌面图标的匹配词：原名 + 去掉空格的低配版（UIA 的 Name 常带后缀）。"""
    out = [label]
    squeezed = label.replace(" ", "")
    if squeezed and squeezed != label:
        out.append(squeezed)
    return tuple(out)


def _spawn(exe: str) -> bool:
    if not exe or not os.path.isfile(exe):
        return False
    try:
        subprocess.Popen([exe], close_fds=True,
                         creationflags=getattr(subprocess, "DETACHED_PROCESS", 0),
                         cwd=os.path.dirname(exe) or None)
        return True
    except Exception:
        log.debug("app_target: 拉起 %s 失败", exe, exc_info=True)
        return False


def _shell_open(path: str) -> bool:
    """用系统默认方式打开一个文件/快捷方式（lnk 指向的程序会照常起来）。"""
    if not path or not os.path.isfile(path):
        return False
    try:
        os.startfile(path)          # noqa: S606 —— Windows 专有，只在这里用
        return True
    except Exception:
        log.debug("app_target: shell 打开 %s 失败", path, exc_info=True)
        return False


def window_visible(name: str) -> bool:
    """屏幕上有没有它的可见窗口——「开没开」的唯一判据。

    不看进程：Electron/浏览器内核应用启动瞬间就有进程，窗口却要几秒才画出来；
    反过来进程还在退出时窗口已经没了。演出等的是"门开了"，不是"人在里面"。
    """
    if sys.platform != "win32" or not name:
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32")
    needle = name.lower()
    hit = [False]

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lp):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if needle in buf.value.lower():
            hit[0] = True
            return False                 # 找到就停
        return True

    try:
        user32.EnumWindows(_cb, 0)
    except Exception:
        return False
    return hit[0]


def activate_async(goal: AppGoal) -> threading.Thread | None:
    """把 ``activate`` 丢到后台线程：点开始菜单要 1~2 秒，不能卡住 16ms 的动画帧。"""
    if goal is None or goal.activate is None:
        return None

    def _run() -> None:
        try:
            goal.activate()
        except Exception:
            log.debug("app_target: 激活线程异常", exc_info=True)

    t = threading.Thread(target=_run, name="pet-open-app", daemon=True)
    t.start()
    return t
