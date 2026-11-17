# -*- coding: utf-8 -*-
"""聊天流 → 演出请求的接线（``pet/chat/service.py``）。

这一层是唯一会碰到用户可见文本的地方，所以断言分两组：
- 标记必须从**增量与收尾全文**里彻底消失（含被切在两个 delta 之间的情况）；
- 只有真带着标记的回复才会发出 ``act``，否则一个信号都不该发（零影响）。
"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pet.acts import DirectiveStream
from pet.chat.service import ChatService


def _qapp():
    return QApplication.instance() or QApplication([])


def _service():
    _qapp()
    service = ChatService()
    service._request_id = 'rid'
    service._act_stream = DirectiveStream()
    events = {'delta': [], 'act': [], 'finished': []}
    service.delta.connect(lambda rid, text: events['delta'].append((rid, text)))
    service.act.connect(lambda rid, cue: events['act'].append((rid, cue)))
    service.finished.connect(lambda rid, text: events['finished'].append((rid, text)))
    return service, events


def test_marker_is_stripped_from_deltas_and_reported_as_a_cue():
    service, events = _service()
    for chunk in ('她想了想', '，[[ac', 't:害羞]]', '说自己也没把握。'):
        service._delta('rid', chunk)
    service._finished('rid', '')
    assert ''.join(text for _, text in events['delta']) == '她想了想，说自己也没把握。'
    assert events['finished'] == [('rid', '她想了想，说自己也没把握。')]
    [(rid, cue)] = events['act']
    assert rid == 'rid'
    assert cue.queries == ('害羞',)
    assert cue.reply_chars == len('她想了想，说自己也没把握。')


def test_reply_without_markers_emits_no_cue_and_stays_byte_identical():
    service, events = _service()
    text = '正常的一句话，带（括号动作）和 f(x)。'
    service._delta('rid', text)
    service._finished('rid', '')
    assert events['delta'] == [('rid', text)]
    assert events['finished'] == [('rid', text)]
    assert events['act'] == []


def test_provider_without_deltas_still_gets_markers_stripped():
    service, events = _service()
    service._finished('rid', '直接给全文[[act:吃零食]]')
    assert events['delta'] == []
    assert events['finished'] == [('rid', '直接给全文')]
    [(_, cue)] = events['act']
    assert cue.queries == ('吃零食',)


def test_marker_only_reply_keeps_raw_text_and_drops_the_cue():
    service, events = _service()
    service._finished('rid', '[[act:想想]]')
    # 模型只写了一个标记：保留原文，至少让用户看到它到底写了什么
    assert events['finished'] == [('rid', '[[act:想想]]')]
    assert events['act'] == []


def test_events_from_another_request_are_dropped():
    service, events = _service()
    service._delta('other', '[[act:害羞]]正文')
    service._finished('other', '')
    assert events['delta'] == []
    assert events['finished'] == []
    assert events['act'] == []
