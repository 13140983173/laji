# -*- coding: utf-8 -*-
"""工作台卡片上的数字、工坊胶囊上的数字，必须等于点进去能数到的卡片。

踩过的坑：工坊卡片永远写「0 个包」（动作名 ``workshop`` 拿去查计数键 ``packs``），
工坊页「未装 0」但列表里躺着 3 个（桶只认 ``off``，工坊的 kind 叫 ``available``）。
"""

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    return instance if instance is not None else QApplication([])


def test_kind_buckets_counts_by_bucket():
    from pet import workstation_window as w

    cards = [
        {"kind": "installed"},
        {"kind": "installed"},
        {"kind": "available"},
        {"kind": "off"},
    ]

    assert w._kind_buckets(cards, {"online": ("installed",), "off": ("available",)}) == {
        "online": 2,
        "off": 1,
    }
    assert w._kind_buckets([], {"failed": ("failed",)}) == {"failed": 0}


def _bench():
    from PySide6.QtWidgets import QWidget

    class Owner:
        character_id = ""

    class Win:
        owner = Owner()

    class Bench(QWidget):
        _win = Win()

        def refresh_counts(self):
            pass

    # 页面是 QWidget，父控件也得是 QWidget，不然 PySide6 直接拒收。
    return Bench()


def test_workstation_cards_read_their_own_count_key(app, monkeypatch):
    """工坊卡片查的是 ``packs``：以前按动作名 ``workshop`` 查，永远 0。"""
    from pet import workstation_window as w

    class Card:
        def __init__(self):
            self.desc = ""

        def set_desc(self, text):
            self.desc = text

    monkeypatch.setattr(w.pet_toolkit, "counts", lambda character="", home="": {
        "connectors": 1,
        "skills": 3,
        "packs": 8,
    })

    bench = _bench()
    bench.cards = {"connectors": Card(), "skills": Card(), "workshop": Card()}
    w.BenchPage.refresh_counts(bench)

    assert [c.desc for c in bench.cards.values()] == ["1 个", "3 条", "8 个包"]


def test_workshop_chips_add_up_to_all(app, monkeypatch):
    """「全部 = 已装 + 未装」，且点「未装」看到的张数和胶囊上那个数字一样。"""
    from pet import workstation_window as w

    packs = [
        {"id": f"in-{i}", "name": f"已装 {i}", "installed": True} for i in range(5)
    ] + [
        {"id": f"out-{i}", "name": f"未装 {i}", "installed": False} for i in range(3)
    ]
    monkeypatch.setattr(w.pet_toolkit, "workshop_packs", lambda *a, **k: packs)

    page = w.WorkshopPage(_bench())
    labels = {key: button.text() for key, button in page._seg_buttons.items()}
    assert labels == {"all": "全部 8", "online": "已装 5", "off": "未装 3"}

    page._filter = "off"
    page._rebuild()
    assert [c["name"] for c in page._visible()] == ["未装 0", "未装 1", "未装 2"]

    page._filter = "online"
    page._rebuild()
    assert len(page._visible()) == 5
