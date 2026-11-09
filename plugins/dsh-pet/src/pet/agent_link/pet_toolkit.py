"""宠物家自己的能力清单：技能 / 连接器 / 能力包。

三个页面只读宠物家（``<userData>/Pet/<角色 id>``），默认不碰 agent 的配置目录 ——
这是"和 agent 独立"的落点。任何文件缺失、格式不对都返回空表，让页面显示空态，
而不是把异常抛到 UI 线程。

连接器也一样：她自己的清单是 ``<home>/.laji/pet-mcp.json``，而宠物 Run 的
``workspace_root`` 就是这个 ``<home>`` —— 引擎按工作区读同一个文件，只挂到她
自己的 Run 上，agent 视图那份 ``mcp-custom.json`` 一个字不动。唯一要读 agent
目录的地方是首次启动的那次迁移（``ensure_imported_from_agent``），只读不写。
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
from typing import Any

from .pet_space import pet_workspace_root

log = logging.getLogger(__name__)

SKILL_FILE = "SKILL.md"
MCP_FILE = "pet-mcp.json"
DISABLED_SUFFIX = ".disabled"
#: 导入进来的条目打这个标（旧文件里写过 ``agent``，读的时候一并归一）。
IMPORTED_SOURCE = "imported"
#: 宠物自己那个插件包不列进工坊：装它就是把自己再复制一份。
SELF_PACK_ID = "com.nerve.dsh-pet"

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_TOML_NAME = re.compile(r'^\s*name\s*=\s*"([^"]*)"', re.M)
_TOML_VERSION = re.compile(r'^\s*version\s*=\s*"([^"]*)"', re.M)
_TOML_ID = re.compile(r'^\s*id\s*=\s*"([^"]*)"', re.M)
_TOML_DESC = re.compile(r'^\s*description\s*=\s*"([^"]*)"', re.M)


def pet_home(character: str = "") -> str:
    """宠物家根目录；建不出来时是空串（页面据此显示"还没安顿下来"）。"""
    try:
        return pet_workspace_root(character) or ""
    except Exception:
        return ""


def _skills_dir(home: str) -> str:
    return os.path.join(home, ".laji", "skills")


def skills_root(character: str = "", home: str = "") -> str:
    """宠物家的技能目录（给「打开技能目录」用）。"""
    home = home or pet_home(character)
    return _skills_dir(home) if home else ""


def packs_root(character: str = "", home: str = "") -> str:
    """宠物家的能力包目录。"""
    home = home or pet_home(character)
    return os.path.join(home, "plugins") if home else ""


def skill_body(path: str) -> str:
    """技能正文（去掉 front matter），编时回填用。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(65536)
    except OSError:
        return ""
    match = _FRONT_MATTER.match(text)
    return (text[match.end():] if match else text).strip()


