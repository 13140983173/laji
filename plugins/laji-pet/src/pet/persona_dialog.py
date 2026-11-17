# -*- coding: utf-8 -*-
"""角色卡上的「人设」编辑：每只桌宠一份，落到 ``pet_persona_overrides[角色 id]``。

以前这组编辑放在「角色与素材 → 打工身份」里，一个下拉切角色 + 一个输入框：要改谁的人设
得先在脑子里记住当前选的是哪只，和角色卡上的名字对不上号。现在入口挂在角色自己身上
（``my_characters_page`` 的每张卡一个「人设」按钮），点哪只就改哪只。

数据仍是同一格：``pet_persona_overrides``（按角色 id 的 dict），留空 = 回落出场人设
（``persona_prompt.character_persona``）。保存时会顺手 ``sync_from_config``，把
``{workspace}/.laji/pet-persona.md`` 一起刷掉——只写配置不同步，用户会以为没生效。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from . import catalog
from .settings_theme_qss import _settings_stylesheet

_LOG = logging.getLogger(__name__)

#: 人设字数上限：够写称呼、口吻、几条忌讳；再长会把每轮系统提示撑胖。
MAX_PERSONA_CHARS = 2000


def _overrides(config) -> dict:
    """config 里那张「按角色手写人设」的表；脏值一律当空表（宁可用出厂，不炸页面）。"""
    try:
        raw = config.get("pet_persona_overrides")
    except Exception:      # noqa: BLE001 - 读配置失败不该让角色页崩
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): str(v or "") for k, v in raw.items()}


def persona_text(config, character_id: str) -> str:
    """这只桌宠的手写人设；空串 = 用出厂人设。"""
    return _overrides(config).get(str(character_id or ""), "")


def has_persona(config, character_id: str) -> bool:
    """这只桌宠有没有用户手写的人设（卡片上那行状态与高亮都靠它）。"""
    return bool(persona_text(config, character_id).strip())


def persona_state_label(config, character_id: str) -> str:
    """卡片上那一行状态：只有用户改过才给一句话。

    没改过就是素材包自带的人设，属于默认情形——卡片上不挂“出厂”这类说明，
    让名字、预览和两个按钮自己说话。
    """
    return "人设 · 自定义" if has_persona(config, character_id) else ""


def save_persona(config, character_id: str, text: str) -> bool:
    """写回配置并落盘，再把人格同步进 Pet 工作区；返回是否真的存下来了。

    落盘前 ``reload()``：设置窗开着的时候主进程也会写 config（托盘开关、切角色），
    不重读就把别人的改动回滚了——与 ``ModernSettingsDialog._write_config`` 同一条理由。
    """
    character_id = str(character_id or "")
    if not character_id:
        return False
    try:
        config.reload()
    except Exception:      # noqa: BLE001 - 重读失败就按内存值写，总比不写强
        _LOG.warning("人设保存前重读配置失败", exc_info=True)
    overrides = _overrides(config)
    text = str(text or "").strip()[:MAX_PERSONA_CHARS]
    if text:
        overrides[character_id] = text
    else:
        overrides.pop(character_id, None)
    config.set("pet_persona_overrides", overrides)
    if config.save() is False:
        return False
    try:
        from .agent_link.persona_prompt import sync_from_config

        sync_from_config(config)
    except Exception:      # noqa: BLE001 - 写不进工作区不影响配置已存
        _LOG.warning("人设已保存，但同步到 Pet 工作区失败", exc_info=True)
    return True


def _display_name(config, character_id: str) -> str:
    """对话框标题上的名字：用户改过名就用别名（与卡片同一条解析）。"""
    getter = getattr(config, "character_display_name", None)
    if callable(getter):
        try:
            name = str(getter(character_id) or "").strip()
            if name:
                return name
        except Exception:      # noqa: BLE001 - 读不到别名就用素材包自带的名字
            _LOG.warning("读取角色别名失败: %s", character_id, exc_info=True)
    return (
        catalog.character_call_name(character_id)
        or catalog.character_display_name(character_id)
        or character_id
    )


def _factory_preview(character_id: str) -> str:
    """出厂人设的首句：让用户知道「留空」到底会得到什么，而不是一句空承诺。"""
    try:
        from .agent_link.persona_prompt import character_persona

        text = str(character_persona(character_id) or "").strip()
    except Exception:      # noqa: BLE001 - 预览拿不到就不显示
        return ""
    head = text.splitlines()[0] if text else ""
    return head if len(head) <= 80 else head[:79] + "…"


class PersonaDialog(QDialog):
    """一只桌宠的人设编辑框：留空回落出厂，保存即写盘 + 同步。"""

    def __init__(self, config, character_id: str, parent=None) -> None:
        super().__init__(parent)
        self._config = config
        self._character_id = str(character_id or "")
        name = _display_name(config, self._character_id)
        self.setWindowTitle(f"{name} · 人设")
        self.setMinimumWidth(540)
        self.setMinimumHeight(420)
        self.setModal(True)

        host = parent.window() if parent is not None else None
        dark = bool(host.property("settingsDark")) if host is not None else False
        self.setStyleSheet(_settings_stylesheet("dark" if dark else "light"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        title = QLabel(f"{name} 的人设", self)
        title.setObjectName("personaTitle")
        layout.addWidget(title)

        hint = QLabel(
            "这段文字就是这只桌宠在 Laji 里的身份：怎么称呼你、什么口吻、哪些话不说。"
            "留空则用出厂人设。",
            self,
        )
        hint.setObjectName("settingHint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        factory = _factory_preview(self._character_id)
        if factory:
            preview = QLabel(f"出厂人设开头：{factory}", self)
            preview.setObjectName("personaFactoryHint")
            preview.setWordWrap(True)
            layout.addWidget(preview)

        self._edit = QPlainTextEdit(self)
        self._edit.setObjectName("personaEdit")
        self._edit.setPlaceholderText("例：你是小满，叫我「老板」，说话简短带一点冷笑话，不卖萌。")
        self._edit.setPlainText(persona_text(config, self._character_id))
        self._edit.setMinimumHeight(190)
        layout.addWidget(self._edit, 1)

        self._counter = QLabel("", self)
        self._counter.setObjectName("settingHint")
        self._counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._counter)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self._reset_btn = QPushButton("恢复出厂人设", self)
        self._reset_btn.setObjectName("characterSecondary")
        self._reset_btn.clicked.connect(self._edit.clear)
        cancel = QPushButton("取消", self)
        cancel.setObjectName("characterSecondary")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存人设", self)
        save.setObjectName("characterPrimary")
        save.setDefault(True)
        save.clicked.connect(self._on_save)
        buttons.addWidget(self._reset_btn, 0)
        buttons.addStretch(1)
        buttons.addWidget(cancel, 0)
        buttons.addWidget(save, 0)
        layout.addLayout(buttons)

        self._edit.textChanged.connect(self._refresh_counter)
        self._refresh_counter()
        self._edit.setFocus()

    def _refresh_counter(self) -> None:
        used = len(self._edit.toPlainText())
        self._counter.setText(f"{used} / {MAX_PERSONA_CHARS}")
        # 超长时按钮不拦（保存会截断），但要让用户看见自己越界了。
        self._counter.setProperty("over", used > MAX_PERSONA_CHARS)

    def _on_save(self) -> None:
        if not save_persona(self._config, self._character_id, self._edit.toPlainText()):
            QMessageBox.warning(
                self,
                "人设没存下来",
                "写入配置失败，这一版人设没有保存。\n可以稍后重试，或检查配置目录是否可写。",
            )
            return
        self.accept()

    def persona_value(self) -> str:
        return self._edit.toPlainText().strip()
