# -*- coding: utf-8 -*-
"""工具显示名：审批条、提醒气泡里给用户看的名字——wire name 不进正文。

口径与主窗口同一套（``packages/laji-client-core/src/shared/args.ts`` 的
``toolDisplayLabel``）：内置工具用中文名，MCP 工具剥掉 ``mcp:<server>:`` 只留
工具本身；都不认识就原样返回——宁可见编码，也不猜一个错名字。
"""
from __future__ import annotations

#: 厂商 wire name → 内部 id（与 args.ts 的 ``COMPOSER_WIRE_ALIASES`` 同表）。
_WIRE_ALIASES = {
    "read": "builtin:read_file",
    "ls": "builtin:list_dir",
    "glob": "builtin:glob",
    "grep": "builtin:grep",
    "write": "builtin:write_file",
    "edit": "builtin:apply_patch",
    "edit_files": "builtin:edit_files",
    "delete": "builtin:delete_file",
    "rename": "builtin:rename_file",
    "shell": "builtin:run_terminal",
}

#: 内置工具中文名（与 laji-ui ``i18n/zh-CN.ts`` 的 ``toolName.*`` 同文案）。
_BUILTIN_NAMES = {
    "list_dir": "浏览目录",
    "glob": "查找文件",
    "grep": "文本搜索",
    "read_file": "读取文件",
    "read_tool_artifact": "读取工具输出",
    "edit_notebook": "编辑 Notebook",
    "web_search": "网页搜索",
    "web_fetch": "抓取网页",
    "browser": "浏览器操作",
    "apply_patch": "编辑文件",
    "edit_files": "编辑文件",
    "write_file": "写入文件",
    "delete_file": "删除文件",
    "rename_file": "重命名文件",
    "generate_image": "生成图片",
    "run_terminal": "运行命令",
    "read_cleared_result": "取回已清理结果",
}

#: 浏览器四件套共用一个名字（同 args.ts 的 ``TOOL_LABEL_KEYS``）。
_BROWSER_TOOLS = ("browser_navigate", "browser_snapshot", "browser_click", "browser_type")


def normalize_wire_tool_name(tool_name: str) -> str:
    """厂商 wire name（``builtin__grep`` / ``shell``）→ 内部 id（``builtin:grep``）。"""
    name = str(tool_name or "").strip()
    if name.startswith("builtin:"):
        return name
    if name.startswith("builtin__"):
        return f"builtin:{name[len('builtin__'):]}"
    if name.startswith("builtin_"):
        return f"builtin:{name[len('builtin_'):]}"
    return _WIRE_ALIASES.get(name, name)


def tool_short_name(tool_name: str) -> str:
    """剥掉 ``builtin:`` 前缀（MCP 的 ``mcp:server:tool`` 原样保留短名由调用方决定）。"""
    internal = normalize_wire_tool_name(tool_name)
    return internal[len("builtin:"):] if internal.startswith("builtin:") else internal


def tool_display_label(tool_name: str) -> str:
    """给用户看的工具名：内置工具中文名，MCP 工具只留工具本身，其余原样。

    ``mcp:pet-hands:look`` → ``look``（服务名是内部装配信息，进正文只会让人猜）；
    ``builtin:run_terminal`` → ``运行命令``。
    """
    internal = normalize_wire_tool_name(tool_name)
    if internal.startswith("mcp:"):
        rest = internal[len("mcp:"):]
        sep = rest.rfind(":")
        return rest[sep + 1:] if sep >= 0 else rest
    if internal.startswith("builtin:"):
        short = internal[len("builtin:"):]
        if short in _BUILTIN_NAMES:
            return _BUILTIN_NAMES[short]
        if short in _BROWSER_TOOLS:
            return _BUILTIN_NAMES["browser"]
        return short
    return internal


def approval_text(tool_name: str, reason: str = "", *, empty: str = "要继续吗") -> str:
    """审批条正文：「要用 <名字>：<为什么>」。

    daemon 的 reason 以工具 id 开头（``laji-policy`` 里
    ``format!("{} 是外部工具，按设置需要逐次授权", tool_name)``）：名字已经在
    前半句说过，这里去掉重复的那一段——同一个编码别在一行里出现两次。
    """
    raw = str(tool_name or "").strip()
    name = tool_display_label(raw)
    body = " ".join(str(reason or "").split())
    if raw and body.startswith(raw):
        body = body[len(raw):].lstrip(" ：:，,")
        if body.startswith("是"):
            body = body[1:].lstrip(" ，,")
    head = f"要用 {name}" if name else empty
    return f"{head}：{body}" if body else head


def approval_headline(tool_name: str, *, empty: str = "有一步要你点头") -> str:
    """审批条的标题句：「要用 <名字>」。只留人话，不带原因。"""
    name = tool_display_label(str(tool_name or "").strip())
    return f"要用 {name}" if name else empty


def approval_detail(
    tool_name: str, reason: str = "", *, fallback: str = "按设置需要你逐次授权"
) -> str:
    """审批条的次要一行：原因里含中文才给人看，英文原文不进正文（留给悬停）。

    daemon 的默认原因是英文（``write tool builtin:write_file requires approval``），
    摆进正文只是一行谁也读不下去的编码；换成一句中文说明。
    """
    raw = str(tool_name or "").strip()
    body = " ".join(str(reason or "").split())
    # daemon 可能写全名（builtin:web_fetch）也可能只写短名（web_fetch），两种都剥。
    for prefix in (raw, raw.rsplit(":", 1)[-1]):
        if prefix and body.startswith(prefix):
            body = body[len(prefix) :].lstrip(" ：:，,")
            if body.startswith("是"):
                body = body[1:].lstrip(" ，,")
            break
    if body and any("\u4e00" <= ch <= "\u9fff" for ch in body):
        return body
    return fallback
