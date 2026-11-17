# -*- coding: utf-8 -*-
"""「我的角色」页（`pet/my_characters_page.py`）的回归测试。

覆盖三件事：缩略图两条取图路径、卡片按清单渲染、切换角色在「有回调（进程内）」
与「无回调（独立设置进程）」两种形态下各自落到哪里。
"""
from __future__ import annotations

import pytest

from pet import my_characters_page as page


@pytest.fixture()
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


class _Config:
    def __init__(self, character: str = "shenshen") -> None:
        self.values = {"character": character}
        self.saves = 0

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def save(self):
        self.saves += 1
        return True


def _rows(*ids: str) -> list[dict]:
    return [
        {
            "id": cid,
            "name": cid.upper(),
            "source": "builtin",
            "preview": None,
            "previewVideo": None,
        }
        for cid in ids
    ]


def test_preview_pixmap_reads_static_frame(tmp_path, qapp):
    from PySide6.QtGui import QColor, QPixmap

    frame = tmp_path / "f_0001.png"
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor("#3388ff"))
    assert pixmap.save(str(frame), "PNG")

    got = page.preview_pixmap({"preview": str(frame), "previewVideo": None})
    assert got is not None and not got.isNull()


def test_preview_pixmap_decodes_video_when_only_webm(monkeypatch, tmp_path, qapp):
    from PySide6.QtGui import QColor, QImage

    calls: list[str] = []
    image = QImage(24, 24, QImage.Format.Format_ARGB32)
    image.fill(QColor("#ff8800"))

    def fake_decode(path):
        calls.append(str(path))
        return image

    monkeypatch.setattr(page, "decode_representative_frame", fake_decode)
    video = tmp_path / "idle.webm"
    got = page.preview_pixmap({"preview": None, "previewVideo": str(video)})
    assert calls == [str(video)], "没有静态帧才去抽视频代表帧"
    assert got is not None and not got.isNull()


def test_preview_pixmap_none_when_nothing_readable(monkeypatch, tmp_path, qapp):
    from PySide6.QtGui import QImage

    monkeypatch.setattr(page, "decode_representative_frame", lambda _p: QImage())
    assert page.preview_pixmap({"preview": None, "previewVideo": None}) is None
    assert page.preview_pixmap(
        {"preview": str(tmp_path / "missing.png"), "previewVideo": None}
    ) is None


def test_page_renders_one_card_per_inventory_row(monkeypatch, qapp):
    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    monkeypatch.setattr(page.catalog, "DEFAULT_CHARACTER", "shenshen")
    widget = page.MyCharactersPage(_Config("shenshen"))
    try:
        assert widget._grid.count() == 2
        assert widget.current_character() == "shenshen"
    finally:
        widget.deleteLater()


def test_page_shows_hint_when_inventory_empty(monkeypatch, qapp):
    monkeypatch.setattr(page.catalog, "character_inventory", list)
    widget = page.MyCharactersPage(_Config())
    try:
        labels = [widget._grid.itemAt(i).widget() for i in range(widget._grid.count())]
        assert any(getattr(w, "text", lambda: "")().startswith("没有找到") for w in labels)
    finally:
        widget.deleteLater()


def test_switch_uses_callback_when_provided(monkeypatch, qapp):
    """进程内路径：交给桌宠主窗口（它自己 set+save+重建窗），页面不重复写盘。"""
    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    config = _Config("shenshen")
    switched: list[str] = []
    widget = page.MyCharactersPage(config, on_switch=switched.append)
    try:
        widget._switch_to("catgirl-gemini")
        assert switched == ["catgirl-gemini"]
        assert config.saves == 0, "有回调时不重复写配置"
    finally:
        widget.deleteLater()


