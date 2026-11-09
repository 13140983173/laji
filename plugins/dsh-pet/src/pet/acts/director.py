# -*- coding: utf-8 -*-
"""演出导演：模型想演，导演决定现在能不能演。

为什么单独一层
--------------
"认出媒体名"（``ActRepertoire``）和"该不该现在演"是两件事。后者全是**时间与
上下文**的判断：刚演过没有、上一分钟演了几次、这段素材是不是比这条回复长、
用户是不是刚把它抓起来。把这些塞进窗口、塞进聊天侧，会变成两处各写一半的
if 堆；独立成这一层后，闸门规则只有一份，且能用假时钟逐条测。

闸门顺序（先便宜的、先不可恢复的）::

    enabled → 有候选 → 全局冷却 → 每分钟配额 → 解析得到素材名 → 不与上次重复
            → 长动作不配短回复 → 放行

"解析"排在冷却与配额之后是刻意的：模型偶尔写错一个名字不该消耗配额，但已经
在上一次演出里放行过的规则不该被一个错名字绕过。

时钟注入
--------
所有时间判断走 ``clock``（缺省 ``time.monotonic``）。测试用假时钟把冷却与配额
逐条卡到边界，不靠 sleep。
"""
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass

#: 放行
REASON_OK = 'ok'
#: 开关关（``chat_act_enabled``）——用户明确不要演出
REASON_DISABLED = 'disabled'
#: 这一轮没有任何候选
REASON_EMPTY = 'empty'
#: 全局冷却中（任意动作刚演过）
REASON_COOLDOWN = 'cooldown'
#: 一分钟配额用尽
REASON_RATE_LIMITED = 'rate_limited'
#: 认不出这个说法（或不是当前角色包的素材）
REASON_UNRESOLVED = 'unresolved'
#: 与上一次演的是同一段素材（连续重复最出戏）
REASON_REPEAT = 'repeat'
#: 素材明显长于这条回复（"嗯"配一段独舞）
REASON_TOO_LONG = 'too_long_for_reply'

#: 缺省闸门（窗口侧会用配置里的冷却覆盖它）
DEFAULT_COOLDOWN_SECONDS = 8.0
DEFAULT_PER_MINUTE = 4
DEFAULT_LONG_ACT_SECONDS = 6.0
DEFAULT_SHORT_REPLY_CHARS = 24

#: 同一段素材的最短重演间隔。只有**紧跟着的上一段**才叫重复：用户隔了半分钟
#: 再要一次舞狮，那是他想看，不是抽风。没有这个窗口时，同一段素材一旦演过就
#: 再也演不了（除非中间插了别的）——嘴答应了、身体不动。
DEFAULT_REPEAT_WINDOW_SECONDS = 20.0
#: 用户点名要看时，冷却只起“别在同一个瞬间重复触发”的作用
USER_ASKED_MIN_GAP_SECONDS = 1.0


@dataclass(frozen=True)
class ActDecision:
    """一次判定结果；``accepted`` 只看 ``name`` 有没有值。"""

    query: str = ''
    name: str = ''
    reason: str = REASON_EMPTY

    @property
    def accepted(self) -> bool:
        return bool(self.name)

    def describe(self) -> str:
        """日志/诊断用的一行话（永不抛异常）。"""
        if self.accepted:
            return f'{self.query} -> {self.name}'
        return f'{self.query or "-"} 未演({self.reason})'


def _as_value(value, default):
    """闸门参数允许传常量或回调：配置改了不必重建导演。"""
    if value is None:
        return default
    if callable(value):
        try:
            return value()
        except Exception:  # noqa: BLE001 - 闸门参数读失败不该拦住演出判定
            return default
    return value


