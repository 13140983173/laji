"""桌宠自己的模型 → 引擎 `config.toml` 里的 `[[model.profiles]]` 镜像。

为什么需要这一层：引擎在线时桌宠的对话交给引擎跑（见 ``agent_link.LajiRunService``），
引擎只认 `config.toml` 的 profile，不认桌宠 `config.json` 的 ``chat.providers``。
两边是**两套模型**，所以这里只写自己的 managed block（名字统一 ``pet-`` 前缀），
并且**绝不写** ``[model.routing.*]`` —— 那条路由属于 agent 视图，桌宠只按名字点名
自己的 profile（``ModelSpec.profile``），改哪边都不影响另一边。

API Key 不进这个文件：写盘的是公开字段，key 走 daemon 的 ``SetModelKey``
（只进 daemon 内存，不落盘、不回写 config.toml）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from .providers import gateway_extra_headers

BEGIN = "# >>> laji-pet-model-profiles (managed by laji-pet)"
END = "# <<< laji-pet-model-profiles"
# daemon 校验 profile 名是 [A-Za-z0-9_-]+（见 laji-agent user-models.ts）
PROFILE_PREFIX = "pet-"
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9_-]+")
WIRE_PROVIDER = "openai_compatible"


def engine_config_path() -> Path:
    """引擎读的那份 config.toml（与 daemon 同一套目录规则）。"""
    override = str(os.environ.get("LAJI_CONFIG_DIR") or "").strip()
    if override:
        return Path(override) / "config.toml"
    for var in ("LOCALAPPDATA", "APPDATA"):
        base = str(os.environ.get(var) or "").strip()
        if base:
            return Path(base) / "laji" / "config.toml"
    return Path.home() / ".config" / "laji" / "config.toml"


def profile_name(provider_id: str) -> str:
    slug = _UNSAFE_NAME.sub("-", str(provider_id or "").strip()).strip("-").lower()
    return PROFILE_PREFIX + (slug or "main")


def _toml(value) -> str:
    """基本字符串：转义反斜杠/引号/换行即可，key 与 URL 里不会有更怪的东西。"""
    text = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    text = text.replace("\r", "").replace("\n", "\\n")
    return f'"{text}"'


def render_block(providers) -> str:
    lines = [
        BEGIN,
        "# 桌宠自己的模型：只有桌宠的 Run 会按名字点名（ModelSpec.profile）。",
        "# 不写 [model.routing.*]，agent 视图的模型路由与这份清单互不影响。",
    ]
    for provider in providers:
        lines.append("")
        lines.append("[[model.profiles]]")
        lines.append(f"name = {_toml(profile_name(provider.provider_id))}")
        lines.append(f"provider = {_toml(WIRE_PROVIDER)}")
        lines.append(f"model_id = {_toml(str(provider.model or '').strip())}")
        if str(provider.base_url or "").strip():
            lines.append(f"base_url = {_toml(str(provider.base_url).strip())}")
        lines.append("supports_tools = true")
        headers = gateway_extra_headers(provider.base_url, provider.provider_id)
        if headers:
            pairs = ", ".join(f"{name} = {_toml(value)}" for name, value in headers.items())
            lines.append(f"extra_headers = {{ {pairs} }}")
    lines.append(END)
    return "\n".join(lines) + "\n"


def strip_block(text: str) -> str:
    """去掉本模块的 managed block（含只剩 END 的残缺片段），其余内容原样保留。"""
    out = text
    while True:
        end = out.find(END)
        if end < 0:
            return out
        begin = out.rfind(BEGIN, 0, end)
        if begin >= 0:
            after = end + len(END)
            # 往前吃掉 block 前的空行，避免反复同步时空行越堆越多
            head = out[:begin].rstrip()
            tail = out[after:].lstrip("\n")
            out = f"{head}\n\n{tail}" if head and tail else f"{head}{tail}"
        else:
            out = out[:end]


def sync_profiles(providers, path: Path | None = None) -> bool:
    """把桌宠的模型清单写进 config.toml 的自己那一段；返回是否真的改了文件。

    只替换 managed block，注释、顺序、agent 的 `[[model.profiles]]` 全都不动。
    """
    target = Path(path) if path is not None else engine_config_path()
    try:
        current = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    except OSError:
        return False
    body = strip_block(current).rstrip()
    block = render_block(providers)
    text = f"{body}\n\n{block}" if body else block
    if text == current:
        return False
    tmp = target.with_suffix(target.suffix + ".pet-tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False
    return True
