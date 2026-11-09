# -*- coding: utf-8 -*-
"""窗口侧整链：``cue`` → 导演闸门 → 真实素材名 → 播放请求。

``PetChatLink.act`` 只是转发，真正决定「演不演、演哪一段」的是
``PetWindow.request_act``。这里用 ``__new__`` 造一个只带必要属性的窗口
（仓库既有手法，见 ``test_cursor_visibility``），把类上的真实方法跑起来：
``act_repertoire`` / ``act_director`` / ``_act_duration_seconds`` / ``request_act``。

只要 ``request_link_anim`` 收到的名字**不在当前库的名字集里**，真实窗口会在
``_switch`` 之后静默不动——所以断言落点就是"被请求的名字必须真实存在"。
"""
from __future__ import annotations

from types import SimpleNamespace

from pet.acts import ActCue
from pet.window import PetWindow

#: 取一小撮真实素材名冒充"当前角色包"，避免依赖 assets 是否装好
POOL = ('害羞惊讶', '开心跃动', '写代码', '吃零食', '伸懒腰', '转圈')


def _window(monkeypatch, *, cfg=None, frames=100):
    win = PetWindow.__new__(PetWindow)
    if cfg is None:
        cfg = SimpleNamespace(get=lambda key, default=None: default)
    win.cfg = cfg
    win.acts = list(POOL)
    win.clicks = []
    win.moves = []
    win.anim = '待机'
    win.lib = SimpleNamespace(frames=lambda name: frames)
    played = []
    win._played = played
    # 播放通道换成录音：整链只关心"最后请求了哪一段"
    win.request_link_anim = lambda name: played.append(name)
    return win


def _cue(text='害羞', reply_chars=40):
    return ActCue(queries=(text,), reply_chars=reply_chars)


def test_cue_resolves_to_a_real_clip_and_reaches_the_play_channel(monkeypatch):
    win = _window(monkeypatch)
    assert win.request_act(_cue('害羞')) is True
    assert win._played == ['害羞惊讶']


def test_resolved_name_always_exists_in_the_current_pool(monkeypatch):
    """模型写的短名 → 素材名，必须能在当前库的名录里找到。"""
    win = _window(monkeypatch)
    repertoire = win.act_repertoire()
    for short in ('害羞', '写代码', '吃零食', '伸懒腰', '转圈', '开心跃动'):
        name = repertoire.resolve(short)
        assert name in POOL, f'{short} 解析成了库里没有的 {name}'


def test_second_identical_request_is_blocked_by_cooldown(monkeypatch):
    win = _window(monkeypatch)
    assert win.request_act(_cue('害羞')) is True
    # 冷却（缺省 8 秒）内再点一次：不演，也不该把播放通道顶掉
    assert win.request_act(_cue('害羞')) is False
    assert win._played == ['害羞惊讶']


def test_disabled_switch_blocks_everything(monkeypatch):
    cfg = SimpleNamespace(get=lambda key, default=None: False if key == 'chat_act_enabled' else default)
    win = _window(monkeypatch, cfg=cfg)
    assert win.request_act(_cue('害羞')) is False
    assert win._played == []


def test_unknown_name_is_dropped_instead_of_playing_nothing(monkeypatch):
    win = _window(monkeypatch)
    assert win.request_act(_cue('倒立转体三周半')) is False
    assert win._played == []


def test_long_clip_is_skipped_for_a_one_word_reply(monkeypatch):
    # 100 帧 × 42ms ≈ 4.2s 的素材
    win = _window(monkeypatch, frames=100)
    win.act_director()._long_act = 2.0  # 把"长素材"的界下调到这段素材之上
    assert win.request_act(_cue('害羞', reply_chars=2)) is False
    assert win._played == []
    assert win.request_act(_cue('害羞', reply_chars=80)) is True
    assert win._played == ['害羞惊讶']


def test_repertoire_is_rebuilt_when_the_character_changes(monkeypatch):
    win = _window(monkeypatch)
    before = win.act_repertoire()
    win.acts = ['螃蟹走路']
    after = win.act_repertoire()
    assert after is not before
    assert after.resolve('走过去') == '螃蟹走路'
    assert after.resolve('害羞') is None
