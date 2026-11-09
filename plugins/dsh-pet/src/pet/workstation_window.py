"""小工位：企微式的三栏窗口（图标条 / 会话列表 / 面板）。

只有三格——消息、待办、工作台。数据一律走已有的层，不新开通道：

- 会话：``QuickChatBubble.store``（SessionStore）只读 ``list`` / ``load``，
  点哪条看哪条；发送交回 ``QuickChatBubble.send_text``，provider 选择、落库、
  信号一概不复制。
- 审批：``PetApp._on_laji_attention`` 递进来的 ``PendingApproval`` 按 run 存表；
  允许/拒绝回 ``laji_service.approve(run_id, call_id, approved)``。
  上游 ``ApprovalWatcher`` 本来就是逐 run 发的（``_probed`` 是多工位表），
  这一层之前被 ``quick_chat`` 的单槽位吞掉了，这里补回来。
- 工作台：按钮直接调壳上已有的槽，不另造入口。

窗口不持有配置、不写文件；关掉就是关掉，重新打开从磁盘和审批表重建。
"""

from __future__ import annotations

import base64
import html
import hashlib
import json
import logging
import mimetypes
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QRegularExpression,
    QSize,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QGuiApplication,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QTextBrowser,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .tool_names import approval_detail, approval_headline
from .agent_link import pet_toolkit
from .chat.markdown_view import markdown_to_html
from .chat.model_tiers import TIER_LABELS, normalize_tier
from .chat.widgets import (
    MAX_IMAGE_BYTES,
    MAX_TEXT_TOTAL_CHARS,
    AttachmentTextEdit,
    _attachment_is_text,
    _discard_clipboard_cache,
    validate_attachment_additions,
)

log = logging.getLogger(__name__)

# 素材在 src/assets，不是 src/pet/assets（跟 quick_chat 的取法一致）：上一版少了一
# 级，头像帧永远读不到，圆环里就是空的。
_ASSETS = Path(__file__).resolve().parent.parent / "assets"

# 正文附件行里这些扩展名的名字已经被图卡代岗了，不再另挂文件卡。
_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff")

WIN_W = 1000
WIN_H = 566
RAIL_W = 72
LIST_W = 304
# 待批卡不铺满整窗：铺满后按钮被推到最右边，跟内容隔着一片空白。
ROW_MAX_W = 520

# 四套主题：强调色 + 三层底色各自成套，切主题不是只换按钮颜色。
THEMES: tuple[tuple[str, str, dict], ...] = (
    (
        "amber",
        "琥珀",
        {
            # 与原型同一套：深色磨砂玻璃 + 金色 #e8a33d（见 quick_chat._WS_*）。
            "shell": "#171a20", "rail": "rgba(18,21,25,224)", "list": "rgba(22,25,30,214)",
            "chat": "rgba(27,30,37,216)",
            "line": "rgba(255,255,255,38)", "line2": "rgba(255,255,255,18)",
            "fg": "#eef1f8", "fg2": "#c9d0dc", "dim": "rgba(255,255,255,150)",
            "dim2": "rgba(255,255,255,105)",
            "acc": "#e8a33d", "accSoft": "rgba(232,163,61,34)", "accLine": "rgba(232,163,61,110)",
            "ink": "#241a06", "bub": "transparent", "bubMe": "#e8a33d",
            "ok": "#67d7a2", "bad": "#e08581", "warn": "#e7bd74",
        },
    ),
    (
        "starsea",
        "星海鲸裙",
        {
            # 壁纸 whale-v2 的 accent #5a7fc8（难蓝），整套里最柔的一支。
            "shell": "#101827", "rail": "#0c131f", "list": "#0e1622", "chat": "#121c2c",
            "line": "rgba(180,200,255,30)", "line2": "rgba(180,200,255,16)",
            "fg": "#e9eefb", "fg2": "#c4cfe9", "dim": "#8f9ab8", "dim2": "#67728f",
            "acc": "#5a7fc8", "accSoft": "rgba(90,127,200,34)", "accLine": "rgba(90,127,200,100)",
            "ink": "#f2f6ff", "bub": "#1b2536", "bubMe": "#26375c",
            "ok": "#67d7a2", "bad": "#e08581", "warn": "#e7bd74",
        },
    ),
    (
        "white",
        "白色",
        {
            # 浅色：白底不做玻璃，靠一档中性灰拉开层次；文字全部翻成深色。
            "shell": "#f2f3f6", "rail": "rgba(237,238,242,240)", "list": "rgba(243,244,247,235)",
            "chat": "rgba(250,250,252,238)",
            "line": "rgba(0,0,0,34)", "line2": "rgba(0,0,0,18)",
            "fg": "#1a1d24", "fg2": "#3f4653", "dim": "rgba(0,0,0,155)",
            "dim2": "rgba(0,0,0,105)",
            "acc": "#b8791a", "accSoft": "rgba(184,121,26,30)", "accLine": "rgba(184,121,26,120)",
            "ink": "#fffaf1", "bub": "#ffffff", "bubMe": "#f3dcb4",
            "ok": "#1c8a5b", "bad": "#c2403b", "warn": "#8f6410",
            "dot": "#ffffff",
            "light": True,
        },
    ),
    (
        "black",
        "黑色",
        {
            # 纯黑：底全是 #000，“层次”只能靠一层白叠加和描边。
            "shell": "#000000", "rail": "#050506", "list": "rgba(12,12,14,245)",
            "chat": "#0a0a0c",
            "line": "rgba(255,255,255,28)", "line2": "rgba(255,255,255,14)",
            "fg": "#f4f6fa", "fg2": "#c6cdda", "dim": "rgba(255,255,255,158)",
            "dim2": "rgba(255,255,255,108)",
            "acc": "#e7ebf3", "accSoft": "rgba(231,235,243,30)", "accLine": "rgba(231,235,243,96)",
            "ink": "#0a0b0e", "bub": "rgba(255,255,255,10)", "bubMe": "#1a1c21",
            "ok": "#67d7a2", "bad": "#f09292", "warn": "#e7bd74",
            "dot": "#0b0c0f",
        },
    ),
)

_QSS = """
#wsRoot{background:%(shell)s;border:1px solid %(line)s;border-radius:18px;}
#wsRail{background:%(rail)s;border-right:1px solid %(line2)s;
        border-top-left-radius:18px;border-bottom-left-radius:18px;}
QToolButton#Rail{background:transparent;border:none;border-radius:10px;color:%(fg2)s;
                 font-size:12px;padding:0px 0px 2px 0px;}
QToolButton#Rail:hover{color:%(fg)s;background:rgba(255,255,255,12);}
QToolButton#Rail:checked{background:%(accSoft)s;color:%(acc)s;
                        border:1px solid %(accLine)s;font-weight:600;}
QLineEdit#Search{background:rgba(255,255,255,12);border:1px solid %(line2)s;border-radius:9px;
                 color:%(fg)s;font-size:12.5px;padding:6px 10px;}
QPushButton#Plus{background:rgba(255,255,255,12);border:none;border-radius:8px;
                 color:%(fg2)s;font-size:15px;font-weight:600;}
QPushButton#Plus:hover{background:rgba(255,255,255,20);color:%(fg)s;}
QListWidget#Sessions{background:transparent;border:none;outline:none;}
QListWidget#Sessions::item{padding:0px;border:none;color:%(fg2)s;}
QListWidget#Sessions::item:selected{background:transparent;}
#wsChat{background:%(chat)s;border-top-right-radius:18px;border-bottom-right-radius:18px;}
#Title{color:%(fg)s;font-size:15px;font-weight:600;}
#Dot{color:%(acc)s;font-size:10px;}
#WsTag{color:%(dim)s;background:rgba(255,255,255,12);border-radius:6px;
       font-size:10.5px;padding:2px 7px;}
#Sub{color:%(dim2)s;font-size:11.5px;}
QScrollArea{border:none;background:transparent;}
/* 滚动区的 viewport 自己就是一层 QWidget：只写 >QWidget>QWidget 盖不到它，
   白底就是它画出来的（对话流一片白的真凶）。 */
QScrollArea>QWidget, QScrollArea>QWidget>QWidget{background:transparent;}
/* 对话流是一整篇只读文档：选择/复制/全选交给 Qt，气泡改由表格拼出来。 */
QTextBrowser#FlowView{background:transparent;border:none;}
/* 输入框本体：附件卡和文字都在这一圈边框里面。 */
QFrame#WsInputBox{background:rgba(255,255,255,18);border:1px solid %(line2)s;
                  border-radius:14px;}
QPlainTextEdit#WsInput{background:transparent;border:none;color:%(fg)s;font-size:13px;
                      padding:2px 3px;}
/* 附件：图片走缩略图卡（_AttachCard 自绘），其余走「类型徽标 + 文件名」的窄条。 */
QFrame#AttFile{background:rgba(255,255,255,14);border:1px solid rgba(255,255,255,26);
               border-radius:8px;}
QFrame#AttFile:hover{background:rgba(255,255,255,24);border:1px solid rgba(255,255,255,40);}
#AttName{color:%(fg2)s;font-size:11.5px;background:transparent;}
QToolButton#AttRemove{background:rgba(0,0,0,150);color:#ffffff;border:none;
                      border-radius:9px;font-size:10px;padding:0px;}
QToolButton#AttRemove:hover{background:rgba(0,0,0,205);}
QToolButton#AttRemoveFlat{background:transparent;color:%(dim2)s;border:none;
                          border-radius:6px;font-size:10px;padding:0px;}
QToolButton#AttRemoveFlat:hover{background:rgba(255,255,255,24);color:%(fg)s;}
QPushButton#Fold{color:%(dim2)s;font-size:11px;}
QPushButton#Send{background:%(acc)s;color:%(ink)s;border:none;border-radius:15px;
                 font-size:16px;font-weight:700;padding:0px;}
QPushButton#Ghost{background:rgba(255,255,255,12);color:%(fg2)s;border:none;
                  border-radius:7px;font-size:11.5px;padding:4px 11px;}
QPushButton#Allow{background:%(acc)s;color:%(ink)s;border:none;border-radius:7px;
                  font-size:12px;font-weight:600;padding:5px 14px;}
QPushButton#Deny{background:transparent;color:%(dim)s;border:1px solid %(line)s;
                 border-radius:7px;font-size:12px;padding:5px 14px;}
/* 待批卡：工位本身就是深色，卡不能另起一块米色。左侧一道岭色竖线标“在等你”。
   边框要分开写：Qt 里 border 简写会把已单独设的 border-left 盖掉。 */
#ApRow{background:rgba(255,255,255,9);border:1px solid %(line2)s;
       border-left:3px solid %(acc)s;border-radius:11px;}
#ApRowQuiet{background:rgba(255,255,255,5);border:1px solid %(line2)s;
            border-left:3px solid %(line2)s;border-radius:11px;}
#ApTitle{color:%(fg)s;font-size:13px;font-weight:600;}
#ApMeta{color:%(dim)s;font-size:11.5px;}
#ApCmd{color:%(dim)s;font-size:11px;}
#ApWs{background:rgba(255,255,255,14);color:%(dim)s;border-radius:5px;font-size:10px;
      font-weight:600;padding:2px 7px;}
#PageHead{color:%(fg)s;font-size:16px;font-weight:600;}
#PageSub{color:%(dim2)s;font-size:11.5px;}
#BenchCard{background:rgba(255,255,255,9);border:1px solid %(line)s;border-radius:11px;}
#BenchCard:hover{background:rgba(255,255,255,16);border:1px solid %(line2)s;}
#BenchTitle{color:%(fg)s;font-size:13.5px;font-weight:600;}
#BenchDesc{color:%(dim2)s;font-size:11.5px;}
#BenchGroup{color:%(dim2)s;font-size:11px;font-weight:600;letter-spacing:.08em;}
#Hair{background:%(line2)s;}
/* 能力卡：照 agent「技能与工具」的卡片网格（三列），皮肤用宠物自己这套深色 */
#CapTile{background:rgba(255,255,255,8);border:1px solid %(line2)s;border-radius:12px;}
#CapTile:hover{background:rgba(255,255,255,12);border:1px solid %(line)s;}
QPushButton#CapAdd{background:rgba(255,255,255,14);border:none;border-radius:6px;
                   color:%(fg2)s;font-size:12px;font-weight:600;padding:0px;}
QPushButton#CapAdd:hover{background:rgba(255,255,255,24);color:%(fg)s;}
QPushButton#CapAdd[done="true"]{background:rgba(63,178,127,46);color:%(ok)s;}
QPushButton#CapAdd[done="true"]:hover{background:rgba(63,178,127,66);color:%(ok)s;}
#CapChipMuted{background:transparent;color:%(dim2)s;border-radius:5px;
              font-size:10px;padding:2px 0px;}
#PackScrim{background:rgba(8,10,14,170);}
#PackSheet{background:%(shell)s;border:1px solid %(line)s;border-radius:14px;}
#PackName{font-size:16px;font-weight:600;color:%(fg)s;}
#PackMeta{font-size:11.5px;color:%(dim2)s;}
#PackDesc{font-size:12.5px;color:%(fg2)s;}
#PackGroup{font-size:11px;font-weight:600;color:%(dim2)s;}
#PackItem{background:rgba(255,255,255,6);border:1px solid %(line2)s;border-radius:9px;}
#PackItemName{font-size:12.5px;font-weight:600;color:%(fg)s;}
#PackItemDesc{font-size:11.5px;color:%(dim2)s;}
#PackItemKind{background:rgba(255,255,255,10);color:%(dim2)s;border-radius:5px;
              font-size:10px;padding:1px 6px;}
#PackItemMark{background:rgba(232,163,61,26);color:%(acc)s;border-radius:6px;font-size:11px;}
#PackItem:hover{background:rgba(255,255,255,12);border-color:%(accLine)s;}
#PackBody{background:rgba(0,0,0,70);border:1px solid %(line2)s;border-radius:9px;color:%(fg2)s;
          font-family:"Cascadia Mono","Consolas","Microsoft YaHei",monospace;font-size:11.5px;
          padding:8px;}
QTextBrowser#PackMd{background:rgba(0,0,0,70);border:1px solid %(line2)s;border-radius:9px;color:%(fg2)s;
                    font-size:12.5px;padding:8px 12px;}
QPushButton#PackPrimary{background:%(acc)s;color:%(ink)s;border:none;border-radius:8px;
                        font-size:12.5px;font-weight:600;padding:7px 18px;}
QPushButton#PackPrimary:hover{background:%(accLine)s;}
QPushButton#PackPrimary:disabled{background:rgba(255,255,255,12);color:%(dim2)s;}
QPushButton#PackDanger{background:rgba(214,90,86,26);color:%(bad)s;border:1px solid rgba(214,90,86,66);
                       border-radius:8px;font-size:12.5px;font-weight:600;padding:7px 18px;}
QPushButton#PackDanger:hover{background:rgba(214,90,86,46);}
#CapTileHot{background:%(accSoft)s;border:1px solid %(accLine)s;border-radius:12px;}
#CapName{color:%(fg)s;font-size:13px;font-weight:600;}
#CapDesc{color:%(dim)s;font-size:11.5px;}
#CapChip{background:rgba(255,255,255,14);color:%(fg2)s;border-radius:5px;
        font-size:10px;padding:2px 6px;}
QPushButton#CapChip{border:none;text-align:center;}
QPushButton#CapChip:hover{background:rgba(255,255,255,28);color:%(fg)s;}
QPushButton#CapChipMuted{border:none;text-align:center;}
QPushButton#CapChipMuted:hover{color:%(fg2)s;}
#CapOn{background:rgba(63,178,127,46);color:%(ok)s;border-radius:7px;
      font-size:10px;padding:1px 7px;}
#CapOff{background:rgba(255,255,255,14);color:%(dim)s;border-radius:7px;
       font-size:10px;padding:1px 7px;}
#CapErr{background:rgba(224,106,106,44);color:%(bad)s;border-radius:7px;
       font-size:10px;padding:1px 7px;}
#CapWait{background:rgba(224,169,75,44);color:%(warn)s;border-radius:7px;
        font-size:10px;padding:1px 7px;}
QPushButton#CapLink{background:transparent;border:none;color:%(acc)s;font-size:11px;
                   padding:0px;text-align:left;}
QPushButton#CapLink:hover{color:%(fg)s;}
QPushButton#CapIcon{background:rgba(255,255,255,12);border:none;border-radius:6px;
                   color:%(dim)s;font-size:11px;padding:0px;}
QPushButton#CapIcon:hover{background:rgba(255,255,255,22);color:%(fg)s;}
QLineEdit#CapSearch{background:rgba(255,255,255,10);border:1px solid %(line2)s;
                   border-radius:13px;color:%(fg)s;font-size:12.5px;padding:6px 13px;}
QWidget#CapSegBar{background:rgba(255,255,255,7);border:1px solid %(line2)s;border-radius:14px;}
QPushButton#CapSeg{background:transparent;border:none;border-radius:11px;color:%(dim)s;
                  font-size:11.5px;padding:5px 10px;}
QPushButton#CapSeg:hover{color:%(fg2)s;}
QPushButton#CapSeg:checked{background:rgba(255,255,255,16);color:%(fg)s;font-weight:600;}
QWidget#CapTabBar{background:rgba(255,255,255,7);border-radius:15px;}
QPushButton#CapTab{background:transparent;border:none;border-radius:12px;color:%(dim)s;
                  font-size:12px;padding:6px 15px;}
QPushButton#CapTab:hover{color:%(fg2)s;}
QPushButton#CapTab:checked{background:rgba(255,255,255,16);color:%(fg)s;font-weight:600;}
QToolButton#CapGear{background:rgba(255,255,255,10);border:1px solid %(line2)s;border-radius:13px;
                   color:%(fg2)s;font-size:13px;padding:0px;}
QToolButton#CapGear:hover{background:rgba(255,255,255,20);color:%(fg)s;border:1px solid %(line)s;}
QToolButton#CapGear::menu-indicator{image:none;width:0px;}
QScrollBar:vertical{background:transparent;width:8px;margin:2px 0px;}
QScrollBar::handle:vertical{background:rgba(255,255,255,44);border-radius:4px;min-height:24px;}
QScrollBar::handle:vertical:hover{background:rgba(255,255,255,78);}
QScrollBar:horizontal{background:transparent;height:8px;margin:0px 2px;}
QScrollBar::handle:horizontal{background:rgba(255,255,255,44);border-radius:4px;min-width:24px;}
QScrollBar::handle:horizontal:hover{background:rgba(255,255,255,78);}
QScrollBar::add-line,QScrollBar::sub-line{width:0px;height:0px;border:none;background:none;}
QScrollBar::add-page,QScrollBar::sub-page{background:transparent;}
QMenu{background:%(chat)s;border:1px solid %(line)s;border-radius:10px;padding:5px;}
QMenu::item{background:transparent;color:%(fg2)s;font-size:12.5px;padding:7px 24px 7px 14px;
            border-radius:7px;}
QMenu::item:selected{background:%(accSoft)s;color:%(fg)s;}
QMenu::item:disabled{color:%(dim2)s;}
QMenu::separator{height:1px;background:%(line2)s;margin:4px 8px;}
QPushButton#CapAct{background:transparent;border:none;border-radius:6px;color:%(dim)s;
                   font-size:13px;padding:0px;}
QPushButton#CapAct:hover{background:rgba(255,255,255,20);color:%(fg)s;}
QPushButton#CapAct[danger="true"]:hover{background:rgba(224,106,106,60);color:%(bad)s;}
#CapDialog{background:%(chat)s;border:1px solid %(line)s;border-radius:14px;}
#CapDialogHead{color:%(fg)s;font-size:14px;font-weight:600;}
QToolButton#CapIcon{background:transparent;border:none;border-radius:8px;}
QToolButton#CapIcon:hover{background:rgba(255,255,255,16);}
QLineEdit#CapField{background:rgba(255,255,255,9);border:1px solid %(line2)s;border-radius:9px;
                   color:%(fg)s;font-size:12.5px;padding:7px 11px 2px;min-height:22px;}
QLineEdit#CapField:focus{border:1px solid %(accLine)s;}
QPlainTextEdit#CapField{background:rgba(255,255,255,9);border:1px solid %(line2)s;border-radius:9px;
                       color:%(fg)s;font-size:12.5px;padding:7px 9px;
                       font-family:Consolas,"Cascadia Mono",monospace;}
/* 只读 Markdown 正文（技能/规则/专家说明）：排版靠 md4c，字体走界面那套，
   不能跟上面那条一样落到等宽上——否则中文标题会缺字、正文像 diff。 */
QTextBrowser#CapMd{background:rgba(255,255,255,9);border:1px solid %(line2)s;border-radius:9px;
                   color:%(fg)s;font-size:12.5px;padding:6px 11px;}
QTextBrowser#CapMd:focus{border:1px solid %(line2)s;}
QPushButton#CapGhost{background:rgba(255,255,255,10);border:1px solid %(line2)s;border-radius:9px;
                     color:%(fg2)s;font-size:12.5px;padding:7px 16px;}
QPushButton#CapGhost:hover{background:rgba(255,255,255,18);color:%(fg)s;}
QPushButton#CapSave{background:%(acc)s;border:none;border-radius:9px;color:%(ink)s;
                    font-size:12.5px;font-weight:600;padding:7px 18px;}
QPushButton#CapSave:hover{background:%(acc)s;}
/* 设置窗：左边选分区，右边是那一区的条目。窗口自己的事（外观/窗口行为）在这；
   模型清单与 agent 视图共用同一份 settings.json，也放在这里，别再另开入口。 */
QPushButton#SetNav{background:transparent;border:none;border-radius:8px;color:%(dim)s;
                   font-size:12.5px;text-align:left;padding:8px 12px;}
QPushButton#SetNav:hover{background:rgba(255,255,255,14);color:%(fg2)s;}
QPushButton#SetNav:checked{background:%(accSoft)s;color:%(acc)s;font-weight:600;}
QLabel#SetHead{color:%(dim2)s;font-size:10.5px;font-weight:600;letter-spacing:.09em;}
QLabel#SetName{color:%(fg)s;font-size:12.5px;}
QLabel#SetGroup{color:%(fg)s;font-size:12px;font-weight:600;}
QLabel#SetHint{color:%(dim)s;font-size:11px;}
QLabel#SetHint[tone="ok"]{color:%(ok)s;}
QLabel#SetHint[tone="bad"]{color:%(bad)s;}
QLabel#SetRowName{color:%(fg)s;font-size:13px;font-weight:600;}
QLabel#SetMark{color:%(acc)s;font-size:11px;}
QFrame#SetRow{background:rgba(255,255,255,7);border:1px solid %(line2)s;border-radius:12px;}
QFrame#SetRow:hover{background:rgba(255,255,255,12);border:1px solid %(line)s;}
QLabel#SetBadge{background:%(accSoft)s;border:1px solid %(accLine)s;border-radius:8px;
                color:%(acc)s;font-size:10.5px;font-weight:600;padding:2px 8px;}
QLabel#SetBadge[state="off"]{background:rgba(255,255,255,8);border:1px solid %(line2)s;
                             color:%(dim)s;font-weight:500;}
QLabel#SetBadge[state="warn"]{background:rgba(224,106,106,26);border:1px solid rgba(224,106,106,90);
                              color:%(bad)s;font-weight:500;}
QLabel#SetFieldLabel{color:%(dim)s;font-size:11.5px;}
QPushButton#SetRemove{background:transparent;border:none;border-radius:7px;color:%(dim2)s;
                      font-size:11.5px;padding:3px 9px;}
QPushButton#SetRemove:hover{background:rgba(224,106,106,45);color:%(bad)s;}
QFrame#SetSplit{background:%(line2)s;border:none;}
QComboBox#CapField{background:rgba(255,255,255,9);border:1px solid %(line2)s;border-radius:9px;
                   color:%(fg)s;font-size:12.5px;padding:5px 10px;min-height:22px;}
QComboBox#CapField:focus{border:1px solid %(accLine)s;}
QComboBox#CapField::drop-down{border:none;width:18px;}
QComboBox#CapField QAbstractItemView{background:%(shell)s;color:%(fg)s;border:1px solid %(line)s;
                                     padding:4px;outline:none;
                                     selection-background-color:%(accSoft)s;selection-color:%(fg)s;}
QFrame#ThemeCard{background:rgba(255,255,255,9);border:1px solid %(line)s;border-radius:10px;}
QFrame#ThemeCard:hover{background:rgba(255,255,255,17);}
QFrame#ThemeCard[on="true"]{background:%(accSoft)s;border:1px solid %(accLine)s;}
"""


def _theme(key: str) -> tuple[str, str, dict]:
    for entry in THEMES:
        if entry[0] == key:
            return entry
    return THEMES[0]


def _qss(colors: dict) -> str:
    """套主题色出样式表。

    QSS 里的层次都是「白色半透明叠一层」写的，在浅色主题上等于什么都没画
    （白底 + 白叠）——那些悬停、分段、输入框的边界会整片消失。浅色主题就把
    这些叠加整体翻成等透明的黑色：明度差守住了，强度和原设计一致。
    """
    sheet = _QSS % colors
    if colors.get("light"):
        sheet = sheet.replace("rgba(255,255,255,", "rgba(0,0,0,")
    return sheet


_ACTIVE_COLORS: dict = THEMES[0][2]


def _veil(alpha: int, colors: dict | None = None) -> QColor:
    """自绘用的“提亮一层”：深色主题叠白，浅色主题叠黑，强度照旧。"""
    palette = colors if isinstance(colors, dict) else _ACTIVE_COLORS
    if palette.get("light"):
        return QColor(0, 0, 0, alpha)
    return QColor(255, 255, 255, alpha)


def _rgba(spec: str) -> QColor:
    """QSS 里的 ``rgba(r,g,b,a)`` 要自己解：QColor 只认 #AARRGGBB / 颜色名。"""
    text = str(spec or "").strip()
    if not text.startswith("rgba("):
        return QColor(text or "#000000")
    parts = [p.strip() for p in text[text.find("(") + 1 : text.rfind(")")].split(",")]
    if len(parts) != 4:
        return QColor(0, 0, 0, 0)
    try:
        return QColor(int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3]))
    except ValueError:
        return QColor(0, 0, 0, 0)


_AVATAR_CACHE: dict[tuple[str, int, str], QPixmap] = {}
# 立绘上方取这么一截（头 + 肩）：整帧缩成圆会把人缩成一颗豆；
# 只截发顶会把脸切掉（实测：下移 24%、取 36% 才能把眼睛和下巴带上）。
_AVATAR_HEAD_OFFSET = 0.30
_AVATAR_HEAD_RATIO = 0.28


def _her_idle_clip(character_id: str) -> Path | None:
    """她 idle 的帧序列目录（第一段能读到首帧的 clip）。"""
    idle = _ASSETS / "characters" / character_id / "frameseq" / "idle"
    try:
        for clip in sorted(idle.iterdir()):
            if (clip / "f_0001.webp").is_file():
                return clip
    except OSError:
        pass
    return None


def _her_frame(character_id: str) -> Path | None:
    """她的 idle 首帧。没有专门的头像图，只能从自己的动画里截一张。"""
    clip = _her_idle_clip(character_id)
    return None if clip is None else clip / "f_0001.webp"


def _alpha_box(image) -> tuple[int, int, int, int] | None:
    """非透明区域包围盒（隔 3 像素扫）：只用来定位头在哪儿。"""
    width, height = image.width(), image.height()
    if not width or not height:
        return None
    top = bottom = -1
    left, right = width, -1
    for y in range(0, height, 3):
        for x in range(0, width, 3):
            if (image.pixel(x, y) >> 24) & 0xFF > 8:
                if top < 0:
                    top = y
                bottom = y
                left = min(left, x)
                right = max(right, x)
    if right < 0:
        return None
    return left, top, right - left + 1, bottom - top + 1


def _avatar_pixmap(character_id: str, size: int, ring: str, letter: str = "她") -> QPixmap:
    """圆形头像：立绘上半身裁圆 + 一圈细环；读不到帧就画个带首字的圆。"""
    key = (character_id, size, ring)
    cached = _AVATAR_CACHE.get(key)
    if cached is not None:
        return cached
    scale = 2.0
    span = size * scale
    pix = QPixmap(int(span), int(span))
    pix.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    circle = QPainterPath()
    circle.addEllipse(QRectF(0, 0, span, span))
    frame = _her_frame(character_id)
    source = QPixmap(str(frame)) if frame is not None else QPixmap()
    drew = False
    if not source.isNull():
        box = _alpha_box(source.toImage().convertToFormat(QImage.Format.Format_ARGB32))
        if box is not None:
            left, top, width, height = box
            side = float(min(width, max(20, int(height * _AVATAR_HEAD_RATIO))))
            painter.setClipPath(circle)
            painter.drawPixmap(
                QRectF(0, 0, span, span),
                source,
                QRectF(
                    left + (width - side) / 2.0,
                    top + height * _AVATAR_HEAD_OFFSET,
                    side,
                    side,
                ),
            )
            painter.setClipping(False)
            drew = True
    if not drew:
        painter.fillPath(circle, _rgba("rgba(232,163,61,46)"))
        font = QFont()
        font.setPixelSize(int(span * 0.42))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(ring))
        painter.drawText(
            QRectF(0, 0, span, span), int(Qt.AlignmentFlag.AlignCenter), letter[:1]
        )
    painter.setPen(QPen(QColor(ring), 1.4 * scale))
    painter.drawEllipse(QRectF(0.9, 0.9, span - 1.8, span - 1.8))
    painter.end()
    pix.setDevicePixelRatio(scale)
    _AVATAR_CACHE[key] = pix
    return pix


