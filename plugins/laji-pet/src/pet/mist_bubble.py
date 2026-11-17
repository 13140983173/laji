# -*- coding: utf-8 -*-
"""贴身对白（MistBubble）——v3 C 方案里「她的话」在真机上的样子。

原型：``.workbuddy/scratch/laji-pet-ui-v3-variants.html`` 的 **C · 贴身对白**。
形态照搬 ``#sC .bubble``：

- 白底面板 ``#fdfdfb``、墨字 ``#232a42``，圆角 ``18 18 18 5``（左下收角）；
- 左上角压着一条**金色名字标签**（``#f2c063`` → ``#e8a33d`` 渐变，溢出面板上沿
  9px），写她的角色显示名；
- 右下角一只 9px 的三角**尾巴**，尖朝下指着她的头——「这是她贴着你说的话」；
- 面板自己带投影，所以**不再需要判断落脚背景**（v2 的雾在白窗上会隐身，
  那时才要抓屏采样；实心面板 + 投影深浅桌面都成立，也省掉每次显示的抓屏）。

模块名与公开 API 沿用 v2（调用点不动）：``mist_text`` / ``clamp_point`` /
``mist_position`` / ``MistBubble`` / ``mist_reply`` / ``mist_clear``。
快速对话回复、审批、Laji 侧等拍板提醒都还走这里。
"""
from __future__ import annotations

import logging
import re

try:  # PySide 的 C++ 存活探测；缺了就退化成「不复检」（不影响正常路径）
    import shiboken6
except Exception:  # pragma: no cover - 只在裁剪过的运行环境里发生
    shiboken6 = None

