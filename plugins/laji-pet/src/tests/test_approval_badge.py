# -*- coding: utf-8 -*-
"""头顶消息中心（A 方案）：裸 logo 待机 → 胶囊通报 → 审批卡。

徽章只是视图——表在壳上，动作走回调。这里测的就是这几条：待机/通报/展开三态怎么
切换、条目怎么显示、点下去把哪个 run 交给谁。
"""
from __future__ import annotations

import os
import time
from dataclasses import replace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtWidgets import QApplication, QPushButton

from pet.agent_link.pending_approval import PendingApproval
from pet.approval_badge import (
    MAX_ROWS,
    ApprovalBadge,
    _FocusCard,
    _GlassCard,
    normalize_card_style,
    remaining_secs,
)

app = QApplication.instance() or QApplication([])


def _entry(
    run_id: str, *, with_approval: bool = True, timeout_secs: int = 0
) -> dict:
    approval = None
    if with_approval:
        approval = PendingApproval(
            run_id=run_id,
            call_id=f"call-{run_id}",
            tool_name="builtin:run_terminal",
            reason="shell command not in allow list",
            timeout_secs=timeout_secs,
        )
    return {
        "run_id": run_id,
        "workspace": "D:\\proj",
        "message": "Laji 那边等你拍板",
        "approval": approval,
    }


def test_empty_table_disappears_entirely():
    """干净 = 整个消失（2026-11-02 实机口径）：审批做完还挂白泡像「还有事」。"""
    badge = ApprovalBadge()
    badge.set_entries([])
    assert badge.count == 0
    assert not badge.isVisible(), "没跟到她之前不落点"

    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    badge.set_entries([_entry("run-1")])
    assert badge.isVisible(), "有待办才出现"

    badge.set_entries([])
    assert not badge.isVisible(), "清空后连 logo 一起消失"
    assert not badge._logo.isVisible()
    assert not badge.is_open

    badge.toggle()
    assert not badge.is_open, "没条目不许摊空卡"


def test_badge_counts_and_folds_out_a_card():
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    badge.set_entries([_entry("run-1"), _entry("run-2")])

    assert badge.count == 2
    assert badge._logo._count.text() == "2"
    assert badge._logo._hot, "有待办时 logo 转金色"
    assert not badge.is_open, "折叠态：只占一枚记号"

    badge.toggle()
    assert badge.is_open
    badge.collapse()
    assert not badge.is_open


def test_fresh_entry_flashes_a_capsule():
    """新条目先弹胶囊报一声；点它当场摊开卡片，不等 2.5s。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 600, 120, 80))

    badge.set_entries([_entry("run-1")])
    assert badge._capsule_on, "新条目要先报一声"
    assert "要用" in badge._cap_text.text()
    assert badge._cap_count.text() == "1"

    badge.toggle()
    assert badge.is_open
    assert not badge._capsule_on, "展开卡片就收起通报"

    # 通报计时器到点：缩回待机 logo，不把胶囊留在头顶。
    badge.collapse()
    badge._on_capsule_timeout()
    assert not badge._capsule_on
    assert badge._logo.isVisible()


def test_refresh_with_same_entries_does_not_re_announce():
    """整表刷新但条目没变：不再弹胶囊，别每 7 秒骚扰一次。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    badge.set_entries([_entry("run-1")])
    assert badge._capsule_on

    badge._on_capsule_timeout()
    badge.set_entries([_entry("run-1")])
    assert not badge._capsule_on, "同一条目重新同步不算新消息"


def test_open_workstation_takes_the_badge_away():
    """工位开着归左栏页：徽章整体收起，也不能被点开。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    badge.set_entries([_entry("run-1")])
    badge.toggle()
    assert badge.is_open

    badge.set_suspended(True)
    assert not badge.is_open
    assert not badge.isVisible()

    badge.toggle()
    assert not badge.is_open, "收起期间点不开（入口在工位那边）"

    badge.set_suspended(False)
    assert badge.isVisible(), "工位关掉就回到她头顶"


def test_long_list_folds_the_rest_towards_the_workstation():
    badge = ApprovalBadge()
    badge.set_entries([_entry(f"run-{i}") for i in range(MAX_ROWS + 2)])
    badge.toggle()

    # 玻璃卡：行对象挂在卡上（行之间还插了 1px 分隔线，不能按布局项数算）。
    assert len(badge._card._rows) == MAX_ROWS
    assert f"还有 2 条" in badge._card._rest.text()


def test_card_grows_when_more_rows_arrive():
    """先 1 条再变 3 条：卡片要当场长高，不能沿用上一回的高度把行叠在一起。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 900, 120, 80))
    badge.set_entries([_entry("run-1")])
    badge.toggle()
    short = badge.height()

    badge.set_entries([_entry(f"run-{i}") for i in range(3)])

    assert badge.height() > short
    assert badge._card.height() == badge.height()