class LivePetView(QWidget):
    """左上角那一格直接演她本体的 idle 逐帧，不是一张静态截图。

    帧由 ``FrameSeqClip`` 提供（后台线程解码 + 异步预取，GUI 线程不碰磁盘），
    这里只负责把每帧裁到该在的位置：

    - ``figure``：整只立绘（按 alpha 包围盒裁），脚下一层淡影 + 身后一圈微光；
    - ``circle``：头肩裁圆加金环，与原先的静态头像同构图，只是会动。

    收起/隐藏时 ``pause()``，不白烧解码；没有素材就退回金圈 + 首字。
    """

    MODES: dict[str, tuple[int, int]] = {"figure": (62, 92), "circle": (40, 40)}

    # 她本人不在座位上时，这一格就是把人拖回来的口。
    dragStarted = Signal(QPoint)
    dragMoved = Signal(QPoint)
    dragReleased = Signal(QPoint)
    # 按下去没拖动的一下就是「逗她」：格子里也得有点击反应，不能只当摆件。
    clicked = Signal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        mode: str = "figure",
        ring: str = "#e8a33d",
        letter: str = "她",
    ) -> None:
        super().__init__(parent)
        self._mode = mode if mode in self.MODES else "figure"
        width, height = self.MODES[self._mode]
        self.setFixedSize(width, height)
        self._ring = QColor(ring)
        self._letter = letter
        self._character = ""
        self._clip = None
        self._box: tuple[int, int, int, int] | None = None
        self._equipped = True
        self._grabbable = False
        self._grabbing = False
        self._press_at: QPoint | None = None
        self._dragged = False

    # -- 收/拖 --------------------------------------------------------------
    def set_equipped(self, on: bool) -> None:
        """她在不在座上：不在就画成空槽（虚线圈 + 她），别画成第二只。"""
        on = bool(on)
        if on == self._equipped:
            return
        self._equipped = on
        clip = self._clip
        if clip is not None:
            (clip.resume if on else clip.pause)()
        self.update()

    def set_grabbable(self, on: bool) -> None:
        """按住这一格能把她抽出来（只在收紧状态才成立）。"""
        self._grabbable = bool(on)
        if not self._grabbable:
            self._grabbing = False

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt 口
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.globalPosition().toPoint()
            self._dragged = False
        if self._grabbable and event.button() == Qt.MouseButton.LeftButton:
            self._grabbing = True
            self.dragStarted.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt 口
        if self._press_at is not None:
            moved = event.globalPosition().toPoint() - self._press_at
            # 4px 死区：手抖不算拖，否则点一下就变成「抽出去又扔回」。
            if moved.manhattanLength() >= 4:
                self._dragged = True
        if self._grabbing:
            self.dragMoved.emit(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 口
        if event.button() == Qt.MouseButton.LeftButton:
            dragged = self._dragged
            self._press_at = None
            self._dragged = False
            if self._grabbing:
                self._grabbing = False
                if dragged:
                    self.dragReleased.emit(event.globalPosition().toPoint())
                else:
                    # 没拖动 = 点击：把她交回壳的点击入口（音效/台词/余额一套）。
                    self.clicked.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    # -- 素材 ---------------------------------------------------------------
    def set_character(self, character_id: str) -> None:
        who = str(character_id or "shenshen")
        if who == self._character and self._clip is not None:
            return
        self._character = who
        self._start_clip()

    def set_ring(self, color: str) -> None:
        self._ring = QColor(color)
        self.update()

    def _start_clip(self) -> None:
        self._stop_clip()
        clip_dir = _her_idle_clip(self._character or "shenshen")
        if clip_dir is None:
            log.debug("小工位：她（%s）没有 idle 帧序列", self._character)
            self.update()
            return
        source = QImage(str(clip_dir / "f_0001.webp"))
        if source.isNull():
            self.update()
            return
        self._box = _alpha_box(source.convertToFormat(QImage.Format.Format_ARGB32))
        try:
            from .frameseq_clip import FrameSeqClip

            clip = FrameSeqClip(clip_dir, self)
        except Exception:
            log.debug("小工位：帧序列起不来", exc_info=True)
            self.update()
            return
        clip.frameChanged.connect(self._on_frame)
        clip.finished.connect(self._loop_clip)
        clip.errorOccurred.connect(
            lambda message: log.debug("小工位：头像帧序列 %s", message)
        )
        self._clip = clip
        # 只是氛围角色，跟上桌宠本体的 24fps 只是白烧解码：慢到 0.85 倍，呼吸感在。
        speed = getattr(clip, "set_playback_speed", None)
        if callable(speed):
            speed(0.85)
        clip.start()
        self.update()

    def _stop_clip(self) -> None:
        clip, self._clip = self._clip, None
        if clip is None:
            return
        try:
            clip.close()
        except Exception:
            log.debug("小工位：帧序列收口失败", exc_info=True)

    def _on_frame(self, _index: int) -> None:
        self.update()

    def _loop_clip(self) -> None:
        """idle 是一圈一圈播的（链式模型），播完自己续上。"""
        clip = self._clip
        if clip is None:
            return
        clip.jumpToFrame(0)
        clip.start()

    # -- 显隐 ---------------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 口
        super().showEvent(event)
        clip = self._clip
        if clip is not None:
            clip.resume()
        elif self._character and self._box is None:
            self._start_clip()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 口
        clip = self._clip
        if clip is not None:
            clip.pause()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 口
        self._stop_clip()
        super().closeEvent(event)

    # -- 画 -----------------------------------------------------------------
    def _frame_image(self):
        clip = self._clip
        if clip is None:
            return None
        image = clip.currentImage()
        if image is None or image.isNull():
            return None
        return image

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt 口
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        image = self._frame_image()
        if image is None or self._box is None or not self._equipped:
            if not self._equipped:
                self._paint_empty(painter)
            else:
                self._paint_fallback(painter)
            painter.end()
            return
        left, top, width, height = self._box
        if self._mode == "circle":
            side = float(min(width, max(20, int(height * 0.34))))
            source = QRectF(
                left + (width - side) / 2.0,
                top + height * 0.26,
                side,
                side,
            )
            shape = QPainterPath()
            shape.addEllipse(QRectF(0, 0, self.width(), self.height()))
            painter.setClipPath(shape)
            painter.drawImage(QRectF(0, 0, self.width(), self.height()), image, source)
            painter.setClipping(False)
            painter.setPen(QPen(self._ring, 1.4))
            painter.drawEllipse(QRectF(0.7, 0.7, self.width() - 1.4, self.height() - 1.4))
            painter.end()
            return
        # figure：四周留一点，脚下对齐底边，身后一圈微光让立绘不从深色栏里「浮」出来。
        pad_x = width * 0.05
        pad_y = height * 0.04
        source = QRectF(left - pad_x, top - pad_y, width + 2 * pad_x, height + 2 * pad_y)
        avail_w = self.width() - 4
        avail_h = self.height() - 3
        scale = min(avail_w / source.width(), avail_h / source.height())
        draw_w = source.width() * scale
        draw_h = source.height() * scale
        draw_x = (self.width() - draw_w) / 2.0
        draw_y = self.height() - 2 - draw_h
        glow = QRadialGradient(
            self.width() / 2.0, self.height() * 0.52, min(self.width(), self.height()) * 0.68
        )
        tint = QColor(self._ring)
        tint.setAlpha(34)
        glow.setColorAt(0.0, tint)
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(glow))
        # 半径收到控件内：超出边界的渐变收不住，会在她身后留下一圈方形接缝。
        painter.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        shadow = QRadialGradient(
            self.width() / 2.0, self.height() - 1.5, max(12.0, draw_w * 0.42)
        )
        shadow.setColorAt(0.0, QColor(0, 0, 0, 120))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(shadow))
        painter.drawEllipse(
            QRectF(
                self.width() / 2.0 - draw_w * 0.42,
                self.height() - 3.5,
                draw_w * 0.84,
                5.0,
            )
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawImage(QRectF(draw_x, draw_y, draw_w, draw_h), image, source)
        painter.end()

    def _paint_empty(self, painter: QPainter) -> None:
        """空槽：虚线圈 + 她。她就在桌面某处，这一格是把她拖回来的位。"""
        span = float(min(self.width(), self.height()))
        ring = QColor(self._ring)
        ring.setAlpha(96)
        pen = QPen(ring, 1.3, Qt.PenStyle.DashLine)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        inset = 3.0
        if self._mode == "circle":
            painter.drawEllipse(QRectF(inset, inset, span - 2 * inset, span - 2 * inset))
        else:
            painter.drawRoundedRect(
                QRectF(inset, inset, self.width() - 2 * inset, self.height() - 2 * inset),
                9.0,
                9.0,
            )
        font = QFont()
        font.setPixelSize(int(span * 0.36))
        painter.setFont(font)
        faded = QColor(self._ring)
        faded.setAlpha(120)
        painter.setPen(QPen(faded))
        painter.drawText(
            QRectF(0, 0, self.width(), self.height()),
            int(Qt.AlignmentFlag.AlignCenter),
            self._letter[:1],
        )

    def _paint_fallback(self, painter: QPainter) -> None:
        """读不到帧：金圈 + 首字（与静态头像的兜底一致，不留空框）。

        圆圈按格子居中摆：``figure`` 是 62×92 的长格，按 ``(0, 0, span, span)`` 画会
        贴在左上角、下面空掉三分之一，看着像一张跑偏的头像。
        """
        span = float(min(self.width(), self.height()))
        box = QRectF(
            (self.width() - span) / 2.0,
            (self.height() - span) / 2.0,
            span,
            span,
        )
        shape = QPainterPath()
        shape.addEllipse(box)
        fill = QColor(self._ring)
        fill.setAlpha(46)
        painter.fillPath(shape, fill)
        font = QFont()
        font.setPixelSize(int(span * 0.42))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(self._ring))
        painter.drawText(
            box,
            int(Qt.AlignmentFlag.AlignCenter),
            self._letter[:1],
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self._ring, 1.4))
        painter.drawEllipse(box.adjusted(0.7, 0.7, -0.7, -0.7))


def _rail_pixmap(kind: str, color: str, badge: int = 0) -> QPixmap:
    """图标条线稿：24×24 逻辑网格画到 2x 位图，边上带角标。

    **先标 DPR 再画**：上一版在 48×48 设备画布上用 5/19 这种「网格值」当设备像素，
    结果字形只占左上四分之一，图标看着又小又偏左，跟文字对不齐。
    现在整函数都按 24×24 逻辑坐标写，Qt 自己乘 DPR。
    """
    px = QPixmap(48, 48)
    px.fill(Qt.GlobalColor.transparent)
    px.setDevicePixelRatio(2.0)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(color))
    pen.setWidthF(1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if kind == "msg":
        body = QPainterPath()
        body.addRoundedRect(QRectF(2.0, 3.0, 20.0, 14.0), 4.5, 4.5)
        painter.drawPath(body)
        painter.drawLine(QPointF(6.5, 17.0), QPointF(6.5, 20.8))
        painter.drawLine(QPointF(6.5, 20.8), QPointF(10.8, 17.0))
    elif kind == "check":
        painter.drawEllipse(QRectF(2.0, 2.0, 20.0, 20.0))
        path = QPainterPath()
        path.moveTo(7.2, 12.2)
        path.lineTo(10.6, 15.6)
        path.lineTo(16.8, 9.0)
        painter.drawPath(path)
    elif kind == "gear":
        painter.drawEllipse(QRectF(5.0, 5.0, 14.0, 14.0))
        painter.drawEllipse(QRectF(10.7, 10.7, 2.6, 2.6))
        for dx, dy in (
            (1.0, 0.0),
            (0.707, 0.707),
            (0.0, 1.0),
            (-0.707, 0.707),
            (-1.0, 0.0),
            (-0.707, -0.707),
            (0.0, -1.0),
            (0.707, -0.707),
        ):
            painter.drawLine(
                QPointF(12.0 + dx * 7.3, 12.0 + dy * 7.3),
                QPointF(12.0 + dx * 10.0, 12.0 + dy * 10.0),
            )
    elif kind == "close":
        painter.drawLine(QPointF(7.6, 7.6), QPointF(16.4, 16.4))
        painter.drawLine(QPointF(16.4, 7.6), QPointF(7.6, 16.4))
    elif kind == "pencil":
        # 一支斜放的笔：笔身是个平行四边形，笔尖收在左下，右上一条短横是笔帽接缝。
        body = QPainterPath()
        body.moveTo(4.0, 20.0)
        body.lineTo(5.2, 16.2)
        body.lineTo(16.2, 5.2)
        body.lineTo(18.8, 7.8)
        body.lineTo(7.8, 18.8)
        body.closeSubpath()
        painter.drawPath(body)
        painter.drawLine(QPointF(14.6, 6.8), QPointF(17.2, 9.4))
    else:  # grid
        for dx, dy in ((0, 0), (11, 0), (0, 11), (11, 11)):
            painter.drawRoundedRect(QRectF(2.0 + dx, 2.0 + dy, 9.0, 9.0), 2.4, 2.4)
    if badge > 0:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(12.5, 0.0, 10.5, 10.5))
        painter.setPen(QColor("#191203"))
        font = QFont()
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            QRectF(12.5, 0.0, 10.5, 10.5),
            int(Qt.AlignmentFlag.AlignCenter),
            str(min(badge, 99)),
        )
    painter.end()
    return px


def _tile_color(widget, danger: bool = False) -> str:
    """卡片小图标用哪个色：删除固定红，其余跟主题的前景色走。

    卡片挂页面、页面挂窗口，``_colors`` 只有窗口那层有，所以往上找。
    """
    if danger:
        return _CODE_FG["danger"]
    node = widget
    while node is not None:
        colors = getattr(node, "_colors", None)
        if isinstance(colors, dict) and colors.get("fg2"):
            return str(colors["fg2"])
        node = node.parentWidget()
    return "#c9d0dc"


# -- 代码 / 日志着色 -------------------------------------------------------
# 弹窗里的 JSON、连接器日志、技能正文都是「贴进来的一段文本」，之前一律单色。
# 这里按内容自己认类型上色：同一条 tool schema 在 agent 那边是彩的，宠物这边
# 不该是一坨灰。颜色不走主题——这是一套代码色，深浅底下都得能读。

_CODE_FG = {
    "key": "#8ab4f8",
    "string": "#a5d6a7",
    "number": "#f2a56b",
    "keyword": "#c9a0ff",
    "punct": "#7f8796",
    "heading": "#e8a33d",
    "strong": "#eef1f8",
    "code": "#4ec9b0",
    "comment": "#5f6b7d",
    "danger": "#ff7b72",
}


class _JsonHighlighter(QSyntaxHighlighter):
    """JSON：键比字符串亮一档，数字/布尔/标点各有色。

    规则顺序就是优先级：后面的覆盖前面的，所以 ``key`` 必须排在 ``string``
    之后，否则键会被字符串那条盖回普通绿色。
    """

    _RULES = (
        ("string", QRegularExpression(r'"(?:[^"\\]|\\.)*"')),
        ("number", QRegularExpression(r"-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b")),
        ("keyword", QRegularExpression(r"\b(?:true|false|null)\b")),
        ("punct", QRegularExpression(r"[{}\[\],:]")),
        ("key", QRegularExpression(r'"(?:[^"\\]|\\.)*"(?=\s*:)')),
    )

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        for key, pattern in self._RULES:
            match = pattern.globalMatch(text)
            while match.hasNext():
                hit = match.next()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(_CODE_FG[key]))
                if key == "key":
                    fmt.setFontWeight(QFont.Weight.DemiBold)
                self.setFormat(hit.capturedStart(), hit.capturedLength(), fmt)


class _LogHighlighter(QSyntaxHighlighter):
    """日志：``[mcp]`` / ``[tools]`` / ``[err]`` 标签上色，出错那一行整行标红。"""

    _TAGS = {"err": "danger", "warn": "heading", "mcp": "key", "tools": "code"}
    _HEAD = QRegularExpression(r"^\s*\[([a-z_]+)\]")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        hit = self._HEAD.match(text)
        if not hit.hasMatch():
            return
        tag = hit.captured(1)
        color = _CODE_FG.get(self._TAGS.get(tag, ""), "")
        if not color:
            return
        if self._TAGS.get(tag) == "danger":
            whole = QTextCharFormat()
            whole.setForeground(QColor(color))
            self.setFormat(0, len(text), whole)
        tag_fmt = QTextCharFormat()
        tag_fmt.setForeground(QColor(color))
        tag_fmt.setFontWeight(QFont.Weight.DemiBold)
        self.setFormat(hit.capturedStart(), hit.capturedLength(), tag_fmt)


class _MarkdownHighlighter(QSyntaxHighlighter):
    """Markdown：标题、列表标记、围栏代码、行内代码与加粗，够看就行。"""

    _FENCE = QRegularExpression(r"^\s*```")
    _HEADING = QRegularExpression(r"^\s{0,3}#{1,6}\s.*$")
    _BULLET = QRegularExpression(r"^\s{0,3}(?:[-*+]|\d+\.)\s")
    _CODE = QRegularExpression(r"`[^`\n]+`")
    _STRONG = QRegularExpression(r"\*\*[^*\n]+\*\*")

    def highlightBlock(self, text: str) -> None:  # noqa: N802 - Qt 命名
        inside = self.previousBlockState() == 1
        if self._FENCE.match(text).hasMatch():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_CODE_FG["comment"]))
            self.setFormat(0, len(text), fmt)
            self.setCurrentBlockState(0 if inside else 1)
            return
        if inside:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_CODE_FG["code"]))
            self.setFormat(0, len(text), fmt)
            self.setCurrentBlockState(1)
            return
        self.setCurrentBlockState(0)
        if self._HEADING.match(text).hasMatch():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_CODE_FG["heading"]))
            fmt.setFontWeight(QFont.Weight.DemiBold)
            self.setFormat(0, len(text), fmt)
            return
        bullet = self._BULLET.match(text)
        if bullet.hasMatch():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(_CODE_FG["heading"]))
            self.setFormat(bullet.capturedStart(), bullet.capturedLength(), fmt)
        for pattern, key, bold in (
            (self._CODE, "code", False),
            (self._STRONG, "strong", True),
        ):
            match = pattern.globalMatch(text)
            while match.hasNext():
                hit = match.next()
                fmt = QTextCharFormat()
                fmt.setForeground(QColor(_CODE_FG[key]))
                if bold:
                    fmt.setFontWeight(QFont.Weight.DemiBold)
                self.setFormat(hit.capturedStart(), hit.capturedLength(), fmt)


_HIGHLIGHTERS = {
    "json": _JsonHighlighter,
    "log": _LogHighlighter,
    "markdown": _MarkdownHighlighter,
}


def _text_kind(text: str) -> str:
    """这一段文本该按什么着色：能解析的就是 JSON，带 ``[tag]`` 行的是日志。"""
    body = str(text or "").strip()
    if not body:
        return "plain"
    if body[0] in "{[":
        try:
            json.loads(body)
        except ValueError:
            pass
        else:
            return "json"
    if re.search(r"^\s*\[(?:err|warn|mcp|tools|run)\]\s", body, re.M):
        return "log"
    return "markdown"


def _style_text(edit: QPlainTextEdit, kind: str = "auto") -> None:
    """给文本框换上等宽字体并着色；``auto`` 时按内容自己认类型。"""
    font = QFont(edit.font())
    font.setFamilies(["Consolas", "Menlo", "Courier New", "monospace"])
    edit.setFont(font)
    if kind == "auto":
        kind = _text_kind(edit.toPlainText())
    factory = _HIGHLIGHTERS.get(kind)
    if factory is None:
        return
    # 高亮器得挂在 edit 上：Qt 只认 C++ 侧父子关系，Python 这侧没人持有就会被回收，
    # 文字跟着退回单色。
    edit._syntax = factory(edit.document())


def _markdown_panel(
    text: str, parent: QWidget | None = None, object_name: str = "CapMd"
) -> QTextBrowser:
    """只读 Markdown 正文（技能 / 规则 / 专家说明）——真的排版，不是源码视图。

    以前这几个弹框直接把 ``SKILL.md`` 原文塞进 QPlainTextEdit：标题留着 ``#``、
    清单留着 ``- [ ]``、强调留着 ``**``，一页技能读下来像在看 diff（用户反馈原话：
    「格式都没处理」）。这里走聊天那套 ``markdown_to_html``，样式交给 QSS 的
    ``QTextBrowser#CapMd`` / ``#PackMd``。

    ``roleplay=False``：聊天里整段被（）包住的是动作/语气（斜体弱化），文档里的
    括号是正经注记，不能跟着变斜体。
    """
    view = QTextBrowser(parent)
    view.setObjectName(object_name)
    view.setFrameShape(QFrame.NoFrame)
    view.setOpenExternalLinks(True)
    view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    view.setHtml(markdown_to_html(str(text or ""), roleplay=False))
    return view


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[:limit].rstrip() + "…"


def _clip_keep(text: str, limit: int) -> str:
    """正文保留换行（对话流里缩进/段落是信息），只在末尾截断。"""
    body = str(text or "").strip()
    return body if len(body) <= limit else body[:limit].rstrip() + "\n…"


#: 对话流里附件卡的尺寸 = 输入框里那张卡（下面 _AttachCard.W/H）：
#: 聊天框里什么样，发出去就什么样，两边不能各画一套。
FLOW_THUMB_W = 100
FLOW_THUMB_H = 60
#: 缩略图缓存目录名（在系统临时目录下；同一张原图只转一次）。
_FLOW_THUMB_DIR = "dsh-pet-flow-thumbs"
#: 缩略图版本：换了卡片画法就抬一版，否则旧缓存里的旧样式会一直上身。
_FLOW_THUMB_VERSION = "widget-3"


def _flow_thumb(source: str | Path) -> Path | None:
    """对话流里的图片卡：直接抓 _AttachCard 本人，转不出来（文件没了）返回 None。

    缓存键带上原图的改动时间与大小：用户重新截一张同名图不会看到旧缩略图。
    """
    made = _flow_card(source)
    return None if made is None else made[0]


def _flow_card(source: str | Path, *, image: bool | None = None) -> tuple[Path, int, int] | None:
    """把附件控件抓成 PNG，返回 ``(图片, 宽, 高)``。

    不自己画：卡片就是输入框里那一张（同圆角、同描边、同裁切），
    用户在聊天框里看到的缩略图和他发出去的是同一份像素。
    """
    path = Path(str(source))
    key_seed = f"{_FLOW_THUMB_VERSION}|{path.resolve() if path.exists() else path.name}"
    try:
        stat = path.stat()
    except OSError:
        stat = None
    if stat is not None:
        key_seed += f"|{stat.st_mtime_ns}|{stat.st_size}"
    key = hashlib.sha1(key_seed.encode("utf-8")).hexdigest()[:20]
    folder = Path(tempfile.gettempdir()) / _FLOW_THUMB_DIR
    # 文件名里带上「逻辑尺寸」：缓存命中时不用再造一个控件就能拿回宽高
    for hit in sorted(folder.glob(f"{key}-*.png")):
        try:
            width, height = (int(n) for n in hit.stem.split("-")[-1].split("x"))
        except ValueError:
            continue
        if QImage(str(hit)).isNull():
            continue
        return hit, width, height

    is_image = image if image is not None else path.suffix.lower() in _IMAGE_SUFFIXES
    widget = _AttachCard(path) if is_image else _AttachChip(path)
    # 控件脱离窗口后拿不到窗口级 QSS，得把同一份主题表自己套上，否则抓出来是白底
    widget.setStyleSheet(_qss(_ACTIVE_COLORS))
    if is_image and widget._pix.isNull():  # noqa: SLF001 - 图坏了就别装卡片
        widget.deleteLater()
        return None
    widget.remove.setVisible(False)  # 聊天里不能点“移除”
    # 用 sizeHint 而不 adjustSize：后者会把无父控件的卡多撑出一段，跟输入框里不一样宽
    widget.resize(widget.sizeHint())
    size = widget.size()
    pixmap = QPixmap(widget.grab())
    widget.deleteLater()
    if pixmap.isNull() or not size.width() or not size.height():
        return None
    # 卡片自己是透明底（在输入框里透的是输入框底色）。直接贴进气泡会透成气泡色，
    # 深色主题的浅色文件名压在橙底上就看不清了——先压一层不透明底再存。
    card_ground = QColor(_html_color(_ACTIVE_COLORS.get("chat", "#14161b"), "#14161b"))
    # 输入框里卡片底下还叠了一层白（rgba(255,255,255,18)），这里补上同样的半格亮，
    # 否则卡片进气泡后比在输入框里黑一截。
    card_ground = card_ground.lighter(118)
    solid = QPixmap(pixmap.size())
    solid.fill(card_ground)
    painter = QPainter(solid)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    pixmap = solid
    out = folder / f"{key}-{size.width()}x{size.height()}.png"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        if not pixmap.save(str(out), "PNG"):
            return None
    except OSError:
        return None
    return out, size.width(), size.height()


_ATTACHMENT_LINE = re.compile(r"^\s*附件\s*[:：]\s*(.*)$")


def _split_attachment_names(text: str) -> tuple[list[str], str]:
    """把正文里的「附件：a.png、b.md」整行摘出来。

    名字交给文件卡上屏，正文不再留一串文件名/路径（老会话落库的就是这种行，
    靠这里一并收干净）。返回 ``(名字列表, 去掉附件行后的正文)``。
    """
    names: list[str] = []
    kept: list[str] = []
    for line in str(text or "").split("\n"):
        matched = _ATTACHMENT_LINE.match(line)
        if not matched:
            kept.append(line)
            continue
        for raw in matched.group(1).split("、"):
            clean = Path(raw.strip().replace("\\", "/")).name
            if clean:
                names.append(clean)
        if kept and not kept[-1].strip():
            kept.pop()  # 连同前面那行空行一起收掉
    return names, "\n".join(kept).strip()


def _has_talk(session) -> bool:
    """这条会话里有没有真说过话（自动建的空壳不算）。"""
    return any(
        _message_role(message) in ("user", "assistant") and _message_text(message).strip()
        for message in list(getattr(session, "messages", None) or [])
    )


def _session_title(session) -> str:
    """会话名就用「在聊哪件事」：第一条用户原话，不是文件名/编号。"""
    for message in list(getattr(session, "messages", None) or []):
        if _message_role(message) == "user":
            head = _message_text(message).strip().splitlines()
            if head and head[0].strip():
                return _clip(head[0], 16)
    return "新会话"


def _session_snippet(session) -> str:
    """会话列表那一行的摘要：取最后一句，附件行不算话（名字由卡片上屏）。"""
    for message in reversed(list(getattr(session, "messages", None) or [])):
        if _message_role(message) in ("user", "assistant"):
            text = _clip(_split_attachment_names(_message_text(message))[1], 26)
            if text:
                return text
    return "还没说话"


def _message_field(message, key: str) -> str:
    """消息既可能是 ``ChatMessage`` 对象，也可能是 dict（旧存档 / 测试桩）。"""
    raw = message.get(key) if isinstance(message, dict) else getattr(message, key, "")
    return "" if raw is None else str(raw)


def _message_role(message) -> str:
    return _message_field(message, "role")


def _message_text(message) -> str:
    """正文可能是字符串，也可能是多段内容（``[{"type": "text", ...}]``）。"""
    raw = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(raw, str):
        return raw
    parts = []
    for part in raw or []:
        if isinstance(part, dict):
            parts.append(str(part.get("text") or part.get("content") or ""))
        elif isinstance(part, str):
            parts.append(part)
        else:
            parts.append(str(getattr(part, "text", "") or ""))
    return "\n".join(text for text in parts if text)


def _last_user_attachment_paths(owner) -> tuple[str, ...]:
    """主人刚发的那一句带上了哪些附件（发送方已经把临时件换成会话目录里的那份）。

    扫描从尾部开始：发完立刻调用时，最后一条 user 消息就是这一句。
    """
    messages = list(getattr(getattr(owner, "session", None), "messages", None) or [])
    for message in reversed(messages):
        if _message_role(message) != "user":
            continue
        raw = (
            message.get("attachments")
            if isinstance(message, dict)
            else getattr(message, "attachments", None)
        )
        return tuple(str(path) for path in (raw or ()) if str(path).strip())
    return ()


def _session_stamp(session) -> str:
    """行尾时间：今天写时:分，更早写月/日（跟参考的会话列表一个口径）。"""
    raw = getattr(session, "updated_at", None)
    if raw is None:
        return ""
    if isinstance(raw, str):
        text = raw.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text[:16]
        # 存档写的是 UTC，列表按本地时间显示，否则刚发的会话会显示成八小时前。
        stamp = parsed.astimezone() if parsed.tzinfo is not None else parsed
    else:
        try:
            stamp = datetime.fromtimestamp(float(raw))
        except (TypeError, ValueError, OSError, OverflowError):
            return str(raw)[:16]
    today = datetime.now()
    if stamp.date() == today.date():
        return stamp.strftime("%H:%M")
    if stamp.year == today.year:
        return stamp.strftime("%m/%d")
    return stamp.strftime("%y/%m/%d")


