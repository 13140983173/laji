# -*- coding: utf-8 -*-
"""聊天灵动岛（ChatIsland）——「和她聊天」的那颗胶囊。

v3 交互定稿（原型 ``.workbuddy/scratch/laji-pet-ui-v3-variants.html`` 的 C 方案）：
桌面上**没有常驻输入框**。平时她脚边只有一颗小胶囊，显示「她在干嘛」；
右键她 →「和她聊天」才把胶囊展开成一条输入胶囊；发出去之后自己收回去接着报进度。

三态：

- ``hidden``：什么都没有（桌宠隐藏 / 主动收起）；
- ``mini``：150x32 状态胶囊，左侧金点（忙的时候脉动）+ 一行状态字；
- ``open``：340x44 输入胶囊，QLineEdit + 发送 + 关闭，弹开即聚焦。

与 ``MistBubble`` 的分工：对白是「她已经说出来的话」（白底标签面板，说完
自动收），岛是「你说话的入口＋她的进度」。两者都是独立置顶 Tool 窗，都贴着
``visible_content_rect()`` 定位。
"""
from __future__ import annotations

import logging
import math

try:  # 同 mist_bubble：C++ 侧被销毁后的单例验尸
    import shiboken6
except Exception:  # pragma: no cover
    shiboken6 = None

from PySide6.QtCore import QPointF, QPropertyAnimation, QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QWidget,
)

STATE_HIDDEN = "hidden"
STATE_MINI = "mini"
STATE_OPEN = "open"

# 胶囊本体（不含投影留白）
MINI_W = 150
MINI_H = 32
OPEN_W = 340
OPEN_H = 44
ISLAND_RADIUS_H = 16          # mini 的胶囊圆角（= 半高）
ISLAND_MARGIN = 8             # 四周留白：投影要地方，否则被窗口裁成硬边
ISLAND_GAP = 5                # 胶囊上缘离她脚尖多远
ISLAND_FOLLOW_MS = 400        # 她走了以后贴回去的比对周期
ISLAND_ANIM_MS = 220
ISLAND_PULSE_MS = 40

ISLAND_FONT_PX = 12
ISLAND_TEXT = QColor(219, 225, 240)          # #dbe1f0
ISLAND_MUTED = QColor(160, 170, 195)
ISLAND_ACCENT = QColor(232, 163, 61)         # 金：和她的人设/主题同色
ISLAND_BG_TOP = QColor(26, 33, 55, 236)
ISLAND_BG_BOTTOM = QColor(15, 21, 38, 230)
ISLAND_EDGE = QColor(255, 255, 255, 46)
# 原型 `#sC .island[data-state="mini"]:hover`：悬停时描边转金（rgba(232,163,61,.42)）
ISLAND_EDGE_HOVER = QColor(232, 163, 61, 107)

# mini 内部排版：原型 `#sC .isl-mini` 是 flex 居中 + gap:7px + padding:0 13px，
# 那颗点 6×6 且**常亮**（``box-shadow:0 0 8px rgba(232,163,61,.9)``）——忙闲只
# 改呼吸，不该改颜色（灰点会让“她在干嘛”这条常驻信息看起来像掉线了）。
MINI_DOT_PX = 6.0
MINI_DOT_GAP = 7.0
MINI_DOT_GLOW_PX = 8.0
MINI_PAD_X = 13.0
# open 态控件尺寸同原型 `.isl-open .send`(30×30) / `.isl-open .x`(20×20)
SEND_BTN_PX = 30
CLOSE_BTN_PX = 20

# 投影：多层下移 + 递减透明度（单层实心偏移会沿边缘留硬边）
_SHADOW_LAYERS = ((1, 40), (2, 26), (3, 16), (4, 8))


# ---------------------------------------------------------------- 纯函数
def island_geometry(anchor: QRect, w: int, h: int, screen: QRect) -> tuple[int, int]:
    """胶囊位置（纯函数，可单测）：贴她脚下居中；脚下放不下就翻到头顶上面。

    ``anchor`` 是她身体框（全局坐标），``w/h`` 是**含投影留白**的窗口尺寸。
    """
    x = anchor.center().x() - w // 2
    y = anchor.bottom() + ISLAND_GAP - ISLAND_MARGIN // 2
    if y + h > screen.bottom() - 2:
        # 贴着屏幕底边（她坐在任务栏上）：翻到她头顶上面去，别藏到栏后面。
        y = anchor.top() - h - ISLAND_GAP + ISLAND_MARGIN // 2
    x = max(screen.left() + 2, min(x, screen.right() - w - 2))
    y = max(screen.top() + 2, min(y, screen.bottom() - h - 2))
    return x, y


