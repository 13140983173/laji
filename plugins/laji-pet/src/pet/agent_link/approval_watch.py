"""Laji 那边的 run 卡在「等你拍板」时，桌宠叫一声。

桌宠自己发起的 run 有事件流，审批会直接弹到气泡里；但在 Laji Agent 窗口里跑的
任务没有这条流。用户要的「两边同步」里最小的一条就是——那边卡住等你点「同意」，
人却在看别的地方干等。这里只做只读轮询，不碰别人的 run。

光知道「有 run 卡住」还不够：要给出能点的【允许/拒绝】就得有 ``call_id``，而它
只活在事件流里（见 ``pending_approval``）。所以每条新卡住的 run 会只读订阅一次，
补出未决审批；探不到就退化成「只提醒」。
"""

from __future__ import annotations

import logging
import threading

from PySide6.QtCore import QMetaObject, QObject, Qt, QTimer, Signal, Slot

from . import daemon_client, pending_approval
from ..tool_names import approval_text

# `RunStatus.RUN_STATUS_AWAITING_APPROVAL`（proto/laji/agent/v1/event.proto）。
AWAITING_APPROVAL = pending_approval.AWAITING_APPROVAL
POLL_INTERVAL_MS = 7000
# 一轮最多给几条新卡住的 run 探测未决审批：每条要开一次只读流，别把轮询拖长。
MAX_PROBES_PER_SCAN = 3


def awaiting(runs) -> list:
    """筛出正在等用户拍板的 run（保持 daemon 给的顺序）。"""
    picked = []
    for run in runs:
        try:
            status = int(getattr(run, "status", 0))
        except (TypeError, ValueError):
            continue
        if status == AWAITING_APPROVAL and getattr(run, "run_id", ""):
            picked.append(run)
    return picked


def describe(run) -> str:
    """一句话说清是哪条会话在等：气泡空间只够一个短标题。"""
    prompt = (getattr(run, "user_prompt", "") or "").strip()
    head = prompt.splitlines()[0].strip() if prompt else ""
    if len(head) > 18:
        head = head[:18].rstrip() + "…"
    return f"Laji 那边有个操作等你拍板：{head}" if head else "Laji 那边有个操作等你拍板"


def describe_approval(approval) -> str:
    """探到了未决审批：说清是哪个工具在等，别只说「有个操作」。

    工具名走 ``approval_text``：引擎的原始 id（``mcp:pet-hands:look``）不进正文，
    口径跟主窗口一致。选择题（``questions_proposed``）不是工具，把题面亮出来。
    """
    if getattr(approval, "is_question", False):
        head = (getattr(approval, "question", "") or "").strip().splitlines()
        head = head[0].strip() if head else ""
        if len(head) > 18:
            head = head[:18].rstrip() + "…"
        return f"Laji 那边问你：{head}" if head else "Laji 那边有一道选择题等你答"
    head = approval_text(approval.tool_name, empty="有一步要你点头")
    return f"Laji 那边等你拍板：{head}"


