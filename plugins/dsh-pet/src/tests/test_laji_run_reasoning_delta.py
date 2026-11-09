"""引擎通路的 delta 分流：思考流不得进气泡正文。

``AssistantDelta`` 带 ``kind``（``proto/laji/agent/v1/event.proto``）：TEXT 是回答正文，
REASONING 是模型的思考过程。桌面端把后者折叠在 Think 块里、永不进回答，桌宠气泡必须
一样——否则用户看到的「回答」全是模型的自言自语（英文草稿），人设再对也没用。
"""

from types import SimpleNamespace

from pet.agent_link.laji_run_service import LajiRunService

_TEXT = 0
_REASONING = 1


def _delta(text: str, kind: int):
    return SimpleNamespace(
        WhichOneof=lambda name: "assistant_delta",
        assistant_delta=SimpleNamespace(text_delta=text, kind=kind),
    )


def _finished_status():
    return SimpleNamespace(
        WhichOneof=lambda name: "status_changed",
        status_changed=SimpleNamespace(status=4),
    )


def _service():
    service = LajiRunService(workspace_root="")
    seen = {"body": [], "activity": [], "finished": []}
    service.delta.connect(lambda rid, text: seen["body"].append(text))
    service.activity.connect(lambda rid, kind, text: seen["activity"].append(kind))
    service.finished.connect(lambda rid, text: seen["finished"].append(text))
    return service, seen


def test_reasoning_delta_only_drives_the_hint():
    service, seen = _service()

    service._handle_event("r1", _delta("The user asks about today's weather. ", _REASONING))

    assert seen["body"] == []
    assert seen["activity"] == ["reasoning"]


def test_reasoning_delta_is_not_archived_with_the_answer():
    service, seen = _service()

    service._handle_event("r1", _delta("The user asks 1+1. ", _REASONING))
    service._handle_event("r1", _delta("等于 2 呀", _TEXT))
    service._handle_event("r1", _finished_status())

    assert seen["body"] == ["等于 2 呀"]
    assert seen["finished"] == ["等于 2 呀"]


def test_text_delta_still_streams_without_a_reasoning_phase():
    service, seen = _service()

    service._handle_event("r1", _delta("好的", _TEXT))

    assert seen["body"] == ["好的"]
    assert seen["activity"] == []
