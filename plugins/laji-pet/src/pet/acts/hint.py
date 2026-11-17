# -*- coding: utf-8 -*-
"""演出联动的开关、参数与提示词注入点。

为什么配置读取单独一层
----------------------
同一组配置有三个消费者：提示词注入（要不要给模型讲清单）、导演闸门（冷却多久）、
设置页（回显与写回）。三处各读一遍 ``config.get(...)`` 就会出现"提示词说能演、
闸门却认为关了"这类打架。口径只留这一份，且**容错**：配置被手改成
``"false"`` / ``"关"`` / ``None`` 都必须解析成确定值，绝不抛异常。
"""
from __future__ import annotations

#: 缺省开启：这条通道本身是惰性的——模型不写标记就什么都不会发生，而它写标记的
#: 前提是提示词里给了清单。用户不想要，一个开关就能整体关掉（关掉后连清单都不注入）。
DEFAULT_ENABLED = True
#: 缺省全局冷却：一条回复演完之后，至少隔这么久才会再演下一段
DEFAULT_COOLDOWN_SECONDS = 8.0
#: 冷却的可配范围（秒）；0 = 不冷却（不推荐，模型中招时会把桌宠变成陀螺）
COOLDOWN_RANGE = (0.0, 120.0)

_OFF_VALUES = frozenset({'0', 'false', 'no', 'off', '否', '关'})


def act_enabled(config) -> bool:
    """``chat_act_enabled``：关掉后既不注入清单也不放行演出。"""
    if config is None:
        return DEFAULT_ENABLED
    try:
        raw = config.get('chat_act_enabled', DEFAULT_ENABLED)
    except Exception:  # noqa: BLE001 - 读配置失败退回缺省，不影响聊天
        return DEFAULT_ENABLED
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return DEFAULT_ENABLED
    text = str(raw).strip().lower()
    if not text:
        return DEFAULT_ENABLED
    return text not in _OFF_VALUES


def act_cooldown_seconds(config) -> float:
    """``chat_act_cooldown_seconds``：全局冷却秒数（钳在 ``COOLDOWN_RANGE`` 内）。"""
    low, high = COOLDOWN_RANGE
    if config is None:
        return DEFAULT_COOLDOWN_SECONDS
    try:
        raw = config.get('chat_act_cooldown_seconds', DEFAULT_COOLDOWN_SECONDS)
        value = float(raw)
    except Exception:  # noqa: BLE001 - 读配置/转换失败都退回缺省
        return DEFAULT_COOLDOWN_SECONDS
    return max(low, min(high, value))


def act_prompt_block(config, pet_window) -> str:
    """给系统提示用的演出说明 + 短名清单；不需要注入时返回空串。

    三个"不注入"条件，任何一个成立就整体闭嘴：开关关着、当前没有桌宠窗口
    （无界面/测试拓扑）、角色包一个可演素材都没有。空串是幂等的——提示词与
    "没有这个功能"逐字一致。
    """
    if not act_enabled(config):
        return ''
    repertoire_getter = getattr(pet_window, 'act_repertoire', None)
    if not callable(repertoire_getter):
        return ''
    try:
        repertoire = repertoire_getter()
    except Exception:  # noqa: BLE001 - 剧目表建不出来就退回无演出
        return ''
    if repertoire is None or not len(repertoire):
        return ''
    return repertoire.prompt_block()


__all__ = [
    'COOLDOWN_RANGE',
    'DEFAULT_COOLDOWN_SECONDS',
    'DEFAULT_ENABLED',
    'act_cooldown_seconds',
    'act_enabled',
    'act_prompt_block',
]
