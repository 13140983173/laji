# -*- coding: utf-8 -*-
"""引擎审批：气泡必须给出可点的【允许/拒绝】。

回归的故障面：引擎在动工具前会停下问一句（run 状态 AWAITING_APPROVAL），
若气泡不渲染这个请求，那一轮就永久卡住，用户只看到「发了没反应」。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from pet.config import Config


def _bubble(tmp_path, request_id: str = "rid-1"):
    from pet.quick_chat import QuickChatBubble

    app = QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(Config(base=tmp_path))
    bubble._active_request_id = request_id
    bubble.laji_service._run_id = "run-1"
    calls: list[tuple[str, str, bool]] = []
    bubble.laji_service.approve = lambda run_id, call_id, approved: calls.append(
        (run_id, call_id, approved)
    )
    return app, bubble, calls


def test_approval_shows_tool_and_reason(tmp_path):
    app, bubble, _calls = _bubble(tmp_path)
    try:
        bubble._approval("rid-1", "call-9", "builtin:run_terminal", "要执行 git status", 30)
        assert not bubble.approval_widget.isHidden()
        text = bubble.approval_label.text()
        assert "运行命令" in text                 # 显示名，不是 builtin:run_terminal
        assert "builtin:" not in text
        assert "要执行 git status" in text
        assert bubble.hint_label.text() == "等你确认"
    finally:
        bubble.close()
        app.processEvents()


def test_approve_button_answers_yes(tmp_path):
    app, bubble, calls = _bubble(tmp_path)
    try:
        bubble._approval("rid-1", "call-9", "builtin:run_terminal", "", 0)
        bubble._answer_approval(True)
        assert calls == [("run-1", "call-9", True)]
        assert bubble.approval_widget.isHidden()
        assert bubble._pending_approval is None
    finally:
        bubble.close()
        app.processEvents()


def test_reject_button_answers_no(tmp_path):
    app, bubble, calls = _bubble(tmp_path)
    try:
        bubble._approval("rid-1", "call-9", "builtin:apply_patch", "", 0)
        bubble._answer_approval(False)
        assert calls == [("run-1", "call-9", False)]
    finally:
        bubble.close()
        app.processEvents()


def test_approval_of_stale_request_is_ignored(tmp_path):
    """上一个请求的审批跑到新请求上，会把用户的【允许】错答给后面的工具。"""
    app, bubble, calls = _bubble(tmp_path)
    try:
        bubble._approval("rid-old", "call-9", "builtin:run_terminal", "", 0)
        assert bubble.approval_widget.isHidden()
        bubble._answer_approval(True)
        assert calls == []
    finally:
        bubble.close()
        app.processEvents()


def test_answering_without_pending_approval_is_noop(tmp_path):
    app, bubble, calls = _bubble(tmp_path)
    try:
        bubble._answer_approval(True)
        assert calls == []
    finally:
        bubble.close()
        app.processEvents()


def test_finished_dismisses_approval(tmp_path):
    """终态后残留的按钮点下去只会是一个空答复。"""
    app, bubble, _calls = _bubble(tmp_path)
    try:
        bubble._approval("rid-1", "call-9", "builtin:run_terminal", "", 0)
        assert not bubble.approval_widget.isHidden()
        bubble._finished("rid-1", "做完了")
        assert bubble.approval_widget.isHidden()
        assert bubble._pending_approval is None
    finally:
        bubble.close()
        app.processEvents()