class _SessionDelegate(QStyledItemDelegate):
    """会话行自绘：标题 14 / 摘要 11.5 / 行尾时间——一行文本只能一个字号，
    用 ``\\n`` 硬换行两行同大小时看不出哪行是标题（上一版就栽在这）。"""

    ROW_H = 62

    def __init__(self, page) -> None:
        super().__init__()   # 不给 parent：delegate 由 setItemDelegate 接管，不靠父对象活
        self._page = page

    def sizeHint(self, option, index):
        return QSize(0, self.ROW_H)

    def paint(self, painter, option, index):
        colors = self._page._win._colors
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(8, 3, -8, -3)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            plate = QPainterPath()
            plate.addRoundedRect(rect, 9, 9)
            painter.fillPath(plate, _veil(22 if selected else 10, colors))
        if selected:
            bar = QPainterPath()
            bar.addRoundedRect(QRectF(rect.left() + 1.5, rect.top() + 9, 3,
                                      rect.height() - 18), 1.5, 1.5)
            painter.fillPath(bar, QColor(colors["acc"]))
        left = rect.left() + 13
        width = rect.width() - 26
        title = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        snippet = str(index.data(Qt.ItemDataRole.UserRole + 1) or "")
        stamp = str(index.data(Qt.ItemDataRole.UserRole + 2) or "")
        font = QFont(painter.font())
        font.setPixelSize(14)
        font.setBold(selected)
        painter.setFont(font)
        painter.setPen(QColor(colors["fg"] if selected else colors["fg2"]))
        painter.drawText(QRectF(left, rect.top() + 8, width - 56, 19),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                         _clip(title, 18))
        if stamp:
            font.setPixelSize(10)
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(_rgba(colors["dim2"]))
            painter.drawText(QRectF(left + width - 52, rect.top() + 9, 52, 17),
                             int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                             stamp)
            painter.setPen(QColor(colors["fg"] if selected else colors["fg2"]))
        font.setPixelSize(11.5)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(_rgba(colors["dim"]))
        # 只有一句话的会话，摘要会和标题一模一样——重复两遍反而像画错了。
        if snippet.strip() and snippet.strip() != title.strip():
            painter.drawText(QRectF(left, rect.top() + 31, width, 18),
                             int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                             _clip(snippet, 24))
        painter.restore()


def _workspace_name(workspace: str) -> str:
    """工位署名：只写末级目录名，长路径在审批行里放不下。"""
    name = str(workspace or "").replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    return name or "本地工位"


def _html_color(value: str, over: str | None = None) -> str:
    """主题里的 rgba() 富文本不认：按底色混一次，压成 #rrggbb。"""

    def parts(text: str):
        raw_text = str(text or "").strip()
        hex_match = re.fullmatch(r"#([0-9a-fA-F]{6})", raw_text)
        if hex_match:
            value = int(hex_match.group(1), 16)
            return (
                float((value >> 16) & 0xFF),
                float((value >> 8) & 0xFF),
                float(value & 0xFF),
                1.0,
            )
        match = re.match(
            r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)",
            raw_text,
        )
        if not match:
            return None
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        if alpha > 1:
            alpha /= 255.0
        return (
            float(match.group(1)),
            float(match.group(2)),
            float(match.group(3)),
            alpha,
        )

    rgb = parts(value)
    if rgb is None:
        return value
    red, green, blue, alpha = rgb
    base = parts(over) if over else None
    if base is None:
        return f"#{int(red):02x}{int(green):02x}{int(blue):02x}"
    return "#%02x%02x%02x" % (
        round(red * alpha + base[0] * (1 - alpha)),
        round(green * alpha + base[1] * (1 - alpha)),
        round(blue * alpha + base[2] * (1 - alpha)),
    )


def _kind_map() -> dict[str, str]:
    """扩展名 → 类型：照 agent 那边的 ``file-kind.ts`` 抄一份，两处徽标同源。"""
    table: dict[str, str] = {}
    for kind, exts in (
        ("sheet", "xlsx xls xlsm csv tsv ods"),
        ("doc", "doc docx odt rtf pages"),
        ("pdf", "pdf"),
        ("archive", "zip rar 7z tar gz tgz bz2 xz"),
        ("markdown", "md mdx markdown"),
        ("text", "txt text log"),
        ("data", "json jsonc yaml yml toml xml ini parquet"),
        ("image", "png jpg jpeg gif webp bmp svg"),
    ):
        for ext in exts.split():
            table[ext] = kind
    return table


_KIND_BY_EXT = _kind_map()
_CODE_EXTS = frozenset(
    "ts tsx js jsx mjs cjs py rs go java kt kts c h cc cpp hpp cs rb php swift sh bash "
    "zsh ps1 bat cmd html htm css scss less vue svelte lua r jl dart sql proto gradle".split()
)
_KIND_TINT = {
    "sheet": "#2f9e63",
    "doc": "#3b82c4",
    "pdf": "#d9534f",
    "archive": "#c99a2e",
    "markdown": "#5b8def",
    "text": "#8a8f98",
    "code": "#1aa3a3",
    "data": "#8b5cf6",
    "image": "#a855f7",
    "file": "#8a8f98",
}


def _file_ext(path: Path) -> str:
    name = path.name
    dot = name.rfind(".")
    return name[dot + 1 :].lower() if dot > 0 else ""


def _file_kind(path: Path) -> str:
    ext = _file_ext(path)
    if not ext:
        return "file"
    return _KIND_BY_EXT.get(ext) or ("code" if ext in _CODE_EXTS else "file")


def _file_badge(path: Path) -> str:
    """徽标文字：扩展名大写（最长 4 字），无扩展名退回文件名。"""
    ext = _file_ext(path)
    if ext:
        return ext.upper()[:4]
    name = path.name
    if name.startswith(".") and len(name) > 1:
        return name[1:5].upper()
    return "FILE"


def _tint_rgba(tint: str, alpha: int) -> str:
    color = QColor(tint)
    return f"rgba({color.red()},{color.green()},{color.blue()},{alpha})"


def _open_local(path: Path) -> None:
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def _is_image_path(path: Path) -> bool:
    """能不能当缩略图画：先问 mime，再退回扩展名表（tif/heic 这类 mime 才认得出）。"""
    if (mimetypes.guess_type(path.name)[0] or "").startswith("image/"):
        return True
    return _file_kind(path) == "image"


