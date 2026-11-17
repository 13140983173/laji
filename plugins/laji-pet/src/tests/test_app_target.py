# -*- coding: utf-8 -*-
"""目标解析：名字 → 一次可演的打开动作。

这层只做**决策**（读缓存、读 lnk 文件），绝不弹任何界面——真正弹开始菜单发生在
她"走过去按下"那一刻。所以测试里也断言：resolve 期间不许碰 press/invoke。
"""
from __future__ import annotations

import pytest

from pet import app_target as at


@pytest.fixture(autouse=True)
def _no_real_taskbar(monkeypatch):
    """单测不许碰真实任务栏：locate_start 是真 UIA 调用，慢且依赖桌面状态。"""
    from pet import taskbar_icon

    monkeypatch.setattr(taskbar_icon, "locate_start",
                        lambda use_cache=True: None)


class _Icon:
    left, top, right, bottom = 200, 300, 240, 340

    @property
    def center_x(self):
        return 220.0

    @property
    def center_y(self):
        return 320.0


def test_prefers_desktop_icon_when_visible(monkeypatch):
    monkeypatch.setattr(at.desktop_icon, "locate", lambda hints, use_cache=True: _Icon())
    monkeypatch.setattr(at, "_start_menu_link", lambda name: "")
    clicks = []
    monkeypatch.setattr(at.desktop_icon, "double_click",
                        lambda x, y: clicks.append((x, y)) or True)

    goal = at.resolve("豆包")
    assert goal is not None and goal.kind == "desktop"
    assert (goal.left, goal.right) == (200, 240)
    assert goal.activate() is True
    assert clicks == [(220, 320)], "双击的必须是图标中心"


def test_falls_back_to_start_menu_and_reports_exe(monkeypatch):
    monkeypatch.setattr(at.desktop_icon, "locate", lambda hints, use_cache=True: None)
    monkeypatch.setattr(at, "_start_menu_link", lambda name: r"C:\x\豆包.lnk")
    monkeypatch.setattr(at, "open_from_start_menu", lambda name, **kw: True)
    from pet import agent_locator
    monkeypatch.setattr(agent_locator, "exe_from_link",
                        lambda lnk: r"D:\soft\doubao\Doubao.exe")

    goal = at.resolve("豆包")
    assert goal is not None and goal.kind == "startmenu"
    assert goal.exe == r"D:\soft\doubao\Doubao.exe"
    assert goal.activate() is True


def test_start_menu_miss_falls_back_to_exe(monkeypatch):
    """菜单里翻不到（名字对不上/折叠在文件夹里）就直接拉 exe，不许空手回来。"""
    monkeypatch.setattr(at.desktop_icon, "locate", lambda hints, use_cache=True: None)
    monkeypatch.setattr(at, "_start_menu_link", lambda name: r"C:\x\豆包.lnk")
    monkeypatch.setattr(at, "open_from_start_menu", lambda name, **kw: False)
    from pet import agent_locator
    monkeypatch.setattr(agent_locator, "exe_from_link", lambda lnk: r"D:\d\Doubao.exe")
    spawned = []
    monkeypatch.setattr(at, "_spawn", lambda exe: spawned.append(exe) or True)

    goal = at.resolve("豆包")
    assert goal is not None
    assert goal.activate() is True
    assert spawned == [r"D:\d\Doubao.exe"]


def test_returns_none_when_nowhere(monkeypatch):
    monkeypatch.setattr(at.desktop_icon, "locate", lambda hints, use_cache=True: None)
    monkeypatch.setattr(at, "_start_menu_link", lambda name: "")
    assert at.resolve("没有这个应用") is None


def test_blank_name_is_not_a_goal():
    assert at.resolve("") is None
    assert at.resolve("   ") is None


def test_resolve_does_not_open_anything(monkeypatch):
    """解析阶段只许读，不许动手——戏还没开演，界面不能先自己动。"""
    monkeypatch.setattr(at.desktop_icon, "locate", lambda hints, use_cache=True: _Icon())
    monkeypatch.setattr(at, "_start_menu_link", lambda name: r"C:\x\豆包.lnk")
    called = []
    monkeypatch.setattr(at, "open_from_start_menu", lambda *a, **k: called.append(1))
    monkeypatch.setattr(at, "_spawn", lambda exe: called.append(1))
    monkeypatch.setattr(at.desktop_icon, "double_click", lambda x, y: called.append(1))

    at.resolve("豆包")
    assert called == [], "resolve 期间不许弹菜单/双击/起进程"


def test_hints_dedupes_spaces():
    assert at._hints("Deep Seek") == ("Deep Seek", "DeepSeek")
    assert at._hints("豆包") == ("豆包",)
