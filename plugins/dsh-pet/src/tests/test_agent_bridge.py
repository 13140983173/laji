from pathlib import Path

from pet import agent_bridge


def _dev_registration(tmp_path: Path, with_app_dir: bool) -> str:
    exe = tmp_path / "node_modules" / "electron" / "dist" / "LajiAgent.exe"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text("", encoding="utf-8")
    app = tmp_path / "apps" / "laji-agent"
    app.mkdir(parents=True, exist_ok=True)
    (app / "package.json").write_text("{}", encoding="utf-8")
    if with_app_dir:
        return f'"{exe}" "{app}" "%1"'
    return f'"{exe}" "%1"'


def test_dev_electron_registration_needs_app_dir(tmp_path):
    assert agent_bridge.registration_ok(_dev_registration(tmp_path, True)) is True
    # 少了应用目录：Electron 会把 URL 当 app 路径，弹出 “Unable to find Electron app”。
    assert agent_bridge.registration_ok(_dev_registration(tmp_path, False)) is False


def test_packaged_exe_registration_is_fine_without_app_dir(tmp_path):
    exe = tmp_path / "Laji.exe"
    exe.write_text("", encoding="utf-8")
    assert agent_bridge.registration_ok(f'"{exe}" "%1"') is True


def test_registration_without_url_placeholder_is_rejected():
    assert agent_bridge.registration_ok("") is False
    assert agent_bridge.registration_ok('"C:\\nowhere\\Laji.exe"') is False


def test_ask_url_shape():
    assert agent_bridge.ask_url() == "laji-agent://ask?from=pet"
    assert agent_bridge.ask_url("你好") == "laji-agent://ask?text=%E4%BD%A0%E5%A5%BD&from=pet"


def test_ask_url_marks_the_pet_source():
    """带 ``from=pet``，Laji 才知道该把会话放进 Pet 工作区（而不是当前项目）。"""
    assert agent_bridge.ASK_SOURCE == "pet"
    assert "from=pet" in agent_bridge.ask_url("干活")


def test_ask_url_carries_the_session_for_the_chat_button():
    """「去聊天窗」要把这一轮的 run 带上，否则只能开一个空白会话。"""
    url = agent_bridge.ask_url("", run_id="run-42")
    assert "from=pet" in url
    assert "run=run-42" in url
    assert "text=" not in url


def test_ask_url_can_target_another_workspace_for_an_approval_reminder():
    """审批提醒指的是项目里那条会话；不带 workspace 就会落到 Pet 下拉空。"""
    url = agent_bridge.ask_url("", run_id="run-42", workspace="D:\\code\\proj")
    assert "run=run-42" in url
    assert "workspace=" in url
    assert "code" in url


def test_open_laji_ask_does_not_pop_an_error_box_when_registration_is_broken(monkeypatch, tmp_path):
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: True)
    monkeypatch.setattr(
        agent_bridge, "protocol_command",
        lambda: _dev_registration(tmp_path, False),
    )
    monkeypatch.setattr(agent_bridge, "direct_commands", lambda: [])
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    # 注册命令不自洽时不弹系统错误框，直接让调用方回退自带聊天窗。
    assert agent_bridge.open_laji_ask("hi") is False
    assert opened == []


def test_broken_registration_still_reaches_the_agent_through_the_dev_entry(monkeypatch, tmp_path):
    """dev 把 laji-agent:// 写成了缺 app 目录的形状：不能因此就点「打工」没反应。"""
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _dev_registration(tmp_path, False))
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: False)
    dev = '"C:\\dev\\LajiAgent.exe" "C:\\dev\\app" "%1"'
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: dev)
    launched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_bridge, "_launch",
        lambda cmd, url, extra_env=None: launched.append((cmd, url)) or True)
    monkeypatch.setattr(agent_bridge, "dev_desktop_env", lambda: {"NERVE_DEV_ROOT": "C:\\dev"})
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is True
    assert opened == []
    assert launched == [(dev, agent_bridge.ask_url("干活"))]


def _packaged_registration(tmp_path: Path) -> str:
    exe = tmp_path / "Laji.exe"
    exe.write_text("", encoding="utf-8")
    return f'"{exe}" "%1"'


def test_open_laji_force_starts_a_stopped_agent(monkeypatch, tmp_path):
    """「打工」按钮要冷启动：「Laji 没在跑」不能把它拦下。"""
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: False)
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _packaged_registration(tmp_path))
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is True
    assert opened == [agent_bridge.ask_url("干活")]


def test_open_laji_without_force_keeps_the_old_precheck(monkeypatch, tmp_path):
    """不带 force 的老入口（去聊天窗）仍要先问进程：保持回退自带聊天窗的行为。"""
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: False)
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _packaged_registration(tmp_path))
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活") is False
    assert opened == []


def _laji_code_registration(tmp_path: Path) -> str:
    exe = tmp_path / "Laji Code.exe"
    exe.write_text("", encoding="utf-8")
    return f'"{exe}" "--open-url" "--" "%1"'


