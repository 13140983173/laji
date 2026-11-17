# -*- coding: utf-8 -*-
"""工位弹框里的 Markdown 正文：技能详情 / 包详情预览要排版，不是源码视图。

用户实测反馈：点开一个技能，弹框里铺的还是 ``#`` ``##`` ``- [ ]`` 原文（
那时是 QPlainTextEdit + markdown 高亮器，只是把标记上了色），一页技能读不成文。
这些用例守两件事：只读正文真的过 ``markdown_to_html``；文档里的（）不会被
聊天那套「动作段」渲染成斜体。
"""

import pytest


@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication

    instance = QApplication.instance()
    return instance if instance is not None else QApplication([])


SKILL_MD = """# 三表勾稽与财报解读自查清单

财报结论出门前过一遍。

## 1. 勾稽恒等式

- [ ] 资产 = 负债 + 所有者权益，逐期核对。
- [ ] 期末未分配利润核对（能拿到数据时）。

结论分级：**已确认**。
"""


def _skill_file(tmp_path):
    path = tmp_path / "SKILL.md"
    path.write_text(SKILL_MD, encoding="utf-8")
    return str(path)


def test_skill_view_renders_markdown_not_source(app, tmp_path):
    from PySide6.QtWidgets import QTextBrowser, QWidget

    from pet import workstation_window as w

    host = QWidget()
    view = w._SkillViewDialog(
        host, {"name": "演示", "source": "插件", "path": _skill_file(tmp_path)}
    )
    browser = view.findChild(QTextBrowser)

    assert browser is not None, "技能正文必须走进 QTextBrowser，别再塞回 QPlainTextEdit"
    plain = browser.toPlainText()
    assert plain.splitlines()[0] == "三表勾稽与财报解读自查清单"
    for marker in ("# ", "## ", "- [ ]", "**"):
        assert marker not in plain
    # 排版掉了，文字本身一个都不能少。
    assert "资产 = 负债 + 所有者权益，逐期核对。" in plain
    assert "结论分级：已确认。" in plain


def test_skill_view_keeps_empty_body_fallback(app):
    from PySide6.QtWidgets import QTextBrowser, QWidget

    from pet import workstation_window as w

    host = QWidget()
    view = w._SkillViewDialog(host, {"name": "演示", "source": "插件", "path": ""})
    browser = view.findChild(QTextBrowser)

    assert browser is not None
    assert "这份技能没有正文。" in browser.toPlainText()


def test_markdown_panel_keeps_brackets_as_notes(app):
    """文档里的（）是注记，不该像聊天那样被点成斜体动作段。"""
    from pet import workstation_window as w
    from pet.chat.markdown_view import markdown_to_html

    text = "期末未分配利润核对（能拿到数据时）再下结论。"
    assert "font-style:italic" in markdown_to_html(text)
    assert "font-style:italic" not in w._markdown_panel(text).toHtml()


def test_markdown_panel_uses_document_style_and_opens_links(app):
    from pet import workstation_window as w

    panel = w._markdown_panel("- 一条\n- 另一条", None, "PackMd")

    assert panel.objectName() == "PackMd"
    assert panel.isReadOnly()
    assert panel.openExternalLinks()
    assert panel.document().blockCount() > 1


def test_pack_preview_renders_markdown_kinds(app):
    """包里的技能/规则/专家正文也是 Markdown 原文，要走排版。"""
    from PySide6.QtWidgets import QTextBrowser

    from pet import workstation_window as w

    for kind in ("skill", "expert", "rule", "contextLayer"):
        preview = w._contribution_preview(kind, "# 标题\n\n- [ ] 核对勾稽\n")
        assert isinstance(preview, QTextBrowser), kind
        assert "- [ ]" not in preview.toPlainText()


def test_pack_preview_keeps_config_as_source(app):
    """连接器那条给的是启动配置（JSON），照旧按源码显示，不能当 Markdown 排版。"""
    from PySide6.QtWidgets import QPlainTextEdit

    from pet import workstation_window as w

    raw = '{"transport": "stdio", "command": "python"}'
    preview = w._contribution_preview("mcp", raw)
    assert isinstance(preview, QPlainTextEdit)
    assert preview.toPlainText() == raw
    assert isinstance(getattr(preview, "_syntax", None), w._JsonHighlighter)


def test_markdown_browser_has_its_own_qss_rule():
    """QSS 落款：等宽那条不能把正文带上，否则中文标题会缺字、正文像 diff。"""
    from pet import workstation_window as w

    assert "QTextBrowser#CapMd{" in w._QSS
    assert "QTextBrowser#PackMd{" in w._QSS