def test_switch_to_writes_config_without_callback(monkeypatch, qapp):
    """独立设置进程里没有主窗口：写盘后由主窗口的 config watcher 接住。"""
    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    config = _Config("shenshen")
    widget = page.MyCharactersPage(config)
    try:
        widget._switch_to("catgirl-gemini")
        assert config.values["character"] == "catgirl-gemini"
        assert config.saves == 1
        assert widget.current_character() == "catgirl-gemini"
        from PySide6.QtWidgets import QPushButton

        buttons = widget.findChildren(QPushButton)
        assert [(b.text(), b.isEnabled()) for b in buttons] == [
            ("设为当前", True), ("改名", True), ("人设", True),
            ("当前角色", False), ("改名", True), ("人设", True),
        ], "刷新后旧卡片必须立刻消失，不能与新卡片叠在一起"

    finally:
        widget.deleteLater()


def test_every_card_carries_a_persona_entry(monkeypatch, qapp):
    """人设的入口长在角色自己身上：「点哪只改哪只」，不再靠下拉先选角色。"""
    from PySide6.QtWidgets import QLabel, QPushButton

    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    config = _Config("shenshen")
    config.values["pet_persona_overrides"] = {"catgirl-gemini": "叫我老板。"}
    widget = page.MyCharactersPage(config)
    try:
        entry = [b for b in widget.findChildren(QPushButton) if b.text() == "人设"]
        assert len(entry) == 2, "每张卡一个「人设」按钮"
        states = [lb.text() for lb in widget.findChildren(QLabel)
                  if lb.objectName() == "characterPersonaState"]
        assert states == ["", "人设 · 自定义"], \
            "只给改过的那只说一句；没改过不挂“出厂”说明"
    finally:
        widget.deleteLater()


def test_cards_carry_no_source_badge(monkeypatch, qapp):
    """卡片上不再挂「内置 / 本机」这类来源说明。"""
    from PySide6.QtWidgets import QLabel

    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    widget = page.MyCharactersPage(_Config("shenshen"))
    try:
        assert not [lb for lb in widget.findChildren(QLabel)
                    if lb.objectName() == "characterBadge"]
        texts = [lb.text() for lb in widget.findChildren(QLabel)]
        assert "内置" not in texts and "本机" not in texts
    finally:
        widget.deleteLater()


def test_selection_follows_the_clicked_card(monkeypatch, qapp):
    """选中态跟着点击走：当前角色不再一直亮着，点哪张就整张亮起来。"""
    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    widget = page.MyCharactersPage(_Config("shenshen"))
    try:
        cards = widget._cards
        assert [bool(c.property("selected")) for c in cards] == [False, False], \
            "一进来不该有任何一张像“被选中”"
        cards[1].clicked.emit("catgirl-gemini")
        assert [bool(c.property("selected")) for c in cards] == [False, True]
        cards[0].clicked.emit("shenshen")
        assert [bool(c.property("selected")) for c in cards] == [True, False], \
            "同一时刻只允许一张卡选中"
    finally:
        widget.deleteLater()


def test_rename_writes_alias_and_updates_the_card(monkeypatch, qapp, tmp_path):
    """改名落到 character_aliases；刷新后卡片上就是新名字。"""
    from PySide6.QtWidgets import QLabel

    from pet.agent_link import pet_space

    monkeypatch.setattr(pet_space, "pet_workspace_root",
                        lambda cid="": str(tmp_path / (cid or "pet")))
    monkeypatch.setattr(page.catalog, "character_inventory",
                        lambda: _rows("shenshen", "catgirl-gemini"))
    config = _Config("shenshen")
    widget = page.MyCharactersPage(config)
    try:
        assert page.rename_character(config, "shenshen", "小满") is True
        assert config.values["character_aliases"] == {"shenshen": "小满"}
        widget.refresh()
        names = [lb.text() for lb in widget.findChildren(QLabel)
                 if lb.objectName() == "characterName"]
        assert "小满" in names
    finally:
        widget.deleteLater()


