# -*- coding: utf-8 -*-
"""小口袋聊天（本地模型直连）的 system 里必须有名字和人设。

回归：角色卡上「人设」写了 700 字、名字也改过，小口袋里问「你知道你是谁吗」，
她答「我算桌面籍的吧」——本地直连不经过 Laji 引擎，读不到引擎侧注入的
`.laji/pet-persona.md`，`PromptBuilder` 只拿到全局默认那句「你是一只可爱的
桌面宠物」，于是身份全靠模型自己编。这里守住：名字 + 人设置顶进 system。
"""
from __future__ import annotations

from pet.chat.models import ChatSettings
from pet.chat.prompt import PromptBuilder, character_identity, compose_identity

_DEFAULT_PROMPT = "你是一只可爱的桌面宠物，请用自然、友善的中文和用户交流。"
_PERSONA = "你是 Ling，一个住在用户桌面上的 Q 版桌宠少女，不是助手。"


class _Config:
    """只带 get 的配置视图：既测 Config 本身，也测拿不到 helper 方法的视图。"""

    def __init__(self, alias: str = "", persona: str = "") -> None:
        self.values: dict = {"character": "ling-girl"}
        if alias:
            self.values["character_aliases"] = {"ling-girl": alias}
        if persona:
            self.values["pet_persona_overrides"] = {"ling-girl": persona}

    def get(self, key, default=None):
        return self.values.get(key, default)


def _system(identity: str) -> str:
    return PromptBuilder().build_messages(
        ChatSettings(), "ling-girl", [], "你还记得你是谁吗", identity=identity
    )[0]["content"]


def test_default_prompt_alone_knows_nothing_about_her():
    """桩：不注入身份时，system 就是那句通用默认提示词（用户看到的那版行为）。"""
    assert _system("").startswith(_DEFAULT_PROMPT)


def test_identity_carries_name_and_persona_above_the_default_prompt():
    config = _Config(alias="Ling", persona=_PERSONA)
    system = _system(character_identity(config, "ling-girl"))

    assert _PERSONA in system, "用户写的人设必须逐字进提示词"
    assert "用户把你的名字改成了「Ling」" in system, "改名必须点明，否则她自己还叫旧名"
    assert system.index(_PERSONA) < system.index(_DEFAULT_PROMPT), \
        "身份要置顶：靠后的通用提示词会盖掉它"


def test_alias_is_read_even_when_config_has_no_helper_methods():
    """独立设置进程里的 slot 视图可能没有 character_display_name，仍要读到别名。"""
    assert "You are Ling" in character_identity(_Config(alias="Ling"), "ling-girl")


def test_blank_config_still_gets_the_built_in_role():
    """没手写过人设也该有身份：角色设定在 ``_CHARACTER_FLAVOR`` 里，不在配置里。

    回归：只读 ``pet_persona_overrides`` 时，配置里那份是空的（用户从没在对话框
    里存过），身份段整个是空串，她照样自编「我算桌面籍的吧」。
    """
    assert compose_identity("", "") == ""
    system = _system(character_identity(_Config(), "ling-girl"))
    assert system.startswith("You are"), system[:80]
    assert system.index("You are") < system.index(_DEFAULT_PROMPT)


def test_role_flavor_reaches_this_link():
    """“圆滚滚、嘴甜心坏、自称鱼鱼”这段只在 persona_prompt 里，必须被捧上来。"""
    class _Shenshen(_Config):
        def __init__(self):
            self.values = {"character": "shenshen"}

    config = _Shenshen()
    text = character_identity(config, "shenshen")
    assert "嘴甜心坏" in text and "鱼鱼" in text
    assert "无名小宠" not in text


def test_engine_side_persona_uses_the_edited_name():
    """引擎侧（气泡/语音）的人设文件里的自称也要跟用户改的名一致。"""
    from pet.agent_link import persona_prompt

    text = persona_prompt.compose_persona("ling-girl", "", name="Ling")
    assert "Ling" in text


def test_renamed_character_no_longer_answers_to_the_pet_name():
    """改名后不能一半新名一半旧名：模板里的「平时自称“鱼鱼”」也要跟着改。"""
    from pet.agent_link import persona_prompt

    text = persona_prompt.character_persona("shenshen", name="小满")
    assert "You are 小满" in text
    assert "平时自称“小满”" in text
    assert "鱼鱼" not in text


def test_unrenamed_character_keeps_the_flavor_self_call():
    from pet.agent_link import persona_prompt

    assert "平时自称“鱼鱼”" in persona_prompt.character_persona("shenshen")
