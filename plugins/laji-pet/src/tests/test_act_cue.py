# -*- coding: utf-8 -*-
"""``ActCue`` 的“用户点名”凭据：嘴和身体别打架。"""
from __future__ import annotations

from types import SimpleNamespace

from pet.acts import ActCue, user_asked


def test_user_asked_is_true_when_the_user_named_the_act():
    cue = ActCue.single('舞狮', user_text='再来一次舞狮嘛')
    assert cue.user_asked() is True


def test_user_asked_ignores_spacing_and_case():
    assert ActCue.single('hello', user_text=' say  HELLO ').user_asked() is True


def test_user_asked_is_false_for_a_self_chosen_act():
    cue = ActCue.single('舞狮', user_text='今天天气不错')
    assert cue.user_asked() is False


def test_user_asked_is_false_without_a_user_text():
    assert ActCue.single('舞狮').user_asked() is False


def test_module_helper_tolerates_cues_without_the_method():
    """测试替身/旧构造点只有 queries；缺能力就当模型自选。"""
    assert user_asked(SimpleNamespace(queries=('舞狮',))) is False
    assert user_asked(None) is False
    assert user_asked(ActCue.single('舞狮', user_text='舞狮')) is True
