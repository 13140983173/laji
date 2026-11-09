"""读别家 run 的未决审批：桌宠自己的 run 有事件流，Laji 窗口里跑的没有。

``RunSummary``（``ListRuns`` / ``GetRun`` 的返回）不带任何 pending 审批字段，
能拿到 ``call_id`` 的地方只有那条 run 的事件流。``StreamRun`` 对同一 run 是
broadcast 多订阅 + 历史回放（``crates/laji-host/src/services/session.rs:296``），
所以只读订阅一次就能补到「现在卡在哪一步」，也不会惊动 Laji 窗口里那条流。
"""

from __future__ import annotations

from dataclasses import dataclass

# `RunStatus.RUN_STATUS_AWAITING_APPROVAL`（proto/laji/agent/v1/event.proto）。
AWAITING_APPROVAL = 3
# 一次探测最多读这么多事件（回放上限，不是超时就停）。
# 2026-11-05 实测：12k 事件的长会话里 ``approval_requested`` 出现在第 5378 个、
# ``questions_proposed`` 在第 5744 个——原来写 4000，探针读到上限就返回 None，
# 卡片退化成「这条还没探到详情」。整条流回放 12k 条只要 ~0.5s，放宽到 6 万；
# 真正的兜底是 ``fetch_pending`` 的 budget_s 时间预算。
MAX_EVENTS = 60000


@dataclass(frozen=True)
class PendingApproval:
    """一条卡在等人点头的工具调用（或一道等人回答的选择题）。"""

    run_id: str
    call_id: str
    tool_name: str = ""
    reason: str = ""
    timeout_secs: int = 0
    # 选择题（``builtin:ask_questions`` / daemon 主动发问，事件 ``questions_proposed``）：
    # question 非空即是一道题；options 是 (id, label) 对，label 才是回传给引擎的答案
    # （主窗 QuestionsCard 的 onDecideOption 传的就是 label）。多步向导（steps>1）：
    # pet 只读不答——一次 ApproveTool 要交齐所有步的答案，这里给不齐，别给半个。
    question: str = ""
    options: tuple[tuple[str, str], ...] = ()
    allow_custom: bool = False

    @property
    def is_question(self) -> bool:
        return bool(self.question)

    @property
    def answerable(self) -> bool:
        """pet 上能不能直接作答：单步且带选项的题才行，其余指路去会话里。"""
        return bool(self.options)


class PendingApprovalReader:
    """按事件顺序跟踪「还有哪些工具调用没被拍板」。

    未决不是队列：并行的工具调用可以同时挂两条，而气泡一次只问一条，所以对外
    只给**最后**请求的那条——先答最新的，答完下一条自然露出来。
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._open: dict[str, PendingApproval] = {}
        self._awaiting = False

    @property
    def pending(self) -> PendingApproval | None:
        if not self._awaiting or not self._open:
            return None
        return next(reversed(self._open.values()))

    def feed(self, event) -> None:
        kind = event.WhichOneof("payload") or ""
        if kind == "approval_requested":
            asked = event.approval_requested
            if asked.call_id:
                self._open[asked.call_id] = PendingApproval(
                    run_id=self.run_id,
                    call_id=asked.call_id,
                    tool_name=asked.tool_name,
                    reason=asked.reason,
                    timeout_secs=int(asked.timeout_secs or 0),
                )
            self._awaiting = True
        elif kind == "questions_proposed":
            asked = event.questions_proposed
            if asked.call_id:
                self._open[asked.call_id] = self._question_from(asked)
            self._awaiting = True
        elif kind == "questions_resolved":
            self._open.pop(event.questions_resolved.call_id, None)
        elif kind == "tool_started":
            # 放行之后引擎才开始跑：同一个 call_id 的审批不再「未决」。
            self._open.pop(event.tool_started.call_id, None)
        elif kind == "tool_finished":
            self._open.pop(event.tool_finished.call_id, None)
        elif kind == "status_changed":
            status = int(event.status_changed.status)
            self._awaiting = status == AWAITING_APPROVAL
            if not self._awaiting:
                self._open.clear()

    def _question_from(self, asked) -> "PendingApproval":
        """QuestionsProposed → PendingApproval；steps 非空时优先（proto 口径）。

        多步向导只取题面不做选项（``answerable``=False）：pet 一次只能交一个
        字符串，替用户答半张向导表不如让他在会话里答完整。
        """
        base = dict(run_id=self.run_id, call_id=asked.call_id)
        steps = tuple(asked.steps) if asked.steps else ()
        if len(steps) > 1:
            return PendingApproval(question=steps[0].prompt or asked.prompt, **base)
        if len(steps) == 1:
            step = steps[0]
            return PendingApproval(
                question=step.prompt,
                options=tuple((o.id, o.label) for o in step.options),
                allow_custom=bool(step.allow_custom),
                **base,
            )
        return PendingApproval(
            question=asked.prompt,
            options=tuple((o.id, o.label) for o in asked.options),
            allow_custom=bool(asked.allow_custom),
            **base,
        )


def pending_from_events(run_id: str, events) -> PendingApproval | None:
    """一批事件里的未决审批（给单测和一次性回放用）。"""
    reader = PendingApprovalReader(run_id)
    for event in events:
        reader.feed(event)
    return reader.pending


def fetch_pending(client, run_id: str, budget_s: float = 8.0) -> PendingApproval | None:
    """只读订阅那条 run，读到未决审批就断开。

    run 此刻停在 AWAITING_APPROVAL，那条 ``approval_requested`` 一定已经在历史
    里，所以命中即断，不会真的等 live。读不到（旧 daemon / 事件被裁 / 连不上）
    就返回 None——上层退化成「只提醒」。
    """
    if not run_id:
        return None
    reader = PendingApprovalReader(run_id)
    stream = client.stream(run_id, timeout=budget_s)
    try:
        for _ in range(MAX_EVENTS):
            try:
                event = next(stream)
            except StopIteration:
                break
            reader.feed(event)
            if reader.pending is not None:
                return reader.pending
    except Exception:  # noqa: BLE001 - 探测失败只降级，不打扰主流程
        return None
    finally:
        cancel = getattr(stream, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:  # noqa: BLE001
                pass
    return None
