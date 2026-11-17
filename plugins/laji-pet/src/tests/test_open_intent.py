# -*- coding: utf-8 -*-
"""「打开 X」的本地意图规则。

重点不是覆盖面，而是**该沉默的时候必须沉默**：桌宠擅自弹开始菜单，比不动手
更烦人。所以下面一半是反例。
"""
from __future__ import annotations

import pytest

from pet import open_intent as oi

# ---------------------------------------------------------------- 该动手
@pytest.mark.parametrize("text,expect", [
    ("帮我打开豆包", "豆包"),
    ("打开豆包", "豆包"),
    ("帮我开一下豆包吧", "豆包"),
    ("把豆包打开", "豆包"),
    ("启动 Apifox", "Apifox"),
    ("运行 chrome", "chrome"),
    ("请你打开一下微信谢谢", "微信"),
    ("打开D盘", "D盘"),
])
def test_parses_clear_commands(text, expect):
    assert oi.parse(text) == expect


# ---------------------------------------------------------------- 不许动手
@pytest.mark.parametrize("text", [
    "怎么打开豆包",          # 在问方法
    "豆包怎么打开",          # 倒装疑问
    "为什么打不开豆包",
    "别打开豆包",            # 否定
    "不用打开豆包",
    "能不能打开豆包",        # 在问能力
    "打开豆包了吗",          # 在问结果（句尾一个"吗"就翻案）
    "豆包在哪里",
    "今天天气不错",
    "打开",                  # 没有宾语
    "",
    None,
])
def test_stays_silent_when_not_a_command(text):
    assert oi.parse(text) is None


def test_strips_polite_shell():
    assert oi.parse("麻烦你帮我打开一下飞书。") == "飞书"


def test_rejects_absurd_length():
    assert oi.parse("打开" + "x" * 200) is None
