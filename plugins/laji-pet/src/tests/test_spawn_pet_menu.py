# -*- coding: utf-8 -*-
"""右键「再来一只」：改名 + 生成时能挑角色的行为契约。

用户口径（2026-10 实机）：「不应该是小肥鱼，应该是再来一只？然后可以选择角色，
现在默认是大肥鱼不好」——所以：

1. 菜单文案＝「再来一只」（``registry.ACTION_LABELS`` 与 ``shared`` 同一处）；
2. 有 ≥2 个角色时摊成二级菜单：首项「跟当前一样」保持继承主宠的旧行为，
   其余按角色清单逐条列出，点谁就以谁生成；
3. 只有一个角色／清单读不出来时退化回单项动作（右键菜单不多加一层）；
4. 角色参数一路透传到 overlay 的建 sprite 路径，建完复位。
"""
from __future__ import annotations

import types

import pytest
from PySide6.QtWidgets import QApplication, QMenu

from pet import catalog
from pet import overlay_shell as ov_mod
from pet.context_menus import registry as registry_mod
from pet.context_menus import shared as shared_mod


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


class _Cfg:
    def __init__(self, values: dict | None = None):
        self._values = dict(values or {})

    def get(self, key, default=None):
        return self._values.get(key, default)


class _Pet:
    """最小宿主：只提供菜单构建需要的 on_spawn_pet / cfg。"""

    def __init__(self, character: str = catalog.DEFAULT_CHARACTER):
        self.cfg = _Cfg({"character": character})
        self.spawned: list = []

    def on_spawn_pet(self, character_id=None):
        self.spawned.append(character_id)


def _spawn_submenu(menu: QMenu) -> QMenu:
    for action in menu.actions():
        if action.text() == shared_mod.SPAWN_PET_LABEL and action.menu() is not None:
            return action.menu()
    raise AssertionError("菜单里没有「再来一只」二级菜单")


def test_spawn_label_is_relying_on_one_name(app):
    assert shared_mod.SPAWN_PET_LABEL == "再来一只"
    assert registry_mod.ACTION_LABELS["spawn_pet"] == "再来一只"


def test_submenu_lists_every_character_and_passes_it_back(app, monkeypatch):
    monkeypatch.setattr(catalog, "list_available_characters",
                        lambda: ["shenshen", "catgirl-gemini"])
    pet = _Pet()
    menu = QMenu()
    shared_mod.add_spawn_pet(menu, pet)
    submenu = _spawn_submenu(menu)
    labels = [a.text() for a in submenu.actions() if not a.isSeparator()]
    assert labels == ["跟当前一样",
                      catalog.character_call_name("shenshen"),
                      catalog.character_call_name("catgirl-gemini")]
    assert labels[:2] == ["跟当前一样", "大肥鱼"]

    # 「跟当前一样」= 旧行为：不带角色
    submenu.actions()[0].trigger()
    assert pet.spawned == [None]

    # 角色项 = 带角色生成
    [a for a in submenu.actions()
     if a.text() == catalog.character_call_name("catgirl-gemini")][0].trigger()
    assert pet.spawned == [None, "catgirl-gemini"]
    menu.close()
    app.processEvents()


def test_single_character_keeps_flat_action(app, monkeypatch):
    monkeypatch.setattr(catalog, "list_available_characters", lambda: ["shenshen"])
    pet = _Pet()
    menu = QMenu()
    action = shared_mod.add_spawn_pet(menu, pet)
    assert action is not None and action.menu() is None
    assert action.text() == "再来一只"
    action.trigger()
    assert pet.spawned == [None]
    menu.close()
    app.processEvents()


def test_broken_inventory_degrades_to_flat_action(app, monkeypatch):
    def boom():
        raise OSError("characters dir unreadable")

    monkeypatch.setattr(catalog, "list_available_characters", boom)
    pet = _Pet()
    menu = QMenu()
    action = shared_mod.add_spawn_pet(menu, pet)
    assert action is not None and action.menu() is None
    menu.close()
    app.processEvents()


class _OverlayStub:
    """OverlayShell.spawn_pet 的外部依赖面（身份分配/落盘/托盘重建）。"""

    def __init__(self):
        self.built: list = []
        self._remembered_active: list = []

    def _spawn_config_dir(self):
        return None

    def _active_slots(self):
        return set()

    def _spawn_slot(self, slot):
        self.built.append((slot, getattr(self, "_spawn_character_override", "missing")))

    def _slot_config_signatures(self):
        return {}

    def _persist_active_slots(self):
        pass

    def _refresh_tray_menu(self):
        pass

    def _sync_alert_copy(self):
        pass

    def _notify_spawn_failed(self, slot, exc):
        raise AssertionError(f"不应失败: {exc}")


def test_overlay_spawn_pet_hands_character_to_sprite_build(app, monkeypatch):
    monkeypatch.setattr(ov_mod.overlay_spawn_state, "allocate_slot",
                        lambda *a, **k: 3)
    stub = _OverlayStub()
    ov_mod.OverlayShell.spawn_pet(stub, "catgirl-gemini")
    assert stub.built == [(3, "catgirl-gemini")]
    # 一次性覆盖：建完必须复位，重启复活路径不能被上一只的角色污染
    assert stub._spawn_character_override is None


def test_app_spawn_pet_forwards_character_to_overlay(app, monkeypatch):
    from pet import app as app_mod

    monkeypatch.setattr(ov_mod, "is_overlay_topology", lambda: True)
    seen: list = []
    owner = types.SimpleNamespace(
        _overlay_shell=types.SimpleNamespace(spawn_pet=seen.append),
        _spawned_pet_count=0,
    )
    app_mod.AppShell.spawn_pet(owner, "catgirl-gemini")
    # QAction.triggered 会塞个 bool 进来：非字符串一律当「没传」
    app_mod.AppShell.spawn_pet(owner, False)
    assert seen == ["catgirl-gemini", None]
