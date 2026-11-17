"""Laji 侧「等你拍板」的提醒：只在**新**出现的审批上叫一声。"""

from types import SimpleNamespace

from PySide6.QtCore import QRect

from pet.agent_link import approval_watch, pending_approval


def _run(run_id, status=3, workspace="D:\\code\\proj", prompt="改一下登录"):
    return SimpleNamespace(run_id=run_id, status=status, workspace_root=workspace, user_prompt=prompt)


def test_only_awaiting_approval_runs_are_picked():
    runs = [_run("a", 3), _run("b", 2), _run("c", 4), SimpleNamespace(run_id="d", status="x")]

    assert [r.run_id for r in approval_watch.awaiting(runs)] == ["a"]


def test_message_names_the_task_but_stays_short():
    text = approval_watch.describe(_run("a", prompt="把这个仓库里所有缺失的类型标注补齐并跑一遍测试"))

    assert text.startswith("Laji 那边有个操作等你拍板：")
    assert text.endswith("…")
    assert len(text) <= 40


def test_message_without_prompt_still_readable():
    assert approval_watch.describe(_run("a", prompt="")) == "Laji 那边有个操作等你拍板"


def test_first_scan_only_seeds_so_a_running_pet_is_not_robbed_with_popups():
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))

    watcher.scan_runs([_run("old")])

    assert seen == []


def test_new_approval_is_announced_with_its_own_workspace():
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.scan_runs([_run("old")])

    watcher.scan_runs([_run("old"), _run("new", workspace="D:\\code\\proj")])

    assert len(seen) == 1
    run_id, workspace, message, approval = seen[0]
    assert run_id == "new"
    assert workspace == "D:\\code\\proj"  # 打开时要落到那条会话自己的工作区
    assert "等你拍板" in message
    assert approval is None  # 探不到未决审批时只能提醒、给不了按钮


def test_same_run_is_announced_only_once():
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.scan_runs([])

    watcher.scan_runs([_run("new")])
    watcher.scan_runs([_run("new")])

    assert len(seen) == 1


def test_resolved_run_can_be_announced_again_if_it_waits_later():
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.scan_runs([])

    watcher.scan_runs([_run("new")])
    watcher.scan_runs([_run("new", status=2)])  # 批完了，继续跑
    watcher.scan_runs([_run("new", status=3)])  # 下一个工具又要拍板

    assert len(seen) == 2


def test_daemon_offline_keeps_the_watcher_quiet(monkeypatch):
    class _Offline:
        def connect(self):
            return False

        def list_runs(self, limit=50):  # pragma: no cover - 不该被调到
            raise AssertionError("connect 失败后不该再读 run 列表")

        def close(self):
            pass

    monkeypatch.setattr(approval_watch.daemon_client, "LajiDaemonClient", _Offline)
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))

    watcher.poll()
    for thread in list(__import__("threading").enumerate()):
        if thread.name == "laji-approval-scan":
            thread.join(timeout=2)

    assert seen == []
    assert watcher._busy is False


def test_attention_goes_to_the_message_center_not_a_bubble(monkeypatch):
    """审批通报归头顶消息中心（徽章胶囊），不再 mist_reply 弹白面板重复一遍。

    2026-11-02 实机：白面板跟徽章胶囊同屏各报一次，还盖掉主窗半栏。消息中心
    接管通报后这里只记账（跳转目标 + 审批表），一个泡都不该冒。
    """
    from pet import app as app_mod
    from pet import mist_bubble as mist_mod

    host = app_mod.AppShell.__new__(app_mod.AppShell)
    host._laji_attention_target = None
    calls = []
    host._remember_laji_approval = lambda *args: calls.append(args)

    def _fail(*args, **kwargs):
        raise AssertionError("审批通报不该再走雾泡")

    monkeypatch.setattr(mist_mod, "mist_reply", _fail)

    host._on_laji_attention("run-1", "D:\\code\\proj", "Laji 那边有个操作等你拍板")

    assert calls and calls[0][0] == "run-1"
    assert host._laji_attention_target == ("run-1", "D:\\code\\proj")


def test_a_probe_that_reads_nothing_is_retried_not_cached():
    """探测读不到只是「这一轮没读到」，下一轮必须重探。

    2026-11-05 实机：12k 事件的会话里审批请求排在第 5378 个，回放上限 4000
    让它读到 None；若把 None 按 updated_at_ms 缓存，就永久停在「只提醒」。
    """
    results = [None, _approval()]
    watcher = approval_watch.ApprovalWatcher(probe=lambda _client, _run_id: results.pop(0))
    run = _run("new")

    assert watcher._probe_pending(None, [run]) == {}
    assert "new" in watcher._probe_pending(None, [run])


def _approval(run_id="new", call_id="call-1", tool_name="builtin:run_terminal"):
    return pending_approval.PendingApproval(
        run_id=run_id, call_id=call_id, tool_name=tool_name, reason="shell"
    )


def test_pending_approval_rides_along_so_the_bubble_can_show_buttons():
    """提醒里带上未决审批：有 call_id 才可能在气泡里给【允许/拒绝】。"""
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.scan_runs([])

    approval = _approval()
    watcher.scan_runs([_run("new")], pending={"new": approval})

    assert seen[0][3] is approval
    # 气泡里给的是名字，不是引擎的 wire name。
    assert "运行命令" in seen[0][2]
    assert "builtin:" not in seen[0][2]


def test_the_next_approval_on_the_same_run_is_announced_again():
    """批完这个还有下一个在等：只按 run_id 去重会把第二条吞掉。"""
    watcher = approval_watch.ApprovalWatcher()
    seen = []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.scan_runs([])

    watcher.scan_runs([_run("new")], pending={"new": _approval(call_id="call-1")})
    watcher.scan_runs([_run("new")], pending={"new": _approval(call_id="call-2")})

    assert [args[3].call_id for args in seen] == ["call-1", "call-2"]


def test_resolved_run_is_reported_gone_and_can_come_back():
    """那边自己批了：要能撤卡；之后又卡住得能再叫一声。"""
    watcher = approval_watch.ApprovalWatcher()
    seen, gone = [], []
    watcher.attention.connect(lambda *args: seen.append(args))
    watcher.gone.connect(gone.append)
    watcher.scan_runs([])

    watcher.scan_runs([_run("new")], pending={"new": _approval(call_id="call-1")})
    watcher.scan_runs([_run("new", status=2)])  # 批完了，继续跑
    watcher.scan_runs([_run("new")], pending={"new": _approval(call_id="call-2")})

    assert gone == ["new"]
    assert [args[3].call_id for args in seen] == ["call-1", "call-2"]


def test_question_approval_is_described_as_a_question():
    approval = pending_approval.PendingApproval(
        run_id="new", call_id="call-q",
        question="你在哪个城市？我按这个城市查今天的天气。",
        options=(("a", "北京"), ("b", "上海")),
    )
    text = approval_watch.describe_approval(approval)
    assert text.startswith("Laji 那边问你：")
    assert "你在哪个城市" in text
    assert len(text) <= 40


def test_question_approval_is_described_as_a_question():
    approval = pending_approval.PendingApproval(
        run_id="new", call_id="call-q",
        question="你在哪个城市？我按这个城市查今天的天气。",
        options=(("a", "北京"), ("b", "上海")),
    )
    text = approval_watch.describe_approval(approval)
    assert text.startswith("Laji 那边问你：")
    assert "你在哪个城市" in text
    assert len(text) <= 40
