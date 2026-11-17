# -*- coding: utf-8 -*-
"""配置口径与提示词注入点（``pet/acts/hint.py``）。

两条硬约束：
1. 配置被手改成奇怪的值也必须解析成确定结果，绝不抛异常（它跑在聊天主路径上）；
2. 任何"不该注入"的情况都返回空串——空串意味着提示词与没有这个功能逐字一致。
"""
from __future__ import annotations

from pet.acts.hint import (
    COOLDOWN_RANGE,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_ENABLED,
    act_cooldown_seconds,
    act_enabled,
    act_prompt_block,
)
from pet.acts.repertoire import ActRepertoire


class Config(dict):
    """够用的 config 替身：只用 ``get``。"""

    def get(self, key, default=None):
        return dict.get(self, key, default)


class BrokenConfig:
    def get(self, key, default=None):
        raise RuntimeError('config unavailable')


class Window:
    """桌宠窗口替身：只暴露 ``act_repertoire`` 这一个公开入口。"""

    def __init__(self, names):
        self._repertoire = ActRepertoire(names)

    def act_repertoire(self):
        return self._repertoire


class BrokenWindow:
    def act_repertoire(self):
        raise RuntimeError('window torn down')


# ---------------------------------------------------------------- 开关
def test_enabled_defaults_to_on_when_unset_or_unreadable():
    assert act_enabled(None) is True
    assert act_enabled(Config()) is DEFAULT_ENABLED
    assert act_enabled(BrokenConfig()) is True


def test_enabled_parses_strings_and_bools():
    for raw in ('0', 'false', 'False', 'no', 'off', '关', '否'):
        assert act_enabled(Config(chat_act_enabled=raw)) is False
    for raw in ('1', 'true', 'on', '开', '是', True, 1):
        assert act_enabled(Config(chat_act_enabled=raw)) is True
    assert act_enabled(Config(chat_act_enabled=False)) is False


# ---------------------------------------------------------------- 冷却
def test_cooldown_defaults_and_clamps():
    assert act_cooldown_seconds(Config()) == DEFAULT_COOLDOWN_SECONDS
    assert act_cooldown_seconds(BrokenConfig()) == DEFAULT_COOLDOWN_SECONDS
    low, high = COOLDOWN_RANGE
    assert act_cooldown_seconds(Config(chat_act_cooldown_seconds=-5)) == low
    assert act_cooldown_seconds(Config(chat_act_cooldown_seconds=9999)) == high
    assert act_cooldown_seconds(Config(chat_act_cooldown_seconds='12')) == 12.0


def test_cooldown_survives_garbage_values():
    for raw in ('', 'abc', None, [], {}, 'nan'):
        value = act_cooldown_seconds(Config(chat_act_cooldown_seconds=raw))
        assert isinstance(value, float)
        assert COOLDOWN_RANGE[0] <= value <= COOLDOWN_RANGE[1]


# ---------------------------------------------------------------- 注入
def test_prompt_block_is_injected_for_a_playable_character():
    block = act_prompt_block(Config(), Window(('写代码', '吃晚餐')))
    assert '[[act:短名]]' in block
    assert '工作：写代码' in block


def test_prompt_block_is_empty_when_the_feature_is_off():
    window = Window(('写代码',))
    assert act_prompt_block(Config(chat_act_enabled=False), window) == ''
    assert act_prompt_block(Config(chat_act_enabled='0'), window) == ''


def test_prompt_block_is_empty_without_a_window_or_a_repertoire():
    assert act_prompt_block(Config(), None) == ''
    assert act_prompt_block(Config(), object()) == ''
    assert act_prompt_block(Config(), BrokenWindow()) == ''
    assert act_prompt_block(Config(), Window(())) == ''
