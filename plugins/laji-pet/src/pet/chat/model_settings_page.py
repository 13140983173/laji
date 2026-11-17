# -*- coding: utf-8 -*-
"""「模型」清单页与「添加模型」对话框。

从小工位（``pet/workstation_window.py``）整段搬来：小工位「设置 → 模型」与桌宠设置窗
「AI 与对话 → 模型设置」是同一件事，两份实现迟早漂移，所以只留这一份。

配色走 :func:`theme_colors`：小工位窗口自带四套主题（``_theme_key``），设置窗没有这个
属性，回退成小工位默认那套琥珀色——两边 ``CapSave`` 的底色也是这个值。
"""
from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .model_tiers import TIER_LABELS, normalize_tier

log = logging.getLogger(__name__)

#: 设置窗没有 ``_theme_key`` 时用的那套（小工位 THEMES[0] 琥珀的 acc / fg2）。
_FALLBACK_COLORS = {"acc": "#e8a33d", "fg": "#f3ece2", "fg2": "#a89b88"}


def theme_colors(window) -> dict:
    """当前窗口的配色：小工位窗口按它自己的主题，其余窗口用默认琥珀。

    延迟导入 ``workstation_window``：设置进程不该为了两个色值把六千行的工位模块
    拉进来（那里的窗口在设置窗里根本不存在，``_theme_key`` 缺失就走回退）。
    """
    key = str(getattr(window, "_theme_key", "") or "")
    if not key:
        return dict(_FALLBACK_COLORS)
    try:
        from ..workstation_window import _theme
    except Exception:  # noqa: BLE001 - 主题查不到不该影响设置页
        return dict(_FALLBACK_COLORS)
    try:
        return dict(_theme(key)[2])
    except Exception:  # noqa: BLE001
        return dict(_FALLBACK_COLORS)

class ModelSwitch(QAbstractButton):
    """卡片右上角的小开关：34x19 的轨道 + 白圆点，开启时用主题强调色。

    QSS 的 ``::indicator`` 画不出滑块（只有一张底图），而这页只需要一个开关控件，
    自绘比塞三张图片省事，也能跟着四条主题色走。
    """

    def __init__(self, checked: bool, accent: str, parent=None, *, dark: bool | None = None) -> None:
        super().__init__(parent)
        self._accent = QColor(accent)
        self._dark = dark
        self.setCheckable(True)
        self.setChecked(bool(checked))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(34, 19)
        self.setToolTip("停用后自动路由不会再挑这个模型")

    def isDark(self) -> bool:  # noqa: N802 - 与 Qt 命名一致
        """底色深浅：设置窗看 ``settingsDark``，小工位看主题的 ``light`` 标记。

        关态轨道是半透明叠加色，底色判错就是「禁用后开关整个消失」：15.7% 的白
        压在浅色主题的白卡片上（#ffffff）叠出来仍是 #ffffff，对比度 1.0:1。
        """
        if self._dark is not None:
            return bool(self._dark)
        window = self.window()
        flag = window.property("settingsDark") if window is not None else None
        if isinstance(flag, bool):
            return flag
        return not bool(theme_colors(window).get("light"))

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        track = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = track.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        if self.isChecked():
            painter.setBrush(self._accent)
        elif self.isDark():
            painter.setBrush(QColor(255, 255, 255, 40))
        else:
            # 浅色底：白叠白看不见，换成黑色 25% —— 白卡片上约 #bfbfbf（对比 1.8:1）
            painter.setBrush(QColor(0, 0, 0, 64))
        painter.drawRoundedRect(track, radius, radius)
        knob = track.height() - 5
        left = track.width() - knob - 2.5 if self.isChecked() else 2.5
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QRectF(left, 2.5, knob, knob))
        painter.end()


class _Scrim(QWidget):
    """弹层身后的压暗层：铺满宿主窗口，随它一起改尺寸。

    弹层是半透明无边框窗口（底由卡片自己画），身后不压暗就会和模型清单叠在一起
    看——实测能同时看到弹层标题和身后的模型行。
    """

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self.setObjectName("CapScrim")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setGeometry(host.rect())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        super().resizeEvent(event)


