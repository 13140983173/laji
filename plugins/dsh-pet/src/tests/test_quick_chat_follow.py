"""快速对话气泡要跟着宠物走：拖动宠物气泡不能钉在原地。

`position_near_pet()` 只在打开/尺寸变化时跑一次（quick_chat.py 的 show/尺寸路径），
拖动宠物不会触发它——气泡留在原地。这里把「跟随」钉成可测行为。

注意：宠物必须放在屏**内**再测。离屏平台只有 800×800，sprite 停在屏外时位置会被
边界夹住不动，跟随本来就没有位移可跟（那是假阴性，不是跟随失效）。
"""

from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from tests.test_overlay_spawn import _make_persistent_shell

_INSIDE = QPointF(300, 300)
_STEPS = (QPointF(120, 0), QPointF(-120, 0), QPointF(0, 80), QPointF(0, -80))


def _open_bubble(tmp_path):
    from pet.overlay_shell import _SpriteChatAnchor
    from pet.quick_chat import QuickChatBubble

    shell, _ = _make_persistent_shell(tmp_path)
    shell.overlay.show()
    shell.spawn_pet()
    sprite = shell.sprite
    anchor = _SpriteChatAnchor(shell, sprite)
    bubble = QuickChatBubble(shell._sprite_config(sprite), pet_window=anchor)
    bubble.show()
    sprite.set_pos(_INSIDE)
    bubble.position_near_pet()
    bubble._follow_rect = bubble._anchor_rect()
    return shell, sprite, bubble


def _move_pet(sprite) -> None:
    """挪一步，跳过被屏幕边界夹住的方向（夹住时根本没有位移可跟）。"""
    start = QPointF(sprite.pos)
    for delta in _STEPS:
        sprite.set_pos(start + delta)
        if sprite.pos != start:
            return
    raise AssertionError("sprite 被边界夹住，测试没真正挪动宠物")


def test_bubble_moves_when_the_pet_moves(tmp_path):
    QApplication.instance() or QApplication([])
    shell, sprite, bubble = _open_bubble(tmp_path)
    try:
        before = bubble.pos()
        _move_pet(sprite)

        bubble._follow_tick()

        assert bubble.pos() != before, "宠物移动后气泡必须跟着走"
    finally:
        bubble.close()


def test_follow_tick_is_cheap_when_the_pet_does_not_move(tmp_path):
    QApplication.instance() or QApplication([])
    shell, sprite, bubble = _open_bubble(tmp_path)
    try:
        before = bubble.pos()
        bubble._follow_tick()
        bubble._follow_tick()

        assert bubble.pos() == before, "没动就不该重排（否则每拍 adjustSize 抖）"
    finally:
        bubble.close()


def test_follow_stops_when_the_bubble_is_hidden(tmp_path):
    QApplication.instance() or QApplication([])
    shell, sprite, bubble = _open_bubble(tmp_path)
    try:
        bubble.hide()

        assert bubble._follow_timer.isActive() is False, "收起后不该还在轮询"
    finally:
        bubble.close()


def test_shown_bubble_follows_through_the_real_timer(tmp_path):
    """不只测 _follow_tick：show 之后定时器真的在跑。"""
    from PySide6.QtTest import QTest

    QApplication.instance() or QApplication([])
    shell, sprite, bubble = _open_bubble(tmp_path)
    try:
        assert bubble._follow_timer.isActive() is True
        before = bubble.pos()
        _move_pet(sprite)

        QTest.qWait(300)

        assert bubble.pos() != before, "定时器没把移动同步到气泡"
    finally:
        bubble.close()
