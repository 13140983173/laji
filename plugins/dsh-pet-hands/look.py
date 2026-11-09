#!/usr/bin/env python3
"""宿主侧的桌面快照：不走模型、不花 token 的那条通道。

server.py 是给模型用的（每调一次都是一轮工具往返）；这个脚本是给**程序**用的：

* 桌宠想「知道你在干嘛」→ 定时跑 `python look.py`，读几行摘要，零 token。
* 想判断该不该搭话、该不该上前 → 看 `--scope windows` 里窗口标题的变化。
* 排查「为什么模型看不见那个按钮」→ 直接 `--json` 看原始结构。

所以这里的输出规则和 server.py 相反：**给人/给脚本看，怎么短怎么来**，
不做 JSON 美化、不落盘、不带任何驱动器黑话。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from server import DriverError, _resolve_target, call_driver

# 摘要里值得出现的字段。驱动器的树结构会随平台/版本变，所以按候选名逐个试。
LABEL_KEYS = ("name", "label", "title", "text", "value", "automation_id")
ROLE_KEYS = ("role", "control_type", "type", "class_name")
# 这些 role 是容器噪音，摘要里去掉——它们占了树的大半且对「在干嘛」毫无信息。
CONTAINER_ROLES = {
    "pane", "group", "custom", "unknown", "client", "window", "root",
    "scrollbar", "titlebar", "title bar", "nonclient", "separator",
}


def _first(node: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def walk(node: Any, out: list[dict[str, str]], limit: int, depth: int = 0) -> None:
    if len(out) >= limit:
        return
    if isinstance(node, dict):
        role = _first(node, ROLE_KEYS)
        label = _first(node, LABEL_KEYS)
        # 根节点的名字通常是窗口标题：「他在干嘛」最要紧的一条，
        # 不能因为 role=window 属于容器而被当成噪音丢掉。
        is_container = role is not None and role.lower() in CONTAINER_ROLES
        if label and (depth == 0 or not is_container):
            entry = {"label": label[:80]}
            if role:
                entry["role"] = role[:40]
            if entry not in out:
                out.append(entry)
        if len(out) >= limit:
            return
        for value in node.values():
            walk(value, out, limit, depth + 1)
    elif isinstance(node, list):
        for value in node:
            # 列表只代表同一层的兄弟节点，不增加深度。
            walk(value, out, limit, depth)


def summarise(payload: Any, limit: int) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    walk(payload, found, limit)
    return found


def markdown_lines(text: str, limit: int) -> list[dict[str, str]]:
    """`tree_markdown` 每行就是一个控件：去掉项目符号和缩进即可。

    elements 模式对同一个 Typora 窗口是 78062 字符，markdown 是 1314——摘要
    只需要「有哪些控件」，没必要为一句话付 60 倍的价钱。
    """
    found: list[dict[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-").strip()
        if not line:
            continue
        found.append({"label": line[:80]})
        if len(found) >= limit:
            break
    return found


def snapshot(scope: str) -> Any:
    """三种 scope 各自的驱动工具。

    `front` **不是** `get_accessibility_tree`：那个工具给的是整桌面（进程 +
    可见窗口），21880 字符就把摘要预算用光，一个控件都轮不到。真正「前台那一个
    窗口」要由 list_windows 选出前台，再向它要树。
    """
    if scope == "windows":
        return call_driver("list_windows", {})
    if scope == "apps":
        return call_driver("list_apps", {})
    target = _resolve_target({})
    payload: dict[str, Any] = {
        "pid": target["pid"],
        "window_id": target["window_id"],
        "include_screenshot": False,
    }
    if scope == "tree":
        payload["tree_format"] = "elements"
    return call_driver("get_window_state", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="桌面快照（宿主侧，零 token）")
    parser.add_argument("--scope", default="front",
                        choices=["front", "windows", "apps", "tree"])
    parser.add_argument("--limit", type=int, default=15, help="摘要最多几条（默认 15）")
    parser.add_argument("--json", action="store_true", help="打印原始 JSON")
    args = parser.parse_args()

    try:
        payload = snapshot(args.scope)
    except DriverError as exc:
        print(f"× {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    markdown = payload.get("tree_markdown") if isinstance(payload, dict) else None
    items = (
        markdown_lines(markdown, args.limit)
        if isinstance(markdown, str)
        else summarise(payload, args.limit)
    )
    if not items:
        print("（没读到可识别的控件；试试 --json 看原始结构）")
        return 0
    for item in items:
        role = item.get("role")
        print(f"- {item['label']}" + (f"  [{role}]" if role else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