def test_buttons_hand_back_that_runs_id():
    calls: list[tuple] = []
    badge = ApprovalBadge(
        on_resolve=lambda run_id, ok: calls.append(("resolve", run_id, ok)),
        on_locate=lambda run_id: calls.append(("locate", run_id)),
    )
    badge.set_entries([_entry("run-7")])
    badge.toggle()

    row = badge._card._rows[0]
    buttons = {btn.text(): btn for btn in row.findChildren(QPushButton)}
    buttons["允许"].click()
    buttons["拒绝"].click()
    # 「在会话里看」收在卡底栏（一条逃逸口，不是每行一个）
    foot = {btn.text(): btn for btn in badge._card.findChildren(QPushButton)}
    foot["在会话里看"].click()

    assert calls == [
        ("resolve", "run-7", True),
        ("resolve", "run-7", False),
        ("locate", "run-7"),
    ]


def test_quiet_entry_only_offers_the_way_to_the_session():
    """探不到未决审批时只能提醒：这时不该给一个按下去必然失败的「允许」。"""
    badge = ApprovalBadge()
    badge.set_entries([_entry("run-9", with_approval=False)])
    badge.toggle()

    row = badge._card._rows[0]
    assert [btn.text() for btn in row.findChildren(QPushButton)] == [], "没有审批就没有动作按钮"
    # 「在会话里看」收在卡底栏，仍然够得着那条会话。
    foot = [btn.text() for btn in badge._card.findChildren(QPushButton)]
    assert "在会话里看" in foot


def test_anchor_vanishing_hides_the_badge():
    """她隐了（全屏自动隐藏/换宠）：徽章不能留在原地当幽灵；她回来要跟着回来。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    badge.set_entries([_entry("run-1")])
    assert badge.isVisible()

    badge.set_anchor_rect(QRect())
    assert not badge.isVisible()

    badge.set_anchor_rect(QRect(500, 600, 120, 80))
    assert badge.isVisible(), "她回来了徽章也要回来"


def test_badge_hangs_at_her_side():
    """审批族挂她身侧（右为默认），头顶正上方让给聊天对白（2026-11-02 口径）。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(60, 600, 120, 80))
    badge.set_entries([_entry("run-1")])
    badge._on_capsule_timeout()  # 通报缩回，量的是待机 logo

    geo = badge.geometry()
    assert geo.left() == 179 - 6, "logo 右缘贴她身体右缘（略微压进身沿）"
    assert 600 <= geo.top() < 680, "挂在头侧（身体上沿往下 ~1/4 处）"

    badge.toggle()
    card = badge.geometry()
    assert card.left() == 179 + 18, "展开卡挂身侧，与身体留一手掌宽"
    assert card.bottom() <= 600, "卡的底边略高于她的头顶，不压脸"


def test_side_flips_left_when_right_is_crowded():
    """右边顶到屏幕边：整族翻到她左侧，别把卡片挤出屏幕。"""
    badge = ApprovalBadge()
    badge.set_anchor_rect(QRect(1880, 600, 120, 80))
    badge.set_entries([_entry("run-1")])

    geo = badge.geometry()
    assert geo.right() <= 1880 + 6, "翻到她左侧"
    assert geo.left() >= 4, "不出屏"


# ---------------------------------------------------------------- 两套版式
def test_style_defaults_to_glass_and_typos_fall_back():
    """配置写错字（glasss / B / focus-mode）一律回默认，别变成第三种卡。"""
    assert ApprovalBadge().card_style == "glass"
    assert normalize_card_style("glass") == "glass"
    assert normalize_card_style("FOCUS") == "focus"
    assert normalize_card_style("glasss") == "glass"
    assert normalize_card_style(None) == "glass"


def test_focus_style_asks_one_at_a_time():
    """E 版式：一次只摊一张，翻页换人，按下去的才是当前这条的 run。"""
    calls: list[tuple] = []
    badge = ApprovalBadge(
        style="focus",
        on_resolve=lambda run_id, ok: calls.append((run_id, ok)),
        on_locate=lambda run_id: calls.append(("locate", run_id)),
    )
    badge.set_anchor_rect(QRect(60, 600, 120, 80))
    badge.set_entries([_entry("run-1"), _entry("run-2"), _entry("run-3")])
    badge.toggle()

    card = badge._card
    assert isinstance(card, _FocusCard)
    assert card._pager.text() == "1 / 3"
    assert "运行命令" in card._title.text()

    card._yes.click()
    assert calls == [("run-1", True)]

    card.step(1)
    assert card._pager.text() == "2 / 3"
    card._no.click()
    assert calls[-1] == ("run-2", False)

    card.step(-1)  # 回到第一条
    assert card._pager.text() == "1 / 3"