def fit_status(text: str, fm: QFontMetrics, width: int) -> str:
    """状态字按可用宽度省略（纯函数，可单测；省略号留给「还有话」的暗示）。"""
    body = " ".join(str(text or "").split())
    if not body:
        return ""
    return fm.elidedText(body, Qt.TextElideMode.ElideRight, max(20, int(width)))


# ---------------------------------------------------------------- 组件
class ChatIsland(QWidget):
    """常驻单例可复用的聊天胶囊：mini 报进度，open 收输入。"""

    submitted = Signal(str)     # 回车 / 点发送：带上文本
    closed = Signal()           # ✕：整颗关掉（用户不想再看见它）
    dismissed = Signal()        # Esc：只退回 mini，胶囊继续报进度
    expanded = Signal()

    def __init__(self, config=None, pet_window=None) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.config = config
        self._pet = pet_window
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # mini 态不抢前台：她报进度时用户可能正在别处打字。
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowTitle("和她聊天")

        font = QFont()
        font.setFamilies(("PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei UI", "Microsoft YaHei"))
        font.setPixelSize(ISLAND_FONT_PX)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.2)
        self.setFont(font)

        self._state = STATE_HIDDEN
        self._status = "在呢"
        self._busy = False
        self._phase = 0.0
        self._expanding = False

        self._build()
        self._anim = QPropertyAnimation(self, b"size", self)
        self._anim.setDuration(ISLAND_ANIM_MS)
        self._anim.finished.connect(self._on_anim_done)

        self._pulse = QTimer(self)
        self._pulse.setInterval(ISLAND_PULSE_MS)
        self._pulse.timeout.connect(self._tick_pulse)

        self._follow = QTimer(self)
        self._follow.setInterval(ISLAND_FOLLOW_MS)
        self._follow.timeout.connect(self._follow_tick)
        self._follow_rect: QRect | None = None

        self.resize(MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2)
        self._apply_state_children()

    # ------------------------------------------------------------ 构建
    def _build(self) -> None:
        row = QHBoxLayout(self)
        # 左右要躲开圆头的自然弧度，输入光标才不贴边
        row.setContentsMargins(ISLAND_MARGIN + 16, ISLAND_MARGIN + 5,
                               ISLAND_MARGIN + 9, ISLAND_MARGIN + 5)
        row.setSpacing(8)

        self.input = QLineEdit(self)
        self.input.setObjectName("chat-island-input")
        self.input.setPlaceholderText("跟她说点什么…（Enter 发送）")
        self.input.setFrame(False)
        self.input.setMinimumHeight(26)
        self.input.returnPressed.connect(self._emit_submit)

        self.send_btn = QPushButton("↑", self)
        self.send_btn.setObjectName("chat-island-send")
        self.send_btn.setFixedSize(SEND_BTN_PX, SEND_BTN_PX)
        self.send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_btn.clicked.connect(self._emit_submit)

        self.close_btn = QPushButton("✕", self)
        self.close_btn.setObjectName("chat-island-close")
        self.close_btn.setFixedSize(CLOSE_BTN_PX, CLOSE_BTN_PX)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self._on_close_clicked)

        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        row.addWidget(self.close_btn)

        self.setStyleSheet(f"""
            QLineEdit#chat-island-input {{
                background: transparent; border: none;
                color: {ISLAND_TEXT.name()}; font-size: 13px;
                selection-background-color: {ISLAND_ACCENT.name()};
                selection-color: #241a06;
            }}
            QPushButton#chat-island-send {{
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #f0b862, stop:1 {ISLAND_ACCENT.name()});
                color: #241a06; border: none; border-radius: 15px;
                font-size: 14px; font-weight: 600; padding: 0;
            }}
            QPushButton#chat-island-send:hover {{ background: #f6c479; }}
            QPushButton#chat-island-close {{
                background: transparent; color: {ISLAND_MUTED.name()};
                border: none; border-radius: 10px; font-size: 11px; padding: 0;
            }}
            QPushButton#chat-island-close:hover {{ background: rgba(255,255,255,30); color: #ffffff; }}
        """)

    def _apply_state_children(self) -> None:
        opened = self._state == STATE_OPEN
        for widget in (self.input, self.send_btn, self.close_btn):
            widget.setVisible(opened)

    # ------------------------------------------------------------ 入口
    @property
    def state(self) -> str:
        return self._state

    def is_open(self) -> bool:
        return self._state == STATE_OPEN

    def set_pet_window(self, pet_window) -> None:
        self._pet = pet_window

    def set_status(self, text: str, *, busy: bool | None = None) -> None:
        """mini 胶囊上那句话（「正在翻日志」「发好啦」）。空串保持原话。"""
        body = " ".join(str(text or "").split())
        if body:
            self._status = body
        if busy is not None:
            self._busy = bool(busy)
        self.update()
        self._sync_pulse()

    def expand(self) -> None:
        """展开成输入胶囊（右键「和她聊天」/ 点 mini 胶囊）。"""
        if self._state == STATE_OPEN:
            self._focus_input()
            return
        self._state = STATE_OPEN
        self._apply_state_children()
        self._show_window()
        self._animate_to(OPEN_W + ISLAND_MARGIN * 2, OPEN_H + ISLAND_MARGIN * 2)
        self.expanded.emit()

    def collapse(self) -> None:
        """收回去当状态胶囊（发出去之后自动走这里）。"""
        if self._state != STATE_OPEN:
            return
        self._state = STATE_MINI
        self.input.clear()
        self._apply_state_children()
        self._animate_to(MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2)
        self._sync_pulse()

    def show_mini(self) -> None:
        """直接以 mini 态出现（她回了话 / 有进度要报）。"""
        if self._state == STATE_OPEN:
            return
        self._state = STATE_MINI
        self._apply_state_children()
        self._show_window()
        if self.size() != QSize(MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2):
            self.resize(MINI_W + ISLAND_MARGIN * 2, MINI_H + ISLAND_MARGIN * 2)
        self._sync_pulse()

    def dismiss(self) -> None:
        """整颗收掉（点 ✕ / 桌宠隐藏 / 程序退出）。"""
        self._state = STATE_HIDDEN
        self._busy = False
        self._pulse.stop()
        self._follow.stop()
        self._follow_rect = None
        self.hide()

    # ------------------------------------------------------------ 内部
    def _show_window(self) -> None:
        show_mini = self._state == STATE_MINI
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, show_mini)
        self._place()
        if not self.isVisible():
            self.show()
        self.raise_()
        self._follow.start()

    def _animate_to(self, w: int, h: int) -> None:
        target = QSize(int(w), int(h))
        self._anim.stop()
        if not self.isVisible():
            self.resize(target)
            return
        self._anim.setStartValue(self.size())
        self._anim.setEndValue(target)
        self._expanding = self._state == STATE_OPEN
        self._anim.start()

    def _on_anim_done(self) -> None:
        if self._state == STATE_OPEN and self._expanding:
            self._focus_input()
        self._expanding = False

    def _focus_input(self) -> None:
        """弹开就聚焦：右键「和她聊天」之后不该还要再点一下输入框。"""
        try:
            self.activateWindow()
            self.input.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:  # pragma: no cover - 窗口正在销毁
            logging.debug("island: 聚焦失败", exc_info=True)

    def _on_close_clicked(self) -> None:
        """✕ = 直接关掉，不再收成常驻 mini。

        收成 mini 会把胶囊一直挂在屏幕上（发一句就弹回来一次），用户点 ✕ 就是
        不想看见它——这里跟 Esc 分开：Esc 只是退出输入、胶囊继续报进度。
        """
        self.dismiss()
        self.closed.emit()

    def _emit_submit(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.submitted.emit(text)

    # ------------------------------------------------------------ 定位
    def _anchor_rect(self) -> QRect | None:
        pet = self._pet
        getter = getattr(pet, "visible_content_rect", None)
        if not callable(getter):
            return None
        try:
            rect = QRect(getter())
        except Exception:
            return None
        return None if rect.isNull() else rect

    def _place(self) -> None:
        anchor = self._anchor_rect()
        if anchor is None:
            screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1040)
            self.move(geo.right() - self.width() - 60, geo.bottom() - self.height() - 40)
            return
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1040)
        x, y = island_geometry(anchor, self.width(), self.height(), geo)
        self.move(x, y)

    def _follow_tick(self) -> None:
        if not self.isVisible():
            self._follow.stop()
            return
        anchor = self._anchor_rect()
        if anchor is None:
            return
        if anchor == self._follow_rect:
            return
        self._follow_rect = QRect(anchor)
        self._place()

    # ------------------------------------------------------------ 事件
    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._follow_rect = None
        self._follow.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._follow.stop()
        super().hideEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        # mini 整颗可点：点它 = 打开输入（原型里胶囊就是入口）
        if self._state == STATE_MINI and event.button() == Qt.MouseButton.LeftButton:
            self.expand()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._state == STATE_OPEN:
            self.collapse()
            self.dismissed.emit()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 绘制
    def _sync_pulse(self) -> None:
        want = self._state == STATE_MINI and self.isVisible() and self._busy
        if want and not self._pulse.isActive():
            self._pulse.start()
        elif not want and self._pulse.isActive():
            self._pulse.stop()
            self.update()

    def _tick_pulse(self) -> None:
        self._phase = (self._phase + 0.22) % (math.pi * 2)
        self.update()

    def _capsule_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(
            ISLAND_MARGIN, ISLAND_MARGIN, -ISLAND_MARGIN, -ISLAND_MARGIN
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        del event
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        body = self._capsule_rect()
        radius = body.height() / 2.0

        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)

        # 投影：贴在胶囊下方，别让它在浅桌面上「浮不起来」
        p.setPen(Qt.PenStyle.NoPen)
        for offset, alpha in _SHADOW_LAYERS:
            layer = QPainterPath()
            layer.addRoundedRect(body.translated(0, offset), radius, radius)
            p.setBrush(QColor(6, 10, 22, alpha))
            p.drawPath(layer)

        fill = QLinearGradient(body.topLeft(), body.bottomLeft())
        fill.setColorAt(0.0, ISLAND_BG_TOP)
        fill.setColorAt(1.0, ISLAND_BG_BOTTOM)
        p.setBrush(fill)
        pen = QPen(ISLAND_EDGE_HOVER
                   if self._state == STATE_MINI and self.underMouse() else ISLAND_EDGE)
        pen.setWidthF(1.0)
        p.setPen(pen)
        p.drawPath(path)

        # 顶部内高光：一条极淡的亮线，像玻璃边缘
        hi = QPainterPath()
        hi.addRoundedRect(body.adjusted(1.5, 1.2, -1.5, -1.2), radius - 1.5, radius - 1.5)
        p.setPen(QPen(QColor(255, 255, 255, 16), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(hi)

        if self._state == STATE_MINI:
            self._paint_mini(p, body)
        p.end()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().leaveEvent(event)
        self.update()

    def _paint_mini(self, p: QPainter, body: QRectF) -> None:
        """小金点 + 一行状态字，整体居中（原型 `.isl-mini` 的 flex 居中）。

        点常亮金色，忙时只加呼吸（scale .75→1.15 / opacity .55→1）；文字色恒
        ``#dbe1f0``。忙闲不换颜色：这颗点会常驻在桌面上报进度，一灰就像掉线。
        """
        fm = QFontMetrics(self.font())
        avail = body.width() - 2 * MINI_PAD_X - MINI_DOT_PX - MINI_DOT_GAP
        label = fit_status(self._status, fm, int(avail))
        text_w = float(fm.horizontalAdvance(label)) if label else 0.0
        total = MINI_DOT_PX + (MINI_DOT_GAP + text_w if label else 0.0)
        left = body.center().x() - total / 2.0
        cy = body.center().y()

        scale = 1.0
        alpha = 1.0
        if self._busy:
            wave = 0.5 + 0.5 * math.sin(self._phase)
            scale = 0.75 + 0.40 * wave
            alpha = 0.55 + 0.45 * wave

        cx = left + MINI_DOT_PX / 2.0
        glow_r = MINI_DOT_GLOW_PX * scale
        gold = ISLAND_ACCENT
        glow = QRadialGradient(QPointF(cx, cy), glow_r)
        glow.setColorAt(0.0, QColor(gold.red(), gold.green(), gold.blue(), int(150 * alpha)))
        glow.setColorAt(1.0, QColor(gold.red(), gold.green(), gold.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        dot = QColor(gold)
        dot.setAlphaF(alpha)
        p.setBrush(dot)
        p.drawEllipse(QPointF(cx, cy), MINI_DOT_PX / 2.0 * scale, MINI_DOT_PX / 2.0 * scale)

        if not label:
            return
        p.setPen(ISLAND_TEXT)
        p.drawText(
            QRectF(left + MINI_DOT_PX + MINI_DOT_GAP, body.top(), text_w + 1.0, body.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            label,
        )


# ---------------------------------------------------------------- 便捷入口
def alive(widget) -> bool:
    """Qt 包装是否还指着活着的 C++ 对象（单例复用前先验尸）。"""
    if widget is None:
        return False
    if shiboken6 is None:
        return True
    try:
        return bool(shiboken6.isValid(widget))
    except Exception:  # pragma: no cover
        return False
