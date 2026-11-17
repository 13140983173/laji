# -*- coding: utf-8 -*-
"""pending_approval：从别家 run 的事件里读出「现在卡在哪一步」（纯函数区）。"""

from types import SimpleNamespace

from pet.agent_link.pending_approval import (
    MAX_EVENTS,
    PendingApprovalReader,
    fetch_pending,
    pending_from_events,
)


class _Event:
    """只实现被测代码用到的那部分：WhichOneof + 唯一那个 payload。"""

    def __init__(self, kind, **fields):
        self._kind = kind
        setattr(self, kind, SimpleNamespace(**fields))

    def WhichOneof(self, _name):
        return self._kind


def _asked(call_id="call-1", tool="builtin:run_terminal", reason="shell", timeout=30):
    return _Event(
        "approval_requested",
        call_id=call_id,
        tool_name=tool,
        reason=reason,
        timeout_secs=timeout,
    )


def _status(value):
    return _Event("status_changed", status=value)


def _started(call_id="call-1"):
    return _Event("tool_started", call_id=call_id)


def _finished(call_id="call-1"):
    return _Event("tool_finished", call_id=call_id)


def test_approval_request_is_pending_with_its_tool_and_reason():
    pending = pending_from_events("run-1", [_status(2), _asked()])

    assert pending is not None
    assert (pending.run_id, pending.call_id) == ("run-1", "call-1")
    assert pending.tool_name == "builtin:run_terminal"
    assert pending.reason == "shell"
    assert pending.timeout_secs == 30


def test_approved_and_running_is_no_longer_pending():
    """放行后 run 回到 executing：那条 call_id 不再是「未决」。"""
    assert pending_from_events("run-1", [_asked(), _status(2)]) is None


def test_tool_start_and_finish_clear_the_same_call_id():
    assert pending_from_events("run-1", [_asked(), _started()]) is None
    assert pending_from_events("run-1", [_asked(), _finished()]) is None


def test_other_call_ids_do_not_clear_it():
    assert pending_from_events("run-1", [_asked("call-1"), _finished("call-2")]) is not None


def test_latest_request_wins_when_calls_queue_up():
    """并行工具可以挂着两条；气泡一次只问一条，先问最新的那条。"""
    pending = pending_from_events(
        "run-1", [_asked("call-1", tool="apply_patch"), _asked("call-2", tool="builtin:run_terminal")]
    )

    assert pending is not None and pending.call_id == "call-2"


def test_unrelated_events_and_empty_stream_are_quiet():
    assert pending_from_events("run-1", []) is None
    assert pending_from_events(
        "run-1", [_status(2), _Event("assistant_delta", text_delta="hi")]
    ) is None


def test_reader_is_incremental_so_a_live_stream_can_stop_early():
    reader = PendingApprovalReader("run-1")
    reader.feed(_status(2))
    assert reader.pending is None

    reader.feed(_asked())
    assert reader.pending is not None

    reader.feed(_status(2))
    assert reader.pending is None


def _question(call_id="call-q", prompt="你在哪个城市？", options=(("a", "北京"), ("b", "上海")), steps=()):
    return _Event(
        "questions_proposed",
        call_id=call_id,
        prompt=prompt,
        options=[SimpleNamespace(id=i, label=l) for i, l in options],
        allow_custom=True,
        custom_option_id="other",
        steps=steps,
    )


def _resolved(call_id="call-q"):
    return _Event("questions_resolved", call_id=call_id, skipped=False, answer="北京")


def test_question_proposed_is_pending_and_answerable():
    pending = pending_from_events("run-1", [_status(2), _question()])

    assert pending is not None
    assert pending.is_question
    assert pending.call_id == "call-q"
    assert pending.question == "你在哪个城市？"
    assert pending.answerable
    assert pending.options == (("a", "北京"), ("b", "上海"))


def test_question_resolved_clears_it():
    assert pending_from_events("run-1", [_question(), _resolved()]) is None


def test_multi_step_wizard_is_visible_but_not_answerable_here():
    """一次 ApproveTool 要交齐所有步的答案：pet 给不全，就不该给半张表。"""
    steps = [
        SimpleNamespace(
            prompt=f"第{i}步", options=[SimpleNamespace(id="a", label="甲")], allow_custom=False,
            custom_option_id="",
        )
        for i in (1, 2)
    ]
    pending = pending_from_events("run-1", [_question(steps=steps)])

    assert pending is not None and pending.is_question
    assert pending.question == "第1步"
    assert not pending.answerable


def test_single_step_wizard_uses_the_step_not_the_legacy_prompt():
    steps = [
        SimpleNamespace(
            prompt="步骤题面", options=[SimpleNamespace(id="a", label="甲")],
            allow_custom=False, custom_option_id="",
        )
    ]
    pending = pending_from_events("run-1", [_question(prompt="旧字段", steps=steps)])

    assert pending.question == "步骤题面"
    assert pending.options == (("a", "甲"),)


def _question(call_id="call-q", prompt="你在哪个城市？", options=(("a", "北京"), ("b", "上海")), steps=()):
    return _Event(
        "questions_proposed",
        call_id=call_id,
        prompt=prompt,
        options=[SimpleNamespace(id=i, label=l) for i, l in options],
        allow_custom=True,
        custom_option_id="other",
        steps=steps,
    )


def _resolved(call_id="call-q"):
    return _Event("questions_resolved", call_id=call_id, skipped=False, answer="北京")


def test_question_proposed_is_pending_and_answerable():
    pending = pending_from_events("run-1", [_status(2), _question()])

    assert pending is not None
    assert pending.is_question
    assert pending.call_id == "call-q"
    assert pending.question == "你在哪个城市？"
    assert pending.answerable
    assert pending.options == (("a", "北京"), ("b", "上海"))


def test_question_resolved_clears_it():
    assert pending_from_events("run-1", [_question(), _resolved()]) is None


def test_multi_step_wizard_is_visible_but_not_answerable_here():
    """一次 ApproveTool 要交齐所有步的答案：pet 给不全，就不该给半张表。"""
    steps = [
        SimpleNamespace(
            prompt=f"第{i}步", options=[SimpleNamespace(id="a", label="甲")], allow_custom=False,
            custom_option_id="",
        )
        for i in (1, 2)
    ]
    pending = pending_from_events("run-1", [_question(steps=steps)])

    assert pending is not None and pending.is_question
    assert pending.question == "第1步"
    assert not pending.answerable


def test_single_step_wizard_uses_the_step_not_the_legacy_prompt():
    steps = [
        SimpleNamespace(
            prompt="步骤题面", options=[SimpleNamespace(id="a", label="甲")],
            allow_custom=False, custom_option_id="",
        )
    ]
    pending = pending_from_events("run-1", [_question(prompt="旧字段", steps=steps)])

    assert pending.question == "步骤题面"
    assert pending.options == (("a", "甲"),)



def test_request_past_four_thousand_events_is_still_reached():
    """回归（2026-11-05 实机）：12k 事件的长会话里审批请求在第 5378 个。

    回放上限写在 4000 时 fetch_pending 读到上限就返回 None，卡片降级成
    「这条还没探到详情」——会话越长越探不到。
    """
    events = (
        [_status(2)]
        + [_Event("assistant_delta", text_delta="x") for _ in range(5380)]
        + [_asked()]
    )

    class _Client:
        def stream(self, _run_id, timeout=0.0):
            return iter(events)

    assert len(events) < MAX_EVENTS, "上限要能盖住这么长的会话"
    pending = fetch_pending(_Client(), "run-1")

    assert pending is not None and pending.call_id == "call-1"