def test_focus_pager_wraps_and_hides_for_one_entry():
    badge = ApprovalBadge(style="focus")
    badge.set_anchor_rect(QRect(60, 600, 120, 80))
    badge.set_entries([_entry("run-1"), _entry("run-2")])
    badge.toggle()
    card = badge._card
    card.step(-1)  # 第一条再往前 = 绕到最后一条
    assert card._pager.text() == "2 / 2"

    badge.set_entries([_entry("run-1")])
    assert not card._prev.isVisible(), "只有一条时翻页器不占地方"
    assert not card._pager.isVisible()


def test_switching_style_swaps_the_card_in_place():
    """配置在运行期被改：摊开着的卡当场换版式，不该把用户正在看的卡收掉。"""
    badge = ApprovalBadge()
    badge.set_entries([_entry("run-1")])
    badge.toggle()
    assert isinstance(badge._card, _GlassCard)

    badge.set_style("focus")
    assert badge.card_style == "focus"
    assert isinstance(badge._card, _FocusCard)
    assert badge.is_open, "切换版式不该连带收起"

    badge.set_style("glass")
    assert isinstance(badge._card, _GlassCard)
    assert badge.is_open


def test_glass_card_never_offers_a_blanket_approve():
    """玻璃卡底栏不给「全部允许」：这里混着不同 run，一键放行可能顺带批掉一条命令。"""
    badge = ApprovalBadge()
    badge.set_entries([_entry("run-1"), _entry("run-2")])
    badge.toggle()
    texts = [btn.text() for btn in badge._card.findChildren(QPushButton)]
    assert not any("全部" in text for text in texts)


def test_countdown_is_derived_from_timeout():
    """daemon 只给总时长：按「第一次见到它」近似剩余；没时长就不显示倒计时。"""
    entry = _entry("run-1", timeout_secs=30)
    entry["seen_at"] = time.monotonic() - 12
    left = remaining_secs(entry)
    assert left is not None and 17 <= left <= 18
    assert remaining_secs(_entry("run-2")) is None, "拿不到时长就别画假的"


def test_glass_row_shows_the_countdown_only_with_a_timeout():
    badge = ApprovalBadge()
    badge.set_entries([_entry("run-1", timeout_secs=30)])
    badge.toggle()
    assert not badge._card._rows[0]._cd.isHidden()

    badge.set_entries([_entry("run-2")])
    assert badge._card._rows[0]._cd.isHidden()


def _question_entry(run_id: str, *, options=(("a", "北京"), ("b", "上海"), ("c", "成都"))) -> dict:
    return {
        "run_id": run_id,
        "workspace": "D://proj",
        "message": "Laji 那边问你：你在哪个城市？",
        "approval": PendingApproval(
            run_id=run_id,
            call_id=f"call-{run_id}",
            question="你在哪个城市？",
            options=options,
        ),
    }


def test_glass_question_row_offers_option_buttons_and_skip():
    """选择题行：题面当标题、选项按钮直接作答、跳过走 skipped。"""
    calls: list[tuple] = []
    badge = ApprovalBadge(
        on_resolve=lambda rid, ok, answer="", skipped=False: calls.append((rid, ok, answer, skipped)),
    )
    badge.set_entries([_question_entry("run-q")])
    badge.toggle()

    row = badge._card._rows[0]
    buttons = [b for b in row.findChildren(QPushButton) if b.objectName() == "glass-opt"]
    labels = [b.text() for b in buttons]
    assert "北京" in labels and "跳过这题" in labels
    assert not [b for b in row.findChildren(QPushButton) if b.text() in ("允许", "拒绝")]

    next(b for b in buttons if b.text() == "北京").click()
    next(b for b in buttons if b.text() == "跳过这题").click()
    assert calls == [("run-q", True, "北京", False), ("run-q", False, "", True)]


def test_focus_question_renders_full_width_options():
    calls: list[tuple] = []
    badge = ApprovalBadge(
        on_resolve=lambda rid, ok, answer="", skipped=False: calls.append((rid, ok, answer, skipped)),
        style="focus",
    )
    badge.set_entries([_question_entry("run-q")])
    badge.toggle()

    card = badge._card
    assert card._title.text() == "你在哪个城市？"
    assert not card._no.isVisible() and not card._yes.isVisible()
    buttons = [b for b in card.findChildren(QPushButton) if b.objectName() == "glass-opt"]
    assert {b.text() for b in buttons} == {"北京", "上海", "成都", "跳过这题"}

    next(b for b in buttons if b.text() == "成都").click()
    assert calls == [("run-q", True, "成都", False)]


