"""桌宠侧直连 laji daemon 的 gRPC 客户端。

桌宠不开 Laji Agent 窗口也能干活，靠的就是这里：连 `laji serve` 引擎，
建 Run、收事件流、回审批。端点与鉴权口径与 `packages/laji-client-core/src/daemon/socket.ts`
保持一致（tcp 端点加 `authorization: Bearer <token>`）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterator

_PROTO_DIR = Path(__file__).resolve().parent / "_proto"
if str(_PROTO_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTO_DIR))

try:  # grpcio 是可选依赖：没打包进来的情况下桌宠照常启动，只是这条能力不可用。
    import grpc

    from laji.agent.v1 import session_pb2, session_pb2_grpc

    AVAILABLE = True
    _IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - 环境缺失路径
    grpc = None
    session_pb2 = None
    session_pb2_grpc = None
    AVAILABLE = False
    _IMPORT_ERROR = f"{type(exc).__name__}: {exc}"


ENDPOINT_NAME = "daemon.endpoint"


def endpoint_candidates() -> list[Path]:
    """按优先级列出可能的端点文件位置。"""
    dirs: list[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    app_data = os.environ.get("APPDATA", "")
    if local_app_data:
        dirs.append(Path(local_app_data) / "laji" / "run")
        dirs.append(Path(local_app_data) / "laji-dev" / "run")
    if app_data:
        dirs.append(Path(app_data) / "Laji Agent" / "run")
    return [d / ENDPOINT_NAME for d in dirs]


def read_endpoint() -> dict | None:
    for path in endpoint_candidates():
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            continue
        if isinstance(data, dict) and data.get("addr"):
            data["_path"] = str(path)
            return data
    return None


def unavailable_reason() -> str:
    if not AVAILABLE:
        return _IMPORT_ERROR or "grpcio not installed"
    if read_endpoint() is None:
        return "daemon endpoint not found"
    return ""


#: `ToolSurface.TOOL_SURFACE_COMPANION`。仓库里的 `_proto` 是旧生成物（枚举只到 4），
#: 而 `proto/laji/agent/v1/session.proto` 已有 COMPANION = 5；proto3 枚举允许直传数字，
#: daemon 侧按 `ToolSurface::from_i32(5)` 解析。pb2 重新生成后可换成枚举常量。
TOOL_SURFACE_COMPANION = 5

#: `ReloadMcpServer` 要真去拉子进程 / 走 OAuth，比普通调用慢得多。
RELOAD_TIMEOUT_SECONDS = 60.0

#: proto 枚举名 → 界面用的小写状态词。
MCP_STATE_KINDS = {
    "MCP_SERVER_STATE_ONLINE": "online",
    "MCP_SERVER_STATE_FAILED": "failed",
    "MCP_SERVER_STATE_DISCONNECTED": "disconnected",
    "MCP_SERVER_STATE_RECONNECTING": "reconnecting",
    "MCP_SERVER_STATE_NEEDS_AUTH": "needs_auth",
}


def _enum_name(message, field: str, value: int) -> str:
    """proto3 枚举数字 → 名字。取不到就回空串，不报错。"""
    try:
        enum = message.DESCRIPTOR.fields_by_name[field].enum_type
        return enum.values_by_number[int(value)].name
    except Exception:
        return ""


def _server_status(one) -> dict:
    state = _enum_name(one, "state", one.state)
    return {
        "name": str(one.name),
        "state": MCP_STATE_KINDS.get(state, "unknown"),
        "error": str(one.error or ""),
        "last_error": str(one.last_error or ""),
        "transport": str(one.transport or ""),
        "url": str(one.url or ""),
        "tool_count": int(one.tool_count),
        "resource_count": int(one.resource_count),
        "prompt_count": int(one.prompt_count),
        "remote_name": str(one.remote_name or ""),
        "remote_version": str(one.remote_version or ""),
        "last_refresh_ms": int(one.last_refresh_ms),
    }


class LajiDaemonClient:
    """一个最小可用的 daemon 客户端。非线程安全，每次调用自建 stub。"""

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout
        self._channel = None
        self._metadata: list[tuple[str, str]] = []
        self.endpoint: dict | None = None

    # -- 连接 ---------------------------------------------------------------
    @property
    def available(self) -> bool:
        return AVAILABLE and self.endpoint is not None and self._channel is not None

    def connect(self) -> bool:
        if not AVAILABLE:
            return False
        endpoint = read_endpoint()
        if endpoint is None:
            return False
        try:
            self._channel = grpc.insecure_channel(endpoint["addr"])
            token = str(endpoint.get("token") or "")
            self._metadata = [("authorization", f"Bearer {token}")] if token else []
            # 用一次廉价调用探活：端点文件可能是上次运行残留的。
            self._daemon().GetVersion(
                self._daemon_pb2().GetVersionRequest(), metadata=self._metadata, timeout=self.timeout
            )
        except Exception:
            self.close()
            return False
        self.endpoint = endpoint
        return True

    def close(self) -> None:
        if self._channel is not None:
            try:
                self._channel.close()
            except Exception:
                pass
        self._channel = None
        self.endpoint = None

    # -- 内部 ---------------------------------------------------------------
    @staticmethod
    def _daemon_pb2():
        from laji.agent.v1 import daemon_pb2

        return daemon_pb2

    def _daemon(self):
        from laji.agent.v1 import daemon_pb2_grpc

        return daemon_pb2_grpc.AgentDaemonStub(self._channel)

    def _session(self):
        return session_pb2_grpc.AgentSessionStub(self._channel)

    # -- 模型清单 / key -----------------------------------------------------
    def list_model_profiles(self) -> list[str]:
        """引擎当前认识的 profile 名（校验桌宠那份镜像是否被读进去）。"""
        request = self._daemon_pb2().ListModelProfilesRequest()
        response = self._daemon().ListModelProfiles(
            request, metadata=self._metadata, timeout=self.timeout
        )
        return [str(item.name) for item in response.profiles]

    def set_model_key(self, model: str, api_key: str) -> bool:
        """把某个 profile 的 key 交给 daemon：只进内存，不落盘、不回写 config.toml。"""
        request = self._daemon_pb2().SetModelKeyRequest(model=str(model), api_key=str(api_key))
        response = self._daemon().SetModelKey(request, metadata=self._metadata, timeout=self.timeout)
        return bool(response.present)

    # -- 读 ---------------------------------------------------------------
    def list_runs(self, limit: int = 20, by_session: bool = False):
        """`by_session=True`：每个工作区各取最新 `limit` 个会话，会话的全部轮次一并返回。

        按 run 计数分页时，别的项目一忙，扫宠的会话就被挤出窗口（现场 2026-11-02 18:36
        那轮因此没找到自己的上一轮，续聊链在那里断成新会话）。
        """
        runs = self._session().ListRuns(
            session_pb2.ListRunsRequest(limit=limit, by_session=by_session),
            metadata=self._metadata,
            timeout=self.timeout,
        )
        listed = list(runs.runs)
        return listed if by_session else listed[:limit]

    def get_run(self, run_id: str):
        return self._session().GetRun(
            session_pb2.GetRunRequest(run_id=run_id), metadata=self._metadata, timeout=self.timeout
        )

    def _meta(self, workspace_root: str = "") -> list[tuple[str, str]]:
        """基础 metadata + 可选的 workspace 限定。

        工作区走 metadata 而不是新增字段：宠物侧的 Python 存根是预生成二进制，
        重生成得有 protoc。引擎两个通道同义，字段优先。
        """
        if not workspace_root:
            return self._metadata
        return [*self._metadata, ("x-laji-workspace-root", workspace_root)]

    def list_mcp_servers(self, workspace_root: str = "") -> list[dict]:
        """配置里每个 server 一条运行态。引擎没起时调用方拿到空列表。

        ``workspace_root`` 非空 = 那个目录自己的连接器清单（`<ws>/.laji/pet-mcp.json`），
        跟 agent 面那份 `config.toml` 清单是两回事。
        """
        request = self._daemon_pb2().ListMcpServersRequest()
        res = self._daemon().ListMcpServers(
            request, metadata=self._meta(workspace_root), timeout=self.timeout
        )
        return [_server_status(one) for one in res.servers]

    def list_mcp_tools(self, workspace_root: str = "") -> list[dict]:
        """只要 MCP 工具（``mcp:<server>:<tool>``），按 server 拆开。"""
        request = self._daemon_pb2().ListToolsRequest()
        res = self._daemon().ListTools(
            request, metadata=self._meta(workspace_root), timeout=self.timeout
        )
        out: list[dict] = []
        for one in res.tools:
            head, _, rest = str(one.name).partition(":")
            if head != "mcp":
                continue
            server, _, tool = rest.partition(":")
            out.append(
                {
                    "server": server,
                    "name": tool,
                    "description": str(one.description or ""),
                    "schema": str(one.parameters_schema_json or ""),
                    "disabled": bool(one.disabled),
                }
            )
        return out

    def reload_mcp_server(
        self, name: str, authorize: bool = False, workspace_root: str = ""
    ) -> dict:
        """重连并重新发现；失败也是 OK，看返回状态里的 ``error``。"""
        request = self._daemon_pb2().ReloadMcpServerRequest(name=name, authorize=authorize)
        res = self._daemon().ReloadMcpServer(
            request,
            metadata=self._meta(workspace_root),
            timeout=max(self.timeout, RELOAD_TIMEOUT_SECONDS),
        )
        return {
            "server": _server_status(res.server),
            "added": list(res.tools_added),
            "removed": list(res.tools_removed),
        }

    def reload_local_config(self) -> bool:
        """重读 ``config.toml``：模型路由、MCP 槽位，以及治理链换芯。

        ``[permissions].allow`` 是治理链在 Build 时吃进去的，写完不重载等于没写 ——
        Run 仍然按旧规则弹「逐次授权」，桌宠那边就卡在审批上等一个没人点的按钮。
        """
        self._daemon().ReloadLocalConfig(
            self._daemon_pb2().ReloadLocalConfigRequest(),
            metadata=self._metadata,
            timeout=max(self.timeout, RELOAD_TIMEOUT_SECONDS),
        )
        return True

    def logout_mcp_server(self, name: str, workspace_root: str = "") -> dict:
        request = self._daemon_pb2().LogoutMcpServerRequest(name=name)
        res = self._daemon().LogoutMcpServer(
            request, metadata=self._meta(workspace_root), timeout=self.timeout
        )
        return _server_status(res.server)

    # -- 写 ---------------------------------------------------------------
    def create_run(
        self, prompt: str, workspace_root: str, parent_run_id: str = "", model_profile: str = ""
    ) -> str:
        """parent_run_id 非空 = 接着那一轮聊（客户端按这条链归组会话）。

        工具面固定 `TOOL_SURFACE_COMPANION`：桌宠是这一面的唯一调用方。不传就落
        CODE —— 气泡拿到的是工程手册而不是宠物词面，`# 记性` 那段指引和
        `builtin:remember` 的用法一起消失（现场 84 轮里有 77 轮就是这么跑出去的）。

        ``model_profile`` 非空 = 这一轮按名字用指定 profile。桌宠模型与 agent 模型
        是两套（见 ``pet/chat/engine_profiles.py``），不传就落 agent 的
        `[model.routing]` —— 用户在桌宠设置里加的模型等于没用上。
        """
        request = session_pb2.CreateRunRequest(
            user_prompt=prompt,
            workspace_root=workspace_root,
            parent_run_id=parent_run_id,
            tool_surface=TOOL_SURFACE_COMPANION,
        )
        if model_profile:
            request.model.CopyFrom(session_pb2.ModelSpec(profile=str(model_profile)))
        created = self._session().CreateRun(
            request, metadata=self._metadata, timeout=self.timeout
        )
        return created.run_id

    def cancel_run(self, run_id: str) -> None:
        self._session().CancelRun(
            session_pb2.CancelRunRequest(run_id=run_id), metadata=self._metadata, timeout=self.timeout
        )

    def approve(
        self,
        run_id: str,
        call_id: str,
        approved: bool,
        question_answer: str = "",
        question_skipped: bool = False,
    ) -> None:
        """回审批；questions 的作答走同一 RPC（``ApproveToolRequest`` 6/7 号字段）。

        主窗 ``decideQuestions`` 的口径：answer 非空或 skipped=True 即算作答，
        此时 approved 无意义（host 只看 question_answer/question_skipped）。
        """
        self._session().ApproveTool(
            session_pb2.ApproveToolRequest(
                run_id=run_id,
                call_id=call_id,
                approved=approved,
                question_answer=question_answer,
                question_skipped=question_skipped,
            ),
            metadata=self._metadata,
            timeout=self.timeout,
        )

    def stream(self, run_id: str, after_event_seq: int = 0, timeout: float = 600.0) -> Iterator:
        """产出 RunEvent；调用方负责在拿到终态后停止迭代。"""
        return self._session().StreamRun(
            session_pb2.StreamRunRequest(run_id=run_id, after_event_seq=after_event_seq),
            metadata=self._metadata,
            timeout=timeout,
        )


RUN_STATUS_LABEL = {
    0: "unknown",
    1: "created",
    2: "executing",
    3: "awaiting_approval",
    4: "completed",
    5: "failed",
    6: "cancelled",
}

TERMINAL_STATUSES = (4, 5, 6)
