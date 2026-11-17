"""桌宠写进 Laji 的打工身份（``{workspace}/.laji/pet-persona.md``）。"""

import os
from pathlib import Path

from pet.agent_link import persona_prompt
from pet.agent_link.persona_prompt import (
    PERSONA_REL_PATH,
    character_persona,
    persona_path,
    resolve_persona,
    sync_pet_persona,
)

_REPO_ROOT = Path(__file__).resolve().parents[5]
_RUST_PERSONA = _REPO_ROOT / "crates" / "laji-context" / "src" / "persona.rs"


def test_rel_path_matches_the_rust_reader():
    """Rust 侧只读这一个文件名；两边漂了就是静默失效。"""
    source = _RUST_PERSONA.read_text(encoding="utf-8")
    assert 'pub const PERSONA_REL_PATH: &str = ".laji/pet-persona.md";' in source
    assert os.path.normpath(PERSONA_REL_PATH) == os.path.normpath(".laji/pet-persona.md")


def test_character_persona_names_the_character_and_forbids_laji_impersonation():
    text = character_persona("shenshen")
    assert "大肥鱼" in text  # 人话称呼，不是目录 id
    assert "shenshen" in text
    assert "桌宠" in text
    assert "不要说自己是 Laji" in text


def test_unknown_character_uses_its_id_instead_of_guessing_a_name():
    text = character_persona("no-such-character")
    assert "no-such-character" in text
    # 不认识的角不能继承 shenshen 的性格。
    assert "大肥鱼" not in text


def test_override_wins_and_is_flattened_to_one_line():
    text = resolve_persona("shenshen", "  You are 老板的私人助理。\n\n 只做报销。 ")
    assert text == "You are 老板的私人助理。 只做报销。"


def test_sync_writes_the_persona_under_the_laji_dir(tmp_path):
    workspace = str(tmp_path)

    assert sync_pet_persona(workspace, "shenshen") is True
    written = Path(persona_path(workspace))
    assert written == tmp_path / ".laji" / "pet-persona.md"
    assert written.read_text(encoding="utf-8").strip() == character_persona("shenshen")


def test_sync_is_idempotent_so_startup_does_not_churn_the_file(tmp_path):
    workspace = str(tmp_path)
    sync_pet_persona(workspace, "shenshen")
    before = os.stat(persona_path(workspace)).st_mtime_ns

    assert sync_pet_persona(workspace, "shenshen") is False
    assert os.stat(persona_path(workspace)).st_mtime_ns == before


def test_sync_rewrites_when_the_character_changes(tmp_path):
    workspace = str(tmp_path)
    sync_pet_persona(workspace, "shenshen")

    assert sync_pet_persona(workspace, "no-such-character") is True
    assert "no-such-character" in Path(persona_path(workspace)).read_text(encoding="utf-8")


def test_disabling_the_persona_removes_the_file_and_restores_laji_identity(tmp_path):
    workspace = str(tmp_path)
    sync_pet_persona(workspace, "shenshen")

    assert sync_pet_persona(workspace, "shenshen", enabled=False) is True
    assert not Path(persona_path(workspace)).exists()
    assert sync_pet_persona(workspace, "shenshen", enabled=False) is False


def test_empty_workspace_is_a_no_op():
    assert sync_pet_persona("", "shenshen") is False


def test_unwritable_workspace_reports_failure_instead_of_raising(tmp_path):
    """写盘失败只记日志，不能把启动/切角色炸掉。"""
    target = str(tmp_path / ".laji" / "pet-persona.md")
    blocker = tmp_path / ".laji"
    blocker.write_text("not a directory", encoding="utf-8")

    assert sync_pet_persona(str(tmp_path), "shenshen") is False
    assert not Path(target).exists()


def test_current_character_reads_the_configured_one():
    class _Cfg:
        def __init__(self, value):
            self._value = value

        def get(self, key, default=None):
            return self._value if key == "character" else default

    assert persona_prompt.current_character(_Cfg("shenshen")) == "shenshen"
    assert persona_prompt.current_character(_Cfg("")) == "shenshen"