def _read_front_matter(path: str) -> dict[str, str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return {}
    match = _FRONT_MATTER.match(head)
    if not match:
        return {}
    out: dict[str, str] = {}
    lines = match.group(1).splitlines()
    for index, line in enumerate(lines):
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        value = value.strip()
        if value[:1] in (">", "|"):
            # YAML 折叠/字面块：真正的说明在下面缩进行里，不能只剩一个「>-」。
            parts: list[str] = []
            for rest in lines[index + 1 :]:
                if not rest.strip():
                    if parts:
                        break
                    continue
                if not rest.startswith((" ", "\t")):
                    break
                parts.append(rest.strip())
            value = ("".join(parts) if value.startswith(">") else " ".join(parts)).strip()
        out[key.strip().lower()] = value.strip("\"'")
    return out


def _normalise_source(value: Any) -> str:
    """来源标记归一：旧文件里写过的 ``agent`` 现在统一当「导入」。"""
    text = str(value or "").strip()
    return IMPORTED_SOURCE if text == "agent" else text


def _skill_one(folder: str, enabled: bool) -> dict[str, Any] | None:
    path = os.path.join(folder, SKILL_FILE)
    if not os.path.isfile(path):
        return None
    meta = _read_front_matter(path)
    name = meta.get("name") or os.path.basename(folder).replace(DISABLED_SUFFIX, "")
    return {
        "name": name,
        "description": meta.get("description") or "",
        "source": _normalise_source(meta.get("source")),
        "path": path,
        "enabled": enabled,
    }


#: 技能开关的真相：``<config>/skills-registry.json`` 的 ``overrides``（与桌面端共用）。
SKILLS_REGISTRY_FILE = "skills-registry.json"
SCOPE_WORKSPACE = "workspace"
SCOPE_GLOBAL = "global"


def daemon_skills_dir() -> str:
    """引擎的全局技能目录（``<config>/skills/``）：桌面端「技能」页读写的也是这份。"""
    return os.path.join(daemon_config_dir(), "skills")


def _skill_registry() -> dict[str, Any]:
    """读 ``skills-registry.json``；读到坏文件当空表，不挡住页面。"""
    path = os.path.join(daemon_config_dir(), SKILLS_REGISTRY_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _write_skill_registry(doc: dict[str, Any]) -> bool:
    path = os.path.join(daemon_config_dir(), SKILLS_REGISTRY_FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_json(path, doc)
    except OSError as exc:
        log.info("技能：写不了 skills-registry.json（%s）", exc)
        return False
    return True


def _skill_disabled_keys() -> set[str]:
    """引擎只认显式 ``enabled: false``；缺省一律算开（没登记过的技能不能凭空消失）。"""
    overrides = _skill_registry().get("overrides")
    if not isinstance(overrides, dict):
        return set()
    return {
        str(key)
        for key, value in overrides.items()
        if isinstance(value, dict) and value.get("enabled") is False
    }


def _skill_folders(root: str) -> list[tuple[str, bool]]:
    """一份技能目录里的各条：``(folder, 是不是旧的 .disabled 形态)``。"""
    out: list[tuple[str, bool]] = []
    if not root or not os.path.isdir(root):
        return out
    for entry in sorted(os.listdir(root)):
        folder = os.path.join(root, entry)
        if not os.path.isdir(folder):
            continue
        if os.path.isfile(os.path.join(folder, SKILL_FILE)):
            out.append((folder, entry.endswith(DISABLED_SUFFIX)))
            continue
        buried = os.path.join(folder, ".disabled")
        if os.path.isdir(buried):
            out.extend(
                (os.path.join(buried, inner), True)
                for inner in sorted(os.listdir(buried))
                if os.path.isdir(os.path.join(buried, inner))
            )
    return out


def skills(character: str = "", home: str = "") -> list[dict[str, Any]]:
    """模型真正看得到的技能：她家 ``.laji/skills`` ＋ 引擎全局 ``<config>/skills``。

    口径跟 ``crates/laji-context/src/skills.rs`` 一一对应：两份目录取并集，同名以她家
    为准（她那排 run 的 workspace 就是她家），开没开只看 ``skills-registry.json`` 的
    ``overrides``——所以开关也写那一份，页面与模型不会再各算一套。
    """
    home = home or pet_home(character)
    disabled = _skill_disabled_keys()
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope, root in (
        (SCOPE_WORKSPACE, _skills_dir(home) if home else ""),
        (SCOPE_GLOBAL, daemon_skills_dir()),
    ):
        for folder, buried in _skill_folders(root):
            one = _skill_one(folder, not buried)
            if not one:
                continue
            name = str(one.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            key = f"{scope}:{name}"
            one["enabled"] = bool(one.get("enabled")) and key not in disabled
            one["scope"] = scope
            one["registry_key"] = key
            out.append(one)
    out.sort(key=lambda s: str(s.get("name") or ""))
    return out


def _unbury_skill(home: str, name: str) -> None:
    """把旧的 ``.disabled`` 目录名收回正常形态；开关状态改由 registry 表达。

    引擎不认那个后缀（照样按目录里的 SKILL.md 加载），留着就等于页面说关、
    模型照用——所以用户第一次碰这个开关时顺手把旧形态收干净。
    """
    root = _skills_dir(home)
    if not root or not os.path.isdir(root):
        return
    for entry in sorted(os.listdir(root)):
        if not entry.endswith(DISABLED_SUFFIX):
            continue
        folder = os.path.join(root, entry)
        skill_file = os.path.join(folder, SKILL_FILE)
        if not os.path.isfile(skill_file):
            continue
        base = entry[: -len(DISABLED_SUFFIX)]
        if name not in (base, _frontmatter_field(skill_file, ("name",))):
            continue
        target = os.path.join(root, base)
        if os.path.exists(target):
            return
        try:
            os.rename(folder, target)
        except OSError:
            log.debug("技能：%s 收不回正常目录名", folder, exc_info=True)
        return


def _pick_servers(payload: Any) -> dict[str, Any]:
    """``pet-mcp.json`` 可能是 ``{mcpServers:{...}}`` / ``{servers:{...}}`` / 直接一张表。"""
    if not isinstance(payload, dict):
        return {}
    for key in ("mcpServers", "servers", "mcp"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            return inner
    return {k: v for k, v in payload.items() if isinstance(v, (dict, str))}


def _transport_of(spec: Any) -> str:
    if isinstance(spec, str):
        return "http" if spec.startswith("http") else "stdio"
    if not isinstance(spec, dict):
        return "stdio"
    kind = str(spec.get("type") or spec.get("transport") or "").lower()
    if kind in ("http", "streamable-http", "sse"):
        return "http"
    if kind in ("stdio", "command"):
        return "stdio"
    return "http" if spec.get("url") else "stdio"


def connectors(character: str = "", home: str = "") -> list[dict[str, Any]]:
    """宠物家登记的 MCP 连接器。``state`` 只知道配置层：``on`` / ``off``。

    真实连没连上要问引擎（``ListMcpServers``）；没引擎时页面就按配置显示。
    """
    home = home or pet_home(character)
    if not home:
        return []
    path = os.path.join(home, ".laji", MCP_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return []
    out: list[dict[str, Any]] = []
    for name, spec in sorted(_pick_servers(payload).items()):
        if isinstance(spec, dict) and spec.get("enabled") is False:
            enabled = False
        else:
            enabled = True
        out.append(
            {
                "name": name,
                "transport": _transport_of(spec),
                "enabled": enabled,
                "state": "on" if enabled else "off",
                "detail": _detail_of(spec),
                "source": _normalise_source(spec.get("source") if isinstance(spec, dict) else ""),
                "url": str(spec.get("url") or "") if isinstance(spec, dict) else "",
                "command": str(spec.get("command") or "") if isinstance(spec, dict) else "",
                "args": [str(a) for a in (spec.get("args") or []) if a] if isinstance(spec, dict) else [],
            }
        )
    return out


def _detail_of(spec: Any) -> str:
    """卡片上那行地址：http 给 url，stdio 给 command + args。"""
    if isinstance(spec, str):
        return spec
    if not isinstance(spec, dict):
        return ""
    if spec.get("url"):
        return str(spec["url"])
    parts = [str(spec.get("command") or "")]
    parts += [str(a) for a in (spec.get("args") or []) if a]
    return " ".join(p for p in parts if p)


def _pack_summary(folder: str) -> dict[str, Any] | None:
    manifest = os.path.join(folder, "laji.plugin.toml")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, encoding="utf-8", errors="replace") as fh:
            body = fh.read(65536)
    except OSError:
        return None
    name_match = _TOML_NAME.search(body)
    version_match = _TOML_VERSION.search(body)
    id_match = _TOML_ID.search(body)
    desc_match = _TOML_DESC.search(body)
    # 官方内置包都挂在 ``com.nerve.`` 下；第三方包没这个前缀，就不打标签。
    bundled = bool(id_match and id_match.group(1).startswith("com.nerve."))
    return {
        "name": (name_match.group(1) if name_match else os.path.basename(folder)),
        "version": version_match.group(1) if version_match else "",
        "description": desc_match.group(1) if desc_match else "",
        "bundled": bundled,
        "skills": len(re.findall(r"\[\[contributions\.skills\]\]", body)),
        "mcp": len(re.findall(r"\[\[contributions\.mcp", body)),
        "path": folder,
    }


def packs(character: str = "", home: str = "") -> list[dict[str, Any]]:
    """宠物家 ``plugins/`` 下已经解包的能力包。"""
    home = home or pet_home(character)
    if not home:
        return []
    root = os.path.join(home, "plugins")
    if not os.path.isdir(root):
        return []
    out: list[dict[str, Any]] = []
    for entry in sorted(os.listdir(root)):
        folder = os.path.join(root, entry)
        if not os.path.isdir(folder):
            continue
        one = _pack_summary(folder)
        if one:
            out.append(one)
    return out


def _write_json(path: str, payload: Any) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def set_connector_enabled(name: str, enabled: bool, character: str = "", home: str = "") -> bool:
    """启停一个连接器：只改宠物家的 ``pet-mcp.json``，不动 agent 的 ``mcp-custom.json``。"""
    home = home or pet_home(character)
    if not home:
        return False
    path = os.path.join(home, ".laji", MCP_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    table: Any = payload
    for key in ("mcpServers", "servers", "mcp"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            table = inner
            break
    spec = table.get(name) if isinstance(table, dict) else None
    if not isinstance(spec, dict):
        return False
    spec["enabled"] = bool(enabled)
    if enabled:
        spec.pop("disabled", None)
    else:
        spec["disabled"] = True
    try:
        _write_json(path, payload)
    except OSError:
        return False
    # 关掉的条目就撒回它的免审批规则：她不会再调到它，留着等于白放行。
    if enabled:
        grant_daemon_connector_tools([name])
    else:
        revoke_daemon_connector_tools([name])
    return True


def daemon_config_dir() -> str:
    """引擎的配置目录（``laji_core::config_dir()``）：``LAJI_CONFIG_DIR`` 优先。"""
    override = (os.environ.get("LAJI_CONFIG_DIR") or "").strip()
    if override:
        return override
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if os.name == "nt":
        base = local or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, "laji")
    return os.path.join(os.path.expanduser("~"), ".local", "share", "laji")


def _python_exe() -> str:
    """``${python}`` 落成真路径。

    桌宠自己若跑在打包 exe 里，``sys.executable`` 不是解释器；这时按宿主相同的
    顺序找系统 Python（3.12 优先）。都找不到就返回空串——宁可不登记，也不要
    登记一条注定 ``program not found`` 的连接器。
    """
    override = (os.environ.get("LAJI_PYTHON") or "").strip()
    if override:
        return override
    exe = sys.executable or ""
    if os.path.basename(exe).lower().startswith("python"):
        return exe
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found:
            return found
    if os.name != "nt":
        return ""
    roots: list[str] = []
    local = (os.environ.get("LOCALAPPDATA") or "").strip()
    if local:
        roots.append(os.path.join(local, "Programs", "Python"))
    program_files = (os.environ.get("ProgramFiles") or "").strip()
    if program_files:
        roots.append(program_files)
    hits: list[tuple[int, str]] = []
    for folder in roots:
        if not os.path.isdir(folder):
            continue
        for entry in os.listdir(folder):
            match = re.fullmatch(r"Python(3\d{2})", entry, re.I)
            if not match:
                continue
            candidate = os.path.join(folder, entry, "python.exe")
            if os.path.isfile(candidate):
                hits.append((int(match.group(1)), candidate))
    if not hits:
        return ""
    hits.sort(key=lambda pair: (pair[0] != 312, pair[0]))
    return hits[0][1]


def _owner_of(entry: Any) -> str:
    """条目是哪个包声明的；不是包声明的返回空串。"""
    if not isinstance(entry, dict):
        return ""
    source = entry.get("source")
    if isinstance(source, dict) and str(source.get("kind") or "") == "plugin":
        return str(source.get("id") or "")
    return ""


# -- 外部工具免逐次授权 -----------------------------------------------------
#
# 引擎默认 ``security.mcp_grant = true``：每个 ``mcp:<server>:<tool>`` 调用都要过一次
# 审批。桌宠发起的 run 停在 ``AWAITING_APPROVAL`` 就没人接这张审批卡，她会一直等到
# 超时、拿不到任何结果 —— 用户看到的就是「插件装好了，她还是说自己没有手」。
#
# 「装好即启用」因此不只是登记 server，还要把 ``tool:mcp:<name>:*`` 写进
# ``config.toml`` 的 ``[permissions].allow``：那是引擎唯一认的免审批逃生口。

PERMISSIONS_FILE = "config.toml"
PERMISSIONS_SECTION = "permissions"
#: 插件安装的连接器一定跑在这个目录下 —— 用它认出历史条目（那时还没写 ``source``）。
PLUGIN_INSTALL_HINT = "plugins"
#: 写完 ``config.toml`` 是否顺手让引擎换芯；测试把配置目录指到 tmp 时必须关掉。
_RELOAD_ENGINE = True


def grant_rule(name: str) -> str:
    """一个连接器的免审批规则（覆盖它的全部工具）。"""
    return f"tool:mcp:{name}:*"


def _section_bounds(lines: list[str], section: str) -> tuple[int, int] | None:
    """``[section]`` 的 (表头行, 段尾行)；段尾是不属于它的第一行。"""
    for index, line in enumerate(lines):
        table = _TABLE.match(line)
        if table and table.group(1).strip() == section:
            end = len(lines)
            for probe in range(index + 1, len(lines)):
                if _TABLE.match(lines[probe]) or _ARRAY_TABLE.match(lines[probe]):
                    end = probe
                    break
            return index, end
    return None


def _allow_span(lines: list[str], start: int, end: int) -> tuple[int, int, list[str]] | None:
    """段内 ``allow = [...]`` 的行区间与现有规则（单行、多行都认）。"""
    for index in range(start, end):
        if not re.match(r"^\s*allow\s*=", lines[index]):
            continue
        last = index
        buffer = lines[index]
        while "]" not in buffer and last + 1 < end:
            last += 1
            buffer += "\n" + lines[last]
        return index, last + 1, _QUOTED.findall(buffer)
    return None


def _write_permission_allow(rules: list[str]) -> bool:
    """把规则表写回 ``[permissions].allow``；其余内容（含注释与托管块）原样保留。"""
    path = os.path.join(daemon_config_dir(), PERMISSIONS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError as exc:
        log.info("连接器：读不到 config.toml（%s）", exc)
        return False
    rendered = "allow = [" + ", ".join(json.dumps(one, ensure_ascii=False) for one in rules) + "]"
    bounds = _section_bounds(lines, PERMISSIONS_SECTION)
    if bounds is None:
        lines.extend(["", f"[{PERMISSIONS_SECTION}]", rendered])
    else:
        start, end = bounds
        span = _allow_span(lines, start, end)
        if span is None:
            insert_at = end
            while insert_at > start + 1 and not lines[insert_at - 1].strip():
                insert_at -= 1
            lines.insert(insert_at, rendered)
        else:
            lines[span[0] : span[1]] = [rendered]
    body = "\n".join(lines) + "\n"
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(body)
        os.replace(tmp, path)
    except OSError as exc:
        log.info("连接器：写不了 config.toml（%s）", exc)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False
    _reload_engine_governance()
    return True


def _reload_engine_governance() -> None:
    """让引擎重建治理链 —— 不重载的话，刚写的 allow 规则只在下次启动 daemon 才生效。

    ``_RELOAD_ENGINE`` 是给测试的闸门：fixture 把配置目录指到 tmp 时，重载等于拿空
    配置去换用户真引擎的芯，绝不能在单测里发生。
    """
    if not _RELOAD_ENGINE:
        return
    try:
        from . import daemon_client

        client = daemon_client.LajiDaemonClient(timeout=8.0)
        try:
            if client.connect():
                client.reload_local_config()
        finally:
            client.close()
    except Exception:  # noqa: BLE001
        log.info("连接器：免审批规则已落盘，但热重载没成功（下次启动生效）")


def grant_daemon_connector_tools(names: list[str]) -> list[str]:
    """把这些连接器的工具加进免审批名单，返回真正新加的规则。"""
    wanted = [name.strip() for name in names if name and name.strip()]
    if not wanted:
        return []
    path = os.path.join(daemon_config_dir(), PERMISSIONS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        lines = []
    bounds = _section_bounds(lines, PERMISSIONS_SECTION)
    span = _allow_span(lines, *bounds) if bounds else None
    current = list(span[2]) if span else []
    added = [rule for rule in (grant_rule(name) for name in wanted) if rule not in current]
    if not added:
        return []
    return added if _write_permission_allow([*current, *added]) else []


def revoke_daemon_connector_tools(names: list[str]) -> list[str]:
    """撤掉这些连接器的免审批规则，返回真正删掉的规则。"""
    doomed = {grant_rule(name.strip()) for name in names if name and name.strip()}
    if not doomed:
        return []
    path = os.path.join(daemon_config_dir(), PERMISSIONS_FILE)
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return []
    bounds = _section_bounds(lines, PERMISSIONS_SECTION)
    span = _allow_span(lines, *bounds) if bounds else None
    if span is None:
        return []
    current = list(span[2])
    kept = [rule for rule in current if rule not in doomed]
    removed = [rule for rule in current if rule in doomed]
    if not removed:
        return []
    return removed if _write_permission_allow(kept) else []


def _is_plugin_connector(name: str, entry: Any) -> bool:
    """这条连接器是不是某个插件装进来的（老条目没写 ``source``，看安装路径）。"""
    if _owner_of(entry):
        return True
    if not isinstance(entry, dict):
        return False
    blob = " ".join(
        [str(entry.get("command") or ""), *(str(a) for a in (entry.get("args") or []))]
    ).replace("/", os.sep)
    # 插件装的连接器一定跑在引擎配置目录的 plugins/ 下。
    root = os.path.join(daemon_config_dir(), PLUGIN_INSTALL_HINT)
    return root.replace("/", os.sep) in blob and name in blob


def sync_daemon_connector_grants(character: str = "", home: str = "") -> list[str]:
    """把已装好、但还没进免审批名单的插件连接器补上。幂等，启动时调一次。

    只看她自己的 ``pet-mcp.json``：这份清单以外的东西是 agent 面的事。
    """
    home = home or pet_home(character)
    if not home:
        return []
    try:
        _path, _payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return []
    names = [
        name
        for name, entry in table.items()
        if _is_plugin_connector(name, entry)
        and not (isinstance(entry, dict) and entry.get("disabled") is True)
    ]
    return grant_daemon_connector_tools(names)


def _write_mcp_doc(home: str, payload: dict) -> bool:
    """写回宠物家那份 ``pet-mcp.json``。"""
    path = os.path.join(home, ".laji", MCP_FILE)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_json(path, payload)
    except OSError as exc:
        log.info("连接器：写不了 pet-mcp.json（%s）", exc)
        return False
    return True


def connector_entry(name: str, character: str = "", home: str = "") -> dict[str, Any]:
    """一条连接器的原始对象 —— 编辑框要照着它显示，字段一个都不能丢。"""
    home = home or pet_home(character)
    name = (name or "").strip()
    if not home or not name:
        return {}
    try:
        _path, _payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return {}
    spec = table.get(name)
    return dict(spec) if isinstance(spec, dict) else {}


def save_connector_entry(
    name: str,
    entry: dict[str, Any],
    *,
    rename_from: str = "",
    character: str = "",
    home: str = "",
) -> bool:
    """按 JSON 里那份原始对象整条写回 ``pet-mcp.json``：``headers`` / ``env`` /
    ``disabled_tools`` 之类透传字段原样保留，只做「名字合法、是对象、至少有一个
    连法」这三样校验。

    写的是宠物家那份：agent 视图的连接器清单一个字不动。
    """
    home = home or pet_home(character)
    name = (name or "").strip()
    if not home or not name or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return False
    if not isinstance(entry, dict):
        return False
    link = str(entry.get("url") or "").strip()
    cmd = str(entry.get("command") or "").strip()
    if not link and not cmd:
        return False
    try:
        _path, payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return False
    old = (rename_from or "").strip()
    if old and old != name:
        previous = table.pop(old, None)
    else:
        previous = table.get(name)
    written = {str(k): v for k, v in entry.items()}
    # 来源标记跟着条目走：改过的仍是同一个包声明的，卸载时才认得出它。
    if isinstance(previous, dict) and previous.get("source") and not written.get("source"):
        written["source"] = previous["source"]
    table[name] = written
    if not _write_mcp_doc(home, payload):
        return False
    if written.get("disabled") is True:
        revoke_daemon_connector_tools([name])
    else:
        grant_daemon_connector_tools([name])
    return True


def remove_connector(name: str, character: str = "", home: str = "") -> bool:
    """从她自己的清单里删掉一条（agent 视图那份不受影响）。"""
    home = home or pet_home(character)
    name = (name or "").strip()
    if not home or not name:
        return False
    try:
        _path, payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return False
    if name not in table:
        return False
    table.pop(name, None)
    if not _write_mcp_doc(home, payload):
        return False
    revoke_daemon_connector_tools([name])
    return True


def _mcp_doc(home: str) -> tuple[str, dict, dict]:
    """读宠物家那份 ``pet-mcp.json``：返回 (路径, 整份载荷, 存连接器那张表)。"""
    path = os.path.join(home, ".laji", MCP_FILE)
    payload: dict = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8", errors="replace") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise ValueError("pet-mcp.json 顶层不是对象")
        payload = loaded
    table = None
    for key in ("mcpServers", "servers", "mcp"):
        if isinstance(payload.get(key), dict):
            table = payload[key]
            break
    if table is None:
        table = payload.setdefault("mcpServers", {})
    return path, payload, table


def save_connector(
    name: str,
    *,
    transport: str = "stdio",
    url: str = "",
    command: str = "",
    args: list[str] | None = None,
    enabled: bool = True,
    rename_from: str = "",
    character: str = "",
    home: str = "",
) -> bool:
    """新增或改一条连接器 —— 只写宠物家那份，agent 那边一个字不动。"""
    name = (name or "").strip()
    if not name:
        return False
    home = home or pet_home(character)
    if not home:
        return False
    try:
        path, payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return False

    spec: dict = {"enabled": bool(enabled)}
    if transport == "http":
        link = (url or "").strip()
        if not link:
            return False
        spec.update({"type": "http", "url": link})
    else:
        cmd = (command or "").strip()
        if not cmd:
            return False
        spec.update({"command": cmd, "args": [str(a).strip() for a in (args or []) if str(a).strip()]})

    old = (rename_from or "").strip()
    if old and old != name:
        previous = table.get(old)
        table.pop(old, None)
    else:
        previous = table.get(name)
    # 来源标记跟着条目走：改过的仍是「来自 agent 的副本」，不是正在同步的东西。
    if isinstance(previous, dict) and previous.get("source"):
        spec["source"] = previous["source"]
    table[name] = spec

    try:
        os.makedirs(os.path.join(home, ".laji"), exist_ok=True)
        _write_json(path, payload)
    except OSError:
        return False
    return True


def remove_connector(name: str, character: str = "", home: str = "") -> bool:
    """删掉一条连接器 —— 同上，只管宠物家这份文件。"""
    home = home or pet_home(character)
    if not home or not (name or "").strip():
        return False
    try:
        path, payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return False
    if name not in table:
        return False
    table.pop(name, None)
    try:
        _write_json(path, payload)
    except OSError:
        return False
    return True


def set_skill_enabled(name: str, enabled: bool, character: str = "", home: str = "") -> bool:
    """开/关一条技能：写引擎那份 ``skills-registry.json``，不删文件。

    与桌面端「技能」页共用同一个状态；只改目录名的老做法收掉了——引擎不认
    ``.disabled`` 后缀，页面说关了、模型照用，那才是真正的不同步。
    """
    name = (name or "").strip()
    home = home or pet_home(character)
    if not name or not home:
        return False
    target = next((s for s in skills(home=home) if str(s.get("name") or "") == name), None)
    if target is None:
        return False
    scope = str(target.get("scope") or SCOPE_WORKSPACE)
    key = str(target.get("registry_key") or f"{scope}:{name}")
    if scope == SCOPE_WORKSPACE:
        _unbury_skill(home, name)
    doc = _skill_registry()
    overrides = doc.get("overrides")
    if not isinstance(overrides, dict):
        overrides = {}
        doc["overrides"] = overrides
    if enabled:
        overrides.pop(key, None)
    else:
        entry = overrides.get(key)
        merged = dict(entry) if isinstance(entry, dict) else {}
        merged["enabled"] = False
        overrides[key] = merged
    return _write_skill_registry(doc)


def counts(character: str = "", home: str = "") -> dict[str, int]:
    """工作台卡片上那几行小字用的计数（一次读齐，省几次扫描）。

    口径是「各页点进去第一屏「全部」的张数」：卡片上的数字必须等于页面里的卡片数。
    踩过的坑：工坊卡片写「0 个包」，点进去躺着 8 个（已装 5 + 没装 3）；技能卡片
    数「已启用」，技能页连停用的也列，两边差一条。
    """
    home = home or pet_home(character)
    return {
        # 连接器只数她自己那份清单，页面看的也是它。
        "connectors": len(connectors(character, home)),
        # 技能页连停用的也列出来，所以这里数全部，不数「已启用」。
        "skills": len(skills(home=home)),
        # 工坊页 = 她已装的 + agent 装了但她还没装的。
        "packs": len(workshop_packs(character, home=home)),
    }


# -- 从 agent 那边搬连接器 ---------------------------------------------------
#
# 插件装好之后 agent 那边就已经登记好 MCP 了（``config.toml`` 的
# ``[[mcp.servers]]`` 与 ``mcp-custom.json``）。宠物家第一次开张时照这份清单
# 复制一份过来，搬家只发生在宠物家还没有 ``pet-mcp.json`` 的时候；之后两边各走
# 各的，宠物这边停用一个连接器不会动 agent 的配置。

AGENT_DATA_ENV = "LAJI_DATA_DIR"
AGENT_MCP_FILE = "mcp-custom.json"
AGENT_CONFIG_FILE = "config.toml"

_QUOTED = re.compile(r'"((?:[^"\\]|\\.)*)"')
_PAIR_QUOTED = re.compile(r'([A-Za-z_][A-Za-z0-9_.]*)\s*=\s*"((?:[^"\\]|\\.)*)"')
_ARRAY_TABLE = re.compile(r"^\s*\[\[([^\]]+)\]\]\s*$")
_TABLE = re.compile(r"^\s*\[(?!\[)([^\]]+)\]\s*$")
_SPEC_KEYS = ("command", "args", "env", "url", "headers", "type")


def _unquote(raw: str) -> str:
    try:
        return json.loads('"' + raw + '"')
    except ValueError:
        return raw


def agent_data_dirs() -> list[str]:
    """agent 的配置目录，顺序同 daemon 端点：用户级 → 开发镜像 → 漫游。"""
    dirs: list[str] = []
    override = os.environ.get(AGENT_DATA_ENV, "")
    if override:
        dirs.append(override)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        dirs.append(os.path.join(local, "laji"))
        dirs.append(os.path.join(local, "laji-dev"))
    roaming = os.environ.get("APPDATA", "")
    if roaming:
        dirs.append(os.path.join(roaming, "Laji Agent"))
    return dirs


def _clean_spec(spec: Any) -> dict[str, Any] | None:
    """只留下启动一个 MCP 需要的键；agent 的停用状态一并带过来。"""
    if isinstance(spec, str):
        return {"url": spec} if spec.startswith("http") else {"command": spec}
    if not isinstance(spec, dict):
        return None
    out = {key: spec[key] for key in _SPEC_KEYS if key in spec}
    if not out:
        return None
    if spec.get("disabled") is True or spec.get("enabled") is False:
        out["enabled"] = False
    return out


def _toml_mcp_servers(path: str) -> dict[str, dict[str, Any]]:
    """``config.toml`` 里的 ``[[mcp.servers]]``。读不懂的行跳过，不猜。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = fh.read(262144).splitlines()
    except OSError:
        return {}
    blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in lines:
        table = _ARRAY_TABLE.match(line)
        if table:
            current = {} if table.group(1).strip() == "mcp.servers" else None
            if current is not None:
                blocks.append(current)
            continue
        if _TABLE.match(line):
            current = None
            continue
        if current is None:
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "name":
            match = _QUOTED.search(value)
            if match:
                current["name"] = _unquote(match.group(1))
        elif key in ("url", "command", "transport"):
            match = _QUOTED.search(value)
            if match:
                current["type" if key == "transport" else key] = _unquote(match.group(1))
        elif key == "args":
            current["args"] = [_unquote(m.group(1)) for m in _QUOTED.finditer(value)]
        elif key == "env":
            current["env"] = {k: _unquote(v) for k, v in _PAIR_QUOTED.findall(value)}
        elif key == "enabled":
            current["enabled"] = value.lower().startswith("true")
    out: dict[str, dict[str, Any]] = {}
    for block in blocks:
        name = str(block.pop("name", "") or "")
        if name:
            out[name] = block
    return out


def _json_mcp_servers(path: str) -> dict[str, dict[str, Any]]:
    """``mcp-custom.json``（Cursor 格式）里的服务表。"""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, spec in _pick_servers(payload).items():
        clean = _clean_spec(spec)
        if clean is not None:
            out[str(name)] = clean
    return out


def agent_connectors(dirs: list[str] | None = None) -> list[dict[str, Any]]:
    """agent 那边登记的 MCP：``config.toml`` 打底，``mcp-custom.json`` 覆盖同名。"""
    found: dict[str, dict[str, Any]] = {}
    for base in dirs if dirs is not None else agent_data_dirs():
        try:
            found.update(_toml_mcp_servers(os.path.join(base, AGENT_CONFIG_FILE)))
            found.update(_json_mcp_servers(os.path.join(base, AGENT_MCP_FILE)))
        except Exception:
            continue
    out: list[dict[str, Any]] = []
    for name, spec in sorted(found.items()):
        out.append(
            {
                "name": name,
                "transport": _transport_of(spec),
                "enabled": spec.get("enabled") is not False,
                "spec": spec,
            }
        )
    return out


def import_from_agent(
    character: str = "", home: str = "", dirs: list[str] | None = None
) -> int:
    """把 agent 已登记的 MCP 补进宠物家：只填空位，同名的留宠物家自己那份。"""
    home = home or pet_home(character)
    if not home:
        return 0
    incoming = agent_connectors(dirs)
    if not incoming:
        return 0
    path = os.path.join(home, ".laji", MCP_FILE)
    payload: dict[str, Any] = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                loaded = json.load(fh)
        except (OSError, ValueError):
            return 0
        if not isinstance(loaded, dict):
            return 0
        payload = loaded
    table: Any = None
    for key in ("mcpServers", "servers", "mcp"):
        if isinstance(payload.get(key), dict):
            table = payload[key]
            break
    if table is None:
        # 扁平表就写在顶层；空文件则新建一个 mcpServers。
        table = payload if payload else payload.setdefault("mcpServers", {})
    added = 0
    for item in incoming:
        name = str(item.get("name") or "")
        spec = item.get("spec")
        if not name or not isinstance(spec, dict) or name in table:
            continue
        table[name] = dict(spec, source=IMPORTED_SOURCE)
        added += 1
    if not added:
        return 0
    try:
        os.makedirs(os.path.join(home, ".laji"), exist_ok=True)
        _write_json(path, payload)
    except OSError:
        return 0
    return added


def ensure_imported_from_agent(
    character: str = "", home: str = "", dirs: list[str] | None = None
) -> int:
    """宠物家还没有 ``pet-mcp.json`` 时先搬一份：装好就能用，之后各管各的。"""
    home = home or pet_home(character)
    if not home or os.path.isfile(os.path.join(home, ".laji", MCP_FILE)):
        return 0
    return import_from_agent(home=home, dirs=dirs)


# ---- 手艺（技能）------------------------------------------------------


def _slug(name: str) -> str:
    """名字变成能当目录名的一段：中文留着，空格和斜杠换掉。"""
    cleaned = re.sub(r"[\\/:*?\"<>|\s]+", "-", (name or "").strip()).strip("-. ")
    return cleaned[:60] or "skill"


def agent_skills(dirs: list[str] | None = None) -> list[dict[str, Any]]:
    """agent 全局技能目录里的技能（``<config>/skills/<name>/SKILL.md``）。"""
    found: dict[str, dict[str, Any]] = {}
    for base in dirs if dirs is not None else agent_data_dirs():
        root = os.path.join(base, "skills")
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            folder = os.path.join(root, entry)
            if not os.path.isdir(folder):
                continue
            one = _skill_one(folder, not entry.endswith(DISABLED_SUFFIX))
            if one and one["name"] not in found:
                found[one["name"]] = one
    return [found[key] for key in sorted(found)]


def import_skills_from_agent(
    character: str = "", home: str = "", dirs: list[str] | None = None
) -> int:
    """把 agent 的技能目录整份拷一份过来：只补她还没有的，同名不动。"""
    home = home or pet_home(character)
    if not home:
        return 0
    root = _skills_dir(home)
    existing = {str(item.get("name") or "") for item in skills(home=home)}
    added = 0
    for item in agent_skills(dirs):
        name = str(item.get("name") or "")
        source = os.path.dirname(str(item.get("path") or ""))
        if not name or name in existing or not os.path.isdir(source):
            continue
        target = os.path.join(root, os.path.basename(source).replace(DISABLED_SUFFIX, ""))
        if os.path.exists(target):
            continue
        try:
            os.makedirs(root, exist_ok=True)
            shutil.copytree(source, target)
        except OSError:
            continue
        added += 1
    return added


def save_skill(
    name: str,
    *,
    description: str = "",
    body: str = "",
    rename_from: str = "",
    character: str = "",
    home: str = "",
) -> bool:
    """写一份 ``SKILL.md``；改名就是把目录换一下，内容重写。"""
    name = (name or "").strip()
    if not name:
        return False
    home = home or pet_home(character)
    if not home:
        return False
    root = _skills_dir(home)
    slug = _slug(name)
    old = (rename_from or "").strip()
    # 编辑时写回它现在那个目录，不然同名的会变成两份。
    target = ""
    for item in skills(home=home):
        if str(item.get("name") or "") == name:
            target = os.path.dirname(str(item.get("path") or ""))
            break
    if not target:
        target = os.path.join(root, slug)
    if old and old != name:
        for item in skills(home=home):
            if str(item.get("name") or "") != old:
                continue
            source = os.path.dirname(str(item.get("path") or ""))
            if os.path.isdir(source) and os.path.abspath(source) != os.path.abspath(target):
                try:
                    shutil.rmtree(target, ignore_errors=True)
                    os.makedirs(root, exist_ok=True)
                    shutil.move(source, target)
                except OSError:
                    return False
            break
    head = ["---", f"name: {name}"]
    if description.strip():
        head.append(f"description: {description.strip()}")
    head.extend(("---", "", body.rstrip(), ""))
    try:
        os.makedirs(target, exist_ok=True)
        with open(os.path.join(target, SKILL_FILE), "w", encoding="utf-8") as fh:
            fh.write("\n".join(head))
    except OSError:
        return False
    return True


def remove_skill(name: str, character: str = "", home: str = "") -> bool:
    """删掉她家的一份技能（连同目录）；找不到就算了。

    全局那份不归她管：那是 agent「技能」页装的，删了一个插件就断了。
    全局技能只能关——关上就写 registry，两边都看得到。
    """
    home = home or pet_home(character)
    if not home or not (name or "").strip():
        return False
    for item in skills(home=home):
        if str(item.get("name") or "") != name:
            continue
        if str(item.get("scope") or SCOPE_WORKSPACE) != SCOPE_WORKSPACE:
            return False
        folder = os.path.dirname(str(item.get("path") or ""))
        if not os.path.isdir(folder):
            return False
        shutil.rmtree(folder, ignore_errors=True)
        return True
    return False


# ---- 创意工坊（能力包）------------------------------------------------


def agent_packs(dirs: list[str] | None = None) -> list[dict[str, Any]]:
    """agent 装过的能力包（``<config>/plugins/<id>/<version>/laji.plugin.toml``）。"""
    out: list[dict[str, Any]] = []
    for base in dirs if dirs is not None else agent_data_dirs():
        root = os.path.join(base, "plugins")
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            outer = os.path.join(root, entry)
            if not os.path.isdir(outer):
                continue
            candidates = [outer]
            try:
                candidates.extend(os.path.join(outer, v) for v in sorted(os.listdir(outer)))
            except OSError:
                pass
            for folder in candidates:
                if not os.path.isdir(folder):
                    continue
                one = _pack_summary(folder)
                if not one:
                    continue
                if one["name"] in {p["name"] for p in out}:
                    continue
                one["id"] = entry
                out.append(one)
                break
    return out


def install_pack(
    pack_id: str, character: str = "", home: str = "", dirs: list[str] | None = None
) -> bool:
    """把 agent 侧一个能力包复制进宠物家 ``plugins/``；同名已存在就不动。"""
    pack_id = (pack_id or "").strip()
    home = home or pet_home(character)
    if not pack_id or not home:
        return False
    target = os.path.join(home, "plugins", pack_id)
    if os.path.exists(target):
        return False
    source = ""
    for item in agent_packs(dirs):
        if str(item.get("id") or "") == pack_id:
            source = str(item.get("path") or "")
            break
    if not source or not os.path.isdir(source):
        return False
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copytree(source, target)
    except OSError:
        return False
    # 拷完就接上：技能搬进她自己的技能目录，连接器写进 pet-mcp.json 并开用。
    activate_pack(pack_id, home=home)
    return True


def activate_pack(pack_id: str, character: str = "", home: str = "") -> dict[str, Any]:
    """把一个包装好之后真正带的东西交出去。

    安装只是把文件拷进 ``plugins/``；不走这一步，它在工坊里显示已装，
    她的手艺与连接器里却什么也没有。
    """
    pack_id = (pack_id or "").strip()
    home = home or pet_home(character)
    folder = os.path.join(home, "plugins", pack_id) if (home and pack_id) else ""
    if not folder or not os.path.isdir(folder):
        return {"skills": [], "connectors": [], "path": ""}
    result: dict[str, Any] = {"skills": [], "connectors": [], "path": folder}
    body = _manifest_text(folder)

    root = _skills_dir(home)
    for block in _manifest_blocks(body, "skills"):
        rel = _block_value(block, "path").replace("\\", "/")
        if not rel:
            continue
        source = os.path.join(folder, rel)
        src_dir = source if os.path.isdir(source) else os.path.dirname(source)
        if not os.path.isdir(src_dir):
            continue
        name = (_frontmatter_field(os.path.join(src_dir, SKILL_FILE), ("name",)) or "").strip()
        name = name or os.path.basename(src_dir)
        target = os.path.join(root, name)
        if os.path.exists(target) or os.path.exists(target + DISABLED_SUFFIX):
            result["skills"].append(name)
            continue
        if os.path.isdir(os.path.join(daemon_skills_dir(), name)):
            # 全局那份已经在引擎的技能清单里了。再拷一份到她家只会多出一份会过期的副本，
            # 而同名以她家为准——那份陈旧副本反而把全局的遮住，连开关都绕过去。
            result["skills"].append(name)
            continue
        try:
            os.makedirs(root, exist_ok=True)
            shutil.copytree(src_dir, target)
        except OSError:
            log.debug("启用包：技能搬不过来 %s", src_dir, exc_info=True)
            continue
        result["skills"].append(name)

    links = _manifest_blocks(body, "mcp")
    prepared: list[tuple[str, dict[str, Any]]] = []
    if links:
        try:
            path, payload, table = _mcp_doc(home)
        except (OSError, ValueError):
            log.debug("启用包：pet-mcp.json 读不了", exc_info=True)
            path, payload, table = "", {}, {}
        changed = False
        for block in links:
            name = _block_value(block, "name")
            if not name:
                continue
            url = _block_value(block, "url")
            command = _expand_placeholders(_block_value(block, "command"), folder)
            spec: dict[str, Any] = {"enabled": True, "source": {"kind": "plugin", "id": pack_id}}
            if url:
                spec.update({"type": "http", "url": url})
            elif command:
                if "${python}" in command:
                    # 解释器没找到：登记了也只会得到 program not found（字面量交给
                    # spawn 去碰运气）。宁可不登记。
                    log.warning("启用包 %s：找不到 Python 3，跳过连接器 %s", pack_id, name)
                    continue
                spec["command"] = command
                args = [_expand_placeholders(one, folder) for one in _block_list(block, "args")]
                if args:
                    spec["args"] = args
                env = _block_table(block, "env")
                if env:
                    spec["env"] = {
                        str(key): _expand_placeholders(str(value), folder)
                        for key, value in env.items()
                    }
            else:
                continue
            transport = _block_value(block, "transport")
            if transport:
                spec["transport"] = transport
            prepared.append((name, spec))
            if table.get(name) == spec:
                result["connectors"].append(name)
                continue
            table[name] = spec
            changed = True
            result["connectors"].append(name)
        if changed and path:
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                _write_json(path, payload)
            except OSError:
                log.debug("启用包：写不进 pet-mcp.json", exc_info=True)
                result["connectors"] = []
        # 登记到她自己那份清单就完事了 —— 引擎按 workspace 读同一个路径，
        # 不再往 agent 面的 mcp-custom.json 里塞一份。
        grant_daemon_connector_tools([name for name, _spec in prepared])
    return result


def workshop_packs(
    character: str = "", home: str = "", dirs: list[str] | None = None
) -> list[dict[str, Any]]:
    """工坊列表：宠物家已装的在前，agent 装了她还没装的在后（``installed`` 区分）。"""
    home = home or pet_home(character)
    have = packs(home=home) if home else []
    out: list[dict[str, Any]] = []
    taken: set[str] = set()
    for item in have:
        pack_id = os.path.basename(str(item.get("path") or ""))
        if pack_id:
            taken.add(pack_id)
        out.append(dict(item, id=pack_id, installed=True))
    for item in agent_packs(dirs):
        pack_id = str(item.get("id") or "")
        if not pack_id or pack_id in taken or pack_id == SELF_PACK_ID:
            continue
        out.append(dict(item, installed=False))
    return out


def _manifest_blocks(body: str, kind: str) -> list[str]:
    """把 ``[[contributions.<kind>]]`` 下面的每个块正文按顺序取出来。"""
    blocks: list[str] = []
    current: list[str] | None = None
    head = f"[[contributions.{kind}]]"
    for line in body.splitlines():
        stripped = line.strip()
        if stripped == head:
            if current is not None:
                blocks.append("\n".join(current))
            current = []
            continue
        if current is not None and stripped.startswith("[") and stripped.endswith("]"):
            blocks.append("\n".join(current))
            current = None
            continue
        if current is not None:
            current.append(line)
    if current is not None:
        blocks.append("\n".join(current))
    return blocks


def _manifest_text(folder: str) -> str:
    path = os.path.join(folder or "", "laji.plugin.toml")
    if not folder or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


_BLOCK_KV = re.compile(r"^\s*([A-Za-z_][\w-]*)\s*=\s*(.+?)\s*$", re.M)
_FM_DOC = re.compile(r"^---\r?\n(.*?)\r?\n---", re.S)


def _block_value(block: str, key: str) -> str:
    for match in _BLOCK_KV.finditer(block):
        if match.group(1) != key:
            continue
        raw = match.group(2).strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
            return raw[1:-1]
        return raw
    return ""


def _block_list(block: str, key: str) -> list[str]:
    raw = _block_value(block, key)
    if not raw.startswith("[") or not raw.endswith("]"):
        return []
    return [one.strip().strip("\"'") for one in raw[1:-1].split(",") if one.strip()]


def _block_table(block: str, key: str) -> dict[str, str]:
    # inline table 的值里会出现 ``${APPDATA}`` 这类占位符：扫到与开关括号配平
    # 的那个 ``}`` 为止。用 ``[^}]*`` 会在占位符自己的 ``}`` 处截断，后面几条
    # env 便被整条丢弃（实机：PET_HANDS_SHOT_DIR 丢了，截图落到她读不到的目录）。
    match = re.search(rf"^{key}\s*=\s*\{{", block, re.M)
    if not match:
        return {}
    start = match.end() - 1
    depth = 0
    quote = ""
    end = -1
    for index in range(start, len(block)):
        char = block[index]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end < 0:
        return {}
    out: dict[str, str] = {}
    for part in _split_top_level(block[start + 1 : end], ","):
        name, _, value = part.partition("=")
        if name.strip():
            out[name.strip()] = value.strip().strip("\"'")
    return out


def _split_top_level(body: str, sep: str) -> list[str]:
    """按 ``,`` 切 inline table，引号里的逗号不算分隔。"""
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    for char in body:
        if quote:
            buf.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            buf.append(char)
        elif char == sep:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
    if buf:
        parts.append("".join(buf))
    return parts


def _frontmatter_field(path: str, keys: tuple[str, ...]) -> str:
    """SKILL.md / 专家 .md 的 front matter 字段；``>-`` 折叠块就往下收缩进行。"""
    if not path or not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            head = handle.read(4000)
    except OSError:
        return ""
    match = _FM_DOC.match(head)
    body = match.group(1) if match else head
    for key in keys:
        hit = re.search(rf"^{key}\s*:\s*(.+)$", body, re.M)
        if hit is None:
            continue
        value = hit.group(1).strip()
        if value[:1] in (">", "|"):
            parts: list[str] = []
            for line in body[hit.end() :].splitlines():
                if not line.strip():
                    if parts:
                        break
                    continue
                if not line.startswith((" ", "\t")):
                    break
                parts.append(line.strip())
            value = ("".join(parts) if value.startswith(">") else " ".join(parts)).strip()
        if value:
            return value.strip("\"'")
    return ""


def pack_contributions(folder: str) -> list[dict[str, Any]]:
    """包里到底带了什么：技能、连接器、规则、界面入口逐条列出来（详情弹层用）。"""
    body = _manifest_text(folder)
    if not body:
        return []
    out: list[dict[str, Any]] = []

    def add(kind: str, name: str, description: str, ref: str) -> None:
        if name or ref:
            out.append(
                {"kind": kind, "name": name or ref, "description": description, "ref": ref}
            )

    def rel_of(block: str) -> str:
        return _block_value(block, "path").replace("\\", "/")

    for block in _manifest_blocks(body, "skills"):
        rel = rel_of(block)
        path = os.path.join(folder, rel) if rel else ""
        add(
            "skill",
            _frontmatter_field(path, ("name",)) or os.path.basename(os.path.dirname(rel)) or rel,
            _frontmatter_field(path, ("description",)),
            rel,
        )
    for block in _manifest_blocks(body, "experts"):
        rel = rel_of(block)
        path = os.path.join(folder, rel) if rel else ""
        add(
            "expert",
            _frontmatter_field(path, ("name",)) or _block_value(block, "id"),
            _frontmatter_field(path, ("description",)),
            rel or _block_value(block, "id"),
        )
    for block in _manifest_blocks(body, "rules"):
        rel = rel_of(block)
        path = os.path.join(folder, rel) if rel else ""
        stem = os.path.splitext(os.path.basename(rel))[0]
        pretty = " ".join(part for part in re.split(r"[-_]", stem) if part)
        add("rule", pretty or rel, _frontmatter_field(path, ("description", "title")), rel)
    for block in _manifest_blocks(body, "context_layers"):
        rel = rel_of(block)
        path = os.path.join(folder, rel) if rel else ""
        add(
            "contextLayer",
            _frontmatter_field(path, ("name", "title")) or _block_value(block, "id"),
            _frontmatter_field(path, ("description",)),
            rel or _block_value(block, "id"),
        )
    for block in _manifest_blocks(body, "mcp"):
        name = _block_value(block, "name")
        if not name:
            continue
        add(
            "mcp",
            name,
            "",
            _block_value(block, "url")
            or _block_value(block, "command")
            or _block_value(block, "transport")
            or "stdio",
        )
    for block in _manifest_blocks(body, "workbench"):
        skin = _block_value(block, "skin")
        if skin:
            add("skin", skin, "", _block_value(block, "id"))
        entry = _block_value(block, "entry")
        if entry:
            add("workbench", _block_value(block, "title") or _block_value(block, "id"), "", entry)
    for block in _manifest_blocks(body, "intro"):
        add(
            "intro",
            _block_value(block, "title") or _block_value(block, "id"),
            "",
            _block_value(block, "id"),
        )
    for block in _manifest_blocks(body, "apps"):
        add(
            "app",
            _block_value(block, "name") or _block_value(block, "id"),
            "",
            _block_value(block, "command"),
        )
    return out


#: 清单里可以直接写的系统目录占位符（大小写照 Windows 的环境变量名）。
_PLACEHOLDER_ROOTS = (
    "APPDATA",
    "LOCALAPPDATA",
    "PROGRAMDATA",
    "PROGRAMFILES",
    "USERPROFILE",
    "HOME",
)


def _expand_placeholders(text: str, folder: str) -> str:
    """``${plugin}`` / ``${python}`` / ``${APPDATA}`` 落成真路径；其余原样留着。

    宠物家那份清单是引擎直接 spawn 的：``${python}`` 不落成真路径就是 ``program
    not found``；``${APPDATA}`` 不落成真路径，截图就落到一个谁都不认的相对目录。
    """
    if folder:
        text = text.replace("${plugin}", folder)

    def _root(match: re.Match[str]) -> str:
        value = os.environ.get(match.group(1), "")
        if not value:
            return match.group(0)
        rest = match.group(2) or ""
        if os.name == "nt":
            rest = rest.replace("/", "\\")
        return value + rest

    roots = "|".join(_PLACEHOLDER_ROOTS)
    text = re.sub(rf"\$\{{({roots})\}}([/\\])?", _root, text)

    def _named(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "") or match.group(0)

    text = re.sub(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}", _named, text)
    if "${python}" in text:
        exe = _python_exe()
        if exe:
            text = text.replace("${python}", exe)
    return text


def read_contribution(folder: str, kind: str, name: str = "", ref: str = "") -> dict[str, Any]:
    """详情页点开一条贡献：能看到的正文或启动配置，取不到就给空正文。"""
    body = _manifest_text(folder)
    if kind == "mcp" and body:
        for block in _manifest_blocks(body, "mcp"):
            if _block_value(block, "name") != name:
                continue
            url = _block_value(block, "url")
            command = _block_value(block, "command")
            transport = _block_value(block, "transport") or ("http" if url else "stdio")
            shown: dict[str, Any] = {"transport": transport}
            if url:
                shown["url"] = url
            if command:
                shown["command"] = _expand_placeholders(command, folder)
            args = [_expand_placeholders(one, folder) for one in _block_list(block, "args")]
            if args:
                shown["args"] = args
            env = _block_table(block, "env")
            if env:
                shown["env"] = env
            meta = [bit for bit in (transport, url or command) if bit]
            return {
                "title": name,
                "meta": meta,
                "body": json.dumps(shown, ensure_ascii=False, indent=2),
            }
    rel = (ref or "").replace("\\", "/")
    if rel and "${" not in rel and "/" in rel:
        path = os.path.join(folder, rel)
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    text = handle.read(200000)
            except OSError:
                text = ""
            # front matter 已经在标题与说明里用过了，正文不再重复。
            text = _FM_DOC.sub("", text, count=1).strip()
            return {"title": name or os.path.basename(path), "meta": [rel], "body": text}
    return {"title": name or ref, "meta": [], "body": ""}


def uninstall_pack(pack_id: str, character: str = "", home: str = "") -> bool:
    """把已装的能力包从宠物家整目录删掉；不存在就不算是失败。"""
    pack_id = (pack_id or "").strip()
    home = home or pet_home(character)
    if not pack_id or ".." in pack_id or "/" in pack_id or "\\" in pack_id or not home:
        return False
    target = os.path.join(home, "plugins", pack_id)
    if not os.path.isdir(target):
        return False
    # 删文件之前先把它带进来的技能与连接器收回去，否则会留下一堆孤儿条目。
    deactivate_pack(pack_id, home=home)
    try:
        shutil.rmtree(target)
    except OSError:
        return False
    return True


def deactivate_pack(pack_id: str, character: str = "", home: str = "") -> dict[str, Any]:
    """卸包前把它带进来的东西收走：连接器按 ``source.id`` 清，技能只删它声明过的。"""
    pack_id = (pack_id or "").strip()
    home = home or pet_home(character)
    folder = os.path.join(home, "plugins", pack_id) if (home and pack_id) else ""
    result: dict[str, Any] = {"skills": [], "connectors": []}
    if not folder or not os.path.isdir(folder):
        return result
    body = _manifest_text(folder)

    root = _skills_dir(home)
    for block in _manifest_blocks(body, "skills"):
        rel = _block_value(block, "path").replace("\\", "/")
        if not rel:
            continue
        source = os.path.join(folder, rel)
        src_dir = source if os.path.isdir(source) else os.path.dirname(source)
        name = (_frontmatter_field(os.path.join(src_dir, SKILL_FILE), ("name",)) or "").strip()
        name = name or os.path.basename(src_dir)
        for entry in (name, name + DISABLED_SUFFIX):
            target = os.path.join(root, entry)
            if not os.path.isdir(target):
                continue
            try:
                shutil.rmtree(target)
            except OSError:
                break
            result["skills"].append(name)
            break

    declared = [n for block in _manifest_blocks(body, "mcp") if (n := _block_value(block, "name"))]
    try:
        path, payload, table = _mcp_doc(home)
    except (OSError, ValueError):
        return result
    changed = False
    revoked: list[str] = []
    for name, spec in list(table.items()):
        source = spec.get("source") if isinstance(spec, dict) else None
        owner = str(source.get("id") or "") if isinstance(source, dict) else ""
        if owner == pack_id or name in declared:
            table.pop(name, None)
            changed = True
            revoked.append(name)
            result["connectors"].append(name)
    if changed:
        try:
            _write_json(path, payload)
        except OSError:
            log.debug("停用包：写不进 pet-mcp.json", exc_info=True)
        else:
            revoke_daemon_connector_tools(revoked)
    return result


def import_packs_from_agent(
    character: str = "", home: str = "", dirs: list[str] | None = None
) -> int:
    """把 agent 已装的能力包复制进宠物家 ``plugins/``：只补缺的，同名不动。"""
    home = home or pet_home(character)
    if not home:
        return 0
    root = os.path.join(home, "plugins")
    existing = {os.path.basename(str(item.get("path") or "")) for item in packs(home=home)}
    added = 0
    for item in agent_packs(dirs):
        pack_id = str(item.get("id") or "")
        source = str(item.get("path") or "")
        if not pack_id or pack_id in existing or not os.path.isdir(source):
            continue
        target = os.path.join(root, pack_id)
        if os.path.exists(target):
            continue
        try:
            os.makedirs(root, exist_ok=True)
            shutil.copytree(source, target)
        except OSError:
            continue
        added += 1
    return added
