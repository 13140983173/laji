# -*- coding: utf-8 -*-
"""头顶消息中心外壳：裸消息 logo 待机 → 新消息胶囊通报 → 审批卡。

定稿 A 方案（``docs/prototypes/pet-message-center-real.html``）：

1. 通报：来了新审批先弹一粒胶囊（图标 + 一句人话 + 计数），2.5 秒自动缩回 logo；
2. 待办在身：金色消息 logo + 计数常驻她头侧，点了摊开审批卡；
3. 清空：连 logo 一起消失——没消息不该在头顶留一枚白泡占地方。

定稿 A 方案的「干净白灰待机 logo」在实机被否（2026-11-02：审批做完白泡还挂着，
像还有事没完），砍掉：徽章只在有消息时存在。

**审批卡两套版式**（``docs/prototypes/pet-approval-card-variants.html`` 的 B / E）：

- ``glass``（B 玻璃分段，默认）：整表摊开，每行一条。左缘一根分类色条代替
  分类标签，右侧「拒绝｜允许」合成一颗分段按钮——两个按钮贴在一起，不容易看错边。
- ``focus``（E 一次一张）：一次只问一条，大标题 + 两个等宽大按钮 + 顶部倒计时
  进度条，多条靠底部 ‹ 1/3 › 翻页。误触率最低，代价是第二条要多点一次。

版式由 ``config.json`` 的 ``approval_card_style`` 选（glass / focus），壳层每一轮
同步时对齐一次：手改配置不用重启桌宠。

本类只是**视图**：条目由壳层整表同步进来（``set_entries``），动作经构造时给的回调
交回去。它不认识 run、不认识 laji_service、也不自己轮询 daemon——徽章与小工位两张
视图由 ``AppShell`` 一处对账，免得两边各记一份后对不上（旧实现正是各喂一份：工位没
开时事件直接丢，工位打开后也不重放，于是「待审批」永远是空的）。

logo 不抢焦点、不激活（``WindowDoesNotAcceptFocus``）：它只是她头顶的一个记号，
每 7 秒一轮的新审批不能打断用户正在打的字。
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .tool_names import (
    approval_detail,
    approval_headline,
    normalize_wire_tool_name,
)

log = logging.getLogger(__name__)

# 侧挂：审批族（logo/胶囊/展开卡）挂她身侧的水平间距（原型 .inbox left:46px）。
SIDE_GAP = 18
# 372 时「要用...：write tool ...」只能折成两行；标题行还要放工作区 chip。
CARD_W = 372
# 卡片里最多列几条：再多就盖住半块桌面，剩下的指路去小工位。
MAX_ROWS = 4
# 待机裸 logo 的边长与里面气泡图标的边长（原型 38/30）。
LOGO_SIZE = 38
ICON_SIZE = 30
# 胶囊通报挂几秒：原型 2.5s；期间点一下就当场展开卡片。
CAPSULE_MS = 2500
# 胶囊那句人话最长多少像素，放不下就截断。
CAPSULE_TEXT_W = 220

#: 审批卡版式（``config.json`` 的 ``approval_card_style``）。
STYLE_GLASS = "glass"
STYLE_FOCUS = "focus"
CARD_STYLES = (STYLE_GLASS, STYLE_FOCUS)
DEFAULT_CARD_STYLE = STYLE_GLASS

#: 倒计时剩这么多秒时换成告警色（烫手了，别再看别的）。
URGENT_SECS = 20

# 定稿原型里的消息气泡：圆角气泡描边 + 三粒点（currentColor 换成实际颜色再喂渲染器）。
SVG_MSG = (
    '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M12 3.2c-5.2 0-9.3 3.5-9.3 7.9 0 2.05.93 3.9 2.44 5.3l-.62 3.5a.6.6 0 0 0 .85.65'
    'l3.55-1.72c1 .3 2 .45 3.08.45 5.2 0 9.3-3.5 9.3-7.9S17.2 3.2 12 3.2z" '
    'stroke="{color}" stroke-width="1.9" stroke-linejoin="round"/>'
    '<circle cx="8" cy="11.1" r="1.15" fill="{color}"/>'
    '<circle cx="12" cy="11.1" r="1.15" fill="{color}"/>'
    '<circle cx="16" cy="11.1" r="1.15" fill="{color}"/>'
    "</svg>"
)
# 有待办 = 金色（跟她审批卡的「允许」同一口音）；干净 = 白灰，隐在桌面里。
COLOR_HOT = "#ffd166"
COLOR_CALM = "#e9eef7"

# 分类 → (键, 中文标签, 色条颜色)。键同时是 QSS 属性选择器的值，别随手改。
_CATEGORIES = {
    "write": ("write", "写入", "#f5c34d"),
    "shell": ("shell", "命令", "#7cc6ff"),
    "mcp": ("mcp", "外部", "#c9a7ff"),
    "ask": ("ask", "提问", "#7fd8a6"),
    "tool": ("tool", "工具", "#5a6270"),
}
_SHELL_TOOLS = {"run_terminal"}
_WRITE_TOOLS = {"write_file", "apply_patch", "edit_files", "delete_file", "rename_file"}
#: 选择题在卡里最多铺几个选项按钮：再多（向导/超长清单）就指路去会话里答。
MAX_OPTIONS = 6


def normalize_card_style(value) -> str:
    """配置值 → 版式标识。不认识的写错一律回默认（glass），别让卡片消失。"""
    raw = str(value or "").strip().lower()
    if raw in {"focus", "one", "single", "one-by-one"}:
        return STYLE_FOCUS
    return STYLE_GLASS


def category_of(tool_name: str) -> tuple[str, str, str]:
    """工具 → (键, 中文标签, 色条色)。MCP 一律「外部」，其余按工具族归类。"""
    internal = normalize_wire_tool_name(str(tool_name or ""))
    if internal.startswith("mcp:"):
        return _CATEGORIES["mcp"]
    short = internal.split(":")[-1]
    if short in _SHELL_TOOLS:
        return _CATEGORIES["shell"]
    if short in _WRITE_TOOLS:
        return _CATEGORIES["write"]
    return _CATEGORIES["tool"]


def remaining_secs(entry: dict) -> int | None:
    """这条审批大概还剩几秒。

    daemon 只给总时长（``timeout_secs``），不给剩余；用「第一次见到它的时刻」
    做近似——扫描是 7 秒一轮，误差不超过一轮。拿不到时长就返回 None（不画倒计时，
    比画个假的 30s 好）。
    """
    approval = entry.get("approval")
    total = int(getattr(approval, "timeout_secs", 0) or 0)
    if total <= 0:
        return None
    seen = entry.get("seen_at")
    if not isinstance(seen, (int, float)):
        return total
    return max(0, total - int(time.monotonic() - seen))


def _qss() -> str:
    return """
    QAbstractButton { background: transparent; border: 0; }
    #logo-count, #msg-capsule #cap-count {
        color: #241a05; font-size: 11px; font-weight: 700;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #ffe08a, stop:1 #f5c34d);
        border-radius: 9px; padding: 1px 5px;
    }
    #msg-capsule {
        background: rgba(24,28,36,0.97);
        border: 1px solid rgba(255,209,102,0.55);
        border-radius: 21px;
    }
    #msg-capsule #cap-icon {
        background: rgba(255,255,255,0.08); border-radius: 15px;
    }
    #msg-capsule #cap-text { color: #ffffff; font-size: 12.5px; }

    /* ---------- B 玻璃分段：整表摊开，一条一行 ---------- */
    #approval-glass {
        background: rgba(28,32,41,0.90);
        border: 1px solid rgba(255,255,255,0.13);
        border-radius: 16px;
    }
    #glass-head { background: transparent; }
    #glass-dot {
        background: #ffd166; border-radius: 3px;
    }
    #glass-title { color: #eef1f7; font-size: 12.5px; font-weight: 600; }
    #glass-sub { color: #6d7480; font-size: 11.5px; }
    #glass-x {
        padding: 0 4px; border: 0; background: transparent;
        color: #6d7480; font-size: 13px;
    }
    #glass-x:hover { color: #e7ecf5; }
    #glass-sep { background: rgba(255,255,255,0.065); }
    #glass-row { background: transparent; }
    #glass-bar { border-radius: 2px; background: #5a6270; }
    #glass-bar[cat="write"] { background: #f5c34d; }
    #glass-bar[cat="shell"] { background: #7cc6ff; }
    #glass-bar[cat="mcp"]   { background: #c9a7ff; }
    #glass-bar[cat="ask"]   { background: #7fd8a6; }
    #glass-what { color: #eef1f7; font-size: 12.5px; }
    #glass-ws {
        color: #b9c3d4; font-size: 10px; background: rgba(255,255,255,0.07);
        border-radius: 4px; padding: 1px 5px;
    }
    #glass-note { color: #9aa1af; font-size: 11px; }
    #glass-cd { color: #6d7480; font-size: 11px; }
    #glass-cd[urgent="1"] { color: #ff9a7a; }
    #glass-seg { border: 1px solid rgba(255,255,255,0.14); border-radius: 9px; }
    #glass-seg QPushButton {
        border: 0; background: transparent; color: #c9d2e0;
        font-size: 11px; padding: 5px 11px;
    }
    #glass-seg QPushButton:hover { background: rgba(255,255,255,0.08); }
    #glass-seg QPushButton[kind="no"] {
        border-top-left-radius: 8px; border-bottom-left-radius: 8px;
    }
    #glass-seg QPushButton[kind="yes"] {
        color: #ffd166; font-weight: 600; background: rgba(255,209,102,0.10);
        border-left: 1px solid rgba(255,255,255,0.14);
        border-top-right-radius: 8px; border-bottom-right-radius: 8px;
    }
    #glass-seg QPushButton[kind="yes"]:hover { background: rgba(255,209,102,0.20); }
    /* 选择题的选项按钮（玻璃卡两列铺、焦点卡通栏铺共用一套） */
    QPushButton#glass-opt {
        border: 1px solid rgba(255,255,255,0.14); border-radius: 8px;
        background: rgba(255,255,255,0.04); color: #dbe3f0;
        font-size: 11px; padding: 4px 9px;
    }
    QPushButton#glass-opt:hover {
        background: rgba(127,216,166,0.14); border-color: rgba(127,216,166,0.45);
        color: #ffffff;
    }
    QPushButton#glass-opt[role="skip"] {
        border-style: dashed; color: #9aa1af; background: transparent;
    }
    QPushButton#glass-opt[role="skip"]:hover { color: #e7ecf5; }
    /* 「其他…」自拟作答：按钮与展开后的输入框同一身形，点开不跳位 */
    QPushButton#glass-opt[role="custom"] { color: #9fd8b6; }
    QPushButton#glass-opt[role="custom"]:hover {
        background: rgba(127,216,166,0.14); border-color: rgba(127,216,166,0.45);
        color: #d9ffe9;
    }
    QLineEdit#glass-custom {
        border: 1px solid rgba(127,216,166,0.45); border-radius: 8px;
        background: rgba(255,255,255,0.06); color: #eef2f8;
        font-size: 11px; padding: 4px 9px;
        selection-background-color: rgba(127,216,166,0.35);
    }
    #glass-more { color: #6d7480; font-size: 10.5px; }
    #glass-foot { background: transparent; }
    #glass-link {
        padding: 2px 0; border: 0; background: transparent;
        color: #9aa1af; font-size: 11px;
    }
    #glass-link:hover { color: #e7ecf5; }

    /* ---------- E 一次一张：大标题 + 大按钮 + 倒计时条 ---------- */
    #approval-focus {
        background: #191d25;
        border: 1px solid rgba(255,255,255,0.11);
        border-radius: 18px;
    }
    #focus-bar-bg { background: rgba(255,255,255,0.08); }
    #focus-bar-fill {
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 #f5c34d, stop:1 #ff9a7a);
    }
    #focus-chip { color: #9aa1af; font-size: 10.5px; }
    #focus-title { color: #eef1f7; font-size: 17px; font-weight: 600; }
    #focus-sub { color: #9aa1af; font-size: 11.5px; }
    #focus-no {
        border: 1px solid rgba(255,255,255,0.16); background: transparent;
        color: #c9d2e0; font-size: 12.5px; font-weight: 600;
        border-radius: 10px; padding: 8px 0;
    }
    #focus-no:hover { background: rgba(255,255,255,0.07); }
    #focus-yes {
        border: 1px solid #ffeab0; color: #241a05;
        font-size: 12.5px; font-weight: 600; border-radius: 10px; padding: 8px 0;
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #ffe08a, stop:1 #f5c34d);
    }
    #focus-yes:hover {
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                    stop:0 #fff0b8, stop:1 #ffd166);
    }
    #focus-pager { color: #6d7480; font-size: 11px; }
    #focus-arrow {
        border: 1px solid #2e3542; background: transparent;
        color: #9aa1af; font-size: 11px; border-radius: 6px; padding: 0;
    }
    #focus-arrow:hover { background: rgba(255,255,255,0.08); color: #e7ecf5; }
    #focus-link {
        border: 0; background: transparent; color: #9aa1af; font-size: 11px;
        padding: 2px 0;
    }
    #focus-link:hover { color: #e7ecf5; }
    """


def _elide(label: QLabel, text: str, width: int) -> str:
    """单行放不下就截断：卡片宽度是固定的，宁可少几个字也不让标题折行。"""
    return label.fontMetrics().elidedText(
        str(text or ""), Qt.TextElideMode.ElideRight, max(40, width)
    )


def _ws_name(workspace) -> str:
    """哪条会话在等：只写末级目录名，长路径在卡片里放不下。"""
    name = str(workspace or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name or "本地"


def _degraded_detail(entry) -> str:
    """探不到 approval 时的说明行：watcher 已经组好了「哪边、什么事」，直接用它。

    降级只该丢按钮，不该丢内容——写死「这条还没探到详情」等于把
    ``approval_watch.describe(run)`` 白算一次。
    """
    message = " ".join(str((entry or {}).get("message") or "").split())
    return message or "这条还没探到详情，去会话里点头"


def _msg_pixmap(color: str, size: int) -> QPixmap:
    """按给定颜色渲染一枚消息气泡 pixmap（通报胶囊里的小图标用）。"""
    renderer = QSvgRenderer(SVG_MSG.format(color=color).encode())
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return pixmap


class _LogoButton(QAbstractButton):
    """裸消息 logo：无底无框，就画一个气泡；右上角一粒金色计数。

    ``QAbstractButton`` 默认不画任何底子，正好——它自己负责把气泡图标画出来，
    待办在身时金色（hot），干净时白灰。
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._hot = False
        self._renderer = QSvgRenderer(SVG_MSG.format(color=COLOR_CALM).encode())
        self.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Laji 那边有消息")
        self._count = QLabel(self)
        self._count.setObjectName("logo-count")
        self._count.hide()

    def set_hot(self, hot: bool) -> None:
        hot = bool(hot)
        if hot == self._hot:
            return
        self._hot = hot
        self._renderer.load(SVG_MSG.format(color=COLOR_HOT if hot else COLOR_CALM).encode())
        self.update()

    def set_count_text(self, text: str | None) -> None:
        if not text:
            self._count.hide()
            return
        self._count.setText(text)
        self._count.adjustSize()
        self._count.move(self.width() - self._count.width() - 2, 0)
        self._count.show()

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._renderer.render(
            painter, QRectF(4, 4, LOGO_SIZE - 8, LOGO_SIZE - 8)
        )


