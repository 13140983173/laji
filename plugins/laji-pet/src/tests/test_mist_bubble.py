# -*- coding: utf-8 -*-
"""mist_bubble：纯函数区 + 三个挂点的接线测试。

纯函数（文本规整 / 悬挂定位 / 屏幕夹取）不建窗口；接线测试走 offscreen 平台，
用真实的 QuickChatBubble 回调（``_approval`` / ``_finished``）验证雾真的被拉起。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication

from pet.config import Config
from pet.mist_bubble import (
    BUBBLE_MAX_CHARS,
    BUBBLE_MAX_TEXT_WIDTH,
    MistBubble,
    clamp_point,
    mist_position,
    mist_text,
    surface_size_for_lines,
    tail_tip_local,
    tail_tip_point,
    win_size_for_surface,
    wrap_lines,
)


# ------------------------------------------------------------ mist_text
class TestMistText:
    def test_plain_becomes_single_line(self):
        # Markdown 标题/加粗/代码围栏都压成平话，雾里不出现记号。
        raw = "## 结论\n**缓存** 已清，`1.2 GB`。\n```bash\ngit push\n```"
        out = mist_text(raw)
        assert out == "结论 缓存 已清，1.2 GB。 bash git push"

    def test_long_text_truncated(self):
        out = mist_text("字" * 300)
        assert len(out) == BUBBLE_MAX_CHARS + 1  # 截断 + 省略号
        assert out.endswith("…")

    def test_empty_is_empty(self):
        assert mist_text("") == ""
        assert mist_text(None) == ""

    def test_short_text_untouched(self):
        assert mist_text("喏。") == "喏。"

    def test_underscore_in_tool_name_survives(self):
        # 审批雾会带上工具名：下划线被当 Markdown 剥掉就成了错名字。
        assert mist_text("要用 builtin:run_terminal") == "要用 builtin:run_terminal"


# ------------------------------------------------------------ clamp_point
class TestClampPoint:
    SCREEN = QRect(0, 0, 1920, 1040)

    def test_inside_untouched(self):
        assert clamp_point(100, 100, 200, 80, self.SCREEN) == (100, 100)

    def test_left_overflow_pushed_in(self):
        x, y = clamp_point(-80, 100, 200, 80, self.SCREEN)
        assert x == self.SCREEN.left() + 4

    def test_bottom_overflow_pushed_up(self):
        x, y = clamp_point(100, 1200, 200, 80, self.SCREEN)
        assert y == self.SCREEN.bottom() - 80 - 4

    def test_right_overflow_pushed_left(self):
        x, _ = clamp_point(1900, 100, 200, 80, self.SCREEN)
        assert x == self.SCREEN.right() - 200 - 4


# ------------------------------------------------------------ mist_position
ANCHOR = QRect(1700, 700, 180, 220)  # 宠物在屏幕右缘
SCREEN = QRect(0, 0, 1920, 1040)


class TestMistPosition:
    # 窗口尺寸按 C 面板反推：留白（投影/标签/尾巴）一并算进去。
    W, H = win_size_for_surface(280, 64)

    def _tip_in_window(self, w: int, h: int, x: int, y: int) -> tuple[int, int]:
        lx, ly = tail_tip_local(w, h)
        return x + lx, y + ly

    def test_normal_tail_points_at_her_head(self):
        # C 方案的对白是「贴身」的：尾巴尖浮在她头顶上方一点，面板往上长。
        tip_x, tip_y = tail_tip_point(ANCHOR, low=False)
        x, y = mist_position(ANCHOR, self.W, self.H, low=False, screen=SCREEN)
        assert self._tip_in_window(self.W, self.H, x, y) == (tip_x, tip_y)
        assert tip_y <= ANCHOR.top()  # 尖到她头顶或更高，不埋进头发
        assert tip_y > ANCHOR.top() - 40  # 只是「稍微往上」，没飘到天上

    def test_low_tail_points_at_her_waist(self):
        # 审批：压到腰侧、往左肩靠，不盖住脸。
        tip_x, tip_y = tail_tip_point(ANCHOR, low=True)
        x, y = mist_position(ANCHOR, self.W, self.H, low=True, screen=SCREEN)
        assert self._tip_in_window(self.W, self.H, x, y) == (tip_x, tip_y)
        assert tip_y > tail_tip_point(ANCHOR, low=False)[1]
        assert tip_x < tail_tip_point(ANCHOR, low=False)[0]

    def test_pet_at_left_edge_bubble_pushed_into_screen(self):
        anchor = QRect(0, 300, 180, 220)  # 靠左：尾巴尖算出来的 x 为负
        x, _ = mist_position(anchor, self.W, self.H, low=False, screen=SCREEN)
        assert x == SCREEN.left() + 4

    def test_not_clamped_when_space_enough(self):
        tip_x, _ = tail_tip_point(ANCHOR, low=False)
        local_x, _ = tail_tip_local(self.W, self.H)
        x, _ = mist_position(ANCHOR, self.W, self.H, low=False, screen=SCREEN)
        assert x == tip_x - local_x  # 空间够就真的贴着她，不夹取

    def test_bubble_never_runs_off_top(self):
        # 她贴在屏幕顶边：整块面板得被夹回可视区，不能只露一条尾巴。
        anchor = QRect(900, 0, 180, 220)
        _, y = mist_position(anchor, self.W, self.H, low=False, screen=SCREEN)
        assert y >= SCREEN.top() + 4


# ------------------------------------------------------------ 折行/面板尺寸
class TestBubbleLayout:
    def _fm(self):
        from PySide6.QtGui import QFont, QFontMetrics

        QApplication.instance() or QApplication([])
        font = QFont()
        font.setPixelSize(15)
        return QFontMetrics(font)

    def test_lines_never_exceed_column_width(self):
        fm = self._fm()
        lines = wrap_lines("字" * 200, fm, BUBBLE_MAX_TEXT_WIDTH)
        assert len(lines) > 1
        for line in lines:
            assert fm.horizontalAdvance(line) <= BUBBLE_MAX_TEXT_WIDTH

    def test_short_text_is_single_line(self):
        assert wrap_lines("喏。", self._fm(), BUBBLE_MAX_TEXT_WIDTH) == ["喏。"]

    def test_surface_grows_with_line_count(self):
        fm = self._fm()
        one = surface_size_for_lines(["喏。"], fm)
        two = surface_size_for_lines(["喏。", "喏喏喏。"], fm)
        assert two[1] > one[1]
        # 宽度只跟最长一行有关（+ 左右内边距），不跟行数
        assert two[0] == fm.horizontalAdvance("喏喏喏。") + 2 * 18
        assert one[0] == fm.horizontalAdvance("喏。") + 2 * 18

    def test_long_word_hard_wrapped(self):
        # 长 URL / 无空格串必须硬断：否则面板被撑过列宽上限
        fm = self._fm()
        lines = wrap_lines("https://example.com/" + "a" * 120, fm, BUBBLE_MAX_TEXT_WIDTH)
        assert len(lines) > 1
        for line in lines:
            assert fm.horizontalAdvance(line) <= BUBBLE_MAX_TEXT_WIDTH

    def test_punct_never_starts_a_line(self):
        # 原型靠浏览器默认断行；Qt 手写折行得自己守行首禁则，否则「？」单独一行。
        fm = self._fm()
        lines = wrap_lines("主色改完了，两处字号待定。要现在定吗？", fm, BUBBLE_MAX_TEXT_WIDTH)
        assert len(lines) > 1
        for line in lines[1:]:
            assert line[0] not in "、。，．？！：；）"

    def test_surface_constants_match_prototype_c(self):
        # 原型 #sC .bubble：白底 #fdfdfb、墨字 #232a42、圆角 18 18 18 5、尾巴 9px/right:16px
        from pet.mist_bubble import (
            BUBBLE_BG,
            BUBBLE_INK,
            BUBBLE_RADIUS,
            BUBBLE_RADIUS_BL,
            BUBBLE_TAIL_H,
            BUBBLE_TAIL_INSET,
        )

        assert BUBBLE_BG.name() == "#fdfdfb"
        assert BUBBLE_INK.name() == "#232a42"
        assert (BUBBLE_RADIUS, BUBBLE_RADIUS_BL) == (18, 5)
        assert (BUBBLE_TAIL_H, BUBBLE_TAIL_INSET) == (9, 16)

    def test_window_leaves_room_for_tag_and_tail(self):
        from pet.mist_bubble import (
            BUBBLE_MARGIN_BOTTOM,
            BUBBLE_MARGIN_TOP,
            BUBBLE_MARGIN_X,
        )

        w, h = win_size_for_surface(280, 64)
        assert w == 280 + BUBBLE_MARGIN_X * 2
        assert h == 64 + BUBBLE_MARGIN_TOP + BUBBLE_MARGIN_BOTTOM


# ------------------------------------------------------------ 名签
class TestTag:
    """名签：几何按原型，名字两条拓扑都得取到。"""

    def test_geometry_matches_prototype_c(self):
        # 原型 .bubble::before：left:15px、top:-9px、padding:1px 9px、圆角 9px、
        # box-shadow:0 3px 8px rgba(0,0,0,.25)
        from pet.mist_bubble import (
            BUBBLE_TAG_H,
            BUBBLE_TAG_LEFT,
            BUBBLE_TAG_OVERHANG,
            BUBBLE_TAG_PAD_X,
            BUBBLE_TAG_RADIUS,
            BUBBLE_TAG_SHADOW_LAYERS,
        )

        assert BUBBLE_TAG_LEFT == 15
        assert BUBBLE_TAG_OVERHANG == 9
        assert BUBBLE_TAG_PAD_X == 9
        assert BUBBLE_TAG_H == 16          # 原型 1px 上下内边距 + 10.5px 行盒 ≈ 15
        assert BUBBLE_TAG_RADIUS == 8      # 原型 9px，高度更矮取半高内
        assert len(BUBBLE_TAG_SHADOW_LAYERS) >= 2

    def test_overlay_anchor_resolves_name_through_shell_config(self, tmp_path):
        # 真机踩过：overlay 拓扑的锚点 __slots__ 里没有 cfg，只看第一层 -> 名签整个不见
        from pet.mist_bubble import pet_display_name

        cfg = Config(base=tmp_path)
        cfg.set("character", "shenshen")

        class Anchor:
            __slots__ = ("_shell", "_sprite")

            def __init__(self, shell):
                self._shell = shell
                self._sprite = None

        class Shell:
            def __init__(self, config):
                self._config = config

        assert pet_display_name(Anchor(Shell(cfg))) == "大肥鱼"

    def test_pet_window_shape_still_works(self, tmp_path):
        from pet.mist_bubble import pet_display_name

        cfg = Config(base=tmp_path)
        cfg.set("character", "shenshen")

        class Pet:
            pass

        pet = Pet()
        pet.cfg = cfg
        assert pet_display_name(pet) == "大肥鱼"

    def test_bare_anchor_gets_no_name(self):
        from pet.mist_bubble import pet_display_name

        assert pet_display_name(object()) == ""
        assert pet_display_name(None) == ""

    def test_raw_character_id_is_never_shown(self, tmp_path):
        # 素材包缺失时只能拿到目录 id：宁可没标签，也不挂一个英文 id
        from pet.mist_bubble import pet_display_name

        cfg = Config(base=tmp_path)
        cfg.set("character", "no_such_character")

        class Pet:
            pass

        pet = Pet()
        pet.cfg = cfg
        assert pet_display_name(pet) == ""

    def test_alias_wins(self, tmp_path):
        from pet.mist_bubble import pet_display_name

        cfg = Config(base=tmp_path)
        cfg.set("character", "shenshen")
        cfg.set_character_alias("shenshen", "阿鲸")

        class Pet:
            pass

        pet = Pet()
        pet.cfg = cfg
        assert pet_display_name(pet) == "阿鲸"

    def test_explicit_name_overrides_anchor(self):
        # 气泡自己知道 character_id：调用方给了名字就不依赖锚点形状
        app = QApplication.instance() or QApplication([])
        mist = MistBubble.instance()
        try:
            mist.show_mist("喏。", pet_window=object(), name="鲸鱼娘")
            app.processEvents()
            assert mist._tag == "鲸鱼娘"
        finally:
            mist.dismiss()
            app.processEvents()


# ------------------------------------------------------------ 挂点接线
def _bubble(tmp_path, request_id: str = "rid-1"):
    """真实快速对话气泡（offscreen）：与 test_quick_chat_engine_approval 同口径。"""
    from pet.quick_chat import QuickChatBubble

    app = QApplication.instance() or QApplication([])
    bubble = QuickChatBubble(Config(base=tmp_path))
    bubble._active_request_id = request_id
    return app, bubble


class TestWiring:
    def test_approval_raises_low_mist(self, tmp_path):
        app, bubble = _bubble(tmp_path)
        try:
            bubble._approval("rid-1", "call-9", "builtin:run_terminal", "要删 .cache/laji/tmp", 30)
            mist = MistBubble.instance()
            assert mist.isVisible()
            # 2026-11-02 口径：聊天框统一在头顶上方，审批人话不再压到腰侧。
            assert mist._low is False
            assert "运行命令" in mist._text            # 显示名，不是 builtin:run_terminal
            assert "要删" in mist._text                    # 人话的 reason 必须上雾
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()

    def test_finished_reply_raises_mist_at_shoulder(self, tmp_path):
        app, bubble = _bubble(tmp_path)
        try:
            bubble._finished("rid-1", "喏。缓存清了，1.2 GB，main 推上去了。")
            mist = MistBubble.instance()
            assert mist.isVisible()
            assert mist._low is False                     # 正常说话在肩侧
            assert mist._text.startswith("喏。缓存清了")
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()

    def test_finished_reply_carries_her_name(self, tmp_path):
        """名签要真的画出名字（真机曾因锚点没 cfg 而整个标签消失）。"""
        app, bubble = _bubble(tmp_path)
        try:
            bubble._finished("rid-1", "喏。缓存清了。")
            assert MistBubble.instance()._tag == "大肥鱼"
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()

    def test_finished_keeps_card_hidden_until_clicked(self, tmp_path):
        """v2：回答默认只走雾；卡片不能自己冒出来（真机截图就被这个坑过）。"""
        app, bubble = _bubble(tmp_path)
        try:
            bubble._finished("rid-1", "苏州今天多云，17℃。明天下雨，记得带伞。")
            app.processEvents()
            assert not bubble.output_scroll.isVisibleTo(bubble)
            assert MistBubble.instance().isVisible()

            bubble._open_full_reply()
            app.processEvents()
            assert bubble.output_scroll.isVisibleTo(bubble)
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()

    def test_clicking_mist_runs_callback(self, tmp_path):
        app, bubble = _bubble(tmp_path)
        try:
            bubble._finished("rid-1", "喏。")
            mist = MistBubble.instance()
            hit = []
            mist._on_click = lambda: hit.append(1)
            mist.clicked.emit()
            assert hit == [1]
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()

    def test_mist_text_is_truncated_preview(self, tmp_path):
        app, bubble = _bubble(tmp_path)
        try:
            bubble._finished("rid-1", "字" * 500)
            mist = MistBubble.instance()
            assert len(mist._text) == BUBBLE_MAX_CHARS + 1
            assert mist._text.endswith("…")
        finally:
            MistBubble.instance().dismiss()
            bubble.close()
            app.processEvents()
