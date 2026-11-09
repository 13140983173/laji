# -*- coding: utf-8 -*-
"""「打开应用」演出节奏三档：配置归一 + 设置页 round trip + 档位语义。

三段，对应三种风险：

1. **配置**（无 Qt）：脏值回 ``cinema``、合法值存得住——设置里写着 quick，
   演出引擎却拿不到，是最难查的一类不一致。
2. **档位语义**（无 Qt）：cinema 与加档前逐位相同；quick 只压时长不砍幕；
   silent 不走路不播动作。时间轴口径的断言在 ``test_work_choreo`` 里也有，
   这里补"配置 → 时间轴"这条链。
3. **设置页接线**（真 QApplication + 真对话框）：行落在「自动化与联动」域、
   保存能落盘、子宠页同样可改（这是全局键，不是每宠偏好）。
"""
from __future__ import annotations

import json

import pytest

from pet import config as config_mod
from pet import settings_open_app
from pet import work_choreo as wc

pytest.importorskip("PySide6")


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- 1. 配置
def test_default_pace_is_cinema(tmp_path):
    """默认必须是 cinema：用户没见过这个设置项之前，行为与加档之前一致。"""
    cfg = config_mod.Config(base=tmp_path)
    assert cfg.get("open_app_pace") == wc.PACE_CINEMA


@pytest.mark.parametrize("dirty", ["turbo", "", None, 3, ["quick"], "  "])
def test_dirty_pace_falls_back_to_cinema(tmp_path, dirty):
    """手改 config.json 写进脏值：回默认，不许让演出按未知档走。"""
    base = tmp_path / "config.json"
    base.write_text(json.dumps({"open_app_pace": dirty}), encoding="utf-8")
    cfg = config_mod.Config(base=tmp_path)
    assert cfg.get("open_app_pace") == wc.PACE_CINEMA


@pytest.mark.parametrize("pace", list(wc.PACE_CHOICES))
def test_every_pace_round_trips(tmp_path, pace):
    cfg = config_mod.Config(base=tmp_path)
    cfg.set("open_app_pace", pace)
    cfg.save()
    assert config_mod.Config(base=tmp_path).get("open_app_pace") == pace


def test_config_pace_feeds_the_timeline(tmp_path):
    """配置里的档位 → 演出时间轴（三档各有各的形状）。"""
    cfg = config_mod.Config(base=tmp_path)
    cfg.set("open_app_pace", wc.PACE_SILENT)
    tl = wc.Timeline.for_pace(cfg.get("open_app_pace"))
    assert tl.animate is False and tl.walk is False
    assert tl.pace == wc.PACE_SILENT


# ---------------------------------------------------------------- 2. 设置页
def test_settings_row_lives_in_automation_domain(qapp, tmp_path):
    """「演出节奏」必须落在「自动化与联动」域（与免打扰同域：都是"她别太吵"）。"""
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_widgets import SettingRow

    dialog = ModernSettingsDialog(config_mod.Config(base=tmp_path), include_ai=False)
    try:
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        page = dialog.pages.widget(labels.index("自动化与联动"))
        for key in settings_open_app.ROW_KEYS:
            row = dialog.findChild(SettingRow, f"settingRow_{key}")
            assert row is not None, f"缺少设置行 {key}"
            assert page.isAncestorOf(row), f"{key} 不在「自动化与联动」域里"

        selector = dialog.open_app_pace_select
        assert [selector.itemData(i) for i in range(selector.count())] == list(
            wc.PACE_CHOICES
        ), "下拉项必须与引擎同一份清单（三档、顺序一致）"
        assert selector.currentData() == wc.PACE_CINEMA

        selector.setCurrentIndex(selector.findData(wc.PACE_QUICK))
        settings_open_app.save_open_app_settings(dialog)
        assert dialog.config.get("open_app_pace") == wc.PACE_QUICK
        dialog.config.save()
        assert config_mod.Config(base=tmp_path).get("open_app_pace") == wc.PACE_QUICK
    finally:
        dialog.close()
        qapp.processEvents()


def test_child_slot_page_can_change_pace(qapp, tmp_path):
    """子宠页也能改：这是**全局**键（演出节奏不该因哪只宠而不同），且改了真落盘。"""
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    master = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    child = ModernSettingsDialog(Config(base=tmp_path, instance_id="slot-1"),
                                 include_ai=False)
    try:
        child.open_app_pace_select.setCurrentIndex(
            child.open_app_pace_select.findData(wc.PACE_SILENT)
        )
        assert child._write_config() is True
        on_disk = json.loads(master.config._main.path.read_text(encoding="utf-8"))
        assert on_disk["open_app_pace"] == wc.PACE_SILENT, "子宠页改的键必须真正生效"
    finally:
        for dialog in (master, child):
            dialog.close()
            dialog.deleteLater()
        qapp.processEvents()