from PySide6.QtCore import (
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QTimer,
    Qt,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QApplication, QWidget

from .speech_bubble_text import truncate_bubble_text

# ---- 面板（对齐原型 #sC .bubble）------------------------------------------
BUBBLE_MAX_TEXT_WIDTH = 280   # 文本列宽上限（px），同原型 max-width
BUBBLE_MAX_CHARS = 72         # 她一次最多说这么多字，再多就截断
BUBBLE_FONT_PX = 15           # 原型 14.5px，取整到 15 与 v2 字号一致
BUBBLE_LINE_HEIGHT = 25       # ≈ 1.65 × 15，原型 line-height:1.65
BUBBLE_PAD_X = 18
BUBBLE_PAD_Y = 13
BUBBLE_RADIUS = 18
BUBBLE_RADIUS_BL = 5          # 左下收角（尾巴在右下，见原型 border-radius）
BUBBLE_BG = QColor("#fdfdfb")
BUBBLE_INK = QColor("#232a42")
# 投影（原型 0 14px 34px + 0 2px 8px）：无模糊 API，用多层递减透明度叠出软边。
# 最大 14+11 正好吃满 BUBBLE_MARGIN_BOTTOM，所以下沿不会被窗口裁成硬边。
BUBBLE_SHADOW_LAYERS = ((2, 2, 22), (5, 4, 16), (9, 7, 12), (14, 11, 8))

# ---- 尾巴 ----------------------------------------------------------------
BUBBLE_TAIL_W = 18            # 三角底边宽（原型两条 9px 透明边）
BUBBLE_TAIL_H = 9             # 尖长（border-top:9px）
BUBBLE_TAIL_INSET = 16        # 三角底边右端距面板右缘（原型 right:16px）

# ---- 名字标签 ------------------------------------------------------------
BUBBLE_TAG_OVERHANG = 9       # 标签上沿溢出面板顶边（原型 top:-9px）
BUBBLE_TAG_LEFT = 15          # 距面板左缘（原型 left:15px）
BUBBLE_TAG_PAD_X = 9         # 原型 padding:1px 9px
BUBBLE_TAG_H = 16             # 原型 1px 上下内边距 + 10.5px 行盒 ≈ 15
BUBBLE_TAG_RADIUS = 8         # 原型 border-radius:9px（高度更矮，取半高内）
BUBBLE_TAG_FONT_PX = 11       # 原型 10.5px（QFont 只收整像素）
BUBBLE_TAG_INK = QColor("#241a06")
BUBBLE_TAG_FROM = QColor("#f2c063")
BUBBLE_TAG_TO = QColor("#e8a33d")
# 原型 box-shadow:0 3px 8px rgba(0,0,0,.25)——无模糊 API，同样叠层近似
BUBBLE_TAG_SHADOW_LAYERS = ((1, 2, 40), (2, 3, 26), (3, 5, 14))

# ---- 窗口留白（投影 / 标签 / 尾巴都在面板外，窗口必须装得下）--------------
BUBBLE_MARGIN_X = 16
BUBBLE_MARGIN_TOP = 22        # 标签外溢 9 + 投影
BUBBLE_MARGIN_BOTTOM = 34     # 尾巴 9 + 投影

BUBBLE_HOLD_DEFAULT_MS = 4200  # 说完到开始收起的停留
BUBBLE_FADE_MS = 620
BUBBLE_FOLLOW_MS = 500         # 宠物移动后贴回去的比对周期
# 尾巴尖要落的那一点：竖直方向按身体框取比例（正常在头顶，审批压到腰侧），
# 水平方向正常取她中心、审批取左肩——避免盖住她的脸。
BUBBLE_TIP_Y_RATIO = 0.06
# 尾巴尖再整体上提一点点：贴着头皮真机上像「顶在脑袋上」，原型里它是浮在她头顶的。
BUBBLE_TIP_LIFT = 16
BUBBLE_TIP_LOW_Y_RATIO = 0.72
BUBBLE_TIP_LOW_X_RATIO = 0.10

# 行首禁则：这些字符不能站在一行开头（浏览器默认就这么断，Qt 手写折行得自己守），
# 否则「要现在定吗」+「？」会把一个问号单独甩到下一行。
_NO_LINE_START = "、。，．？！：；）〕］｝〉》」』】…·ー～”’%"


# ---------------------------------------------------------------- 纯函数
def _plain(text: str) -> str:
    """回复文本 → 平话：剥代码围栏/标题/列表点/粗体/反引号，**保留下划线**。

    不能直接用 ``speech_bubble_text.normalize_bubble_text``：它把 ``_`` 也当 Markdown
    强调符剥掉，``builtin:run_terminal`` 会变成 ``runterminal``——审批里工具名就错了。
    """
    value = str(text or "").replace("```", " ")
    value = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", value)
    value = re.sub(r"(?m)^\s*[-*+]\s+", "", value)
    value = re.sub(r"\*\*|__|`", "", value)
    return re.sub(r"\s+", " ", value).strip()


def mist_text(text: str) -> str:
    """任意回复文本 → 对白里那几行字（纯函数，可单测）。

    Markdown 压成平话、空白折掉、超长截断——她一次只装得下「一口气说的话」。
    """
    return truncate_bubble_text(_plain(text), BUBBLE_MAX_CHARS)


def _tokens(text: str) -> list[str]:
    """切成换行单位：西文词/数字连写算一个，其余逐字（CJK 逐字断行）。"""
    return re.findall(r"[A-Za-z0-9_:/.\-]+|\s+|.", text)


def _avoid_line_start_punct(lines: list[str]) -> list[str]:
    """行首禁则：把本行末字下放，先把下一行开头的标点接回去（纯函数，可单测）。"""
    for index in range(1, len(lines)):
        while lines[index] and lines[index][0] in _NO_LINE_START and len(lines[index - 1]) > 1:
            lines[index] = lines[index - 1][-1] + lines[index]
            lines[index - 1] = lines[index - 1][:-1].rstrip()
    return lines


def wrap_lines(text: str, fm: QFontMetrics, max_width: int) -> list[str]:
    """按像素宽贪心折行（纯函数，可单测）；CJK 逐字断、西文按词断。

    比整列还长的单词（长 URL、无空格的串）**逐字硬断**：不硬断的话面板会被
    撑过 280px 的列宽上限，桌面上的白底方块会横穿别人的窗口。
    """
    lines: list[str] = []
    current = ""
    for token in _tokens(text):
        if not current and token.isspace():
            continue
        if fm.horizontalAdvance(token) > max_width:
            for char in token:
                if current and fm.horizontalAdvance(current + char) > max_width:
                    lines.append(current.rstrip())
                    current = ""
                current += char
            continue
        candidate = current + token
        if not current or fm.horizontalAdvance(candidate) <= max_width:
            current = candidate
            continue
        lines.append(current.rstrip())
        current = "" if token.isspace() else token
    if current.strip():
        lines.append(current.rstrip())
    return _avoid_line_start_punct(lines) or [""]


def surface_size_for_lines(lines: list[str], fm: QFontMetrics) -> tuple[int, int]:
    """面板本体尺寸（不含留白）：文本量 → (宽, 高)（纯函数，可单测）。"""
    text_w = max((fm.horizontalAdvance(line) for line in lines), default=0)
    text_h = max(1, len(lines)) * BUBBLE_LINE_HEIGHT
    return int(text_w) + BUBBLE_PAD_X * 2, text_h + BUBBLE_PAD_Y * 2


def win_size_for_surface(surface_w: int, surface_h: int) -> tuple[int, int]:
    """面板尺寸 → 窗口尺寸（含投影/标签/尾巴留白）（纯函数，可单测）。"""
    return (
        int(surface_w) + BUBBLE_MARGIN_X * 2,
        BUBBLE_MARGIN_TOP + int(surface_h) + BUBBLE_MARGIN_BOTTOM,
    )


def clamp_point(x: int, y: int, w: int, h: int, screen: QRect) -> tuple[int, int]:
    """把 (x, y, w, h) 窗口夹进屏幕可用区（纯函数，可单测）。"""
    x = max(screen.left() + 4, min(x, screen.right() - w - 4))
    y = max(screen.top() + 4, min(y, screen.bottom() - h - 4))
    return x, y


def tail_tip_point(anchor: QRect, low: bool) -> tuple[int, int]:
    """尾巴尖该指向她的哪一点（全局坐标，纯函数，可单测）。"""
    if low:
        x = anchor.left() + int(anchor.width() * BUBBLE_TIP_LOW_X_RATIO)
        y = anchor.top() + int(anchor.height() * BUBBLE_TIP_LOW_Y_RATIO)
    else:
        x = anchor.center().x()
        y = anchor.top() + int(anchor.height() * BUBBLE_TIP_Y_RATIO) - BUBBLE_TIP_LIFT
    return x, y


def tail_tip_local(w: int, h: int) -> tuple[int, int]:
    """尾巴尖在窗口里的位置（纯函数，可单测）：由窗口尺寸反推。"""
    surface_w = int(w) - BUBBLE_MARGIN_X * 2
    surface_h = int(h) - BUBBLE_MARGIN_TOP - BUBBLE_MARGIN_BOTTOM
    x = BUBBLE_MARGIN_X + surface_w - BUBBLE_TAIL_INSET - BUBBLE_TAIL_W // 2
    y = BUBBLE_MARGIN_TOP + surface_h + BUBBLE_TAIL_H
    return x, y


def mist_position(anchor: QRect, w: int, h: int, low: bool, screen: QRect) -> tuple[int, int]:
    """对白的位置（纯函数，可单测）：尾巴尖落在她头（或腰）上，其余往上长。"""
    tip_x, tip_y = tail_tip_point(anchor, low)
    local_x, local_y = tail_tip_local(w, h)
    return clamp_point(tip_x - local_x, tip_y - local_y, w, h, screen)


def _config_of(pet):
    """从形形色色的「宠物锚点」里翻出配置对象（拿不到返回 None）。

    两条拓扑的锚点形状不同：PetWindow 自己就是 ``cfg``；overlay 拓扑传进来的
    是 ``_SpriteChatAnchor``（``__slots__`` 只有 ``_shell``/``_sprite``），配置
    挂在壳上。只看第一层会得到空名字——真机上标签就整个消失了。
    """

    def _usable(obj):
        return obj is not None and callable(getattr(obj, "get", None))

    for attr in ("cfg", "config", "_config"):
        cfg = getattr(pet, attr, None)
        if _usable(cfg):
            return cfg
    for attr in ("_shell", "shell"):
        shell = getattr(pet, attr, None)
        if shell is None:
            continue
        for key in ("_config", "config", "cfg"):
            cfg = getattr(shell, key, None)
            if _usable(cfg):
                return cfg
    return None


def pet_display_name(pet) -> str:
    """她的角色显示名（名字标签用）；取不到就返回空串（不画标签）。"""
    if pet is None:
        return ""
    try:
        cfg = _config_of(pet)
        cid = str(getattr(pet, "character_id", "") or "")
        if not cid and cfg is not None:
            cid = str(cfg.get("character", "") or "")
        if not cid and cfg is not None:
            from . import catalog  # 延迟导入：只有画标签时才用

            cid = str(catalog.DEFAULT_CHARACTER)
        resolver = getattr(cfg, "character_alias", None)
        if cid and callable(resolver):
            alias = str(resolver(cid) or "").strip()
            if alias:
                return alias
        if cid:
            from . import catalog  # 延迟导入：只有画标签时才用

            name = str(catalog.character_call_name(cid) or "").strip()
            # 退成英文目录 id 就别挂标签（比不挂难看）
            if name and name != cid:
                return name
    except Exception:
        logging.debug("mist: 角色名解析失败", exc_info=True)
    return ""


# ---------------------------------------------------------------- 路径
def _rounded_path(rect: QRectF, radii: tuple[float, float, float, float]) -> QPainterPath:
    """四角半径各不相同的圆角矩形（Qt 的 addRoundedRect 只支持统一半径）。"""
    r_tl, r_tr, r_br, r_bl = radii
    path = QPainterPath()
    path.moveTo(rect.left() + r_tl, rect.top())
    path.lineTo(rect.right() - r_tr, rect.top())
    path.quadTo(rect.right(), rect.top(), rect.right(), rect.top() + r_tr)
    path.lineTo(rect.right(), rect.bottom() - r_br)
    path.quadTo(rect.right(), rect.bottom(), rect.right() - r_br, rect.bottom())
    path.lineTo(rect.left() + r_bl, rect.bottom())
    path.quadTo(rect.left(), rect.bottom(), rect.left(), rect.bottom() - r_bl)
    path.lineTo(rect.left(), rect.top() + r_tl)
    path.quadTo(rect.left(), rect.top(), rect.left() + r_tl, rect.top())
    path.closeSubpath()
    return path


def _tail_path(surface: QRectF) -> QPainterPath:
    """右下的尾巴三角：底边贴面板下沿，尖朝下指着她。"""
    right = surface.right() - BUBBLE_TAIL_INSET
    left = right - BUBBLE_TAIL_W
    tip_x = (left + right) / 2.0
    path = QPainterPath()
    path.moveTo(left, surface.bottom())
    path.lineTo(right, surface.bottom())
    path.lineTo(tip_x, surface.bottom() + BUBBLE_TAIL_H)
    path.closeSubpath()
    return path


def bubble_path(surface: QRectF) -> QPainterPath:
    """面板 + 尾巴的整块外形（纯函数，可单测）。"""
    radii = (BUBBLE_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS, BUBBLE_RADIUS_BL)
    return _rounded_path(surface, radii).united(_tail_path(surface)).simplified()


# ---------------------------------------------------------------- 组件
class MistBubble(QWidget):
    """常驻单例的对白窗口：show_mist() 上话，说完自动收起。"""

    # 点对白（她说完那面板）：调用方接「看全文」这类后续动作。
    clicked = Signal()

    _instance: "MistBubble | None" = None

    @classmethod
    def instance(cls) -> "MistBubble":
        """取常驻对白窗口；C++ 侧已被销毁就重建。

        Qt（或测试清场、会话结束、屏幕拓扑变化）可能把这层顶层窗口直接从 C++
        删掉，Python 单例却还攥着一个悬空包装——此时任何属性访问都会
        ``RuntimeError: Internal C++ object already deleted``。宁可重建，不复用死壳。
        """
        inst = cls._instance
        if inst is not None and shiboken6 is not None and not shiboken6.isValid(inst):
            cls._instance = inst = None
        if inst is None:
            inst = cls()
            cls._instance = inst
        return inst

    def __init__(self) -> None:
        super().__init__(
            None,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # 她说话不该抢输入焦点（用户可能正在别处打字）。
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)

        font = QFont()
        font.setFamilies(
            ("PingFang SC", "HarmonyOS Sans SC", "Microsoft YaHei UI", "Microsoft YaHei")
        )
        font.setPixelSize(BUBBLE_FONT_PX)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.4)
        self.setFont(font)

        self._text = ""
        self._pet = None
        self._low = False
        self._on_click = None
        self._tag = ""
        self.clicked.connect(self._fire_click)
        self._lines: list[str] = []
        self._surface_rect = QRectF()
        self._follow_rect: QRect | None = None

        self._follow = QTimer(self)
        self._follow.setInterval(BUBBLE_FOLLOW_MS)
        self._follow.timeout.connect(self._follow_tick)

        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._fade_out)

        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(BUBBLE_FADE_MS)
        self._anim.finished.connect(self._on_fade_done)
        self._fading_out = False

    # ------------------------------------------------------------ 入口
    def show_mist(
        self,
        text: str,
        pet_window=None,
        *,
        low: bool = False,
        ms: int = BUBBLE_HOLD_DEFAULT_MS,
        on_click=None,
        name: str = "",
    ) -> None:
        body = mist_text(text)
        if not body:
            return
        self._text = body
        self._pet = pet_window
        self._low = bool(low)
        self._on_click = on_click
        # 调用方自己解析出的名字优先（气泡知道自己的 character_id），
        # 拿不到再退回按锚点翻配置（两拓扑形状不同，见 _config_of）。
        self._tag = str(name or "").strip() or pet_display_name(pet_window)
        self._layout_for_text()
        self._place()
        self._hold.stop()
        self._hold.start(max(600, int(ms)))
        self._follow.start()
        # 流式逐段刷新时对白已经在屏上：**别再走一遍淡入**。每来一段就把不透明度
        # 拽回 0 再涨上来，屏幕上就是持续闪烁（原型没这问题，真机才有）。
        if self.isVisible() and not self._fading_out:
            self.update()
            return
        self._fading_out = False
        self._anim.stop()
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(min(220, BUBBLE_FADE_MS))
        self._anim.start()

    def _fire_click(self) -> None:
        """点对白：先把话交给调用方（通常是「展开全文」）。"""
        cb = self._on_click
        if callable(cb):
            try:
                cb()
            except Exception:
                logging.debug("mist: 点击回调失败", exc_info=True)

    def dismiss(self) -> None:
        self._hold.stop()
        self._fade_out()

    # ------------------------------------------------------------ 布局
    def _layout_for_text(self) -> None:
        """按文本量出面板 + 留白的窗口尺寸。

        窗口必须把**整块面板**（含标签外溢、尾巴、投影）装进去：面板一旦超出
        窗口边界就被裁成直角矩形（v2 真机截图就踩过——方方正正一块色块）。
        """
        fm = QFontMetrics(self.font())
        self._lines = wrap_lines(self._text, fm, BUBBLE_MAX_TEXT_WIDTH)
        surface_w, surface_h = surface_size_for_lines(self._lines, fm)
        w, h = win_size_for_surface(surface_w, surface_h)
        self._surface_rect = QRectF(
            float(BUBBLE_MARGIN_X),
            float(BUBBLE_MARGIN_TOP),
            float(surface_w),
            float(surface_h),
        )
        self.resize(w, h)

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
            # 没有锚点就退到主屏右下角——有总比没有强。
            primary = QApplication.primaryScreen()
            geo = primary.availableGeometry() if primary else QRect(0, 0, 1920, 1040)
            x = geo.right() - self.width() - 220
            y = geo.bottom() - self.height() - 320
        else:
            screen = QApplication.screenAt(anchor.center())
            if screen is None:
                screen = QApplication.primaryScreen()
            geo = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1040)
            x, y = mist_position(anchor, self.width(), self.height(), self._low, geo)
        self.move(x, y)

    def _follow_tick(self) -> None:
        if not self.isVisible():
            self._follow.stop()
            return
        anchor = self._anchor_rect()
        if anchor is None or anchor == self._follow_rect:
            return
        self._follow_rect = QRect(anchor)
        self._place()

    # ------------------------------------------------------------ 淡出
    def _fade_out(self) -> None:
        if not self.isVisible() or self._fading_out:
            return
        self._fading_out = True
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.setDuration(BUBBLE_FADE_MS)
        self._anim.start()

    def _on_fade_done(self) -> None:
        if self._fading_out and self.windowOpacity() <= 0.01:
            self._follow.stop()
            self._follow_rect = None
            self.hide()
            self._fading_out = False

    # ------------------------------------------------------------ 事件
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        # 点一下提前收起：对白是「说完就走」的话，不该等人。
        self.dismiss()
        self.clicked.emit()
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        if not self._text:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        surface = self._surface_rect
        path = bubble_path(surface)

        # 投影：面板 + 尾巴整体下移，逐层变大、逐层变淡。
        for dy, grow, alpha in BUBBLE_SHADOW_LAYERS:
            shadow = bubble_path(surface.adjusted(-grow, -grow, grow, grow))
            shadow.translate(0.0, float(dy))
            p.fillPath(shadow, QColor(20, 26, 45, alpha))

        # 面板本体。
        p.fillPath(path, BUBBLE_BG)
        edge = QPen(QColor(20, 26, 45, 18))
        edge.setWidthF(1.0)
        p.setPen(edge)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)

        self._paint_tag(p)
        self._paint_text(p)

        p.end()

    def _paint_tag(self, p: QPainter) -> None:
        """左上角压着面板上沿的金色名字标签（原型 .bubble::before）。"""
        if not self._tag:
            return
        font = QFont(self.font())
        font.setPixelSize(BUBBLE_TAG_FONT_PX)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.0)
        font.setWeight(QFont.Weight.Normal)  # 原型没设字重
        fm = QFontMetrics(font)
        tag_w = fm.horizontalAdvance(self._tag) + BUBBLE_TAG_PAD_X * 2
        surface = self._surface_rect
        tag = QRectF(
            surface.left() + BUBBLE_TAG_LEFT,
            surface.top() - BUBBLE_TAG_OVERHANG,
            float(tag_w),
            float(BUBBLE_TAG_H),
        )
        radius = min(float(BUBBLE_TAG_RADIUS), tag.height() / 2.0)
        p.setPen(Qt.PenStyle.NoPen)
        for dy, spread, alpha in BUBBLE_TAG_SHADOW_LAYERS:
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(
                tag.adjusted(-spread * 0.25, float(dy), spread * 0.25, float(dy + spread)),
                radius + spread * 0.25,
                radius + spread * 0.25,
            )
        # 原型 linear-gradient(160deg,...)：基本向下、略微右偏
        grad = QLinearGradient(
            tag.topLeft(), QPointF(tag.left() + tag.width() * 0.36, tag.bottom()))
        grad.setColorAt(0.0, BUBBLE_TAG_FROM)
        grad.setColorAt(1.0, BUBBLE_TAG_TO)
        p.setBrush(grad)
        p.drawRoundedRect(tag, radius, radius)
        p.setFont(font)
        p.setPen(BUBBLE_TAG_INK)
        p.drawText(tag, int(Qt.AlignmentFlag.AlignCenter), self._tag)

    def _paint_text(self, p: QPainter) -> None:
        """正文：左对齐、行高固定 25px（原型 line-height:1.65）。"""
        fm = QFontMetrics(self.font())
        surface = self._surface_rect
        p.setFont(self.font())
        p.setPen(BUBBLE_INK)
        block_h = len(self._lines) * BUBBLE_LINE_HEIGHT
        top = surface.top() + BUBBLE_PAD_Y
        # 文本块比面板矮时垂直居中（多行短句不会顶在面板上沿）。
        top += max(0.0, (surface.height() - BUBBLE_PAD_Y * 2 - block_h) / 2.0)
        for index, line in enumerate(self._lines):
            line_top = top + index * BUBBLE_LINE_HEIGHT
            baseline = line_top + (BUBBLE_LINE_HEIGHT - fm.height()) / 2.0 + fm.ascent()
            p.drawText(QPointF(surface.left() + BUBBLE_PAD_X, baseline), line)


# ---------------------------------------------------------------- 便捷入口
def mist_clear() -> None:
    """立刻收起对白（她开口问下一句时，上一句不该还挂在旁边）。"""
    try:
        inst = MistBubble._instance
        if inst is not None and inst.isVisible():
            inst.dismiss()
    except Exception:
        logging.debug("mist: 收起失败", exc_info=True)


def mist_reply(
    text: str,
    pet_window=None,
    *,
    low: bool = False,
    ms: int = BUBBLE_HOLD_DEFAULT_MS,
    on_click=None,
    name: str = "",
) -> bool:
    """把一句话放到她身边。任何失败只记日志，绝不打扰主流程。"""
    try:
        if QApplication.instance() is None:
            return False
        MistBubble.instance().show_mist(
            text, pet_window=pet_window, low=low, ms=ms, on_click=on_click, name=name
        )
        return True
    except Exception:
        logging.debug("mist: 显示失败", exc_info=True)
        return False
