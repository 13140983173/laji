# -*- coding: utf-8 -*-
"""chat_island：她脚边那颗聊天胶囊（三态 / 定位 / 与快速对话的接线）。

纯函数（定位 / 状态字省略）不建窗口；组件与接线走 offscreen 平台，用真实的
``QuickChatBubble`` 验证「右键和她聊天 → 展开 → 发出去 → 收回去报进度」这条链。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

from pet.chat_island import (
    ISLAND_ANIM_MS,
    ISLAND_MARGIN,
    MINI_H,
    MINI_W,
    OPEN_H,
    OPEN_W,
    STATE_HIDDEN,
    STATE_MINI,
    STATE_OPEN,
    ChatIsland,
    fit_status,
    island_geometry,
)

SCREEN = QRect(0, 0, 1920, 1040)
ANCHOR = QRect(1500, 560, 200, 300)          # 右下角的一只宠（脚下还有地方）


def _app():
    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------ 纯函数
class TestGeometry:
    def test_hangs_under_feet_centered(self):
        w, h = MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2
        x, y = island_geometry(ANCHOR, w, h, SCREEN)
        assert x == ANCHOR.center().x() - w // 2
        assert y >= ANCHOR.bottom()

    def test_flips_above_when_no_room_below(self):
        """她坐在任务栏上（脚下没地方）：胶囊必须翻到头顶上面，不能藏栏后。"""
        anchor = QRect(1500, 880, 200, 150)
        w, h = MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2
        _, y = island_geometry(anchor, w, h, SCREEN)
        assert y + h <= anchor.top() + ISLAND_MARGIN

    def test_stays_inside_screen_at_right_edge(self):
        anchor = QRect(1860, 700, 60, 200)
        w, h = OPEN_W + ISLAND_MARGIN * 2, OPEN_H + ISLAND_MARGIN * 2
        x, _ = island_geometry(anchor, w, h, SCREEN)
        assert x + w <= SCREEN.right()

    def test_zero_size_screen_still_returns_pair(self):
        x, y = island_geometry(ANCHOR, 100, 40, QRect(0, 0, 0, 0))
        assert isinstance(x, int) and isinstance(y, int)


class TestFitStatus:
    def test_short_text_untouched(self):
        _app()
        fm = QFontMetrics(QFont())
        assert fit_status("在想了…", fm, 200) == "在想了…"

    def test_long_text_gets_ellipsis(self):
        _app()
        fm = QFontMetrics(QFont())
        out = fit_status("正在把昨晚的构建日志翻一遍挑出报错", fm, 60)
        assert out.endswith("…")
        assert len(out) < len("正在把昨晚的构建日志翻一遍挑出报错")

    def test_blank_collapses_to_empty(self):
        _app()
        fm = QFontMetrics(QFont())
        assert fit_status("   \n ", fm, 200) == ""


# ------------------------------------------------------------ 组件三态
class TestStates:
    def test_starts_hidden(self):
        _app()
        island = ChatIsland()
        try:
            assert island.state == STATE_HIDDEN
            assert not island.isVisible()
        finally:
            island.deleteLater()

    def test_expand_shows_input_and_sets_open(self):
        _app()
        island = ChatIsland()
        try:
            island.expand()
            assert island.state == STATE_OPEN
            assert island.is_open()
            assert island.input.isVisibleTo(island)
            assert island.send_btn.isVisibleTo(island)
        finally:
            island.dismiss()
            island.deleteLater()

    def test_collapse_back_to_mini_clears_input(self):
        _app()
        island = ChatIsland()
        try:
            island.expand()
            island.input.setText("帮我看下构建")
            island.collapse()
            assert island.state == STATE_MINI
            assert island.input.text() == ""
            assert not island.input.isVisibleTo(island)
        finally:
            island.dismiss()
            island.deleteLater()

    def test_dismiss_hides_window(self):
        _app()
        island = ChatIsland()
        try:
            island.expand()
            island.dismiss()
            assert island.state == STATE_HIDDEN
            assert not island.isVisible()
        finally:
            island.deleteLater()

    def test_open_is_idempotent(self):
        _app()
        island = ChatIsland()
        try:
            island.expand()
            size = island.size()
            island.expand()
            assert island.state == STATE_OPEN
            assert island.size() == size
        finally:
            island.dismiss()
            island.deleteLater()

    def test_mini_is_smaller_than_open(self):
        _app()
        island = ChatIsland()
        try:
            island.show_mini()
            mini = island.size()
            island.dismiss()
            island.expand()
            QTest.qWait(ISLAND_ANIM_MS + 80)      # 弹簧动画跑完再量
            opened = island.size()
            assert mini.width() < opened.width()
            assert mini.height() < opened.height()
        finally:
            island.dismiss()
            island.deleteLater()


# ------------------------------------------------------------ 交互
class TestInteractions:
    def test_enter_emits_submitted_text(self):
        _app()
        island = ChatIsland()
        got: list[str] = []
        island.submitted.connect(got.append)
        try:
            island.expand()
            island.input.setText("  帮我把日志发群里  ")
            QTest.keyClick(island.input, Qt.Key.Key_Return)
            assert got == ["帮我把日志发群里"]
        finally:
            island.dismiss()
            island.deleteLater()

    def test_blank_not_submitted(self):
        _app()
        island = ChatIsland()
        got: list[str] = []
        island.submitted.connect(got.append)
        try:
            island.expand()
            island.input.setText("   ")
            QTest.keyClick(island.input, Qt.Key.Key_Return)
            assert got == []
        finally:
            island.dismiss()
            island.deleteLater()

    def test_clicking_mini_expands(self):
        _app()
        island = ChatIsland()
        try:
            island.show_mini()
            QTest.mouseClick(island, Qt.MouseButton.LeftButton, pos=island.rect().center())
            assert island.state == STATE_OPEN
        finally:
            island.dismiss()
            island.deleteLater()

    def test_escape_collapses_and_reports(self):
        _app()
        island = ChatIsland()
        hits: list[int] = []
        island.dismissed.connect(lambda: hits.append(1))
        try:
            island.expand()
            QTest.keyClick(island, Qt.Key.Key_Escape)
            assert island.state == STATE_MINI
            assert hits == [1]
        finally:
            island.dismiss()
            island.deleteLater()

    def test_busy_pulses_only_in_mini(self):
        _app()
        island = ChatIsland()
        try:
            island.show_mini()
            island.set_status("在想了…", busy=True)
            assert island._pulse.isActive()
            island.set_status("说好啦", busy=False)
            assert not island._pulse.isActive()
            island.expand()
            island.set_status("在想了…", busy=True)
            assert not island._pulse.isActive()      # 展开态不脉动（用户在看输入框）
        finally:
            island.dismiss()
            island.deleteLater()

    def test_status_blank_keeps_previous(self):
        _app()
        island = ChatIsland()
        try:
            island.set_status("在做：翻日志")
            island.set_status("")
            assert island._status == "在做：翻日志"
        finally:
            island.dismiss()
            island.deleteLater()


# ------------------------------------------------------------ 与快速对话接线
def _bubble(tmp_path):
    from pet.quick_chat import QuickChatBubble
    from pet.config import Config

    _app()
    bubble = QuickChatBubble(Config(base=tmp_path))
    return bubble


def _teardown(bubble):
    bubble.dismiss_island()
    bubble.close()
    QApplication.processEvents()


def _flow_texts(bubble) -> list[str]:
    """对话流里每一行当前的文字（面板只有一个滚动区，正文都在这里）。"""
    layout = bubble.history_layout
    texts: list[str] = []
    for index in range(layout.count()):
        widget = layout.itemAt(index).widget()
        if widget is None:
            continue
        texts.extend(label.text() for label in widget.findChildren(QLabel))
    return texts


class TestQuickChatWiring:
    def test_open_island_expands_capsule(self, tmp_path):
        bubble = _bubble(tmp_path)
        try:
            bubble.open_island()
            island = bubble.island_widget()
            assert island.state == STATE_OPEN
            assert island.isVisible()
        finally:
            _teardown(bubble)

    def test_show_for_pet_opens_island_not_panel(self, tmp_path):
        """v3 契约：入口是胶囊，面板不许自己冒出来。"""
        bubble = _bubble(tmp_path)
        try:
            bubble.show_for_pet(None)
            assert bubble.island_widget().state == STATE_OPEN
            assert not bubble.isVisible()
        finally:
            _teardown(bubble)

    def test_submit_goes_through_send_and_collapses(self, tmp_path):
        bubble = _bubble(tmp_path)
        sent: list[str] = []
        try:
            bubble._send = lambda: sent.append(bubble.input.text())
            bubble.open_island()
            island = bubble.island_widget()
            island.input.setText("帮我看下今天的告警")
            QTest.keyClick(island.input, Qt.Key.Key_Return)
            assert sent == ["帮我看下今天的告警"]
            assert island.state == STATE_MINI          # 发出去就收回去报进度
        finally:
            _teardown(bubble)

    def test_island_status_appears_as_mini(self, tmp_path):
        bubble = _bubble(tmp_path)
        try:
            bubble.island_status("在做：翻日志", busy=True)
            island = bubble.island_widget()
            assert island.state == STATE_MINI
            assert island.isVisible()
            assert island._status == "在做：翻日志"
        finally:
            _teardown(bubble)

    def test_close_button_dismisses_instead_of_collapsing(self, tmp_path):
        """✕ = 直接关掉（不再收成常驻 mini，所以胶囊不会一直在）。"""
        bubble = _bubble(tmp_path)
        try:
            bubble.open_island()
            island = bubble.island_widget()
            assert island.state == STATE_OPEN
            island.close_btn.click()
            QApplication.processEvents()
            assert island.state == STATE_HIDDEN
            assert not island.isVisible()
        finally:
            _teardown(bubble)

    def test_dismissed_island_does_not_come_back_on_status(self, tmp_path):
        """✕ 关掉后，她下一句状态不得把胶囊再弹回来。"""
        bubble = _bubble(tmp_path)
        try:
            bubble.open_island()
            island = bubble.island_widget()
            island.close_btn.click()
            QApplication.processEvents()

            bubble.island_status("在做：翻日志", busy=True)
            QApplication.processEvents()
            assert island.state == STATE_HIDDEN
            assert not island.isVisible()
            # 状态本身照样记着：下次叫她时就是最新那句
            assert island._status == "在做：翻日志"
            assert bubble._island_hint == "在做：翻日志"
        finally:
            _teardown(bubble)

    def test_calling_her_again_clears_the_close(self, tmp_path):
        bubble = _bubble(tmp_path)
        try:
            bubble.open_island()
            bubble.island_widget().close_btn.click()
            QApplication.processEvents()

            bubble.open_island()
            island = bubble.island_widget()
            assert island.state == STATE_OPEN
            # 叫她之后状态又能正常弹胶囊
            island.collapse()
            bubble.island_status("在做：翻日志", busy=True)
            assert island.state == STATE_MINI
            assert island.isVisible()
        finally:
            _teardown(bubble)

    def test_finished_reports_her_line_on_island(self, tmp_path):
        from pet.mist_bubble import MistBubble

        bubble = _bubble(tmp_path)
        try:
            bubble._active_request_id = "rid-1"
            bubble._finished("rid-1", "喏。缓存清了，1.2 GB，main 推上去了。")
            island = bubble.island_widget()
            assert island.state == STATE_MINI
            assert island._status.startswith("喏。缓存清了")
            assert island._busy is False
        finally:
            MistBubble.instance().dismiss()
            _teardown(bubble)

    def test_work_station_applies_dark_skin(self, tmp_path):
        bubble = _bubble(tmp_path)
        try:
            bubble.open_work_station()
            from pet.quick_chat import WORKSTATION_W

            assert bubble._ws_dark is True
            assert bubble.minimumWidth() == WORKSTATION_W
            assert bubble.isVisible()
        finally:
            _teardown(bubble)

    def test_work_station_keeps_last_reply_in_flow(self, tmp_path):
        """面板里她的回答长在对话流里，不再单独钉在输入框上方（只有一个滑条）。"""
        from pet.mist_bubble import MistBubble

        bubble = _bubble(tmp_path)
        try:
            bubble._active_request_id = "rid-1"
            bubble._finished("rid-1", "喏。缓存清了。")
            bubble.open_work_station()
            assert not bubble.output_scroll.isVisibleTo(bubble)
            assert any("缓存清了" in text for text in _flow_texts(bubble))
        finally:
            MistBubble.instance().dismiss()
            _teardown(bubble)

    def test_work_station_streams_into_flow(self, tmp_path):
        """生成中的那句就长在流尾巴上，收尾定格 —— 上下文与正文共用一个滑条。"""
        from pet.mist_bubble import MistBubble

        bubble = _bubble(tmp_path)
        try:
            bubble.open_work_station()
            bubble._active_request_id = "rid-1"
            bubble._delta("rid-1", "喏。")
            bubble._delta("rid-1", "缓存清了。")
            assert sum("缓存清了" in text for text in _flow_texts(bubble)) == 1
            bubble._finished("rid-1", "喏。缓存清了。")
            assert sum("缓存清了" in text for text in _flow_texts(bubble)) == 1
            assert bubble._stream_row is None
        finally:
            MistBubble.instance().dismiss()
            _teardown(bubble)

    def test_work_station_never_shows_raw_character_id(self, tmp_path):
        """素材包缺失时显示名会回退成角色 id（"shenshen"）——宁可用默认标题。"""
        bubble = _bubble(tmp_path)
        try:
            bubble.open_work_station()
            assert bubble.title_label.text() != bubble.character_id
            assert bubble.title_label.text().strip()
        finally:
            _teardown(bubble)

    def test_laji_task_skips_my_own_question(self, tmp_path):
        """引擎把我那句话原样当任务名报回来：清单里不许长出「✓ 那我是谁」。"""
        from pet.chat.models import ChatMessage

        bubble = _bubble(tmp_path)
        try:
            bubble.session.messages.append(ChatMessage("user", "那我是谁"))
            bubble._active_request_id = "rid-1"
            bubble._laji_task("rid-1", "那我是谁")
            assert bubble._task_rows == []
            assert not bubble.tasks_widget.isVisibleTo(bubble)
            # 她“在做”的提示还是要有：只是不进活清单
            assert "那我是谁" in bubble.hint_label.text()

            bubble._laji_task("rid-1", "翻日志")
            assert [row.text() for row in bubble._task_rows] == ["○ 翻日志"]
        finally:
            _teardown(bubble)

    def test_laji_task_grows_work_list(self, tmp_path):

        bubble = _bubble(tmp_path)
        try:
            bubble._active_request_id = "rid-1"
            bubble._laji_task("rid-1", "翻日志")
            bubble._laji_task("rid-1", "挑报错")
            assert [row.text() for row in bubble._task_rows] == ["○ 翻日志", "○ 挑报错"]
            assert bubble.tasks_widget.isVisibleTo(bubble)

            bubble._mark_tasks_done()
            assert [row.text() for row in bubble._task_rows] == ["✓ 翻日志", "✓ 挑报错"]
        finally:
            _teardown(bubble)

    def test_task_rows_capped(self, tmp_path):
        from pet.quick_chat import WORKSTATION_MAX_TASKS

        bubble = _bubble(tmp_path)
        try:
            bubble._active_request_id = "rid-1"
            for i in range(WORKSTATION_MAX_TASKS + 3):
                bubble._laji_task("rid-1", f"第{i}步")
            assert len(bubble._task_rows) == WORKSTATION_MAX_TASKS
        finally:
            _teardown(bubble)

    def test_new_turn_clears_old_tasks(self, tmp_path):
        bubble = _bubble(tmp_path)
        try:
            bubble._active_request_id = "rid-1"
            bubble._laji_task("rid-1", "翻日志")
            bubble._active_request_id = "rid-2"
            bubble._clear_tasks()
            assert bubble._task_rows == []
            assert not bubble.tasks_widget.isVisibleTo(bubble)
        finally:
            _teardown(bubble)


# ------------------------------------------------------------ 端到端（overlay 壳）
class TestOverlayEndToEnd:
    """从壳的两个入口真跑一遍：和她聊天 → 胶囊；打开小工位 → 面板。"""

    def test_shell_entries_drive_island_and_panel(self, tmp_path):
        from tests.test_overlay_collision_toggle import _make_slot_shell

        shell, _cfg = _make_slot_shell(tmp_path)
        shell.overlay.show()
        try:
            assert shell.quick_chat_available() is True
            assert shell.open_quick_chat(shell.sprite) is True
            bubble = shell._quick_chat
            assert bubble.island_widget().state == STATE_OPEN
            assert not bubble.isVisible()          # 面板不许自己冒出来

            assert shell.open_work_station(shell.sprite) is True
            assert bubble._ws_dark is True
            assert bubble.isVisible()
        finally:
            shell._close_quick_chat()
            shell._delete_runtime_marker()

    def test_close_quick_chat_dismisses_island(self, tmp_path):
        from tests.test_overlay_collision_toggle import _make_slot_shell

        shell, _cfg = _make_slot_shell(tmp_path)
        shell.overlay.show()
        try:
            shell.open_quick_chat(shell.sprite)
            bubble = shell._quick_chat
            island = bubble.island_widget()
            assert island.isVisible()
            shell._close_quick_chat()
            assert not island.isVisible()
        finally:
            shell._delete_runtime_marker()


# ------------------------------------------------------------ 端到端（overlay 壳）
class TestOverlayEndToEnd:
    """从壳的两个入口真跑一遍：和她聊天 → 胶囊；打开小工位 → 面板。"""

    def test_shell_entries_drive_island_and_panel(self, tmp_path):
        from tests.test_overlay_collision_toggle import _make_slot_shell

        shell, _cfg = _make_slot_shell(tmp_path)
        shell.overlay.show()
        try:
            assert shell.quick_chat_available() is True
            assert shell.open_quick_chat(shell.sprite) is True
            bubble = shell._quick_chat
            assert bubble.island_widget().state == STATE_OPEN
            assert not bubble.isVisible()          # 面板不许自己冒出来

            assert shell.open_work_station(shell.sprite) is True
            assert bubble._ws_dark is True
            assert bubble.isVisible()
        finally:
            shell._close_quick_chat()
            shell._delete_runtime_marker()

    def test_close_quick_chat_dismisses_island(self, tmp_path):
        from tests.test_overlay_collision_toggle import _make_slot_shell

        shell, _cfg = _make_slot_shell(tmp_path)
        shell.overlay.show()
        try:
            shell.open_quick_chat(shell.sprite)
            bubble = shell._quick_chat
            island = bubble.island_widget()
            assert island.isVisible()
            shell._close_quick_chat()
            assert not island.isVisible()
        finally:
            shell._delete_runtime_marker()
