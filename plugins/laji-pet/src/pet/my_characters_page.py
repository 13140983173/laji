# -*- coding: utf-8 -*-
"""设置页「我的角色」：角色卡 + 缩略图 + 一键切换当前角色。

单独成模块的原因有两个：``modern_settings_dialog.py`` 有硬行数预算，对话框里只留
接线；「小口袋」右键直接落到这一页（见 ``app.open_pet_manager``），所以它必须能在
**独立设置进程**里单独工作——没有桌宠主窗口可回调时，切换角色就写配置落盘，由主
窗口的 config watcher 接住（和面板里改别的设置是同一条路）。

清单与缩略图的唯一真源是 ``catalog.character_inventory()``（与右键「切换角色」同一
份）：本页不自己扫素材目录，也不猜哪套包布局。
"""

from __future__ import annotations

import logging
from typing import Callable

import shiboken6

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import catalog
from .animation_thumbnail import decode_representative_frame
from .persona_dialog import PersonaDialog, has_persona, persona_state_label

_LOG = logging.getLogger(__name__)

#: 缩略图边长。
#: ``animation_thumbnail`` 的代表帧按 128 像素缓存，再放大只是糊边，所以卡上的预览
#: 就按这个上限来。
PREVIEW_SIDE = 128

#: 卡片宽度与**最大**列数：默认内容区约 800 宽，3 列 × 216 加间距刚好不挤成两行文字。
#: 实际列数按窗口宽度算（见 ``MyCharactersPage._columns_for_width``）——固定 3 列
#: 时窗口窄一点，第三张卡就被右边裁掉半张，连「人设」按钮都点不到。
CARD_WIDTH = 216
COLUMNS = 3

#: 改名的字数上限，与 ``Config.set_character_alias`` 的截断保持一致。
MAX_NAME_CHARS = 24


def display_name(config, character_id: str, fallback: str = "") -> str:
    """卡片/标题上的名字：用户改过名就用别名，没改过才用清单里的名字。

    与气泡、识屏同一条解析（``Config.character_display_name``）；这样在角色卡上
    改完名，右键气泡和标题不会还挂着旧名字。
    """
    getter = getattr(config, "character_display_name", None)
    if callable(getter):
        try:
            name = str(getter(character_id) or "").strip()
            if name:
                return name
        except Exception:      # noqa: BLE001 - 取名失败退回清单名字
            _LOG.warning("读取角色别名失败: %s", character_id, exc_info=True)
    try:
        aliases = config.get("character_aliases")
    except Exception:      # noqa: BLE001 - 没有 get 的视图就用清单名字
        aliases = None
    if isinstance(aliases, dict):
        alias = str(aliases.get(character_id) or "").strip()
        if alias:
            return alias
    return fallback or str(character_id or "")


def rename_character(config, character_id: str, name: str) -> bool:
    """把这只桌宠改名（空名 = 恢复默认名），返回是否真的落盘。

    落到 ``character_aliases``：``Config.set_character_alias`` 有就走它（它负责
    长度截断与 ``save()``），没有 setter 的对象就自己写同一格配置。
    """
    character_id = str(character_id or "").strip()
    if not character_id:
        return False
    name = str(name or "").strip()[:MAX_NAME_CHARS]
    setter = getattr(config, "set_character_alias", None)
    try:
        if callable(setter):
            setter(character_id, name)
            saved = True
        else:
            raw = config.get("character_aliases")
            aliases = dict(raw) if isinstance(raw, dict) else {}
            if name:
                aliases[character_id] = name
            else:
                aliases.pop(character_id, None)
            config.set("character_aliases", aliases)
            saved = config.save() is not False
    except Exception:      # noqa: BLE001 - 改名失败不该掀翻设置页
        _LOG.warning("角色改名失败: %s", character_id, exc_info=True)
        return False
    _sync_persona_after_rename(config, character_id)
    return saved


