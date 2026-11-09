# -*- coding: utf-8 -*-
"""设置页「消息中心」：审批卡版式行挂在「自动化与联动」域、保存写规范键。"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pet import settings_approval


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_dirty_config_value_loads_as_default(qapp, tmp_path):
    """config 里写错值：下拉显示默认档（normalize 兜底），别让下拉空着。"""
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog, SettingRow

    cfg = Config(base=tmp_path)
    cfg.set("approval_card_style", " nonsense ")
    dialog = ModernSettingsDialog(cfg, include_ai=False)
    try:
        selector = dialog.approval_card_style_select
        assert selector.currentData() == "glass"
        assert len(settings_approval.ROW_KEYS) == 1
        row = dialog.findChild(SettingRow, "settingRow_approval_card_style")
        assert row is not None
        labels = [dialog.sidebar.item(i).text() for i in range(dialog.sidebar.count())]
        page = dialog.pages.widget(labels.index("自动化与联动"))
        assert page.isAncestorOf(row), "版式行要挂在「自动化与联动」域"
    finally:
        dialog.close()
        qapp.processEvents()


def test_save_round_trips_focus_style(qapp, tmp_path):
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        selector = dialog.approval_card_style_select
        selector.setCurrentIndex(selector.findData("focus"))
        settings_approval.save_approval_settings(dialog)
        assert dialog.config.get("approval_card_style") == "focus"
        dialog.config.save()
        from pet.config import Config as _C
        assert _C(base=tmp_path).get("approval_card_style") == "focus"
    finally:
        dialog.close()
        qapp.processEvents()


def test_save_normalizes_dirty_selection(qapp, tmp_path):
    """下拉的 data 理论上只可能是规范键；万一被塞脏值，落盘前兜回默认。"""
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    dialog = ModernSettingsDialog(Config(tmp_path), include_ai=False)
    try:
        selector = dialog.approval_card_style_select
        selector.addItem("脏数据", "weird")
        selector.setCurrentIndex(selector.findData("weird"))
        settings_approval.save_approval_settings(dialog)
        assert dialog.config.get("approval_card_style") == "glass"
    finally:
        dialog.close()
        qapp.processEvents()


def test_overlay_shell_picks_up_focus_style_from_config(tmp_path, monkeypatch):
    """保存之后壳层下一轮同步就该换版式（不用重启）。"""
    from pet.config import Config
    from pet import overlay_shell as ovs

    cfg = Config(base=tmp_path)
    cfg.set("approval_card_style", "focus")
    shell = ovs.OverlayShell.__new__(ovs.OverlayShell)
    shell._config = cfg  # 壳层读 _config（不缓存，每轮同步读一次）
    assert shell._approval_card_style() == "focus"
