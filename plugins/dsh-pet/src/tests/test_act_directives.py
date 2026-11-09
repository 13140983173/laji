# -*- coding: utf-8 -*-
"""演出标记的语法与流式剥离（``pet/acts/directives.py``）。

这一层的失败模式全都是"用户看见了不该看见的东西"，所以断言集中在两件事：
1. 标记永远不会出现在可见文本里（**包括被切在两个 delta 之间的**）；
2. 不写标记时，输出与输入逐字节一致（关掉功能的路径必须零影响）。
"""
from __future__ import annotations

from pet.acts.directives import (
    DirectiveStream,
    holdback_length,
    parse_markers,
    strip_markers,
    tidy_reply,
)


# ---------------------------------------------------------------- 语素
def test_parse_extracts_names_in_order_without_duplicates():
    text = '好呀[[act:写代码]]，那我先改一版[[act:想想]]，再来一遍[[act:写代码]]'
    assert parse_markers(text) == ('写代码', '想想')


def test_parse_accepts_fullwidth_colon_spaces_and_case():
    assert parse_markers('嗯[[ACT： 吃Token ]]') == ('吃Token',)
    assert parse_markers('嗯[[ act : 跳舞 ]]') == ('跳舞',)


def test_parse_ignores_empty_and_unterminated_markers():
    assert parse_markers('[[act:]]') == ()
    assert parse_markers('[[act:写代码]') == ()


def test_strip_removes_only_markers():
    assert strip_markers('她说[[act:害羞]]好。') == '她说好。'
    assert strip_markers('没有标记的正文') == '没有标记的正文'


def test_holdback_length_detects_marker_prefixes():
    assert holdback_length('正文') == 0
    assert holdback_length('正文[') == 1
    assert holdback_length('正文[[') == 2
    assert holdback_length('正文[[ac') == 4
    assert holdback_length('正文[[act') == 5
    assert holdback_length('正文[[act:') == 6
    # 已经完整闭合的标记不是前缀：它会被 MARKER_RE 抽走，不参与扣留
    assert holdback_length('正文]') == 0
    assert holdback_length('正文[哈]') == 0


def test_holdback_keeps_unclosed_marker_body_out_of_view():
    # 尾巴是「害羞」而不是标记前缀：只靠前缀判定会被漏出去
    assert holdback_length('她说[[act:害羞') == len('[[act:害羞')
    assert holdback_length('甲[[act：开心跃动') == len('[[act：开心跃动')


def test_holdback_releases_unclosed_opener_too_long_to_be_a_marker():
    # 标记名上限 32 字，超出就当普通正文，不会把整条回复吞掉
    assert holdback_length('[[act:' + '很' * 60) == 0


def test_tidy_reply_collapses_blank_lines_left_by_markers():
    text = '好呀\n\n[[act:写代码]]\n\n\n还是好呀'
    assert tidy_reply(strip_markers(text)) == '好呀\n\n还是好呀'


# ---------------------------------------------------------------- 流式
def _feed_all(chunks):
    stream = DirectiveStream()
    parts = [stream.feed(chunk) for chunk in chunks]
    return stream, parts


def test_stream_never_leaks_marker_split_across_deltas():
    stream, parts = _feed_all(['她说', '[[ac', 't:害羞]]', '好。'])
    assert ''.join(parts) == '她说好。'
    queries, text = stream.finish()
    assert queries == ('害羞',)
    assert text == '她说好。'


def test_stream_keeps_unclosed_marker_hidden_until_closed():
    stream, parts = _feed_all(['她说[[act:害羞', ']]好。'])
    assert ''.join(parts) == '她说好。'
    assert stream.finish() == (('害羞',), '她说好。')


def test_stream_holds_bare_bracket_until_next_delta():
    stream, parts = _feed_all(['看这个[', '1]结论'])
    # 第一个 delta 末尾的 '[' 可能是标记开头，先扣住；下一拍证明是普通文本
    assert parts[0] == '看这个'
    assert ''.join(parts) == '看这个[1]结论'
    queries, text = stream.finish()
    assert queries == ()
    assert text == '看这个[1]结论'


def test_stream_without_markers_is_byte_identical():
    text = '正常一句话，带（括号动作）和 f(x) 这种函数。'
    stream, parts = _feed_all(list(text))
    _, final = stream.finish()
    assert ''.join(parts) == text
    assert final == text


def test_stream_finish_flushes_held_tail_as_plain_text():
    stream, parts = _feed_all(['看到一半', '[[act'])
    assert ''.join(parts) == '看到一半'
    queries, text = stream.finish()
    assert queries == ()
    assert text == '看到一半[[act'


def test_stream_finish_uses_full_text_when_provider_sends_no_delta():
    stream = DirectiveStream()
    queries, text = stream.finish('直接给全文[[act:吃零食]]')
    assert queries == ('吃零食',)
    assert text == '直接给全文'


def test_stream_finish_tops_up_full_text_suffix():
    stream, _ = _feed_all(['前半句'])
    queries, text = stream.finish('前半句后半句[[act:想想]]')
    assert queries == ('想想',)
    assert text == '前半句后半句'


def test_stream_finish_ignores_full_text_that_does_not_extend_what_was_shown():
    stream, _ = _feed_all(['用户已经看到的版本'])
    queries, text = stream.finish('完全不同的另一份[[act:想想]]')
    assert queries == ()
    assert text == '用户已经看到的版本'


def test_stream_queries_accumulate_across_deltas_and_reset_after_finish():
    stream, _ = _feed_all(['甲[[act:写代码]]', '乙[[act:想想]]'])
    assert stream.finish() == (('写代码', '想想'), '甲乙')
    # 复用同一个 stream 的第二条回复：上一条的候选不许残留
    stream.feed('丙')
    assert stream.finish() == ((), '丙')


def test_marker_only_reply_yields_empty_text_but_keeps_query():
    stream = DirectiveStream()
    queries, text = stream.finish('[[act:开心跃动]]')
    assert queries == ('开心跃动',)
    assert text == ''