def test_laji_code_registration_is_bypassed_for_the_real_agent(monkeypatch, tmp_path):
    """dev 把 laji-agent:// 指给了 Laji Code：点「打工」不能打开那个 VS Code 壳。"""
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _laji_code_registration(tmp_path))
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: True)
    dev = '"C:\\dev\\LajiAgent.exe" "C:\\dev\\app" "%1"'
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: dev)
    launched: list[tuple[str, str]] = []
    envs: list[dict] = []

    def fake_launch(cmd, url, extra_env=None):
        launched.append((cmd, url))
        envs.append(extra_env or {})
        return True

    monkeypatch.setattr(agent_bridge, "_launch", fake_launch)
    monkeypatch.setattr(agent_bridge, "dev_desktop_env", lambda: {"NERVE_DEV_ROOT": "C:\\dev"})
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is True
    assert opened == []
    assert launched == [(dev, agent_bridge.ask_url("干活"))]
    assert envs == [{"NERVE_DEV_ROOT": "C:\\dev"}]


def test_laji_code_registration_falls_back_to_the_handler(monkeypatch, tmp_path):
    """找不到 dev 入口时不静默失败：还是交给系统协议（至少能弹出东西）。"""
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _laji_code_registration(tmp_path))
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: True)
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: "")
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is True
    assert opened == [agent_bridge.ask_url("干活")]


def test_dev_env_without_dev_server_loads_the_built_renderer(monkeypatch):
    """没在跑 dev server 就别声称自己是 dev shell：让进程走已构建的 renderer。"""
    monkeypatch.setattr(agent_bridge, "_dev_root", lambda: "C:\\dev")
    monkeypatch.setattr(agent_bridge, "_dev_server_running", lambda: False)
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\me\\AppData\\Local")
    for key in ("NERVE_DEV_ROOT", "LAJI_IN_PROCESS", "LAJI_SKIP_STARTUP_GATE",
                "LAJI_DATA_DIR", "LAJI_CONFIG_DIR", "VITE_DEV_SERVER_URL", "LAJI_DEV_SHELL"):
        monkeypatch.delenv(key, raising=False)

    env = agent_bridge.dev_desktop_env()

    assert env["VITE_DEV_SERVER_URL"] is None
    assert env["LAJI_DEV_SHELL"] is None
    assert env["NERVE_DEV_ROOT"] == "C:\\dev"
    assert env["LAJI_DATA_DIR"] == "C:\\Users\\me\\AppData\\Local\\laji"


def test_dev_env_attaches_a_running_dev_server(monkeypatch):
    """dev server 活着就要挂上去，否则冷启动的窗口看不到正在改的 UI。"""
    monkeypatch.setattr(agent_bridge, "_dev_root", lambda: "C:\\dev")
    monkeypatch.setattr(agent_bridge, "_dev_server_running", lambda: True)
    monkeypatch.setenv("LOCALAPPDATA", "C:\\Users\\me\\AppData\\Local")
    monkeypatch.delenv("VITE_DEV_SERVER_URL", raising=False)
    monkeypatch.delenv("LAJI_DEV_SHELL", raising=False)

    env = agent_bridge.dev_desktop_env()

    assert env["VITE_DEV_SERVER_URL"] == "http://127.0.0.1:5174/"
    assert env["LAJI_DEV_SHELL"] == "1"


def test_dev_env_never_overrides_the_caller(monkeypatch):
    """已经在 dev 环境里的调用方（npm run dev 起的那份）不能被改配置。"""
    monkeypatch.setattr(agent_bridge, "_dev_root", lambda: "C:\\dev")
    monkeypatch.setattr(agent_bridge, "_dev_server_running", lambda: False)
    monkeypatch.setenv("LAJI_IN_PROCESS", "1")

    assert "LAJI_IN_PROCESS" not in agent_bridge.dev_desktop_env()


def test_dev_env_is_empty_without_a_dev_root(monkeypatch):
    monkeypatch.setattr(agent_bridge, "_dev_root", lambda: "")

    assert agent_bridge.dev_desktop_env() == {}


def test_apply_env_drops_stale_dev_server_entries():
    """继承来的过期 dev server 地址必须被删，否则冷启动一个白屏窗口。"""
    base = {
        "PATH": "C:\\Windows",
        "VITE_DEV_SERVER_URL": "http://127.0.0.1:5174/",
        "LAJI_DEV_SHELL": "1",
    }

    merged = agent_bridge._apply_env(
        base, {"VITE_DEV_SERVER_URL": None, "LAJI_DEV_SHELL": None, "NERVE_DEV_ROOT": "C:\\dev"})

    assert merged == {"PATH": "C:\\Windows", "NERVE_DEV_ROOT": "C:\\dev"}
    assert base["LAJI_DEV_SHELL"] == "1"


def test_packaged_registration_still_uses_the_system_handler(monkeypatch, tmp_path):
    """装好的 Laji（协议对着 Laji.exe）保持原路径，不自己拼命令。"""
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: _packaged_registration(tmp_path))
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: True)
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: '"C:\\dev\\LajiAgent.exe" "%1"')
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is True
    assert opened == [agent_bridge.ask_url("干活")]