class _ImagePreview(QLabel):
    """对话流里悬停图片时贴边显示的大图。

    无边框浮层（``ToolTip`` 窗型：不抢焦点、不进任务栏），鼠标穿透：
    它与光标只隔十几像素，一旦拦住鼠标就会自己触发 Leave→隐藏→又进入的闪烁。
    """

    MAX_W = 760
    MAX_H = 600
    #: 浮层与鼠标的间距（px）。
    GAP = 18

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            "QLabel{background:rgba(18,20,26,238);border:1px solid rgba(255,255,255,48);"
            "border-radius:10px;padding:6px;}"
        )
        self._source = ""

    def show_for(self, source: str, anchor: QPoint) -> None:
        """在 ``anchor``（全局坐标）旁边显示 ``source`` 的大图。"""
        if source != self._source:
            pixmap = QPixmap(source)
            if pixmap.isNull():
                self.hide()
                return
            max_w, max_h = self.MAX_W, self.MAX_H
            screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
            if screen is not None:
                avail = screen.availableGeometry()
                max_w = min(max_w, max(240, int(avail.width() * 0.7)))
                max_h = min(max_h, max(200, int(avail.height() * 0.7)))
            if pixmap.width() > max_w or pixmap.height() > max_h:
                pixmap = pixmap.scaled(
                    max_w,
                    max_h,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            self.setPixmap(pixmap)
            self._source = source
        self.move(self._placement(anchor))
        self.show()
        self.raise_()

    def _placement(self, anchor: QPoint) -> QPoint:
        """默认放光标右侧；右边放不下就翻到左边，上下夹在屏幕里。"""
        size = self.sizeHint()
        screen = QGuiApplication.screenAt(anchor) or QGuiApplication.primaryScreen()
        avail = (
            screen.availableGeometry()
            if screen is not None
            else QRect(anchor, size)
        )
        x = anchor.x() + self.GAP
        if x + size.width() > avail.right():
            x = anchor.x() - self.GAP - size.width()
        y = max(avail.top(), min(anchor.y() - size.height() // 2, avail.bottom() - size.height()))
        return QPoint(max(avail.left(), x), y)


class _AttachCard(QFrame):
    """图片附件：100×60 封面裁切缩略图 + 右上角移除钮，点图开原图。

    形制照 agent 输入区的 ``InlineImageCard``（同 100×60、同圆角），
    不再是一个写着文件名的文字胶囊。
    """

    W = 100
    H = 60

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self._pix = QPixmap(str(path))
        self._hover = False
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(path))

        self.remove = QToolButton(self)
        self.remove.setObjectName("AttRemove")
        self.remove.setText("✕")
        self.remove.setFixedSize(18, 18)
        self.remove.move(self.W - 22, 4)
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("移除这个附件")
        self.remove.raise_()

    def enterEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            _open_local(self._path)
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape = QPainterPath()
        shape.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.setClipPath(shape)
        if self._pix.isNull():
            painter.fillPath(shape, _veil(14))
        else:
            scaled = self._pix.scaled(
                QSize(self.W, self.H),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            # 等比铺满再居中裁掉溢出的一边，跟 CSS 的 object-fit:cover 一个意思
            painter.drawPixmap(
                QPoint(0, 0),
                scaled.copy(
                    max(0, (scaled.width() - self.W) // 2),
                    max(0, (scaled.height() - self.H) // 2),
                    self.W,
                    self.H,
                ),
            )
        painter.setClipping(False)
        painter.setPen(QPen(_veil(95 if self._hover else 40), 1))
        painter.drawPath(shape)


class _AttachChip(QFrame):
    """非图片附件：类型徽标 + 文件名 + 移除，形制照 ``composer-attach-chip``。"""

    H = 30

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._path = path
        self.setObjectName("AttFile")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFixedHeight(self.H)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(str(path))

        tint = _KIND_TINT.get(_file_kind(path), _KIND_TINT["file"])
        row = QHBoxLayout(self)
        row.setContentsMargins(3, 3, 4, 3)
        row.setSpacing(6)

        badge = QLabel(_file_badge(path), self)
        badge.setObjectName("AttKind")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(26, 22)
        badge.setStyleSheet(
            f"QLabel#AttKind{{background:{_tint_rgba(tint, 40)};color:{tint};"
            "border-radius:5px;font-size:9.5px;font-weight:700;}"
        )
        name = QLabel(
            self.fontMetrics().elidedText(path.name, Qt.TextElideMode.ElideMiddle, 150), self
        )
        name.setObjectName("AttName")

        self.remove = QToolButton(self)
        self.remove.setObjectName("AttRemoveFlat")
        self.remove.setText("✕")
        self.remove.setFixedSize(16, 16)
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.setToolTip("移除这个附件")

        row.addWidget(badge)
        row.addWidget(name, 1)
        row.addWidget(self.remove)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            _open_local(self._path)
        super().mouseReleaseEvent(event)


class _AttachmentFlow(QWidget):
    """附件一行摆满就换行：卡片宽度是定的，直接算坐标比套 QLayout 省事。"""

    GAP = 6

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cards: list[QWidget] = []
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def clear(self) -> None:
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards = []
        self._relayout()

    def add(self, card: QWidget) -> None:
        card.setParent(self)
        card.show()
        self._cards.append(card)
        # 还没上屏的控件 sizeHint 是无效值，先摆一次让它自己算出尺寸
        card.adjustSize()
        self._relayout()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        available = max(self.width(), 1)
        x = y = row_h = 0
        for card in self._cards:
            width, height = card.width(), card.height()
            if width <= 1 or height <= 1:
                hint = card.sizeHint()
                width, height = max(hint.width(), 1), max(hint.height(), 1)
            if x and x + width > available:
                x = 0
                y += row_h + self.GAP
                row_h = 0
            card.setGeometry(x, y, width, height)
            x += width + self.GAP
            row_h = max(row_h, height)
        total = (y + row_h) if self._cards else 0
        if self.minimumHeight() != total:
            self.setFixedHeight(total)


class _WorkstationComposer(QFrame):
    #: 输入框就是个矮条：初始一行半，写到这个高度为止，再长就内部滚。
    EDIT_MIN = 32
    EDIT_MAX = 96
    """工位输入区：多行文本 + 附件，粘贴图片、拖文件、选文件都收。

    附件那套直接借普通聊天窗的 ``AttachmentTextEdit``（粘贴优先取图、拖内存图落盘、
    拖本地文件），工位不再是一根单行 QLineEdit。agent 那排选项按钮这里不摆。
    """

    submitted = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WsComposer")
        self.attachment_paths: list[Path] = []
        self._ime_composing = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # 附件卡在输入框里面（框顶一行），不是框外面另起一排。
        self.box = QFrame(self)
        self.box.setObjectName("WsInputBox")
        box = QVBoxLayout(self.box)
        box.setContentsMargins(9, 7, 7, 5)
        box.setSpacing(4)

        self.chips = _AttachmentFlow(self.box)
        self.chips.setVisible(False)
        box.addWidget(self.chips)

        self.edit = AttachmentTextEdit(self.box)
        self.edit.setObjectName("WsInput")
        self.edit.setPlaceholderText(
            "跟她说点什么…"
        )
        self.edit.setFixedHeight(self.EDIT_MIN)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.document().documentLayout().documentSizeChanged.connect(self._fit_edit_height)
        self.edit.textChanged.connect(self._fit_edit_height)
        self.edit.files_dropped.connect(self.add_attachments)
        self.edit.installEventFilter(self)

        self.send = QPushButton("↑", self.box)
        self.send.setObjectName("Send")
        self.send.setFixedSize(26, 26)
        self.send.setToolTip("发给她（Enter）")
        self.send.clicked.connect(self._submit)

        # 输入框底部一行：发送靠右，两个都在框里。
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        row.addStretch(1)
        row.addWidget(self.send, 0, Qt.AlignmentFlag.AlignRight)

        box.addWidget(self.edit)
        box.addLayout(row)
        root.addWidget(self.box)

    def _fit_edit_height(self, *_args) -> None:
        """输入框默认就是一个矮条，写多了才长高，到上限开始内部滚。"""
        lines = self.edit.blockCount()
        wanted = lines * self.edit.fontMetrics().lineSpacing() + 12
        height = max(self.EDIT_MIN, min(self.EDIT_MAX, wanted))
        if height != self.edit.height():
            self.edit.setFixedHeight(height)

    def _submit(self, *_args) -> None:
        self.submitted.emit()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 - Qt 命名
        if obj is self.edit:
            kind = event.type()
            if kind == QEvent.Type.InputMethod:
                # 组合中回车是上屏候选，不是发送
                self._ime_composing = bool(event.preeditString())
                if event.commitString():
                    self._ime_composing = False
            elif kind == QEvent.Type.KeyPress:
                enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
                if enter and not shift and not self._ime_composing:
                    self._submit()
                    return True
        return super().eventFilter(obj, event)

    def add_attachments(self, paths) -> None:
        accepted, warnings = validate_attachment_additions(
            self.attachment_paths, [Path(str(path)) for path in paths]
        )
        self.attachment_paths.extend(accepted)
        self._sync_chips()
        if warnings:
            QToolTip.showText(
                self.edit.mapToGlobal(self.edit.rect().topLeft()), "\n".join(warnings)
            )

    def remove_attachment(self, path: Path) -> None:
        self.attachment_paths = [item for item in self.attachment_paths if item != path]
        _discard_clipboard_cache(path)
        self._sync_chips()

    def clear(self, discard: bool = True) -> None:
        """清空输入区。``discard=False`` 留给发送方收：粘贴图得先落进会话目录再删。"""
        self.edit.clear()
        if discard:
            for path in self.attachment_paths:
                _discard_clipboard_cache(path)
        self.attachment_paths = []
        self._sync_chips()

    def set_text(self, text: str) -> None:
        self.edit.setPlainText(text)
        self.edit.moveCursor(QTextCursor.MoveOperation.End)

    def _sync_chips(self) -> None:
        self.chips.clear()
        for path in self.attachment_paths:
            card = (
                _AttachCard(path, self.chips)
                if _is_image_path(path)
                else _AttachChip(path, self.chips)
            )
            card.remove.clicked.connect(
                lambda _=False, target=path: self.remove_attachment(target)
            )
            self.chips.add(card)
        self.chips.setVisible(bool(self.attachment_paths))

    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def payload(self) -> dict | None:
        """没有附件时 None；有就带上名单、正文提示和图片负载。"""
        if not self.attachment_paths:
            return None
        return {
            "names": [path.name for path in self.attachment_paths],
            "prompt": self._attachment_prompt(),
            "images": self._image_payloads(),
            # 图片**路径**也交出去：images 里只有 base64，落库之后反解不出
            # 一个能打开的本地文件，小工位就没法把附件画成缩略图。
            "image_paths": [str(path) for path in self._image_files()],
            # 全部附件路径：图走缩略图，其余走文件卡；聊天记录不再只留一行文件名。
            "paths": [str(path) for path in self.attachment_paths],
        }

    def _image_files(self) -> list[Path]:
        """能当图片发出去的附件（负载与上屏缩略图共用这一份判据）。"""
        files: list[Path] = []
        for path in self.attachment_paths:
            mime = mimetypes.guess_type(path.name)[0] or ""
            if not mime.startswith("image/"):
                continue
            try:
                if path.stat().st_size > MAX_IMAGE_BYTES:
                    continue
            except OSError:
                continue
            files.append(path)
        return files

    def _attachment_prompt(self) -> str:
        blocks: list[str] = []
        budget = MAX_TEXT_TOTAL_CHARS
        for path in self.attachment_paths:
            mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            header = f"附件：{path.name}（{mime}）"
            if budget > 0 and _attachment_is_text(path):
                try:
                    content = path.read_text(encoding="utf-8", errors="replace")[:budget]
                except OSError:
                    content = "[读不出来]"
                budget = max(0, budget - len(content))
                blocks.append(f"{header}\n{content}")
            else:
                blocks.append(header)
        return "\n\n".join(blocks)

    def _image_payloads(self) -> list[dict]:
        payloads: list[dict] = []
        for path in self._image_files():
            mime = mimetypes.guess_type(path.name)[0] or ""
            try:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            except OSError:
                continue
            payloads.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}}
            )
        return payloads


class MessagesPage(QWidget):
    """会话列表 + 对话流 + 输入框。左栏只装自己的工位。"""

    MAX_SESSIONS = 40
    MAX_FLOW = 30

    def __init__(self, win) -> None:
        super().__init__(win)
        self._win = win
        self._owner = win.owner
        self._session_id = ""
        self._doc_messages: list[tuple[str, bool, tuple[str, ...]]] = []
        #: 缩略图 URL → 原图路径：文档里写的是缩略图，hover 要的是原图。
        self._shot_sources: dict[str, str] = {}
        self._shot_images: set[str] = set()
        self._shot_images: set[str] = set()
        self._preview = _ImagePreview()
        self._build()
        self.bind_service()

    def bind_service(self) -> None:
        """回答是在气泡那边接的：完事/报错时回来重画一遍，别让三栏窗停在旧状态。"""
        for holder in (getattr(self._owner, "service", None),
                       getattr(self._owner, "laji_service", None)):
            if holder is None:
                continue
            for name in ("finished", "error"):
                signal = getattr(holder, name, None)
                connect = getattr(signal, "connect", None)
                if not callable(connect):
                    continue
                try:
                    connect(self._on_turn_done)
                except Exception:
                    log.debug("小工位：接服务信号失败（%s）", name, exc_info=True)

    def _on_turn_done(self, *_args) -> None:
        QTimer.singleShot(0, self.refresh_flow_from_owner)

    def refresh_flow_from_owner(self) -> None:
        """气泡那边已经把新消息写进 ``owner.session``，重画就能看到。"""
        self.render_flow(getattr(self._owner, "session", None))

    def _build(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QWidget(self)
        side.setObjectName("wsList")
        side.setFixedWidth(LIST_W)
        left = QVBoxLayout(side)
        left.setContentsMargins(9, 10, 9, 8)
        left.setSpacing(6)
        search_row = QHBoxLayout()
        search_row.setSpacing(6)
        self.search = QLineEdit(side)
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索会话")
        self.search.setReadOnly(True)
        plus = QPushButton("＋", side)
        plus.setObjectName("Plus")
        plus.setFixedSize(26, 24)
        plus.setToolTip("开一件新事（交给她）")
        plus.clicked.connect(lambda: self._win.bench_action("new_session"))
        search_row.addWidget(self.search, 1)
        search_row.addWidget(plus)
        left.addLayout(search_row)

        self.sessions = QListWidget(side)
        self.sessions.setObjectName("Sessions")
        self.sessions.setFrameShape(QFrame.Shape.NoFrame)
        self.sessions.itemClicked.connect(self._on_picked)
        self.sessions.setMouseTracking(True)   # 悬停态由 delegate 自己画
        self.sessions.setUniformItemSizes(True)
        # setItemDelegate 不接管所有权，不留引用就会被 GC 掉（视图随即崩溃）。
        self._session_delegate = _SessionDelegate(self)
        self.sessions.setItemDelegate(self._session_delegate)
        left.addWidget(self.sessions, 1)
        self.empty_hint = QLabel("还没聊过 —— 在下面说第一句", side)
        self.empty_hint.setObjectName("PageSub")
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setVisible(False)
        left.addWidget(self.empty_hint)
        outer.addWidget(side)

        chat = QWidget(self)
        chat.setObjectName("wsChat")
        column = QVBoxLayout(chat)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        head = QWidget(chat)
        self.head = head  # 空标题栏就是窗口的拖手
        head_row = QVBoxLayout(head)
        head_row.setContentsMargins(16, 10, 16, 9)
        head_row.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel("—", head)
        self.title.setObjectName("Title")
        dot = QLabel("●", head)
        dot.setObjectName("Dot")
        tag = QLabel("自己的工位", head)
        tag.setObjectName("WsTag")
        top.addWidget(dot)
        top.addSpacing(4)
        top.addWidget(self.title)
        top.addSpacing(8)
        top.addWidget(tag)
        top.addStretch(1)
        head_row.addLayout(top)
        self.subtitle = QLabel("她在旁边待命", head)
        self.subtitle.setObjectName("Sub")
        head_row.addWidget(self.subtitle)
        column.addWidget(head)

        # 对话流是一整篇只读文档：跨气泡拖选、Ctrl+A、Ctrl+C、右键复制全交给 Qt，
        # 不再是「一个气泡一个 QLabel」那种选不起来也复制不了的控件树。
        self.view = QTextBrowser(chat)
        self.view.setObjectName("FlowView")
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setOpenExternalLinks(True)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # 视口默认拿调色板 Base 色（浅色系统下就是纯白），不显式关掉会盖出一块白底。
        self.view.viewport().setAutoFillBackground(False)
        # 悬停看大图：鼠标停在文档里的缩略图上，旁边浮一张原图。
        self.view.viewport().setMouseTracking(True)
        self.view.viewport().installEventFilter(self)
        column.addWidget(self.view, 1)

        bottom = QWidget(chat)
        bottom_row = QVBoxLayout(bottom)
        bottom_row.setContentsMargins(14, 8, 22, 12)
        bottom_row.setSpacing(0)
        self.composer = _WorkstationComposer(bottom)
        self.composer.submitted.connect(self._send)
        bottom_row.addWidget(self.composer)
        column.addWidget(bottom)
        outer.addWidget(chat, 1)

    def refresh_sessions(self) -> None:
        store = getattr(self._owner, "store", None)
        character = str(getattr(self._owner, "character_id", "") or "")
        if store is None or not character:
            return
        try:
            sessions = list(store.list(character) or [])
        except Exception:
            log.debug("小工位：读会话列表失败", exc_info=True)
            return
        owner_session_id = str(
            getattr(getattr(self._owner, "session", None), "session_id", "") or ""
        )
        # 「她手上这条」与「左栏预览这条」必须分开看：新建会话后 owner.session 已是新
        # 会话，而 _session_id 还停在旧那条；用 `or` 合成一个 keep_id 会两头出错——
        # 新空壳被当成没说过话的自动会话过滤掉，自动选中的旧行又把她换回旧会话。
        keep_ids = {sid for sid in (self._session_id, owner_session_id) if sid}
        self.sessions.clear()
        current_row = -1
        preview_row = -1
        for session in sessions[: self.MAX_SESSIONS]:
            session_id = str(getattr(session, "session_id", "") or "")
            if not _has_talk(session) and session_id not in keep_ids:
                # 自动建但一句没说过的空壳不占一格（不然列表里只有一条「新会话」）。
                continue
            item = QListWidgetItem(_session_title(session))
            item.setData(Qt.ItemDataRole.UserRole, session_id)
            item.setData(Qt.ItemDataRole.UserRole + 1, _session_snippet(session))
            item.setData(Qt.ItemDataRole.UserRole + 2, _session_stamp(session))
            self.sessions.addItem(item)
            if session_id == owner_session_id:
                current_row = self.sessions.count() - 1
            if session_id and session_id == self._session_id:
                preview_row = self.sessions.count() - 1
        has_rows = self.sessions.count() > 0
        self.empty_hint.setVisible(not has_rows)
        if current_row < 0:
            current_row = preview_row
        if current_row < 0 and has_rows:
            current_row = 0
        if current_row >= 0:
            target = str(
                self.sessions.item(current_row).data(Qt.ItemDataRole.UserRole) or ""
            )
            self.sessions.setCurrentRow(current_row)
            # 自动选中的那条不是她手上这条时，只当预览，不把她正在聊的会话换掉。
            self._open_row(current_row, switch_owner=(not owner_session_id or target == owner_session_id))

    def focus_session(self, session_id: str) -> None:
        """给「她的会话」页用：按 id 定位到左栏那一行并切过去。"""
        for row in range(self.sessions.count()):
            item = self.sessions.item(row)
            if item is None:
                continue
            if str(item.data(Qt.ItemDataRole.UserRole) or "") == session_id:
                self._open_row(row)
                self.sessions.setCurrentRow(row)
                return

    def _on_picked(self, item: QListWidgetItem) -> None:
        self._open_row(self.sessions.row(item))

    def _open_row(self, row: int, switch_owner: bool = True) -> None:
        item = self.sessions.item(row) if row >= 0 else None
        if item is None:
            return
        session_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        store = getattr(self._owner, "store", None)
        character = str(getattr(self._owner, "character_id", "") or "")
        session = None
        if store is not None and session_id:
            try:
                session = store.load(session_id, character)
            except Exception:
                log.debug("小工位：读会话失败", exc_info=True)
        if session is None:
            return
        self._session_id = session_id
        # 只有「在看这条」才算数：把气泡的当前会话一起切过去，否则输入框里的
        # 字会落进另一条（``_send`` 读的是 ``owner.session``）。
        if switch_owner:
            try:
                self._owner.session = session
            except Exception:
                log.debug("小工位：切会话失败", exc_info=True)
        self.title.setText(_session_title(session))
        self.title.setToolTip(_session_title(session))
        self.subtitle.setText(_session_snippet(session))
        self.render_flow(session)

    def render_flow(self, session=None) -> None:
        if session is None:
            session = getattr(self._owner, "session", None)
        messages = [
            message
            for message in list(getattr(session, "messages", None) or [])
            if _message_role(message) in ("user", "assistant") and _message_text(message).strip()
        ]
        self._doc_messages = [
            (
                _message_text(message),
                _message_role(message) == "user",
                tuple(str(path) for path in (getattr(message, "attachments", None) or [])),
            )
            for message in messages[-self.MAX_FLOW:]
        ]
        self._render_document()

    def _render_document(self) -> None:
        """整段对话进一个只读文档：跨气泡拖选、Ctrl+A、Ctrl+C、右键复制全走 Qt。"""
        colors = self._colors()
        over = _html_color(colors.get("shell", "") or "#101216")
        self._shot_sources.clear()
        self._shot_images.clear()
        if not self._doc_messages:
            self.view.setHtml(
                f'<div style="color:{_html_color(colors["dim2"], over)};font-size:12.5px;">'
                "还没有对话 —— 在下面跟她说第一句</div>"
            )
            return
        self.view.setHtml(
            "".join(
                self._bubble_html(text, mine, colors, images)
                for text, mine, images in self._doc_messages
            )
        )
        QTimer.singleShot(0, self._scroll_to_bottom)

    def _colors(self) -> dict:
        colors = getattr(self._win, "_colors", None)
        if isinstance(colors, dict):
            return colors
        return _theme(str(_LAST_THEME.get("key") or ""))[2]

    def _bubble_html(
        self, text: str, mine: bool, colors: dict, images: tuple[str, ...] = ()
    ) -> str:
        """气泡用表格拼：富文本没有 border-radius，圆角只能退成直边色块。

        附件卡片放在气泡里、文字前面，和输入框里那块是同一张卡——
        发出去只是把它从输入框挪进气泡，不是另画一副样子。
        """
        over = _html_color(colors.get("chat", ""), _html_color(colors.get("shell", "") or "#101216"))
        # 正文里的「附件：a.png、b.md」整行摘掉：名字改由卡片上屏，正文不再留路径行。
        names_in_text, shown = _split_attachment_names(text)
        body = html.escape(_clip_keep(shown, 480)).replace("\n", "<br>")
        cards = self._attach_row_html(images, names_in_text)
        inner = body
        if cards:
            inner = f"{cards}<br>{body}" if body.strip() else cards
        gap = '<div style="font-size:8px;">&#160;</div>'
        if mine:
            ground = _html_color(colors["acc"], over)
            bubble = ""
            if inner.strip():
                bubble = (
                    f'<table cellspacing="0" cellpadding="8" bgcolor="{ground}"><tr>'
                    f'<td style="color:{_html_color(colors["ink"], ground)};font-size:13px;">'
                    f"{inner}</td></tr></table>"
                )
            return (
                '<table width="100%" cellspacing="0" cellpadding="0"><tr><td align="right">'
                f"{bubble}</td></tr></table>" + gap
            )
        return (
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td width="3" bgcolor="{_html_color(colors["accLine"], over)}"></td>'
            f'<td style="color:{_html_color(colors["fg2"], over)};font-size:13px;padding-left:10px;">'
            f"{inner}</td></tr></table>"
            + gap
        )

    def _attach_row_html(self, images, names_in_text: list[str]) -> str:
        """气泡里的附件卡：一张张真控件抓出来的图，说话人那边照样缩在气泡里。"""
        cards: list[str] = []
        seen: set[str] = set()
        for raw in images or ():
            source = str(raw or "")
            label = Path(source.replace("\\", "/")).name
            if not source or not label or label in seen:
                continue
            seen.add(label)
            made = _flow_card(source) or _flow_card(source, image=False)
            if made is None:
                continue
            png, width, height = made
            url = QUrl.fromLocalFile(str(png)).toString()
            if Path(source).suffix.lower() in _IMAGE_SUFFIXES:
                self._shot_images.add(url)  # 悬停才弹大图，文档不弹
            self._shot_sources[url] = source  # 点一下打开原文件
            # 点卡片 = 打开原文件（和输入框里点一下一样）
            href = QUrl.fromLocalFile(source).toString() if Path(source).exists() else ""
            card = (
                f'<img src="{html.escape(url, quote=True)}" '
                f'width="{width}" height="{height}">'
            )
            if href:
                card = f'<a href="{html.escape(href, quote=True)}">{card}</a>'
            cards.append(card + " ")
        # 老会话只存了名字（文件早删了）：也挂一个类型卡，不放路径字符串
        for name in names_in_text:
            if name in seen:
                continue
            seen.add(name)
            made = _flow_card(Path(name), image=False)
            if made is None:
                continue
            png, width, height = made
            url = QUrl.fromLocalFile(str(png)).toString()
            cards.append(
                f'<img src="{html.escape(url, quote=True)}" '
                f'width="{width}" height="{height}"> '
            )
        if not cards:
            return ""
        return "".join(cards)

    def _note(self, text: str, mine: bool = False, images: tuple[str, ...] = ()) -> None:
        """本地先说一句（等回复的空档、或者发送失败）：进文档，不落库。"""
        self._doc_messages.append((text, mine, tuple(images)))
        self._render_document()

    def _scroll_to_bottom(self) -> None:
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def eventFilter(self, watched, event) -> bool:
        """缩略图既能悬停看大图，也能直接点开原文件。"""
        viewport = getattr(getattr(self, "view", None), "viewport", None)
        if watched is viewport:
            if event.type() == QEvent.Type.MouseMove:
                self._hover_image(event.position().toPoint())
            elif (
                event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton
                and self._open_card_at(event.position().toPoint())
            ):
                return True
            elif event.type() in (
                QEvent.Type.Leave,
                QEvent.Type.Wheel,
                QEvent.Type.Hide,
            ):
                self._preview.hide()
        return super().eventFilter(watched, event)

    def _card_source_at(self, point: QPoint) -> str:
        """光标底下那张卡对应的原文件（没有就返回空串）。

        不能直接信 `cursorForPosition(point).charFormat()`：图片只占一个字符，
        点在卡上时光标常常落到它前面或后面的普通字符上。这里反过来，
        拿光标所在段里的每个图片片段自己的横坐标范围跟点比。
        """
        document = self.view.document()
        block = document.findBlock(self.view.cursorForPosition(point).position())
        if not block.isValid():
            return ""
        it = block.begin()
        while not it.atEnd():
            fragment = it.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                fmt = fragment.charFormat()
                start = QTextCursor(document)
                start.setPosition(fragment.position())
                end = QTextCursor(document)
                end.setPosition(fragment.position() + 1)
                left = self.view.cursorRect(start).x()
                right = max(left + 1, self.view.cursorRect(end).x())
                if left <= point.x() <= right:
                    source = self._shot_sources.get(str(fmt.toImageFormat().name() or ""), "")
                    if source:
                        return source
            it += 1
        return ""

    def _open_card_at(self, point: QPoint) -> bool:
        """点卡片就开原文件：图片给看图器放大，文档给系统默认程序。"""
        source = self._card_source_at(point)
        if not source:
            return False
        path = Path(source)
        if not path.exists():
            self._note(f"这个附件不在了：{path.name}")
            return True
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return True

    def _hover_image(self, point: QPoint) -> None:
        """光标压在图片卡上就弹原图；文档卡不弹，点击直接打开。"""
        source = self._card_source_at(point)
        if not source or not self._is_hover_image(source):
            self._preview.hide()
            return
        self._preview.show_for(source, self.view.viewport().mapToGlobal(point))

    def _is_hover_image(self, source: str) -> bool:
        url = QUrl.fromLocalFile(source).toString()
        return url in self._shot_images or Path(source).suffix.lower() in _IMAGE_SUFFIXES

    def hideEvent(self, event) -> None:
        self._preview.hide()
        super().hideEvent(event)

    def _send(self) -> None:
        text = self.composer.text()
        attachments = self.composer.payload()
        if not text and not attachments:
            return
        send = getattr(self._owner, "send_text", None)
        if not callable(send):
            self._note("这条通道没接上，先在气泡里说。")
            return
        # 输入框永远属于「现在显示的那条」：显示的和她手上的不一致时先对齐，
        # 否则字会落进另一条会话，列表里看不到自己刚说的话。
        current = str(getattr(getattr(self._owner, "session", None), "session_id", "") or "")
        if self._session_id and self._session_id != current:
            self._open_row(self.sessions.currentRow())
        names = list((attachments or {}).get("names") or [])
        # 附件路径（图 + 文件）全部上屏：缩略图与文件卡都从这份路径现算，
        # 只交图片路径的话，.md/.txt 这类永远只剩一行文件名。
        attach_paths = tuple(
            str(path)
            for path in (
                (attachments or {}).get("paths")
                or (attachments or {}).get("image_paths")
                or ()
            )
        )
        draft = text
        shown = text or "请查看附件"
        if names:
            shown += "\n\n附件：" + "、".join(names)
        # 先上屏：等回复的那几秒不至于一片静。也必须在清空输入区**之前**画：
        # 粘贴图还在临时目录里，先删就画不出缩略图了。
        self._note(shown, True, attach_paths)
        try:
            accepted = bool(send(text, attachments=attachments))
        except Exception:
            log.exception("小工位：发送失败")
            self._note("发送失败了，再试一次。")
            self._restore_draft(draft)
            return
        if not accepted:
            self._note(
                "这句没发出去：她的聊天通道还没配好（去 AI 设置里填 Key），"
                "或者上一句还没说完。"
            )
            self._restore_draft(draft)
            return
        # 发送方已把粘贴图搬进会话目录（见 persist_chat_attachments）：上屏行改指落库的
        # 那份路径，否则临时件一收，缩略图会先消失一秒再跟着 1200ms 刷新回来。
        stored = _last_user_attachment_paths(self._owner)
        if stored and self._doc_messages and self._doc_messages[-1][1]:
            row_text, row_mine, _old = self._doc_messages[-1]
            self._doc_messages[-1] = (row_text, row_mine, stored)
            self._render_document()
        # 现在才清输入区：``discard=False`` 让发送方收临时件（它已经先搬好了）。
        self.composer.clear(discard=False)
        self.subtitle.setText("等她说…")
        QTimer.singleShot(1200, self.refresh_flow_from_owner)
        QTimer.singleShot(1800, self.refresh_sessions)

    def _restore_draft(self, draft: str) -> None:
        """没发出去的那句原样放回输入框，别让用户重打一遍。"""
        if draft:
            self.composer.set_text(draft)


class ApprovalsPage(QWidget):
    """全部工位的待批汇总。批完回 laji_service，不在本地假装已批。"""

    def __init__(self, win) -> None:
        super().__init__(win)
        self._win = win
        self._build()

    def _build(self) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 13, 20, 12)
        column.setSpacing(8)
        head_box = QWidget(self)
        self.head = head_box
        head = QHBoxLayout(head_box)
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(9)
        title = QLabel("待办", head_box)
        title.setObjectName("PageHead")
        self.count = QLabel("", head_box)
        self.count.setObjectName("PageSub")
        head.addWidget(title)
        head.addWidget(self.count)
        head.addStretch(1)
        column.addWidget(head_box)

        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.body_holder = QWidget(self.scroll)
        self.body = QVBoxLayout(self.body_holder)
        self.body.setContentsMargins(0, 6, 0, 6)
        self.body.setSpacing(8)
        self.body.addStretch(1)
        self.scroll.setWidget(self.body_holder)
        column.addWidget(self.scroll, 1)

    def _clear_body(self) -> None:
        """把内容区清空（含末尾那段伸缩），交给 ``rebuild`` 重新铺。"""
        while self.body.count():
            item = self.body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # deleteLater 要等事件循环，旧卡会先和空态文案叠在一起：
                # 先脱离父控件，这一帧就从屏幕上消失。
                widget.setParent(None)
                widget.deleteLater()

    def rebuild(self) -> None:
        self._clear_body()
        entries = list(getattr(self._win, "approvals", {}).items())
        self.count.setText(f"{len(entries)} 个在等" if entries else "")
        if not entries:
            # 空态是内容区的一句话，不是左上角的一行标签：上下各留一段伸缩，
            # 让它落在中间（holder 高度随 viewport，顶部标题栏照旧）。
            empty = QLabel("暂无数据", self.body_holder)
            empty.setObjectName("PageSub")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.body.addStretch(1)
            self.body.addWidget(empty)
            self.body.addStretch(1)
            return
        for run_id, entry in entries:
            self.body.addWidget(self._row(run_id, entry))
        self.body.addStretch(1)

    def _row(self, run_id: str, entry: dict) -> QWidget:
        approval = entry.get("approval")
        row = QFrame(self.body_holder)
        row.setObjectName("ApRow" if approval is not None else "ApRowQuiet")
        row.setMaximumWidth(ROW_MAX_W)
        box = QVBoxLayout(row)
        box.setContentsMargins(14, 11, 14, 11)
        box.setSpacing(4)

        tool = str(getattr(approval, "tool_name", "") or "") if approval is not None else ""
        reason = str(getattr(approval, "reason", "") or "") if approval is not None else ""

        top = QHBoxLayout()
        top.setSpacing(8)
        ws = QLabel(_workspace_name(str(entry.get("workspace", ""))), row)
        ws.setObjectName("ApWs")
        name = QLabel(approval_headline(tool), row)
        name.setObjectName("ApTitle")
        name.setWordWrap(False)
        top.addWidget(ws)
        top.addWidget(name, 1)
        box.addLayout(top)

        # 英文原文不当正文：换一句中文，原文只留给悬停（见 approval_detail）。
        if approval is not None:
            detail = approval_detail(tool, reason)
        else:
            detail = str(entry.get("message") or "").strip() or "这条还没探到详情"
        cmd = QLabel(row)
        cmd.setObjectName("ApCmd")
        cmd.setWordWrap(False)
        cmd.setText(
            cmd.fontMetrics().elidedText(
                detail, Qt.TextElideMode.ElideRight, ROW_MAX_W - 34
            )
        )
        cmd.setToolTip(f"{tool} · {reason}".strip(" ·") or detail)
        box.addWidget(cmd)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)
        if approval is not None:
            allow = QPushButton("允许", row)
            allow.setObjectName("Allow")
            allow.setFixedWidth(58)
            allow.clicked.connect(lambda _=False, r=run_id: self._win.resolve_approval(r, True))
            deny = QPushButton("拒绝", row)
            deny.setObjectName("Deny")
            deny.setFixedWidth(58)
            deny.clicked.connect(lambda _=False, r=run_id: self._win.resolve_approval(r, False))
            loc = QPushButton("看看是哪条会话 ›", row)
            loc.setObjectName("Ghost")
            loc.clicked.connect(lambda _=False, r=run_id: self._win.locate_run(r))
            actions.addWidget(allow)
            actions.addWidget(deny)
            actions.addWidget(loc)
        box.addLayout(actions)
        return row


class BenchCard(QFrame):
    """工作台入口卡：左边一块色当锚点，右边名称加一行小字。"""

    def __init__(self, glyph: str, ink: str, title: str, desc: str, on_click, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("BenchCard")
        self.setMinimumHeight(62)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._on_click = on_click
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 10, 12, 10)
        row.setSpacing(10)
        badge = QLabel(glyph, self)
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background:{ink}; color:#12141a; border-radius:9px;"
            "font-size:15px; font-weight:700;"
        )
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title_label = QLabel(title, self)
        self.title_label.setObjectName("BenchTitle")
        self.desc_label = QLabel(desc, self)
        self.desc_label.setObjectName("BenchDesc")
        text.addWidget(self.title_label)
        text.addWidget(self.desc_label)
        row.addWidget(badge)
        row.addLayout(text, 1)

    def set_desc(self, text: str) -> None:
        self.desc_label.setText(text)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        inside = self.rect().contains(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and inside:
            self._on_click()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._on_click()
            return
        super().keyPressEvent(event)


class BenchPage(QWidget):
    """工作台：只放入口，不放模式/沙箱开关。"""

    ACTIONS = (
        ("连接器", "能用哪些工具", "connectors", "连", "#4f9dd8"),
        ("技能", "她学会的手艺", "skills", "艺", "#3fb27f"),
        ("创意工坊", "给她的能力包", "workshop", "坊", "#c98a1b"),
    )

    GROUPS = (("", ("connectors", "skills", "workshop")),)

    def __init__(self, win) -> None:
        super().__init__(win)
        self._win = win
        self.cards: dict[str, BenchCard] = {}
        self.pages: dict[str, QWidget] = {}
        self._build()

    def _build(self) -> None:
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.stack = QStackedWidget(self)
        column.addWidget(self.stack)

        home = QWidget(self.stack)
        self.home = home
        inner = QVBoxLayout(home)
        inner.setContentsMargins(20, 13, 20, 14)
        inner.setSpacing(9)
        head_box = QWidget(home)
        self.head = head_box
        head = QHBoxLayout(head_box)
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel("工作台", head_box)
        title.setObjectName("PageHead")
        head.addWidget(title)
        head.addStretch(1)
        inner.addWidget(head_box)

        by_action = {row[2]: row for row in self.ACTIONS}
        for group_name, actions in self.GROUPS:
            if group_name:
                caption = QLabel(group_name, home)
                caption.setObjectName("BenchGroup")
                inner.addWidget(caption)
            grid = QGridLayout()
            grid.setSpacing(10)
            span = 2 if len(actions) == 2 else 1
            for slot, action in enumerate(actions):
                title_text, desc, _, glyph, ink = by_action[action]
                card = BenchCard(
                    glyph,
                    ink,
                    title_text,
                    desc,
                    lambda a=action: self._win.bench_action(a),
                    home,
                )
                grid.addWidget(card, 0, slot * span, 1, span)
                self.cards[action] = card
            inner.addLayout(grid)
        inner.addStretch(1)
        self.stack.addWidget(home)

        # 四页能力放在工作台自己的子栈里：图标条仍然只有三项，不抢 rail。
        for key, page in (
            ("connectors", ConnectorsPage(self)),
            ("skills", SkillsPage(self)),
            ("workshop", WorkshopPage(self)),
            ("sessions", SessionsPage(self)),
        ):
            self.pages[key] = page
            self.stack.addWidget(page)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self.refresh_counts()

    def show_home(self) -> None:
        self.refresh_counts()
        self.stack.setCurrentWidget(self.home)

    def show_page(self, key: str) -> None:
        page = self.pages.get(key)
        if page is None:
            self.show_home()
            return
        page.refresh()
        self.stack.setCurrentWidget(page)

    def refresh_counts(self) -> None:
        """卡片上那几行小字跟着宠物家目录变：装完一个包不用重启。"""
        try:
            counted = pet_toolkit.counts(str(getattr(self._win.owner, "character_id", "") or ""))
        except Exception:
            log.debug("工作台：数不清能力库存", exc_info=True)
            return
        for action, key, label in (
            ("connectors", "connectors", "{n} 个"),
            ("skills", "skills", "{n} 条"),
            # 卡片动作叫 workshop，计数键叫 packs —— 以前拿动作名去查，查不到就
            # 静默写 0，卡片上永远是「0 个包」。
            ("workshop", "packs", "{n} 个包"),
        ):
            card = self.cards.get(action)
            if card is None:
                continue
            count = int(counted.get(key, 0) or 0)
            card.set_desc(label.format(n=count))


def _kind_buckets(cards: list[dict], buckets: dict[str, tuple[str, ...]]) -> dict[str, int]:
    """卡片 ``kind`` → 每个筛选桶的张数。桶键就是胶囊键，没人命中的桶记 0。"""
    counts = dict.fromkeys(buckets, 0)
    for card in cards:
        kind = str(card.get("kind") or "")
        for key, kinds in buckets.items():
            if kind in kinds:
                counts[key] += 1
    return counts


class _CapabilityPage(QWidget):
    """能力页的公共壳：一个返回、一个计数、一排行、一句脚注。

    三页都只读宠物家（``pet_toolkit``），不碰 agent 的配置目录。
    """

    TITLE = ""

    def __init__(self, bench) -> None:
        super().__init__(bench)
        self._bench = bench
        self._win = bench._win
        column = QVBoxLayout(self)
        column.setContentsMargins(20, 13, 20, 14)
        column.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        back = QPushButton("工作台", self)
        back.setObjectName("Ghost")
        back.clicked.connect(lambda: self._bench.show_home())
        title = QLabel(self.TITLE, self)
        title.setObjectName("PageHead")
        self.count = QLabel("", self)
        self.count.setObjectName("PageSub")
        head.addWidget(back)
        head.addWidget(title)
        head.addStretch(1)
        for label, callback in self.header_actions():
            action = QPushButton(label, self)
            action.setObjectName("Ghost")
            action.clicked.connect(lambda _=False, cb=callback: cb())
            head.addWidget(action)
        head.addWidget(self.count)
        column.addLayout(head)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        column.addLayout(self.rows, 1)
        self.refresh()

    # -- 子类填这两样 -------------------------------------------------------
    def rows_spec(self) -> list[tuple[str, str, str, list]]:
        """``[(标题, 副标题, 标签, [(按钮字, 回调)])]``。"""
        return []

    #: 计数用在这一页上的量词
    UNIT = "条"

    def header_actions(self) -> list[tuple[str, object]]:
        """右上角那几个动作按钮：``[(按钮字, 回调)]``。"""
        return []

    def empty_text(self) -> str:
        return "暂无数据"

    def refresh(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        try:
            spec = list(self.rows_spec())
        except Exception:
            log.debug("%s：读不出来", self.TITLE, exc_info=True)
            spec = []
        self.count.setText(f"{len(spec)} {self.UNIT}" if spec else "")
        if not spec:
            hint = QLabel(self.empty_text(), self)
            hint.setObjectName("PageSub")
            hint.setWordWrap(True)
            self.rows.addStretch(1)
            self.rows.addWidget(hint, 0, Qt.AlignmentFlag.AlignCenter)
            self.rows.addStretch(1)
            return
        for title, meta, tag, buttons in spec:
            self.rows.addWidget(self._row(title, meta, tag, buttons))

    def _row(self, title: str, meta: str, tag: str, buttons: list) -> QFrame:
        row = QFrame(self)
        row.setObjectName("ApRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(10, 8, 10, 8)
        line.setSpacing(8)
        text = QVBoxLayout()
        text.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(title, row)
        name.setObjectName("ApTitle")
        head.addWidget(name)
        if tag:
            chip = QLabel(tag, row)
            chip.setObjectName("ApWs")
            head.addWidget(chip)
        head.addStretch(1)
        text.addLayout(head)
        note = QLabel(meta, row)
        note.setObjectName("PageSub")
        note.setWordWrap(True)
        text.addWidget(note)
        line.addLayout(text, 1)
        for label, callback in buttons:
            button = QPushButton(label, row)
            button.setObjectName("Ghost")
            button.clicked.connect(lambda _=False, cb=callback: cb())
            line.addWidget(button)
        return row


class _Switch(QWidget):
    """34×18 的开关。QSS 画不出圆角轨道 + 圆点，所以自绘。"""

    toggled = Signal(bool)

    def __init__(self, on: bool, parent=None) -> None:
        super().__init__(parent)
        self._on = bool(on)
        self.setFixedSize(34, 18)
        self.setCursor(Qt.PointingHandCursor)

    def isOn(self) -> bool:
        return self._on

    def setOn(self, on: bool) -> None:
        self._on = bool(on)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt 的接口名
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3fb27f" if self._on else "#4b545e"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 33, 17), 8.5, 8.5)
        painter.setBrush(QColor("#ffffff" if self._on else "#c7cfd8"))
        painter.drawEllipse(QRectF(18 if self._on else 2, 2, 14, 14))

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 的接口名
        if event.button() == Qt.LeftButton:
            self._on = not self._on
            self.update()
            self.toggled.emit(self._on)


def _name_hue(name: str) -> int:
    """名字 → 色相，同一个名字每次都是同一个颜色。"""
    return sum((index + 1) * ord(ch) for index, ch in enumerate(name)) % 360


def _avatar(name: str, parent) -> QLabel:
    label = QLabel((name or "?")[:1].upper(), parent)
    label.setFixedSize(34, 34)
    label.setAlignment(Qt.AlignCenter)
    color = QColor.fromHsl(_name_hue(name), 135, 120)
    label.setStyleSheet(
        f"background:{color.name()};color:#ffffff;border-radius:9px;"
        "font-size:13px;font-weight:700;"
    )
    return label


#: 状态 → (徽标文字, QSS objectName)
_KIND_LABEL = {
    "online": ("在线", "CapOn"),
    "installed": ("已装", "CapOn"),
    "available": ("未装", "CapOff"),
    "off": ("已禁用", "CapOff"),
    "failed": ("失败", "CapErr"),
    # 断连 / 重连中 / 需要认证都落这里：agent 视图也把这三类叫「等待加载」，
    # 而且都不进统计桶，不然同一份配置两边数出来差一大截。
    "pending": ("等待加载", "CapWait"),
}


class _ElideLabel(QLabel):
    """单行、超宽打点：地址和插件名都是长串，换行换不开，会撑爆网格列。"""

    def __init__(self, text: str = "", parent=None, elide=Qt.ElideRight):
        super().__init__("", parent)
        self._full = str(text)
        self._elide = elide
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setText(self._full)

    def setText(self, text: str) -> None:
        self._full = str(text)
        self._apply()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def _apply(self) -> None:
        width = max(32, self.width())
        shown = self.fontMetrics().elidedText(self._full, self._elide, width)
        super().setText(shown)
        self.setToolTip(self._full if shown != self._full else "")


class _ClampLabel(QLabel):
    """描述文字：最多两行、超出加省略号（agent 那边是 -webkit-line-clamp: 2）。"""

    LINES = 2

    def __init__(self, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self._raw = str(text or "")
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        fm = self.fontMetrics()
        self.setFixedHeight(fm.lineSpacing() * self.LINES + 2)
        width = max(self.width() - 2, 60)
        lines: list[str] = []
        cur = ""
        for ch in self._raw:
            if cur and fm.horizontalAdvance(cur + ch) > width:
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        if cur:
            lines.append(cur)
        if len(lines) > self.LINES:
            tail = "".join(lines[self.LINES - 1 :])
            lines = lines[: self.LINES - 1] + [fm.elidedText(tail, Qt.ElideRight, width)]
        super().setText("\n".join(lines))


class _CapTile(QFrame):
    """能力卡：整张可点（agent 的市场卡片是 ``cursor: pointer``）。"""

    def __init__(self, parent, on_click=None) -> None:
        super().__init__(parent)
        self._on_click = on_click
        if on_click is not None:
            self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:
        if self._on_click is not None and event.button() == Qt.LeftButton:
            self._on_click()
        super().mouseReleaseEvent(event)


def _cap_tile(card: dict, parent) -> QFrame:
    """一张能力卡：首字母色块 + 名字 + 状态徽标 + 开关 / 一行地址 / chip。"""
    name = str(card.get("name") or "")
    kind = str(card.get("kind") or "off")
    tile = _CapTile(parent, card.get("open"))
    tile.setObjectName("CapTileHot" if card.get("hot") else "CapTile")
    # 列宽由网格说话：卡片自己报的宽度会被长地址撑大，一列吃掉整行。
    tile.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    tile.setMinimumWidth(150)
    box = QVBoxLayout(tile)
    box.setContentsMargins(12, 11, 12, 10)
    box.setSpacing(6)

    top = QHBoxLayout()
    top.setSpacing(9)
    top.addWidget(_avatar(name, tile), 0, Qt.AlignTop)

    label = QVBoxLayout()
    label.setSpacing(3)
    title = _ElideLabel(name, tile)
    title.setObjectName("CapName")
    label.addWidget(title)
    if card.get("show_kind", True):
        text, object_name = _KIND_LABEL.get(kind, _KIND_LABEL["pending"])
        badge = QLabel(text, tile)
        badge.setObjectName(object_name)
        badge_row = QHBoxLayout()
        badge_row.setSpacing(0)
        badge_row.addWidget(badge)
        badge_row.addStretch(1)
        label.addLayout(badge_row)
    top.addLayout(label, 1)

    # 卡片自己的小动作（编辑 / 删除），跟 agent 卡片右上角一致。
    for icon_kind, tip, danger, handler in (
        ("pencil", "编辑", False, card.get("edit")),
        ("close", "删除", True, card.get("remove")),
    ):
        if handler is None:
            continue
        button = QPushButton(tile)
        button.setObjectName("CapAct")
        button.setProperty("danger", danger)
        button.setFixedSize(20, 20)
        button.setIcon(QIcon(_rail_pixmap(icon_kind, _tile_color(tile, danger))))
        button.setIconSize(QSize(12, 12))
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.clicked.connect(lambda _=False, cb=handler: cb())
        top.addWidget(button, 0, Qt.AlignTop)

    # 工坊的主动作：未装是灰底 ＋，装好变成绿底 √（agent 的 nd-skill-tile-add）。
    action = card.get("action")
    if action is not None:
        glyph, tip, done, handler = action
        button = QPushButton(glyph, tile)
        button.setObjectName("CapAdd")
        button.setProperty("done", "true" if done else "false")
        button.setFixedSize(24, 24)
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip(tip)
        button.setEnabled(not card.get("busy"))
        if handler is not None:
            button.clicked.connect(lambda _=False, cb=handler: cb())
        top.addWidget(button, 0, Qt.AlignTop)

    if card.get("on") is not None:
        switch = _Switch(bool(card.get("on")), tile)
        callback = card.get("toggle")
        if callback is not None:
            switch.toggled.connect(lambda on, cb=callback: cb(bool(on)))
        top.addWidget(switch, 0, Qt.AlignTop)
    box.addLayout(top)

    desc = str(card.get("desc") or "")
    if desc:
        note = _ClampLabel(desc, tile)
        note.setObjectName("CapDesc")
        note.setToolTip(desc)
        box.addWidget(note)

    chips = [chip for chip in (card.get("chips") or []) if chip]
    if chips:
        row = QHBoxLayout()
        row.setSpacing(5)
        for item in chips[:4]:
            callback = None
            tip = ""
            if isinstance(item, dict):
                text = str(item.get("text") or "")
                muted = bool(item.get("muted"))
                callback = item.get("click")
                tip = str(item.get("tip") or "")
            else:
                text, muted = item if isinstance(item, tuple) else (item, False)
            if callback is None:
                chip = QLabel(str(text), tile)
                chip.setObjectName("CapChipMuted" if muted else "CapChip")
                if tip:
                    chip.setToolTip(tip)
            else:
                # 有内容可看的胶囊才做成按钮：点开是这条工具的「摘要 / JSON」。
                chip = QPushButton(str(text), tile)
                chip.setObjectName("CapChipMuted" if muted else "CapChip")
                chip.setCursor(Qt.PointingHandCursor)
                chip.setToolTip(tip)
                chip.clicked.connect(lambda _=False, cb=callback: cb())
            row.addWidget(chip)
        row.addStretch(1)
        box.addLayout(row)

    foot = card.get("foot") or ()
    if foot:
        row = QHBoxLayout()
        row.setSpacing(12)
        for label_text, callback in foot:
            link = QPushButton(str(label_text), tile)
            link.setObjectName("CapLink")
            link.setCursor(Qt.PointingHandCursor)
            link.clicked.connect(lambda _=False, cb=callback: cb())
            row.addWidget(link)
        row.addStretch(1)
        box.addLayout(row)
    return tile


class _CapabilityGridPage(QWidget):
    """能力页：搜索 + 筛选胶囊 + 三列卡片网格（照 agent「技能与工具」的排法）。"""

    TITLE = ""
    UNIT = "个"
    SEARCH = "搜索"
    GEAR_TIP = "设置"
    PAGE_KEY = ""
    TABS: tuple[tuple[str, str], ...] = ()
    FILTERS = (("all", "全部"), ("online", "在线"), ("failed", "失败"), ("off", "已禁用"))

    def __init__(self, bench) -> None:
        super().__init__(bench)
        self._bench = bench
        self._win = bench._win
        self._query = ""
        self._filter = "all"
        self._cards: list[dict] = []
        self._seg_buttons: dict[str, QPushButton] = {}

        column = QVBoxLayout(self)
        column.setContentsMargins(20, 13, 20, 14)
        column.setSpacing(9)

        # 返回和 tab 同一行：返回是页级动作，tab 只是页内切换，不能把返回挤到
        # 下一行去当「第三个 tab」。
        top = QHBoxLayout()
        top.setSpacing(0)
        back = QPushButton("← 工作台", self)
        back.setObjectName("Ghost")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(lambda: self._bench.show_home())
        top.addWidget(back)
        top.addSpacing(8)
        tab_row = self._build_tab_row()
        if tab_row is not None:
            top.addLayout(tab_row)
        else:
            top.addStretch(1)
        column.addLayout(top)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel(self.TITLE, self)
        title.setObjectName("PageHead")
        head.addWidget(title)
        head.addStretch(1)
        for label_text, callback in self.header_actions():
            action = QPushButton(label_text, self)
            action.setObjectName("Ghost")
            action.clicked.connect(lambda _=False, cb=callback: cb())
            head.addWidget(action)
        # 齿轮是这一页唯一的总入口：不用把「导入」「添加」摊在标题行上，
        # 既不会跟计数挤在一起，也不用一进来就看见一次性动作。
        self.gear = None
        menu_items = self.menu_items()
        if menu_items:
            self.gear = QToolButton(self)
            self.gear.setObjectName("CapGear")
            # 齿轮就是齿轮：文字版「更多」在标题行里跟计数抢视线，也是
            # agent 那边用图标、宠物这边用字的地方之一。
            self.gear.setIcon(QIcon(_rail_pixmap("gear", _tile_color(self, False))))
            self.gear.setIconSize(QSize(14, 14))
            self.gear.setPopupMode(QToolButton.InstantPopup)
            self.gear.setCursor(Qt.PointingHandCursor)
            self.gear.setFixedSize(26, 26)
            self.gear.setToolTip(self.GEAR_TIP)
            menu = QMenu(self.gear)
            self._fill_gear_menu(menu_items, menu)
            self.gear.setMenu(menu)
            head.addWidget(self.gear)
        column.addLayout(head)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.search = QLineEdit(self)
        self.search.setObjectName("CapSearch")
        self.search.setPlaceholderText(self.SEARCH)
        self.search.textChanged.connect(self._on_query)
        toolbar.addWidget(self.search, 1)
        bar = QWidget(self)
        bar.setObjectName("CapSegBar")
        seg = QHBoxLayout(bar)
        seg.setContentsMargins(3, 3, 3, 3)
        seg.setSpacing(2)
        for key, label_text in self.FILTERS:
            button = QPushButton(label_text, bar)
            button.setObjectName("CapSeg")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setChecked(key == "all")
            button.clicked.connect(lambda _=False, k=key: self._on_filter(k))
            seg.addWidget(button)
            self._seg_buttons[key] = button
        toolbar.addWidget(bar)
        column.addLayout(toolbar)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._body = QWidget(self._scroll)
        body_column = QVBoxLayout(self._body)
        body_column.setContentsMargins(0, 0, 0, 0)
        body_column.setSpacing(0)
        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(10)
        for col in range(3):
            self._grid.setColumnStretch(col, 1)
        body_column.addLayout(self._grid)
        body_column.addStretch(1)
        self._scroll.setWidget(self._body)
        column.addWidget(self._scroll, 1)

        self.refresh()

    # -- 子类填这几样 -------------------------------------------------------
    def cards_spec(self) -> list[dict]:
        """``[{name, kind, desc, chips, on, toggle, foot}]``。"""
        return []

    def header_actions(self) -> list[tuple[str, object]]:
        return []

    def _build_tab_row(self) -> QHBoxLayout | None:
        """技能 · 连接器 的胶囊 tab（照 agent 的 nd-cap-hub-tabs）。"""
        if not self.TABS:
            return None
        bar = QWidget(self)
        bar.setObjectName("CapTabBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        for key, label_text in self.TABS:
            button = QPushButton(label_text, bar)
            button.setObjectName("CapTab")
            button.setCheckable(True)
            button.setChecked(key == self.PAGE_KEY)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, target=key: self._bench.show_page(target))
            lay.addWidget(button)
        row = QHBoxLayout()
        row.addWidget(bar)
        row.addStretch(1)
        return row

    def menu_items(self) -> list[object]:
        """齿轮菜单里的条目：``(文案, 回调)``，或 ``"-"`` 分隔线。"""
        return []

    def _fill_gear_menu(self, items: list[object], menu: QMenu) -> None:
        for entry in items:
            if entry == "-":
                menu.addSeparator()
                continue
            label_text, callback = entry
            action = menu.addAction(str(label_text))
            action.triggered.connect(lambda _=False, cb=callback: cb())

    def empty_text(self) -> str:
        return "暂无数据"

    # -- 搜索 / 筛选 -------------------------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 构造时这页还没挂到窗口上，拿不到主题色；每回显示重画一次最稳。
        self._paint_gear()
        super().showEvent(event)

    def _paint_gear(self) -> None:
        """换主题后重画齿轮：icon 是位图，不会跟着 QSS 变色。"""
        gear = getattr(self, "gear", None)
        if gear is not None:
            gear.setIcon(QIcon(_rail_pixmap("gear", _tile_color(self, False))))

    def _on_query(self, text: str) -> None:
        self._query = str(text or "").strip().lower()
        self._rebuild()

    def _on_filter(self, key: str) -> None:
        self._filter = key
        for name, button in self._seg_buttons.items():
            button.setChecked(name == key)
        self._rebuild()

    #: 筛选键 → 算进这一桶的卡片 ``kind``。三页各有各的词（在线/已装），
    #: 所以桶归子类说；胶囊数字和筛选都对它。
    BUCKETS: dict[str, tuple[str, ...]] = {
        "online": ("online", "installed"),
        "failed": ("failed",),
        "off": ("off",),
    }

    def refresh(self) -> None:
        self._paint_gear()
        self._cards = list(self.cards_spec())
        counts = {"all": len(self._cards)}
        counts.update(_kind_buckets(self._cards, self.BUCKETS))
        for key, label_text in self.FILTERS:
            button = self._seg_buttons.get(key)
            if button is not None:
                button.setText(f"{label_text} {counts.get(key, 0)}")
        self._rebuild()

    def _visible(self) -> list[dict]:
        # 胶囊上的数字和点开看到的卡片必须同时由 BUCKETS 决定，各算一套就会对不上。
        kinds = self.BUCKETS.get(self._filter)
        out: list[dict] = []
        for card in self._cards:
            if kinds is not None and str(card.get("kind") or "") not in kinds:
                continue
            if self._query:
                hay = " ".join(
                    [str(card.get("name") or ""), str(card.get("desc") or "")]
                    + [str(chip) for chip in (card.get("chips") or [])]
                ).lower()
                if self._query not in hay:
                    continue
            out.append(card)
        return out

    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                # 先摘离再 deleteLater：延迟删除生效前它不能还留在屏上。
                widget.setParent(None)
                widget.deleteLater()
        rows = self._visible()
        for index, card in enumerate(rows):
            self._grid.addWidget(_cap_tile(card, self._body), index // 3, index % 3, Qt.AlignTop)
        if not rows:
            empty = QLabel(self.empty_text(), self._body)
            empty.setObjectName("PageSub")
            empty.setWordWrap(True)
            empty.setAlignment(Qt.AlignCenter)
            self._grid.addWidget(empty, 0, 0, 1, 3)


class _ThemeCard(QFrame):
    """一格皮肤：主色点 + 名字。点整格就换过去，不用再按一次确定。"""

    picked = Signal(str)

    def __init__(self, key: str, label: str, dot_color: str, parent=None) -> None:
        super().__init__(parent)
        self.key = key
        self.setObjectName("ThemeCard")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setProperty("on", False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(44)
        row = QHBoxLayout(self)
        row.setContentsMargins(11, 9, 11, 9)
        row.setSpacing(9)
        dot = QLabel(self)
        dot.setFixedSize(12, 12)
        dot.setAttribute(Qt.WA_StyledBackground, True)
        dot.setStyleSheet(
            # 中性描边：纯白/纯黑的主题色只能靠它跟同色卡片分开，太淡就白搭。
            f"background:{dot_color};border:1px solid rgba(128,128,128,185);border-radius:6px;"
        )
        row.addWidget(dot)
        name = QLabel(label, self)
        name.setObjectName("SetName")
        row.addWidget(name)
        row.addStretch(1)
        self._mark = QLabel("使用中", self)
        self._mark.setObjectName("SetMark")
        self._mark.setVisible(False)
        row.addWidget(self._mark)

    def set_on(self, on: bool) -> None:
        self.setProperty("on", bool(on))
        self._mark.setVisible(bool(on))
        # 动态属性变了 QSS 不会自己重算，得手动 re-polish 一次。
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 的接口名
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self.key)
        super().mouseReleaseEvent(event)


class _WsSwitch(QAbstractButton):
    """卡片右上角的小开关：34x19 的轨道 + 白圆点，开启时用主题强调色。

    QSS 的 ``::indicator`` 画不出滑块（只有一张底图），而这页只需要一个开关控件，
    自绘比塞三张图片省事，也能跟着四条主题色走。
    """

    def __init__(self, checked: bool, accent: str, parent=None) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(34, 19)
        self.setToolTip("停用后自动路由不会再挑这个模型")

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = track.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(
            self._accent if self.isChecked() else QColor(255, 255, 255, 40)
        )
        painter.drawRoundedRect(track, radius, radius)
        knob = track.height() - 5
        left = track.width() - knob - 2.5 if self.isChecked() else 2.5
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QRectF(left, 2.5, knob, knob))
        painter.end()


class _WsChatModelPage(QWidget):
    """设置 → 模型：桌宠聊天用哪些模型。

    版式和交互照抄 agent 视图的模型页（``ModelSection.tsx``）：右上「刷新」+「+ 添加模型」，
    下面按云端 / 本地分组摆卡片（名字、状态、模型与端点、启用开关、删除）。

    用哪个模型不需要选：发送前按清单顺序自动挑第一个能用的（``ChatSettings.auto_pick``），
    停用的卡片自动跳过。

    和 agent 视图是两套配置，互不影响：只读写桌宠自己的 ``config.json``，不碰
    Electron 的 ``User/settings.json``，也不写引擎的 ``config.toml``。
    """

    def __init__(self, config, on_manage=None, refresh_chat=None, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self._on_manage = on_manage
        self._refresh_chat = refresh_chat
        self._settings = config.chat_settings() if config is not None else None
        self._dialog = None
        self.setObjectName("modelSettingsContent")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("模型", self)
        title.setObjectName("SetHead")
        head.addWidget(title)
        head.addStretch(1)
        self._reload = QPushButton("刷新", self)
        self._reload.setObjectName("CapGhost")
        self._reload.setCursor(Qt.PointingHandCursor)
        self._reload.clicked.connect(self._manual_refresh)
        head.addWidget(self._reload)
        self._add = QPushButton("+ 添加模型", self)
        self._add.setObjectName("CapSave")
        self._add.setCursor(Qt.PointingHandCursor)
        self._add.setToolTip("新增模型、填 API Key、测试连接")
        self._add.clicked.connect(self._open_add_dialog)
        self._add.setEnabled(config is not None)
        head.addWidget(self._add)
        outer.addLayout(head)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        self._host = QWidget(scroll)
        self._col = QVBoxLayout(self._host)
        self._col.setContentsMargins(0, 0, 8, 0)
        self._col.setSpacing(8)
        scroll.setWidget(self._host)
        outer.addWidget(scroll, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("SetHint")
        self._status.setWordWrap(True)
        self._status.hide()
        outer.addWidget(self._status)

        self._render()

    # -- 渲染 ---------------------------------------------------------------
    def _render(self) -> None:
        while self._col.count():
            item = self._col.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        if self.config is None or self._settings is None:
            self._col.addWidget(self._empty("读不到桌宠配置，模型页暂时不可用。"))
            self._col.addStretch(1)
            return

        self._settings = self.config.chat_settings()
        providers = self._settings.providers
        if not providers:
            self._col.addWidget(self._empty("还没有模型。点右上「+ 添加模型」加一个。"))
            self._col.addStretch(1)
            return
        for caption, local in (("云端", False), ("本地", True)):
            items = [
                (provider_id, provider)
                for provider_id, provider in providers.items()
                if self._settings.is_local_endpoint(provider.base_url) is local
            ]
            if not items:
                continue
            self._col.addWidget(self._group_label(caption))
            for provider_id, provider in items:
                self._col.addWidget(self._provider_row(provider_id, provider))
        self._col.addStretch(1)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 模型可能在另一个窗口里改过，回到这页就重读一遍（比信号接线可靠）。
        super().showEvent(event)
        if self.config is not None:
            self._render()

    def _group_label(self, text: str) -> QLabel:
        label = QLabel(text, self._host)
        label.setObjectName("SetGroup")
        return label

    def _accent(self) -> str:
        """当前主题的强调色（自绘开关要用）。"""
        key = str(getattr(self.window(), "_theme_key", "") or "")
        return str(_theme(key)[2].get("acc") or "#e8a33d")

    def _provider_row(self, provider_id: str, provider) -> QFrame:
        row = QFrame(self._host)
        row.setObjectName("SetRow")
        line = QVBoxLayout(row)
        line.setContentsMargins(14, 11, 12, 11)
        line.setSpacing(3)

        top = QHBoxLayout()
        top.setSpacing(10)
        name = QLabel(str(provider.name or provider_id), row)
        name.setObjectName("SetRowName")
        top.addWidget(name)
        top.addStretch(1)
        badge = self._badge_for(provider_id, provider)
        if badge is not None:
            top.addWidget(badge)

        enable = _WsSwitch(bool(provider.enabled), self._accent(), row)
        enable.toggled.connect(lambda on, pid=provider_id: self._set_enabled(pid, on))
        top.addWidget(enable)

        remove = QPushButton("删除", row)
        remove.setObjectName("SetRemove")
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.clicked.connect(lambda _=False, pid=provider_id: self._delete(pid))
        top.addWidget(remove)
        line.addLayout(top)

        detail = " · ".join(
            part
            for part in (
                TIER_LABELS["fast"] if normalize_tier(getattr(provider, "tier", "")) == "fast" else "",
                str(provider.model or ""),
                str(provider.base_url or ""),
            )
            if part
        )
        if detail:
            meta = QLabel(detail, row)
            meta.setObjectName("SetHint")
            meta.setWordWrap(True)
            line.addWidget(meta)
        return row

    def _badge_for(self, provider_id: str, provider) -> QLabel | None:
        # 停用的卡片不挂徽标：开关本身就是那个状态，再标一个「已停用」是重复。
        if not provider.enabled:
            return None
        if self._settings is not None and self._settings.auto_pick() is not None:
            in_use = self._settings.auto_pick()[0] == provider_id
        else:
            in_use = provider_id == self._settings.active_provider
        if in_use:
            return self._badge("在用", "on")
        if self._settings is not None and self._settings.usable_for_request(provider_id):
            return self._badge("备用", "off")
        return self._badge("缺 Key", "warn")

    def _badge(self, text: str, state: str) -> QLabel:
        badge = QLabel(text, self._host)
        badge.setObjectName("SetBadge")
        badge.setProperty("state", state)
        return badge

    def _empty(self, text: str) -> QLabel:
        label = QLabel(text, self._host)
        label.setObjectName("SetHint")
        label.setWordWrap(True)
        return label

    def _set_status(self, text: str) -> None:
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _commit(self) -> bool:
        """落盘并让开着的聊天窗重读配置（气泡自己缓存 settings）。"""
        try:
            ok = self.config.save()
        except Exception:  # noqa: BLE001 - 写盘失败要提示，不能静默
            log.debug("保存聊天模型清单失败", exc_info=True)
            ok = False
        if callable(self._refresh_chat):
            self._refresh_chat()
        self._render()
        if ok:
            self._sync_engine_profiles()
        else:
            self._set_status("保存失败：配置文件写不进去。")
        return ok

    def _sync_engine_profiles(self) -> None:
        """把桌宠这份模型清单镜像进引擎的 ``config.toml``（它自己的 managed block）。

        只是让引擎认识桌宠的模型：名字统一 ``pet-`` 前缀，key 走 ``SetModelKey``
        进 daemon 内存，**不写** ``[model.routing.*]`` —— agent 视图那份模型设置
        一个字都不会被改到。daemon 没起就只写盘，等它起来后下一句对话再补。
        """
        try:
            from .agent_link import daemon_client
            from .chat import engine_profiles
        except Exception:  # noqa: BLE001 - 引擎侧缺件不该挡住桌宠自己的保存
            log.debug("引擎模块不可用，跳过模型镜像", exc_info=True)
            return
        providers = [
            p
            for p in (self._settings.providers.values() if self._settings is not None else [])
            if str(getattr(p, "model", "") or "").strip()
        ]
        try:
            changed = engine_profiles.sync_profiles(providers)
        except Exception:  # noqa: BLE001 - 写不进 config.toml 只影响引擎那条路
            log.debug("写桌宠模型镜像失败", exc_info=True)
            return
        if not daemon_client.AVAILABLE:
            return
        keys = {
            engine_profiles.profile_name(p.provider_id): str(p.api_key or "")
            for p in providers
            if str(getattr(p, "api_key", "") or "").strip()
        }

        def worker() -> None:
            client = daemon_client.LajiDaemonClient()
            try:
                if not client.connect():
                    return
                if changed:
                    client.reload_local_config()
                for name, key in keys.items():
                    client.set_model_key(name, key)
            except Exception:  # noqa: BLE001 - 同步失败不弹窗，下一轮对话会重试
                log.debug("同步桌宠模型到引擎失败", exc_info=True)
            finally:
                client.close()

        threading.Thread(target=worker, daemon=True, name="pet-model-sync").start()

    def _manual_refresh(self) -> None:
        self._set_status("")
        self._render()

    def _set_enabled(self, provider_id: str, on: bool) -> None:
        if self.config is None:
            return
        settings = self.config.chat_settings()
        provider = settings.providers.get(provider_id)
        if provider is None or bool(provider.enabled) == bool(on):
            return
        provider.enabled = bool(on)
        self.config.set_chat_settings(settings)
        self._set_status("")
        self._commit()

    def _delete(self, provider_id: str) -> None:
        if self.config is None:
            return
        settings = self.config.chat_settings()
        provider = settings.providers.get(provider_id)
        if provider is None:
            return
        name = str(provider.name or provider_id)
        answer = QMessageBox.question(
            self,
            "删除模型",
            f"从清单里删掉「{name}」？\nAPI Key 不会被这个窗口删掉，重新加回同名模型还能接着用。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        settings.providers.pop(provider_id, None)
        if settings.active_provider == provider_id:
            settings.active_provider = next(iter(settings.providers), "")
        self.config.set_chat_settings(settings)
        if self._commit():
            self._set_status(f"已删除 {name}。")

    def _open_add_dialog(self) -> None:
        if self.config is None:
            self._set_status("读不到桌宠配置，加不了模型。")
            return
        dialog = _AddModelDialog(self.config, self)
        self._dialog = dialog  # 保住引用，别被 GC 提前收走
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        provider_id = dialog.saved_provider_id
        self._dialog = None
        if not accepted or not provider_id:
            return
        self._commit()
        settings = self.config.chat_settings()
        provider = settings.providers.get(provider_id)
        self._set_status(f"已添加 {provider.name if provider is not None else provider_id}。")


# 预设照抄 agent 视图的 providers.ts，只留 OpenAI 兼容的服务：协议不对的预设
# （Anthropic 这种）填进去能存下来，第一次对话就 404，用户会以为是自己 key 填错了。
_WS_MODEL_PRESETS = (
    {
        "id": "deepseek",
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-v4-flash",
        "models": ("deepseek-v4-flash", "deepseek-v4-pro"),
        "needs_key": True,
    },
    {
        "id": "groq",
        "label": "Groq（免费额度）",
        "base_url": "https://api.groq.com/openai/v1",
        "model": "qwen/qwen3.6-27b",
        "models": ("qwen/qwen3.6-27b", "llama-3.3-70b-versatile"),
        "needs_key": True,
    },
    {
        "id": "gemini",
        "label": "Google Gemini（免费额度）",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-2.0-flash",
        "models": ("gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"),
        "needs_key": True,
    },
    {
        "id": "openai",
        "label": "OpenAI / OpenAI 兼容",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "models": ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"),
        "needs_key": True,
    },
    {
        "id": "qwen",
        "label": "Qwen（DashScope）",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "models": ("qwen-plus", "qwen-turbo", "qwen-max"),
        "needs_key": True,
    },
    {
        "id": "opencode",
        "label": "OpenCode Go（订阅）",
        "base_url": "https://opencode.ai/zen/go/v1",
        "model": "deepseek-v4.1-flash",
        "models": (
            "deepseek-v4.1-flash",
            "deepseek-v4-pro",
            "kimi-k3.1-pro",
            "glm-5.3-flash",
            "qwen3.7-plus",
        ),
        "needs_key": True,
    },
    {
        "id": "ollama",
        "label": "Ollama（本地）",
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen2.5-coder:7b",
        "models": ("qwen2.5-coder:7b", "deepseek-r1:7b", "llama3.2:latest"),
        "needs_key": False,
    },
    {
        "id": "custom",
        "label": "自定义 OpenAI 兼容网关",
        "base_url": "",
        "model": "",
        "models": (),
        "needs_key": True,
    },
)


def _ws_model_preset(preset_id: str) -> dict:
    for preset in _WS_MODEL_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return _WS_MODEL_PRESETS[-1]


class _AddModelDialog(QDialog):
    """新增一个聊天模型：服务商 → 模型 ID → 端点 → API Key，底部「测试连接」。

    字段顺序和信息密度照抄 agent 视图的「添加模型」对话框（``AddModelDialog.tsx``）：
    名称 → 服务商 → 模型 ID（带建议，可自己填）→ 端点（非自定义预设只读）→ API Key。
    只写桌宠自己的 ``config.json``。
    """

    test_done = Signal(bool, str)

    def __init__(self, config, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.saved_provider_id = None
        self._test_thread = None
        # 真正画背景的是里面那层 QFrame：无边框窗口自己不画圆角，只靠半透明
        # 顶层 + 圆角卡片，否则弹出的是个直角方块。
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setFixedWidth(452)

        shell = QFrame(self)
        shell.setObjectName("CapDialog")
        shell.setAttribute(Qt.WA_StyledBackground, True)
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(shell)

        box = QVBoxLayout(shell)
        box.setContentsMargins(20, 16, 20, 16)
        box.setSpacing(11)

        head = QHBoxLayout()
        head.setSpacing(8)
        title = QLabel("添加模型", shell)
        title.setObjectName("CapDialogHead")
        head.addWidget(title)
        head.addStretch(1)
        close = QToolButton(shell)
        close.setObjectName("CapIcon")
        close.setIcon(QIcon(self._close_pixmap()))
        close.setIconSize(QSize(12, 12))
        close.setFixedSize(26, 26)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setToolTip("关闭")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        box.addLayout(head)

        # 名称和服务商并排：竖着排下来弹框又高又空
        self._name = QLineEdit(shell)
        self._name.setObjectName("CapField")
        self._name.setPlaceholderText("留空就用服务商名字")
        self._name.setMaxLength(40)
        self._preset = QComboBox(shell)
        self._preset.setObjectName("CapField")
        for preset in _WS_MODEL_PRESETS:
            self._preset.addItem(preset["label"], preset["id"])
        self._preset.currentIndexChanged.connect(self._on_preset_changed)
        pair = QGridLayout()
        pair.setHorizontalSpacing(10)
        pair.setVerticalSpacing(0)
        pair.addWidget(self._field("模型名称", self._name, shell), 0, 0)
        pair.addWidget(self._field("模型服务商", self._preset, shell), 0, 1)
        pair.setColumnStretch(0, 1)
        pair.setColumnStretch(1, 1)
        box.addLayout(pair)

        self._model = QComboBox(shell)
        self._model.setObjectName("CapField")
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self._tier = QComboBox(shell)
        self._tier.setObjectName("CapField")
        for tier_id in ("standard", "fast"):
            self._tier.addItem(TIER_LABELS[tier_id], tier_id)
        self._tier.setToolTip("快档：寒暄、算术、「怎么选」这类一句话问答优先用它；正经任务仍走标准档")
        model_row = QGridLayout()
        model_row.setHorizontalSpacing(10)
        model_row.setVerticalSpacing(0)
        model_row.addWidget(self._field("Model ID", self._model, shell), 0, 0)
        model_row.addWidget(self._field("档位", self._tier, shell), 0, 1)
        model_row.setColumnStretch(0, 2)
        model_row.setColumnStretch(1, 1)
        box.addLayout(model_row)

        self._endpoint = QLineEdit(shell)
        self._endpoint.setObjectName("CapField")
        box.addWidget(self._field("端点", self._endpoint, shell))

        self._key = QLineEdit(shell)
        self._key.setObjectName("CapField")
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setClearButtonEnabled(True)
        box.addWidget(self._field("API Key", self._key, shell))

        # 结果行先占位，否则测试完弹框会突然长高
        self._result = QLabel("", shell)
        self._result.setObjectName("SetHint")
        self._result.setWordWrap(True)
        self._result.setMinimumHeight(14)
        box.addWidget(self._result)

        split = QFrame(shell)
        split.setObjectName("SetSplit")
        split.setFixedHeight(1)
        box.addWidget(split)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        self._test = QPushButton("测试连接", shell)
        self._test.setObjectName("CapGhost")
        self._test.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test.clicked.connect(self._run_test)
        foot.addWidget(self._test)
        foot.addStretch(1)
        cancel = QPushButton("取消", shell)
        cancel.setObjectName("CapGhost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        self._submit_btn = QPushButton("添加模型", shell)
        self._submit_btn.setObjectName("CapSave")
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.clicked.connect(self._submit)
        foot.addWidget(self._submit_btn)
        box.addLayout(foot)

        self.test_done.connect(self._on_test_done)
        self._sync_preset()

    def _close_pixmap(self) -> QPixmap:
        """自绘关闭叉：字体缺 "×" 字形时按钮会是空白，图标画出来更稳。"""
        key = str(getattr(self.window(), "_theme_key", "") or "")
        _key, _label, colors = _theme(key)
        pix = QPixmap(24, 24)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor(colors["fg2"]), 1.5)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(7, 7, 17, 17)
        painter.drawLine(17, 7, 7, 17)
        painter.end()
        return pix

    def _field(self, caption: str, widget: QWidget, parent=None) -> QWidget:
        holder = QWidget(parent or self)
        col = QVBoxLayout(holder)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(6)
        label = QLabel(caption, holder)
        label.setObjectName("SetFieldLabel")
        col.addWidget(label)
        col.addWidget(widget)
        return holder

    # -- 预设联动 -----------------------------------------------------------
    def _preset_spec(self) -> dict:
        return _ws_model_preset(str(self._preset.currentData() or ""))

    def _on_preset_changed(self, _index: int) -> None:
        self._sync_preset()

    def _sync_preset(self) -> None:
        spec = self._preset_spec()
        custom = spec["id"] == "custom"
        self._endpoint.setText(spec["base_url"])
        self._endpoint.setReadOnly(not custom)
        self._endpoint.setPlaceholderText("https://gateway.example.com/v1")
        self._model.clear()
        self._model.addItems([str(m) for m in spec["models"]])
        self._model.setCurrentText(spec["model"])
        self._key.setEnabled(bool(spec["needs_key"]))
        self._key.setPlaceholderText("sk-…" if spec["needs_key"] else "本地服务不用填")
        if spec["needs_key"]:
            self._set_tone("")
            self._result.setText("")
        else:
            self._result.setText(f"{spec['label']} 不需要 API Key。")
            self._set_tone("")

    def _set_tone(self, tone: str) -> None:
        if self._result.property("tone") == tone:
            return
        self._result.setProperty("tone", tone)
        self._result.style().unpolish(self._result)
        self._result.style().polish(self._result)

    def _set_result(self, text: str, ok: bool) -> None:
        self._result.setText(text)
        self._set_tone("ok" if ok else "bad")

    # -- 测试连接 -----------------------------------------------------------
    def _provisional_provider(self):
        from .chat.models import ProviderConfig

        spec = self._preset_spec()
        return ProviderConfig(
            provider_id="connection-test",
            name=str(self._name.text().strip() or spec["label"]),
            base_url=self._endpoint.text().strip(),
            chat_path="/v1/chat/completions",
            model=str(self._model.currentText().strip()),
            api_key=self._key.text().strip(),
            timeout=20.0,
        )

    def _run_test(self) -> None:
        if self._test_thread is not None and self._test_thread.is_alive():
            return
        spec = self._preset_spec()
        if not self._endpoint.text().strip():
            self._set_result("先填端点地址。", False)
            return
        if not self._model.currentText().strip():
            self._set_result("先填 Model ID。", False)
            return
        if spec["needs_key"] and not self._key.text().strip():
            self._set_result("先填 API Key 再测。", False)
            return
        provider = self._provisional_provider()
        self._test.setEnabled(False)
        self._test.setText("测试中…")
        self._result.setText("")
        self._test_thread = threading.Thread(
            target=self._test_worker,
            args=(provider,),
            daemon=True,
            name="pet-ws-model-connection-test",
        )
        self._test_thread.start()

    def _test_worker(self, provider) -> None:
        from .chat.providers import test_connection

        ok, message = test_connection(provider, timeout=10.0)
        # 对话框可能在测试在飞时被关掉销毁：直接 emit 会对已删 C++ 对象 RuntimeError。
        try:
            self.test_done.emit(ok, message)
        except RuntimeError:
            pass

    def _on_test_done(self, ok: bool, message: str) -> None:
        self._test.setEnabled(True)
        self._test.setText("测试连接")
        self._set_result(message, ok)
        self._test_thread = None

    # -- 保存 ---------------------------------------------------------------
    def _unique_id(self, settings, base: str) -> str:
        base = base or "model"
        if base not in settings.providers:
            return base
        index = 2
        while f"{base}-{index}" in settings.providers:
            index += 1
        return f"{base}-{index}"

    def _submit(self) -> None:
        from .chat.models import ProviderConfig, SecretStore

        if self.config is None:
            self._set_result("读不到桌宠配置，加不了模型。", False)
            return
        spec = self._preset_spec()
        model = str(self._model.currentText().strip())
        base_url = self._endpoint.text().strip()
        if not model:
            self._set_result("先填 Model ID。", False)
            return
        if not base_url:
            self._set_result("先填端点地址。", False)
            return
        settings = self.config.chat_settings()
        provider_id = self._unique_id(settings, str(spec["id"]))
        provider = ProviderConfig(
            provider_id=provider_id,
            name=str(self._name.text().strip() or spec["label"]),
            base_url=base_url,
            chat_path="/v1/chat/completions",
            model=model,
            api_key_ref=f"provider/{provider_id}",
            tier=str(self._tier.currentData() or "standard"),
        )
        note = ""
        key = self._key.text().strip()
        if key and not SecretStore().set(provider.api_key_ref, key):
            provider.api_key = key  # 钥匙串不可用：只留内存，写盘时会被剔除
            note = "（系统钥匙串不可用，Key 只在本次运行有效）"
        settings.providers[provider_id] = provider
        if not settings.active_provider:
            settings.active_provider = provider_id
        self.config.set_chat_settings(settings)
        try:
            saved = self.config.save()
        except Exception:  # noqa: BLE001 - 写盘失败要提示
            log.debug("保存新增模型失败", exc_info=True)
            saved = False
        if not saved:
            self._set_result("保存失败：配置文件写不进去。", False)
            return
        self.saved_provider_id = provider_id
        if note:
            log.info("新增模型 %s %s", provider_id, note)
        self.accept()


class _WsSettingsDialog(QDialog):
    """窗口自己的设置：外观、模型。"""

    SECTIONS = (("appearance", "外观"), ("models", "模型"))

    def __init__(self, win, parent=None) -> None:
        super().__init__(parent or win)
        self.win = win
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(660)
        tall = win.height() if win is not None else 0
        self.setFixedHeight(max(360, min(560, tall - 30)) if tall else 470)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 15, 18, 14)
        box.setSpacing(10)

        head_row = QHBoxLayout()
        head_row.setSpacing(8)
        head = QLabel("设置", self)
        head.setObjectName("CapDialogHead")
        head_row.addWidget(head)
        head_row.addStretch(1)
        done = QPushButton("完成", self)
        done.setObjectName("CapGhost")
        done.clicked.connect(self.accept)
        head_row.addWidget(done)
        box.addLayout(head_row)

        body = QHBoxLayout()
        body.setSpacing(14)
        # 只剩一个分区时不摆导航列，省下来的宽度给页面。
        self._group: QButtonGroup | None = None
        if len(self.SECTIONS) > 1:
            nav = QWidget(self)
            nav.setFixedWidth(112)
            nav_col = QVBoxLayout(nav)
            nav_col.setContentsMargins(0, 2, 0, 0)
            nav_col.setSpacing(4)
            self._group = QButtonGroup(self)
            self._group.setExclusive(True)
            for index, (_key, label) in enumerate(self.SECTIONS):
                button = QPushButton(label, nav)
                button.setObjectName("SetNav")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.clicked.connect(lambda _=False, i=index: self.pages.setCurrentIndex(i))
                self._group.addButton(button, index)
                nav_col.addWidget(button)
            nav_col.addStretch(1)
            body.addWidget(nav)

        builders = {
            "appearance": self._appearance_page,
            "models": self._model_page,
        }
        self.pages = QStackedWidget(self)
        for key, _label in self.SECTIONS:
            self.pages.addWidget(builders[key]())
        body.addWidget(self.pages, 1)
        box.addLayout(body, 1)
        if self._group is not None:
            self._group.button(0).setChecked(True)
        self.pages.setCurrentIndex(0)
        self._sync_themes()

    # -- 外观 ---------------------------------------------------------------
    def _appearance_page(self) -> QWidget:
        page = QWidget(self)
        col = QVBoxLayout(page)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        head = QLabel("主题颜色", page)
        head.setObjectName("SetHead")
        col.addWidget(head)
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self.theme_cards: dict[str, _ThemeCard] = {}
        for index, (key, label, palette) in enumerate(THEMES):
            # 点的颜色就是主题本身：白/黑那两套的“强调色”是金/近白，直接拿它当点就不直观了。
            dot_color = str(palette.get("dot") or palette.get("acc") or "#e8a33d")
            card = _ThemeCard(key, label, dot_color, page)
            card.picked.connect(self._pick_theme)
            grid.addWidget(card, index // 2, index % 2)
            self.theme_cards[key] = card
        col.addLayout(grid)
        col.addStretch(1)
        return page

    def _pick_theme(self, key: str) -> None:
        if self.win is None:
            return
        self.win.apply_theme(key)
        self._sync_themes()

    def _sync_themes(self) -> None:
        current = str(getattr(self.win, "_theme_key", "") or "")
        for key, card in self.theme_cards.items():
            card.set_on(key == current)

    # -- 模型 ---------------------------------------------------------------
    def _model_page(self) -> QWidget:
        owner = getattr(self.win, "owner", None) if self.win is not None else None
        self.model_page = _WsChatModelPage(
            getattr(owner, "config", None),
            on_manage=self._open_chat_model_settings,
            refresh_chat=self._refresh_chat_consumers,
            parent=self,
        )
        return self.model_page

    def _refresh_chat_consumers(self) -> None:
        """切换后让开着的聊天窗重读配置。

        小工位的 owner 就是快捷聊天气泡（``QuickChatBubble``）：它把 settings 缓存在
        自己身上（发送时读 ``self.settings.active_config``）。``PetApp._refresh_chat_windows``
        只管 legacy/modern 两个大窗，够不到这里，而小工位这一路也只有它一个消费者。
        """
        owner = getattr(self.win, "owner", None) if self.win is not None else None
        if owner is None or not hasattr(owner, "settings"):
            return
        config = getattr(owner, "config", None)
        if config is None:
            return
        try:
            owner.settings = config.chat_settings()
        except Exception:  # noqa: BLE001 - 刷新失败不该回滚已落盘的选择
            log.debug("刷新聊天窗设置失败", exc_info=True)

    def _open_chat_model_settings(self) -> bool:
        """跳到管完整模型清单的地方（增删改 / 密钥 / 测试连接都在那边）。

        入口在 ``PetWindow.on_open_chat_settings``（``PetApp._wire_window`` 注入的
        ``PetApp.open_chat_settings``）；小工位的 owner 并不是 ``PetApp``，所以按
        「气泡 -> pet_window -> 回调」找，别直接去 owner 上取同名方法。
        """
        owner = getattr(self.win, "owner", None) if self.win is not None else None
        pet_window = getattr(owner, "pet_window", None)
        opener = getattr(pet_window, "on_open_chat_settings", None)
        if not callable(opener):
            opener = getattr(owner, "on_open_chat_settings", None)
        if callable(opener):
            self.accept()
            QTimer.singleShot(0, opener)
            return True
        if self._open_chat_settings_dialog():
            self.accept()
            return True
        log.warning("聊天 AI 设置入口未接：owner=%r", type(owner).__name__)
        return False

    def _open_chat_settings_dialog(self) -> bool:
        """最后一道布置：自己开一个 AI 设置对话框，不依赖 app 的接线。

        工作台的主人可能是快捷聊天气泡、也可能是别处传来的一层壳，任何一层没接上
        回调，都不应该表现成「点了没反应」。
        """
        config = getattr(self.model_page, "config", None)
        if config is None:
            return False
        try:
            from .chat.settings_dialog import ChatSettingsDialog
        except Exception:  # noqa: BLE001 - 聊天子系统缺失时不拦别的设置项
            log.warning("聊天 AI 设置不可用", exc_info=True)
            return False
        dialog = ChatSettingsDialog(config, self.win)
        dialog.setModal(False)
        dialog.setWindowModality(Qt.WindowModality.NonModal)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.finished.connect(lambda _result: self._refresh_chat_consumers())
        self._chat_settings_dialog = dialog  # 保住引用，别被 GC 提前收走
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True


class _ConnectorDialog(QDialog):
    """加一个、改一个连接器：直接改那条 JSON（与 agent 的编辑框同一份形状）。

    写回的是宠物家那份 ``pet-mcp.json`` —— 只影响这个工作区的宠物 Run，
    agent 视图那份 ``mcp-custom.json`` 一个字不动。``headers`` / ``env`` /
    ``disabled_tools`` 这类字段一个都不能丢。
    """

    def __init__(self, parent=None, card: dict | None = None, home: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(520)
        avail = parent.height() if parent is not None else 0
        self.setFixedHeight(min(560, max(360, avail - 24)) if avail else 460)
        self._editing = str((card or {}).get("name") or "")
        self._home = home

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        head = QLabel(f"编辑 {self._editing}" if self._editing else "添加连接器", self)
        head.setObjectName("CapDialogHead")
        box.addWidget(head)

        self.body = QPlainTextEdit(self)
        self.body.setObjectName("CapField")
        self.body.setMinimumHeight(200)
        self.body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.body.setPlainText(self._initial_text(card))
        _style_text(self.body, "json")
        box.addWidget(self.body, 1)

        self._error = QLabel("", self)
        self._error.setObjectName("CapDialogHint")
        self._error.setWordWrap(True)
        self._error.setStyleSheet("color:#d9645e;")
        self._error.setVisible(False)
        box.addWidget(self._error)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.setObjectName("CapGhost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        save = QPushButton("保存", self)
        save.setObjectName("CapSave")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        foot.addWidget(save)
        box.addLayout(foot)

    def _initial_text(self, card: dict | None) -> str:
        name = self._editing
        entry = pet_toolkit.connector_entry(name, home=self._home) if name else {}
        if not entry:
            entry = {"url": "http://127.0.0.1:8080/mcp"}
        return json.dumps({name or "my-mcp-server": entry}, ensure_ascii=False, indent=2) + "\n"

    def _show_error(self, text: str) -> None:
        self._error.setText(text)
        self._error.setVisible(True)
        self.body.setFocus()

    def payload(self) -> dict | None:
        """解析编辑框：只收「一个名字 → 一个对象」，校验与 agent 那份同一套。"""
        try:
            parsed = json.loads(self.body.toPlainText())
        except ValueError as exc:
            self._show_error(f"JSON 解析不了：{exc}")
            return None
        if not isinstance(parsed, dict):
            self._show_error("最外层要是一个对象")
            return None
        if len(parsed) != 1:
            self._show_error(f"一次只写一条：现在有 {len(parsed)} 个名字")
            return None
        name = str(next(iter(parsed)))
        entry = parsed[name]
        if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            self._show_error(f"名字「{name}」只能用字母、数字、下划线、横线")
            return None
        if not isinstance(entry, dict):
            self._show_error(f"「{name}」的值要是一个对象")
            return None
        if not (
            str(entry.get("url") or "").strip() or str(entry.get("command") or "").strip()
        ):
            self._show_error("要么写 url（远程），要么写 command（本机进程）")
            return None
        return {"name": name, "entry": dict(entry), "rename_from": self._editing}

    def _on_save(self) -> None:
        if self.payload() is None:
            return
        self.accept()


def _connector_log_text(name: str, item: dict, runtime: dict, tools: list[dict]) -> str:
    """按 agent 那张日志弹窗的同一份格式拼文本（同源同字段，两边对得上）。"""
    lines = [f"[mcp] connector: {name}"]
    if runtime:
        kind = _runtime_kind(runtime, bool(item.get("enabled")))
        label = _KIND_LABEL.get(kind, kind)
        if isinstance(label, tuple):
            label = label[0]
        lines.append(f"[mcp] state: {kind} ({label})")
        transport = str(runtime.get("transport") or item.get("transport") or "").strip()
        if transport:
            lines.append(f"[mcp] transport: {transport}")
        url = str(runtime.get("url") or item.get("url") or "").strip()
        if url:
            lines.append(f"[mcp] url: {url}")
        else:
            command = str(item.get("command") or "").strip()
            if command:
                argv = [command, *[str(a) for a in (item.get("args") or [])]]
                lines.append("[mcp] command: " + " ".join(argv))
        remote = str(runtime.get("remote_name") or "").strip()
        if remote:
            version = str(runtime.get("remote_version") or "").strip()
            lines.append(f"[mcp] remote: {remote}{' ' + version if version else ''}")
        registered = int(runtime.get("tool_count") or 0)
        if registered > 0:
            lines.append(f"[tools] registered: {registered}")
        stamp = int(runtime.get("last_refresh_ms") or 0)
        if stamp > 0:
            when = datetime.fromtimestamp(stamp / 1000).isoformat(timespec="seconds")
            lines.append(f"[mcp] last_refresh: {when}")
        extra = []
        if int(runtime.get("resource_count") or 0) > 0:
            extra.append(f"resources={int(runtime['resource_count'])}")
        if int(runtime.get("prompt_count") or 0) > 0:
            extra.append(f"prompts={int(runtime['prompt_count'])}")
        if extra:
            lines.append("[mcp] " + " ".join(extra))
        error = str(runtime.get("error") or "").strip()
        if error:
            lines.append(f"[err] {error}")
        last = str(runtime.get("last_error") or "").strip()
        if last and last != error:
            lines.append(f"[err] last: {last}")
    else:
        lines.append("[mcp] state: pending (no runtime snapshot)")
        endpoint = str(item.get("url") or item.get("command") or "").strip()
        if endpoint:
            lines.append(f"[mcp] endpoint: {endpoint}")
    if tools:
        lines.append("[tools] names: " + ", ".join(str(t.get("name") or "") for t in tools))
    return "\n".join(lines) if len(lines) > 1 else ""


class _ConnectorLogsDialog(QDialog):
    """一条连接器的当前状况：和 agent 那边同一份字段、同一份文本。"""

    def __init__(self, parent, name: str, item: dict, runtime: dict, tools: list[dict]) -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(560)
        avail = parent.height() if parent is not None else 0
        self.setFixedHeight(min(520, max(320, avail - 24)) if avail else 420)
        self._text = _connector_log_text(name, item, runtime, tools)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        head = QLabel(f"{name} 的日志", self)
        head.setObjectName("CapDialogHead")
        top.addWidget(head)
        top.addStretch(1)
        self.close_button = QPushButton(self)
        self.close_button.setObjectName("CapAct")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setIcon(QIcon(_rail_pixmap("close", _CODE_FG["punct"])))
        self.close_button.setIconSize(QSize(11, 11))
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.reject)
        top.addWidget(self.close_button)
        box.addLayout(top)

        self.body = QPlainTextEdit(self)
        self.body.setObjectName("CapField")
        self.body.setReadOnly(True)
        self.body.setMinimumHeight(150)
        self.body.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.body.setPlainText(self._text or "还没有可看的记录：引擎没给这一条任何运行态。")
        _style_text(self.body, "log")
        box.addWidget(self.body, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        copy = QPushButton("复制", self)
        copy.setObjectName("CapGhost")
        copy.setCursor(Qt.PointingHandCursor)
        copy.clicked.connect(self._copy)
        foot.addWidget(copy)
        foot.addStretch(1)
        close = QPushButton("关掉", self)
        close.setObjectName("CapSave")
        close.setCursor(Qt.PointingHandCursor)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        box.addLayout(foot)

    def _copy(self) -> None:
        QApplication.clipboard().setText(self._text)


class _SkillViewDialog(QDialog):
    """看一份不属于自己的技能：agent 装的那份只读，改了那边也没了。

    之前这种情形只能弹一句「去 Laji 的技能页」，等于卡上看不到任何内容。
    """

    def __init__(self, parent, item: dict) -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        name = str(item.get("name") or "技能")
        self.setFixedWidth(500)
        avail = parent.height() if parent is not None else 0
        self.setFixedHeight(min(560, max(320, avail - 24)) if avail else 420)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        head = QLabel(name, self)
        head.setObjectName("CapDialogHead")
        top.addWidget(head)
        top.addStretch(1)
        close = QPushButton(self)
        close.setObjectName("CapAct")
        close.setFixedSize(22, 22)
        close.setIcon(QIcon(_rail_pixmap("close", _CODE_FG["punct"])))
        close.setIconSize(QSize(11, 11))
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("关闭")
        close.clicked.connect(self.reject)
        self.close_button = close
        top.addWidget(close)
        box.addLayout(top)

        source = str(item.get("source") or "")
        hint = "全局技能（跟插件一起来的那份），这里只看不能改"
        if source:
            hint += f" · {source}"
        note = QLabel(hint, self)
        note.setObjectName("CapDialogHint")
        note.setWordWrap(True)
        box.addWidget(note)

        body = _markdown_panel(
            pet_toolkit.skill_body(str(item.get("path") or "")) or "这份技能没有正文。",
            self,
        )
        box.addWidget(body, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        done = QPushButton("关掉", self)
        done.setObjectName("CapSave")
        done.setCursor(Qt.PointingHandCursor)
        done.setDefault(True)
        done.clicked.connect(self.accept)
        foot.addWidget(done)
        box.addLayout(foot)


class _McpToolListDialog(QDialog):
    """连接器卡片上那颗 ``+N`` 点开的东西：剩下的几条工具，点一条接着看详情。

    上一版 ``+N`` 是个 ``QLabel``，看着像能点其实点不动。既然工具已经能一条条
    点开，剩下的也应该能翻开，而不是让用户自己去数「还有几条」。
    """

    def __init__(self, parent, tools: list[dict], server: str) -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.picked: dict | None = None
        self.row_count = len(tools)
        self.setFixedWidth(430)
        tall = 78 + 34 * max(1, min(len(tools), 12))
        avail = parent.height() if parent is not None else 0
        self.setFixedHeight(min(tall, max(200, avail - 24)) if avail else tall)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        head = QLabel(f"{server or '这个连接器'}的工具（{len(tools)}）", self)
        head.setObjectName("CapDialogHead")
        top.addWidget(head)
        top.addStretch(1)
        self.close_button = QPushButton(self)
        self.close_button.setObjectName("CapAct")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setIcon(QIcon(_rail_pixmap("close", _CODE_FG["punct"])))
        self.close_button.setIconSize(QSize(11, 11))
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.reject)
        top.addWidget(self.close_button)
        box.addLayout(top)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        holder = QWidget(self._scroll)
        rows = QVBoxLayout(holder)
        rows.setContentsMargins(0, 0, 0, 0)
        rows.setSpacing(4)
        for tool in tools:
            name = str(tool.get("name") or "")
            desc = _clip(str(tool.get("description") or ""), 52)
            row = QPushButton(f"{name}    {desc}" if desc else name, holder)
            row.setObjectName("CapGhost")
            row.setCursor(Qt.PointingHandCursor)
            row.setStyleSheet("text-align:left;padding:7px 12px;")
            row.clicked.connect(lambda _=False, t=tool: self._pick(t))
            rows.addWidget(row)
        rows.addStretch(1)
        self._scroll.setWidget(holder)
        box.addWidget(self._scroll, 1)

    def _pick(self, tool: dict) -> None:
        self.picked = tool
        self.accept()


class _McpToolDetailDialog(QDialog):
    """一条 MCP 工具：说明、参数，以及原始 schema（和 agent 那张弹窗一样两页）。"""

    def __init__(self, parent, tool: dict, server: str) -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        # 高度跟父窗口要：无边框弹窗居中在父窗口里，比它高了底部那颗按钮就被
        # 盖到窗口外面（上一版就是这样，只能按 Esc）。
        avail = parent.height() if parent is not None else 0
        self.setFixedWidth(520)
        self.setFixedHeight(min(600, max(360, avail - 24)) if avail else 560)

        raw_name = str(tool.get("name") or "")
        prefix = f"mcp__{server}__" if server else ""
        local = raw_name[len(prefix) :] if prefix and raw_name.startswith(prefix) else raw_name
        description = str(tool.get("description") or "").strip()
        schema_text = str(tool.get("schema") or "").strip()
        schema = _parse_schema(schema_text)

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(8)

        top = QHBoxLayout()
        top.setSpacing(8)
        head = QLabel(local or "工具", self)
        head.setObjectName("CapDialogHead")
        top.addWidget(head)
        top.addStretch(1)
        self._summary_btn = QPushButton("摘要", self)
        self._summary_btn.setObjectName("CapSeg")
        self._summary_btn.setCheckable(True)
        self._summary_btn.setChecked(True)
        self._summary_btn.setCursor(Qt.PointingHandCursor)
        self._summary_btn.clicked.connect(lambda: self._show("summary"))
        top.addWidget(self._summary_btn)
        self._json_btn = QPushButton("JSON", self)
        self._json_btn.setObjectName("CapSeg")
        self._json_btn.setCheckable(True)
        self._json_btn.setCursor(Qt.PointingHandCursor)
        self._json_btn.clicked.connect(lambda: self._show("json"))
        top.addWidget(self._json_btn)
        # 无边框窗口没有系统标题栏，右上角这个×是唯一的「一眼看见的退路」。
        self.close_button = QPushButton(self)
        self.close_button.setObjectName("CapAct")
        self.close_button.setFixedSize(22, 22)
        self.close_button.setIcon(QIcon(_rail_pixmap("close", _CODE_FG["punct"])))
        self.close_button.setIconSize(QSize(11, 11))
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip("关闭")
        self.close_button.clicked.connect(self.reject)
        top.addWidget(self.close_button)
        box.addLayout(top)

        meta = QLabel(f"来自 {server}  ·  {raw_name}", self)
        meta.setObjectName("CapDialogHint")
        meta.setWordWrap(True)
        box.addWidget(meta)

        self._summary = QWidget(self)
        summary_box = QVBoxLayout(self._summary)
        summary_box.setContentsMargins(0, 0, 0, 0)
        summary_box.setSpacing(6)
        if description:
            said = QLabel(description, self._summary)
            said.setObjectName("CapDialogHint")
            said.setWordWrap(True)
            summary_box.addWidget(said)
        params = _schema_props(schema)
        if params:
            caption = QLabel(f"参数（{len(params)}）", self._summary)
            caption.setObjectName("CapDialogHint")
            summary_box.addWidget(caption)
            self._params = QPlainTextEdit(self._summary)
            self._params.setObjectName("CapField")
            self._params.setReadOnly(True)
            self._params.setMinimumHeight(90)
            self._params.setLineWrapMode(QPlainTextEdit.NoWrap)
            self._params.setPlainText(
                "\n".join(_param_lines(params, schema.get("required") or []))
            )
            _style_text(self._params, "plain")
            summary_box.addWidget(self._params, 1)
        else:
            none = QLabel("这条工具不接参数。", self._summary)
            none.setObjectName("CapDialogHint")
            summary_box.addWidget(none)
        box.addWidget(self._summary, 1)

        self._json = QPlainTextEdit(self)
        self._json.setObjectName("CapField")
        self._json.setReadOnly(True)
        self._json.setMinimumHeight(120)
        self._json.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._json.setPlainText(_pretty_json(schema_text))
        _style_text(self._json, "json")
        self._json.setVisible(False)
        box.addWidget(self._json, 1)

        foot = QHBoxLayout()
        foot.addStretch(1)
        close = QPushButton("关掉", self)
        close.setObjectName("CapSave")
        close.setCursor(Qt.PointingHandCursor)
        close.setDefault(True)
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        box.addLayout(foot)

    def _show(self, view: str) -> None:
        summary = view == "summary"
        self._summary_btn.setChecked(summary)
        self._json_btn.setChecked(not summary)
        self._summary.setVisible(summary)
        self._json.setVisible(not summary)


def _parse_schema(text: str) -> dict:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _pretty_json(text: str) -> str:
    """能格式化就格式化，不能就把原文摆出来 —— 别把唯一一份信息吞掉。"""
    if not text:
        return "{}"
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text


def _schema_props(schema: dict) -> dict:
    props = schema.get("properties") if isinstance(schema, dict) else None
    return props if isinstance(props, dict) else {}


def _param_lines(props: dict, required: list) -> list[str]:
    """一行一个参数：名字、类型、必填与否，说明缩在下一行。"""
    must = {str(v) for v in required if isinstance(v, str)}
    lines = []
    for key, spec in props.items():
        spec = spec if isinstance(spec, dict) else {}
        kind = str(spec.get("type") or "any")
        if kind == "array":
            item = spec.get("items") if isinstance(spec.get("items"), dict) else {}
            kind = f"array<{item.get('type') or 'any'}>"
        head = f"{key}  {kind}" + ("  必填" if key in must else "")
        if spec.get("enum"):
            head += "  ← " + " / ".join(str(v) for v in spec["enum"][:6])
        lines.append(head)
        said = str(spec.get("description") or "").strip()
        if said:
            lines.append(f"    {said}")
    return lines


class _SkillDialog(QDialog):
    """写一份技能：名字 / 一句话描述 / 正文。"""

    def __init__(self, parent=None, item: dict | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CapDialog")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setModal(True)
        self.setFixedWidth(470)
        avail = parent.height() if parent is not None else 0
        self.setFixedHeight(min(560, max(380, avail - 24)) if avail else 470)
        self._editing = str((item or {}).get("name") or "")

        box = QVBoxLayout(self)
        box.setContentsMargins(18, 16, 18, 16)
        box.setSpacing(10)

        head = QLabel("改这份技能" if self._editing else "添加技能", self)
        head.setObjectName("CapDialogHead")
        box.addWidget(head)

        self.name = QLineEdit(self._editing, self)
        self.name.setObjectName("CapField")
        self.name.setPlaceholderText("技能名字，比如 备忘速记")
        box.addWidget(self._labelled("名字", self.name))

        self.description = QLineEdit(str((item or {}).get("description") or ""), self)
        self.description.setObjectName("CapField")
        self.description.setPlaceholderText("一句话说清什么时候用她")
        box.addWidget(self._labelled("什么时候用", self.description))

        self.body = QPlainTextEdit(self)
        self.body.setObjectName("CapField")
        self.body.setPlaceholderText("步骤、注意事项……")
        self.body.setMinimumHeight(140)
        if item and item.get("path"):
            self.body.setPlainText(pet_toolkit.skill_body(str(item.get("path"))))
        # 技能正文本来就是 Markdown，写得出来就该看得见层级。
        _style_text(self.body, "markdown")
        body_box = self._labelled("正文", self.body)
        body_box.setMinimumHeight(180)
        box.addWidget(body_box, 1)

        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addStretch(1)
        cancel = QPushButton("取消", self)
        cancel.setObjectName("CapGhost")
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        foot.addWidget(cancel)
        save = QPushButton("保存", self)
        save.setObjectName("CapSave")
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        foot.addWidget(save)
        box.addLayout(foot)

    def _labelled(self, caption: str, field) -> QWidget:
        holder = QWidget(self)
        lay = QVBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        label = QLabel(caption, holder)
        label.setObjectName("CapDialogHint")
        lay.addWidget(label)
        lay.addWidget(field)
        return holder

    def _on_save(self) -> None:
        if not self.name.text().strip():
            self.name.setFocus()
            return
        self.accept()

    def spec(self) -> dict:
        return {
            "name": self.name.text().strip(),
            "description": self.description.text().strip(),
            "body": self.body.toPlainText().strip(),
            "rename_from": self._editing,
        }


#: 引擎运行态的缓存时长。整页重建会连着问两三回，别每次都去敲引擎的门。
_MCP_RUNTIME_TTL_SECONDS = 3.0
_mcp_runtime_cache: list = [0.0, "", {}, {}]

#: 引擎状态 → 卡片状态词。只保留 ``online`` / ``failed`` / ``off`` 三种可统计的，
#: 其余（还没连、断连、重连中、需要认证）统一是 ``pending``：agent 视图也是这么分的，
def _runtime_kind(runtime: dict, enabled: bool) -> str:
    """一条连接器该显示成什么：跟 agent 视图的 ``runtimeRowStatus`` 一一对应。

    顺序不能变：需要认证优先于 error，error 优先于断连（断着又有报错就是真失败），
    最后看在线或工具数——工具数 > 0 就是在线的强证据（有工具就不可能没连上）。
    """
    if not enabled:
        return "off"
    if not runtime:
        return "pending"
    state = str(runtime.get("state") or "")
    if state == "needs_auth":
        return "pending"
    if runtime.get("error"):
        return "failed"
    if state == "failed":
        return "failed"
    if state == "online" or runtime.get("tool_count"):
        return "online"
    return "pending"


def _forget_mcp_runtime() -> None:
    _mcp_runtime_cache[0] = 0.0
    _mcp_runtime_cache[1] = ""


def _open_daemon():
    """连上引擎；连不上返回 None（宠物单独跑，或者引擎还在起）。"""
    try:
        from .agent_link import daemon_client

        client = daemon_client.LajiDaemonClient(timeout=4.0)
    except Exception:
        log.debug("连接器页：daemon 客户端建不起来", exc_info=True)
        return None
    try:
        if client.connect():
            return client
    except Exception:
        log.debug("连接器页：连不上引擎", exc_info=True)
    try:
        client.close()
    except Exception:
        log.debug("连接器页：关客户端失败", exc_info=True)
    return None


def _mcp_runtime(workspace: str = "") -> tuple[dict[str, dict], dict[str, list[dict]]]:
    """问引擎真实状态与工具：``({name: 运行态}, {name: [{name, description, schema}]})``。

    引擎没起就都空着 —— 配置里开着的条目那时只能说「等待加载」，不能算它挂了。
    ``workspace`` 非空 = 问该工作区自己的连接器清单（``<ws>/.laji/pet-mcp.json``），
    不是 agent 面那份 ``config.toml``。
    """
    stamp, cached_ws, status, tools = _mcp_runtime_cache
    if cached_ws == workspace and time.monotonic() - stamp < _MCP_RUNTIME_TTL_SECONDS:
        return status, tools
    status: dict[str, dict] = {}
    tools: dict[str, list[dict]] = {}
    client = _open_daemon()
    if client is not None:
        try:
            for one in client.list_mcp_servers(workspace_root=workspace):
                status[str(one.get("name") or "")] = one
            for tool in client.list_mcp_tools(workspace_root=workspace):
                tools.setdefault(str(tool.get("server") or ""), []).append(
                    {
                        "name": str(tool.get("name") or ""),
                        "description": str(tool.get("description") or ""),
                        "schema": str(tool.get("schema") or ""),
                    }
                )
        except Exception:
            log.debug("连接器页：问引擎运行态失败", exc_info=True)
            status, tools = {}, {}
        finally:
            try:
                client.close()
            except Exception:
                log.debug("连接器页：关客户端失败", exc_info=True)
    _mcp_runtime_cache[0] = time.monotonic()
    _mcp_runtime_cache[1] = workspace
    _mcp_runtime_cache[2] = status
    _mcp_runtime_cache[3] = tools
    return status, tools


def _tool_chips(tools: list[dict], server: str = "") -> list:
    """工具做成小胶囊；长出来就折成 ``+N``，跟 agent 视图里那一排对齐。

    每个胶囊（包括 ``+N``）都带自己的原始名，点开是同一条工具的「摘要 / JSON」
    详情；``+N`` 点开是剩下那几条的清单，不是一块点不动的灰字。
    """
    if not tools:
        return []
    shown = tools[:3]
    rest = len(tools) - len(shown)
    chips: list = []
    for tool in shown:
        name = str(tool.get("name") or "")
        chips.append(
            {
                "text": name,
                "tip": str(tool.get("description") or name),
                "click": lambda t=tool, s=server: _open_tool_detail(t, s),
            }
        )
    if rest > 0:
        hidden = tools[len(shown) :]
        chips.append(
            {
                "text": f"+{rest}",
                "muted": True,
                "tip": f"还有 {rest} 条工具，点开看全部",
                "click": lambda items=hidden, s=server: _open_tool_list(items, s),
            }
        )
    return chips


def _open_tool_detail(tool: dict, server: str) -> None:
    """点开一条 MCP 工具的说明与参数（agent 那张详情弹窗的同款内容）。"""
    parent = QApplication.activeWindow()
    try:
        _McpToolDetailDialog(parent, tool, server).exec()
    except Exception:
        log.debug("连接器页：打不开工具详情 %s", tool.get("name"), exc_info=True)


def _open_tool_list(tools: list[dict], server: str) -> None:
    """``+N`` 点开：剩下那几条工具的清单，选中一条接着看详情。"""
    parent = QApplication.activeWindow()
    dialog = _McpToolListDialog(parent, tools, server)
    try:
        if dialog.exec() and dialog.picked is not None:
            _open_tool_detail(dialog.picked, server)
    except Exception:
        log.debug("连接器页：打不开工具清单 %s", server, exc_info=True)


def _reload_connector(name: str, authorize: bool = False, workspace: str = "") -> None:
    """让引擎重连这一条。宿主在监听时它自己也会做，这里兜住宠物单独跑的情况。

    ``authorize=True`` 是「连接」那个动作：没连上过的远端条目得带上授权才会
    把授权窗拉起来，光重载发现不出口令。``workspace`` 非空 = 重连那个工作区
    自己那份清单里的条目。
    """
    client = _open_daemon()
    if client is None:
        return
    try:
        client.reload_mcp_server(name, authorize=authorize, workspace_root=workspace)
    except Exception:
        log.debug("连接器页：重连 %s 失败", name, exc_info=True)
    finally:
        try:
            client.close()
        except Exception:
            log.debug("连接器页：关客户端失败", exc_info=True)


class ConnectorsPage(_CapabilityGridPage):
    TITLE = "连接器"
    PAGE_KEY = "connectors"
    UNIT = "个"
    SEARCH = "搜索连接器"
    GEAR_TIP = "连接器设置"

    def __init__(self, bench) -> None:
        super().__init__(bench)

    @property
    def _home(self) -> str:
        """连接器落在这个工作区的 ``.laji/pet-mcp.json``；引擎按同一个路径读。"""
        character = str(getattr(self._win.owner, "character_id", "") or "")
        return pet_toolkit.pet_home(character)

    def _character(self) -> str:
        return str(getattr(self._win.owner, "character_id", "") or "")

    def _items(self) -> list[dict]:
        return pet_toolkit.connectors(self._character(), self._home)

    def menu_items(self) -> list[object]:
        return [
            ("添加连接器…", self._add),
            "-",
            ("刷新状态", self._reload_all),
        ]

    def _reload_all(self) -> None:
        """让引擎把开着的都重连一遍 —— 改了配置、引擎没热重载时的手动那一下。"""
        for item in self._items():
            if item.get("enabled"):
                _reload_connector(str(item.get("name") or ""), workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def cards_spec(self) -> list[dict]:
        status_map, tool_map = _mcp_runtime(self._home)
        out: list[dict] = []
        for item in self._items():
            enabled = bool(item.get("enabled"))
            name = str(item.get("name") or "")
            runtime = status_map.get(name) or {}
            kind = _runtime_kind(runtime, enabled)
            detail = str(item.get("detail") or "") or "还没有写地址"
            error = str(runtime.get("error") or "") or str(runtime.get("last_error") or "")
            if kind == "failed" and error:
                detail = error
            chips = _tool_chips(tool_map.get(name, []), name) or [
                str(item.get("transport") or "stdio")
            ]
            out.append(
                {
                    "name": name,
                    "kind": kind,
                    "desc": detail,
                    "chips": chips,
                    "foot": self._foot(name, kind, item, runtime, tool_map.get(name, [])),
                    "open": lambda target=name: self._edit(target),
                    "on": enabled,
                    "toggle": lambda on, target=name: self._toggle(target, bool(on)),
                    "edit": lambda target=name: self._edit(target),
                    "remove": lambda target=name: self._remove(target),
                }
            )
        return out

    def _foot(
        self, name: str, kind: str, item: dict, runtime: dict, tools: list[dict]
    ) -> list[tuple[str, object]]:
        """卡片底下那排链接 —— 和 agent 卡一个顺序：连接/重连、登出、查看日志。"""
        links: list[tuple[str, object]] = []
        if item.get("enabled"):
            if kind == "online":
                links.append(("重连", lambda target=name: self._reload(target)))
            else:
                links.append(("连接", lambda target=name: self._connect(target)))
            if kind == "online" and str(item.get("transport") or "") == "http":
                links.append(("登出", lambda target=name: self._logout(target)))
        links.append(
            (
                "查看日志",
                lambda target=name, it=item, rt=runtime, tl=tools: self._logs(target, it, rt, tl),
            )
        )
        return links

    def _connect(self, name: str) -> None:
        """「连接」：重连并走一次授权，失败也刷新回来把错因摆到卡片上。"""
        _reload_connector(name, authorize=True, workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def _reload(self, name: str) -> None:
        _reload_connector(name, workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def _logout(self, name: str) -> None:
        client = _open_daemon()
        if client is None:
            return
        try:
            client.logout_mcp_server(name, workspace_root=self._home)
        except Exception:
            log.debug("连接器页：登出 %s 失败", name, exc_info=True)
        finally:
            try:
                client.close()
            except Exception:
                log.debug("连接器页：关客户端失败", exc_info=True)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def _logs(self, name: str, item: dict, runtime: dict, tools: list[dict]) -> None:
        _ConnectorLogsDialog(self, name, item, runtime, tools).exec()

    def _toggle(self, name: str, enabled: bool) -> None:
        if not pet_toolkit.set_connector_enabled(name, enabled, self._character(), self._home):
            log.debug("连接器页：%s 开关没写进去", name)
            return
        if enabled:
            _reload_connector(name, workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def _add(self) -> None:
        self._open_dialog(None)

    def _edit(self, name: str) -> None:
        for item in self._items():
            if str(item.get("name") or "") == name:
                self._open_dialog(item)
                return

    def _open_dialog(self, card: dict | None) -> None:
        dialog = _ConnectorDialog(self, card, home=self._home)
        if dialog.exec() != QDialog.Accepted:
            return
        payload = dialog.payload()
        if payload is None:
            return
        ok = pet_toolkit.save_connector_entry(
            payload["name"],
            payload["entry"],
            rename_from=payload["rename_from"],
            character=self._character(),
            home=self._home,
        )
        if not ok:
            log.debug("连接器页：%s 没写进去", payload["name"])
        _reload_connector(payload["name"], workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def _remove(self, name: str) -> None:
        answer = QMessageBox.question(
            self,
            "删掉连接器",
            f"从她的连接器清单里删掉「{name}」？\nagent 视图那份不动。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        pet_toolkit.remove_connector(name, self._character(), self._home)
        _reload_connector(name, workspace=self._home)
        _forget_mcp_runtime()
        self.refresh()
        self._bench.refresh_counts()

    def empty_text(self) -> str:
        return "暂无数据"


class SkillsPage(_CapabilityGridPage):
    TITLE = "技能"
    UNIT = "个"
    SEARCH = "搜索技能"
    PAGE_KEY = "skills"
    GEAR_TIP = "技能设置"

    def menu_items(self) -> list[object]:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        return [
            ("添加技能…", self._add),
            "-",
            ("打开技能目录", lambda: _open_folder(pet_toolkit.skills_root(character))),
        ]

    def cards_spec(self) -> list[dict]:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        out: list[dict] = []
        for item in pet_toolkit.skills(character):
            enabled = bool(item.get("enabled"))
            name = str(item.get("name") or "")
            source = str(item.get("source") or "")
            scope = "她家" if item.get("scope") == "workspace" else "全局"
            out.append(
                {
                    "name": name,
                    "kind": "online" if enabled else "off",
                    "desc": str(item.get("description") or "") or "暂无数据",
                    "chips": [scope] + ([source] if source else []),
                    "open": lambda target=name: self._preview(target),
                    "on": enabled,
                    "toggle": lambda on, target=name: self._toggle(target, bool(on)),
                    "edit": lambda target=name: self._edit(target),
                    "remove": lambda target=name: self._remove(target),
                }
            )
        return out

    def _toggle(self, name: str, enabled: bool) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        pet_toolkit.set_skill_enabled(name, enabled, character)
        self.refresh()
        self._bench.refresh_counts()

    def _add(self) -> None:
        self._open_dialog(None)

    def _preview(self, name: str) -> None:
        """看正文：不分「她家」还是「全局」，让每张卡都能点开内容。"""
        character = str(getattr(self._win.owner, "character_id", "") or "")
        for item in pet_toolkit.skills(character):
            if str(item.get("name") or "") == name:
                _SkillViewDialog(self, item).exec()
                return

    def _edit(self, name: str) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        for item in pet_toolkit.skills(character):
            if str(item.get("name") or "") != name:
                continue
            if item.get("scope") != "workspace":
                # 全局技能不能改，但至少得能看：铅笔图标总得点开东西。
                _SkillViewDialog(self, item).exec()
                return
            self._open_dialog(item)
            return

    def _open_dialog(self, item: dict | None) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        dialog = _SkillDialog(self, item)
        if dialog.exec() != QDialog.Accepted:
            return
        spec = dialog.spec()
        if not pet_toolkit.save_skill(
            spec["name"],
            description=spec["description"],
            body=spec["body"],
            rename_from=spec["rename_from"],
            character=character,
        ):
            log.debug("技能页：%s 没写进去", spec["name"])
        self.refresh()
        self._bench.refresh_counts()

    def _remove(self, name: str) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        scope = next(
            (
                item.get("scope")
                for item in pet_toolkit.skills(character)
                if str(item.get("name") or "") == name
            ),
            "workspace",
        )
        if scope != "workspace":
            QMessageBox.information(
                self,
                "全局技能",
                f"「{name}」是 agent 装的全局技能，删了那边也没了。\n"
                "只想让她别用：把开关关掉就行。",
            )
            return
        answer = QMessageBox.question(
            self,
            "删掉技能",
            f"把「{name}」从她家删掉？\nSKILL.md 和整个目录一起删，删了不能恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        pet_toolkit.remove_skill(name, character)
        self.refresh()
        self._bench.refresh_counts()

    def empty_text(self) -> str:
        return "暂无数据"


_CONTRIB_META: dict[str, tuple[str, str, str]] = {
    "skill": ("技", "技能", "随包安装，装完就能在技能里用"),
    "expert": ("专", "专家", "装完多出一个可以对话的专家"),
    "rule": ("规", "规则", "常驻在提示里的行为约束"),
    "contextLayer": ("层", "上下文层", "按需注入的上下文片段"),
    "mcp": ("连", "连接器", "注册成一个可调用的 MCP 服务"),
    "workbench": ("坊", "创意工坊", "带自己的界面，装完出现在工坊里"),
    "skin": ("肤", "皮肤", "换掉这一身装扮"),
    "intro": ("启", "启动动画", "启动时先播的一段"),
    "app": ("程", "程序", "由宿主拉起的独立进程"),
    "tool": ("具", "工具", "模型工具箱里多出来的那几只"),
}
_MARKDOWN_CONTRIB = frozenset({"skill", "expert", "rule", "contextLayer"})


def _contribution_preview(kind: str, body: str, parent: QWidget | None = None) -> QWidget:
    """包详情的一条贡献正文：Markdown 类排版，配置/代码类照旧给源码（带高亮）。"""
    if kind in _MARKDOWN_CONTRIB:
        return _markdown_panel(body, parent, "PackMd")
    text = QPlainTextEdit(parent)
    text.setObjectName("PackBody")
    text.setReadOnly(True)
    text.setPlainText(body)
    _style_text(text, "auto")
    return text


_CONTRIB_ORDER = (
    "skill",
    "expert",
    "rule",
    "contextLayer",
    "mcp",
    "workbench",
    "skin",
    "intro",
    "app",
    "tool",
)


class PackDetailSheet(QWidget):
    """包详情：点工坊卡片弹出来，信息和 agent 的插件详情弹层对齐。"""

    WIDTH = 560

    def __init__(self, page, pack_id: str) -> None:
        super().__init__(page)
        self._page = page
        self._win = page._win
        self._pack_id = pack_id
        self._busy = False
        self._view: tuple[str, str, str] | None = None
        self._primary: QPushButton | None = None
        self.setObjectName("PackScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card = QFrame(self)
        self._card.setObjectName("PackSheet")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._card.setFixedWidth(self.WIDTH)
        self._body = QVBoxLayout(self._card)
        self._body.setContentsMargins(20, 18, 20, 16)
        self._body.setSpacing(12)
        shell = QVBoxLayout(self)
        shell.setContentsMargins(24, 24, 24, 24)
        shell.addStretch(1)
        mid = QHBoxLayout()
        mid.addStretch(1)
        mid.addWidget(self._card, 0, Qt.AlignTop)
        mid.addStretch(1)
        shell.addLayout(mid)
        shell.addStretch(1)
        self._build()
        page.installEventFilter(self)

    # ---- 布局跟随 ----
    def eventFilter(self, obj, event) -> bool:
        if obj is self._page and event.type() == QEvent.Type.Resize:
            self.setGeometry(self._page.rect())
        return super().eventFilter(obj, event)

    def showEvent(self, event) -> None:
        self.setGeometry(self._page.rect())
        super().showEvent(event)
        self.raise_()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and not self._busy:
            self.close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if not self._busy and not self._card.geometry().contains(event.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        self._page.removeEventFilter(self)
        super().closeEvent(event)

    # ---- 内容 ----
    def _clear(self) -> None:
        while self._body.count():
            item = self._body.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先摘离再 deleteLater：延迟删除生效前旧内容不能还留在屏上。
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop(item.layout())

    def _drop(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._drop(item.layout())

    def _find(self) -> dict:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        try:
            for item in pet_toolkit.workshop_packs(character):
                if str(item.get("id") or "") == self._pack_id:
                    return item
        except Exception:
            log.debug("包详情：读不到 %s", self._pack_id, exc_info=True)
        return {}

    def _build(self) -> None:
        self._clear()
        item = self._find()
        folder = str(item.get("path") or "")
        name = str(item.get("name") or self._pack_id)
        version = str(item.get("version") or "")
        installed = bool(item.get("installed"))

        hero = QHBoxLayout()
        hero.setSpacing(12)
        icon = QLabel(name[:1].upper(), self._card)
        icon.setFixedSize(44, 44)
        icon.setAlignment(Qt.AlignCenter)
        color = QColor.fromHsl(_name_hue(name), 135, 120)
        icon.setStyleSheet(
            f"background:{color.name()};color:#fff;border-radius:11px;"
            "font-size:18px;font-weight:700;"
        )
        hero.addWidget(icon, 0, Qt.AlignTop)
        titles = QVBoxLayout()
        titles.setSpacing(3)
        title = QLabel(name, self._card)
        title.setObjectName("PackName")
        title.setWordWrap(True)
        bits = [self._pack_id, f"v{version}" if version else "", "内置" if item.get("bundled") else ""]
        meta = QLabel(" · ".join(bit for bit in bits if bit), self._card)
        meta.setObjectName("PackMeta")
        titles.addWidget(title)
        titles.addWidget(meta)
        hero.addLayout(titles, 1)
        close = QPushButton("×", self._card)
        close.setObjectName("CapAct")
        close.setFixedSize(22, 22)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("关闭")
        close.clicked.connect(self.close)
        hero.addWidget(close, 0, Qt.AlignTop)
        self._body.addLayout(hero)

        desc = QLabel(str(item.get("description") or "") or "暂无说明", self._card)
        desc.setObjectName("PackDesc")
        desc.setWordWrap(True)
        self._body.addWidget(desc)

        contributions: list[dict] = []
        if folder:
            try:
                contributions = pet_toolkit.pack_contributions(folder)
            except Exception:
                log.debug("包详情：读不到贡献 %s", folder, exc_info=True)
        if self._view is not None:
            self._build_contribution_view(folder, *self._view)
        elif contributions:
            for kind in _CONTRIB_ORDER:
                group = [one for one in contributions if one["kind"] == kind]
                if not group:
                    continue
                glyph, label, _note = _CONTRIB_META.get(kind, ("件", kind, ""))
                head = QLabel(f"{label} · {len(group)}", self._card)
                head.setObjectName("PackGroup")
                self._body.addWidget(head)
                for one in group:
                    self._body.addWidget(self._contrib_row(one))
        else:
            none = QLabel("这个包不附带技能、规则或界面，只提供一条能力声明。", self._card)
            none.setObjectName("PackDesc")
            none.setWordWrap(True)
            self._body.addWidget(none)

        actions = QHBoxLayout()
        actions.addStretch(1)
        if installed:
            button = QPushButton("卸载", self._card)
            button.setObjectName("PackDanger")
            button.clicked.connect(lambda: self._run("uninstall"))
        else:
            button = QPushButton("装进来", self._card)
            button.setObjectName("PackPrimary")
            button.clicked.connect(lambda: self._run("install"))
        button.setCursor(Qt.PointingHandCursor)
        button.setEnabled(not self._busy)
        self._primary = button
        actions.addWidget(button)
        self._body.addSpacing(2)
        self._body.addLayout(actions)

    # ---- 贡献条目 ----
    def _contrib_row(self, one: dict) -> QFrame:
        kind = str(one.get("kind") or "")
        glyph, label, note = _CONTRIB_META.get(kind, ("件", kind, ""))
        row = _CapTile(self._card, lambda: self._open_contribution(one))
        row.setObjectName("PackItem")
        box = QHBoxLayout(row)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(9)
        mark = QLabel(glyph, row)
        mark.setObjectName("PackItemMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(22, 22)
        box.addWidget(mark, 0, Qt.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(2)
        head = QHBoxLayout()
        head.setSpacing(6)
        name = QLabel(str(one.get("name") or ""), row)
        name.setObjectName("PackItemName")
        head.addWidget(name)
        badge = QLabel(label, row)
        badge.setObjectName("PackItemKind")
        head.addWidget(badge)
        head.addStretch(1)
        column.addLayout(head)
        blurb = QLabel(str(one.get("description") or "") or note, row)
        blurb.setObjectName("PackItemDesc")
        blurb.setWordWrap(True)
        column.addWidget(blurb)
        box.addLayout(column, 1)
        return row

    def _open_contribution(self, one: dict) -> None:
        self._view = (
            str(one.get("kind") or ""),
            str(one.get("name") or ""),
            str(one.get("ref") or ""),
        )
        self._build()

    def _back(self) -> None:
        self._view = None
        self._build()

    def _build_contribution_view(self, folder: str, kind: str, name: str, ref: str) -> None:
        try:
            detail = pet_toolkit.read_contribution(folder, kind, name, ref)
        except Exception:
            log.debug("包详情：读不到条文 %s %s", kind, name, exc_info=True)
            detail = {"title": name, "meta": [], "body": ""}
        back = QPushButton("← 返回", self._card)
        back.setObjectName("CapAct")
        back.setFixedHeight(22)
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(self._back)
        head = QHBoxLayout()
        head.addWidget(back, 0, Qt.AlignLeft)
        head.addStretch(1)
        self._body.addLayout(head)
        title = QLabel(str(detail.get("title") or name), self._card)
        title.setObjectName("PackName")
        title.setWordWrap(True)
        self._body.addWidget(title)
        meta = " · ".join(str(bit) for bit in (detail.get("meta") or []) if bit)
        if meta:
            meta_label = QLabel(meta, self._card)
            meta_label.setObjectName("PackMeta")
            meta_label.setWordWrap(True)
            self._body.addWidget(meta_label)
        text = _contribution_preview(
            kind, str(detail.get("body") or "这里没有可预览的内容。"), self._card
        )
        text.setMinimumHeight(230)
        self._body.addWidget(text, 1)

    # ---- 动作 ----
    def _run(self, kind: str) -> None:
        if self._busy or self._primary is None:
            return
        self._busy = True
        self._primary.setEnabled(False)
        self._primary.setText("正在装…" if kind == "install" else "正在卸…")
        # 先把按钮的忙态画出来，再去碰磁盘。
        QTimer.singleShot(60, lambda: self._apply(kind))

    def _apply(self, kind: str) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        try:
            if kind == "install":
                ok = pet_toolkit.install_pack(self._pack_id, character)
            else:
                ok = pet_toolkit.uninstall_pack(self._pack_id, character)
        except Exception:
            log.debug("包详情：%s 失败 %s", kind, self._pack_id, exc_info=True)
            ok = False
        if not ok:
            self._busy = False
            if self._primary is not None:
                self._primary.setEnabled(True)
                self._primary.setText("没成功，再试一次")
            return
        # 本地复制就几十毫秒，给个看得见的停留，否则跟“一下就完了”没区别。
        QTimer.singleShot(420, self._done)

    def _done(self) -> None:
        self._busy = False
        self._page.refresh()
        self._page._bench.refresh_counts()
        self._build()


class WorkshopPage(_CapabilityGridPage):
    TITLE = "创意工坊"
    UNIT = "个"
    SEARCH = "搜索能力包"
    GEAR_TIP = "工坊设置"
    FILTERS = (("all", "全部"), ("online", "已装"), ("off", "未装"))
    #: 工坊的卡片 kind 是 installed / available，跟连接器那套词不一样。
    BUCKETS = {"online": ("installed",), "off": ("available",)}

    def menu_items(self) -> list[object]:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        return [
            ("导入已装能力包…", self._import_agent),
            ("打开插件目录", lambda: _open_folder(pet_toolkit.packs_root(character))),
        ]

    def _import_agent(self) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        try:
            added = pet_toolkit.import_packs_from_agent(character)
        except Exception:
            log.debug("工坊页：导入已装能力包失败", exc_info=True)
            return
        if not added:
            QMessageBox.information(
                self,
                "导入已装能力包",
                "没有她还没装的能力包。这一步只复制一次，之后各自独立。",
            )
        self.refresh()
        self._bench.refresh_counts()

    def cards_spec(self) -> list[dict]:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        out: list[dict] = []
        for item in pet_toolkit.workshop_packs(character):
            pack_id = str(item.get("id") or "")
            version = str(item.get("version") or "")
            skills = int(item.get("skills") or 0)
            mcp = int(item.get("mcp") or 0)
            installed = bool(item.get("installed"))
            # 描述优先用 manifest 里那句人话，没有才退回“N 个技能”。
            desc = str(item.get("description") or "") or "、".join(
                bit for bit in (f"{skills} 个技能" if skills else "", f"{mcp} 个连接器" if mcp else "") if bit
            )
            chips: list[object] = []
            if pack_id:
                chips.append((pack_id, True))
            if version:
                chips.append(f"v{version}")
            if item.get("bundled"):
                chips.append("内置")
            busy = pack_id in getattr(self, "_installing", set())
            detail = lambda pid=pack_id: self._open_sheet(pid)  # noqa: E731
            install = lambda pid=pack_id: self._install_pack(pid)  # noqa: E731
            if busy:
                action: tuple = ("…", "正在装", False, None)
            elif installed:
                action = ("√", "看看这个包", True, detail)
            else:
                action = ("+", "装进来", False, install)
            out.append(
                {
                    "name": str(item.get("name") or ""),
                    "kind": "installed" if installed else "available",
                    "show_kind": False,
                    "desc": desc or "暂无说明",
                    "chips": chips,
                    "action": action,
                    "busy": busy,
                    # 整张卡可点：打开详情（agent 那边也是点卡片看包里的东西）。
                    "open": None if busy else detail,
                }
            )
        return out

    def _open_sheet(self, pack_id: str) -> None:
        if not pack_id:
            return
        sheet = getattr(self, "_sheet", None)
        if sheet is not None:
            sheet.close()
        sheet = PackDetailSheet(self, pack_id)
        self._sheet = sheet
        sheet.show()

    def _install_pack(self, pack_id: str) -> None:
        """卡片右上＋：先上忙态，再落盘，跟详情弹层的按钮同一套节奏。"""
        if not hasattr(self, "_installing"):
            self._installing = set()
        if not pack_id or pack_id in self._installing:
            return
        self._installing.add(pack_id)
        self.refresh()
        QTimer.singleShot(60, lambda: self._apply_install(pack_id))

    def _apply_install(self, pack_id: str) -> None:
        character = str(getattr(self._win.owner, "character_id", "") or "")
        try:
            ok = pet_toolkit.install_pack(pack_id, character)
        except Exception:
            log.debug("工坊页：装能力包失败 %s", pack_id, exc_info=True)
            ok = False
        if ok:
            self._reload_pack_connectors(pack_id, character)
        # 本地复制就几十毫秒，给个看得见的停留，否则跟“一下就完了”没区别。
        QTimer.singleShot(420, lambda: self._finish_install(pack_id, ok))

    def _reload_pack_connectors(self, pack_id: str, character: str) -> None:
        """装完就让引擎重连一次它刚拿到的连接器。

        宿主开着时会监听 ``mcp-custom.json`` 自己热重载；宿主不在（宠物单独跑）
        就没人替我们做了，而她能不能动手完全取决于引擎那边有没有这个 server。
        失败静默：装包本身已经成功了，重连不上只影响“马上”能不能用。
        """
        home = pet_toolkit.pet_home(character)
        folder = os.path.join(home, "plugins", pack_id) if home else ""
        if not folder or not os.path.isdir(folder):
            return
        try:
            names = [
                str(row.get("name") or "")
                for row in pet_toolkit.pack_contributions(folder)
                if str(row.get("kind") or "") == "mcp"
            ]
        except Exception:
            log.debug("工坊页：读连接器声明失败 %s", pack_id, exc_info=True)
            return
        names = [name for name in names if name]
        if not names:
            return
        from .agent_link import daemon_client

        try:
            client = daemon_client.LajiDaemonClient()
        except Exception:
            log.debug("工坊页：daemon 客户端建不起来", exc_info=True)
            return
        try:
            if not client.connect():
                return
            for name in names:
                client.reload_mcp_server(name)
        except Exception:
            log.debug("工坊页：连接器重连失败 %s", pack_id, exc_info=True)
        finally:
            try:
                client.close()
            except Exception:
                log.debug("工坊页：关客户端失败", exc_info=True)

    def _finish_install(self, pack_id: str, ok: bool) -> None:
        self._installing.discard(pack_id)
        if not ok:
            QMessageBox.information(self, "装进来", f"没能装上「{pack_id}」。")
        self.refresh()
        self._bench.refresh_counts()

    def empty_text(self) -> str:
        return "暂无数据"


def _open_folder(path: str) -> None:
    """打开能力包目录（不存在就什么也不做）。"""
    if path and os.path.isdir(path):
        try:
            os.startfile(path)  # noqa: S606 - Windows 上打开资源管理器
        except OSError:
            log.debug("打开目录失败: %s", path, exc_info=True)



class SessionsPage(_CapabilityPage):
    TITLE = "她的会话"

    def empty_text(self) -> str:
        return "暂无数据"

    def rows_spec(self):
        store = getattr(self._win.owner, "store", None)
        character = str(getattr(self._win.owner, "character_id", "") or "")
        if store is None or not character:
            return []
        try:
            sessions = list(store.list(character) or [])
        except Exception:
            log.debug("她的会话：读列表失败", exc_info=True)
            return []
        out = []
        for session in sessions[:20]:
            session_id = str(getattr(session, "session_id", "") or "")
            if not session_id:
                continue
            stamp = _session_stamp(session)
            snippet = _session_snippet(session)
            meta = f"{stamp} · {snippet}" if stamp and snippet else (snippet or stamp)
            out.append(
                (
                    _session_title(session),
                    meta,
                    "",
                    [("继续聊", lambda sid=session_id: self._open(sid))],
                )
            )
        return out

    def _open(self, session_id: str) -> None:
        messages = getattr(self._win, "messages", None)
        try:
            self._win.select(0)
            messages.refresh_sessions()
            messages.focus_session(session_id)
        except Exception:
            log.debug("她的会话：切不过去", exc_info=True)


RAIL_ITEMS = (
    ("messages", "消息", "msg"),
    ("approvals", "待办", "check"),
    ("bench", "工作台", "grid"),
)

# 主题跟着人走：窗口关掉再开还是上回那套（不进配置，重开会回默认）。
_LAST_THEME = {"key": THEMES[0][0]}


class WorkstationWindow(QFrame):
    """企微式的三栏窗口：图标条选页，右边整个给当前页。

    ``owner`` 是 ``QuickChatBubble``：会话、服务、壳上入口全从它拿。
    窗口只记两样自己的东西——主题和待批表（后者上游本来就有）。
    """

    # 开 / 关要说一声：待批只有一个入口，工位开着时它在左栏页，关掉就回到
    # 她头顶那枚徽章（见 ``overlay_shell._refresh_approval_views``）。
    visibilityChanged = Signal(bool)

    def __init__(self, owner, parent=None) -> None:
        super().__init__(parent)
        self.owner = owner
        self.approvals: dict[str, dict] = {}
        # 皮肤和置顶都记在配置里：关掉再开还是上次那套，别每次回到默认。
        saved_theme = str(self._remembered("workstation_theme", "") or "")
        self._theme_key = saved_theme if saved_theme in {e[0] for e in THEMES} else _LAST_THEME["key"]
        self._colors = _theme(self._theme_key)[2]
        self.buttons: dict[str, QToolButton] = {}
        self._pet = None
        self._pet_docked = False
        self._pet_home: QRect | None = None
        # overlay 拓扑：她是一只 sprite，不是窗；格子里那格只是会动的预览。
        # 地扔到槽位附近就自动收回：按拍看她的身体框与槽位是否重叠，比盯 mouseRelease
        # 可靠（她的拖放会经过物理/贴边，释放点不等于落点）。
        self._dock_watch = QTimer(self)
        self._dock_watch.setInterval(160)
        self._dock_watch.timeout.connect(self._watch_return)
        # 正常应用窗：标题栏、边框、任务栏、Alt+Tab、最小化全归窗口管理器。
        # 之前是 Tool + 无边框自绘标题栏，看着像一块浮在桌面上的弹框，也进不了任务栏。
        self.setWindowTitle("小工位")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        # 有系统边框就不再铺透明底：透明会让标题栏和四角透出背后的桌面。
        self.setMinimumSize(760, 460)
        self.resize(WIN_W, WIN_H)
        self._build()
        self.apply_theme(self._theme_key)
        self._on_top = bool(self._remembered("workstation_on_top", False))
        if self._on_top:
            # flag 要在第一次 show 之前就位，否则会先弹到后面再跳上来。
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    # -- 骨架 ---------------------------------------------------------------
    def _build(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        rail = QWidget(self)
        rail.setObjectName("wsRail")
        rail.setFixedWidth(RAIL_W)
        self.rail = rail
        column = QVBoxLayout(rail)
        column.setContentsMargins(5, 8, 5, 8)
        column.setSpacing(6)

        # 原型左上角就是她本人：这里演她 idle 的逐帧，静态图看着像遗照。
        self.avatar = LivePetView(rail, mode="figure")
        self.avatar.setToolTip("她的工位")
        self.avatar.clicked.connect(self._on_pet_clicked)
        column.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(2)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, label, _kind) in enumerate(RAIL_ITEMS):
            button = QToolButton(rail)
            button.setObjectName("Rail")
            button.setText(label)
            button.setToolTip(label)
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setIconSize(QSize(26, 26))
            button.setCheckable(True)
            button.setFixedSize(56, 58)
            button.clicked.connect(lambda _=False, i=index: self.select(i))
            group.addButton(button, index)
            column.addWidget(button, 0, Qt.AlignmentFlag.AlignHCenter)
            self.buttons[key] = button
        column.addStretch(1)

        # 设置收在左栏底部那颗齿轮里：皮肤和「她本人」都在它弹出来的菜单里。
        self.gear = QToolButton(rail)
        self.gear.setObjectName("Rail")
        self.gear.setText("设置")
        self.gear.setToolTip("设置")
        self.gear.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.gear.setIconSize(QSize(26, 26))
        self.gear.setFixedSize(56, 58)
        self.gear.setCursor(Qt.CursorShape.PointingHandCursor)
        self.gear.clicked.connect(self._open_settings_menu)
        column.addWidget(self.gear, 0, Qt.AlignmentFlag.AlignHCenter)

        self.stack = QStackedWidget(self)
        self.messages = MessagesPage(self)
        self.approvals_page = ApprovalsPage(self)
        self.bench = BenchPage(self)
        for page in (self.messages, self.approvals_page, self.bench):
            self.stack.addWidget(page)

        root.addWidget(rail)
        root.addWidget(self.stack, 1)

        self.select(0)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 口
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        # 圆角交给系统边框（Windows 11 自带）：自己再切角会露出背后的桌面。
        path.addRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        painter.fillPath(path, _rgba(self._colors["shell"]))
        painter.setPen(QPen(_rgba(self._colors["line"]), 1))
        painter.drawPath(path)
        # 磨砂玻璃：顶亮一点、底暗一点，另加一条极淡高光（纯色块看起来是平板）。
        base = QColor(self._colors["shell"])
        glass = QLinearGradient(0, 0, 0, self.height())
        glass.setColorAt(0.0, base.lighter(114))
        glass.setColorAt(0.55, base)
        glass.setColorAt(1.0, base.darker(106))
        painter.fillPath(path, QBrush(glass))
        painter.setPen(QPen(_veil(20, self._colors), 1))
        painter.drawLine(QPointF(14, 1.5), QPointF(self.width() - 14, 1.5))
        painter.end()

    # -- 主题与角标 ---------------------------------------------------------
    def apply_theme(self, key: str) -> None:
        _, _, colors = _theme(key)
        self._theme_key = key
        self._colors = colors
        global _ACTIVE_COLORS
        _ACTIVE_COLORS = colors
        _LAST_THEME["key"] = key
        self.setStyleSheet(_qss(colors))
        self._refresh_rail_icons()
        self._refresh_gear_icon()
        self._refresh_avatar()
        # 气泡颜色是写进富文档 HTML 里的，换肤得重画一遍文档才会跟着变。
        flow = getattr(self, "messages", None)
        if flow is not None:
            flow.render_flow()
        self.update()
        self._remember("workstation_theme", key)

    # -- 设置项背靠的配置 ---------------------------------------------------
    def _remembered(self, key: str, default):
        """读窗口记着的值。配置拿不到就认默认，绝不让设置页因为读不到而起不来。"""
        config = getattr(self.owner, "config", None)
        getter = getattr(config, "get", None)
        if not callable(getter):
            return default
        try:
            value = getter(key, default)
        except Exception:
            log.debug("工作台：读不了配置 %s", key, exc_info=True)
            return default
        return default if value is None else value

    def _remember(self, key: str, value) -> None:
        setter = getattr(getattr(self.owner, "config", None), "set", None)
        if not callable(setter):
            return
        try:
            setter(key, value)
        except Exception:
            log.debug("工作台：存不下配置 %s", key, exc_info=True)

    def is_on_top(self) -> bool:
        return bool(getattr(self, "_on_top", False))

    def set_on_top(self, on: bool) -> None:
        """置顶开关。改 flag 在 Windows 上会重走一次 show，所以位置尺寸自己接住。"""
        self._on_top = bool(on)
        if self.isVisible():
            spot = self.geometry()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._on_top)
            self.show()
            self.setGeometry(spot)
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self._on_top)
        self._remember("workstation_on_top", self._on_top)

    def reset_geometry(self) -> None:
        """回到默认尺寸和贴右停靠的位置。"""
        self.resize(WIN_W, WIN_H)
        self._place()

    def open_settings(self) -> None:
        """齿轮：窗口自己的设置（外观 / 模型 / 窗口行为）。"""
        _WsSettingsDialog(self).exec()

    def _open_settings_menu(self) -> None:
        """旧名字：齿轮的 clicked 还接着它，留个转发，不为改名动信号连接。"""
        self.open_settings()

    def _refresh_gear_icon(self) -> None:
        gear = getattr(self, "gear", None)
        if gear is None:
            return
        gear.setIcon(QIcon(_rail_pixmap("gear", self._colors["fg2"])))

    def _refresh_avatar(self) -> None:
        avatar = getattr(self, "avatar", None)
        if avatar is None:
            return
        who = str(getattr(self.owner, "character_id", "") or "shenshen")
        avatar.set_ring(self._colors["acc"])
        avatar.set_character(who)

    def cycle_theme(self) -> None:
        keys = [entry[0] for entry in THEMES]
        index = keys.index(self._theme_key) if self._theme_key in keys else -1
        self.apply_theme(keys[(index + 1) % len(keys)])

    def _refresh_rail_icons(self) -> None:
        for key, _label, kind in RAIL_ITEMS:
            button = self.buttons.get(key)
            if button is None:
                continue
            # 未选中也要看得清：用不透明的次级前景（dim2 只有 41% 白）。
            color = self._colors["acc"] if button.isChecked() else self._colors["fg2"]
            badge = len(self.approvals) if key == "approvals" else 0
            button.setIcon(QIcon(_rail_pixmap(kind, color, badge)))

    # -- 页切换 -------------------------------------------------------------
    def select(self, index: int) -> None:
        index = max(0, min(index, self.stack.count() - 1))
        self.stack.setCurrentIndex(index)
        key = RAIL_ITEMS[index][0]
        button = self.buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)
        self._refresh_rail_icons()
        if index == 0:
            self.messages.refresh_sessions()
        elif index == 1:
            self.approvals_page.rebuild()
        elif index == 2:
            # 点左栏「工作台」本身也算回工作台：停在连接器/技能那种子页时一键退回首页。
            self.bench.show_home()

    def present(self) -> None:
        self.messages.refresh_sessions()
        self.approvals_page.rebuild()
        self._place()
        # 最小化过的窗被任务栏/气泡再叫出来：先还原，否则 show() 只是闪一下任务栏。
        if self.isMinimized():
            self.showNormal()
        self.show()
        self._make_room()
        self.dock_pet()
        self.raise_()
        self.activateWindow()

    # -- 把她收进左上角 / 抽出来 ---------------------------------------------
    def slot_global_rect(self) -> QRect:
        """左上角那一格在屏幕上的位置（她回去的落点、气泡的锚点都是它）。"""
        return QRect(self.avatar.mapToGlobal(QPoint(0, 0)), self.avatar.size())

    def _show_empty_slot(self) -> None:
        """把这一格摆回“她不在座上”：虚线空位 + 她的首字。

        收起失败的分支必须调它，而不是 `set_equipped(True)`：`True` 表示她真的在格子里，
        而那时 `_pet`/`_pet_docked` 都没记下东西，`undock_pet()` 会在 `window is None`
        就返回，`set_equipped(False)` 永远不会跑到——这一格就卡在“演她”的分支里，
        读不到帧时只能画兜底圆，直到重启。
        """
        self.avatar.set_equipped(False)
        self.avatar.set_grabbable(False)
        self.avatar.setToolTip("她出去了：拖回这一格就回来")

    def dock_pet(self, pet=None) -> bool:
        """把她收进左栏那一格。

        overlay 拓扑（``_SpriteChatAnchor``）：桌面那只**不动也不隐藏**，只让格子里
        的 ``LivePetView`` 开始演她——同一时刻屏幕上两个她，一个能摸一个只是预览。
        widget 拓扑（老 ``PetWindow``）：真窗隐藏，槽位放同一段帧。
        """
        window = pet if pet is not None else getattr(self.owner, "pet_window", None)
        if window is None or getattr(self.owner, "_capture_compat", False):
            # 捕获兼容时不行：气泡就是主窗的子内容，把主窗藏了等于把工位自己藏了。
            if not self._pet_docked:
                self._show_empty_slot()
            return False
        shell = getattr(window, "_shell", None)
        sprite = getattr(window, "_sprite", None)
        if shell is not None and sprite is not None:
            # overlay 拓扑：她不是一扇窗，是合成窗里的一块 sprite（见下）。
            return self._dock_overlay_pet(window, shell, sprite)
        if not isinstance(window, QWidget) or not window.isWindow():
            # 其余不认识的锚点对象：直接当「收不起来」，别再掀 traceback。
            if not self._pet_docked:
                self._show_empty_slot()
            return False
        if self._pet is not window:
            self._pet = window
        geometry = getattr(window, "visible_content_rect", None)
        if callable(geometry):
            try:
                self._pet_home = QRect(geometry())
            except Exception:
                log.debug("小工位：记她原来的位置失败", exc_info=True)
        self._pet_docked = True
        self._dock_watch.stop()
        try:
            window.hide()
        except Exception:
            log.debug("小工位：收不起桌宠窗", exc_info=True)
        # 气泡/胶囊的锚点改成槽位：真窗藏了，它的 visible_content_rect 已经是旧位置。
        try:
            window._docked_slot_rect = self.slot_global_rect
        except Exception:
            pass
        self.avatar.set_equipped(True)
        self.avatar.set_grabbable(True)
        self.avatar.setToolTip("按住她往外拖，能放回桌面")
        self._nudge_panels()
        return True

    def _dock_overlay_pet(self, anchor, shell, sprite) -> bool:
        """overlay 拓扑的收起：桌面那只不动，格子里那格开始演她。

        ``owner.pet_window`` 这时是 ``_SpriteChatAnchor``（``_shell``/``_sprite`` 两个槽），
        老路径的 ``hide()``/``move()``/``frameGeometry()`` 全无从下手。做法：记下槽位矩形
        当锚点（气泡靠它定位），桌面真 sprite 一直画着，格子里的 ``LivePetView`` 只是
        会动的预览，也不可拖。
        """
        setter = getattr(sprite, "set_visible", None)
        if not callable(setter) or not anchor.presentation_valid():
            # 时机不对（sprite 还没就绪）：这次收不起来，格子照实退回空位。
            if not self._pet_docked:
                self._show_empty_slot()
            return False
        self._pet = anchor
        self._pet_docked = True
        self._dock_watch.stop()
        try:
            anchor._docked_slot_rect = self.slot_global_rect
        except Exception:
            log.debug("小工位：挂槽位锚点失败", exc_info=True)
        # 桌面上那只不动：她一直都在，框里这个只是会动的她。
        self.avatar.set_equipped(True)
        self.avatar.set_grabbable(False)
        self.avatar.setToolTip("她在工位里也在桌面上")
        self._nudge_panels()
        return True

    # -- overlay 拓扑：sprite 的位置/缩放过渡 ---------------------------------
    def _pet_sprite(self):
        """当前的 ``(sprite, shell)``；QWidget 拓扑或不明锚点返回 ``(None, None)``。"""
        anchor = self._pet
        sprite = getattr(anchor, "_sprite", None)
        shell = getattr(anchor, "_shell", None)
        if sprite is None or shell is None:
            return None, None
        return sprite, shell

    def undock_pet(self, *, restore: bool = True) -> bool:
        """把她放回桌面（真窗显形），槽位变成虚线空位等她回来。"""
        window, self._pet = self._pet, None
        if window is None:
            # 没东西可放回，但格子也要回到「她不在座上」：收起失败过的那一次
            # 只要把 `_equipped` 留成 True，就再没入口把它翻回去。
            if not self._pet_docked:
                self._show_empty_slot()
            return False
        self._pet_docked = False
        try:
            # 置 None 而不是 del：``_SpriteChatAnchor`` 是 __slots__ 类，del 之后
            # 属性直接不存在（getattr 虽能兜，但每次都要跑 except 路径）。
            window._docked_slot_rect = None
        except Exception:
            pass
        shell = getattr(window, "_shell", None)
        sprite = getattr(window, "_sprite", None)
        if shell is not None and sprite is not None:
            # 桌面上那只一直都在，框里只是个会动的她：收起框只把格里的展示收掉。
            self.avatar.set_equipped(False)
            self.avatar.set_grabbable(False)
            self.avatar.setToolTip("她出去了：拖回这一格就回来")
            self._nudge_panels()
            return True
        if restore:
            home = getattr(self, "_pet_home", None)
            try:
                if isinstance(home, QRect) and home.isValid():
                    frame = QRect(window.frameGeometry())
                    delta = home.center() - frame.center()
                    window.move(window.pos() + delta)
                window.show()
                window.raise_()
            except Exception:
                log.debug("小工位：把桌宠放回桌面失败", exc_info=True)
            # 上次收紧时她就坐在槽位上：原地显形会被看门狗立刻又收回去，
            # 得先把她挪到面板外侧。
            content = self._pet_content_rect()
            if content is not None and self._slot_takes(content):
                panel = self.frameGeometry()
                try:
                    window.move(window.pos() + QPoint(max(48, panel.right() + 40 - content.left()), 0))
                except Exception:
                    log.debug("小工位：放回桌面时挪开失败", exc_info=True)
        self.avatar.set_equipped(False)
        self.avatar.set_grabbable(False)
        self.avatar.setToolTip("她出去了：拖回这一格就回来")
        if restore:
            self._dock_watch.start()
        self._nudge_panels()
        return True

    def _nudge_panels(self) -> None:
        """她换了位置就把弹框重新贴上去（气泡自己有跟拍，这里只负责叫醒它）。"""
        bubble = self.owner
        follow = getattr(bubble, "position_near_pet", None)
        if callable(follow):
            try:
                if getattr(bubble, "isVisible", lambda: False)():
                    follow()
            except Exception:
                log.debug("小工位：气泡重定位失败", exc_info=True)
        place = getattr(bubble, "_position_workstation", None)
        if callable(place):
            try:
                place()
            except Exception:
                log.debug("小工位：工位重定位失败", exc_info=True)

    def _pet_content_rect(self) -> QRect | None:
        window = self._pet
        getter = getattr(window, "visible_content_rect", None)
        if not callable(getter):
            return None
        try:
            rect = QRect(getter())
        except Exception:
            return None
        return rect if rect.isValid() else None

    def _on_pet_clicked(self) -> None:
        """点一下格子里的她：交回壳的点击入口（点击音效/台词/余额那一套）。

        她在格子里时真 sprite 不在这一格上画；所以这一下由 ``LivePetView`` 代收，
        再拿同一个入口转给壳。
        """
        sprite, shell = self._pet_sprite()
        if sprite is None or shell is None:
            return
        handler = getattr(shell, "_on_sprite_click", None)
        if not callable(handler):
            return
        try:
            handler(sprite, "")
        except Exception:
            log.debug("小工位：格子里点击反应失败", exc_info=True)

    def _slot_takes(self, rect: QRect | None) -> bool:
        """她身体面积有一半落在槽位里就算「拖回来了」。"""
        if rect is None:
            return False
        slot = self.slot_global_rect()
        overlap = slot.intersected(rect)
        if overlap.isEmpty():
            return False
        area = max(1, rect.width() * rect.height())
        return (overlap.width() * overlap.height()) / area >= 0.5

    def _watch_return(self) -> None:
        if self._pet is None or self._pet_docked or not self.isVisible():
            self._dock_watch.stop()
            return
        if QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton:
            return
        if self._slot_takes(self._pet_content_rect()):
            self.dock_pet()

    def _make_room(self) -> None:
        """展开就把她挠开：大窗不该压着宠物。壳上有多只时交给壳自己挑。"""
        if self._pet_docked:
            # 她已经收进左栏了，没有「让位」这回事。
            return
        rect = self.frameGeometry()
        shell = getattr(getattr(self.owner, "pet_window", None), "_shell", None)
        make_room = getattr(shell, "make_room_for", None)
        if callable(make_room):
            try:
                make_room(rect)
                return
            except Exception:
                log.debug("小工位：让位（壳）失败", exc_info=True)
        # 旧拓扑：桌宠是一整个窗口，直接把它挑到窗左侧就行。
        window = getattr(self.owner, "pet_window", None)
        geometry = getattr(window, "frameGeometry", None)
        move = getattr(window, "move", None)
        if not callable(geometry) or not callable(move):
            return
        try:
            pet = geometry()
            if not pet.isValid() or not pet.intersects(rect):
                return
            move(max(8, rect.left() - pet.width() - 28), pet.top())
        except Exception:
            log.debug("小工位：让位（窗口）失败", exc_info=True)

    def _place(self) -> None:
        """贴屏幕右边：左边留给桌宠和气泡，不抢她刚站的位置。"""
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x = max(area.left() + 8, area.right() - WIN_W - 18)
        y = max(area.top() + 8, area.center().y() - WIN_H // 2)
        self.move(x, y)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 口
        # 关掉只是收起来：下次打开不重建，待批表也不丢。
        event.ignore()
        self.hide()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt 口
        super().showEvent(event)
        self.visibilityChanged.emit(True)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt 口
        # 窗收了，她不能跟着一起消失：放回桌面。
        if self._pet_docked:
            self.undock_pet()
        super().hideEvent(event)
        self.visibilityChanged.emit(False)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 口
        super().resizeEvent(event)

    # -- 待批表 -------------------------------------------------------------
    def sync_approvals(self, entries) -> None:
        """整表对账（上游是唯一数据源）：工位开着时把全部待批一次摆出来。

        旧路径是逐条 ``add_approval``，只有「工位已经开着」才喂得到——工位没开时
        事件直接丢，之后打开也不重放，左栏页于是永远是空的。整表同步让「先卡住、
        后开工位」也能看见。
        """
        table: dict[str, dict] = {}
        if isinstance(entries, dict):
            pairs = list(entries.items())
        else:
            pairs = [
                (e.get("run_id") if isinstance(e, dict) else None, e)
                for e in (entries or [])
            ]
        for key, entry in pairs:
            if not isinstance(entry, dict):
                continue
            run_id = str(entry.get("run_id") or key or "")
            if run_id:
                table[run_id] = entry
        if table == self.approvals:
            return
        self.approvals = table
        self.approvals_page.rebuild()
        self._refresh_rail_icons()

    def add_approval(self, run_id, workspace, message, approval) -> None:
        run_id = str(run_id or "")
        if not run_id:
            return
        self.approvals[run_id] = {
            "workspace": str(workspace or ""),
            "message": str(message or ""),
            "approval": approval,
        }
        self.approvals_page.rebuild()
        self._refresh_rail_icons()

    def drop_approval(self, run_id) -> None:
        if self.approvals.pop(str(run_id or ""), None) is None:
            return
        self.approvals_page.rebuild()
        self._refresh_rail_icons()

    def resolve_approval(self, run_id: str, approved: bool) -> None:
        entry = self.approvals.get(str(run_id or "")) or {}
        approval = entry.get("approval")
        if approval is None:
            self.drop_approval(run_id)
            return
        approve = getattr(getattr(self.owner, "laji_service", None), "approve", None)
        if not callable(approve):
            log.warning("小工位：没有可用的 laji_service，审批发不回去")
            return
        try:
            approve(str(run_id), str(getattr(approval, "call_id", "")), bool(approved))
        except Exception:
            log.exception("小工位：审批回传失败")
            return
        self.drop_approval(run_id)
        self._hand_back(run_id)

    def _hand_back(self, run_id: str) -> None:
        """批完要通知壳把同一张表里的这条也删掉。

        否则工位一关，徽章会把这已经批过的条重新挂出来（它读的是壳那张表），
        用户点下去只能得到一个失败。
        """
        shell = getattr(getattr(self.owner, "pet_window", None), "_shell", None)
        drop = getattr(shell, "drop_external_approval", None)
        if not callable(drop):
            return
        try:
            drop(str(run_id or ""))
        except Exception:
            log.debug("小工位：回传审批结果失败", exc_info=True)

    def locate_run(self, run_id: str) -> None:
        """run 会话只在主窗里看得到：不在这里假装能定位。"""
        log.debug("小工位：去主窗看 %s 那条会话", run_id)
        self.open_full_chat()

    # -- 工作台入口 ---------------------------------------------------------
    def open_full_chat(self) -> None:
        """回主窗。壳上给的 ``open_chat_callback`` 才是正口（overlay 拓扑下
        ``pet_window`` 只是个锚点，没有这个方法）。"""
        slot = getattr(self.owner, "open_chat_callback", None)
        if not callable(slot):
            slot = getattr(getattr(self.owner, "pet_window", None), "open_full_chat", None)
        if callable(slot):
            try:
                slot()
            except Exception:
                log.exception("小工位：打开主窗失败")
                return
            self.hide()
            return
        self.messages.subtitle.setText("主窗没开，先在气泡里说。")

    def bench_action(self, action: str) -> None:
        if action == "messages":
            self.select(0)
            return
        if action == "approvals":
            self.select(1)
            return
        if action == "new_session":
            current = getattr(self.owner, "session", None)
            if current is not None and not list(getattr(current, "messages", []) or []):
                # 手上这条本来就空：再点 ＋ 只是回到它，不必往 sessions/ 里堆空壳文件。
                self.select(0)
                self.messages.refresh_sessions()
                return
            factory = getattr(self.owner, "_new_session", None)
            if callable(factory):
                try:
                    self.owner.session = factory()
                except Exception:
                    log.exception("小工位：新建会话失败")
            self.select(0)
            self.messages.refresh_sessions()
            return
        if action == "work":
            text = self.messages.composer.text().strip()
            send = getattr(self.owner, "send_text", None)
            if text and callable(send):
                self.messages.composer.clear()
                self.select(0)
                send(text)
            else:
                self.messages.subtitle.setText("先在输入框里写一句要她干的事。")
            return
        if action in self.bench.pages:
            # 连接器 / 手艺 / 工坊 / 会话：在工位里就地开页，不再弹回 agent 主窗。
            self.bench.show_page(action)
            return
        if action == "settings":
            slot = getattr(getattr(self.owner, "pet_window", None), "open_chat_settings", None)
            if callable(slot):
                slot()
                return
        self.open_full_chat()


def open_workstation(owner) -> WorkstationWindow:
    """壳上的入口：有就亮出来，没有就现造一个（挂在 owner 上防被回收）。"""
    window = getattr(owner, "_workstation", None)
    if not isinstance(window, WorkstationWindow):
        window = WorkstationWindow(owner)
        try:
            owner._workstation = window
        except Exception:
            log.debug("小工位：记不住实例", exc_info=True)
    window.present()
    return window
