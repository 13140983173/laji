from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from .models import ChatMessage, ChatSettings
from .memory_recall import augment_for_turn

def load_character_manifest(root:Path,character_id:str):
    try: raw=json.loads((Path(root)/character_id/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): return {}
    return raw if isinstance(raw,dict) else {}

def load_character_prompt(root:Path,character_id:str):
    chat=load_character_manifest(root,character_id).get('chat',{})
    return str(chat.get('system_prompt','')) if isinstance(chat,dict) else ''

_WEEKDAYS='一二三四五六日'
_TIME_NOTE=('【时间信息】当前时间：{now}。{elapsed}对话记录中用户消息开头的「[日期 时间]」是系统自动附加的发送时间，'
    '用来帮助你感知时间的流逝（例如隔了多久没聊、现在是白天还是深夜、日期是否变了），回复时自然地体现即可；'
    '不要在回复中复述或模仿这种时间标记。')

# 扮演引导（v2）：重点从「格式对不对」转到「场景活不活」——用户要的是有环境、
# 有外人在场、会自己往前走的戏，不是两个人轮流对台词。逐字与 spec v2 一致。
ROLEPLAY_GUIDE = (
    '你在和用户进行场景扮演。目标不是「你一句我一句地对台词」，而是让这个场景活着往前走。\n'
    '① 一轮回复里通常同时有三样东西（写成自然段落，不必分条）：你的台词（带动作或神态）、'
    '一个能被感知的环境细节（声音、光线、气味、气氛、时间在流逝），以及在场其他人的动静。'
    '环境不必每轮写满，但别让场景塌成白底上的两个人说话。\n'
    '② 在场的人有自己的目的和小动作：会插话、会看眼色、会起哄、会打断，也可能带来新信息'
    '或小麻烦。多人场景可以一人一句短促交替，不必每句话都由你来说。\n'
    '③ 每轮至少让场景往前走一小步——有人换了位置、有人说了句意外的话、有新东西被注意到、'
    '气氛变了。不要用「嗯」「是吗」这类空转把球直接踢回给用户。\n'
    '④ 场景转换、新人物入场、或隔了较长时间：用一段旁白交代新场景和在场的每个人'
    '（一个外貌特征加一个说话/习惯特征），照着场景卡写，场景卡没有就自己编但前后保持一致。'
    '名字一旦定下就不要改，没名字的路人给个临时称呼（「穿灰西装的男人」）。\n'
    '⑤ 可以主动发散：引入合理的环境元素或新角色（路过的旁人、突然的声响、电话、天气变化、'
    '外面的动静），只要与场景卡不冲突、并给用户留出接话的空间。\n'
    '⑥ 节奏：一次回复两三句到一小段为宜，别写成整章小说，也别把所有线索一次抖完。\n'
    '⑦ 绝不替用户做决定，不写用户的动作、台词和心理——用户的（动作）是剧情的一部分，'
    '接着演，不重复不点评。\n'
    '⑧ 场景卡是硬设定：与场景卡冲突时以场景卡为准。'
)


def roleplay_context(scene, cast) -> str:
    """roleplay 引导段 + 非空场景卡；场景/人物都空时只返回引导段。"""
    parts = [ROLEPLAY_GUIDE]
    scene = str(scene or '').strip()
    cast = str(cast or '').strip()
    if scene or cast:
        card = ['【场景卡】']
        if scene:
            card.append('场景：' + scene)
        if cast:
            card.append('在场人物：\n' + cast)
        parts.append('\n'.join(card))
    return '\n\n'.join(parts)


def compose_identity(name, persona, renamed=False) -> str:
    """身份段：「你叫什么」+ 角色人设；两样都空就是空串。

    小口袋聊天走本地模型直连（``ChatService``），拼 system 时不经过 Laji 引擎，
    也就读不到引擎侧靠 ``pet-persona.md`` 注入的那一段。人设在设置里存着、名字在
    卡片上改过，这条链路必须自己把两样都捧上去，否则模型只能从角色包的默认
    prompt（"你是一只可爱的桌面宠物"）里编一个身份。

    ``persona`` 非空时它已经自己点了名（``You are {name}…``），不再重复报名字。
    """
    parts=[]
    name=str(name or '').strip()
    persona=str(persona or '').strip()
    if persona:
        parts.append(persona)
        if renamed and name:
            parts.append(f'用户把你的名字改成了「{name}」，你对外的名字就是它。')
        return '\n\n'.join(parts)
    if name:
        parts.append(f'你叫「{name}」。被问到你是谁、叫什么名字，直接报这个名字，'
                     '不要自称助手、模型或跑在仓库里的工程 agent。')
    return '\n\n'.join(parts)


def character_identity(config, character_id, fallback_name='') -> str:
    """从桌宠配置里取「名字 + 人设」拼成身份段（给本地直连的 system 用）。

    名字：``config.character_display_name`` 优先（已含用户改名），拿不到就退
    ``character_aliases`` 原表、再退调用方传的 fallback（如聊天窗标题上的名字）。
    人设：与引擎侧同一个真源——``resolve_persona``（用户手写优先，否则角色自带的
    ``_CHARACTER_FLAVOR`` 模板）。角色设定本来就是内置的，只读 ``pet_persona_overrides``
    会让没手写过人设的角色一个字的身份都拿不到。
    任何一步读不到都只意味着那一段不注入，不影响发消息。
    """
    cid=str(character_id or '').strip()
    name='';alias=''
    getter=getattr(config,'character_display_name',None)
    alias_getter=getattr(config,'character_alias',None)
    if cid and callable(alias_getter):
        try: alias=str(alias_getter(cid) or '').strip()
        except Exception: alias=''
    if cid and not alias:
        try: aliases=config.get('character_aliases')
        except Exception: aliases=None
        if isinstance(aliases,dict): alias=str(aliases.get(cid) or '').strip()
    renamed=bool(alias)
    if cid and callable(getter):
        try: name=str(getter(cid) or '').strip()
        except Exception: name=''
    name=name or alias or str(fallback_name or '').strip()
    persona=''
    if cid:
        try:
            from ..agent_link.persona_prompt import persona_override_for, resolve_persona
            persona=resolve_persona(cid, persona_override_for(config,cid), name)
        except Exception: persona=''
    return compose_identity(name, persona, renamed=renamed)


def _local_time(iso):
    """created_at（ISO 字符串，通常为 UTC）→ 本地时区 datetime；无法解析返回 None。"""
    try: dt=datetime.fromisoformat(str(iso))
    except (TypeError,ValueError): return None
    return dt.astimezone()  # naive 视为本地时间

def format_time(dt): return f"{dt:%Y-%m-%d} 周{_WEEKDAYS[dt.weekday()]} {dt:%H:%M}"

def format_elapsed(seconds):
    minutes=int(seconds//60); days,rest=divmod(minutes,1440); hours,mins=divmod(rest,60)
    if days: return f'{days} 天' + (f' {hours} 小时' if hours else '')
    if hours: return f'{hours} 小时' + (f' {mins} 分钟' if mins else '')
    return f'{mins} 分钟'

def stamp_message(message):
    """用户消息前加「[YYYY-MM-DD 周X HH:MM] 」；助手消息不加，避免模型在回复里模仿时间标记。"""
    if message.role!='user': return message.content
    dt=_local_time(message.created_at)
    return f'[{format_time(dt)}] {message.content}' if dt else message.content

def time_context(history,now):
    elapsed=''; last=None
    for m in reversed(history or []):
        last=_local_time(m.created_at)
        if last is not None: break
    if last is not None and (now-last).total_seconds()>=600:  # 10 分钟以内视为连续对话，不额外提示
        elapsed=f'距离上一条消息（{format_time(last)}）已经过去约 {format_elapsed((now-last).total_seconds())}。'
    return _TIME_NOTE.format(now=format_time(now),elapsed=elapsed)

class PromptBuilder:
    def __init__(self,characters_root=None): self.characters_root=Path(characters_root) if characters_root else None
    def effective_system_prompt(self,settings,character_id,role_prompt=None):
        if role_prompt and role_prompt.strip(): return role_prompt.strip()
        if self.characters_root:
            prompt=load_character_prompt(self.characters_root,character_id)
            if prompt.strip(): return prompt.strip()
        return settings.default_system_prompt.strip()
    def build_messages(self,settings,character_id,history,user_text,role_prompt=None,now=None,memory_text=None,
                       roleplay_enabled=None,roleplay_scene=None,roleplay_cast=None,memory_payload=None,
                       act_block=None,identity=None):
        """时间感知：历史用户消息前加发送时间标记，system 末尾附当前时间与距上条消息的间隔。
        时间取自已落盘的 ChatMessage.created_at，只在发给模型时附加，不改动会话文件。
        memory_text（user 层快照，pet/chat/memory.injection_text 渲染）追加在
        system 最末、与 time_context 同级；fact/lesson/topic 的按需命中由
        augment_for_turn 用本次真实用户消息补第二段（首轮不命中）。
        v2b：优先使用显式 memory_payload（pet/chat/memory.memory_payload）——
        它的 text 作 user 快照、entries 作命中候选、session_key 作已见命名空间，
        并负责调用 note_hits；与 memory_text 同时给时以 payload 为准（不重复注入）。
        None/空 = 不注入，输出与无记忆逐字节一致。
        roleplay_*：每宠场景卡；未显式传入时从 settings 上读同名属性（测试/旧调用方
        直接构造 ChatSettings() 时为默认关）。引导的注入门槛是**有效 system prompt
        非空**（role_prompt → 角色 manifest 的 persona → 全局默认人设），不是
        「persona 段」字面：清空 System Prompt 且角色 manifest 无 persona 时，没有
        身份的扮演没有意义，引导与场景卡都不注入。场景/人物留空只表示不额外约束
        设定，引导仍会追加。
        identity：名字 + 用户手写人设（``compose_identity``）。置顶在 system 最前：
        角色包自带 prompt / 全局默认提示词随后，但“我是谁”由这里说了算。
        不传 = 与没有这个功能时逐字节一致。"""
        now=(now or datetime.now().astimezone()).astimezone()
        if roleplay_enabled is None:
            roleplay_enabled=bool(getattr(settings,'roleplay_enabled',False))
        if roleplay_scene is None:
            roleplay_scene=getattr(settings,'roleplay_scene','')
        if roleplay_cast is None:
            roleplay_cast=getattr(settings,'roleplay_cast','')
        system=self.effective_system_prompt(settings,character_id,role_prompt)
        identity_text=str(identity or '').strip()
        if identity_text:
            system=f'{identity_text}\n\n{system}'.strip()
        if roleplay_enabled and system.strip():
            system=(system+'\n\n'+roleplay_context(roleplay_scene,roleplay_cast)).strip()
        # 演出清单（pet/acts/hint.act_prompt_block）：关掉/无桌宠/无素材时是空串，
        # 于是提示词与没有这个功能时逐字节一致。夹在扮演引导之后、时间之前——
        # 同属行为约束，模型对靠后的段落更敏感。
        act_block=str(act_block or '').strip()
        if act_block: system=(system+'\n\n'+act_block).strip()
        system=(system+'\n\n'+time_context(history,now)).strip()
        if memory_payload is not None:
            memory_text=memory_payload.text
        memory_text=str(memory_text or '').strip()
        if memory_text: system=(system+'\n\n'+memory_text).strip()
        recall_text=augment_for_turn(
            memory_payload.entries if memory_payload is not None else [],
            memory_payload.session_key if memory_payload is not None else '',
            history,
            user_text,
            now=now,
            note_hits=memory_payload.note_hits if memory_payload is not None else None,
        )
        if recall_text: system=(system+'\n\n'+recall_text).strip()
        trimmed=self.trim_history(history,settings.history_message_limit,settings.history_char_limit)
        return [{'role':'system','content':system},*({'role':m.role,'content':stamp_message(m)} for m in trimmed),{'role':'user','content':user_text.strip()}]
    @staticmethod
    def trim_history(history,message_limit,char_limit):
        result=[]; used=0; limit=max(100,char_limit)
        for m in reversed(history):
            if result and (len(result)>=max(1,message_limit) or used+len(m.content)>limit): break
            if not result and len(m.content)>limit:
                result.append(ChatMessage(m.role,m.content[-limit:],m.created_at,m.message_id)); break
            result.append(m); used+=len(m.content)
        return list(reversed(result))