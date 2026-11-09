# -*- coding: utf-8 -*-
"""聊天正文里的演出标记：语法、流式剥离、跨 delta 缓冲。

模型要驱动桌宠的身体，就得有一条**显式**通道：正文里写 ``[[act:短名]]``。

为什么不用括号启发式
--------------------
``pet/chat/markdown_view.py`` 的动作段是"括号形状"启发式（正文里的 ``f(x)``、
``(共 3 个)`` 都会被当成动作段，该模块已把这条登记为已知限制）。那条启发式只
影响**渲染**，误判的代价是几个字变斜体；演出指令误判的代价是"随口一句话就跳
一段舞"。所以指令必须显式、唯一、自定界，并且能从给用户看的文本里彻底剥掉。

为什么不用 tools
----------------
``pet/chat/providers.py`` 的 tools 链路（联网检索 ``_research``）是**独立一轮非
思考请求**：DeepSeek 思考模式带 tools 要求回传历史所有轮次的 reasoning_content，
而会话历史并不保存思维链（见该模块 ``_research`` 的注释）。把演出挂在正式流式
回答的 tools 上会踩同一个坑；内联标记对任何 provider 都成立，也不多一次往返。

为什么要在流式里缓冲
--------------------
标记可能被切在两个 delta 之间（``"…[[ac"`` + ``"t:写代码]]"``）。裸正则逐块匹配
会把半个标记漏给用户看，随后又永远等不到完整标记。``DirectiveStream`` 因此把
"可能是标记开头"的尾巴扣住不发（最多 6 个字符），下一次 delta 或 ``finish()``
时再决定它是标记还是普通正文。
"""
from __future__ import annotations

import re

#: 标记本体：``[[act:名字]]``。全角冒号一起认（中文输入法下模型常打成「：」）。
#: 名字里不允许出现方括号与换行：那正是"标记到此为止"的边界，避免贪婪吞掉正文。
MARKER_RE = re.compile(r'\[\[\s*act\s*[:：]\s*([^\[\]\n]{1,32}?)\s*\]\]', re.IGNORECASE)

#: 所有合法的标记开头（小写形态）。缓冲判定用它：尾巴只要还是其中某个的前缀，
#: 就有可能是被切断的标记，不能当正文发出去。
_OPENERS = ('[[act:', '[[act：')
_MAX_OPENER_LEN = max(len(opener) for opener in _OPENERS)
#: 未闭合标记最长能被扣住多少字符（32 字名字 + 开头本身 + 余量）
_UNCLOSED_MAX_CHARS = 48
#: 标记开头（宽松匹配：允许中间空白与全角冒号，和 ``MARKER_RE`` 的口径一致）
_OPENER_RE = re.compile(r'\[\[\s*act\s*[:：]', re.IGNORECASE)

_BLANK_LINES = re.compile(r'\n{3,}')
_TRAILING_SPACES = re.compile(r'[ \t]+\n')


def parse_markers(text: str) -> tuple[str, ...]:
    """抽出正文里所有演出标记的名字（保序去重，含空白的名字已 strip）。"""
    found = (match.strip() for match in MARKER_RE.findall(str(text or '')))
    return tuple(dict.fromkeys(name for name in found if name))


def strip_markers(text: str) -> str:
    """去掉正文里的全部演出标记，其余字符原样保留。"""
    return MARKER_RE.sub('', str(text or ''))


def holdback_length(text: str) -> int:
    """``text`` 末尾有多少字符"可能是被切断的标记"，必须扣住不发。

    两种情况，取较大者：

    1. **尾巴是标记开头的前缀**：``[`` / ``[[`` / ``[[a`` … ``[[act:``。只认真正
       的标记前缀，不做形状猜测：正文里正常出现的 ``[1]``、``[哈哈]`` 都以 ``[``
       开头，最多被扣一个字符，下一个 delta 立刻放出来。
    2. **已经出现开头的标记还没闭合**：模型可能把 ``[[act:害羞`` 和 ``]]`` 分在
       两个 delta 里。只管尾部前缀拦不住它（尾巴是「害羞」不是前缀），会把半个
       标记当正文露给用户。所以从最后一个没闭合的 ``[[act:`` 起全部扣住。

    第二种情况带长度上限：标记名不许超过 32 字，超出 ``_UNCLOSED_MAX_CHARS`` 的
    未闭合开头就当普通正文放出去，免得一个误输入的 ``[[act:`` 把整条回复吞掉。
    """
    if not text:
        return 0
    return max(_tail_prefix_length(text), _unclosed_length(text))


