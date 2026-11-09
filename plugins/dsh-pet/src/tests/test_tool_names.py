"""审批条上的工具名：用户看到的是名字，不是引擎的 wire name。"""

from pet.tool_names import approval_text, tool_display_label


def test_mcp_tool_shows_only_the_tool_itself():
    # 服务名是内部装配信息，正文里只留工具本身（口径同主窗口 toolDisplayLabel）。
    assert tool_display_label("mcp:pet-hands:look") == "look"
    assert tool_display_label("mcp:pet-hands:act") == "act"


def test_builtin_tool_uses_the_same_chinese_name_as_the_main_window():
    assert tool_display_label("builtin:run_terminal") == "运行命令"
    assert tool_display_label("builtin__grep") == "文本搜索"
    assert tool_display_label("builtin:browser_click") == "浏览器操作"


def test_composer_aliases_resolve_to_the_builtin_name():
    assert tool_display_label("shell") == "运行命令"
    assert tool_display_label("read") == "读取文件"


def test_unknown_name_is_passed_through_instead_of_guessed():
    assert tool_display_label("some_new_tool") == "some_new_tool"
    assert tool_display_label("") == ""


def test_approval_text_names_the_tool_once():
    # daemon 的 reason 以工具 id 开头（laji-policy 的 mcp_grant 文案）。
    text = approval_text(
        "mcp:pet-hands:look", "mcp:pet-hands:look 是外部工具，按设置需要逐次授权"
    )

    assert text == "要用 look：外部工具，按设置需要逐次授权"
    assert "mcp:" not in text


def test_approval_text_without_reason_or_tool_stays_readable():
    assert approval_text("mcp:pet-hands:look") == "要用 look"
    assert approval_text("", "", empty="有一步要你点头") == "有一步要你点头"
    assert approval_text("", "沙箱下的联网要逐次确认") == "要继续吗：沙箱下的联网要逐次确认"
