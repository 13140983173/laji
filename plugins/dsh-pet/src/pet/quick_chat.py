# -*- coding: utf-8 -*-
"""快速对话气泡（Quick Chat）。

点击桌宠弹出的头顶小气泡输入框；回车发送，AI 回复在气泡内流式显示，
与完整 AI 对话窗口共用同一会话历史（SessionStore / ChatService）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QTimer, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .speech_bubble import BUBBLE_STYLE_PRESETS
from .tool_names import approval_text
from .speech_bubble_text import truncate_bubble_text
from . import catalog
from .mist_bubble import mist_clear, mist_reply
from .chat_island import ChatIsland, alive as island_alive

from .chat.models import ChatMessage
from .chat.markdown_view import markdown_to_html
from .chat.memory_extract import schedule_extraction
from .chat.prompt import PromptBuilder
from .acts.hint import act_prompt_block
from .chat.service import ChatService
from .agent_link.laji_run_service import LajiRunService
from .chat.session_store import SessionStore
from .chat.widgets import persist_chat_attachments

log = logging.getLogger(__name__)

_PAGE_SIZE = 500

# 气泡内 AI 回答的展示上限：超长回答不进气泡（头顶气泡只有几百像素），
# 截断到 _REPLY_PREVIEW_LIMIT 字并提示全文在聊天窗（气泡内提供直达按钮）。
_REPLY_PREVIEW_LIMIT = 150
_REPLY_PREVIEW_SUFFIX = "…（全文见聊天窗）"

# 「和她说话」的预设开场：点一下直接问，省掉“不知道能说什么”的门槛。
_QUICK_PROMPTS = ("摸摸头", "你在干嘛", "今天好累")

# 气泡里回填的历史轮数上限（按消息条数，一问一答算两条）。超过就只留最近几条，
# 长上下文交给完整聊天窗。
_HISTORY_REPLAY_LIMIT = 4
# 面板（工位）是完整对话面：一次回填整段上下文，用户往下滑能看回最早那句。
_WORKSTATION_REPLAY_LIMIT = 40

# 历史区里她的话只留一行：面板是「和她说话」的输入面，不是阅读器。
# 整段回答已经在她身侧的雾里（点雾展开），这里再贴一遍就成了一堵墙。
_HER_LINE_LIMIT = 44
# 「全文在哪」的提示：只在面板没开时才需要（面板里正文已经在流里了）
_HINT_SEE_FULL = "点雾看全文"


def _her_line(text: str, limit: int = _HER_LINE_LIMIT) -> str:
    """任意回答 → 历史区那一行「她说过什么」的痕迹（纯函数）。

    ``limit`` 是这一行最多几个字：头顶气泡给 44，小工位面板一行装不下那么多
    （310px 一行约 24 字），传 20 就刚好压在单行里。
    """
    body = " ".join(str(text or "").split())
    for mark in ("**", "`", "#", ">", "|"):
        body = body.replace(mark, "")
    if not body:
        return ""
    head = body.split("。")[0].strip()
    if len(head) < 6:                      # 「好。」这种太短，就多带一句
        head = body
    if len(head) > limit:
        return head[:limit].rstrip() + "…"
    return head if head == body else head + "…"


def _surface_radius(preset: dict) -> float:
    """气泡主体圆角。

    breath_bubble 是有机水滴形（speech_bubble 专属几何，preset 里 radius=0）：
    quick_chat 不支持该形状，按 0 渲染会变直角方框——同一
    self_talk_bubble_style 设置在桌宠气泡与快速对话两套观感。这里用大圆角
    近似，与 speech_bubble 同设置不破解；普通预设用自己的 radius。
    """
    if preset.get("shape") == "breath_bubble":
        return 22.0
    return float(preset.get("radius", 14))


def _rgba(color, alpha: int) -> str:
    """颜色 → QSS 的 rgba() 字串（QSS 不支持 8 位十六进制）。"""
    c = QColor(color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def _blend(base, target, ratio: float) -> str:
    """按比例混色：从面板色派生输入框底色 / 按钮悬停色，无需给每个预设配色表。"""
    a, b = QColor(base), QColor(target)
    t = max(0.0, min(1.0, float(ratio)))
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
    ).name()


# 气泡投影：多层低透明度向下叠加。单层实心色偏移 2px 会沿边缘留一条硬边，
# 看着像贴纸描边而不是影子；这里靠 (偏移, alpha) 表叠出渐隐。
_SHADOW_LAYERS = ((1, 46), (2, 30), (3, 18), (4, 10), (5, 5))


# 气泡跟随宠物的重排间隔。面板是独立 Tool 窗，两种拓扑（legacy 一窗一宠 /
# overlay 单合成窗）都不会把"宠物走了"通知到气泡，只能自己按拍比对锚点；
# 33ms ≈ 30Hz，与 sprite 位置监听通道同频，拖动时看不出滞后。
_FOLLOW_INTERVAL_MS = 33

# ---- 小工位（workstation）面板：原型 C 方案那块深色磨砂玻璃 ----
# 面板宽度定死 344：输入面 / 阅读面都要有稳定的行宽，跟着内容忽宽忽窄最难看。
WORKSTATION_W = 344
WORKSTATION_FLOW_H = 300
WORKSTATION_FLOW_MIN_H = 34    # 对话流最小高度：够她自己那一行（多了就是空白）
WORKSTATION_GAP = 12          # 面板右缘离她身体多远
WORKSTATION_MAX_TASKS = 4

_WS_FG = "#eef1f8"
_WS_MUTED = "rgba(255,255,255,115)"
_WS_ACCENT = "#e8a33d"
_WS_ME_FG = "#241a06"


def _workstation_qss() -> str:
    """小工位面板的深色磨砂样式（与原型 ``#sC .mat`` 一套配色）。

    浅米色审批卡压在深色玻璃上才跳得出来——这是原型里定下的对比关系，
    别把面板改回浅色（浅色面板上审批卡会糊成一片）。
    """
    hair = "rgba(255,255,255,38)"
    field = "rgba(255,255,255,20)"
    return f"""
        QLabel#quick-chat-title, QLabel#quick-chat-hint, QLabel#quick-chat-page,
        QLabel#quick-chat-task {{ background: transparent; border: none; }}
        QLabel#quick-chat-title {{ color: {_WS_FG}; font-weight: 600; font-size: 13px; }}
        QLabel#quick-chat-hint {{ color: {_WS_MUTED}; font-size: 11px; }}
        QLabel#quick-chat-dot {{ color: {_WS_ACCENT}; font-size: 9px; }}
        QLabel#quick-chat-task {{ color: rgba(255,255,255,180); font-size: 11.5px; }}
        QLabel#quick-chat-task[state="done"] {{ color: rgba(255,255,255,110); }}
        QLabel#quick-chat-output {{
            background: rgba(255,255,255,16); color: {_WS_FG};
            border: 1px solid {hair}; border-radius: 12px; padding: 9px 12px;
        }}
        QScrollArea#quick-chat-output-scroll, QScrollArea#quick-chat-history-scroll
        {{ background: transparent; border: none; }}
        QScrollArea > QWidget#qt_scrollarea_viewport,
        QWidget#quick-chat-history-body {{ background: transparent; }}
        QScrollBar:vertical {{ background: transparent; width: 6px; margin: 2px 0; }}
        QScrollBar::handle:vertical {{
            background: rgba(255,255,255,70); border-radius: 3px; min-height: 26px;
        }}
        QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,120); }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
        QPushButton#quick-chat-close {{
            background: transparent; color: {_WS_MUTED}; border: none;
            border-radius: 12px; font-size: 15px;
        }}
        QPushButton#quick-chat-close:hover {{ background: rgba(255,255,255,26); color: #ffffff; }}
        /* 她的话在流里只留一行痕迹：正文归雾，面板不是阅读器 */
        QLabel#quick-chat-msg-her {{
            background: transparent; color: {_WS_MUTED};
            border: none; border-left: 2px solid rgba(232,163,61,120);
            padding: 1px 0 1px 8px; font-size: 12px;
        }}
        QLabel#quick-chat-msg-me {{
            background: {_WS_ACCENT}; color: {_WS_ME_FG}; border: none;
            border-radius: 12px; padding: 7px 11px; font-size: 12.5px;
        }}
        /* 审批卡：浅米色长在对话流里，是整块面板上唯一的高亮面 */
        QFrame#quick-chat-approval {{
            background: #fbf6ea; border: 1px solid rgba(0,0,0,26); border-radius: 12px;
        }}
        QLabel#quick-chat-approval-text {{ color: #3a362c; font-size: 12.5px; }}
        QLabel#quick-chat-approval-cap {{
            color: #8a8375; font-size: 10.5px; letter-spacing: .3px;
        }}
        QPushButton#quick-chat-approve {{
            background: {_WS_ACCENT}; color: {_WS_ME_FG}; border-radius: 9px;
            padding: 3px 12px; font-weight: 600; font-size: 12px;
        }}
        QPushButton#quick-chat-approve:hover {{ background: #f6c479; }}
        QPushButton#quick-chat-reject {{
            background: transparent; color: #554f43;
            border: 1px solid rgba(0,0,0,48); border-radius: 9px;
            padding: 2px 11px; font-size: 12px;
        }}
        QPushButton#quick-chat-reject:hover {{ background: rgba(0,0,0,18); }}
        QPushButton {{
            background: rgba(255,255,255,24); color: {_WS_FG}; border: none;
            border-radius: 8px; padding: 3px 8px;
        }}
        QPushButton#quick-chat-chip {{
            background: transparent; color: {_WS_FG};
            border: 1px solid rgba(255,255,255,60); border-radius: 11px;
            padding: 2px 10px 3px; font-size: 12px;
        }}
        QPushButton#quick-chat-chip:hover {{
            background: {_WS_ACCENT}; color: {_WS_ME_FG}; border-color: {_WS_ACCENT};
        }}
        QPushButton#quick-chat-send {{
            background: {_WS_ACCENT}; color: {_WS_ME_FG}; border: none; border-radius: 15px;
            min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
            padding: 0; font-weight: 600; font-size: 14px;
        }}
        QPushButton#quick-chat-send:hover {{ background: #f6c479; }}
        QPushButton#quick-chat-work {{
            background: {_WS_ACCENT}; color: {_WS_ME_FG}; border-radius: 10px;
            padding: 3px 12px; font-weight: 600;
        }}
        QPushButton#quick-chat-open {{
            background: transparent; color: {_WS_FG};
            border: 1px solid rgba(255,255,255,52); border-radius: 10px; padding: 2px 11px;
        }}
        QLineEdit {{
            background: {field}; color: {_WS_FG}; border: 1px solid rgba(255,255,255,34);
            border-radius: 13px; padding: 6px 15px;
            selection-background-color: {_WS_ACCENT}; selection-color: {_WS_ME_FG};
            placeholder-text-color: rgba(255,255,255,95);
        }}
        QLineEdit:focus {{ border: 1px solid rgba(232,163,61,170); }}
    """



class QuickChatBubble(QFrame):
    def __init__(self, config, pet_window=None, parent=None):
        super().__init__(parent)
        self.config = config
        self.pet_window = pet_window
        self.setObjectName("quick-chat-bubble")
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._capture_compat = False
        self._capture_host: QWidget | None = None
        self.setMinimumWidth(320)
        self.setMaximumWidth(460)

        style_id = str(config.get("self_talk_bubble_style", "classic_top") or "classic_top")
        self._preset = BUBBLE_STYLE_PRESETS.get(style_id, BUBBLE_STYLE_PRESETS["classic_top"])
        self._tail_up = False

        self.character_id = str(config.get("character", "shenshen"))
        self.settings = config.chat_settings()
        self.prompt_builder = PromptBuilder(Path(__file__).resolve().parent.parent / "assets" / "characters")
        self.store = SessionStore(config.dir, "" if str(getattr(config, "instance_id", "")) == "slot-0" else str(getattr(config, "instance_id", "")))
        self.session = self._get_session()
        self.service = ChatService(parent=self)
        self.service.memory_extract_hook = self._schedule_memory_extract
        # 引擎在跑时由 Laji 干活（同一份会话与工作区）；不在则原样退回 provider。
        # providers 回调用到 settings 的当前值：桌宠模型清单是引擎那边 profile 的来源。
        self.laji_service = LajiRunService(
            parent=self,
            character=self.character_id,
            providers=lambda: list(self.settings.providers.values()),
        )
        self.laji_available = False
        self._active_request_id: str | None = None
        self._reply_full = ""       # AI 回答全文（会话历史/聊天窗用，不截断）
        self._reply_text = ""       # 气泡内展示文本（超上限截断 + 提示看聊天窗）
        self._reply_truncated = False
        # v2：回答默认只走「雾」（她身侧那团白气），气泡本身收成一条输入线。
        # 想看全文才把卡片展开（点雾 / 点「全文」），所以卡片显隐都挂在这个开关上。
        self._full_open = False
        self._page = 0
        self._pages: list[str] = []
        self._deactivate_check_pending = False
        self._refit_pending = False
        # 引擎问审批时的在途 (call_id, tool_name)；None = 当前没有待答复的审批
        self._pending_approval: tuple[str, str, str | None] | None = None
        # 「打开 X」这类话要她**真的去开**，不能只回一句"好呀"。宿主（PetInstance）
        # 注入回调，参数是目标名；None = 这个拓扑没有演出面，只当普通聊天。
        self.open_app_callback = None
        # 跟随重排：只在气泡可见时跑，锚点矩形没变就一次也不算（见 _follow_tick）
        self._follow_rect: QRect | None = None
        self._follow_timer = QTimer(self)
        self._follow_timer.setInterval(_FOLLOW_INTERVAL_MS)
        self._follow_timer.timeout.connect(self._follow_tick)

        # v3：桌面上不再有常驻输入框。平时她脚边只有一颗灵动岛胶囊（报进度），
        # 右键「和她聊天」才展开成输入胶囊；这个面板退居「小工位」（点菜单才开）。
        self._island: ChatIsland | None = None
        self._island_hint = "在呢"      # 胶囊上那句话（她此刻在干嘛）
        self._island_muted = False        # 用户按过 ✕：状态照记，但不再自己冒出来
        self.island_mode = True
        # 小工位面板：深色磨砂 + 任务行，只有从菜单/点雾打开时才用这套皮肤
        self._ws_dark = False
        self._task_rows: list[QLabel] = []
        # 面板里正在生成的那一行（流式时原地改字，不另起一块）
        self._stream_row: QLabel | None = None

        self._build()
        self._connect()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(7)
        # 金色小点：面板的「她在场」标记（原型里名牌前那颗点）
        self.dot_label = QLabel("●")
        self.dot_label.setObjectName("quick-chat-dot")
        header.addWidget(self.dot_label)
        title = QLabel("和她说话")
        title.setObjectName("quick-chat-title")
        self.title_label = title  # 子类（灵动岛气泡）改标题用
        header.addWidget(title)
        header.addStretch(1)
        self.hint_label = QLabel("")
        self.hint_label.setObjectName("quick-chat-hint")
        header.addWidget(self.hint_label)
        # 紧凑面板只是「一面」：想同时看会话列表 / 跨工位待批 / 工作台入口，
        # 点这颗展开成三栏工位窗（同一条 chat 链路，不另开通道）。
        self.expand_btn = QPushButton("展开")
        self.expand_btn.setObjectName("quick-chat-expand")
        self.expand_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.expand_btn.setFixedSize(34, 24)
        self.expand_btn.setToolTip("展开成三栏小工位（消息 / 待办 / 工作台）")
        self.expand_btn.setStyleSheet(
            "QPushButton{background:transparent;border:none;color:#8a9aa1;"
            "font-size:11px;padding:0px;}"
            "QPushButton:hover{color:#f0b429;}"
        )
        self.expand_btn.clicked.connect(self.open_workstation)
        header.addWidget(self.expand_btn)
        self.close_btn = QPushButton("×")
        self.close_btn.setObjectName("quick-chat-close")
        self.close_btn.setFixedSize(24, 24)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        # 已发生的对话（她的回答落成白底/靛底气泡，我的话靠右）。当前仍在流式的
        # 回答走下面的 output 区，所以两者样式一致、完成后不会跳变。
        self.history_body = QWidget()
        self.history_body.setObjectName("quick-chat-history-body")
        self.history_layout = QVBoxLayout(self.history_body)
        self.history_layout.setContentsMargins(0, 0, 0, 0)
        self.history_layout.setSpacing(8)
        self.history_layout.addStretch(1)
        self.history_scroll = QScrollArea()
        self.history_scroll.setObjectName("quick-chat-history-scroll")
        self.history_scroll.setWidgetResizable(True)
        self.history_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.history_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.history_scroll.setMaximumHeight(170)
        self.history_scroll.setWidget(self.history_body)
        self.history_scroll.viewport().setAutoFillBackground(False)
        self.history_scroll.setVisible(False)
        layout.addWidget(self.history_scroll)

        self.output = QLabel("")
        self.output.setObjectName("quick-chat-output")
        self.output.setWordWrap(True)
        self.output.setMinimumHeight(44)
        self.output.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.output_scroll = QScrollArea()
        self.output_scroll.setObjectName("quick-chat-output-scroll")
        self.output_scroll.setWidgetResizable(True)
        self.output_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.output_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.output_scroll.setMinimumHeight(44)
        self.output_scroll.viewport().setAutoFillBackground(False)
        self.output_scroll.setMaximumHeight(220)
        self.output_scroll.setWidget(self.output)
        layout.addWidget(self.output_scroll)
        # 默认收起：没回答时这块是 44px 白底占位，会变成气泡底部一条空白。
        self.output_scroll.setVisible(False)

        # 活清单：她每报一步就长一行（原型右页那张「今天的活」），完成后打勾变淡。
        self.tasks_widget = QWidget()
        self.tasks_layout = QVBoxLayout(self.tasks_widget)
        self.tasks_layout.setContentsMargins(0, 0, 0, 0)
        self.tasks_layout.setSpacing(3)
        layout.addWidget(self.tasks_widget)
        self.tasks_widget.setVisible(False)

        # 引擎的审批请求：引擎停下问「允许吗」时，气泡必须给出可点的答复，否则
        # 那一轮就永久卡在 AWAITING_APPROVAL，用户只能看到「没反应」。
        # 小工位里它是**对话流里的一张浅米色卡**（不能飘在面板外面等人点）。
        self.approval_widget = QFrame()
        self.approval_widget.setObjectName("quick-chat-approval")
        card = QVBoxLayout(self.approval_widget)
        card.setContentsMargins(12, 9, 12, 10)
        card.setSpacing(6)
        self.approval_cap = QLabel("需要你拍板")
        self.approval_cap.setObjectName("quick-chat-approval-cap")
        card.addWidget(self.approval_cap)
        self.approval_label = QLabel("")
        self.approval_label.setObjectName("quick-chat-approval-text")
        self.approval_label.setWordWrap(True)
        card.addWidget(self.approval_label)
        approval_row = QHBoxLayout()
        approval_row.setContentsMargins(0, 0, 0, 0)
        approval_row.addStretch(1)
        self.approve_btn = QPushButton("好，带上")
        self.approve_btn.setObjectName("quick-chat-approve")
        self.reject_btn = QPushButton("不要")
        self.reject_btn.setObjectName("quick-chat-reject")
        approval_row.addWidget(self.approve_btn)
        approval_row.addWidget(self.reject_btn)
        card.addLayout(approval_row)
        layout.addWidget(self.approval_widget)
        self.approval_widget.setVisible(False)

        self.page_widget = QWidget()
        self.page_row = QHBoxLayout(self.page_widget)
        self.page_row.setContentsMargins(0, 0, 0, 0)
        self.prev_btn = QPushButton("←")
        self.page_label = QLabel("")
        self.next_btn = QPushButton("→")
        for btn in (self.prev_btn, self.next_btn):
            btn.setObjectName("quick-chat-page")
            btn.setFixedSize(28, 24)
        self.work_btn = QPushButton("打工")
        self.work_btn.setObjectName("quick-chat-work")
        self.open_chat_btn = QPushButton("去聊天窗")
        self.open_chat_btn.setObjectName("quick-chat-open")
        self.page_row.addWidget(self.prev_btn)
        self.page_row.addWidget(self.page_label)
        self.page_row.addWidget(self.next_btn)
        self.page_row.addStretch(1)
        self.page_row.addWidget(self.work_btn)
        self.page_row.addWidget(self.open_chat_btn)
        layout.addWidget(self.page_widget)
        self.page_widget.setVisible(False)

        # 没配 API Key 时的引导（不会发注定 401 的请求）：一行中文说明 + 设置入口。
        self.setup_widget = QWidget()
        setup_row = QHBoxLayout(self.setup_widget)
        setup_row.setContentsMargins(0, 0, 0, 0)
        self.setup_label = QLabel("")
        self.setup_label.setObjectName("quick-chat-hint")
        self.setup_label.setWordWrap(True)
        self.setup_btn = QPushButton("去 AI 设置")
        self.setup_btn.setObjectName("quick-chat-setup")
        setup_row.addWidget(self.setup_label, 1)
        setup_row.addWidget(self.setup_btn)
        layout.addWidget(self.setup_widget)
        self.setup_widget.setVisible(False)

        self.chips_widget = QWidget()
        chips_row = QHBoxLayout(self.chips_widget)
        chips_row.setContentsMargins(0, 0, 0, 0)
        chips_row.setSpacing(6)
        self.chip_buttons: list[QPushButton] = []
        for chip_text in _QUICK_PROMPTS:
            chip = QPushButton(chip_text)
            chip.setObjectName("quick-chat-chip")
            chip.clicked.connect(lambda _checked=False, text=chip_text: self._ask_preset(text))
            chips_row.addWidget(chip)
            self.chip_buttons.append(chip)
        chips_row.addStretch(1)
        self.chips_widget.setVisible(False)
        layout.addWidget(self.chips_widget)

        input_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("和她说点什么…")
        self.send_btn = QPushButton("↑")
        self.send_btn.setObjectName("quick-chat-send")
        input_row.addWidget(self.input, 1)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        bg = self._preset["background"]
        fg = self._preset["foreground"]
        border = self._preset["border"]
        accent = str(self._preset.get("accent") or border)
        radius = int(_surface_radius(self._preset))
        # 单行气泡高度只有 28px 上下：radius 超过半高时 Qt 不画圆角（整块变直角），
        # 所以消息气泡的圆角单独夹到 14px，面板/回答区继续用预设大圆角。
        bubble_radius = min(radius, 14)
        dark = QColor(bg).lightness() < 128
        # 她的气泡在浅色主题用半透明白、深色主题用微亮白；我的话用主题辅色。
        her_bg = "rgba(255,255,255,26)" if dark else "rgba(255,255,255,205)"
        # 白底气泡在米色面板上“没边”就浮不起来：一道极淡描边定形，不抢眼。
        her_line = _rgba("#ffffff", 42) if dark else _rgba(fg, 30)
        me_fg = "#ffffff" if QColor(accent).lightness() < 150 else "#15132a"
        # 输入框要“像个能写的框”：浅色主题比面板提亮一档、深色主题压暗一档；
        # 边框平时是中性细线，只有聚焦时才点亮主题辅色。
        field_bg = _blend(bg, "#000000" if dark else "#ffffff", 0.35)
        field_line = _rgba(fg, 34)
        muted = _rgba(fg, 150)
        # 按钮悬停只轻微加深（原来直接翻成前景色，鼠标划过是一块深色闪屏）。
        hover_fill = _blend(accent, fg, 0.18)
        handle = _rgba(fg, 60)
        handle_hover = _rgba(fg, 115)
        self.setStyleSheet(f"""
            QLabel#quick-chat-title, QLabel#quick-chat-hint, QLabel#quick-chat-page
            {{ background: transparent; color: {fg}; border: none; }}
            QLabel#quick-chat-title {{ font-weight: 600; font-size: 13px; }}
            QLabel#quick-chat-hint {{ color: {muted}; font-size: 11px; }}
            QLabel#quick-chat-dot {{ color: {accent}; font-size: 9px; }}
            QLabel#quick-chat-task {{ background: transparent; border: none;
                color: {_rgba(fg, 175)}; font-size: 11.5px; }}
            QLabel#quick-chat-task[state="done"] {{ color: {_rgba(fg, 110)}; }}
            QFrame#quick-chat-approval {{
                background: {_rgba("#ffffff", 120 if dark else 190)};
                border: 1px solid {her_line}; border-radius: 12px;
            }}
            QLabel#quick-chat-approval-text {{
                background: transparent; color: {fg}; font-size: 12.5px;
            }}
            QLabel#quick-chat-approval-cap {{
                background: transparent; color: {muted};
                font-size: 10.5px; letter-spacing: .3px;
            }}
            QLabel#quick-chat-output {{
                background: {her_bg}; color: {fg}; border: 1px solid {her_line};
                border-radius: {bubble_radius}px; padding: 8px 11px;
            }}
            QScrollArea#quick-chat-output-scroll, QScrollArea#quick-chat-history-scroll
            {{ background: transparent; border: none; }}
            /* viewport 不继承 QScrollArea 的透明：不单独置透明，米色面板上会
               压出一条灰带（历史区与回答区都会）。 */
            QScrollArea > QWidget#qt_scrollarea_viewport,
            QWidget#quick-chat-history-body
            {{ background: transparent; }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 2px 0;
            }}
            QScrollBar::handle:vertical {{
                background: {handle}; border-radius: 3px; min-height: 26px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {handle_hover}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical
            {{ height: 0; border: none; }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical
            {{ background: transparent; }}
            QPushButton#quick-chat-close {{
                background: transparent; color: {muted}; border: none;
                border-radius: 12px; font-size: 15px;
            }}
            QPushButton#quick-chat-close:hover {{ background: {_rgba(fg, 30)}; color: {fg}; }}
            /* 她的话在历史区不画气泡：一条淡竖线 + 小字，像手账里记的一句，
               而不是又一个聊天框（她说的正文在雾里）。 */
            QLabel#quick-chat-msg-her {{
                background: transparent; color: {muted};
                border: none; border-left: 2px solid {_rgba(accent, 80)};
                padding: 1px 0 1px 8px; font-size: 12px;
            }}
            QLabel#quick-chat-msg-me {{
                background: {accent}; color: {me_fg}; border: 1px solid {accent};
                border-radius: {bubble_radius}px; padding: 7px 11px;
            }}
            QPushButton {{
                background: {border}; color: {fg}; border: none; border-radius: 8px;
                padding: 3px 8px;
            }}
            QPushButton#quick-chat-chip {{
                background: transparent; color: {fg};
                border: 1px solid {border}; border-radius: 11px;
                padding: 2px 10px 3px; font-size: 12px;
            }}
            QPushButton#quick-chat-chip:hover {{
                background: {accent}; color: {me_fg}; border-color: {accent};
            }}
            QPushButton#quick-chat-send {{
                background: {accent}; color: {me_fg}; border: none; border-radius: 15px;
                min-width: 30px; max-width: 30px; min-height: 30px; max-height: 30px;
                padding: 0; font-weight: 600; font-size: 14px;
            }}
            QPushButton#quick-chat-send:hover {{ background: {hover_fill}; }}
            QPushButton#quick-chat-send:disabled {{ background: {_rgba(accent, 70)}; }}
            QPushButton#quick-chat-work {{
                background: {accent}; color: {me_fg}; border-radius: 10px;
                padding: 3px 12px; font-weight: 600;
            }}
            QPushButton#quick-chat-work:hover {{ background: {hover_fill}; }}
            QPushButton#quick-chat-approve {{
                background: {accent}; color: {me_fg}; border-radius: 10px;
                padding: 3px 12px; font-weight: 600;
            }}
            QPushButton#quick-chat-approve:hover {{ background: {hover_fill}; }}
            QPushButton#quick-chat-reject {{
                background: transparent; color: {fg};
                border: 1px solid {border}; border-radius: 10px; padding: 2px 11px;
            }}
            QPushButton#quick-chat-reject:hover {{
                background: {_rgba(fg, 30)}; color: {fg}; border-color: {border};
            }}
            QPushButton:hover {{ background: {fg}; color: {bg}; }}
            QLineEdit {{
                background: {field_bg}; color: {fg}; border: 1px solid {field_line};
                border-radius: 14px; padding: 6px 12px;
                selection-background-color: {accent}; selection-color: {me_fg};
                placeholder-text-color: {_rgba(fg, 125)};
            }}
            QLineEdit:focus {{ border: 1px solid {accent}; }}
        """)

    def _connect(self) -> None:
        self.close_btn.clicked.connect(self.close)
        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.prev_btn.clicked.connect(lambda: self._show_page(self._page - 1))
        self.next_btn.clicked.connect(lambda: self._show_page(self._page + 1))
        self.open_chat_btn.clicked.connect(self._open_full_chat)
        self.work_btn.clicked.connect(self._open_laji_work)
        self.setup_btn.clicked.connect(self._open_ai_settings)
        self.approve_btn.clicked.connect(lambda: self._answer_approval(True))
        self.reject_btn.clicked.connect(lambda: self._answer_approval(False))
        # started 在 send() 内**同步**发出，而 _active_request_id 是 send() 的
        # 返回值——直连会让 _started 的 id 过滤恒命中（气泡提示永远停在
        # 「思考中…」）。排队一拍：emit 先于 worker.start() 投递，事件按
        # FIFO 处理，本槽必在首个 delta 之前跑到，此刻 id 已落位。
        self.service.started.connect(self._started, Qt.ConnectionType.QueuedConnection)
        self.service.delta.connect(self._delta)
        self.service.activity.connect(self._activity)
        self.service.finished.connect(self._finished)
        self.service.error.connect(self._error)
        self.service.stopped.connect(self._stopped)
        self.service.act.connect(self._act)
        # 同一批 handler：两个服务信号签名一致，靠 request_id 区分谁在途。
        self._connect_laji_service()

    def _connect_laji_service(self) -> None:
        """把引擎那条服务的信号接到同一批 handler（换角色会换实例，要重接）。"""
        self.laji_service.started.connect(self._started, Qt.ConnectionType.QueuedConnection)
        self.laji_service.delta.connect(self._delta)
        # 引擎路径同样会把正文里的演出标记剥出来发 act：不接这根线，模型点了
        # 桌宠也不演（quick_chat 走 daemon 时这是唯一的演出入口）。
        self.laji_service.act.connect(self._act)
        self.laji_service.activity.connect(self._activity)
        self.laji_service.finished.connect(self._finished)
        self.laji_service.error.connect(self._error)
        self.laji_service.stopped.connect(self._stopped)
        self.laji_service.task.connect(self._laji_task)
        self.laji_service.approval.connect(self._approval)

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self._ws_dark:
            self._paint_glass(painter)
            painter.end()
            return
        rect = QRectF(self.rect()).adjusted(6, 8, -6, -8)
        radius = _surface_radius(self._preset)
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        tail = QPainterPath()
        tip_x = rect.center().x()
        if self._tail_up:
            tip = QPointF(tip_x, rect.top() - 6)
            tail.moveTo(QPointF(tip_x - 8, rect.top() + 2))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + 8, rect.top() + 2))
        else:
            tip = QPointF(tip_x, rect.bottom() + 6)
            tail.moveTo(QPointF(tip_x - 8, rect.bottom() - 2))
            tail.lineTo(tip)
            tail.lineTo(QPointF(tip_x + 8, rect.bottom() - 2))
        tail.closeSubpath()
        surface = body.united(tail).simplified()

        # 柔和阴影：多层下移 + 递减透明度，替代单层实心偏移（后者沿边缘留硬边）
        base_shadow = QColor(self._preset.get("shadow", "#6b542b"))
        painter.setPen(Qt.PenStyle.NoPen)
        for offset, alpha in _SHADOW_LAYERS:
            layer = QColor(base_shadow)
            layer.setAlpha(alpha)
            path = QPainterPath(surface)
            path.translate(0, offset)
            painter.setBrush(layer)
            painter.drawPath(path)

        # 气泡主体：上缘向白提亮一档，整块纯色在浅色主题上显得扁
        body_fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        body_fill.setColorAt(0.0, QColor(_blend(self._preset["background"], "#ffffff", 0.18)))
        body_fill.setColorAt(1.0, QColor(self._preset["background"]))
        painter.setBrush(QBrush(body_fill))
        painter.setPen(QPen(QColor(self._preset["border"]), 1))
        painter.drawPath(surface)
        painter.end()

    def _paint_glass(self, painter: QPainter) -> None:
        """小工位底板：深色磨砂玻璃（圆角 + 发丝边 + 顶部内高光 + 大投影）。

        Qt 拿不到桌面背景做真模糊（Windows 的 acrylic 要走 DWM 私有接口），
        这里用「接近不透明的深色 + 极淡内高光」模拟玻璃：浅色壁纸下压得住字，
        深色壁纸下也不是一块死黑。
        """
        rect = QRectF(self.rect()).adjusted(5, 6, -5, -6)
        radius = 16.0
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)

        painter.setPen(Qt.PenStyle.NoPen)
        for offset, alpha in ((2, 58), (5, 32), (9, 16)):
            layer = QPainterPath()
            layer.addRoundedRect(rect.translated(0, offset), radius, radius)
            painter.setBrush(QColor(4, 8, 20, alpha))
            painter.drawPath(layer)

        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0.0, QColor(31, 39, 63, 243))
        fill.setColorAt(0.55, QColor(22, 29, 50, 240))
        fill.setColorAt(1.0, QColor(15, 21, 38, 238))
        painter.setBrush(QBrush(fill))
        painter.setPen(QPen(QColor(255, 255, 255, 44), 1))
        painter.drawPath(body)

        # 顶部一道内高光：玻璃边缘的反光，别画成白描边
        glow = QLinearGradient(rect.topLeft(), rect.topLeft() + QPointF(0, rect.height() * 0.35))
        glow.setColorAt(0.0, QColor(255, 255, 255, 26))
        glow.setColorAt(1.0, QColor(255, 255, 255, 0))
        inner = QPainterPath()
        inner.addRoundedRect(rect.adjusted(1.2, 1.2, -1.2, -1.2), radius - 1.2, radius - 1.2)
        painter.setBrush(QBrush(glow))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(inner)

    # ------------------------------------------------------------ 会话
    def _get_session(self):
        # 会话按天分割：当天已有就用它，没有才另建一条（见 SessionStore.session_on）。
        return self.store.session_on(self.character_id) or self._new_session()

    def _roll_to_today(self) -> None:
        """跨过零点还在聊：今天的话不能写进昨天那条会话。

        气泡里的旧对话属于昨天那条，切走时一并收掉；今天已有会话就直接接着写。
        """
        if self.session is not None and self.store.is_today(self.session):
            return
        self._invalidate_in_flight_request()
        self.session = self._get_session()
        self._clear_history()

    def refresh_session(self) -> None:
        """从磁盘重取当天会话（公开 seam；角色切换后外部刷新用，替代私访 _get_session）。

        会话按天分割，所以「重取」的是**今天**那一条：今天还没聊过就顺手建一条。
        """
        self.session = self._get_session()

    def switch_character(self, character_id: str) -> None:
        """切角色同步 seam（B07）：先作废在途请求，再换身份 + 按新角色重取会话。

        气泡的角色是构造期一次性快照（``character_id`` 决定会话目录与系统提示，
        见 ``_get_session`` / ``_send`` 的 ``build_messages``）；主宠切角色后不同步
        这里，气泡会一直用旧角色的会话与人格提示。空身份/同角色不动作（避免无谓
        重建会话，丢掉正在续聊的那一条）。

        作废在途请求是先决条件：``_finished`` / ``_delta`` / ``_error`` / ``_stopped``
        一律按 ``_active_request_id`` 认领信号，换会话时不清它，旧角色那次请求的完成
        信号到达时 ID 仍然匹配，回答就被 append 进**新**角色的 session（对照完整聊天窗
        ``chat/widgets.py::switch_character`` 的同款闸门）。
        """
        new_id = str(character_id or "")
        if not new_id or new_id == self.character_id:
            return
        self._invalidate_in_flight_request()
        self.character_id = new_id
        # 引擎那条路的 workspace 是构造时定下的（Pet/<角色>）：换角色要一起换掉，
        # 否则新角色的话会落进上一只的目录，侧栏分组也对不上。
        self.laji_service = LajiRunService(
            parent=self,
            character=new_id,
            providers=lambda: list(self.settings.providers.values()),
        )
        self._connect_laji_service()
        self.refresh_session()

    def _invalidate_in_flight_request(self) -> None:
        """作废在途请求：清 ID 闸 + 停掉 worker + 撤掉它的显示残留。

        清 ID 后旧请求的完成/增量/错误/停止信号全部按 ID 失配静默丢弃（既不落库也不
        上屏）；停 worker 只是别让它在后台白跑完再被丢弃。已上屏的半截回答属于**旧角色**
        的回答，换身份后不该留在新角色的气泡里，故与完整聊天窗换角色一致地复位显示。
        """
        if self._active_request_id is None:
            return
        self._active_request_id = None
        self.service.stop()
        self.laji_service.stop()
        self._set_reply_text("")
        self._page = 0
        self._pages = []
        self.page_widget.setVisible(False)
        self._render_reply()
        self.hint_label.setText("")
        self._clear_history()

    def _new_session(self):
        session = self.store.create(
            self.character_id,
            self.settings.active_provider,
            self.prompt_builder.effective_system_prompt(self.settings, self.character_id),
        )
        self.store.save(session)
        return session

    def position_near_pet(self) -> None:
        if self._ws_dark:
            # 小工位是「贴她左侧的一块板」，不是头顶气泡
            self._position_workstation()
            return
        pet = self.pet_window
        if pet is None or not hasattr(pet, "visible_content_rect"):
            return
        anchor = pet.visible_content_rect()
        host = self._capture_host if self._capture_compat else None
        if host is not None and not host.geometry().isEmpty():
            available = host.geometry()
        else:
            screen = QGuiApplication.screenAt(anchor.center())
            available = screen.availableGeometry() if screen else QGuiApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        w = self.width()
        h = self.height()
        x = anchor.center().x() - w // 2
        y = anchor.top() - h - 8
        self._tail_up = False
        if host is not None and y < available.top():
            # 子模式默认只允许落在主窗内，会把气泡挤到下方/遮挡宠物。
            # 先向主窗申请透明头顶空间，尽量恢复“向上生成”的原生位置。
            screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
            if screen is not None:
                screen_top = screen.availableGeometry().top()
                desired_top = y - 4
                if desired_top >= screen_top:
                    desired_h = available.top() - desired_top
                    setter = getattr(host, "set_capture_headroom", None)
                    if desired_h > 0 and setter is not None and setter(desired_h):
                        return self.position_near_pet()
        if y < available.top():
            y = anchor.bottom() + 8
            self._tail_up = True
        x = max(available.left() + 4, min(x, available.right() - w - 4))
        if host is not None:
            # 直播捕获子模式下只允许落在主窗矩形内；空间不足时夹到窗内，
            # 避免子控件被主窗边界裁掉。
            if h <= available.height():
                y = max(available.top() + 4, min(y, available.bottom() - h - 4))
            else:
                y = available.top() + 4
            self.move(host.mapFromGlobal(QPoint(x, y)))
        else:
            self.move(x, y)
        self.update()

    def _anchor_rect(self) -> QRect | None:
        """宠物身体框（与 ``position_near_pet`` 同一口径）；拿不到就是 None。

        她收在小工位左栏时真窗是藏着的，它的 ``visible_content_rect`` 已经是旧
        位置；这时以工位槽位为锚点（小工位 ``dock_pet`` 会挂上这个回调）。
        """
        pet = self.pet_window
        docked = getattr(pet, "_docked_slot_rect", None)
        if callable(docked):
            try:
                rect = QRect(docked())
            except Exception:
                rect = QRect()
            if not rect.isNull():
                return rect
        getter = getattr(pet, "visible_content_rect", None)
        if not callable(getter):
            return None
        try:
            rect = QRect(getter())
        except Exception:
            return None
        return None if rect.isNull() else rect

    def _follow_tick(self) -> None:
        """宠物走了就贴回去，没走就什么都不做。

        不订阅 sprite 的位置监听：legacy 一窗一宠与 overlay 单合成窗都不把位移
        告知独立 Tool 气泡，而锚点对象只有个 ``visible_content_rect()``；按拍比对
        是两种拓扑都能用、且不动别人的最小改法。capture 兼容模式下气泡本身就是
        主窗子控件，父窗移动天然带着它，不必重排。
        """
        if self._capture_compat:
            return
        rect = self._anchor_rect()
        if rect is None or rect == self._follow_rect:
            return
        self._follow_rect = rect
        self.position_near_pet()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self._follow_rect = None
        self._follow_timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._follow_timer.stop()
        super().hideEvent(event)

    def set_capture_compat(self, on: bool, host: QWidget | None = None) -> None:
        """直播捕获兼容：把快速对话气泡作为桌宠主窗的子内容渲染（issue #62）。

        开启后快速对话不再是独立 Tool 窗口，而成为主窗子控件，捕获主窗时即可
        看到并操作它；关闭后恢复独立置顶 Tool 窗口形态。
        """
        on = bool(on)
        if on == self._capture_compat:
            return
        if on and host is None:
            return
        was_visible = self.isVisible()
        self._capture_compat = on
        self._capture_host = host if on else None
        if on:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.setParent(host)
        else:
            self.setParent(None)
            flags = (
                Qt.WindowType.Tool
                | Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.WindowStaysOnTopHint
            )
            self.setWindowFlags(flags)
        if was_visible:
            self.position_near_pet()
            self.show()
            if not on:
                self.raise_()
                self.activateWindow()
                self.input.setFocus()
        else:
            # 子模式重挂主窗后不能随父窗显示而自动弹出空白窗。
            self.hide()

    def show_for_pet(self, pet_window=None) -> None:
        if pet_window is not None:
            self.pet_window = pet_window
        if self.island_mode:
            # v3：她脚边那颗胶囊才是入口——「和她聊天」= 展开胶囊，不再是头顶一张
            # 输入卡。面板（小工位）只在右键菜单/点雾时开。
            self.open_island()
            return
        self._replay_history()
        self.position_near_pet()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    # ------------------------------------------------------------ 灵动岛
    def _ensure_island(self) -> ChatIsland:
        """取（或建）她脚边那颗胶囊；C++ 侧被销毁就重建。"""
        if self._island is not None and not island_alive(self._island):
            self._island = None
        if self._island is None:
            island = ChatIsland(self.config, pet_window=self.pet_window)
            island.submitted.connect(self._on_island_submit)
            island.closed.connect(self._on_island_closed)
            island.expanded.connect(self._on_island_expanded)
            self._island = island
        self._island.set_pet_window(self.pet_window)
        return self._island

    def open_island(self) -> None:
        """右键「和她聊天」：把胶囊展开成输入。"""
        # 用户主动叫她 = 解掉 ✕ 的静默（否则关过一次就再也叫不出来）
        self._island_muted = False
        island = self._ensure_island()
        # 用她上一句「在干嘛」当占位，而不是 hint 那种操作提示（「点雾看全文」）
        island.set_status(self._island_hint, busy=self.request_in_flight())
        island.expand()

    def island_status(self, text: str, *, busy: bool | None = None) -> None:
        """把她此刻在干嘛写到胶囊上；还没岛就顺手建一颗（她开口，胶囊才出现）。"""
        if not self.island_mode:
            return
        try:
            if QApplication.instance() is None:
                return
        except Exception:
            return
        self._island_hint = " ".join(str(text or "").split()) or self._island_hint
        if self._island_muted:
            # ✕ 关掉之后：状态照记（下次叫她时就是最新那句），但不再把岛弹回来
            island = self._island
            if island is not None and island_alive(island):
                island.set_status(text, busy=busy)
            return
        island = self._ensure_island()
        island.set_status(text, busy=busy)
        if island.state == "hidden":
            island.show_mini()

    def _on_island_submit(self, text: str) -> None:
        self.input.setText(text)
        self._send()
        island = self._island
        if island is not None and island_alive(island) and island.is_open():
            island.collapse()

    def _on_island_expanded(self) -> None:
        """点 mini 胶囊 / 右键叫她：她又被叫出来了，解掉 ✕ 的静默。"""
        self._island_muted = False

    def _on_island_closed(self) -> None:
        """点胶囊的 ✕：岛整颗关掉，也不让她下一句状态把它弹回来。

        解除静默只有一条路：用户主动叫她（右键「和她聊天」/ 点 mini 胶囊）。
        """
        self._island_muted = True

    def island_widget(self):
        """测试/宿主取岛的口子（懒建）。"""
        return self._ensure_island()

    def dismiss_island(self) -> None:
        """整颗收掉（退出收口）。"""
        island = self._island
        if island is not None and island_alive(island):
            island.dismiss()

    # ------------------------------------------------------------ 小工位
    def _character_name(self) -> str:
        """她的名字：用户别名 > 唤名表 > manifest name，读不到就留空。

        素材包缺失时显示名会回退成角色 id（"shenshen"）——面板顶上挂一个英文 id
        比不挂更难看，这种情况返回空串，调用方保留原标题。
        """
        cid = str(self.character_id or "").strip()
        if not cid:
            return ""
        try:
            alias_of = getattr(self.config, "character_alias", None)
            if callable(alias_of):
                alias = str(alias_of(cid) or "").strip()
                if alias:
                    return alias
            name = str(catalog.character_call_name(cid) or "").strip()
            if name and name != cid:
                return name
        except Exception:
            logging.debug("quick_chat: 角色名读取失败", exc_info=True)
        return ""

    def _apply_workstation_style(self) -> None:
        """切到小工位皮肤：深色磨砂 + 定宽 344 + 加高的对话流。"""
        if self._ws_dark:
            return
        self._ws_dark = True
        self.setStyleSheet(_workstation_qss())
        self.setMinimumWidth(WORKSTATION_W)
        self.setMaximumWidth(WORKSTATION_W)
        self.history_scroll.setMaximumHeight(WORKSTATION_FLOW_H)
        # 面板里对话流是主角：固定一圈高度，内容多了在框内滑（跟着内容缩会变成
        # 一条一行的窄条，用户得不停地上下扒）
        self.history_scroll.setMinimumHeight(WORKSTATION_FLOW_H)
        self.output_scroll.setMaximumHeight(WORKSTATION_FLOW_H)
        # QSS 的 padding 在 QLineEdit 上不稳（实测占位文字仍贴着圆角），
        # 用 setTextMargins 自带一份，首字才不会被 13px 圆角咬掉。
        self.input.setTextMargins(14, 0, 8, 0)
        name = self._character_name()
        if name:
            self.title_label.setText(name)
        self.update()

    def send_text(self, text: str, attachments: dict | None = None) -> bool:
        """外部输入的同一张嘴（小工位输入框）：写进来，走原来的 ``_send``。

        ``attachments`` 是小工位那个输入框收的附件：``names`` 上屏、``prompt`` 进请求正文、
        ``images`` 当图片负载跟着最后一条消息走（和普通聊天窗同一个口径）。

        返回是否真的发出去了：``_send`` 在「没配 Key」「服务忙」「空文本」这些路
        上提前 return，输入框里的字不会被清掉。三栏窗靠这个回执决定要不要提示，
        否则一次静默的 no-op 看起来就像按钮坏了。
        """
        text = str(text or "").strip()
        payload = dict(attachments or {})
        names = [str(name) for name in (payload.get("names") or [])]
        if (not text and not names) or not hasattr(self, "input"):
            return False
        self.input.setText(text)
        self._send(attachments=payload if names else None)
        accepted = not self.input.text().strip()
        if not accepted:
            self.input.clear()  # 面板里不留一条幽灵草稿
        return accepted

    def open_workstation(self) -> None:
        """右键「打开小工位」：企微式三栏窗（消息 / 待办 / 工作台）。"""
        from .workstation_window import open_workstation

        # 紧凑面板和三栏窗是同一件事的两种摆法：开大的就把小的收起来。
        if self.isVisible():
            self.hide()
        open_workstation(self)

    def open_work_station(self) -> None:
        """右键「打开小工位」：把面板拉出来（默认收着）。"""
        self._apply_workstation_style()
        if self.hint_label.text() == _HINT_SEE_FULL:
            self.hint_label.setText("")      # 面板里正文就在流里，不用再指路
        self._replay_history()
        # 面板里没有「钉在输入框上方的最后一次回复」：正文全在对话流里。
        # 只有还在生成的那一句接着往下写（半截也得看得见，不能等收尾才出现）。
        if self._reply_full and self._active_request_id:
            self._push_her_reply(self._reply_full)
        self._position_workstation()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()
        island = self._island
        if island is not None and island_alive(island):
            island.collapse()
        # C 方案：面板一拉出来，贴在旁边的对白让位（原型 #sC.open .bubble opacity:0），
        # 否则同屏两块白底方块抢读。
        mist_clear()

    def _position_workstation(self) -> None:
        """面板贴她左侧（右边是屏幕边），下缘对齐她的腰；放不下就翻到右边。"""
        anchor = self._anchor_rect()
        if anchor is None:
            return
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1040)
        self.adjustSize()
        w, h = self.width(), self.height()
        x = anchor.left() - w - WORKSTATION_GAP
        if x < available.left() + 6:
            x = anchor.right() + WORKSTATION_GAP
        y = anchor.bottom() - h + 28
        x = max(available.left() + 6, min(x, available.right() - w - 6))
        y = max(available.top() + 6, min(y, available.bottom() - h - 6))
        self.move(x, y)
        self.update()

    # ------------------------------------------------------------ 任务行
    def _add_task_row(self, title: str) -> None:
        """她报一步就在活清单里长一行（超过上限就挤掉最旧的）。"""
        body = " ".join(str(title or "").split())
        if not body:
            return
        label = QLabel(f"○ {body}")
        label.setObjectName("quick-chat-task")
        label.setWordWrap(True)
        self.tasks_layout.addWidget(label)
        self._task_rows.append(label)
        while len(self._task_rows) > WORKSTATION_MAX_TASKS:
            old = self._task_rows.pop(0)
            self.tasks_layout.removeWidget(old)
            old.deleteLater()
        self.tasks_widget.setVisible(True)
        self._refit_later()

    def _mark_tasks_done(self) -> None:
        for label in self._task_rows:
            text = label.text()
            if text.startswith("○ "):
                label.setText("✓ " + text[2:])
            label.setProperty("state", "done")
            label.style().unpolish(label)
            label.style().polish(label)

    def _clear_tasks(self) -> None:
        for label in self._task_rows:
            self.tasks_layout.removeWidget(label)
            label.deleteLater()
        self._task_rows = []
        self.tasks_widget.setVisible(False)

    # ------------------------------------------------------------ 发送
    def _active_service(self):
        """引擎在跑就把活派给 Laji；否则退回桌宠自己的 provider。"""
        ok, _reason = LajiRunService.probe()
        self.laji_available = ok
        return self.laji_service if ok else self.service

    def _laji_task(self, _request_id: str, title: str) -> None:
        if not title:
            return
        body = " ".join(str(title).split())
        if self._is_tool_id(body):
            # 引擎把工具 id（``mcp:pet-hands:look``）当任务名报回来。那是审计信息，
            # 不该上屏：人只想知道她在忙，不想看工具名。
            log.debug("quick_chat：工具任务 %s", body)
            self.island_status("正忙着…", busy=True)
            return
        self.hint_label.setText(f"Laji 在做：{body}")
        # 活清单只记「在干什么」：引擎把用户那句话原样当任务名报回来时，
        # 清单里就长出一行「✓ 那我是谁」——那不是活，是噪音（真机截图）。
        echo = self._echoes_my_question(body)
        if not echo:
            self._add_task_row(body)
        self.island_status(f"在做：{body}", busy=True)

    @staticmethod
    def _is_tool_id(title: str) -> bool:
        """这一条「任务名」是不是工具 id：没空格、也没汉字 → 不是人话。"""
        body = " ".join(str(title or "").split())
        if not body or " " in body:
            return False
        return not any("\u4e00" <= ch <= "\u9fff" for ch in body)

    def _echoes_my_question(self, title: str) -> bool:
        """这一条「活」是不是我自己那句问题被引擎原样报了回来。"""
        body = " ".join(str(title or "").split())
        if not body:
            return True
        for message in reversed(list(getattr(self.session, "messages", []) or [])[-6:]):
            if getattr(message, "role", "") != "user":
                continue
            asked = " ".join(str(getattr(message, "content", "") or "").split())
            if not asked:
                return False
            return asked == body or (len(body) >= 6 and asked.startswith(body))
        return False

    def _approval(
        self, request_id: str, call_id: str, tool_name: str, reason: str, timeout_secs: int
    ) -> None:
        """引擎要动工具前先问一句：在气泡里给出可点的【允许/拒绝】。"""
        if request_id != self._active_request_id:
            return
        self._pending_approval = (str(call_id), str(tool_name), None)
        text = approval_text(tool_name, reason)
        self.approval_label.setText(text)
        self.approval_widget.setVisible(True)
        self.hint_label.setText("等你确认")
        self.island_status("等你点头", busy=False)
        # 对白统一走头顶上方（尾巴指头、往上长）；审批的人话不再压到腰侧
        # （2026-11-02 口径：聊天框在上面，审批族挂她身侧）。
        mist_reply(text, pet_window=self.pet_window, ms=9000,
                   name=self._character_name())
        self._refit_later()

    def _answer_approval(self, approved: bool) -> None:
        pending = self._pending_approval
        self._pending_approval = None
        self.approval_widget.setVisible(False)
        if pending is None:
            return
        call_id, _tool, run_id = pending
        # run_id 为 None = 桌宠自己发起的 run（旧口径）；非 None = Laji 窗口里那条。
        self.laji_service.approve(run_id or self.laji_service.run_id, call_id, approved)
        self.hint_label.setText("放行啦" if approved else "已拒绝")
        self.island_status("好，这就去" if approved else "那不做啦", busy=approved)
        self._refit_later()

    def _dismiss_approval(self) -> None:
        """终态时收起审批条：留下的按钮点下去只会是一个空答复。"""
        self._pending_approval = None
        self.approval_widget.setVisible(False)

    # 别家 run 的审批已撤除：入口改由她头顶的徽章（工位开着则归左栏页，见 overlay_shell）。

    def _send(self, _checked: bool = False, attachments: dict | None = None) -> None:
        service = self._active_service()
        if service.busy:
            service.stop()
            return
        text = self.input.text().strip()
        attach = dict(attachments or {})
        names = [str(name) for name in (attach.get("names") or [])]
        if not text and not names:
            return
        # 一句话问答优先走快档模型（口径见 chat/model_tiers.py）；判成正经任务还是用原来那个
        has_files = bool(names or attach.get("images") or attach.get("paths"))
        config = self.settings.route_config(text, has_attachments=has_files)
        config.api_key = self.config.resolve_api_key(config)
        if not config.api_key and service is self.service:
            # 空凭据时 providers 连 Authorization 头都不发，服务端只回一句英文
            # “Authentication Fails”：发出去没有任何价值，直接告诉用户去哪配。
            self._show_key_hint(config)
            return
        display_text = text or "请查看附件"
        if names:
            display_text += "\n\n附件：" + "、".join(names)
        attachment_context = str(attach.get("prompt") or "").strip()
        request_text = text or "看看这些附件。"
        if attachment_context:
            request_text = f"{request_text}\n\n{attachment_context}"
        images = list(attach.get("images") or [])
        # 附件路径跟着消息落库：小工位拿它画缩略图 / 文件卡，不必指望 1200ms 后的内存快照。
        # 粘贴图先搬进会话目录——临时件发完就得收回，否则历史里只剩一个查无此物的文件名。
        image_paths = [str(path) for path in (attach.get("image_paths") or [])]
        attachment_paths = persist_chat_attachments(
            attach.get("paths") or image_paths,
            store_root=self.store.root,
            character_id=self.session.character_id,
            session_id=self.session.session_id,
        )
        self.input.clear()
        self._roll_to_today()
        # 上一轮回答先归档进历史，本轮问题紧跟着往下接：消掉“上一句被新一句
        # 顶掉”的失落感，同时不改变流式期间 output 的显示口径。
        if self._reply_text and not self._ws_dark:
            # 面板里上一句已经长进对话流了（收尾时推的），这里再归档就成了上下两遍
            self._append_message("her", self._reply_text, html=True)
        self._append_message("me", display_text)
        self._stream_row = None
        self.chips_widget.setVisible(False)
        # 新一轮活：上一轮的清单收掉，别让旧步骤混进这次
        self._clear_tasks()
        # 陈旧快照防护（DS-M7 → R3 P1 硬修）：原子「读-追加-提交」
        synced, _absorbed = self.store.append_message(
            self.session, ChatMessage("user", display_text, attachments=attachment_paths)
        )
        if synced is None:
            self.session.messages.append(
                ChatMessage("user", display_text, attachments=attachment_paths)
            )
            self.store.save(self.session)
        else:
            self.session = synced
        self._set_output_markdown("")
        self._set_reply_text("")
        self._full_open = False
        # 新的一句进来，上一句的雾立刻收：她不会一边回答新问题、一边挂着旧话。
        mist_clear()
        self._page = 0
        self._pages = []
        self.page_widget.setVisible(False)
        self.hint_label.setText("思考中…")
        self.island_status("在想了…", busy=True)
        self.setup_widget.setVisible(False)
        # 气泡快速对话刻意不注入记忆：一次性问答，注入只会拖慢首字；它仍然
        # 通过 service.memory_extract_hook 参与后台提炼（见 _schedule_memory_extract）。
        messages = self.prompt_builder.build_messages(
            self.settings, self.character_id, self.session.messages[:-1], request_text,
            # 每宠键：config 可能是 slot 路由视图，必须从 get 逐键读（chat_settings()
            # 转发主配置，读不到这只宠的场景卡）。与 widgets.py / legacy_widgets.py 同口径。
            roleplay_enabled=bool(self.config.get("roleplay_enabled", False)),
            roleplay_scene=str(self.config.get("roleplay_scene", "") or ""),
            roleplay_cast=str(self.config.get("roleplay_cast", "") or ""),
            # 演出清单：关掉/无桌宠/无素材时为空串，提示词与没有这个功能时一致
            act_block=act_prompt_block(self.config, self.pet_window),
        )
        if images:
            # 图不给图看就等于没发：追加在最后一条 user 后面（同 widgets.py 2386 行）。
            messages[-1]["content"] = [{"type": "text", "text": request_text}, *images]
        self._request_pet_window = self.pet_window
        self._active_request_id = service.send(messages, config)
        # 交代她办的事要**当场起步**，别等模型把话说完——回复是"我去了"，
        # 身体得已经在路上，否则就是嘴上答应。
        self._maybe_open_app(text)

    def _act(self, _request_id: str, cue) -> None:
        """模型在回复里点的演出：转给桌宠窗口的导演闸门（认不出/冷却中由对面拦）。

        气泡快速对话不持有 PetChatLink，直接问窗口要 request_act。
        """
        window = getattr(self, "_request_pet_window", None) or self.pet_window
        request = getattr(window, "request_act", None)
        if not callable(request):
            return
        try:
            request(cue)
        except Exception:
            logging.debug("quick_chat: 演出请求失败", exc_info=True)

    def _maybe_open_app(self, text: str) -> None:
        """「帮我打开 X」→ 交给宿主去演一遍找→按→开门。

        识别放在本地规则里（pet/open_intent）：零延迟、不依赖模型、也不会把
        "怎么打开"误当命令。识别不出就什么都不做，照常聊天。
        """
        try:
            from . import open_intent

            name = open_intent.parse(text)
            if not name:
                return
            cb = self.open_app_callback
            if not callable(cb):
                return
            if cb(name):
                self.hint_label.setText(f"去打开{name}了…")
                # 她自己要走开去干活：气泡跟着飘过去（跟随器锚 sprite）会很怪，
                # 而且挡住要看的地方。收起气泡，把画面让给演出。回复不会丢，
                # 回来点开还在（hideEvent 只停跟随，不停请求）。
                QTimer.singleShot(140, self.hide)
        except Exception:
            logging.debug("quick_chat: 打开意图处理失败", exc_info=True)

    def _started(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self.hint_label.setText("生成中…")
        self.island_status("写着呢…", busy=True)

    def _activity(self, request_id: str, kind: str, text: str) -> None:
        if request_id != self._active_request_id or self._reply_full:
            return
        # 引擎发来的是工具原始 id（``mcp:pet-hands:look`` 这种），那是给审计看的，
        # 不是给她眼前的人看的：工具类活动一律收成一句人话，原文只进日志。
        if kind == "reasoning":
            self.hint_label.setText("深度思考中…")
            self.island_status("想得很深…", busy=True)
            return
        log.debug("quick_chat：工具活动 %s", str(text or "").strip())
        self.hint_label.setText("正在忙…")
        self.island_status("正忙着…", busy=True)

    def _request_presentation_valid(self) -> bool:
        target = getattr(self, "_request_pet_window", self.pet_window)
        valid = getattr(target, "presentation_valid", None)
        return target is self.pet_window and (not callable(valid) or bool(valid()))

    def _delta(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id or not self._request_presentation_valid():
            return
        live = self._reply_full + str(text)
        self._set_reply_text(live)
        if self._ws_dark:
            # 面板里只有一条滑条：生成中的那句就长在对话流最下面，原地改字
            self._push_her_reply(live)
        else:
            self._render_reply()
        # 她边说边散：对白跟着长，别等整段说完才冒出来。
        if not (self._ws_dark and self.isVisible()):
            # 面板开着时桌面上不再冒一块（原型 #sC.open .bubble{opacity:0}）
            mist_reply(live, getattr(self, "_request_pet_window", None) or self.pet_window,
                       ms=6000, on_click=self._open_full_reply,
                       name=self._character_name())

    def _schedule_memory_extract(self, user_text: str, reply_text: str, provider, provider_config) -> None:
        """档 B：回复完成后的静默记忆提炼（护栏/后台线程都在 memory_extract 内）。"""
        schedule_extraction(
            config=self.config,
            memory_path=self.store.root / self.character_id / "memory.json",
            user_text=user_text, reply_text=reply_text,
            provider=provider, provider_config=provider_config)

    def _finished(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id:
            return
        # 落库/聊天窗用全文；气泡展示文本另行截断（见 _set_reply_text）。
        self._set_reply_text(text)
        synced, _absorbed = self.store.append_message(self.session, ChatMessage("assistant", self._reply_full))
        if synced is None:
            self.session.messages.append(ChatMessage("assistant", self._reply_full))
            self.store.save(self.session)
        else:
            self.session = synced
        self._active_request_id = None
        self.hint_label.setText("")
        self._dismiss_approval()
        self._mark_tasks_done()
        # 岛：把她这句话的前半句当状态挂上去——「说完了」比「已完成」像人话
        self.island_status(_her_line(self._reply_full) or "说好啦", busy=False)
        # v3 C 方案：她的回答走身边那块白底对白（原型 #sC .bubble：名字标签 + 尾巴，
        # 贴身、说完自收）。气泡卡片默认不展开——点对白才看全文。
        if self._ws_dark and self.isVisible():
            # 面板开着：原型里这时对白不显示（#sC.open .bubble{opacity:0}），
            # 她这句话已经长在面板的对话流里了
            mist_clear()
        else:
            mist_reply(
                self._reply_full,
                getattr(self, "_request_pet_window", None) or self.pet_window,
                on_click=self._open_full_reply,
                name=self._character_name(),
            )
        if self._ws_dark:
            # 面板里没有「钉在输入框上方的最后一次回复」：这一句定格进流，
            # 跟上面的问答一起滑。
            self._push_her_reply(self._reply_full, final=True)
            self._set_output_markdown("")
        elif self._request_presentation_valid():
            self._render_reply()
            # 卡片默认收起，得告诉人「全文去哪了」——点她那团字。
            self.hint_label.setText(_HINT_SEE_FULL if self._reply_text else "")
        else:
            self.hide()

    def _open_full_reply(self) -> None:
        """点对白 → 把完整回答展开进面板（小工位皮肤，窗口长出来）。"""
        if not self._reply_text:
            return
        self._full_open = True
        if self.island_mode:
            self._apply_workstation_style()
        self._render_reply()
        self._refit_later()
        # 面板可能已经被收起（她去开门 / 用户按了 ×）：点雾要能把它叫回来。
        if not self.isVisible() and self._request_presentation_valid():
            self.show()
            self.position_near_pet()

    def _error(self, request_id: str, text: str) -> None:
        if request_id != self._active_request_id:
            return
        self._active_request_id = None
        self.hint_label.setText("")
        self._dismiss_approval()
        self._set_reply_text(f"请求失败：{text}")
        self.island_status("出岔子了", busy=False)
        if self.island_mode:
            # 岛上只报三个字，完整错误得有个地方看——把面板叫出来
            self.open_work_station()
        if self._ws_dark:
            # 面板里错误也长在对话流里（面板没有单独钉在底部的正文块了）
            self._set_output_markdown("")
            self._push_her_reply(f"请求失败：{text}", final=True)
        else:
            # 报错必须看得见：卡片默认收起，这里强制展开（对白装不下错误详情）。
            self._full_open = True
            self._render_reply()

    def _stopped(self, request_id: str) -> None:
        if request_id != self._active_request_id:
            return
        self._active_request_id = None
        self.hint_label.setText("已停止")
        self._dismiss_approval()
        self.island_status("停住了", busy=False)

    def request_in_flight(self) -> bool:
        """是否有自己发出的、尚未到终态的请求在途。

        预览式改写（``show_reply``/``show_feedback``）会把 ``_active_request_id``
        清成 None，此后真实完成回调按 request_id 匹配全部**静默返回**（回答既不
        上屏也不落库）。所以任何"接管气泡显示"的外部入口都必须先问这一句。
        """
        return self._active_request_id is not None or self.service.busy or self.laji_service.busy

    # ------------------------------------------------------------ 显示
    def _set_reply_text(self, full_text: str) -> None:
        """记录 AI 回答全文，并算出气泡内展示文本（超限截断 + 提示全文位置）。

        全文与展示文本分开：会话历史/聊天窗始终拿全文，气泡只展示开头一段，
        免得长回答把头顶气泡撑成一堵墙。
        """
        self._reply_full = str(full_text or "")
        self._reply_text = truncate_bubble_text(
            self._reply_full, _REPLY_PREVIEW_LIMIT, _REPLY_PREVIEW_SUFFIX
        )
        self._reply_truncated = self._reply_text != self._reply_full

    def _set_page_controls_visible(self, on: bool) -> None:
        """显示/隐藏分页箭头与页码（截断预览时只保留「去聊天窗」按钮）。"""
        for widget in (self.prev_btn, self.page_label, self.next_btn):
            widget.setVisible(on)

    def _render_reply(self) -> None:
        text = self._reply_text
        if len(text) > _PAGE_SIZE:
            self._pages = [text[i:i + _PAGE_SIZE] for i in range(0, len(text), _PAGE_SIZE)]
            self._show_page(0)
            self._set_page_controls_visible(self._full_open)
            self.page_widget.setVisible(self._full_open)
            return
        self._pages = []
        # 截断预览：文案末尾已提示「全文见聊天窗」，这里只露出直达按钮；
        # 分页箭头/页码对一段预览没有意义，隐藏。
        self._set_page_controls_visible(self._full_open and not self._reply_truncated)
        self.page_widget.setVisible(self._full_open and self._reply_truncated)
        self._set_output_markdown(text)

    def _show_page(self, index: int) -> None:
        if not self._pages:
            return
        self._page = max(0, min(index, len(self._pages) - 1))
        self._set_output_markdown(self._pages[self._page])
        self.page_label.setText(f"{self._page + 1}/{len(self._pages)}")

    def _set_output_markdown(self, text: str) -> None:
        """助手回复按 Markdown 渲染；所有 chat surface 统一渲染，落盘原文不变。

        空文本清空即可；非空走 RichText。分页是对纯文本切的，跨页围栏代码块
        可能渲染不完整——气泡本来就是预览面，全文在聊天窗（分页为既有行为，
        不在这里改）。
        """
        if not text:
            self.output.setText("")
            self.output_scroll.setVisible(False)
            self._refit_later()
            return
        self.output.setTextFormat(Qt.TextFormat.RichText)
        self.output.setText(markdown_to_html(text))
        # v2：回答默认不进卡片（只有雾）。`_full_open` 是唯一开关——点雾才展开。
        self.output_scroll.setVisible(self._full_open)
        self.prev_btn.setEnabled(self._page > 0)
        self.next_btn.setEnabled(self._page < len(self._pages) - 1)
        self._refit_later()

    def _refit_later(self) -> None:
        """内容长短/显隐变了就让窗口重新贴合内容，同一事件轮内只做一次。

        窗口高度只在弹出时 ``adjustSize()`` 过：空的回复区一收起、流式增量把回复区
        从 60px 撑到 220px，父窗口都还留在旧高度上——多出来或少掉的那截就是气泡里
        那块空白。合并到一轮事件循环里重排，避免流式逐帧 adjustSize 抖动。
        """
        if self._refit_pending:
            return
        self._refit_pending = True
        QTimer.singleShot(0, self, self._refit_now)

    def _refit_now(self) -> None:
        self._refit_pending = False
        before = self.size()
        self.adjustSize()
        if self.isVisible() and self.size() != before:
            # 尺寸变了才跟着锚点重定位：气泡是贴着桌宠头顶长上去的。
            self.position_near_pet()

    # ------------------------------------------------------------ 对话气泡
    def _clear_history(self) -> None:
        while self.history_layout.count() > 1:
            item = self.history_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.history_scroll.setVisible(False)
        self.chips_widget.setVisible(False)
        self._stream_row = None
        self._full_open = False
        self._set_output_markdown("")

    def _append_message(self, role: str, text: str, html: bool = False) -> QLabel | None:
        """往历史区追加一条对话气泡，返回那一行；role 取 ``me`` / ``her``。

        贴身处历史区只是预览面：她的话留一行痕迹，整段归对白。工位面板是完整
        对话面：她的话整段进流，跟用户的话一起滑，不再单独钉在输入框上方。
        """
        body = str(text or "").strip()
        if not body:
            return None
        if role != "me" and not self._ws_dark:
            # 她的话在贴身处只留一行痕迹：整段回答归对白（点对白看全文），
            # 面板里再贴一遍就等于没改（真机截图被这么打过脸）。
            body = _her_line(body, _HER_LINE_LIMIT)
            html = False
            if not body:
                return None
        label = QLabel()
        label.setObjectName("quick-chat-msg-me" if role == "me" else "quick-chat-msg-her")
        if html:
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setText(markdown_to_html(body))
        else:
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setText(body)
        label.setWordWrap(True)
        # 固定上限而不是跟 self.width()：窗口宽度在 adjustSize 前可能还是旧值，
        # 拿它算宽度会让新气泡忽宽忽窄。
        label.setMaximumWidth(232)
        # 短文也要有个下限宽度：QLabel 开了 wordWrap 之后，布局会把窄文本挤成
        # 竖条（真机上「那我是谁」被折成两行就是这么来的）。+26 是 me 行的
        # padding 7px 11px 加边框。
        label.setMinimumWidth(min(232, max(24, label.fontMetrics().horizontalAdvance(body) + 34)))
        label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        if self._ws_dark and role != "me":
            # 面板里她那行要占满整行（不然被 sizeHint 卡成 140px，长段落挤成窄条）
            label.setMaximumWidth(WORKSTATION_W - 40)
            label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)
        if role == "me":
            row_layout.addStretch(1)
            row_layout.addWidget(label)
        else:
            row_layout.addWidget(label)
            row_layout.addStretch(1)
        self.history_layout.insertWidget(max(0, self.history_layout.count() - 1), row)
        self.history_scroll.setVisible(True)
        self._refit_later()
        QTimer.singleShot(0, self, self._scroll_history_bottom)
        return label

    def _push_her_reply(self, text: str, *, final: bool = False) -> None:
        """面板里她的回答直接长进对话流（不再单独钉在输入框上方）。

        流式期间复用同一行原地改字，收尾时定格：整段对话只有一个滚动条，
        往下滑能一路看到最早那句。
        """
        body = str(text or "").strip()
        if not body:
            return
        label = self._stream_row
        if label is None:
            label = self._append_message("her", body, html=True)
            if label is None:
                return
            self._stream_row = None if final else label
            return
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setText(markdown_to_html(body))
        label.setMaximumWidth(WORKSTATION_W - 40)
        if final:
            self._stream_row = None
        self._refit_later()
        QTimer.singleShot(0, self, self._scroll_history_bottom)

    def _scroll_history_bottom(self) -> None:
        bar = self.history_scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _replay_history(self) -> None:
        """重新打开气泡时回填最近几条对话；没有上下文时露出预设开场。"""
        self._clear_history()
        messages = list(getattr(self.session, "messages", []) or [])
        limit = _WORKSTATION_REPLAY_LIMIT if self._ws_dark else _HISTORY_REPLAY_LIMIT
        recent = messages[-limit:]
        for message in recent:
            role = "me" if getattr(message, "role", "") == "user" else "her"
            self._append_message(role, str(getattr(message, "content", "") or ""), html=role == "her")
        self.chips_widget.setVisible(not recent)

    def _ask_preset(self, text: str) -> None:
        if self.service.busy:
            return
        self.input.setText(text)
        self._send()

    def _show_key_hint(self, config) -> None:
        """provider 没凭据：直接在气泡里说人话，不发注定 401 的请求。"""
        name = str(getattr(config, "name", "") or "当前模型").strip()
        self.setup_label.setText(
            f"还没配 {name} 的 API Key，填上就能聊。"
            "入口：托盘图标右键 →「AI 设置」→ API Key。"
        )
        self.setup_widget.setVisible(True)
        self.chips_widget.setVisible(False)
        self.adjustSize()
        self.position_near_pet()
        if self.island_mode:
            # 岛只报一句「还没配 key」，配置入口在面板里——不把面板叫出来等于没说
            self.open_work_station()

    def _open_ai_settings(self) -> None:
        """「去 AI 设置」：legacy 直开 AI 设置页，sprite 壳退到设置窗/聊天窗。"""
        pet = self.pet_window
        opener = getattr(pet, "open_chat_settings", None)
        if callable(opener):
            try:
                opener()
            except Exception:
                log.debug("快速对话：打开 AI 设置失败", exc_info=True)
                self._open_full_chat()
                return
            self.close()
            return
        self._open_full_chat()

    def _open_laji_work(self) -> None:
        """「打工」：把这一下交给 Laji Agent，输入框里已经写的话一并带过去。

        与 ``_open_full_chat`` 的分别在于 ``force=True``：后者经 ``app.open_chat``
        走，Laji 没跑时回退自带聊天窗；而这个按钮的语义就是「打开 Laji」，冷启动
        也算命中，所以不能先问进程在不在。

        先让桌宠演一遍「走过去按一下」（work_choreo）；壳不具备演出面（老架构的
        PetWindow 没有 sprite）或素材不全时，choreo_for 直接返回 None，落到原来
        那条同步拉起。
        """
        from .agent_bridge import open_laji

        text = self.input.text().strip()
        pet = getattr(self, "pet_window", None)
        if pet is not None:
            try:
                from .work_choreo import choreo_for

                choreo = choreo_for(pet, getattr(pet, "sprite", None))
                if choreo is not None and choreo.start(text):
                    self.close()
                    return
            except Exception:
                pass  # 演出失败不许影响「打工」本身
        if open_laji(text, force=True):
            self.close()
            return
        # 协议没注册 / 系统没接手：退回落旧入口，按钮不能变成死项。
        self._open_full_chat()

    def _current_run_id(self) -> str:
        """气泡这一轮在 Laji 里的 run id；自带 provider 的 ChatService 没有 run。"""
        service = getattr(self, "laji_service", None)
        return str(getattr(service, "run_id", "") or "")

    def _open_full_chat(self) -> None:
        """「去聊天窗」：打开 Laji 里这一轮所在的会话，而不是一个空白新会话。"""
        pet = self.pet_window
        run_id = self._current_run_id()
        opener = getattr(pet, "open_chat_session", None) if pet is not None else None
        if callable(opener) and run_id:
            opener(run_id)
            return
        if pet is not None and callable(getattr(pet, "on_open_chat", None)):
            pet.on_open_chat()
        elif hasattr(self, "open_chat_callback") and callable(self.open_chat_callback):
            self.open_chat_callback()

    def event(self, event) -> bool:
        if event.type() == QEvent.Type.WindowDeactivate and self.isVisible():
            # Cocoa 在另一个应用内窗口仍活动时首次 show/activate Tool 窗口，
            # 会产生一次过渡性的 WindowDeactivate；此时同步 close 会留下只
            # 有原生灰色底板的空白窗口。下一事件轮的 activeWindow 已稳定，
            # 可以区分这次过渡和用户真正切走焦点。
            if not self._deactivate_check_pending:
                self._deactivate_check_pending = True
                QTimer.singleShot(0, self, self._close_if_still_inactive)
        return super().event(event)

    def _close_if_still_inactive(self) -> None:
        self._deactivate_check_pending = False
        if self.isVisible() and QApplication.activeWindow() is not self:
            self.close()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.service.busy:
            self.service.stop()
        if self._capture_compat and self._capture_host is not None:
            setter = getattr(self._capture_host, "set_capture_headroom", None)
            if setter is not None:
                try:
                    setter(0)
                except RuntimeError:
                    pass  # 宿主窗口已在销毁中
        super().closeEvent(event)