def _sync_persona_after_rename(config, character_id: str) -> None:
    """改名顺手把引擎侧的人设文件重写一份：里面的自称跟着名字改。

    人设文在旧名字时写的（``你是 Ling``），不改文件的话气泡/语音那条引擎路径
    会继续拿旧名字自称。设置进程拿不到环境变量也能算对路径（见 ``pet_space``），
    真算不出来就只记日志——界面上的名字已经改好了。
    """
    if character_id:
        try:
            from .agent_link.persona_prompt import current_character, sync_from_config

            if current_character(config) != str(character_id):
                return                      # 只刷当前角色：别人名下的文件不该被碰
            sync_from_config(config)
        except Exception:      # noqa: BLE001 - 写不进工作区不影响已保存的别名
            _LOG.warning("改名已保存，但同步人设文件失败", exc_info=True)


def _repolish(widget: QWidget) -> None:
    """改过 property 后重算样式：不 unpolish/polish，Qt 不会重读 QSS 选择器。"""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


class _CharacterCard(QFrame):
    """角色卡本体：点卡片（含卡片留白）就整卡进入选中态。"""

    clicked = Signal(str)

    def __init__(self, character_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.character_id = str(character_id or "")

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.character_id)
        super().mousePressEvent(event)


def preview_pixmap(row: dict) -> QPixmap | None:
    """一行清单的缩略图：静态帧直读（Qt 认 png/webp），只有视频的抽代表帧。

    webp 不能靠 QPixmap 直接吃，但 Qt 的图像插件能读，所以 ``QPixmap(path)`` 就够；
    只有 ``previewVideo`` 的角色才走 ffmpeg 抽帧（带进程内 + 磁盘缓存）。
    """
    frame = str(row.get("preview") or "")
    if frame:
        pixmap = QPixmap(frame)
        if not pixmap.isNull():
            return pixmap
    video = str(row.get("previewVideo") or "")
    if video:
        image = decode_representative_frame(video)
        if not image.isNull():
            return QPixmap.fromImage(image)
    return None


