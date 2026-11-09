# -*- coding: utf-8 -*-
"""导演闸门（``pet/acts/director.py``）：什么时候允许演，什么时候必须不演。

全部用假时钟把冷却与配额卡到边界：这类"过一会儿才能再演"的规则靠 sleep 测，
注定要么慢要么偶发失败。
"""
from __future__ import annotations

from pet.acts.director import (
    REASON_COOLDOWN,
    REASON_DISABLED,
    REASON_EMPTY,
    REASON_OK,
    REASON_RATE_LIMITED,
    REASON_REPEAT,
    REASON_TOO_LONG,
    REASON_UNRESOLVED,
    ActDirector,
)

NAMES = ('写代码', '开心跃动', '吃晚餐', '小幅度原地 360 度旋转展示')


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _resolver(name_map, unknown=None):
    """用固定映射当解析器：这里测闸门，不测语义收敛。"""
    def resolve(query):
        if query in name_map:
            return name_map[query]
        return unknown
    return resolve


def _director(clock, *, duration=None, enabled=True, cooldown=8.0, per_minute=4):
    return ActDirector(
        _resolver({'代码': '写代码', '开心': '开心跃动', '晚饭': '吃晚餐',
                   '转圈': '小幅度原地 360 度旋转展示'}),
        duration=duration, enabled=enabled, cooldown=cooldown, clock=clock,
        per_minute=per_minute,
    )


def test_first_cue_passes_and_is_reported():
    clock = FakeClock()
    decision = _director(clock).decide(['代码'])
    assert decision.accepted
    assert decision.name == '写代码'
    assert decision.reason == REASON_OK
    assert decision.query == '代码'


def test_disabled_blocks_everything_without_touching_state():
    clock = FakeClock()
    director = _director(clock, enabled=False)
    assert director.decide(['代码']).reason == REASON_DISABLED
    assert director.accepted_count == 0


def test_enabled_can_be_a_callable_so_config_changes_take_effect():
    flag = {'on': False}
    director = ActDirector(_resolver({'代码': '写代码'}), enabled=lambda: flag['on'],
                           clock=FakeClock())
    assert director.decide(['代码']).reason == REASON_DISABLED
    flag['on'] = True
    assert director.decide(['代码']).accepted


def test_no_candidates_is_empty_not_an_error():
    assert _director(FakeClock()).decide([]).reason == REASON_EMPTY
    assert _director(FakeClock()).decide(None).reason == REASON_EMPTY


def test_cooldown_is_measured_from_the_last_accepted_act():
    clock = FakeClock()
    director = _director(clock, cooldown=8.0)
    assert director.decide(['代码']).accepted
    clock.advance(7.9)
    assert director.decide(['开心']).reason == REASON_COOLDOWN
    clock.advance(0.1)
    assert director.decide(['开心']).accepted


def test_zero_cooldown_still_allows_every_reply():
    clock = FakeClock()
    director = _director(clock, cooldown=0.0)
    assert director.decide(['代码']).accepted
    assert director.decide(['开心']).accepted


def test_per_minute_quota_caps_bursts_then_recovers():
    clock = FakeClock()
    director = _director(clock, cooldown=0.0, per_minute=2)
    assert director.decide(['代码']).accepted
    clock.advance(1)
    assert director.decide(['开心']).accepted
    clock.advance(1)
    assert director.decide(['晚饭']).reason == REASON_RATE_LIMITED
    # 窗口滑过去之后配额回来（60 秒窗口，第一批已过期）
    clock.advance(60)
    assert director.decide(['晚饭']).accepted


def test_repeating_the_same_act_back_to_back_is_refused():
    clock = FakeClock()
    director = _director(clock, cooldown=0.0)
    assert director.decide(['代码']).accepted
    clock.advance(5)
    assert director.decide(['代码']).reason == REASON_REPEAT
    # 换一段就能演，之后旧的那段又可以演
    assert director.decide(['开心']).accepted
    clock.advance(5)
    assert director.decide(['代码']).accepted


