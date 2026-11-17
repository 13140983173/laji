# -*- coding: utf-8 -*-
"""``pet/catalog.py`` 角色清单（桌宠管家面板「角色卡」的唯一真源）的回归测试。

背景：1.2.3 起角色素材打进桌宠 exe 内部的 ``_internal/assets/characters``，安装目录
不再带 ``characters/``，面板自己扫目录就会显示「没有找到角色包」。改为桌宠发布
``<桌宠家>/characters.json``、面板只读同一份。
"""
from __future__ import annotations

import json

import pytest

from pet import catalog


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


@pytest.fixture()
def external(tmp_path, monkeypatch):
    root = tmp_path / "characters"
    root.mkdir()
    monkeypatch.setattr(catalog, "external_character_dirs", lambda: [root])
    return root


def test_inventory_starts_with_the_builtin_characters(external):
    rows = catalog.character_inventory()
    assert [row["id"] for row in rows][:len(catalog.CHARACTERS)] == list(catalog.CHARACTERS)
    assert [row["source"] for row in rows][:len(catalog.CHARACTERS)] == ["builtin"] * len(catalog.CHARACTERS)


def test_inventory_picks_up_a_legacy_videos_directory(external):
    _touch(external / "whale-maid" / "videos" / "idle" / "a.webm")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["whale-maid"]["source"] == "user"


def test_inventory_marks_installed_character_packs(external):
    pack = external / "cat-extra" / "1.0.0-win-x64"
    pack.mkdir(parents=True)
    (pack / "character.json").write_text("{}", encoding="utf-8")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["cat-extra"]["source"] == "pack"


def test_publish_writes_the_inventory_and_current(tmp_path, external):
    target = tmp_path / "home" / "characters.json"
    assert catalog.publish_character_inventory(target, current="catgirl-gemini") == target
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["version"] == catalog.CHARACTER_INVENTORY_VERSION
    assert doc["current"] == "catgirl-gemini"
    assert [row["id"] for row in doc["characters"]][:2] == list(catalog.CHARACTERS)


def test_publish_skips_an_unchanged_inventory(tmp_path, external):
    """内容没变就不碰文件：面板按内容判变化，白写一次会惊动它的读盘。"""
    target = tmp_path / "home" / "characters.json"
    catalog.publish_character_inventory(target, current="shenshen")
    first = target.stat().st_mtime_ns
    catalog.publish_character_inventory(target, current="shenshen")
    assert target.stat().st_mtime_ns == first
    assert not (tmp_path / "home" / (catalog.CHARACTER_INVENTORY_FILENAME + ".tmp")).exists()


def test_publish_refreshes_when_the_current_character_changes(tmp_path, external):
    target = tmp_path / "home" / "characters.json"
    catalog.publish_character_inventory(target, current="shenshen")
    catalog.publish_character_inventory(target, current="catgirl-gemini")
    doc = json.loads(target.read_text(encoding="utf-8"))
    assert doc["current"] == "catgirl-gemini"


def test_inventory_carries_a_static_preview_frame(external):
    """有 frameseq 的角色直接给第一帧静态图，面板不必抽帧。"""
    clip = external / "whale-maid" / "frameseq" / "idle" / "待机.gabc" / "f_0002.webp"
    _touch(clip)
    _touch(external / "whale-maid" / "videos" / "idle" / "a.webm")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["whale-maid"]["preview"] == str(clip)
    assert rows["whale-maid"]["previewVideo"] is None


def test_inventory_finds_frames_in_the_installed_three_level_layout(external):
    """安装包里的片段多一层 ``<片段>.webm/<g哈希>/f_0001.webp``，不能漏。"""
    clip = (external / "whale-maid" / "frameseq" / "idle" / "打瞌睡被惊醒.webm"
            / "打瞌睡被惊醒.g914d505ab2ba" / "f_0001.webp")
    _touch(clip)
    assert catalog.character_preview("whale-maid")["preview"] == str(clip)


def test_inventory_falls_back_to_a_webm_for_ffmpeg_thumbnails(external):
    """只有 webm 的角色把文件路径交给面板抽帧（idle 优先）。"""
    webm = _touch(external / "whale-maid" / "videos" / "idle" / "a.webm")
    _touch(external / "whale-maid" / "videos" / "click" / "b.webm")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["whale-maid"]["preview"] is None
    assert rows["whale-maid"]["previewVideo"] == str(webm)


def test_inventory_keeps_a_card_but_no_preview_without_media(external):
    """包索引在、素材缺失：仍然出卡（能切），预览留空给面板占位块。"""
    pack = external / "cat-extra" / "1.0.0-win-x64"
    pack.mkdir(parents=True)
    (pack / "character.json").write_text("{}", encoding="utf-8")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["cat-extra"]["preview"] is None
    assert rows["cat-extra"]["previewVideo"] is None


def test_inventory_pack_preview_is_found_inside_the_version_directory(external):
    """角色包布局是 <id>/<版本>/frameseq/...：素材在版本目录里，不能只看父目录。"""
    version = external / "cat-extra" / "1.0.0-win-x64"
    clip = version / "frameseq" / "idle" / "x" / "f_0001.webp"
    _touch(clip)
    (version / "character.json").write_text("{}", encoding="utf-8")
    rows = {row["id"]: row for row in catalog.character_inventory()}
    assert rows["cat-extra"]["preview"] == str(clip)


def test_publish_declares_the_asset_roots_the_panel_may_read(tmp_path, external):
    """面板的 /api/preview 只放行这些根；不声明，内置角色的图一律 403。"""
    target = tmp_path / "home" / "characters.json"
    catalog.publish_character_inventory(target, current="shenshen")
    doc = json.loads(target.read_text(encoding="utf-8"))
    roots = set(doc["assetRoots"])
    assert str(catalog.characters_dir()) in roots
    assert str(external) in roots


def test_builtin_characters_get_a_real_preview_from_this_checkout():
    """仓库自带素材应该能挑出代表帧 —— 缩略图不能停在「以后再说」。"""
    for cid in catalog.CHARACTERS:
        row = catalog.character_preview(cid)
        assert row["preview"] or row["previewVideo"], cid
