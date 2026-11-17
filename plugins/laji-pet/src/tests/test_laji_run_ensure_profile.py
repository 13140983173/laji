# -*- coding: utf-8 -*-
"""`_ensure_profile` 的 reload 触发条件。

回归：托管块早已写盘（sync 无变更）但 daemon 内存里还没有该 profile
（daemon 后起、或上次 reload 因重名失败被吞）时，必须补一次 reload，
否则 create_run 会报 unknown model profile。
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

from pet.agent_link.laji_run_service import LajiRunService
from pet.chat import engine_profiles


class _Provider:
    def __init__(self):
        self.provider_id = "opencode-2"
        self.model = "deepseek-v4.1-flash"
        self.base_url = "https://opencode.ai/zen/go/v1"
        self.api_key = "sk-test"


class _FakeClient:
    def __init__(self, known):
        self.known = list(known)
        self.reloads = 0
        self.keys = {}

    def list_model_profiles(self):
        return list(self.known)

    def reload_local_config(self):
        self.reloads += 1
        return True

    def set_model_key(self, name, key):
        self.keys[name] = key


@pytest.fixture
def tmp_engine_config(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(engine_profiles, "engine_config_path", lambda: tmp_path / "config.toml")
    return tmp_path


def _service() -> LajiRunService:
    svc = LajiRunService(workspace_root="")
    svc._provider_id = "opencode-2"
    svc._api_key = "sk-test"
    svc._providers = lambda: [_Provider()]
    return svc


def test_reloads_when_daemon_lacks_profile(tmp_engine_config):
    # 先写一次盘，让下一次 sync 无变更（changed=False 分支）
    engine_profiles.sync_profiles([_Provider()])

    service = _service()
    client = _FakeClient(known=["pet-opencode", "pet-deepseek"])

    name = service._ensure_profile(client)

    assert name == "pet-opencode-2"
    assert client.reloads == 1  # changed=False，但内存缺 profile 触发补 reload
    assert client.keys == {"pet-opencode-2": "sk-test"}


def test_no_reload_when_daemon_knows_profile(tmp_engine_config):
    engine_profiles.sync_profiles([_Provider()])

    service = _service()
    client = _FakeClient(known=["pet-opencode-2", "pet-deepseek"])

    assert service._ensure_profile(client) == "pet-opencode-2"
    assert client.reloads == 0