def test_every_bundled_character_has_its_own_persona_and_self_call():
    """五个内置角色各有独立性格句与小名——登记表漏登记 = 桌宠变无名氏管家。"""
    expected = {
        "shenshen": "鱼鱼",
        "whale-maid-extra": "小蓝",
        "whale-maid-gpt": "阿蓝",
        "whale-maid-claude": "蓝蓝",
        "catgirl-gemini": "喵喵",
    }
    flavors = set()
    for ident, call in expected.items():
        assert persona_prompt.character_self_call(ident) == call
        text = character_persona(ident)
        assert call in text, f"{ident} 的自称没进人设句"
        flavors.add(persona_prompt._CHARACTER_FLAVOR[ident])
    # 性格句两两不同（同一形象的三个女仆分身也不许共用一份）。
    assert len(flavors) == len(expected)


def test_persona_override_prefers_per_character_entry_over_legacy_global():
    """按角色单设优先；没单设的角色回落旧全局键；两处都空 = 走角色默认。"""

    class _Cfg:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

    cfg = _Cfg({
        "pet_persona_overrides": {"whale-maid-gpt": "  元气满满。\n"},
        "pet_persona_override": "旧全局身份",
    })
    assert persona_prompt.persona_override_for(cfg, "whale-maid-gpt") == "元气满满。"
    assert persona_prompt.persona_override_for(cfg, "shenshen") == "旧全局身份"
    assert persona_prompt.persona_override_for(_Cfg({}), "shenshen") == ""


def test_sync_from_config_uses_per_character_override(tmp_path, monkeypatch):
    """同步链路按当前角色取单设人设（切换角色 = 各写各的）。"""
    import pet.agent_link.pet_space as pet_space

    monkeypatch.setattr(
        pet_space, "pet_workspace_root", lambda cid: str(tmp_path / cid)
    )

    class _Cfg:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

    cfg = _Cfg({
        "character": "whale-maid-gpt",
        "pet_persona_overrides": {"whale-maid-gpt": "You are 阿蓝，元气担当。"},
    })
    assert persona_prompt.sync_from_config(cfg, workspace=str(tmp_path / "whale-maid-gpt"))
    written = (tmp_path / "whale-maid-gpt" / PERSONA_REL_PATH).read_text(encoding="utf-8")
    assert "阿蓝，元气担当" in written
    assert "鱼鱼" not in written


def test_every_bundled_character_has_its_own_persona_and_self_call():
    """五个内置角色各有独立性格句与小名——登记表漏登记 = 桌宠变无名氏管家。"""
    expected = {
        "shenshen": "鱼鱼",
        "whale-maid-extra": "小蓝",
        "whale-maid-gpt": "阿蓝",
        "whale-maid-claude": "蓝蓝",
        "catgirl-gemini": "喵喵",
    }
    flavors = set()
    for ident, call in expected.items():
        assert persona_prompt.character_self_call(ident) == call
        text = character_persona(ident)
        assert call in text, f"{ident} 的自称没进人设句"
        flavors.add(persona_prompt._CHARACTER_FLAVOR[ident])
    # 性格句两两不同（同一形象的三个女仆分身也不许共用一份）。
    assert len(flavors) == len(expected)


def test_persona_override_prefers_per_character_entry_over_legacy_global():
    """按角色单设优先；没单设的角色回落旧全局键；两处都空 = 走角色默认。"""

    class _Cfg:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

    cfg = _Cfg({
        "pet_persona_overrides": {"whale-maid-gpt": "  元气满满。\n"},
        "pet_persona_override": "旧全局身份",
    })
    assert persona_prompt.persona_override_for(cfg, "whale-maid-gpt") == "元气满满。"
    assert persona_prompt.persona_override_for(cfg, "shenshen") == "旧全局身份"
    assert persona_prompt.persona_override_for(_Cfg({}), "shenshen") == ""


def test_sync_from_config_uses_per_character_override(tmp_path, monkeypatch):
    """同步链路按当前角色取单设人设（切换角色 = 各写各的）。"""
    import pet.agent_link.pet_space as pet_space

    monkeypatch.setattr(
        pet_space, "pet_workspace_root", lambda cid: str(tmp_path / cid)
    )

    class _Cfg:
        def __init__(self, data):
            self._data = data

        def get(self, key, default=None):
            return self._data.get(key, default)

    cfg = _Cfg({
        "character": "whale-maid-gpt",
        "pet_persona_overrides": {"whale-maid-gpt": "You are 阿蓝，元气担当。"},
    })
    assert persona_prompt.sync_from_config(cfg, workspace=str(tmp_path / "whale-maid-gpt"))
    written = (tmp_path / "whale-maid-gpt" / PERSONA_REL_PATH).read_text(encoding="utf-8")
    assert "阿蓝，元气担当" in written
    assert "鱼鱼" not in written
