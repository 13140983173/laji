"""把 laji daemon 包装成与 `pet.chat.service.ChatService` 同接口的服务。

这样做的好处：`quick_chat` 里只需挑一个 service，不用改它的流式渲染、分页、
历史归档任何逻辑——引擎可用时走引擎，不可用时原样退回 provider。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PySide6.QtCore import QObject, Signal

from . import daemon_client
from .pet_space import pet_workspace_root, same_workspace
from ..acts import ActCue, DirectiveStream

log = logging.getLogger(__name__)

_ACTIVITY_TOOL = "tool"
# 与 quick_chat._activity 的约定同名：hint 显示「深度思考中…」，不是回答正文。
_ACTIVITY_REASONING = "reasoning"
# proto DeltaKind.DELTA_KIND_REASONING：模型推理流，桌面端折叠在 Think 块里、不进回答。
_DELTA_KIND_REASONING = 1


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages or []):
        if str(message.get("role", "")) == "user":
            return str(message.get("content", "") or "").strip()
    return ""


class LajiRunService(QObject):
    """信号与 ChatService 同名同签名，`quick_chat` 可以直接换过来。"""

    started = Signal(str)
    delta = Signal(str, str)
    finished = Signal(str, str)
    error = Signal(str, str)
    stopped = Signal(str)
    activity = Signal(str, str, str)
    # rid, call_id, tool_name, reason, timeout_secs
    approval = Signal(str, str, str, str, int)
    # rid, 任务标题（= 用户原话前 40 字，用于气泡上那行小字）
    task = Signal(str, str)
    # (rid, ActCue)：模型在正文里点的演出，已剥离出正文（pet/acts/directives）。
    # 与 ChatService.act 同签名——quick_chat 两条路径接同一个回调。
    act = Signal(str, object)

    def __init__(
        self, parent=None, workspace_root: str = "", character: str = "", providers=None
    ) -> None:
        super().__init__(parent)
        # 桌宠不去挤用户当前的代码工作区：固定落在自己的 Pet/<角色> 目录（见 pet_space）。
        self._workspace_root = workspace_root or pet_workspace_root(character)
        self._character = character
        # 桌宠自己的模型清单（callable → list[ProviderConfig]）。用它把 profile 镜像进
        # config.toml；这是与 agent 模型完全分开的一份数据。
        self._providers = providers
        self._provider_id = ""
        self._api_key = ""
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()
        self._rid = ""
        self._run_id = ""
        self._text: list[str] = []
        self._act_stream: DirectiveStream | None = None
        self._user_text = ""
        # (workspace, run_id)：进程内记住上一轮，下一次气泡直接接上去。
        self._last_ctx: tuple[str, str] = ("", "")

    # -- 能力探测 -----------------------------------------------------------
    @staticmethod
    def probe(timeout: float = 1.5) -> tuple[bool, str]:
        if not daemon_client.AVAILABLE:
            return False, daemon_client.unavailable_reason()
        client = daemon_client.LajiDaemonClient(timeout=timeout)
        try:
            return (True, "") if client.connect() else (False, "连不上 Laji 引擎（daemon 没在跑）")
        finally:
            client.close()

    @property
    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def run_id(self) -> str:
        return self._run_id

    # -- 发送 ---------------------------------------------------------------
    def send(self, messages: list[dict[str, Any]], config=None, request_id: str | None = None) -> str:
        self._rid = request_id or "laji-run"
        self._cancel.clear()
        self._text = []
        self._act_stream = DirectiveStream()
        self._run_id = ""
        prompt = _last_user_text(messages)
        # 用户原话：director 用它判定“这是用户点名要看的，不是模型自选”
        self._user_text = prompt
        # 本轮用哪个桌宠模型：worker 线程里凭它点名 profile（config 就是 active_config）。
        self._provider_id = str(getattr(config, "provider_id", "") or "")
        self._api_key = str(getattr(config, "api_key", "") or "")
        if not prompt:
            self.error.emit(self._rid, "没听到要做什么")
            return self._rid
        self._thread = threading.Thread(
            target=self._worker, args=(self._rid, prompt), name="laji-run", daemon=True
        )
        self._thread.start()
        return self._rid

    def stop(self) -> None:
        self._cancel.set()
        run_id = self._run_id
        rid = self._rid
        if not run_id:
            return

        def _cancel() -> None:
            client = daemon_client.LajiDaemonClient()
            try:
                if client.connect():
                    client.cancel_run(run_id)
            except Exception:
                pass
            finally:
                client.close()

        threading.Thread(target=_cancel, name="laji-cancel", daemon=True).start()
        self.stopped.emit(rid)

    def approve(self, run_id: str, call_id: str, approved: bool) -> None:
        def _approve() -> None:
            client = daemon_client.LajiDaemonClient()
            try:
                if client.connect():
                    client.approve(run_id, call_id, approved)
            except Exception:
                pass
            finally:
                client.close()

        threading.Thread(target=_approve, name="laji-approve", daemon=True).start()

    # -- 后台 ---------------------------------------------------------------
    def _resolve_context(self, client) -> tuple[str, str]:
        """会话固定落在桌宠自己的工作区，并接上它最近的一轮。

        会话归属是客户端按 parent_run_id 链算出来的（`sessionRootForRun`）：空 parent
        起的 run 在 Laji Agent 侧栏里是一条谁也看不到的孤岛，用户会以为「两边没同步」。
        顺带这也给桌宠补上了多轮上下文——上一次说的话会作为本次前缀。

        注意不能直接拿 `list_runs` 的第一条当 parent：那可能是用户在项目里刚跑的
        会话，一旦拿它当 parent，桌宠的话就被接进那个工作区的会话里了。
        """
        workspace = self._workspace_root or pet_workspace_root(
            getattr(self, "_character", ""))
        # 自己刚发的那轮一定同 workspace，比列表可靠：每次发送都多一次列表往返，
        # 而且那个列表会因别的项目（或长时间没用桌宠）把 Pet 的会话挤出窗口。
        last_ws, last_run = getattr(self, "_last_ctx", ("", ""))
        if last_run and same_workspace(last_ws, workspace):
            return workspace, last_run
        parent = ""
        try:
            for run in client.list_runs(limit=1, by_session=True):
                if same_workspace(run.workspace_root, workspace) and run.run_id:
                    parent = run.run_id
                    break
        except Exception:
            pass  # 读不到最近一轮就退化成新建会话，不能让发送失败
        return workspace, parent

    def _ensure_profile(self, client) -> str:
        """把桌宠这一轮的模型弄成引擎认得的一个 profile，返回它的名字。

        三步都不碰 ``[model.routing.*]``：只写自己的 managed block、把 key 推进 daemon
        内存、必要时重读一遍。profile 已存在且内容没变时这两步都不发 RPC。
        """
        provider_id = getattr(self, "_provider_id", "")
        if not provider_id:
            return ""
        try:
            from ..chat import engine_profiles

            providers = []
            if callable(self._providers):
                try:
                    providers = list(self._providers() or [])
                except Exception:
                    providers = []
            providers = [p for p in providers if str(getattr(p, "model", "") or "").strip()]
            if not providers:
                return ""
            if engine_profiles.sync_profiles(providers):
                client.reload_local_config()
            name = engine_profiles.profile_name(provider_id)
            api_key = str(getattr(self, "_api_key", "") or "")
            if api_key:
                client.set_model_key(name, api_key)
            return name
        except Exception:
            log.debug("桌宠模型镜像失败，退回引擎默认路由", exc_info=True)
            return ""

    def _worker(self, rid: str, prompt: str) -> None:
        client = daemon_client.LajiDaemonClient()
        if not client.connect():
            self.error.emit(rid, "连不上 Laji 引擎：daemon 没在跑")
            return
        try:
            profile = self._ensure_profile(client)
            workspace, parent = self._resolve_context(client)
            run_id = client.create_run(prompt, workspace, parent, model_profile=profile)
            self._run_id = run_id
            self._last_ctx = (workspace, run_id)
            self.task.emit(rid, prompt[:40])
            self.started.emit(rid)
            for event in client.stream(run_id):
                if self._cancel.is_set():
                    return
                self._handle_event(rid, event)
        except Exception as exc:
            if not self._cancel.is_set():
                self.error.emit(rid, f"{type(exc).__name__}: {exc}")
        finally:
            client.close()

    def _handle_event(self, rid: str, event) -> None:
        kind = event.WhichOneof("payload") or ""
        if kind == "assistant_delta":
            delta = event.assistant_delta
            if delta.kind == _DELTA_KIND_REASONING:
                # 思考流只驱动 hint：拼进正文会让气泡和落库历史里出现模型的英文自言自语。
                self.activity.emit(rid, _ACTIVITY_REASONING, "")
                return
            piece = delta.text_delta
            if not piece:
                return
            self._text.append(piece)
            stream = self._act_stream
            shown = stream.feed(piece) if stream is not None else piece
            # 整个 delta 都被标记吃掉时没有可见正文，不必发一次空增量
            if shown:
                self.delta.emit(rid, shown)
        elif kind == "tool_started":
            self.activity.emit(rid, _ACTIVITY_TOOL, event.tool_started.tool_name)
        elif kind == "approval_requested":
            asked = event.approval_requested
            self.activity.emit(rid, _ACTIVITY_TOOL, asked.tool_name)
            self.approval.emit(
                rid, asked.call_id, asked.tool_name, asked.reason, int(asked.timeout_secs)
            )
        elif kind == "status_changed":
            status = event.status_changed.status
            if status == 4:
                text, cue = self._settle_act("".join(self._text))
                if cue is not None:
                    self.act.emit(rid, cue)
                self.finished.emit(rid, text)
            elif status == 5:
                self.error.emit(rid, "任务失败了")
            elif status == 6:
                self.stopped.emit(rid)
        elif kind == "error":
            self.error.emit(rid, event.error.message or event.error.code)

    def _settle_act(self, text: str) -> tuple[str, ActCue | None]:
        """收尾：返回（不含标记的正文, 演出席位 | None）。

        与 ``chat/service.ChatService._settle_act`` 同一口径：落盘与展示都用不含
        标记的正文，会话历史里留着 ``[[act:…]]`` 会让模型下一轮照着吐。
        """
        stream = self._act_stream
        self._act_stream = None
        if stream is None:
            return text, None
        try:
            queries, clean = stream.finish(text)
        except Exception:  # noqa: BLE001 - 剥离失败退回原文，不能吞掉整条回复
            return text, None
        if not queries:
            return (clean if clean.strip() else text), None
        if not clean.strip():
            return text, None
        return clean, ActCue(queries=queries, reply_chars=len(clean),
                            user_text=getattr(self, "_user_text", "") or "")
