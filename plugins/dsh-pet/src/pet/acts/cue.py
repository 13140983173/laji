# -*- coding: utf-8 -*-
"""一次回复提出的演出席位（模型意图 → 桌宠的搬运结构）。

它只装**意图**，不装结论：模型写了几个名字、这条回复有多长、来自哪条通道。
能不能真的演由 ``pet.acts.director.ActDirector`` 判，解析成哪个素材名由
``pet.acts.repertoire.ActRepertoire`` 判——三层各管一件事，谁也不替谁下结论。

为什么跨层传结构而不是传字符串：短回复配长动作的闸门需要 ``reply_chars``，
而"这条回复多长"只有聊天侧知道；把它和名字一起带过去，桌宠侧就不必回头问
聊天侧要上下文（单向依赖，易测）。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 通道标识：日志/诊断里区分"演出是谁提的"，也是将来加优先级的挂点。
SOURCE_CHAT = 'chat'
SOURCE_MENU = 'menu'


@dataclass(frozen=True)
class ActCue:
    """一条回复的演出席位；``queries`` 里可能不止一个（模型写了多个标记）。"""

    queries: tuple[str, ...] = ()
    reply_chars: int = 0
    source: str = SOURCE_CHAT
    #: 触发这条回复的用户原话。用户已经点名要看的动作不该被“别重复”闸门
    #: 挡掉（他说了三次舞狮，画面却只动一次，那是嘴和身体打架）。
    user_text: str = ''

    def __post_init__(self) -> None:
        # 冻结数据类也允许在 __post_init__ 里规范化：上游可能是 list/生成器，
        # 且模型常写出带空格的名字。这里统一成干净元组，下游不必再防。
        cleaned = tuple(
            str(item).strip() for item in (self.queries or ()) if str(item).strip()
        )
        object.__setattr__(self, 'queries', cleaned)
        object.__setattr__(self, 'reply_chars', max(0, int(self.reply_chars or 0)))
        object.__setattr__(self, 'source', str(self.source or SOURCE_CHAT))
        object.__setattr__(self, 'user_text', str(self.user_text or ''))

    def user_asked(self) -> bool:
        """用户原话里是不是就提到了这个动作（点名要看，不是模型自选）。"""
        text = ''.join(self.user_text.split()).casefold()
        if not text:
            return False
        return any(''.join(q.split()).casefold() in text for q in self.queries)

    def __bool__(self) -> bool:
        return bool(self.queries)

    def __len__(self) -> int:
        return len(self.queries)

    @classmethod
    def single(cls, query: str, *, reply_chars: int = 0,
               source: str = SOURCE_CHAT, user_text: str = '') -> 'ActCue':
        return cls(queries=(query,), reply_chars=reply_chars, source=source,
                   user_text=user_text)


__all__ = ['ActCue', 'SOURCE_CHAT', 'SOURCE_MENU', 'user_asked']


def user_asked(cue) -> bool:
    """``cue`` 是否带“用户点名要看”的免重复凭据。

    测试替身、旧构造点里可能没有这个能力（只有 ``queries``），所以只认方法
    存在性，缺失一律当“模型自选”。
    """
    check = getattr(cue, 'user_asked', None)
    if not callable(check):
        return False
    try:
        return bool(check())
    except Exception:
        return False