def test_switch_to_current_is_noop(monkeypatch, qapp):
    monkeypatch.setattr(page.catalog, "character_inventory", lambda: _rows("shenshen"))
    config = _Config("shenshen")
    switched: list[str] = []
    widget = page.MyCharactersPage(config, on_switch=switched.append)
    try:
        widget._switch_to("shenshen")
        assert switched == []
        assert config.saves == 0
    finally:
        widget.deleteLater()


def test_build_content_hands_back_page(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget

    monkeypatch.setattr(page.catalog, "character_inventory", lambda: _rows("shenshen"))

    class _Dialog(QWidget):
        def __init__(self):
            super().__init__()
            self.config = _Config()

    dialog = _Dialog()
    try:
        content = page.build_content(dialog)
        assert isinstance(content, page.MyCharactersPage)
        assert content.parent() is dialog
    finally:
        dialog.deleteLater()


def test_settings_link_lands_on_the_my_characters_tab(tmp_path, monkeypatch, qapp):
    """「小口袋」的深链接式 ``桌宠/我的角色`` 直达到那一张标签，不靠用户自己翻。"""
    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_widgets import MY_CHARACTERS_LINK, SettingsTabContainer

    assert MY_CHARACTERS_LINK == "桌宠/我的角色"
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = ModernSettingsDialog(
        Config(tmp_path / "appdata"), include_ai=False,
        initial_page=MY_CHARACTERS_LINK,
    )
    try:
        assert dialog.sidebar.currentItem().text() == "桌宠", "先落到桌宠域"
        container = dialog.pages.currentWidget().findChild(SettingsTabContainer)
        assert container is not None, "桌宠域应当是有页内标签的域"
        assert container.labels()[container.stack.currentIndex()] == "我的角色"
        assert container.currentKey() == "my_characters"
        assert container.stack.currentWidget() is dialog._my_characters_page
    finally:
        dialog.deleteLater()


def test_plain_domain_link_still_selects_the_domain(tmp_path, monkeypatch, qapp):
    """旧调用只有域名：行为不变（不因为新语法把纯域名解析错）。"""
    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog

    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path / "appdata"), include_ai=False)
    try:
        assert dialog.select_page("更新") is True
        assert dialog.sidebar.currentItem().text() == "更新"
        assert dialog.select_page("没有这一页") is False
    finally:
        dialog.deleteLater()


def test_sidebar_lists_only_the_pet_and_ai_domains(tmp_path, monkeypatch, qapp):
    """侧栏只列「桌宠 / AI 与对话」；其余域仍可深链，但不进导航列表。

    「菜单」域 2026-11-18 整域下线（右键菜单固定用默认那套），所以连页都不建。
    """
    from pet import modern_settings_dialog as settings_mod
    from pet.config import Config
    from pet.modern_settings_dialog import ModernSettingsDialog
    from pet.settings_widgets import SIDEBAR_VISIBLE_DOMAINS, SETTINGS_DOMAIN_NAV

    assert SIDEBAR_VISIBLE_DOMAINS == ("桌宠", "AI 与对话")
    monkeypatch.setattr(settings_mod.autostart_mod, "is_enabled", lambda: False)
    dialog = ModernSettingsDialog(Config(tmp_path / "appdata"), include_ai=True)
    try:
        listed = [
            dialog.sidebar.item(index).text()
            for index in range(dialog.sidebar.count())
            if not dialog.sidebar.item(index).isHidden()
        ]
        assert tuple(listed) == SIDEBAR_VISIBLE_DOMAINS
        # 打开就落在第一个可见域：高亮不能停在看不见的「常规」上
        assert dialog.sidebar.currentItem().text() == "桌宠"
        # 隐藏不等于删除：深链接（右键/更新通知）还要能到；只少「菜单」这一个下线域
        assert dialog.pages.count() == len(SETTINGS_DOMAIN_NAV) - 1
        assert dialog.select_page("更新") is True
        assert dialog.sidebar.currentItem().text() == "更新"
        assert dialog.pages.currentWidget() is not None
    finally:
        dialog.deleteLater()
