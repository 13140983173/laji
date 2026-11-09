# -*- coding: utf-8 -*-
"""引擎聊天路径的演出联动：标记剥离 + 开演意图。

桌宠聊天在引擎可用时走 ``LajiRunService``（daemon 的一条 run），不经过
``pet.chat.service`` 的 provider 路径。演出标记因此要在这一层剥，且剥离后
的正文才是展示与落盘的唯一口径。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pet.acts import DirectiveStream
from pet.agent_link.laji_run_service import LajiRunService
from pet.agent_link.persona_prompt import PERSONA_MAX_CHARS, compose_persona


def _delta_event(text: str, kind: int = 0):
    return SimpleNamespace(
        WhichOneof=lambda _name: "assistant_delta",
        assistant_delta=SimpleNamespace(kind=kind, text_delta=text),
    )


def _status_event(code: int):
    return SimpleNamespace(
        WhichOneof=lambda _name: "status_changed",
        status_changed=SimpleNamespace(status=code),
    )


@pytest.fixture()
def service(tmp_path):
    svc = LajiRunService(workspace_root=str(tmp_path))
    shown: list[str] = []
    acts: list = []
    done: list[str] = []
    svc.delta.connect(lambda _rid, text: shown.append(text))
    svc.act.connect(lambda _rid, cue: acts.append(cue))
    svc.finished.connect(lambda _rid, text: done.append(text))
    svc._act_stream = DirectiveStream()
    return svc, shown, acts, done


def test_marker_is_stripped_from_stream_and_finished_text(service):
    svc, shown, acts, done = service
    for piece in ("今天有点", "想动一动", "[[act:跳舞", "]]"):
        svc._handle_event("r1", _delta_event(piece))
    svc._handle_event("r1", _status_event(4))

    assert "".join(shown) == "今天有点想动一动"
    assert done == ["今天有点想动一动"]
    assert len(acts) == 1
    assert acts[0].queries == ("跳舞",)
    assert acts[0].reply_chars == len("今天有点想动一动")


def test_reply_without_marker_emits_no_act(service):
    svc, _shown, acts, done = service
    svc._handle_event("r2", _delta_event("嗯，我在。"))
    svc._handle_event("r2", _status_event(4))

    assert acts == []
    assert done == ["嗯，我在。"]


def test_reasoning_delta_never_reaches_the_bubble(service):
    svc, shown, acts, done = service
    svc._handle_event("r3", _delta_event("用户问跳舞", kind=1))
    svc._handle_event("r3", _delta_event("我只会晃肚皮。"))
    svc._handle_event("r3", _status_event(4))

    assert "".join(shown) == "我只会晃肚皮。"
    assert acts == []
    assert done == ["我只会晃肚皮。"]


def test_marker_only_reply_keeps_text_and_skips_act(service):
    """整条回复只有标记：正文留原文，不空着演一场。"""
    svc, _shown, acts, done = service
    svc._handle_event("r4", _delta_event("[[act:跳舞]]"))
    svc._handle_event("r4", _status_event(4))

    assert acts == []
    assert done == ["[[act:跳舞]]"]


def test_engine_path_carries_the_user_text_into_the_cue(service):
    """Engine path must carry the user words, else a named act is gated as
    if the model chose it on its own."""
    svc, _shown, _acts, _done = service
    svc._user_text = "please do happy again"
    clean, cue = svc._settle_act("ok[[act:happy]]")

    assert clean == "ok"
    assert cue.user_asked() is True


def test_persona_carries_act_block_after_identity():
    text = compose_persona("shenshen", "", "【演出】写完话再点标记。")
    assert text.startswith("You are ")
    assert "大肥鱼" in text
    assert text.endswith("【演出】写完话再点标记。")


def test_persona_without_act_block_is_identity_only():
    assert "【演出】" not in compose_persona("shenshen", "")


def test_persona_keeps_act_block_line_breaks():
    """分组清单必须保留分行：压平后模型分不出哪个短名属于哪个场合。

    真机证据：压平版写进 ``pet-persona.md`` 只剩 3 行（身份句 / 空行 / 一整行
    清单），而 ``prompt_block()`` 给的是抬头 5 行 + 每个分类 1 行。
    """
    from pet.acts.repertoire import ActRepertoire

    block = ActRepertoire(["点击回应-开心跃动", "写代码"]).prompt_block()
    text = compose_persona("shenshen", "", block)
    tail = text.split("\n\n", 1)[1]

    assert tail.splitlines() == block.splitlines()
    assert len(tail.splitlines()) > 3
    assert "\n情绪：" in tail


def test_persona_is_clipped_to_the_rust_limit():
    """Rust 侧按同一上限截断，超了就截到半句清单——这里先截。"""
    text = compose_persona("shenshen", "", "演" * (PERSONA_MAX_CHARS * 2))
    assert len(text) == PERSONA_MAX_CHARS


def test_overlay_anchor_forwards_both_act_faces():
    """气泡的 ``pet_window`` 是锚点：少了这两面，提示词没清单、标记也没人接。"""
    from pet.overlay_shell import _SpriteChatAnchor

    class _Shell:
        def __init__(self):
            self.calls = []

        def act_repertoire(self):
            return "REP"

        def request_act(self, cue):
            self.calls.append(cue)
            return True

    shell = _Shell()
    anchor = _SpriteChatAnchor(shell, sprite=None)

    assert anchor.act_repertoire() == "REP"
    assert anchor.request_act("cue") is True
    assert shell.calls == ["cue"]
