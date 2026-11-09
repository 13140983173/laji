# -*- coding: utf-8 -*-
"""设置页「消息中心」：Laji 审批卡版式（glass 玻璃分段 / focus 一次一张）。

**为什么单独一个模块**：``modern_settings_dialog.py`` 行数预算无余量，本组控件
与行在此构建（与 ``settings_quiet`` 同口径：本模块建控件与行，对话框只接线，
行不进该文件的 ``all_rows`` 快照、不走 claim）。

**语义**：改的是 ``config.json`` 的 ``approval_card_style``；徽章的版式由壳层
每一轮审批同步（≤7s）读取对齐——保存后不用重启桌宠，下次头顶冒卡就是新版式。
版式定义见 ``approval_badge``（``normalize_card_style`` 负责把写错的值兜回默认）。
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from .approval_badge import CARD_STYLES, DEFAULT_CARD_STYLE, normalize_card_style
from .settings_widgets import SettingRow

#: 设置行 objectName 键（``settingRow_<key>``），测试与搜索按它定位。
ROW_KEYS = ("approval_card_style",)

#: 下拉项文案（data 存规范键，QSS/翻译都不碰它）。
_STYLE_LABELS = (
    (DEFAULT_CARD_STYLE, "玻璃分段（整表摊开）"),
    ("focus", "一次一张（大按钮翻页）"),
)


def create_approval_controls(dialog) -> None:
    """创建版式下拉（幂等：域重建会再调一次）。"""
    if getattr(dialog, "approval_card_style_select", None) is not None:
        return
    selector = QComboBox(dialog)
    selector.setObjectName("approvalCardStyleSelect")
    for value, label in _STYLE_LABELS:
        selector.addItem(label, value)
    current = normalize_card_style(dialog.config.get("approval_card_style", DEFAULT_CARD_STYLE))
    index = selector.findData(current)
    selector.setCurrentIndex(index if index >= 0 else 0)
    dialog.approval_card_style_select = selector


def build_approval_rows(dialog) -> list[SettingRow]:
    """「消息中心」小节（由「自动化与联动」域直接取用，不走 claim）。"""
    create_approval_controls(dialog)
    return [
        SettingRow(
            ROW_KEYS[0],
            "Laji 审批卡版式",
            "她在 Laji 那边卡住等你拍板时，头顶消息中心摊开的那种卡："
            "玻璃分段把所有待批一条一行铺开；一次一张只露一条，"
            "大按钮 + 底部翻页。保存后最多 7 秒生效，不用重启。",
            dialog.approval_card_style_select,
        ),
    ]


def save_approval_settings(dialog) -> None:
    """把版式写回 config（控件未创建时无操作）。"""
    selector = getattr(dialog, "approval_card_style_select", None)
    if selector is None:
        return
    value = str(selector.currentData() or DEFAULT_CARD_STYLE)
    # 写规范键：写错值壳层会兜回默认，但落盘前就在这里规范掉更干净。
    dialog.config.set("approval_card_style", value if value in CARD_STYLES else DEFAULT_CARD_STYLE)