class MyCharactersPage(QWidget):
    """角色卡网格。切换是**立即生效**的，不写「重启后生效」——它改的是 config 里的
    当前角色（右键菜单切换角色改的是同一格），主窗口 watcher 接住后重建桌宠。
    """

    def __init__(self, config, *, on_switch: Callable[[str], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._on_switch = on_switch
        self._current = ""
        #: 点了哪张卡（纯视觉选中）：当前角色不再常亮，选中态跟着点击走。
        self._selected = ""
        self._pending: list[tuple[QLabel, dict]] = []
        self._cards: list[QWidget] = []
        self._cols = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(18)
        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)
        # 末尾留一列弹性空白：卡片按列靠左，不跟着窗口宽度摊开成一片大间隙。
        self._grid.setColumnStretch(COLUMNS, 1)
        layout.addWidget(self._grid_host)
        layout.addStretch(1)
        self.refresh()

    def current_character(self) -> str:
        return str(self._config.get("character", "") or catalog.DEFAULT_CHARACTER)

    def _columns_for_width(self, width: int) -> int:
        """这个宽度能摆几列卡片（不算末尾那列弹性空白）。"""
        spacing = max(self._grid.horizontalSpacing(), 0)
        cols = (max(int(width), 0) + spacing) // (CARD_WIDTH + spacing)
        return max(1, min(COLUMNS, int(cols)))

    def _layout_cards(self) -> None:
        """按当前列数重新排；卡片本身不重建，缩略图也就不会重新抽帧。"""
        self._cols = self._columns_for_width(self.width())
        while self._grid.count():
            self._grid.takeAt(0)
        for index, card in enumerate(self._cards):
            self._grid.addWidget(card, index // self._cols, index % self._cols)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._cards and self._columns_for_width(self.width()) != self._cols:
            self._layout_cards()

    def refresh(self) -> None:
        """按最新清单与当前角色重建卡片。切换后调用一次，按钮状态跟着变。"""
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # 先摘父再 deleteLater：deleteLater 要等事件循环回来才真销毁，光靠它
                # 旧卡片会在原位多显示一帧，与新建的卡片叠在一起。
                widget.setParent(None)
                widget.deleteLater()
        self._cards.clear()
        self._pending.clear()
        self._current = self.current_character()
        selected = self._selected
        rows = catalog.character_inventory()
        if not rows:
            empty = QLabel("没有找到可用的角色素材。装一个角色包，或把素材放进角色目录。",
                           self._grid_host)
            empty.setObjectName("settingHint")
            empty.setWordWrap(True)
            self._cards.append(empty)
        for row in rows:
            card, preview = self._build_card(row, selected)
            self._cards.append(card)
            self._pending.append((preview, row))
        self._layout_cards()
        # 抽帧首次要跑 ffmpeg（几百毫秒），逐张排队填：窗口先显示出来，再慢慢出图。
        QTimer.singleShot(0, self._fill_next_preview)

    def _build_card(self, row: dict, selected: str = "") -> tuple[QWidget, QLabel]:
        character_id = str(row.get("id") or "")
        card = _CharacterCard(character_id, self._grid_host)
        card.setObjectName("settingsCard")
        card.setFixedWidth(CARD_WIDTH)
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        is_current = character_id == self._current
        # current 只给代码看（「当前角色」按钮的文案/置灰）——整卡描边跟前点击走：
        # 否则正在用的那只永远亮着，看起来像“被选中”。
        card.setProperty("current", is_current)
        card.setProperty("selected", bool(character_id) and character_id == selected)
        card.clicked.connect(self._select)

        preview = QLabel("\U0001F41F", card)
        preview.setObjectName("characterPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(PREVIEW_SIDE, PREVIEW_SIDE)
        # 预览与名字不拦鼠标：点在上面也要落到卡片上，整卡才能一起选中。
        preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)

        shown_name = display_name(self._config, character_id, str(row.get("name") or ""))
        name = QLabel(shown_name, card)
        name.setObjectName("characterName")
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        name.setWordWrap(True)
        name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # 固定高度：名字一行还是两行，三张卡都得一样高，否则底排按钮参差。
        name.setFixedHeight(36)
        layout.addWidget(name)

        # 人设状态：只有“自定义”要说；没改过就是出厂，不必挂在卡片上。
        custom = has_persona(self._config, character_id)
        persona_state = QLabel(persona_state_label(self._config, character_id) if custom else "",
                               card)
        persona_state.setObjectName("characterPersonaState")
        persona_state.setProperty("custom", custom)
        persona_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        persona_state.setFixedHeight(14)
        persona_state.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(persona_state)

        button = QPushButton("当前角色" if is_current else "设为当前", card)
        button.setObjectName("characterPrimary")
        button.setEnabled(not is_current)
        button.setAutoDefault(False)
        button.setDefault(False)
        button.clicked.connect(
            lambda _checked=False, cid=character_id: self._switch_to(cid)
        )
        layout.addWidget(button)

        actions = QHBoxLayout()
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(6)
        rename_btn = QPushButton("改名", card)
        rename_btn.setObjectName("characterSecondary")
        rename_btn.setAutoDefault(False)
        rename_btn.setDefault(False)
        rename_btn.setToolTip(f"给「{shown_name}」换个名字")
        rename_btn.clicked.connect(
            lambda _checked=False, cid=character_id: self._rename(cid)
        )
        persona_btn = QPushButton("人设", card)
        persona_btn.setObjectName("characterSecondary")
        persona_btn.setAutoDefault(False)
        persona_btn.setDefault(False)
        persona_btn.setToolTip(f"编辑「{shown_name}」的人设")
        persona_btn.clicked.connect(
            lambda _checked=False, cid=character_id: self._open_persona(cid)
        )
        actions.addWidget(rename_btn, 1)
        actions.addWidget(persona_btn, 1)
        layout.addLayout(actions)
        return card, preview

    def _select(self, character_id: str) -> None:
        """点哪张卡就整卡选中：同一时刻最多一张，再点已选中的不动。"""
        character_id = str(character_id or "")
        if not character_id or character_id == self._selected:
            return
        self._selected = character_id
        for card in self._cards:
            card_id = getattr(card, "character_id", "")
            if not card_id:
                continue
            card.setProperty("selected", card_id == character_id)
            _repolish(card)

    def _rename(self, character_id: str) -> None:
        """改这只桌宠的名字；空名 = 恢复素材包自带的名字。"""
        if not character_id:
            return
        current = display_name(self._config, character_id)
        alias = ""
        getter = getattr(self._config, "character_alias", None)
        if callable(getter):
            try:
                alias = str(getter(character_id) or "")
            except Exception:      # noqa: BLE001 - 读不到就按没改过处理
                alias = ""
        name, ok = QInputDialog.getText(
            self, "改名", f"「{current}」的新名字（留空 = 恢复默认名）：", text=alias
        )
        if not ok:
            return
        if not rename_character(self._config, character_id, name):
            _LOG.warning("角色改名没有写进配置: %s", character_id)
            return
        self.refresh()

    def _open_persona(self, character_id: str) -> None:
        """开这只桌宠的人设编辑框；存下来了就重建卡片，把「人设 · 自定义」显出来。"""
        if not character_id:
            return
        try:
            dialog = PersonaDialog(self._config, character_id, self)
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
            dialog.deleteLater()
        except Exception:      # noqa: BLE001 - 人设窗起不来不该掀翻设置页
            _LOG.warning("打开人设编辑失败: %s", character_id, exc_info=True)
            return
        if accepted:
            self.refresh()

    def _fill_next_preview(self) -> None:
        """逐张装载缩略图；设置窗关掉后这张卡可能已被销毁，所以每一步都先验活。

        ``QTimer.singleShot`` 排着的回调不随控件销毁取消：直接 ``setPixmap`` 会落进
        已删除的 C++ 对象（``RuntimeError: Internal C++ object already deleted``）。
        """
        if not self._pending or not shiboken6.isValid(self):
            return
        preview, row = self._pending.pop(0)
        try:
            pixmap = preview_pixmap(row)
        except Exception:      # noqa: BLE001 - 一张缩略图失败不该炸整页
            _LOG.warning("角色缩略图读取失败: %s", row.get("id"), exc_info=True)
            pixmap = None
        if pixmap is not None and not pixmap.isNull() and shiboken6.isValid(preview):
            preview.setPixmap(
                pixmap.scaled(
                    PREVIEW_SIDE,
                    PREVIEW_SIDE,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        if self._pending:
            QTimer.singleShot(0, self._fill_next_preview)

    def _switch_to(self, character_id: str) -> None:
        """切到 ``character_id``：有回调用回调，没有就自己写配置落盘。

        独立设置进程里没有桌宠主窗口可回调，写盘后由主窗口的 config watcher 接住；
        失败也不静默——按钮状态不变就是没切成，日志里能查到原因。
        """
        if not character_id or character_id == self._current:
            return
        try:
            if self._on_switch is not None:
                self._on_switch(character_id)
            else:
                self._config.set("character", character_id)
                self._config.save()
        except Exception:      # noqa: BLE001 - 切角色失败不该掀翻设置页
            _LOG.warning("切换角色失败: %s", character_id, exc_info=True)
            return
        self.refresh()


def build_content(dialog, *, on_switch: Callable[[str], None] | None = None) -> QWidget:
    """给 ``ModernSettingsDialog`` 用的入口：页面直接挂在对话框下，与其它域页一致。"""
    return MyCharactersPage(dialog.config, on_switch=on_switch, parent=dialog)
