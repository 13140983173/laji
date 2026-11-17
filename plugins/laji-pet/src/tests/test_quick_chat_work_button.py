# -*- coding: utf-8 -*-
"""气泡「打工」按钮：把当前输入交给 Laji Agent，没开就负责把它拉起来。

回归的故障面：桌宠此前只能「发消息给引擎」，用户想回到 Laji Agent 的完整界面
（看计划、diff、多任务）时没有出口；而这个出口不能走 ``open_laji_ask``，
后者在 Laji 没运行时直接返回 False，「没开」恰恰是最需要它打开的时候。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet import agent_bridge
from pet.config import Config


def _bubble(tmp_path):
    from pet.quick_chat import QuickChatBubble

    app = QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(Config(base=tmp_path))
    return app, bubble


def test_work_button_sends_input_text_with_force(tmp_path, monkeypatch):
    app, bubble = _bubble(tmp_path)
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        agent_bridge, "open_laji",
        lambda text="", force=False: calls.append((text, force)) or True,
    )
    try:
        bubble.input.setText("  帮我把测试跑一遍  ")
        bubble._open_laji_work()
        assert calls == [("帮我把测试跑一遍", True)]
    finally:
        bubble.close()
        app.processEvents()


def test_work_button_falls_back_when_protocol_missing(tmp_path, monkeypatch):
    """协议没注册：不能变成一个点了没反应的死按钮。"""
    app, bubble = _bubble(tmp_path)
    fell_back: list[bool] = []
    bubble.open_chat_callback = lambda: fell_back.append(True)
    monkeypatch.setattr(agent_bridge, "open_laji", lambda text="", force=False: False)
    try:
        bubble._open_laji_work()
        assert fell_back == [True]
    finally:
        bubble.close()
        app.processEvents()


def test_work_button_is_present_and_named(tmp_path):
    app, bubble = _bubble(tmp_path)
    try:
        assert bubble.work_btn.text() == "打工"
        assert bubble.work_btn.objectName() == "quick-chat-work"
    finally:
        bubble.close()
        app.processEvents()