class _ProviderRow(QFrame):
    """一张模型卡。点哪儿都进编辑：名字、端点、Model ID 没有别的入口。

    行内的开关 / 删除 / 笔自己吃掉点击，所以不会误触；文字区（QLabel 默认不收鼠标
    事件）会冒泡到这里。
    """

    clicked = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击编辑这个模型")

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(
            event.position().toPoint()
        ):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ChatModelPage(QWidget):
    """设置 → 模型：桌宠聊天用哪些模型。

    版式和交互照抄 agent 视图的模型页（``ModelSection.tsx``）：右上「刷新」+「+ 添加模型」，
    下面按云端 / 本地分组摆卡片（名字、状态、模型与端点、启用开关、删除）。

    用哪个模型不需要选：发送前按清单顺序自动挑第一个能用的（``ChatSettings.auto_pick``），
    停用的卡片自动跳过。

    和 agent 视图是两套配置，互不影响：只读写桌宠自己的 ``config.json``，不碰
    Electron 的 ``User/settings.json``，也不写引擎的 ``config.toml``。
    """

    _STATUS_TTL_MS = 4500  # 页脚短句停留多久

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
        scroll.setObjectName("modelSettingsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # 滚动区不铺自己的底：设置页是白底，QScrollArea 默认的窗口色会在卡片后面
        # 垫出一条灰带（实测云端/本地两组各自套一层灰底）。
        scroll.viewport().setAutoFillBackground(False)
        self._host = QWidget(scroll)
        self._host.setObjectName("modelSettingsHost")
        self._col = QVBoxLayout(self._host)
        # 滚动区是 widgetResizable：host 会被压成视口大小，只有让布局的「最小尺寸跟内容走」，
        # QScrollArea 才知道内容长高了、才给滚动条范围。否则重建后内容比视口高，
        # 既不撑高 host 也不出滚动条：新加的模型卡在视口外，看起来就是「添加完不显示」。
        self._col.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        self._col.setContentsMargins(0, 0, 8, 0)
        self._col.setSpacing(8)
        scroll.setWidget(self._host)
        self._scroll = scroll
        outer.addWidget(scroll, 1)

        self._status = QLabel("", self)
        self._status.setObjectName("SetHint")
        self._status.setWordWrap(True)
        self._status.hide()
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(lambda: self._set_status(""))
        outer.addWidget(self._status)

        self._render()

    # -- 渲染 ---------------------------------------------------------------
    def _render(self) -> None:
        self._row_widgets = {}
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
                row = self._provider_row(provider_id, provider)
                self._row_widgets[provider_id] = row
                self._col.addWidget(row)
        self._col.addStretch(1)

    def _reveal_provider(self, provider_id: str) -> None:
        """把刚加/刚存的卡片滚进视口：列表常有七八条，它落在末尾，不滚就等于「没加上」。"""
        row = getattr(self, "_row_widgets", {}).get(provider_id)
        scroll = getattr(self, "_scroll", None)
        if row is None or scroll is None:
            return
        scroll.ensureWidgetVisible(row)

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
        window = self.window()
        return str(theme_colors(window).get("acc") or "#e8a33d")

    def _provider_row(self, provider_id: str, provider) -> QFrame:
        row = _ProviderRow(self._host)
        row.setObjectName("SetRow")
        row.clicked.connect(lambda pid=provider_id: self._open_edit_dialog(pid))
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

        # 卡片上没有其他可点的地方，改「名字 / 端点 / Model ID / Key」只能从这里进：
        # 一支笔比「编辑」两个字省位置，也和弹层右上那个关闭叉同一套样式。
        edit = QToolButton(row)
        edit.setObjectName("CapIcon")
        edit.setIcon(QIcon(self._pen_pixmap()))
        edit.setIconSize(QSize(16, 16))
        edit.setFixedSize(26, 26)
        edit.setCursor(Qt.CursorShape.PointingHandCursor)
        edit.setToolTip("编辑这个模型")
        edit.clicked.connect(lambda _=False, pid=provider_id: self._open_edit_dialog(pid))
        top.addWidget(edit)

        enable = ModelSwitch(bool(provider.enabled), self._accent(), row)
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

    def _pen_pixmap(self) -> QPixmap:
        """自绘铅笔：字体缺图标字形时按钮会是空白。

        实心斜条 + 笔尖三角：14px 宽下画线稿会糊成一道斜杠，看不出是笔。
        颜色用行尾「删除」那个灰：设置窗拿不到工位主题（``theme_colors`` 会回退成
        深色皮肤那套近白色），按主题取色会在浅色背景上画出一支看不见的笔。
        """
        pix = QPixmap(16, 16)
        pix.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#8a8a93"))
        painter.drawPolygon(
            QPolygon([QPoint(4, 12), QPoint(12, 4), QPoint(14, 6), QPoint(6, 14)])
        )
        painter.drawPolygon(QPolygon([QPoint(1, 15), QPoint(4, 12), QPoint(6, 14)]))
        painter.end()
        return pix

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
        # 只标「在用」。剩下两种都不是“状态”而是“还没弄好 / 等着”：
        # 缺 Key 是还没填完，填了没选中也只是一个备用项——两者摆成徽标都像在报错，
        # 而开关本身已经把停用说清楚了。
        return None

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

    def _set_status(self, text: str, *, sticky: bool = False) -> None:
        """页脚状态行。

        它说的是「刚刚做了什么」，所以要说一阵子就走：留着会让人当成这次操作的结果
        ——删完东西再去改一张卡，页脚还写着「已删除 XX」。失败这类要人处理的才常驻。
        """
        self._status_timer.stop()
        self._status.setText(text)
        self._status.setVisible(bool(text))
        if text and not sticky:
            self._status_timer.start(self._STATUS_TTL_MS)

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
            self._set_status("保存失败：配置文件写不进去。", sticky=True)
        return ok

    def _sync_engine_profiles(self) -> None:
        """把桌宠这份模型清单镜像进引擎的 ``config.toml``（它自己的 managed block）。

        只是让引擎认识桌宠的模型：名字统一 ``pet-`` 前缀，key 走 ``SetModelKey``
        进 daemon 内存，**不写** ``[model.routing.*]`` —— agent 视图那份模型设置
        一个字都不会被改到。daemon 没起就只写盘，等它起来后下一句对话再补。
        """
        try:
            from ..agent_link import daemon_client
            from . import engine_profiles
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
        # 删除成功不再往页脚写「已删除 XX」：清单变了本身就是反馈（页脚只留要人处理的话）。
        self._commit()

    def _open_add_dialog(self) -> None:
        self._open_model_dialog(None)

    def _open_edit_dialog(self, provider_id: str) -> None:
        self._open_model_dialog(provider_id)

    def _open_model_dialog(self, provider_id: str | None) -> None:
        """新增和编辑走同一个弹层：字段、校验、测试连接完全一样，只差开头填不填。"""
        if self.config is None:
            self._set_status("读不到桌宠配置，改不了模型。")
            return
        # 弹层是独立无边框窗口，居到宿主中间；身后压一层暗，免得和清单糊在一起。
        self._set_status("")
        host = self.window()
        scrim = _Scrim(host)
        scrim.show()
        scrim.raise_()
        dialog = AddModelDialog(self.config, host, provider_id=provider_id)
        self._dialog = dialog  # 保住引用，别被 GC 提前收走
        dialog.adjustSize()
        dialog.move(host.mapToGlobal(host.rect().center()) - dialog.rect().center())
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            scrim.deleteLater()
        saved_id = dialog.saved_provider_id
        self._dialog = None
        if not accepted or not saved_id:
            return
        # 成功不写页脚（「已保存 / 已添加」已下线）：卡片本身刷新即是反馈。
        self._commit()
        self._reveal_provider(saved_id)


# 预设照抄 agent 视图的 providers.ts，只留 OpenAI 兼容的服务：协议不对的预设
# （Anthropic 这种）填进去能存下来，第一次对话就 404，用户会以为是自己 key 填错了。
MODEL_PRESETS = (
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


def model_preset(preset_id: str) -> dict:
    for preset in MODEL_PRESETS:
        if preset["id"] == preset_id:
            return preset
    return MODEL_PRESETS[-1]


class AddModelDialog(QDialog):
    """新增一个聊天模型：服务商 → 模型 ID → 端点 → API Key，底部「测试连接」。

    字段顺序和信息密度照抄 agent 视图的「添加模型」对话框（``AddModelDialog.tsx``）：
    名称 → 服务商 → 模型 ID（带建议，可自己填）→ 端点（非自定义预设只读）→ API Key。
    只写桌宠自己的 ``config.json``。
    """

    test_done = Signal(bool, str)

    def __init__(self, config, parent=None, provider_id: str | None = None) -> None:
        super().__init__(parent)
        self.config = config
        # 给了 provider_id 就是「改这一张卡」：字段全部预填，保存时改原地而不是新增。
        self.provider_id = provider_id
        self.editing = bool(provider_id)
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
        title = QLabel("编辑模型" if self.editing else "添加模型", shell)
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
        for preset in MODEL_PRESETS:
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
        self._submit_btn = QPushButton("保存" if self.editing else "添加模型", shell)
        self._submit_btn.setObjectName("CapSave")
        self._submit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._submit_btn.clicked.connect(self._submit)
        foot.addWidget(self._submit_btn)
        box.addLayout(foot)

        self.test_done.connect(self._on_test_done)
        self._sync_preset()
        if self.provider_id:
            self._load_provider(str(self.provider_id))

    def _close_pixmap(self) -> QPixmap:
        """自绘关闭叉：字体缺 "×" 字形时按钮会是空白，图标画出来更稳。"""
        window = self.window()
        colors = theme_colors(window)
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
        return model_preset(str(self._preset.currentData() or ""))

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

    def _load_provider(self, provider_id: str) -> None:
        """把现有卡片的字段填回弹层。

        API Key 不回显：钥匙串里存的 secret 不该只为了「看着方便」读进内存，
        留空即不改，占位文字会说清楚。
        """
        settings = self.config.chat_settings() if self.config is not None else None
        provider = settings.providers.get(provider_id) if settings is not None else None
        if provider is None:
            return
        base_url = str(provider.base_url or "")
        matched = next(
            (
                str(p["id"])
                for p in MODEL_PRESETS
                if str(p["base_url"] or "").rstrip("/") == base_url.rstrip("/") and p["base_url"]
            ),
            "custom",
        )
        self._preset.blockSignals(True)
        self._preset.setCurrentIndex(max(self._preset.findData(matched), 0))
        self._preset.blockSignals(False)
        self._sync_preset()
        # 预设联动先把字段刷成预设默认值，这里再把她的实际值盖回去
        self._name.setText(str(provider.name or ""))
        self._endpoint.setText(base_url)
        self._endpoint.setReadOnly(matched != "custom")
        self._model.setCurrentText(str(provider.model or ""))
        self._tier.setCurrentIndex(max(self._tier.findData(normalize_tier(provider.tier)), 0))
        self._key.clear()
        self._key.setPlaceholderText("已保存，留空不改")

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
        from .models import ProviderConfig

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
        from .providers import test_connection

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
        from .models import ProviderConfig, SecretStore

        if self.config is None:
            self._set_result("读不到桌宠配置，改不了模型。", False)
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
        if self.editing:
            provider_id = str(self.provider_id)
            provider = settings.providers.get(provider_id)
            if provider is None:
                self._set_result("这个模型已经被删掉了，关掉重开一次。", False)
                return
            provider.name = str(self._name.text().strip() or provider.name or spec["label"])
            provider.base_url = base_url
            provider.model = model
            provider.tier = str(self._tier.currentData() or "standard")
            if not provider.chat_path:
                provider.chat_path = "/v1/chat/completions"
        else:
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
        if key:
            ref = provider.api_key_ref or f"provider/{provider_id}"
            provider.api_key_ref = ref
            if not SecretStore().set(ref, key):
                provider.api_key = key  # 钥匙串不可用：只留内存，写盘时会被剔除
                note = "（系统钥匙串不可用，Key 只在本次运行有效）"
        settings.providers[provider_id] = provider
        if not settings.active_provider:
            settings.active_provider = provider_id
        self.config.set_chat_settings(settings)
        try:
            saved = self.config.save()
        except Exception:  # noqa: BLE001 - 写盘失败要提示
            log.debug("保存模型失败", exc_info=True)
            saved = False
        if not saved:
            self._set_result("保存失败：配置文件写不进去。", False)
            return
        self.saved_provider_id = provider_id
        if note:
            log.info("%s模型 %s %s", "编辑" if self.editing else "新增", provider_id, note)
        self.accept()
