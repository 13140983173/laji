# -*- coding: utf-8 -*-
"""附件发出以后还得看得见：聊天记录里是缩略图 / 文件卡，不是一行文件名。

曾经的现场：小工位先把粘贴图从临时目录删掉，再回头画对话流，缩略图永远转不出来，
用户只看到「附件：paste-1793780151157678800.png」。拍板口径是——
发送时把粘贴图搬进会话自己的目录，历史消息从此一直画得出图；非图片附件画文件卡。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _paste_image() -> Path:
    """按真机路径造一张粘贴图：落进剪贴板缓存目录的那种临时件。"""
    from pet.chat.widgets import _save_clipboard_image

    image = QImage(40, 30, QImage.Format.Format_ARGB32)
    image.fill(0xFF44AAEE)
    saved = _save_clipboard_image(image)
    assert saved is not None
    return Path(saved)


def test_pasted_image_is_kept_in_the_session_dir(tmp_path):
    _app()
    from pet.chat.widgets import _is_clipboard_cache_file, persist_chat_attachments

    source = _paste_image()
    kept = persist_chat_attachments(
        [str(source)],
        store_root=tmp_path / "sessions",
        character_id="pet",
        session_id="s1",
    )

    assert len(kept) == 1
    target = Path(kept[0])
    assert target.is_file(), "粘贴图必须真的落进会话附件目录"
    assert target.parent.parent == tmp_path / "attachments" / "pet" / "s1"
    assert target.name == source.name, "文件名要原样保留，气泡正文靠它认领那一行附件"
    assert not _is_clipboard_cache_file(target), "会话目录里的附件不再算临时件"
    assert not source.exists(), "临时件照旧收回，别在临时目录里越堆越多"


def test_thumbnail_still_renders_after_the_send_cleanup(tmp_path):
    _app()
    """老现场：临时件一删就只剩文件名；新路径得一直转得出缩略图。"""
    from pet import workstation_window as w
    from pet.chat.widgets import _discard_clipboard_cache, persist_chat_attachments

    source = _paste_image()
    kept = persist_chat_attachments(
        [str(source)],
        store_root=tmp_path / "sessions",
        character_id="pet",
        session_id="s1",
    )
    _discard_clipboard_cache(source)

    assert w._flow_thumb(source) is None, "临时件收掉以后本来就画不出图（当年那行文件名的由来）"
    card = w._flow_thumb(kept[0])
    assert card is not None, "落进会话目录的图要一直画得出缩略图"
    # 卡片尺寸跟输入框里那张卡一致；PNG 是高清物理像素，按逻辑尺寸上屏
    made = w._flow_card(kept[0])
    assert made is not None
    png, width, height = made
    assert (width, height) == (w.FLOW_THUMB_W, w.FLOW_THUMB_H)
    from PySide6.QtGui import QImage

    physical = QImage(str(png))
    assert physical.width() >= width and physical.height() >= height


def test_user_file_is_referenced_not_copied(tmp_path):
    _app()
    from pet.chat.widgets import persist_chat_attachments

    document = tmp_path / "说明.md"
    document.write_text("# hi", encoding="utf-8")

    kept = persist_chat_attachments(
        [str(document)],
        store_root=tmp_path / "sessions",
        character_id="pet",
        session_id="s1",
    )

    assert kept == [str(document)], "用户自己的文件原地引用，不复制"
    assert document.is_file(), "更不能删"


def test_file_attachment_renders_a_card_not_a_path(tmp_path):
    _app()
    from pathlib import Path

    from PySide6.QtGui import QImage

    from pet import workstation_window as w

    document = tmp_path / "对接说明.md"
    document.write_text("# hi", encoding="utf-8")

    made = w._flow_card(document)

    assert made is not None, "非图片附件也要能抓成卡片"
    png, width, height = made
    assert QImage(str(png)).height() > 0
    assert height == w._AttachChip.H, "文件卡就是输入框里那条胶囊的高度"
    assert width > 0


def test_flow_card_matches_the_composer_card(tmp_path):
    """拍板口径：聊天框里什么样，发出去就什么样——同一尺寸、同一画法。"""
    _app()
    from pet import workstation_window as w

    source = _paste_image()
    made = w._flow_card(source)

    assert made is not None
    _png, width, height = made
    assert (width, height) == (w._AttachCard.W, w._AttachCard.H)
    assert (w.FLOW_THUMB_W, w.FLOW_THUMB_H) == (w._AttachCard.W, w._AttachCard.H)


def test_cards_come_first_in_the_bubble():
    _app()
    from pet import workstation_window as w
    from pet.chat.models import ChatMessage, ChatSession

    source = _paste_image()
    message = ChatMessage("user", "这张图你看下", attachments=[str(source)])
    page = w.MessagesPage.__new__(w.MessagesPage)
    page._shot_sources = {}
    page._shot_images = set()
    html = page._bubble_html(
        message.content,
        True,
        w._theme(w.THEMES[0][0])[2],
        tuple(message.attachments),
    )

    assert "这张图你看下" in html
    assert html.index("<img") < html.index("这张图你看下"), "卡片在文字上面"
    assert "附件：" not in html
    assert str(source.parent) not in html, "不要把路径写进对话流"


def test_attachments_are_inside_the_input_box():
    _app()
    from pet import workstation_window as w

    composer = w._WorkstationComposer()
    composer.add_attachments([_paste_image()])

    root = composer.layout()
    assert root.count() == 1, "框里只放那一个输入框，附件不能另起一排"
    assert root.itemAt(0).widget() is composer.box
    assert composer.chips.parent() is composer.box
    assert composer.edit.parent() is composer.box


def test_attachment_cards_follow_the_speaker_side():
    _app()
    from pet import workstation_window as w

    source = _paste_image()
    page = w.MessagesPage.__new__(w.MessagesPage)
    page._shot_sources = {}
    page._shot_images = set()
    colors = w._theme(w.THEMES[0][0])[2]

    mine = page._bubble_html("嗯", True, colors, (str(source),))
    theirs = page._bubble_html("嗯", False, colors, (str(source),))

    assert 'align="right"' in mine
    assert 'align="right"' not in theirs, "对方发的附件靠左，不能跟自己的一模一样"


def test_attachment_line_leaves_the_body_and_becomes_a_card():
    _app()
    from pet import workstation_window as w

    text = "1=1?\n\n附件：paste-1.png、对接说明.md"

    names, shown = w._split_attachment_names(text)

    assert names == ["paste-1.png", "对接说明.md"]
    assert shown == "1=1?", "附件行整行摘掉，名字改由文件卡上屏"


def test_input_box_stays_short_and_keeps_its_buttons_inside():
    _app()
    from pet import workstation_window as w

    composer = w._WorkstationComposer()
    assert composer.edit.height() <= 60, "默认就是个矮条，不要吃掉半个工位"
    assert composer.send.parent() is composer.box
    assert composer.edit.parent() is composer.box
    assert composer.edit.placeholderText() == "跟她说点什么…", "输入区里不挂操作说明"


def test_input_box_grows_with_lines_but_stops_at_the_cap():
    _app()
    from pet import workstation_window as w

    composer = w._WorkstationComposer()
    short = composer.edit.height()

    composer.edit.setPlainText("\n".join(f"第{i}行" for i in range(4)))
    assert composer.edit.height() > short

    composer.edit.setPlainText("\n".join(f"第{i}行" for i in range(40)))
    assert composer.edit.height() <= 96, "写再多也只到上限，剩下的内部滚"


def test_composer_is_a_short_strip_not_a_half_page():
    _app()
    from pet import workstation_window as w

    composer = w._WorkstationComposer()
    assert composer.sizeHint().height() <= 80, "整个输入框就应该是一条矮条"


def test_composer_hands_pasted_files_to_the_sender():
    _app()
    from pet import workstation_window as w
    from pet.chat.widgets import _save_clipboard_image

    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(0xFF224466)
    source = Path(_save_clipboard_image(image))
    composer = w._WorkstationComposer()
    composer.add_attachments([source])

    composer.clear(discard=False)
    assert source.exists(), "发送方还没收图，清输入区不能抢先删"

    composer.add_attachments([source])
    composer.clear()
    assert not source.exists(), "手动移除照旧收临时件"
