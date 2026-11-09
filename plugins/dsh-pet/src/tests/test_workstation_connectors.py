# -*- coding: utf-8 -*-
"""工坊连接器页：卡片底下那排链接、JSON 编辑框、工具详情。

对齐目标是 agent 的连接器卡（同一套动作、同一份 JSON、同一张工具详情）。
这些用例只碰纯函数与控件，不连引擎。
"""

import json

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    return instance if instance is not None else QApplication([])


def test_tool_chips_clickable_and_folded():
    from pet import workstation_window as w

    tools = [
        {"name": "mcp__pet-hands__look", "description": "看窗口", "schema": "{}"},
        {"name": "mcp__pet-hands__act", "description": "点一下", "schema": "{}"},
        {"name": "mcp__pet-hands__screen", "description": "截图", "schema": "{}"},
        {"name": "mcp__pet-hands__raw", "description": "原生", "schema": "{}"},
    ]

    chips = w._tool_chips(tools, "pet-hands")

    assert [c.get("text") if isinstance(c, dict) else c for c in chips] == [
        "mcp__pet-hands__look",
        "mcp__pet-hands__act",
        "mcp__pet-hands__screen",
        "+1",
    ]
    # 每颗胶囊都点得开：前三个是工具详情，`+1` 是剩下的清单。
    assert callable(chips[0]["click"])
    assert chips[0]["tip"] == "看窗口"
    assert chips[-1]["text"] == "+1"
    assert callable(chips[-1]["click"])
    assert "1 条工具" in chips[-1]["tip"]


def test_folded_chip_opens_the_rest(monkeypatch):
    """`+N` 上一版是 QLabel，看着能点其实点不动；现在它得真的报出剩下那几条。"""
    from pet import workstation_window as w

    tools = [{"name": f"mcp__s__t{i}", "description": "", "schema": "{}"} for i in range(5)]
    seen = []
    monkeypatch.setattr(w, "_open_tool_list", lambda items, server: seen.append((items, server)))

    chips = w._tool_chips(tools, "s")
    chips[-1]["click"]()

    assert len(seen) == 1
    items, server = seen[0]
    assert server == "s"
    assert [one["name"] for one in items] == ["mcp__s__t3", "mcp__s__t4"]


def test_text_kind_sniffs_json_log_and_markdown():
    from pet import workstation_window as w

    assert w._text_kind('{"a": 1}') == "json"
    assert w._text_kind("[mcp] state: online") == "log"
    assert w._text_kind("[err] boom") == "log"
    assert w._text_kind("# 标题\n- 一条") == "markdown"
    assert w._text_kind("   ") == "plain"


def test_dialogs_keep_a_visible_close_button(app):
    """无边框弹窗没有系统标题栏：工具详情 / 清单 / 只读技能都得自带一个×。"""
    from PySide6.QtWidgets import QWidget

    from pet import workstation_window as w

    host = QWidget()
    host.resize(900, 560)
    tool = {"name": "mcp__pet-hands__look", "description": "看", "schema": '{"type": "object"}'}

    detail = w._McpToolDetailDialog(host, tool, "pet-hands")
    assert detail.close_button.toolTip() == "关闭"
    # 高度不能超过宿主窗口，否则底部按钮被挤到窗口外。
    assert detail.height() <= host.height()

    listing = w._McpToolListDialog(host, [tool], "pet-hands")
    assert listing.row_count == 1
    assert listing.picked is None

    view = w._SkillViewDialog(host, {"name": "演示", "source": "plugin:x", "path": ""})
    assert view.close_button.toolTip() == "关闭"


def test_schema_json_is_highlighted(app):
    from PySide6.QtWidgets import QWidget

    from pet import workstation_window as w

    host = QWidget()
    tool = {"name": "look", "description": "", "schema": '{"type": "object"}'}
    dialog = w._McpToolDetailDialog(host, tool, "pet-hands")

    assert isinstance(getattr(dialog._json, "_syntax", None), w._JsonHighlighter)


def test_tool_chips_empty_when_no_tools():
    from pet import workstation_window as w

    assert w._tool_chips([], "pet-hands") == []


def test_connector_log_text_matches_agent_fields():
    from pet import workstation_window as w

    runtime = {
        "state": "ready",
        "transport": "stdio",
        "tool_count": 5,
        "last_refresh_ms": 1700000000000,
    }
    text = w._connector_log_text(
        "pet-hands",
        {"enabled": True, "transport": "stdio", "command": "python", "args": ["-m", "x"]},
        runtime,
        [{"name": "mcp__pet-hands__look"}],
    )

    assert text.splitlines()[0] == "[mcp] connector: pet-hands"
    assert "online" in text
    assert "[mcp] command: python -m x" in text
    assert "[tools] registered: 5" in text
    assert "mcp__pet-hands__look" in text


def test_connector_log_text_reports_error():
    from pet import workstation_window as w

    text = w._connector_log_text(
        "pet-hands",
        {"enabled": True},
        {"transport": "stdio", "tool_count": 5, "error": "boom"},
        [],
    )

    assert "failed" in text
    assert "[err] boom" in text


def test_connector_log_text_without_runtime_says_pending():
    from pet import workstation_window as w

    text = w._connector_log_text("pet-hands", {"enabled": True, "url": "http://x/mcp"}, {}, [])

    assert "pending (no runtime snapshot)" in text
    assert "http://x/mcp" in text


def test_json_dialog_shows_raw_entry_and_parses_it(app, monkeypatch, tmp_path):
    from pet import workstation_window as w
    from pet.agent_link import pet_toolkit

    monkeypatch.setattr(pet_toolkit, "daemon_config_dir", lambda: str(tmp_path))
    (tmp_path / "mcp-custom.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "pet-hands": {
                        "command": "python",
                        "args": ["server.py"],
                        "headers": {"A": "1"},
                        "disabled_tools": ["mcp__pet-hands__raw"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    dialog = w._ConnectorDialog(None, {"name": "pet-hands"})
    body = json.loads(dialog.body.toPlainText())

    # 表单化会吃掉 headers / disabled_tools —— JSON 编辑框必须原样带着。
    assert body["pet-hands"]["headers"] == {"A": "1"}
    assert body["pet-hands"]["disabled_tools"] == ["mcp__pet-hands__raw"]

    payload = dialog.payload()
    assert payload == {
        "name": "pet-hands",
        "entry": body["pet-hands"],
        "rename_from": "pet-hands",
    }


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"a": {"url": "u"}, "b": {"url": "u"}}',
        '{"bad name": {"url": "u"}}',
        '{"a": "not-an-object"}',
        '{"a": {"args": []}}',
    ],
)
def test_json_dialog_rejects_bad_input(app, text):
    from pet import workstation_window as w

    dialog = w._ConnectorDialog(None, None)
    dialog.body.setPlainText(text)

    assert dialog.payload() is None
    assert dialog._error.isVisibleTo(dialog)
