# -*- coding: utf-8 -*-
"""设置页「打开应用」：**她替你打开应用时的演出节奏**（三档）。

**为什么单独一个模块**：``modern_settings_dialog.py`` 的行数预算已反复触顶，
本组控件/行/保存照 ``settings_quiet`` 的先例搬出来，那边只留一句接线。

**为什么这是设置项而不是右键菜单项**（``docs/SETTINGS-CHANGE-GATES.md`` 准入）：
它是**长期偏好**——"她平时多吵"是稳定的个人口味，不是"这一次快一点"的一次性命令；
低频、跨任务；默认值安全（``cinema`` = 加档之前的老行为，逐位不变）；归属唯一
（「自动化与联动」域，与「免打扰」同域：都是"她别太吵"的旋钮）；产品无法替用户
推断"我现在想不想看这一出"；契约完整（无平台差异、无外部依赖、立即保存）。

档位清单与文案**只有一份**（``work_choreo.PACE_CHOICES / PACE_LABELS / PACE_HINTS``）：
演出引擎、设置页下拉、配置清洗三处共用，不会出现"设置里写着快节奏，演出来是完整的"。
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox

from .config import DEFAULT_OPEN_APP_PACE, normalize_open_app_pace
from .settings_widgets import SettingRow
from .work_choreo import PACE_CHOICES, PACE_LABELS

#: 设置行 objectName 键（``settingRow_<key>``），测试与搜索按它定位。
ROW_KEYS = ("open_app_pace",)


def create_open_app_controls(dialog) -> None:
    """建档位下拉（幂等：域重建会再调一次）。"""
    existing = getattr(dialog, "open_app_pace_select", None)
    if existing is not None:
        return
    selector = QComboBox(dialog)
    selector.setObjectName("openAppPaceSelect")
    for pace in PACE_CHOICES:
        selector.addItem(PACE_LABELS.get(pace, pace), pace)
    current = normalize_open_app_pace(
        dialog.config.get("open_app_pace", DEFAULT_OPEN_APP_PACE)
    )
    index = selector.findData(current)
    selector.setCurrentIndex(index if index >= 0 else 0)
    dialog.open_app_pace_select = selector


def _current_pace(dialog) -> str:
    selector = getattr(dialog, "open_app_pace_select", None)
    if selector is None:
        return DEFAULT_OPEN_APP_PACE
    return normalize_open_app_pace(selector.currentData())


def build_open_app_rows(dialog) -> list[SettingRow]:
    """「打开应用」小节的行（由「自动化与联动」域直接取用，不走 claim）。"""
    create_open_app_controls(dialog)
    return [
        SettingRow(
            ROW_KEYS[0],
            "演出节奏",
            "你说「帮我打开 豆包」时，她找过去、按下、再等开门的这一套演多快："
            "完整演出会走过去并按给你看（约 5~8 秒）；快节奏幕序不变但每幕压短"
            "（约 2~3 秒）；安静不演不走路也不播动作，直接把应用点亮，只留"
            "「点它」和「开好啦」两句气泡（约 1 秒）。已经开着的东西一律只"
            "叫到前台，任何档位都不会开第二个窗口。",
            dialog.open_app_pace_select,
        ),
    ]


def save_open_app_settings(dialog) -> None:
    """把选择写回 config（控件未创建时无操作，兼容裁剪过的对话框）。"""
    selector = getattr(dialog, "open_app_pace_select", None)
    if selector is None:
        return
    dialog.config.set("open_app_pace", _current_pace(dialog))