def _tail_prefix_length(text: str) -> int:
    lowered = text.casefold()
    for size in range(min(len(lowered), _MAX_OPENER_LEN), 0, -1):
        tail = lowered[-size:]
        if any(opener.startswith(tail) for opener in _OPENERS):
            return size
    return 0


def _unclosed_length(text: str) -> int:
    """从最后一个未闭合的标记开头到末尾的字符数；没有则 0。"""
    start = 0
    while True:
        match = _OPENER_RE.search(text, start)
        if match is None:
            return 0
        closing = text.find(']]', match.end())
        if closing == -1:
            span = len(text) - match.start()
            return span if span <= _UNCLOSED_MAX_CHARS else 0
        start = closing + 2


def tidy_reply(text: str) -> str:
    """收尾整理：抹掉剥离标记留下的空行与行尾空格，不动正文内容。"""
    cleaned = _BLANK_LINES.sub('\n\n', _TRAILING_SPACES.sub('\n', str(text or '')))
    return cleaned.strip('\n')


class DirectiveStream:
    """把一条回复的流式片段变成「可显示正文 + 演出名」。

    用法（``pet/chat/service.py`` 是唯一调用方）::

        stream = DirectiveStream()
        visible = stream.feed(chunk)         # 可显示增量（可能为空串）
        queries, text = stream.finish(full)  # 收尾：演出名 + 权威全文

    设计取舍：``finish`` 返回的全文以**已发出的可见文本**为准（而不是 provider
    的原文）。这样无论 provider 有没有发 delta、delta 有没有被上游丢掉，落盘与
    展示的永远是同一份、且一定不含标记的文本。
    """

    __slots__ = ('_raw', '_pending', '_visible', '_queries')

    def __init__(self) -> None:
        self._raw = ''        # 已喂进来的原文（finish 对账用）
        self._pending = ''    # 扣住的"可能是标记开头"的尾巴
        self._visible = ''    # 已确认可显示的正文
        self._queries: list[str] = []

    def feed(self, chunk: str) -> str:
        """吃一段增量，返回本次可以显示的正文（可能为空串）。"""
        if not chunk:
            return ''
        self._raw += chunk
        buffer = self._pending + chunk
        self._queries.extend(parse_markers(buffer))
        text = strip_markers(buffer)
        hold = holdback_length(text)
        cut = len(text) - hold
        visible, self._pending = text[:cut], text[cut:]
        self._visible += visible
        return visible

    def finish(self, full_text: str | None = None) -> tuple[tuple[str, ...], str]:
        """收尾：返回 ``(演出名元组, 不含标记的全文)``。

        ``full_text`` 是 provider 给的权威全文。只在它"以已喂进来的原文为前缀"
        时才用它补齐差额（不发 delta 的 provider 就靠这条路径）；对不上就丢掉它，
        免得把用户已经看到的正文替换成另一份。
        """
        if full_text is not None and full_text != self._raw:
            if full_text.startswith(self._raw):
                self.feed(full_text[len(self._raw):])
        tail = self._pending
        self._queries.extend(parse_markers(tail))
        self._visible += strip_markers(tail)
        self._pending = ''
        self._raw = ''
        queries = tuple(dict.fromkeys(name for name in self._queries if name))
        self._queries = []
        text = tidy_reply(self._visible)
        # 完整复位：同一个 stream 可能被复用，上一条回复的正文绝不能漏进下一条
        self._visible = ''
        return queries, text

    def visible_text(self) -> str:
        """当前已确认的可见正文（诊断/测试用，不含被扣住的尾巴）。"""
        return self._visible


__all__ = [
    'MARKER_RE',
    'DirectiveStream',
    'holdback_length',
    'parse_markers',
    'strip_markers',
    'tidy_reply',
]