def _isolate_install_roots(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for key in ("APPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        monkeypatch.delenv(key, raising=False)


def test_installed_command_finds_the_user_level_install(monkeypatch, tmp_path):
    """用户只拷了桌宠包、协议又没注册好时，靠安装器默认落点把它拉起来。"""
    _isolate_install_roots(monkeypatch, tmp_path)
    exe = tmp_path / "Programs" / "Laji Agent" / "Laji Agent.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")

    assert agent_bridge.installed_desktop_command() == f'"{exe}" "%1"'


def test_installed_command_looks_into_version_subdirs(monkeypatch, tmp_path):
    _isolate_install_roots(monkeypatch, tmp_path)
    exe = tmp_path / "Programs" / "Laji Agent" / "app-1.2.3" / "LajiAgent.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")

    assert agent_bridge.installed_desktop_command() == f'"{exe}" "%1"'


def test_installed_command_is_empty_when_nothing_is_installed(monkeypatch, tmp_path):
    _isolate_install_roots(monkeypatch, tmp_path)

    assert agent_bridge.installed_desktop_command() == ""


def test_open_laji_cold_starts_an_unregistered_install(monkeypatch, tmp_path):
    """没有任何协议注册：点「打工」也必须能把 Laji 开起来。"""
    _isolate_install_roots(monkeypatch, tmp_path)
    exe = tmp_path / "Programs" / "Laji Agent" / "Laji Agent.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: "")
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: "")
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: False)
    launched: list[tuple[str, str]] = []
    monkeypatch.setattr(
        agent_bridge, "_launch",
        lambda cmd, url, extra_env=None: launched.append((cmd, url)) or True)
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("", force=True) is True
    assert launched == [(f'"{exe}" "%1"', agent_bridge.ask_url(""))]
    assert opened == []


def test_open_laji_reports_failure_when_there_is_nowhere_to_go(monkeypatch, tmp_path):
    """什么都没装、注册也空：返回 False 让调用方提示用户，而不是假装成功。"""
    _isolate_install_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: "")
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: "")
    monkeypatch.setattr(agent_bridge, "laji_running", lambda: False)
    opened: list[str] = []
    monkeypatch.setattr(agent_bridge, "_open_url", lambda url: opened.append(url) or True)

    assert agent_bridge.open_laji("干活", force=True) is False
    assert opened == []


def test_dev_server_probe_is_cached_between_clicks(monkeypatch):
    """Windows 上探测一个关闭的端口要等超时（实测 ~276ms）；点击路径不能每次都交这笔钱。"""
    import socket

    probes: list[tuple[str, int]] = []
    monkeypatch.setattr(socket, "create_connection",
                        lambda addr, timeout=0: probes.append(addr) or (_ for _ in ()).throw(OSError))
    monkeypatch.setattr(agent_bridge, "_DEV_SERVER_CACHE", {"key": None, "at": 0.0, "ok": False})

    assert agent_bridge._dev_server_running() is False
    assert agent_bridge._dev_server_running() is False
    assert len(probes) == 1  # 第二次命中缓存

    agent_bridge._dev_server_running(fresh=True)
    assert len(probes) == 2  # 强制刷新才重新探


def test_has_launch_entry_accepts_the_dev_mirror(monkeypatch, tmp_path):
    """注册项坏掉（缺 app 目录）但有 dev 镜像：仍算「能叫起来」，不该先说她找不到。"""
    monkeypatch.setattr(agent_bridge, "protocol_command",
                        lambda: _dev_registration(tmp_path, False))
    monkeypatch.setattr(agent_bridge, "dev_desktop_command",
                        lambda: _dev_registration(tmp_path, True))

    assert agent_bridge.has_launch_entry() is True


def test_has_launch_entry_is_false_when_nothing_is_installed(monkeypatch, tmp_path):
    _isolate_install_roots(monkeypatch, tmp_path)
    monkeypatch.setattr(agent_bridge, "protocol_command", lambda: "")
    monkeypatch.setattr(agent_bridge, "dev_desktop_command", lambda: "")

    assert agent_bridge.has_launch_entry() is False


def test_open_laji_in_background_keeps_the_ui_thread_free(monkeypatch):
    """点击路径不能在主线程里等 Electron 冷启动。"""
    import threading
    import time

    done = threading.Event()
    seen: dict = {}

    def fake_open_laji(*args, **kwargs):
        seen["worker"] = threading.current_thread().name
        time.sleep(0.05)  # 假装 Electron 在起
        return True

    monkeypatch.setattr(agent_bridge, "open_laji", fake_open_laji)

    started = time.perf_counter()
    assert agent_bridge.open_laji_in_background("", force=True, on_done=lambda ok: done.set()) is True
    assert (time.perf_counter() - started) < 0.05  # 立刻返回，不等拉起
    assert done.wait(2.0) is True
    assert seen["worker"] != threading.current_thread().name
