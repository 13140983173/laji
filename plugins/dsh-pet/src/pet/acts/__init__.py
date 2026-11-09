# -*- coding: utf-8 -*-
"""演出联动层：模型的一句话，怎么变成桌宠身上的一段动作。

四层，各管一件事，全部不依赖 Qt（可直接单测，也能被无界面拓扑引用）：

``directives``
    通道语法。模型在正文里写 ``[[act:短名]]``；``DirectiveStream`` 负责流式剥离，
    用户永远看不到标记。**唯一会产生文本副作用的层**，所以它只管文本。
``vocabulary`` / ``repertoire``
    语义层。素材名 ↔ 模型能念的短名/触发词；解析只认**当前角色包真实可播**的
    名字，认不出就不演。
``director``
    节流层。开关、全局冷却、每分钟配额、连续重复、长动作不配短回复。
``hint``
    配置口径与提示词注入点（开关关着时注入空串）。

接线方（谁把四层串起来）：

* 聊天侧 ``pet/chat/service.py``：一条回复流 → ``DirectiveStream`` → ``ActCue``
* 桌宠侧 ``pet/window.py``：``ActCue`` → ``ActDirector`` → ``request_link_anim``
* 提示词 ``pet/chat/prompt.py``：``hint.act_prompt_block`` 注入的演出清单
"""
from __future__ import annotations

from .cue import SOURCE_CHAT, SOURCE_MENU, ActCue, user_asked
from .directives import (
    MARKER_RE,
    DirectiveStream,
    holdback_length,
    parse_markers,
    strip_markers,
    tidy_reply,
)
from .director import ActDecision, ActDirector
from .hint import act_cooldown_seconds, act_enabled, act_prompt_block
from .repertoire import ActEntry, ActRepertoire

__all__ = [
    'MARKER_RE',
    'SOURCE_CHAT',
    'SOURCE_MENU',
    'ActCue',
    'ActDecision',
    'ActDirector',
    'ActEntry',
    'ActRepertoire',
    'DirectiveStream',
    'act_cooldown_seconds',
    'act_enabled',
    'act_prompt_block',
    'holdback_length',
    'parse_markers',
    'strip_markers',
    'tidy_reply',
    'user_asked',
]
