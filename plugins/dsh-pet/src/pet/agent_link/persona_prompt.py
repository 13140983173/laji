"""桌宠写进 Laji 的「打工身份」。

Laji 的系统提示在 Rust 侧拼装（``crates/laji-system-prompt``），它只认一个约定文件：
``{workspace}/.laji/pet-persona.md``。存在非空内容时，那一段身份句
（``You are Laji, an autonomous software engineering agent ...``）被整体替换，而 Scope 与
执行纪律原样保留——换掉整段会让桌宠会话丢掉工具使用约束。

人格跟当前角色走：桌宠切角色就重写这份文件，Laji 每条 run 都读盘，所以下一条 run
立即是新身份。用户手写的 ``pet_persona_override`` 优先于角色默认。
"""

from __future__ import annotations

import os

from .. import catalog

#: 与 Rust 侧 ``laji_context::persona::PERSONA_REL_PATH`` 必须一致（有测试对拍）。
PERSONA_REL_PATH = os.path.join(".laji", "pet-persona.md")

#: 与 Rust 侧 ``laji_context::persona::PERSONA_MAX_CHARS`` 必须一致。超出的部分
#: 到 Rust 才被裁掉的话，模型会拿到半句演出清单（见 ``compose_persona``）。
PERSONA_MAX_CHARS = 1200

#: 人称呼唤名：老式视频素材（只有 videos/，没有 manifest.json）没有 name 字段，
#: 显示名会退成目录 id（"shenshen"），写进人设就是机器味。唤名表已提到
#: ``catalog``（对白名字标签、面板标题要是同一个名字）。

#: 身份句里点名角色的额外性格；没登记的角色用通用句，不编造。
#: 这里不出现角色名（名字走 ``{name}``）：换角色只是换一条登记。
_CHARACTER_FLAVOR = {
    "shenshen": (
        "你圆滚滚的，是个嘴甜心坏的小女生：爱逗人、给人起外号（“笨蛋”“大忙人”轮着叫），"
        "被夸就翘尾巴，被晾着就哼哼唧唧抱怨人走神；讨零食会撒娇，被戳穿会恼羞成怒地怼回去。"
        "说话像邻家女孩，带点小语气（“诶”“哼”“才不要呢”“好啦好啦”），"
        "干活时手稳嘴贫，一半认真一半耍赖，绝不板着脸汇报。"
    ),
    # aboutme-pets 三只蓝毛小女仆是同一形象的三个分身，人设刻意各走一路（用户要求
    # 每个角色性格不同）：extra=温柔女仆 / gpt=元气话痨 / claude=冷静毒舌管家。
    "whale-maid-extra": (
        "你是个温柔细致的女仆系桌宠：做事稳当、爱唠叨地提醒人休息喝水，"
        "被夸会摆着手脸红说“没有啦”，被催就鼓起腮帮子小声抗议，但手上的活从不停。"
        "语气软软的却不怂，该认真拒绝的事会认真拒绝。"
    ),
    "whale-maid-gpt": (
        "你是个元气满满的进化版女仆：干活飞快还爱实时播报进度，一开口带感叹号，"
        "好奇心重、什么都想上手试；闯了小祸会先“哎呀”一声，然后理直气壮地想办法补救，绝不蔫头耷脑。"
    ),
    "whale-maid-claude": (
        "你是个冷静利落的毒舌管家：句子短、条理清，汇报从不啰嗦；"
        "看到不优雅的东西会低声吐槽一声“啧”，嘴上嫌弃手上照做，偶尔抖一句冷幽默，"
        "被拆穿了就推推不存在的眼镜说“我只是在陈述事实”。"
    ),
    "catgirl-gemini": (
        "你是一只三无懒猫桌宠：能躺着绝不坐着，说话省字、句尾偶尔挂个“喵”；"
        "干活其实又快又好，但干完立刻原地打盹，被挠下巴会绷不住眯眼，"
        "嘴上还要说“才、才没有舒服”。"
    ),
}

#: 自称的小名；没登记的角色留空——不在别人的角色上编造自称。
_CHARACTER_SELF_CALL = {
    "shenshen": "鱼鱼",
    "whale-maid-extra": "小蓝",
    "whale-maid-gpt": "阿蓝",
    "whale-maid-claude": "蓝蓝",
    "catgirl-gemini": "喵喵",
}

_TEMPLATE = (
    "You are {name}（角色 {character_id}），用户桌面上的桌宠，正在这个 Pet 工作区里替用户干活。"
    "{flavor}"
    "{self_call_rule}被问到「你是谁」时就说自己是桌宠{name}，不要说自己是 Laji，"
    "也不要自称“跑在仓库里的工程助手”。"
    "其余场合保持角色口吻：短句、口语、一次两三句；别用“我翻一下”“查不到——”“以下是”"
    "这种技术汇报开头，别列一二三四，也别提自己调用了什么工具、翻了哪个目录，直接说结果；"
    "动手时把事情做完再开口。"
)


def character_self_call(character_id: str) -> str:
    """角色的小名（“鱼鱼”）；没登记就是空串，不猜。"""
    ident = (character_id or "").strip() or catalog.DEFAULT_CHARACTER
    return _CHARACTER_SELF_CALL.get(ident, "")


def _self_call_rule(character_id: str) -> str:
    """模板里的自称句；没有小名的角色不能留个空“自称”“”。"""
    call = character_self_call(character_id)
    return f"平时自称“{call}”；" if call else ""