def test_question_with_no_options_points_to_the_session():
    """多步向导 pet 答不全：不铺选项按钮，只留去会话里答。"""
    badge = ApprovalBadge()
    entry = _question_entry("run-q", options=())
    badge.set_entries([entry])
    badge.toggle()

    from PySide6.QtWidgets import QLabel

    row = badge._card._rows[0]
    assert [b for b in row.findChildren(QPushButton) if b.objectName() == "glass-opt"] == []
    notes = [w.text() for w in row.findChildren(QLabel) if "会话里答" in w.text()]
    assert notes, "要指路去会话里答"
    # 没有可点选项时不该有「允许/拒绝」
    assert not [b for b in row.findChildren(QPushButton) if b.text() in ("允许", "拒绝")]


def test_option_overflow_points_to_the_session():
    """超过 MAX_OPTIONS 的选项不铺：给一句「还有 N 个选项」。"""
    many = tuple((str(i), f"选项{i}") for i in range(9))
    badge = ApprovalBadge()
    badge.set_entries([_question_entry("run-q", options=many)])
    badge.toggle()

    labels = [
        b.text() for b in badge._card._rows[0].findChildren(QPushButton)
        if b.objectName() == "glass-opt"
    ]
    assert len(labels) == 7  # 6 个选项 + 跳过
    assert "选项6" not in labels


def _custom_question_entry(run_id: str) -> dict:
    entry = _question_entry(run_id)
    entry["approval"] = replace(entry["approval"], allow_custom=True)
    return entry


def test_custom_answer_inline_input():
    """allow_custom：铺一颗「其他…」，点了原地换输入框，回车把自拟答案交回去。"""
    from PySide6.QtWidgets import QLineEdit

    calls: list[tuple] = []
    badge = ApprovalBadge(
        on_resolve=lambda rid, ok, answer="", skipped=False: calls.append((rid, ok, answer, skipped)),
    )
    badge.set_entries([_custom_question_entry("run-q")])
    badge.toggle()

    row = badge._card._rows[0]
    buttons = [b for b in row.findChildren(QPushButton) if b.objectName() == "glass-opt"]
    other = next(b for b in buttons if b.text() == "其他…")
    edits = row.findChildren(QLineEdit)
    assert edits and edits[0].isHidden()

    other.click()
    edit = edits[0]
    assert not edit.isHidden() and other.isHidden()

    edit.setText("自定义答案")
    edit.returnPressed.emit()
    assert calls == [("run-q", True, "自定义答案", False)]


def test_custom_answer_escape_restores_the_button():
    """Esc 反悔：输入框收回，「其他…」回来，不交卷。"""
    from PySide6.QtWidgets import QLineEdit

    calls: list[tuple] = []
    badge = ApprovalBadge(
        on_resolve=lambda rid, ok, answer="", skipped=False: calls.append((rid, ok, answer, skipped)),
    )
    badge.set_entries([_custom_question_entry("run-q")])
    badge.toggle()

    row = badge._card._rows[0]
    other = next(b for b in row.findChildren(QPushButton) if b.text() == "其他…")
    other.click()
    edit = row.findChildren(QLineEdit)[0]
    from pet.approval_badge import _AnswerEdit

    assert isinstance(edit, _AnswerEdit)
    edit.setText("半截话")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not other.isHidden() and edit.isHidden()
    assert calls == [], "Esc 不该交卷"

    other.click()  # 反悔后还能再点开
    assert not row.findChildren(QLineEdit)[0].isHidden()


def test_long_options_elided_inside_fixed_card():
    """长选项截断到列宽以内（tooltip 留全文），不再把 372 定宽卡撑破。"""
    from PySide6.QtWidgets import QLineEdit, QSizePolicy

    long_label = "一张（大标题 + 全宽按钮 + 倒计时进度条 + 底部翻页器）超长选项文案"
    badge = ApprovalBadge()
    badge.set_entries([_question_entry("run-q", options=(("a", long_label), ("b", "短选项")))])
    badge.toggle()

    row = badge._card._rows[0]
    buttons = [b for b in row.findChildren(QPushButton) if b.objectName() == "glass-opt"]
    long_btn = next(b for b in buttons if b.text() != "短选项" and b.text() != "跳过这题")
    assert long_btn.text() != long_label, "长文案要截断，别原样塞进去"
    assert long_btn.toolTip() == long_label
    assert long_btn.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Expanding
    # 两列 + 间距收在卡内：每颗按钮 sizeHint 不超过半张卡
    col_w = (372 - 38 - 6) // 2
    assert long_btn.sizeHint().width() <= col_w + 4