class ApprovalWatcher(QObject):
    """定时扫一遍 daemon 的 run 列表，新出现的「等拍板」才提醒。

    `attention` 携带 (run_id, workspace_root, 文案, 未决审批)：带 workspace 是为了
    点开时能直接落到那条会话所在的工作区——它可能根本不是桌宠自己的 `Pet` 目录；
    未决审批为 None 时只能提醒，带了就能在气泡里给【允许/拒绝】。
    """

    attention = Signal(str, str, str, object)
    # 那条 run 不再等拍板（那边自己批了/取消了）：把挂着的审批卡撤掉。
    gone = Signal(str)

    def __init__(
        self, parent=None, interval_ms: int = POLL_INTERVAL_MS, probe=None
    ) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.poll)
        # 探测可注入：单测不该真去连 daemon。
        self._probe = probe or pending_approval.fetch_pending
        # None = 还没扫过第一轮（第一轮只登记不报，别一启动就糊用户一脸气泡）。
        self._known: set | None = None
        # run_id -> (updated_at_ms, 未决审批)：同一条 run 有变化才重新探。
        self._probed: dict[str, tuple[int, object]] = {}
        # 上一轮还在等、这轮不等了的 run。
        self._resolved: list[str] = []
        self._busy = False
        self._pending: list = []

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def poll(self) -> None:
        """扫一次（主线程只负责起线程，RPC 不阻塞 GUI）。"""
        if self._busy:
            return
        self._busy = True
        threading.Thread(target=self._scan, name="laji-approval-scan", daemon=True).start()

    def scan_runs(self, runs, pending: dict | None = None) -> None:
        """拿到 run 列表后的判定（主线程直接调；单测也走这里）。

        ``pending`` 是 {run_id: PendingApproval}；没有就给「只提醒」的那一版。
        """
        for run, approval in self._collect(runs, pending or {}):
            self.attention.emit(
                run.run_id,
                getattr(run, "workspace_root", "") or "",
                describe_approval(approval) if approval is not None else describe(run),
                approval,
            )
        for run_id in self._resolved:
            self.gone.emit(run_id)

    def _collect(self, runs, pending: dict) -> list:
        """返回「这一轮才新出现的审批」；启动后第一轮只登记不报。"""
        current = {run.run_id: run for run in awaiting(runs)}
        known_runs = {
            key[0] if isinstance(key, tuple) else key for key in (self._known or set())
        }
        self._resolved = sorted(known_runs - set(current)) if self._known is not None else []
        self._forget(dead=set(current))
        first = self._known is None
        fresh = []
        keys = set()
        for run_id in current:
            approval = pending.get(run_id)
            key = self._key(run_id, approval)
            keys.add(key)
            if not first and key not in self._known:
                fresh.append((current[run_id], approval))
        self._known = keys
        return fresh

    @staticmethod
    def _key(run_id: str, approval) -> object:
        """同一条 run 的下一个审批也算「新」：批完这个还有下一个在等。"""
        return (run_id, approval.call_id) if approval is not None else run_id

    def _forget(self, dead: set[str]) -> None:
        """已经不在等拍板的 run 忘掉：下次再卡住要能重新叫一声。"""
        if self._known is None:
            return
        self._known = {
            key for key in self._known
            if (key[0] if isinstance(key, tuple) else key) in dead
        }
        for run_id in list(self._probed):
            if run_id not in dead:
                self._probed.pop(run_id, None)

    def _probe_pending(self, client, awaiting_runs) -> dict:
        """给每条还没探过的「等拍板」run 探出未决审批（同一条 run 变了才重探）。

        探到 None **不进缓存**：那是「这轮没读到」，不是结论。缓存了就会在
        ``updated_at_ms`` 不变期间一直复用它，一次失败等于永久降级成「只提醒」。
        重探的节奏由 ``MAX_PROBES_PER_SCAN`` 限流，不会把轮询拖长。
        """
        found: dict = {}
        budget = MAX_PROBES_PER_SCAN
        for run in awaiting_runs:
            run_id = run.run_id
            version = int(getattr(run, "updated_at_ms", 0) or 0)
            cached = self._probed.get(run_id)
            if cached is not None and cached[0] == version:
                found[run_id] = cached[1]
                continue
            if budget <= 0:
                continue
            budget -= 1
            try:
                approval = self._probe(client, run_id)
            except Exception:  # noqa: BLE001 - 探测失败只降级
                logging.debug("Laji 审批探测失败：%s", run_id, exc_info=True)
                continue
            if approval is not None:
                self._probed[run_id] = (version, approval)
                found[run_id] = approval
        return found

    @Slot()
    def _flush(self) -> None:
        """后台线程算完的队尾，回到 watcher 所在线程（主线程）再冒泡。"""
        pending, self._pending = self._pending, []
        resolved, self._resolved = self._resolved, []
        for item in pending:
            run, approval = item
            self.attention.emit(
                run.run_id,
                getattr(run, "workspace_root", "") or "",
                describe_approval(approval) if approval is not None else describe(run),
                approval,
            )
        for run_id in resolved:
            self.gone.emit(run_id)

    def _scan(self) -> None:
        try:
            client = daemon_client.LajiDaemonClient()
            if not client.connect():
                return
            try:
                runs = client.list_runs(limit=50)
                found = self._probe_pending(client, awaiting(runs))
            finally:
                client.close()
            first = self._known is None
            self._pending.extend(self._collect(runs, found))
            if first:
                # 一行就够：出问题时先看这里，「亮没亮」不用猜。
                logging.info("Laji 审批提醒就绪：daemon 现有 %d 条会话在等你拍板",
                             len(self._pending))
            # 跨线程直接 emit 会在工作线程里调 Qt 控件（气泡）——排回主线程。
            QMetaObject.invokeMethod(self, "_flush", Qt.ConnectionType.QueuedConnection)
        except Exception:
            logging.debug("Laji 审批提醒扫描失败", exc_info=True)
        finally:
            self._busy = False