def test_unresolvable_names_never_play():
    clock = FakeClock()
    decision = _director(clock).decide(['胡说八道'])
    assert not decision.accepted
    assert decision.reason == REASON_UNRESOLVED


def test_first_resolvable_candidate_wins_when_model_names_several():
    clock = FakeClock()
    decision = _director(clock).decide(['胡说八道', '晚饭', '代码'])
    assert decision.name == '吃晚餐'
    assert decision.query == '晚饭'


def test_long_act_is_refused_for_a_very_short_reply():
    clock = FakeClock()
    durations = {'写代码': 3.0, '小幅度原地 360 度旋转展示': 12.0}
    director = _director(clock, duration=durations.get, cooldown=0.0)
    assert director.decide(['转圈'], reply_chars=4).reason == REASON_TOO_LONG
    # 回复够长就放行
    assert director.decide(['转圈'], reply_chars=80).accepted


def test_duration_gate_is_skipped_when_chat_side_sends_no_length():
    clock = FakeClock()
    director = _director(clock, duration=lambda name: 99.0, cooldown=0.0)
    assert director.decide(['转圈'], reply_chars=0).accepted


def test_duration_lookup_failure_does_not_block_the_act():
    clock = FakeClock()

    def broken(name):
        raise RuntimeError('media missing')

    director = _director(clock, duration=broken, cooldown=0.0)
    assert director.decide(['转圈'], reply_chars=2).accepted


def test_resolver_failure_is_treated_as_unresolved():
    def broken(query):
        raise RuntimeError('boom')

    director = ActDirector(broken, clock=FakeClock())
    assert director.decide(['代码']).reason == REASON_UNRESOLVED


def test_stats_count_accepts_and_every_drop_reason():
    clock = FakeClock()
    director = _director(clock, cooldown=8.0)
    director.decide(['代码'])
    clock.advance(1)
    director.decide(['开心'])
    stats = director.stats()
    assert stats['accepted'] == 1
    assert stats['dropped'][REASON_COOLDOWN] == 1
    assert director.last_name() == '写代码'


def test_reset_clears_throttle_state_for_a_new_character():
    clock = FakeClock()
    director = _director(clock, cooldown=30.0)
    assert director.decide(['代码']).accepted
    director.reset()
    assert director.decide(['代码']).accepted
    assert director.last_name() == '写代码'


def test_same_act_can_play_again_after_the_repeat_window():
    """隔了半分钟再要一次舞狮：那是想看，不是抽风。

    回归：最初“与上一段同名就永远拒绝”，于是同一段素材一旦演过就再也演不了
    （除非中间插了别的）——嘴答应了、身体不动。
    """
    clock = FakeClock()
    director = _director(clock, cooldown=0.0)
    assert director.decide(['代码']).accepted
    clock.advance(30)
    assert director.decide(['代码']).accepted


def test_user_asked_repeat_is_not_blocked():
    clock = FakeClock()
    director = _director(clock, cooldown=8.0)
    assert director.decide(['代码']).accepted
    clock.advance(2)
    assert director.decide(['代码'], user_asked=True).accepted


def test_user_asked_only_shortens_the_cooldown_not_the_quota():
    clock = FakeClock()
    director = _director(clock, cooldown=30.0, per_minute=2)
    assert director.decide(['代码'], user_asked=True).accepted
    clock.advance(2)
    assert director.decide(['开心'], user_asked=True).accepted
    clock.advance(2)
    assert director.decide(['晚饭'], user_asked=True).reason == REASON_RATE_LIMITED


def test_user_asked_still_needs_a_moment_between_plays():
    """同一轮里重复 emit 不能把动动画刷成逐帧重启。"""
    clock = FakeClock()
    director = _director(clock, cooldown=8.0)
    assert director.decide(['代码'], user_asked=True).accepted
    assert director.decide(['代码'], user_asked=True).reason == REASON_COOLDOWN
