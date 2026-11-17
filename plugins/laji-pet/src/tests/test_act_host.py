# -*- coding: utf-8 -*-
"""壳拓扑里的演出面（``pet/acts/host.py``）。

回归的正是这次断掉的那条链：overlay 拓扑没有 ``PetWindow``，聊天窗只认宿主上
``act_repertoire()`` / ``request_act(cue)`` 这两个洞。缺一个的症状是**静默失联**
——清单返回空串（模型压根不知道能演）、请求无人接收（写了标记也白写），
全程不抛异常、不打错误日志。所以测试必须断言"内容真的到了"，不能只断言不报错。
"""
from __future__ import annotations

from pet.acts.cue import ActCue
from pet.acts.hint import act_prompt_block
from pet.acts.host import ChatActHost

#: 一条一次性回应素材（可播、已登记短名）+ 一段动作素材
ACTS = ('点击回应 - 开心跃动', '写代码')
#: 30 帧 × 42ms ≈ 1.26s，短于闸门的"长动作配短回复"阈值，不干扰别的断言
SHORT_FRAMES = 30
LONG_REPLY = 200


class Config(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class Lib:
    def __init__(self, frames=SHORT_FRAMES):
        self._frames = frames

    def frames(self, name):
        return self._frames


class Shell:
    """overlay 壳替身：只暴露 host 真用到的四个面。"""

    def __init__(self, cats=None, frames=SHORT_FRAMES):
        self.cats = dict(cats or {'acts': list(ACTS), 'clicks': [], 'moves': []})
        self.lib = Lib(frames)
        self.played = []
        # 壳自己那份 config 只是身份载体，不该被当成真配置读
        self.config = object()

    def request_link_anim(self, name):
        self.played.append(name)


class BrokenShell:
    """分类表读不出来（换角色瞬间/壳正在重建）的壳。"""

    def __init__(self):
        self.lib = Lib()
        self.played = []

    @property
    def cats(self):
        raise RuntimeError('cats 正在重建')

    def request_link_anim(self, name):
        self.played.append(name)


def _host(config=None, shell=None):
    return ChatActHost(shell or Shell(), Config(config or {}))


# ---------------------------------------------------------------- 清单入提示词
def test_prompt_block_reaches_the_model_from_shell_cats():
    block = act_prompt_block(Config(), _host())
    assert block != ''
    assert '开心跃动' in block
    assert '写代码' in block


def test_prompt_block_is_empty_when_the_switch_is_off():
    host = _host({'chat_act_enabled': '0'})
    assert act_prompt_block(Config({'chat_act_enabled': '0'}), host) == ''


# ---------------------------------------------------------------- 请求真能开演
def test_request_act_plays_through_the_shell():
    shell = Shell()
    host = _host(shell=shell)
    cue = ActCue.single('开心跃动', reply_chars=LONG_REPLY)
    assert host.request_act(cue) is True
    assert shell.played == ['点击回应 - 开心跃动']


def test_request_act_refuses_names_the_pack_cannot_play():
    shell = Shell()
    host = _host(shell=shell)
    assert host.request_act(ActCue.single('没这段素材', reply_chars=LONG_REPLY)) is False
    assert host.request_act(ActCue()) is False
    assert host.request_act(None) is False
    assert shell.played == []


def test_switch_off_silences_request_act():
    shell = Shell()
    host = _host({'chat_act_enabled': 'false'}, shell)
    assert host.request_act(ActCue.single('开心跃动', reply_chars=LONG_REPLY)) is False
    assert shell.played == []


def test_long_clip_with_short_reply_is_refused():
    shell = Shell(frames=600)  # 600 × 42ms ≈ 25s
    host = _host(shell=shell)
    assert host.request_act(ActCue.single('开心跃动', reply_chars=2)) is False
    assert shell.played == []


# ---------------------------------------------------------------- 换角色
def test_repertoire_follows_the_current_character():
    shell = Shell()
    host = _host(shell=shell)
    assert host.act_repertoire().resolve('开心跃动') is not None
    shell.cats = {'acts': ['摇扇纳凉'], 'clicks': [], 'moves': []}
    assert host.act_repertoire().resolve('开心跃动') is None
    assert shell.played == []  # 换角色后旧名字不能再开演
    assert host.request_act(ActCue.single('开心跃动', reply_chars=LONG_REPLY)) is False


def test_unreadable_cats_degrade_to_no_acts():
    host = _host(shell=BrokenShell())
    assert len(host.act_repertoire()) == 0
    assert host.request_act(ActCue.single('开心跃动', reply_chars=LONG_REPLY)) is False