class ActDirector:
    """把``候选说法``变成"这次演/不演"。"""

    def __init__(self, resolve, *, duration=None, enabled=None, cooldown=None,
                 clock=None, per_minute: int = DEFAULT_PER_MINUTE,
                 window_seconds: float = 60.0,
                 long_act_seconds: float = DEFAULT_LONG_ACT_SECONDS,
                 short_reply_chars: int = DEFAULT_SHORT_REPLY_CHARS,
                 repeat_window_seconds: float = DEFAULT_REPEAT_WINDOW_SECONDS) -> None:
        #: ``(说法) -> 素材名 | None``，通常是 ``ActRepertoire.resolve``
        self._resolve = resolve
        #: ``(素材名) -> 秒 | None``；None = 这一层拿不到时长，跳过时长闸门
        self._duration = duration
        self._enabled = enabled
        self._cooldown = cooldown
        self._clock = clock if callable(clock) else time.monotonic
        self._per_minute = max(0, int(per_minute))
        self._window = max(1.0, float(window_seconds))
        self._long_act = max(0.0, float(long_act_seconds))
        self._short_reply = max(0, int(short_reply_chars))
        self._repeat_window = max(0.0, float(repeat_window_seconds))
        self._stamps: deque[float] = deque()
        self._last_at: float | None = None
        self._last_name = ''
        #: 放行计数与各拒绝原因的计数（诊断/回归用，不参与判定）
        self.accepted_count = 0
        self.dropped: Counter = Counter()

    # ------------------------------------------------------------ 判定
    def decide(self, queries, *, reply_chars: int = 0, user_asked: bool = False) -> ActDecision:
        """对一条回复的候选说法做判定，最多放行一个。

        ``user_asked`` = 用户原话里就点了这个动作（不是模型自选）：这时不拦
        "重复"，否则用户说三次舞狮只能看见一次。冷却与配额仍照拦。
        """
        candidates = [str(q).strip() for q in (queries or ()) if str(q).strip()]
        if not _as_value(self._enabled, True):
            return self._drop(candidates[0] if candidates else '', REASON_DISABLED)
        if not candidates:
            return self._drop('', REASON_EMPTY)
        now = self._clock()
        cooldown = max(0.0, float(_as_value(self._cooldown, DEFAULT_COOLDOWN_SECONDS)))
        if user_asked:
            # 用户自己点了两遍舞狮：拦着不演就是无视他
            cooldown = min(cooldown, USER_ASKED_MIN_GAP_SECONDS)
        if (self._last_at is not None and cooldown > 0.0
                and now - self._last_at < cooldown):
            return self._drop(candidates[0], REASON_COOLDOWN)
        if self._per_minute and self._count_recent(now) >= self._per_minute:
            return self._drop(candidates[0], REASON_RATE_LIMITED)
        name = ''
        hit_query = candidates[0]
        for query in candidates:
            resolved = self._resolve_name(query)
            if resolved:
                name, hit_query = resolved, query
                break
        if not name:
            return self._drop(candidates[0], REASON_UNRESOLVED)
        if not user_asked and self._is_repeat(name, now):
            return self._drop(candidates[0], REASON_REPEAT)
        if self._too_long_for(name, int(reply_chars or 0)):
            return self._drop(candidates[0], REASON_TOO_LONG)
        self._last_at = now
        self._last_name = name
        self._stamps.append(now)
        self.accepted_count += 1
        return ActDecision(query=hit_query, name=name, reason=REASON_OK)

    def reset(self) -> None:
        """清空节流状态（换角色、重置设置时用；不影响统计）。"""
        self._stamps.clear()
        self._last_at = None
        self._last_name = ''

    # ------------------------------------------------------------ 诊断
    def stats(self) -> dict:
        """``{'accepted': n, 'dropped': {原因: n}}``（日志/设置页展示用）。"""
        return {'accepted': self.accepted_count, 'dropped': dict(self.dropped)}

    def last_name(self) -> str:
        return self._last_name

    # ------------------------------------------------------------ 内部
    def _drop(self, query: str, reason: str) -> ActDecision:
        self.dropped[reason] += 1
        return ActDecision(query=str(query or ''), reason=reason)

    def _resolve_name(self, query: str) -> str:
        try:
            resolved = self._resolve(query)
        except Exception:  # noqa: BLE001 - 解析实现出错按"认不出"处理，不炸聊天
            return ''
        return str(resolved or '').strip()

    def _count_recent(self, now: float) -> int:
        while self._stamps and now - self._stamps[0] > self._window:
            self._stamps.popleft()
        return len(self._stamps)

    def _is_repeat(self, name: str, now: float) -> bool:
        """与上一段同名，且还在重演窗口内。"""
        if name != self._last_name or self._last_at is None:
            return False
        window = max(0.0, float(_as_value(self._repeat_window,
                                          DEFAULT_REPEAT_WINDOW_SECONDS)))
        return window > 0.0 and now - self._last_at < window

    def _too_long_for(self, name: str, reply_chars: int) -> bool:
        """动作明显长于回复 → 不要（0 秒回复长度 = 聊天侧没给，跳过这条闸门）。"""
        if not reply_chars or not callable(self._duration) or self._long_act <= 0:
            return False
        if reply_chars >= self._short_reply:
            return False
        try:
            seconds = self._duration(name)
        except Exception:  # noqa: BLE001 - 时长读不到就不做这条判断
            return False
        if seconds is None:
            return False
        try:
            return float(seconds) > self._long_act
        except (TypeError, ValueError):
            return False


__all__ = [
    'ActDecision',
    'ActDirector',
    'DEFAULT_COOLDOWN_SECONDS',
    'DEFAULT_LONG_ACT_SECONDS',
    'DEFAULT_PER_MINUTE',
    'DEFAULT_SHORT_REPLY_CHARS',
    'REASON_COOLDOWN',
    'REASON_DISABLED',
    'REASON_EMPTY',
    'REASON_OK',
    'REASON_RATE_LIMITED',
    'REASON_REPEAT',
    'REASON_TOO_LONG',
    'REASON_UNRESOLVED',
]
