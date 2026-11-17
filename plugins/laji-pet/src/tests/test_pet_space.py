"""桌宠工作区（``Pet`` 目录）与会话归属的选择规则。"""

from types import SimpleNamespace

from pet.agent_link import daemon_client, pet_space
from pet.agent_link.laji_run_service import LajiRunService


def _run(workspace_root: str, run_id: str):
    return SimpleNamespace(workspace_root=workspace_root, run_id=run_id)


def _client(runs):
    def list_runs(limit=20, by_session=False):
        return list(runs)

    return SimpleNamespace(list_runs=list_runs)


def test_workspace_follows_the_injected_env(monkeypatch, tmp_path):
    target = tmp_path / "Pet"
    monkeypatch.setenv(pet_space.PET_WORKSPACE_ENV, str(target))

    root = pet_space.pet_workspace_root()

    assert root == str(target)
    assert target.is_dir()


def test_workspace_falls_back_under_the_app_user_data(monkeypatch, tmp_path):
    monkeypatch.delenv(pet_space.PET_WORKSPACE_ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    root = pet_space.pet_workspace_root("shenshen")

    # 每只桌宠一格：`Pet/<角色 id>`。老版本直接落在 `Pet` 上，那种会话现在也还认。
    assert root == str(tmp_path / "Laji Agent" / "Pet" / "shenshen")
    assert (tmp_path / "Laji Agent" / "Pet" / "shenshen").is_dir()


def test_workspace_without_a_character_uses_the_default_one(monkeypatch, tmp_path):
    monkeypatch.delenv(pet_space.PET_WORKSPACE_ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))

    root = pet_space.pet_workspace_root()

    assert root.startswith(str(tmp_path / "Laji Agent" / "Pet") + "\\") or root.startswith(
        str(tmp_path / "Laji Agent" / "Pet") + "/"), root
    assert root != str(tmp_path / "Laji Agent" / "Pet")


def test_workspace_inherits_the_old_pet_dot_laji_once(monkeypatch, tmp_path):
    """老存档在 `Pet/.laji`：新格子第一次出现时拿一份副本，之后不再覆盖。"""
    monkeypatch.delenv(pet_space.PET_WORKSPACE_ENV, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    legacy = tmp_path / "Laji Agent" / "Pet" / ".laji"
    legacy.mkdir(parents=True)
    (legacy / "pet-persona.md").write_text("老人设", encoding="utf-8")

    root = pet_space.pet_workspace_root("shenshen")

    copied = tmp_path / "Laji Agent" / "Pet" / "shenshen" / ".laji" / "pet-persona.md"
    assert copied.read_text(encoding="utf-8") == "老人设"

    # 用户改了新人设，再次解析不能拿老的盖回去。
    copied.write_text("新人设", encoding="utf-8")
    pet_space.pet_workspace_root("shenshen")
    assert copied.read_text(encoding="utf-8") == "新人设"
    assert str(root).endswith("shenshen")


def test_same_workspace_ignores_case_and_trailing_separator():
    assert pet_space.same_workspace("C:\\Users\\me\\Laji Agent\\Pet", "c:/users/me/laji agent/pet/")
    assert not pet_space.same_workspace("C:\\code\\proj", "C:\\Users\\me\\Pet")
    assert not pet_space.same_workspace("", "C:\\Users\\me\\Pet")


def test_session_stays_in_the_pet_space_instead_of_the_active_project(monkeypatch, tmp_path):
    """最近一次 run 在项目里跑，桌宠也不能把自己的话接进那个会话。"""
    pet_dir = tmp_path / "Pet"
    monkeypatch.setenv(pet_space.PET_WORKSPACE_ENV, str(pet_dir))
    client = _client([_run("C:\\code\\proj", "proj-run")])

    workspace, parent = LajiRunService._resolve_context(SimpleNamespace(_workspace_root=""), client)

    assert workspace == str(pet_dir)
    assert parent == ""


def test_session_chains_onto_the_last_pet_run(monkeypatch, tmp_path):
    pet_dir = tmp_path / "Pet"
    monkeypatch.setenv(pet_space.PET_WORKSPACE_ENV, str(pet_dir))
    client = _client([
        _run("C:\\code\\proj", "proj-run"),
        _run(str(pet_dir), "pet-run-1"),
        _run(str(pet_dir), "pet-run-0"),
    ])

    workspace, parent = LajiRunService._resolve_context(SimpleNamespace(_workspace_root=""), client)

    assert workspace == str(pet_dir)
    assert parent == "pet-run-1"


def test_session_reuses_the_run_it_just_created(monkeypatch, tmp_path):
    """进程内记住的那一轮优先：不再为每次气泡多打一次列表，也不会因窗口滑动断链。"""
    pet_dir = tmp_path / "Pet"
    monkeypatch.setenv(pet_space.PET_WORKSPACE_ENV, str(pet_dir))
    calls: list = []

    def list_runs(limit=20, by_session=False):
        calls.append((limit, by_session))
        return [_run(str(pet_dir), "stale-run")]

    service = SimpleNamespace(_workspace_root="", _last_ctx=(str(pet_dir), "fresh-run"))

    workspace, parent = LajiRunService._resolve_context(service, SimpleNamespace(list_runs=list_runs))

    assert (workspace, parent) == (str(pet_dir), "fresh-run")
    assert calls == [], "命中内存里的上一轮时不应再打列表 RPC"


def test_session_drops_a_stale_parent_after_a_workspace_switch(monkeypatch, tmp_path):
    """切到另一个工作区（换角色）后，旧的 parent 不能带过去——daemon 会报跨工作区。"""
    pet_dir = tmp_path / "Pet"
    monkeypatch.setenv(pet_space.PET_WORKSPACE_ENV, str(pet_dir))
    client = _client([_run(str(pet_dir), "pet-run-1")])
    service = SimpleNamespace(_workspace_root="", _last_ctx=("C:\\code\\proj", "proj-run"))

    workspace, parent = LajiRunService._resolve_context(service, client)

    assert (workspace, parent) == (str(pet_dir), "pet-run-1")


def test_list_runs_can_page_by_session():
    """按会话分页才能保证每个工作区都各有自己的上一轮（run 计数分页会被别的项目挤出窗口）。"""
    seen: dict = {}

    class Stub:
        def ListRuns(self, request, metadata=None, timeout=None):  # noqa: N802 - gRPC 生成名
            seen["limit"] = request.limit
            seen["by_session"] = request.by_session
            return SimpleNamespace(runs=[_run("C:\\x", "r1")])

    client = daemon_client.LajiDaemonClient.__new__(daemon_client.LajiDaemonClient)
    client._session = lambda: Stub()
    client._metadata = ()
    client.timeout = 5.0

    client.list_runs(limit=1, by_session=True)

    assert seen == {"limit": 1, "by_session": True}