class _CardBase(QFrame):
    """审批卡公共契约：整表进、动作出；倒计时自己刷。"""

    def __init__(self, *, on_resolve, on_locate, parent=None) -> None:
        super().__init__(parent)
        self._on_resolve = on_resolve
        self._on_locate = on_locate
        self._entries: list[dict] = []

    def set_entries(self, entries) -> None:
        self._entries = list(entries or [])
        self.rebuild()

    def rebuild(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def tick(self) -> None:  # pragma: no cover - 子类实现
        """每秒一次：只刷倒计时与进度条，不重建控件（重建会打断 hover）。"""


# ---------------------------------------------------------------- B 玻璃分段
class _AnswerEdit(QLineEdit):
    """「其他」自拟答案的行内输入框：回车交卷、Esc 反悔收回。"""

    cancelled = Signal()

    def keyPressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


def _fit_label(btn: QPushButton, text: str, width: int) -> str:
    """把选项文案截到按钮里放得下：卡是定宽的，溢出会被窗口裁掉半边（实机踩过）。"""
    fitted = btn.fontMetrics().elidedText(
        str(text or ""), Qt.TextElideMode.ElideRight, max(20, width)
    )
    btn.setText(fitted)
    if fitted != text:
        btn.setToolTip(text)  # 截掉的全文挪进 tooltip，别让答案只剩半个词
    return fitted


def _fill_option_buttons(
    lay, approval, run_id, on_resolve, *, columns: int = 2, avail: int = CARD_W
) -> str:
    """往布局里铺选项按钮（``glass-opt``），返回溢出提示文案（没有就空串）。

    点选项 = 作答（answer=label，主窗 onDecideOption 同口径）。``allow_custom``
    时垫一颗「其他…」：点了原地换成输入框，回车把自拟答案交回去——主窗
    QuestionsCard 的 custom 选项同语义；「跳过」虚线按钮最后压轴。
    三类按钮都横贯整行铺（选项才分列），每颗文案截到列宽以内：372px 定宽卡
    里按钮 sizeHint 超了会把卡撑破，文字顶出卡外。
    """
    options = tuple(getattr(approval, "options", ()) or ())
    shown = options[:MAX_OPTIONS]
    inner = max(60, avail - 6 * (columns - 1))
    col_text_w = inner // columns - 22  # 扣按钮左右 padding + 边框
    grid = QGridLayout()
    grid.setContentsMargins(0, 4, 0, 0)
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(5)

    def _mk_btn(text: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("glass-opt")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        _fit_label(btn, text, col_text_w)
        return btn

    for index, (_opt_id, label) in enumerate(shown):
        btn = _mk_btn(str(label))
        btn.clicked.connect(
            lambda _=False, text=str(label): on_resolve(run_id, True, answer=text)
        )
        grid.addWidget(btn, index // columns, index % columns)

    next_row = (len(shown) + columns - 1) // columns
    if getattr(approval, "allow_custom", False):
        custom = _mk_btn("其他…")
        custom.setProperty("role", "custom")
        edit = _AnswerEdit()
        edit.setObjectName("glass-custom")
        edit.setPlaceholderText("输入你的回答，回车提交")
        edit.setVisible(False)

        def _open_custom() -> None:
            custom.setVisible(False)
            edit.setVisible(True)
            edit.setFocus(Qt.FocusReason.MouseFocusReason)

        def _close_custom() -> None:
            edit.setVisible(False)
            custom.setVisible(True)

        custom.clicked.connect(_open_custom)
        edit.returnPressed.connect(
            lambda: on_resolve(run_id, True, answer=edit.text().strip())
            if edit.text().strip()
            else None
        )
        edit.cancelled.connect(_close_custom)
        grid.addWidget(custom, next_row, 0, 1, columns)
        grid.addWidget(edit, next_row, 0, 1, columns)
        next_row += 1

    skip = _mk_btn("跳过这题")
    skip.setProperty("role", "skip")
    skip.clicked.connect(lambda _=False: on_resolve(run_id, False, skipped=True))
    grid.addWidget(skip, next_row, 0, 1, columns)
    lay.addLayout(grid)
    rest = len(options) - len(shown)
    return f"还有 {rest} 个选项，去会话里答" if rest > 0 else ""


class _Row(QFrame):
    """玻璃卡的一条：分类色条 + 标题 + 说明 + 「拒绝｜允许」分段按钮。

    分段按钮是「一颗」控件（两个按钮贴在同一圈边框里）：允许侧淡金底 + 金字，
    两个动作挨着，鼠标移过去不会看错边。
    选择题（``approval.is_question``）没有拒绝/允许：色条换绿色，正文是题面，
    下面铺选项按钮直接作答（``_fill_option_buttons``）。
    """

    def __init__(self, entry: dict, *, on_resolve, on_locate, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("glass-row")
        self._run_id = str(entry.get("run_id") or "")
        approval = entry.get("approval")
        is_question = bool(getattr(approval, "is_question", False))
        tool = str(getattr(approval, "tool_name", "") or "")
        reason = str(getattr(approval, "reason", "") or "")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(13, 10, 12, 10)
        lay.setSpacing(10)

        bar = QFrame(self)
        bar.setObjectName("glass-bar")
        bar.setProperty("cat", "ask" if is_question else category_of(tool)[0])
        bar.setFixedWidth(3)
        bar.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        lay.addWidget(bar)

        body = QVBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(2)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        if is_question:
            what_text = str(getattr(approval, "question", "") or "") or "有题要你答"
        else:
            what_text = approval_headline(tool)
        what = QLabel(_elide(QLabel(), what_text, CARD_W - 200))
        what.setObjectName("glass-what")
        top.addWidget(what)
        ws = QLabel(_ws_name(entry.get("workspace")))
        ws.setObjectName("glass-ws")
        top.addWidget(ws)
        top.addStretch(1)
        body.addLayout(top)

        if is_question:
            note = QLabel(
                "点一个选项直接作答" if getattr(approval, "answerable", False)
                else "这道题在会话里答"
            )
            note.setObjectName("glass-note")
            body.addWidget(note)
            if getattr(approval, "answerable", False):
                more = _fill_option_buttons(
                    body, approval, self._run_id, on_resolve, columns=2, avail=CARD_W - 38
                )
                if more:
                    rest = QLabel(more)
                    rest.setObjectName("glass-more")
                    body.addWidget(rest)
        else:
            detail = (
                approval_detail(tool, reason) if approval is not None
                else _degraded_detail(entry)
            )
            note = QLabel()
            note.setObjectName("glass-note")
            note.setText(_elide(note, detail, CARD_W - 180))
            note.setToolTip(f"{tool} · {reason}".strip(" ·") or detail)
            body.addWidget(note)
        lay.addLayout(body, 1)

        self._cd = QLabel("")
        self._cd.setObjectName("glass-cd")
        lay.addWidget(self._cd)

        if approval is not None and not is_question:
            seg = QFrame(self)
            seg.setObjectName("glass-seg")
            seg_lay = QHBoxLayout(seg)
            seg_lay.setContentsMargins(0, 0, 0, 0)
            seg_lay.setSpacing(0)
            for text, kind, approved in (("拒绝", "no", False), ("允许", "yes", True)):
                btn = QPushButton(text, seg)
                btn.setObjectName("glass-seg-btn")
                btn.setProperty("kind", kind)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(
                    lambda _=False, ok=approved: on_resolve(self._run_id, ok)
                )
                seg_lay.addWidget(btn)
            lay.addWidget(seg)
        self.refresh_time(entry)

    def refresh_time(self, entry: dict) -> None:
        left = remaining_secs(entry)
        if left is None:
            self._cd.hide()
            return
        self._cd.setText(f"{left}s")
        self._cd.setProperty("urgent", "1" if left <= URGENT_SECS else "0")
        self._cd.style().unpolish(self._cd)
        self._cd.style().polish(self._cd)
        self._cd.show()


class _GlassCard(_CardBase):
    """B 玻璃分段：整表摊开，一条一行，底部只留一个「在会话里看」的逃逸口。

    底部**没有**「全部允许」：这里混着不同 run 的审批，一键全放行可能顺手批准
    一条 shell 命令。批量语义（本次运行全部允许）只在主窗的小工位里有——那里
    是同一个 run。
    """

    def __init__(self, *, on_resolve, on_locate, parent=None) -> None:
        super().__init__(on_resolve=on_resolve, on_locate=on_locate, parent=parent)
        self.setObjectName("approval-glass")
        self._rows: list[_Row] = []

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        head = QWidget(self)
        head.setObjectName("glass-head")
        head_lay = QHBoxLayout(head)
        head_lay.setContentsMargins(13, 11, 10, 10)
        head_lay.setSpacing(8)
        dot = QFrame(head)
        dot.setObjectName("glass-dot")
        dot.setFixedSize(7, 7)
        head_lay.addWidget(dot)
        title = QLabel("等你点头")
        title.setObjectName("glass-title")
        head_lay.addWidget(title)
        self._count = QLabel("")
        self._count.setObjectName("glass-sub")
        head_lay.addWidget(self._count)
        head_lay.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("glass-x")
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self._request_collapse)
        head_lay.addWidget(close)
        lay.addWidget(head)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(0)
        lay.addLayout(self._body)

        foot = QWidget(self)
        foot.setObjectName("glass-foot")
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(13, 9, 12, 10)
        foot_lay.setSpacing(8)
        self._rest = QLabel("")
        self._rest.setObjectName("glass-sub")
        foot_lay.addWidget(self._rest)
        foot_lay.addStretch(1)
        link = QPushButton("在会话里看")
        link.setObjectName("glass-link")
        link.setCursor(Qt.CursorShape.PointingHandCursor)
        link.clicked.connect(self._locate_first)
        foot_lay.addWidget(link)
        lay.addWidget(foot)
        self._foot = foot

    # 卡的收起动作由徽章注入（卡片不认识窗口状态）
    _on_collapse = None

    def _request_collapse(self) -> None:
        if callable(self._on_collapse):
            self._on_collapse()

    def _locate_first(self) -> None:
        if self._entries:
            self._on_locate(str(self._entries[0].get("run_id") or ""))

    def rebuild(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._rows = []
        shown = self._entries[:MAX_ROWS]
        self._count.setText(f"{len(self._entries)} 个操作")
        for index, entry in enumerate(shown):
            if index:
                sep = QFrame(self)
                sep.setObjectName("glass-sep")
                sep.setFixedHeight(1)
                sep.setVisible(True)  # 同上：隐藏项会被布局当 0 高
                self._body.addWidget(sep)
            row = _Row(
                entry,
                on_resolve=self._on_resolve,
                on_locate=self._on_locate,
                parent=self,
            )
            # 新加的控件默认是隐藏态，布局把隐藏项当 0 高：不显式设可见，卡片就
            # 不会长高，几条内容全叠在上一回的高度里（旧实现踩过同一个坑）。
            row.setVisible(True)
            self._body.addWidget(row)
            self._rows.append(row)
        rest = len(self._entries) - MAX_ROWS
        self._rest.setText(f"还有 {rest} 条，工位里一起看" if rest > 0 else "")
        self._foot.setVisible(bool(self._entries))

    def tick(self) -> None:
        for row, entry in zip(self._rows, self._entries):
            row.refresh_time(entry)


# ---------------------------------------------------------------- E 一次一张
class _FocusCard(_CardBase):
    """E 一次一张：大标题 + 两个等宽大按钮 + 顶部倒计时条 + 底部翻页。

    倒计时条按 ``timeout_secs`` 的近似剩余画；daemon 没给时长就不画（宁缺毋假）。
    """

    def __init__(self, *, on_resolve, on_locate, parent=None) -> None:
        super().__init__(on_resolve=on_resolve, on_locate=on_locate, parent=parent)
        self.setObjectName("approval-focus")
        self._index = 0
        self._on_collapse = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._bar_bg = QFrame(self)
        self._bar_bg.setObjectName("focus-bar-bg")
        self._bar_bg.setFixedHeight(3)
        self._bar_fill = QFrame(self._bar_bg)
        self._bar_fill.setObjectName("focus-bar-fill")
        self._bar_fill.setGeometry(0, 0, 0, 3)
        outer.addWidget(self._bar_bg)

        body = QWidget(self)
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(15, 13, 15, 0)
        body_lay.setSpacing(0)

        self._chip = QLabel("")
        self._chip.setObjectName("focus-chip")
        body_lay.addWidget(self._chip)

        self._title = QLabel("")
        self._title.setObjectName("focus-title")
        body_lay.addWidget(self._title)

        self._sub = QLabel("")
        self._sub.setObjectName("focus-sub")
        self._sub.setWordWrap(False)
        body_lay.addWidget(self._sub)

        # 选择题的选项区（普通审批隐藏）：选项通栏铺、每颗一行，「跳过」垫底。
        self._opts = QVBoxLayout()
        self._opts.setContentsMargins(0, 8, 0, 0)
        self._opts.setSpacing(5)
        body_lay.addLayout(self._opts)

        acts = QHBoxLayout()
        acts.setContentsMargins(0, 13, 0, 0)
        acts.setSpacing(8)
        self._no = QPushButton("拒绝")
        self._no.setObjectName("focus-no")
        self._no.setCursor(Qt.CursorShape.PointingHandCursor)
        self._no.setFixedHeight(36)
        self._no.clicked.connect(lambda: self._resolve(False))
        self._yes = QPushButton("允许")
        self._yes.setObjectName("focus-yes")
        self._yes.setCursor(Qt.CursorShape.PointingHandCursor)
        self._yes.setFixedHeight(36)
        self._yes.clicked.connect(lambda: self._resolve(True))
        acts.addWidget(self._no, 1)
        acts.addWidget(self._yes, 1)
        body_lay.addLayout(acts)
        outer.addWidget(body)

        foot = QWidget(self)
        foot_lay = QHBoxLayout(foot)
        foot_lay.setContentsMargins(15, 10, 15, 12)
        foot_lay.setSpacing(6)
        self._prev = QPushButton("‹")
        self._prev.setObjectName("focus-arrow")
        self._prev.setFixedSize(20, 20)
        self._prev.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev.clicked.connect(lambda: self.step(-1))
        self._pager = QLabel("")
        self._pager.setObjectName("focus-pager")
        self._next = QPushButton("›")
        self._next.setObjectName("focus-arrow")
        self._next.setFixedSize(20, 20)
        self._next.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next.clicked.connect(lambda: self.step(1))
        for widget in (self._prev, self._pager, self._next):
            foot_lay.addWidget(widget)
        foot_lay.addStretch(1)
        self._link = QPushButton("在会话里看 ›")
        self._link.setObjectName("focus-link")
        self._link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._link.clicked.connect(self._locate_current)
        foot_lay.addWidget(self._link)
        outer.addWidget(foot)

    # -- 翻页 ---------------------------------------------------------------
    def step(self, delta: int) -> None:
        total = len(self._entries)
        if total <= 1:
            return
        self._index = (self._index + delta) % total
        self.rebuild()

    def _current(self) -> dict:
        if not self._entries:
            return {}
        self._index = max(0, min(self._index, len(self._entries) - 1))
        return self._entries[self._index]

    # -- 动作 ---------------------------------------------------------------
    def _resolve(self, approved: bool) -> None:
        run_id = str(self._current().get("run_id") or "")
        if run_id:
            self._on_resolve(run_id, approved)

    def _locate_current(self) -> None:
        run_id = str(self._current().get("run_id") or "")
        self._on_locate(run_id)

    # -- 渲染 ---------------------------------------------------------------
    def rebuild(self) -> None:
        total = len(self._entries)
        entry = self._current()
        approval = entry.get("approval")
        tool = str(getattr(approval, "tool_name", "") or "")
        reason = str(getattr(approval, "reason", "") or "")
        is_question = bool(getattr(approval, "is_question", False))
        cat, cat_label, _color = (
            ("ask", "提问", None) if is_question else category_of(tool)
        )

        self._chip.setText(f"{cat_label} · {_ws_name(entry.get('workspace'))}")
        if is_question:
            title_text = str(getattr(approval, "question", "") or "") or "有题要你答"
        else:
            title_text = approval_headline(tool)
        self._title.setWordWrap(is_question)  # 题面常超一行，让它折，别截半句
        self._title.setText(
            _elide(self._title, title_text, CARD_W - 40) if not is_question else title_text
        )
        if is_question:
            detail = (
                "点一个选项直接作答"
                if getattr(approval, "answerable", False)
                else "这道题在会话里答"
            )
        else:
            detail = (
                approval_detail(tool, reason) if approval is not None
                else _degraded_detail(entry)
            )
        self._sub.setText(_elide(self._sub, detail, CARD_W - 40))
        self._sub.setToolTip("" if is_question else f"{tool} · {reason}".strip(" ·") or detail)

        # 选项区：先清空再铺（翻页/换条目都要重建）
        while self._opts.count():
            item = self._opts.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
            elif item.layout() is not None:
                while item.layout().count():
                    sub_item = item.layout().takeAt(0)
                    if sub_item.widget() is not None:
                        sub_item.widget().deleteLater()
        has_actions = approval is not None and not is_question
        self._no.setVisible(has_actions)
        self._yes.setVisible(has_actions)
        if approval is not None and is_question and getattr(approval, "answerable", False):
            more = _fill_option_buttons(
                self._opts, approval, str(entry.get("run_id") or ""), self._on_resolve,
                columns=1, avail=CARD_W - 30,
            )
            if more:
                rest = QLabel(more)
                rest.setObjectName("glass-more")
                self._opts.addWidget(rest)
        elif approval is not None and is_question:
            skip = QPushButton("跳过这题")
            skip.setObjectName("glass-opt")
            skip.setProperty("role", "skip")
            skip.setCursor(Qt.CursorShape.PointingHandCursor)
            skip.clicked.connect(
                lambda _=False: self._on_resolve(
                    str(entry.get("run_id") or ""), False, skipped=True
                )
            )
            self._opts.addWidget(skip)

        multi = total > 1
        for widget in (self._prev, self._pager, self._next):
            widget.setVisible(multi)
        self._pager.setText(f"{self._index + 1} / {total}" if multi else "")
        self._link.setVisible(bool(entry))
        self.tick()

    def tick(self) -> None:
        entry = self._current()
        left = remaining_secs(entry)
        if left is None:
            self._bar_bg.hide()
            return
        self._bar_bg.show()
        total = int(getattr(entry.get("approval"), "timeout_secs", 0) or 0) or 1
        done = max(0.0, min(1.0, 1.0 - left / float(total)))
        self._bar_fill.setGeometry(
            0, 0, int(self._bar_bg.width() * done), self._bar_bg.height()
        )

    def resizeEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        super().resizeEvent(event)
        self.tick()


class ApprovalBadge(QWidget):
    """她头顶的消息中心：裸 logo 待机 / 胶囊通报 / 审批卡（glass | focus 两版）。

    ``on_resolve(run_id, approved, answer="", skipped=False)``：回传审批；选择题点
    选项时 answer=label、skipped=True 表示跳过（approved 被忽略）。``on_locate(run_id)``：
    去主窗看那条会话。两者都由壳层注入——徽章自己够不到 laji_service，也不该够到。
    """

    def __init__(self, parent=None, *, on_resolve=None, on_locate=None, style=None) -> None:
        super().__init__(parent)
        self._on_resolve = on_resolve or (lambda run_id, approved, answer="", skipped=False: None)
        self._on_locate = on_locate or (lambda run_id: None)
        self._entries: list[dict] = []
        self._anchor = QRect()
        self._open = False
        self._suspended = False
        self._capsule_on = False
        self._style = normalize_card_style(style)
        self._seen: dict[str, float] = {}

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            # 状态记号不该成为键盘焦点窗口：每 7 秒一轮的新审批不能打断打字。
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setStyleSheet(_qss())

        # 待机态：裸消息 logo（干净白灰 / 有待办金色），右上角计数。
        self._logo = _LogoButton(self)
        self._logo.clicked.connect(self.toggle)

        # 通报态：新审批先弹一粒胶囊，2.5s 后缩回 logo。
        self._capsule = QFrame(self)
        self._capsule.setObjectName("msg-capsule")
        cap_lay = QHBoxLayout(self._capsule)
        cap_lay.setContentsMargins(5, 5, 14, 5)
        cap_lay.setSpacing(8)
        self._cap_icon = QLabel()
        self._cap_icon.setObjectName("cap-icon")
        self._cap_icon.setFixedSize(ICON_SIZE, ICON_SIZE)
        self._cap_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cap_icon.setPixmap(_msg_pixmap(COLOR_CALM, 17))
        self._cap_text = QLabel()
        self._cap_text.setObjectName("cap-text")
        self._cap_count = QLabel()
        self._cap_count.setObjectName("cap-count")
        for child in (self._cap_icon, self._cap_text, self._cap_count):
            cap_lay.addWidget(child)
        self._capsule.setCursor(Qt.CursorShape.PointingHandCursor)
        self._capsule.hide()
        self._capsule.installEventFilter(self)
        self._cap_timer = QTimer(self)
        self._cap_timer.setSingleShot(True)
        self._cap_timer.setInterval(CAPSULE_MS)
        self._cap_timer.timeout.connect(self._on_capsule_timeout)

        self._card: _CardBase | None = None
        self._build_card()

        # 倒计时/进度条：只在卡片摊开时跑（待机态没有时间可走）。
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._on_tick)

        self.hide()

    # -- 对外面 -------------------------------------------------------------
    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def card_style(self) -> str:
        return self._style

    def set_style(self, style) -> None:
        """切版式（配置驱动）：glass ↔ focus。摊开中就当场换，下次点击生效也一样。"""
        style = normalize_card_style(style)
        if style == self._style:
            return
        was_open = self._open
        self._style = style
        self._build_card()
        self._rebuild()
        if was_open and self._entries:
            self._apply_mode()
        else:
            self.hide()

    def set_entries(self, entries) -> None:
        """整表同步（``AppShell`` 是唯一数据源，这里不做增删推断）。"""
        rows = [e for e in (entries or []) if isinstance(e, dict) and e.get("run_id")]
        before = [str(e.get("run_id")) for e in self._entries]
        now = time.monotonic()
        live = {str(e.get("run_id")): e for e in rows}
        # 首次见到的时刻（倒计时近似用）：条目走了就忘掉，别让字典长期膨胀。
        self._seen = {
            rid: self._seen.get(rid, now) for rid in live if rid in self._seen
        }
        for rid in live:
            self._seen.setdefault(rid, now)
        for row in rows:
            row["seen_at"] = self._seen.get(str(row.get("run_id")), now)
        self._entries = rows
        ids = [str(e.get("run_id")) for e in rows]
        fresh = [rid for rid in ids if rid not in set(before)]
        if not rows:
            self._open = False
            self._capsule_on = False
            self._cap_timer.stop()
            self._capsule.hide()
            self._tick_timer.stop()
            self._rebuild()
            self._apply_mode()
            return
        if ids != before:
            self._rebuild()
            # 新条目先报一声：胶囊通报，别指望用户盯着她头顶的计数。
            if fresh and not self._open and not self._suspended:
                first = next(e for e in rows if str(e.get("run_id")) == fresh[0])
                self._announce(first)
        self._apply_mode()

    def set_anchor_rect(self, rect: QRect) -> None:
        """她头顶的全局矩形（sprite 身体框）。位置没变就不动窗。"""
        rect = QRect(rect)
        if rect == self._anchor:
            return
        was_live = not (self._anchor.isNull() or self._anchor.isEmpty())
        now_live = not (rect.isNull() or rect.isEmpty())
        self._anchor = rect
        if self.isVisible():
            if now_live:
                self._place()
            else:
                # 她隐了（全屏自动隐藏/换宠）：记号不能留在原地当幽灵。
                self.hide()
        elif now_live and not was_live:
            # 锚点从无到有（首次跟到她）：待机 logo 这才有了落脚的地方。
            self._apply_mode()

    def set_suspended(self, on: bool) -> None:
        """小工位开着：审批归左栏页，她头顶不再挂记号。"""
        on = bool(on)
        if on == self._suspended:
            return
        self._suspended = on
        if on:
            self._open = False
            self._capsule_on = False
            self._cap_timer.stop()
            self._capsule.hide()
            self._tick_timer.stop()
            self.hide()
        elif self._entries:
            self._apply_mode()

    def toggle(self) -> None:
        if self._suspended or not self._entries:
            return
        self._open = not self._open
        if self._open:
            self._dismiss_capsule()
        self._apply_mode()

    def collapse(self) -> None:
        if not self._open:
            return
        self._open = False
        self._apply_mode()

    # -- 内部 ---------------------------------------------------------------
    def _build_card(self) -> None:
        old = self._card
        if old is not None:
            old.hide()
            old.deleteLater()
        cls = _FocusCard if self._style == STYLE_FOCUS else _GlassCard
        card = cls(
            on_resolve=self._on_resolve,
            on_locate=self._on_locate,
            parent=self,
        )
        card._on_collapse = self.collapse
        card.hide()
        self._card = card

    def _on_tick(self) -> None:
        if self._open and self._card is not None:
            self._card.tick()

    def _announce(self, entry: dict) -> None:
        """新条目通报：图标 + 一句人话（「要用 xxx」/ 题面）+ 总数，2.5s 后自动缩回。"""
        approval = entry.get("approval")
        if getattr(approval, "is_question", False):
            text = (getattr(approval, "question", "") or "").strip().splitlines()
            text = text[0].strip() if text else "Laji 那边有题要你答"
        else:
            tool = str(getattr(approval, "tool_name", "") or "")
            text = approval_headline(tool) if approval is not None else "Laji 那边有操作等你点头"
        self._cap_text.setText(
            self._cap_text.fontMetrics().elidedText(
                text, Qt.TextElideMode.ElideRight, CAPSULE_TEXT_W
            )
        )
        total = len(self._entries)
        self._cap_count.setText("9+" if total > 9 else str(total))
        self._capsule.adjustSize()
        self._capsule_on = True
        self._cap_timer.start()
        self._apply_mode()

    def _dismiss_capsule(self) -> None:
        self._capsule_on = False
        self._cap_timer.stop()
        self._capsule.hide()

    def _on_capsule_timeout(self) -> None:
        self._capsule_on = False
        self._capsule.hide()
        self._apply_mode()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802（Qt 命名）
        """胶囊也是入口：点它直接摊开卡片，不等 2.5s。"""
        if watched is self._capsule and event.type() == event.Type.MouseButtonRelease:
            self.toggle()
            return True
        return super().eventFilter(watched, event)

    def _rebuild(self) -> None:
        if self._card is not None:
            # 整表交给卡片：玻璃卡自己按 MAX_ROWS 截断（要看得出「还有几条」），
            # 焦点卡要翻页，也得知道总条数。
            self._card.set_entries(self._entries)
        total = len(self._entries)
        # 待机 logo：有待办金身 + 计数；干净了就回到白灰、摘掉计数。
        self._logo.set_hot(total > 0)
        self._logo.set_count_text("" if total <= 0 else ("9+" if total > 9 else str(total)))

    def _settle(self, widget) -> None:
        """新加进布局的控件在 polish 之前 sizeHint 是 0。

        刚重建完就取尺会只拿到标题那几十像素，卡片因此不长高、几行内容叠在一起；
        取尺前先连嵌套布局一起让它们把字算一遍。
        """

        def walk(lay) -> None:
            lay.activate()
            for index in range(lay.count()):
                item = lay.itemAt(index)
                child = item.widget()
                if child is not None:
                    child.ensurePolished()
                    sub = child.layout()
                    if sub is not None:
                        walk(sub)
                elif item.layout() is not None:
                    walk(item.layout())

        root = widget.layout()
        if root is not None:
            walk(root)

    def _current_size(self) -> QSize:
        if self._open and self._card is not None:
            self._card.setFixedWidth(CARD_W)
            self._settle(self._card)
            lay = self._card.layout()
            if lay is None:
                return QSize(CARD_W, self._card.sizeHint().height())
            return QSize(CARD_W, lay.totalSizeHint().height())
        if self._capsule_on:
            self._settle(self._capsule)
            lay = self._capsule.layout()
            if lay is not None:
                hint = lay.totalSizeHint()
                if hint.width() > 0 and hint.height() > 0:
                    return hint
            return self._capsule.sizeHint()
        return QSize(LOGO_SIZE, LOGO_SIZE)

    def _apply_mode(self) -> None:
        if self._suspended:
            self._tick_timer.stop()
            self.hide()
            return
        if self._anchor.isNull() or self._anchor.isEmpty():
            # 还没跟到她：记号也不能瞎飘在 (0, 0)。
            self._tick_timer.stop()
            self.hide()
            return
        if not self._entries and not self._capsule_on and not self._open:
            # 干净了就整个消失（2026-11-02 实机口径）：审批做完还挂一枚白泡
            # 会被当成「还有事」——没消息才是好消息，头顶不该有常驻记号。
            if self._card is not None:
                self._card.hide()
            self._logo.hide()
            self._capsule.hide()
            self._tick_timer.stop()
            self.hide()
            return
        if self._open and self._entries and self._card is not None:
            self._dismiss_capsule()
            self._logo.hide()
            self._card.show()
            self._tick_timer.start()
        else:
            if self._card is not None:
                self._card.hide()
            self._tick_timer.stop()
            self._logo.setVisible(not self._capsule_on)
            self._capsule.setVisible(self._capsule_on)
        self._place()
        self.show()
        self.raise_()

    def _place(self) -> None:
        anchor = self._anchor
        if anchor.isNull() or anchor.isEmpty():
            return
        size = self._current_size()
        if size.width() <= 0 or size.height() <= 0:
            return
        self.resize(size)
        self._logo.setGeometry(0, 0, LOGO_SIZE, LOGO_SIZE)
        self._capsule.setGeometry(0, 0, size.width(), size.height())
        if self._card is not None:
            self._card.setGeometry(0, 0, size.width(), size.height())

        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1040)

        # 侧挂口径（原型 .a-ball left:54/top:-88 与 .inbox left:46/bottom:138）：
        # 审批族（logo/胶囊/展开卡）挂她身侧，右为默认、右边放不下翻左边；
        # 头顶正上方让给聊天对白（mist 泡尾巴指头、往上长）。
        if self._open:
            x = self._side_x(size.width(), anchor, avail, SIDE_GAP)
            # 卡的底边略高于她的头顶（原型 bottom:138px，而头顶在 120px）。
            y = anchor.top() - SIDE_GAP - size.height()
        else:
            x = self._side_x(size.width(), anchor, avail, -6)
            # logo/胶囊贴在头侧：上沿落在身体上沿往下 ~1/4 处（原型 top:-88/120）。
            y = anchor.top() + int(anchor.height() * 0.24)
        x = max(avail.left() + 4, min(x, avail.right() - size.width() - 4))
        y = max(avail.top() + 4, min(y, avail.bottom() - size.height() - 4))
        self.move(x, y)

    def _side_x(self, width: int, anchor: QRect, avail: QRect, gap: int) -> int:
        """挂她哪一侧：默认右缘贴着身体右侧（gap<0 表示略微压进身沿）；
        右边放不下翻左边；两边都紧就取还能塞下的位置。"""
        right = anchor.right() + gap
        if right + width <= avail.right() - 4:
            return right
        left = anchor.left() - gap - width
        if left >= avail.left() + 4:
            return left
        return max(avail.left() + 4, min(right, avail.right() - width - 4))