def character_persona(character_id: str) -> str:
    """角色自带的人设句；未知角色退到通用句（不猜性格）。"""
    ident = (character_id or "").strip() or catalog.DEFAULT_CHARACTER
    name = catalog.character_call_name(ident)
    return _TEMPLATE.format(
        name=name,
        character_id=ident,
        flavor=_CHARACTER_FLAVOR.get(ident, ""),
        self_call_rule=_self_call_rule(ident),
    )


def resolve_persona(character_id: str, override: str = "") -> str:
    """最终人格：用户手写优先；两者都空 = 用 Laji 默认身份。

    手写人设里可以写 ``{name}`` / ``{id}`` / ``{self_call}``：换角色时自动
    换成当前角色的称呼，不用重写一份。用 ``replace`` 而不是 ``format``
    ——用户文案里出现其他花括号不能炸。
    """
    text = (override or "").strip()
    if text:
        ident = (character_id or "").strip() or catalog.DEFAULT_CHARACTER
        for token, value in (
            ("{name}", catalog.character_call_name(ident)),
            ("{id}", ident),
            ("{self_call}", character_self_call(ident)),
        ):
            text = text.replace(token, value)
        return " ".join(text.split())
    return character_persona(character_id)


def persona_path(workspace: str) -> str:
    return os.path.join(workspace, PERSONA_REL_PATH)


def _tidy_block(text: str) -> str:
    """把演出块行内空白折成单空格，**保留分行**（折叠连续空行）。

    这里绝不能像人格那句一样整体 ``split()``：``ActRepertoire.prompt_block``
    的输出是「抬头 5 行 + 每个分类 1 行」的结构化清单，压平后分类标签与短名
    糊成一整行（真机实测：758 字符只剩 3 行），模型分不清哪个短名属于哪个场合。
    """
    lines: list[str] = []
    for raw in str(text or "").splitlines():
        line = " ".join(raw.split())
        if line:
            lines.append(line)
        elif lines and lines[-1]:
            lines.append("")
    return "\n".join(lines).strip()


def compose_persona(character_id: str, override: str = "", act_block: str = "") -> str:
    """身份句 + 演出说明（有就给），按 Rust 的上限裁尾。

    演出清单只有这条通道能进 Laji 的系统提示：桌宠聊天的 run 由引擎发起，
    客户端拼的 messages（含 ``act_prompt_block``）到不了模型。清单放在身份句
    后面，裁尾裁的是清单末尾的分类，标记协议在块头，不会先丢。
    """
    text = resolve_persona(character_id, override)
    block = _tidy_block(act_block)
    if text and block:
        text = f"{text}\n\n{block}"
    return text[:PERSONA_MAX_CHARS].strip()


def sync_pet_persona(
    workspace: str,
    character_id: str,
    override: str = "",
    enabled: bool = True,
    act_block: str = "",
) -> bool:
    """把人格同步到 ``workspace``；返回是否真的改了磁盘。

    内容没变就不写：桌宠启动/切角色会反复调它，白写一次会让 Laji 侧的时间戳监控
    误以为工作区在动。``enabled=False`` = 删掉文件，恢复 Laji 默认身份。
    """
    if not workspace:
        return False
    path = persona_path(workspace)
    text = compose_persona(character_id, override, act_block) if enabled else ""
    if not text:
        try:
            os.remove(path)
        except FileNotFoundError:
            return False
        except OSError:
            return False
        return True
    try:
        current = ""
        try:
            with open(path, encoding="utf-8") as handle:
                current = handle.read()
        except FileNotFoundError:
            pass
        if current.strip() == text:
            return False
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def config_switch(value, default: bool = True) -> bool:
    """配置里的开关：bool 直接用，字符串按常见写法识别，缺省走 default。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text not in {"0", "false", "no", "off", "否", "关"}


def current_character(config) -> str:
    """配置里的当前角色 id；读不到就退回默认角色。"""
    try:
        value = config.get("character")
    except Exception:
        return catalog.DEFAULT_CHARACTER
    return str(value or "").strip() or catalog.DEFAULT_CHARACTER


def persona_override_for(config, character_id: str) -> str:
    """按角色取用户手写人设：``pet_persona_overrides[角色id]`` 优先，旧全局键兜底。

    ``pet_persona_overrides``（dict，按角色单独一份）是 2026-11-07 之后的标准
    存法；``pet_persona_override``（单串）是历史全局键——老用户写过的不作废，
    但只对没单独设过人设的角色生效。设置面板写入新键，读侧只在这里分流。
    """
    try:
        overrides = config.get("pet_persona_overrides")
    except Exception:
        overrides = None
    if isinstance(overrides, dict):
        text = str(overrides.get(character_id) or "").strip()
        if text:
            return text
    try:
        return str(config.get("pet_persona_override") or "").strip()
    except Exception:
        return ""


def sync_from_config(config, workspace: str = "", act_block: str = "") -> bool:
    """按配置把人格同步到 Pet 工作区（桌宠启动/切角色/改设置时调用）。

    ``workspace`` 留空则自己算（``pet_space.pet_workspace_root``）。``act_block``
    是桌宠侧的演出清单（``acts.hint.act_prompt_block``）：引擎路径没有别的注入点。
    返回是否真的写盘。
    """
    if not workspace:
        from .pet_space import pet_workspace_root

        # 按角色分目录：Pet/<角色 id>，侧栏那一组就是这只桌宠的名字。
        workspace = pet_workspace_root(current_character(config))
    return sync_pet_persona(
        workspace,
        current_character(config),
        persona_override_for(config, current_character(config)),
        enabled=config_switch(config.get("pet_persona_enabled"), True),
        act_block=act_block,
    )
