# -*- coding: utf-8 -*-
"""角色卡上的人设编辑（`pet/persona_dialog.py`）的回归测试。

盯三件事：真值仍是 ``pet_persona_overrides[角色 id]``、留空 = 回落出厂（键要删掉、
不是写空串）、保存必须落盘（只改内存 = 用户以为存了）。
"""
from __future__ import annotations

import pytest

from pet import persona_dialog as pd_mod


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


class _Config:
    def __init__(self, **values) -> None:
        self.values = dict(values)
        self.saves = 0
        self.reloads = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def reload(self):
        self.reloads += 1
        return True

    def save(self):
        self.saves += 1
        return True


def test_save_persona_keeps_one_entry_per_character():
    config = _Config(pet_persona_overrides={"shenshen": "叫我老板。"})
    assert pd_mod.save_persona(config, "catgirl-gemini", "  你是小满。  ") is True

    assert config.values["pet_persona_overrides"] == {
        "shenshen": "叫我老板。",          # 别的角色那份不许被冲掉
        "catgirl-gemini": "你是小满。",    # 前后空白去掉再存
    }
    assert config.saves == 1, "必须落盘，不能只改内存"
    assert config.reloads == 1, "写盘前要重读，别回滚主进程刚写的键"


def test_blank_persona_drops_the_key_instead_of_storing_empty_string():
    """留空 = 回落出厂人设：留着空串会让「自定义」状态一直亮着。"""
    config = _Config(pet_persona_overrides={"shenshen": "叫我老板。"})
    assert pd_mod.save_persona(config, "shenshen", "   ") is True
    assert config.values["pet_persona_overrides"] == {}


def test_state_label_reflects_override_presence():
    """只有改过才给一句话；没改过（出厂）不往卡片上掛说明。"""
    empty = _Config()
    filled = _Config(pet_persona_overrides={"shenshen": "叫我老板。"})
    assert pd_mod.persona_state_label(empty, "shenshen") == ""
    assert pd_mod.persona_state_label(filled, "shenshen") == "人设 · 自定义"
    assert pd_mod.persona_state_label(filled, "catgirl-gemini") == ""


def test_dialog_prefills_and_writes_back(qapp):
    config = _Config(pet_persona_overrides={"shenshen": "叫我老板。"})
    dialog = pd_mod.PersonaDialog(config, "shenshen")
    try:
        assert dialog.persona_value() == "叫我老板。"
        dialog._edit.setPlainText("叫我大老板，说话短一点。")
        dialog._on_save()
        assert config.values["pet_persona_overrides"]["shenshen"] == "叫我大老板，说话短一点。"
        assert config.saves == 1
    finally:
        dialog.deleteLater()


def test_reset_button_clears_back_to_factory(qapp):
    config = _Config(pet_persona_overrides={"shenshen": "叫我老板。"})
    dialog = pd_mod.PersonaDialog(config, "shenshen")
    try:
        dialog._reset_btn.click()
        assert dialog.persona_value() == ""
        dialog._on_save()
        assert "shenshen" not in config.values["pet_persona_overrides"]
    finally:
        dialog.deleteLater()
