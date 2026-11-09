"""宠物家的能力库存：技能 / 连接器 / 能力包，以及两个开关。

这些文件是宠物自己那一份（``<宠物家>/.laji`` 与 ``<宠物家>/plugins``）。
连接器是唯一的例外：引擎只读它自己那份 ``mcp-custom.json``，所以连接器一律
d往 ``LAJI_CONFIG_DIR`` 里写（测试把那个目录指到 tmp_path）。
"""

import json

import pytest

from pet.agent_link import pet_toolkit


@pytest.fixture(autouse=True)
def _config_dir(tmp_path, monkeypatch):
    """引擎那份清单落到临时目录：测试绝不能碰用户真实的 mcp-custom.json。"""
    cfg = tmp_path / "laji-config"
    cfg.mkdir()
    monkeypatch.setenv("LAJI_CONFIG_DIR", str(cfg))
    # 临时目录里的 config.toml 是假的：绝不能让引擎拿它去换芯。
    monkeypatch.setattr(pet_toolkit, "_RELOAD_ENGINE", False)
    # 工坊的读数会去数 agent 装过的包（agent_data_dirs）：不挡的话数字随开发机变。
    monkeypatch.setattr(pet_toolkit, "agent_data_dirs", lambda: [str(cfg)])
    return cfg


def _home(tmp_path):
    home = tmp_path / "Pet" / "shenshen"
    (home / ".laji" / "skills").mkdir(parents=True)
    (home / "plugins").mkdir(parents=True)
    return home


def _skill(home, folder, name, description="", source=""):
    target = home / ".laji" / "skills" / folder
    target.mkdir(parents=True)
    body = f"---\nname: {name}\ndescription: {description}\n"
    if source:
        body += f"source: {source}\n"
    body += "---\n\n正文\n"
    (target / "SKILL.md").write_text(body, encoding="utf-8")
    return target


def _agent_skill(base, folder, name, description=""):
    target = base / "skills" / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\nagent 正文\n",
        encoding="utf-8",
    )
    return target


def _mcp(home, servers):
    (home / ".laji" / "pet-mcp.json").write_text(
        json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8"
    )


def test_skills_read_front_matter_and_are_sorted(tmp_path):
    home = _home(tmp_path)
    _skill(home, "desktop-ops", "桌面操作", "看屏幕、点控件", "pet-hands")
    _skill(home, "packing-kit", "打包瘦身", "PyInstaller 清单")

    listed = pet_toolkit.skills(home=str(home))

    assert [s["name"] for s in listed] == ["打包瘦身", "桌面操作"]
    assert listed[1]["description"] == "看屏幕、点控件"
    assert listed[1]["source"] == "pet-hands"
    assert all(s["enabled"] for s in listed)


def test_skill_without_front_matter_falls_back_to_folder_name(tmp_path):
    home = _home(tmp_path)
    folder = home / ".laji" / "skills" / "raw-tool"
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text("# 没有头部\n", encoding="utf-8")

    listed = pet_toolkit.skills(home=str(home))

    assert [s["name"] for s in listed] == ["raw-tool"]
    assert listed[0]["description"] == ""


def test_skill_toggle_writes_the_shared_registry(tmp_path, _config_dir):
    home = _home(tmp_path)
    folder = _skill(home, "desktop-ops", "桌面操作", "看屏幕")

    assert pet_toolkit.set_skill_enabled("桌面操作", False, home=str(home))
    # 文件不动：引擎只认 registry 里的 enabled: false。
    assert (folder / "SKILL.md").is_file()
    registry = json.loads((_config_dir / "skills-registry.json").read_text(encoding="utf-8"))
    assert registry["overrides"]["workspace:桌面操作"]["enabled"] is False
    assert [s["enabled"] for s in pet_toolkit.skills(home=str(home))] == [False]

    assert pet_toolkit.set_skill_enabled("桌面操作", True, home=str(home))
    registry = json.loads((_config_dir / "skills-registry.json").read_text(encoding="utf-8"))
    assert "workspace:桌面操作" not in registry["overrides"]
    assert [s["enabled"] for s in pet_toolkit.skills(home=str(home))] == [True]


def test_legacy_disabled_folder_is_unburied_on_toggle(tmp_path, _config_dir):
    home = _home(tmp_path)
    folder = _skill(home, "desktop-ops", "桌面操作", "看屏幕")
    buried = folder.with_name("desktop-ops.disabled")
    folder.rename(buried)
    assert [s["enabled"] for s in pet_toolkit.skills(home=str(home))] == [False]

    assert pet_toolkit.set_skill_enabled("桌面操作", True, home=str(home))

    assert (folder / "SKILL.md").is_file()
    assert not buried.exists()


def test_skills_include_global_dir_and_pet_home_wins(tmp_path, _config_dir):
    home = _home(tmp_path)
    _skill(home, "pet-hands", "pet-hands", "她的那份")
    _agent_skill(_config_dir, "pet-hands", "pet-hands", "全局同名")
    _agent_skill(_config_dir, "fin-review", "fin-statement-review", "看财报表")

    listed = pet_toolkit.skills(home=str(home))

    assert [(s["name"], s["scope"]) for s in listed] == [
        ("fin-statement-review", "global"),
        ("pet-hands", "workspace"),
    ]
    assert listed[1]["description"] == "她的那份"


def test_global_skill_toggle_and_delete_guards(tmp_path, _config_dir):
    home = _home(tmp_path)
    folder = _agent_skill(_config_dir, "fin-review", "fin-statement-review", "看财报表")

    assert pet_toolkit.set_skill_enabled("fin-statement-review", False, home=str(home))

    registry = json.loads((_config_dir / "skills-registry.json").read_text(encoding="utf-8"))
    assert registry["overrides"]["global:fin-statement-review"]["enabled"] is False
    # 全局技能不许从宠物这边删：那是 agent 的技能页管的。
    assert not pet_toolkit.remove_skill("fin-statement-review", home=str(home))
    assert folder.is_dir()


def test_connectors_read_transport_and_disabled_flag(tmp_path):
    home = _home(tmp_path)
    _mcp(
        home,
        {
            "pet-hands": {"command": "python", "args": ["-m", "pet_hands"], "source": "pet-hands"},
            "recloud": {"url": "https://example.invalid/mcp"},
            "mail": {"url": "https://example.invalid/mail", "enabled": False},
        },
    )

    listed = pet_toolkit.connectors(home=str(home))

    assert [(c["name"], c["transport"], c["enabled"]) for c in listed] == [
        ("mail", "http", False),
        ("pet-hands", "stdio", True),
        ("recloud", "http", True),
    ]


def test_connector_toggle_writes_only_the_pet_file(tmp_path):
    home = _home(tmp_path)
    _mcp(home, {"recloud": {"url": "https://example.invalid/mcp"}})

    assert pet_toolkit.set_connector_enabled("recloud", False, home=str(home))

    payload = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))
    assert payload["mcpServers"]["recloud"]["enabled"] is False
    assert payload["mcpServers"]["recloud"]["url"] == "https://example.invalid/mcp"
    assert [c["enabled"] for c in pet_toolkit.connectors(home=str(home))] == [False]


def test_packs_count_contributions(tmp_path):
    home = _home(tmp_path)
    manifest = home / "plugins" / "pet-hands-src" / "laji.plugin.toml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        'name = "pet-hands"\nversion = "1.2.0"\n\n'
        '[[contributions.skills]]\npath = "a"\n'
        '[[contributions.skills]]\npath = "b"\n\n'
        '[[contributions.mcp]]\nname = "pet-hands"\n',
        encoding="utf-8",
    )

    listed = pet_toolkit.packs(home=str(home))

    assert [(p["name"], p["version"], p["skills"], p["mcp"]) for p in listed] == [
        ("pet-hands", "1.2.0", 2, 1)
    ]


def test_counts_reads_all_three_inventory_sources(tmp_path, _config_dir):
    home = _home(tmp_path)
    _skill(home, "desktop-ops", "桌面操作", "看屏幕")
    _skill(home, "old-one", "旧的", "已关掉").rename(home / ".laji" / "skills" / "old-one.disabled")
    _agent_custom(_config_dir, {"pet-hands": {"command": "python"}})
    (home / "plugins" / "packing").mkdir()
    (home / "plugins" / "packing" / "laji.plugin.toml").write_text('name = "packing"\n', encoding="utf-8")

    # 口径 = 各页「全部」的张数：技能页连停用的也列（2 条），工坊页 = 已装 + agent 装的。
    assert pet_toolkit.counts(home=str(home)) == {"connectors": 1, "skills": 2, "packs": 1}


def test_missing_or_broken_files_are_empty_not_errors(tmp_path):
    home = _home(tmp_path)
    (home / ".laji" / "pet-mcp.json").write_text("{oops", encoding="utf-8")

    assert pet_toolkit.skills(home=str(home)) == []
    assert pet_toolkit.connectors(home=str(home)) == []
    assert pet_toolkit.packs(home=str(home)) == []
    assert pet_toolkit.counts(home=str(home)) == {"connectors": 0, "skills": 0, "packs": 0}
    assert pet_toolkit.skills(home=str(tmp_path / "nowhere")) == []
    assert not pet_toolkit.set_connector_enabled("x", False, home=str(home))
    assert not pet_toolkit.set_skill_enabled("x", False, home=str(home))


# -- 从 agent 那边搬过来 -----------------------------------------------------


def _agent_config(base, servers):
    """写一份 ``config.toml`` 片段，形状照真实文件里的 ``[[mcp.servers]]``。"""
    lines = ["# 别的东西先来一段", "[security]", 'mode = "strict"', ""]
    for spec in servers:
        lines.append("[[mcp.servers]]")
        lines.append(f'name = "{spec["name"]}"')
        if "url" in spec:
            lines.append('transport = "http"')
            lines.append(f'url = "{spec["url"]}"')
        else:
            lines.append(f'command = "{spec["command"]}"')
            args = ", ".join(f'"{a}"' for a in spec.get("args", []))
            lines.append(f"args = [{args}]")
            env = ", ".join(f'{k} = "{v}"' for k, v in spec.get("env", {}).items())
            if env:
                lines.append(f"env = {{ {env} }}")
        lines.append("")
    lines.append("[model]")
    lines.append('name = "not-a-server"')
    base.mkdir(parents=True, exist_ok=True)
    (base / "config.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _agent_custom(base, servers):
    base.mkdir(parents=True, exist_ok=True)
    (base / "mcp-custom.json").write_text(
        json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8"
    )


def test_agent_connectors_read_both_files(tmp_path):
    base = tmp_path / "laji"
    _agent_config(
        base,
        [
            {"name": "biz", "url": "http://localhost:8888/mcp"},
            {"name": "zentao", "command": "npx", "args": ["-y", "zentao-mcp"], "env": {"TOKEN": "t"}},
        ],
    )
    _agent_custom(
        base,
        {
            "pet-hands": {"command": "python.exe", "args": ["server.py"], "env": {"A": "1"}},
            "zentao": {"command": "C:/bin/zentao.exe", "args": []},
            "off": {"url": "https://example.invalid/mcp", "disabled": True},
        },
    )

    listed = pet_toolkit.agent_connectors([str(base)])

    assert [(c["name"], c["transport"], c["enabled"]) for c in listed] == [
        ("biz", "http", True),
        ("off", "http", False),
        ("pet-hands", "stdio", True),
        ("zentao", "stdio", True),
    ]
    # 同名以 mcp-custom.json 为准；config.toml 里别的表（security/model）不能误读。
    zentao = next(c for c in listed if c["name"] == "zentao")
    assert zentao["spec"]["command"] == "C:/bin/zentao.exe"
    hands = next(c for c in listed if c["name"] == "pet-hands")
    assert hands["spec"]["args"] == ["server.py"]
    assert hands["spec"]["env"] == {"A": "1"}


def test_import_from_agent_only_fills_empty_slots(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    _agent_config(base, [{"name": "biz", "url": "http://localhost:8888/mcp"}])
    _agent_custom(
        base,
        {
            "pet-hands": {"command": "python.exe", "args": ["server.py"]},
            "biz": {"url": "http://localhost:8888/mcp"},
        },
    )
    _mcp(home, {"biz": {"url": "http://localhost:7000/mine", "enabled": False}})

    added = pet_toolkit.import_from_agent(home=str(home), dirs=[str(base)])

    assert added == 1
    payload = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))
    assert payload["mcpServers"]["biz"]["url"] == "http://localhost:7000/mine"
    assert payload["mcpServers"]["biz"]["enabled"] is False
    assert payload["mcpServers"]["pet-hands"]["source"] == pet_toolkit.IMPORTED_SOURCE
    assert [c["name"] for c in pet_toolkit.connectors(home=str(home))] == ["biz", "pet-hands"]


def test_ensure_imports_only_on_first_open(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    _agent_custom(base, {"pet-hands": {"command": "python.exe", "args": ["server.py"]}})

    assert pet_toolkit.ensure_imported_from_agent(home=str(home), dirs=[str(base)]) == 1
    # 第二次开页不再动它：用户在宠物家改了停用，不能被搬回来。
    assert pet_toolkit.set_connector_enabled("pet-hands", False, home=str(home))
    assert pet_toolkit.ensure_imported_from_agent(home=str(home), dirs=[str(base)]) == 0
    assert [c["enabled"] for c in pet_toolkit.connectors(home=str(home))] == [False]


def test_agent_side_without_mcp_is_a_noop(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    base.mkdir(parents=True)

    assert pet_toolkit.agent_connectors([str(base)]) == []
    assert pet_toolkit.import_from_agent(home=str(home), dirs=[str(base)]) == 0
    assert not (home / ".laji" / "pet-mcp.json").exists()


def test_connectors_expose_spec_for_editing(tmp_path):
    home = _home(tmp_path)
    _mcp(
        home,
        {
            "pet-hands": {"command": "python.exe", "args": ["server.py", "--stdio"]},
            "biz": {"type": "http", "url": "http://localhost:8888/mcp"},
        },
    )

    rows = {c["name"]: c for c in pet_toolkit.connectors(home=str(home))}

    assert rows["pet-hands"]["command"] == "python.exe"
    assert rows["pet-hands"]["args"] == ["server.py", "--stdio"]
    assert rows["pet-hands"]["url"] == ""
    assert rows["biz"]["url"] == "http://localhost:8888/mcp"
    assert rows["biz"]["command"] == ""


def test_save_connector_creates_and_edits_only_pet_home(tmp_path):
    home = _home(tmp_path)

    assert pet_toolkit.save_connector(
        "mine", transport="stdio", command="python.exe", args=["a.py", ""], home=str(home)
    )
    rows = pet_toolkit.connectors(home=str(home))
    assert rows[0]["command"] == "python.exe"
    assert rows[0]["args"] == ["a.py"]
    assert rows[0]["enabled"] is True

    # 同名再存就是把那一条改掉，不是多出一条。
    assert pet_toolkit.save_connector(
        "mine", transport="http", url="https://example.com/mcp", enabled=False, home=str(home)
    )
    rows = pet_toolkit.connectors(home=str(home))
    assert len(rows) == 1
    assert rows[0]["transport"] == "http"
    assert rows[0]["url"] == "https://example.com/mcp"
    assert rows[0]["enabled"] is False


def test_save_connector_rejects_empty_fields_and_keeps_source(tmp_path):
    home = _home(tmp_path)
    _mcp(home, {"biz": {"url": "http://old/mcp", "source": "agent"}})

    assert not pet_toolkit.save_connector("", command="python.exe", home=str(home))
    assert not pet_toolkit.save_connector("http-mcp", transport="http", url="  ", home=str(home))
    assert not pet_toolkit.save_connector("stdio-mcp", command="", home=str(home))

    # 改名后还是「导入时带过来的那一份」，只是地址换了。
    assert pet_toolkit.save_connector(
        "biz2",
        transport="http",
        url="http://new/mcp",
        rename_from="biz",
        home=str(home),
    )
    rows = pet_toolkit.connectors(home=str(home))
    assert [c["name"] for c in rows] == ["biz2"]
    assert rows[0]["source"] == pet_toolkit.IMPORTED_SOURCE


def test_save_skill_writes_front_matter_and_renames_folder(tmp_path):
    home = _home(tmp_path)
    folder = _skill(home, "memo", "备忘速记", "记东西")

    assert pet_toolkit.save_skill(
        "备忘速记", description="记下口头交接", body="第一步……", home=str(home)
    )
    listed = pet_toolkit.skills(home=str(home))
    assert len(listed) == 1
    assert listed[0]["description"] == "记下口头交接"
    assert pet_toolkit.skill_body(str(listed[0]["path"])) == "第一步……"

    assert pet_toolkit.save_skill(
        "口味备忘", description="记住偏好", body="不加冰", rename_from="备忘速记", home=str(home)
    )
    assert [s["name"] for s in pet_toolkit.skills(home=str(home))] == ["口味备忘"]
    assert not folder.exists()
    assert not pet_toolkit.save_skill(" ", home=str(home))


def test_remove_skill_deletes_the_folder(tmp_path):
    home = _home(tmp_path)
    folder = _skill(home, "memo", "备忘速记")

    assert pet_toolkit.remove_skill("备忘速记", home=str(home))
    assert not folder.exists()
    assert pet_toolkit.skills(home=str(home)) == []
    assert not pet_toolkit.remove_skill("没有这个", home=str(home))


def test_import_skills_from_agent_only_fills_empty_slots(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    (base / "skills").mkdir(parents=True)
    _agent_skill(base, "desktop-ops", "桌面操作", "看屏幕")
    _agent_skill(base, "memo", "备忘速记", "agent 的版本")
    _skill(home, "memo", "备忘速记", "她自己改过的版本")

    assert pet_toolkit.import_skills_from_agent(home=str(home), dirs=[str(base)]) == 1
    listed = {s["name"]: s for s in pet_toolkit.skills(home=str(home))}
    assert set(listed) == {"备忘速记", "桌面操作"}
    assert listed["备忘速记"]["description"] == "她自己改过的版本"
    # 再导一次不会多出一份。
    assert pet_toolkit.import_skills_from_agent(home=str(home), dirs=[str(base)]) == 0


def test_import_packs_from_agent_copies_version_folder(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    pack = base / "plugins" / "com.nerve.dsh-pet-hands" / "0.1.0"
    pack.mkdir(parents=True)
    (pack / "laji.plugin.toml").write_text(
        'name = "pet-hands"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    assert pet_toolkit.import_packs_from_agent(home=str(home), dirs=[str(base)]) == 1
    assert (home / "plugins" / "com.nerve.dsh-pet-hands" / "laji.plugin.toml").is_file()
    assert [p["name"] for p in pet_toolkit.packs(home=str(home))] == ["pet-hands"]
    assert pet_toolkit.import_packs_from_agent(home=str(home), dirs=[str(base)]) == 0


def test_workshop_lists_agent_packs_she_has_not_installed(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    for pack_id, name in (
        ("com.nerve.dsh-pet-hands", "伙伴的手"),
        ("com.nerve.dsh-pet", "大钚鱼桌宠"),
    ):
        pack = base / "plugins" / pack_id / "0.1.0"
        pack.mkdir(parents=True)
        (pack / "laji.plugin.toml").write_text(
            f'name = "{name}"\nversion = "0.1.0"\n', encoding="utf-8"
        )
    own = home / "plugins" / "hub.whale-widget"
    own.mkdir(parents=True)
    (own / "laji.plugin.toml").write_text('name = "小钚鱼挂件"\n', encoding="utf-8")

    listed = pet_toolkit.workshop_packs(home=str(home), dirs=[str(base)])

    by_name = {item["name"]: item for item in listed}
    assert set(by_name) == {"小钚鱼挂件", "伙伴的手"}
    assert by_name["小钚鱼挂件"]["installed"] is True
    assert by_name["伙伴的手"]["installed"] is False


def test_install_pack_copies_one_pack_into_her_plugins(tmp_path):
    home = _home(tmp_path)
    base = tmp_path / "laji"
    pack = base / "plugins" / "com.nerve.dsh-pet-hands" / "0.1.0"
    pack.mkdir(parents=True)
    (pack / "laji.plugin.toml").write_text(
        'name = "pet-hands"\nversion = "0.1.0"\n', encoding="utf-8"
    )

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])
    assert (home / "plugins" / "com.nerve.dsh-pet-hands" / "laji.plugin.toml").is_file()
    # 再装一次什么都不做；不存在的能力包也返回 False。
    assert not pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])
    assert not pet_toolkit.install_pack("没有这个包", home=str(home), dirs=[str(base)])


def test_remove_connector_leaves_other_entries_alone(tmp_path):
    home = _home(tmp_path)
    _mcp(home, {"a": {"command": "x"}, "b": {"command": "y"}})

    assert pet_toolkit.remove_connector("a", home=str(home))
    assert [c["name"] for c in pet_toolkit.connectors(home=str(home))] == ["b"]
    # 不存在的名字什么也不做，也不报错。
    assert not pet_toolkit.remove_connector("nope", home=str(home))
    assert [c["name"] for c in pet_toolkit.connectors(home=str(home))] == ["b"]


_PACK_TOML = """[plugin]
id = "com.nerve.dsh-pet-hands"
name = "伙伴的手"
version = "0.1.0"
description = "让她能操作这台电脑。"

[[contributions.skills]]
path = "skills/pet-hands/SKILL.md"

[[contributions.mcp]]
name = "pet-hands"
command = "${python}"
args = ["${plugin}/server.py"]
transport = "stdio"
env = { PYTHONUNBUFFERED = "1" }

[[contributions.workbench]]
id = "whale-widget"
skin = "whale-widget"
"""


def _source_pack(tmp_path, pack_id="com.nerve.dsh-pet-hands"):
    base = tmp_path / "laji"
    pack = base / "plugins" / pack_id / "0.1.0"
    skill = pack / "skills" / "pet-hands"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: pet-hands\ndescription: >-\n  通过真实鼠标键盘操作这台电脑。\n---\n\n# 她的手\n\n正文。\n",
        encoding="utf-8",
    )
    (pack / "laji.plugin.toml").write_text(_PACK_TOML, encoding="utf-8")
    return base, pack


def test_pack_contributions_reads_manifest_and_skill_description(tmp_path):
    _base, pack = _source_pack(tmp_path)

    rows = pet_toolkit.pack_contributions(str(pack))

    assert [(one["kind"], one["name"]) for one in rows] == [
        ("skill", "pet-hands"),
        ("mcp", "pet-hands"),
        ("skin", "whale-widget"),
    ]
    assert rows[0]["description"] == "通过真实鼠标键盘操作这台电脑。"
    assert rows[0]["ref"] == "skills/pet-hands/SKILL.md"
    # manifest 里只有 [plugin] 的包就是没贡献，不是报错。
    bare = tmp_path / "bare"
    bare.mkdir()
    (bare / "laji.plugin.toml").write_text('[plugin]\nid = "x"\n', encoding="utf-8")
    assert pet_toolkit.pack_contributions(str(bare)) == []


def test_read_contribution_previews_skill_body_and_mcp_spec(tmp_path):
    _base, pack = _source_pack(tmp_path)

    skill = pet_toolkit.read_contribution(
        str(pack), "skill", "pet-hands", "skills/pet-hands/SKILL.md"
    )
    # front matter 已经用来做标题和说明了，正文从标题开始。
    assert skill["body"].startswith("# 她的手")
    assert skill["meta"] == ["skills/pet-hands/SKILL.md"]

    spec = json.loads(pet_toolkit.read_contribution(str(pack), "mcp", "pet-hands", "")["body"])
    assert spec["command"] == "${python}"
    assert spec["args"] == [str(pack) + "/server.py"]
    assert spec["env"] == {"PYTHONUNBUFFERED": "1"}

    missing = pet_toolkit.read_contribution(str(pack), "skill", "没这个", "skills/没这个/SKILL.md")
    assert missing["body"] == ""


def test_install_pack_hands_over_the_skills_and_connectors_it_brings(tmp_path):
    home = _home(tmp_path)
    _mcp(home, {"mine": {"command": "x"}})
    base, _pack = _source_pack(tmp_path)

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    # 拷完直接能用：技能进了她自己的目录，连接器进了 pet-mcp.json 且已开。
    assert (home / ".laji" / "skills" / "pet-hands" / "SKILL.md").is_file()
    doc = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))
    spec = doc["mcpServers"]["pet-hands"]
    assert spec["enabled"] is True
    assert spec["source"] == {"kind": "plugin", "id": "com.nerve.dsh-pet-hands"}
    assert spec["args"] == [str(home / "plugins" / "com.nerve.dsh-pet-hands") + "/server.py"]
    # 用户自己配的那条不动。
    assert "mine" in doc["mcpServers"]
    assert sorted(c["name"] for c in pet_toolkit.connectors(home=str(home))) == ["mine", "pet-hands"]

    # 装第二次不重复搬，也不会把技能目录叠成第二份。
    assert not pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])
    assert sorted(p.name for p in (home / ".laji" / "skills").iterdir()) == ["pet-hands"]


def test_uninstall_pack_takes_its_skills_and_connectors_with_it(tmp_path):
    home = _home(tmp_path)
    _mcp(home, {"mine": {"command": "x"}})
    base, _pack = _source_pack(tmp_path)
    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    assert pet_toolkit.uninstall_pack("com.nerve.dsh-pet-hands", home=str(home))

    assert not (home / "plugins" / "com.nerve.dsh-pet-hands").exists()
    assert not (home / ".laji" / "skills" / "pet-hands").exists()
    assert [c["name"] for c in pet_toolkit.connectors(home=str(home))] == ["mine"]


def test_install_pack_registers_the_connector_for_the_engine(tmp_path, _config_dir):
    """引擎只读 mcp-custom.json：只写宠物家那份，她手上永远不会出现这些工具。"""
    home = _home(tmp_path)
    base, _pack = _source_pack(tmp_path)
    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    store = _config_dir / "mcp-custom.json"
    entry = json.loads(store.read_text(encoding="utf-8"))["mcpServers"]["pet-hands"]
    assert entry["source"] == {"kind": "plugin", "id": "com.nerve.dsh-pet-hands"}
    # `${python}` 必须落成真解释器，否则引擎只会得到 program not found。
    assert entry["command"] and "${" not in entry["command"]
    assert entry["args"] == [str(home / "plugins" / "com.nerve.dsh-pet-hands") + "/server.py"]
    assert entry["env"] == {"PYTHONUNBUFFERED": "1"}

    assert pet_toolkit.uninstall_pack("com.nerve.dsh-pet-hands", home=str(home))
    assert "pet-hands" not in json.loads(store.read_text(encoding="utf-8"))["mcpServers"]


def test_a_connector_someone_else_registered_is_left_alone(tmp_path, _config_dir):
    store = _config_dir / "mcp-custom.json"
    mine = {"command": "python", "args": ["x.py"]}
    store.write_text(json.dumps({"mcpServers": {"pet-hands": mine}}), encoding="utf-8")
    home = _home(tmp_path)
    base, _pack = _source_pack(tmp_path)

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])
    assert json.loads(store.read_text(encoding="utf-8"))["mcpServers"]["pet-hands"] == mine

    # 卸包也不该把它当成自己的账带走。
    assert pet_toolkit.uninstall_pack("com.nerve.dsh-pet-hands", home=str(home))
    assert json.loads(store.read_text(encoding="utf-8"))["mcpServers"]["pet-hands"] == mine


def _permissions(_config_dir) -> str:
    return (_config_dir / "config.toml").read_text(encoding="utf-8")


def _write_permissions(_config_dir, body: str) -> None:
    (_config_dir / "config.toml").write_text(body, encoding="utf-8")


CONFIG_WITH_ALLOW = """[permissions]
# >>> laji-security (managed by Laji Desktop)
network_confirm = false
network_allow_domains = ["a.com"]
# <<< laji-security
mode = "auto"
allow = ["tool:builtin:remember"]

[security]
mcp_grant = true
"""


def test_installing_a_pack_grants_its_tools_without_per_call_approval(tmp_path, _config_dir):
    """登记 server 不够：引擎默认每个外部工具都要过审批，桌宠没人点，她就永远没手。"""
    home = _home(tmp_path)
    base, _pack = _source_pack(tmp_path)
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW)

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    body = _permissions(_config_dir)
    assert '"tool:mcp:pet-hands:*"' in body
    # 原有规则、注释、后面的段落都原样留着。
    assert 'allow = ["tool:builtin:remember", "tool:mcp:pet-hands:*"]' in body
    assert "# >>> laji-security" in body and 'mcp_grant = true' in body


def test_uninstalling_a_pack_takes_its_grant_away(tmp_path, _config_dir):
    home = _home(tmp_path)
    base, _pack = _source_pack(tmp_path)
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW)
    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    assert pet_toolkit.uninstall_pack("com.nerve.dsh-pet-hands", home=str(home))

    body = _permissions(_config_dir)
    assert "tool:mcp:pet-hands:*" not in body
    assert 'allow = ["tool:builtin:remember"]' in body


def test_disabling_a_connector_drops_its_grant(tmp_path, _config_dir):
    home = _home(tmp_path)
    base, _pack = _source_pack(tmp_path)
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW)
    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    assert pet_toolkit.set_connector_enabled("pet-hands", False, home=str(home))
    assert "tool:mcp:pet-hands:*" not in _permissions(_config_dir)

    assert pet_toolkit.set_connector_enabled("pet-hands", True, home=str(home))
    assert "tool:mcp:pet-hands:*" in _permissions(_config_dir)


def test_granting_creates_the_key_when_it_is_missing(tmp_path, _config_dir):
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW.replace('allow = ["tool:builtin:remember"]\n', ""))

    assert pet_toolkit.grant_daemon_connector_tools(["pet-hands"]) == ["tool:mcp:pet-hands:*"]

    body = _permissions(_config_dir)
    assert 'allow = ["tool:mcp:pet-hands:*"]' in body
    assert body.index("allow =") < body.index("[security]")


def test_granting_twice_adds_nothing(tmp_path, _config_dir):
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW)
    assert pet_toolkit.grant_daemon_connector_tools(["pet-hands"]) == ["tool:mcp:pet-hands:*"]

    assert pet_toolkit.grant_daemon_connector_tools(["pet-hands"]) == []
    assert _permissions(_config_dir).count("tool:mcp:pet-hands:*") == 1


def test_sync_picks_up_a_connector_installed_before_grants_existed(tmp_path, _config_dir):
    """老版本的装包只写了``pet-mcp.json``（没写 source）：靠安装路径认出来补上规则。"""
    home = _home(tmp_path)
    installed = home / "plugins" / "com.nerve.dsh-pet-hands" / "0.1.0" / "server.py"
    installed.parent.mkdir(parents=True)
    installed.write_text("# server\n", encoding="utf-8")
    _mcp(
        home,
        {
            "pet-hands": {"command": "python", "args": [str(installed)]},
            "zentao": {"url": "http://127.0.0.1:8802/mcp"},
        },
    )
    _write_permissions(_config_dir, CONFIG_WITH_ALLOW)

    assert pet_toolkit.sync_daemon_connector_grants(home=str(home)) == ["tool:mcp:pet-hands:*"]

    body = _permissions(_config_dir)
    assert "tool:mcp:pet-hands:*" in body
    # 用户自己的 http 连接器不因为装了插件就被放行。
    assert "tool:mcp:zentao:*" not in body
    assert pet_toolkit.sync_daemon_connector_grants(home=str(home)) == []


def test_json_edit_keeps_passthrough_fields(tmp_path, monkeypatch):
    """编辑框只改该改的：headers / disabled_tools 这类透传字段一个都不能丢。"""
    home = _home(tmp_path)
    monkeypatch.setattr(pet_toolkit, "grant_daemon_connector_tools", lambda names: list(names))
    monkeypatch.setattr(pet_toolkit, "revoke_daemon_connector_tools", lambda names: list(names))
    _mcp(
        home,
        {
            "pet-hands": {
                "command": "python.exe",
                "args": ["server.py"],
                "headers": {"A": "1"},
                "disabled_tools": ["mcp__pet-hands__raw"],
            }
        },
    )

    assert pet_toolkit.save_connector_entry(
        "pet-hands",
        {
            "command": "python.exe",
            "args": ["server2.py"],
            "headers": {"A": "1"},
            "disabled_tools": ["mcp__pet-hands__raw"],
        },
        home=str(home),
    )

    kept = pet_toolkit.connector_entry("pet-hands", home=str(home))
    assert kept["args"] == ["server2.py"]
    assert kept["headers"] == {"A": "1"}
    assert kept["disabled_tools"] == ["mcp__pet-hands__raw"]


def test_json_edit_rejects_bad_shape(tmp_path):
    home = _home(tmp_path)
    assert not pet_toolkit.save_connector_entry("bad name", {"url": "u"}, home=str(home))
    assert not pet_toolkit.save_connector_entry("ok", {}, home=str(home))
    assert not pet_toolkit.save_connector_entry("ok", {"args": []}, home=str(home))
    assert pet_toolkit.connector_entry("也没写", home=str(home)) == {}


def test_json_edit_carries_plugin_source_across_rename(tmp_path, monkeypatch):
    """改了名字，插件来源也得跟着 —— 否则卸载包时认不出这条是谁装的。"""
    home = _home(tmp_path)
    monkeypatch.setattr(pet_toolkit, "grant_daemon_connector_tools", lambda names: list(names))
    _mcp(
        home,
        {
            "pet-hands": {
                "command": "p",
                "source": {"kind": "plugin", "id": "com.nerve.dsh-pet-hands"},
            }
        },
    )

    assert pet_toolkit.save_connector_entry(
        "hands", {"command": "p2"}, rename_from="pet-hands", home=str(home)
    )

    table = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert table["hands"]["source"]["id"] == "com.nerve.dsh-pet-hands"
    assert "pet-hands" not in table


def test_json_edit_disabled_revokes_grant(tmp_path, monkeypatch):
    home = _home(tmp_path)
    revoked: list[str] = []
    monkeypatch.setattr(
        pet_toolkit, "revoke_daemon_connector_tools", lambda names: revoked.extend(names)
    )
    monkeypatch.setattr(pet_toolkit, "grant_daemon_connector_tools", lambda names: [])

    assert pet_toolkit.save_connector_entry("x", {"url": "u", "disabled": True}, home=str(home))

    assert revoked == ["x"]


def test_manifest_env_placeholder_does_not_truncate_the_table(tmp_path, monkeypatch):
    """env 值里的 ``${APPDATA}`` 不能被当成 inline table 的结尾。"""
    monkeypatch.setenv("APPDATA", r"C:\Users\someone\AppData\Roaming")
    home = _home(tmp_path)
    _mcp(home, {})
    base, pack = _source_pack(tmp_path)
    (pack / "laji.plugin.toml").write_text(
        _PACK_TOML.replace(
            'env = { PYTHONUNBUFFERED = "1" }',
            'env = { PYTHONUNBUFFERED = "1", '
            'PET_HANDS_SHOT_DIR = "${APPDATA}/Laji Agent/Pet/shenshen/.laji/shots" }',
        ),
        encoding="utf-8",
    )

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    entry = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))[
        "mcpServers"
    ]["pet-hands"]
    shots = entry["env"]["PET_HANDS_SHOT_DIR"]
    # 表没被截断：三条都在，且目录占位符已经落成真路径。
    assert entry["env"]["PYTHONUNBUFFERED"] == "1"
    assert shots.startswith("C:\\Users\\someone\\AppData\\Roaming"), shots
    assert shots.endswith(r"Laji Agent\Pet\shenshen\.laji\shots"), shots


def test_connector_is_not_registered_when_python_is_missing(tmp_path, monkeypatch):
    """找不到解释器就不登记：字面量 ``${python}`` 只会换来 program not found。"""
    monkeypatch.setattr(pet_toolkit, "_python_exe", lambda: "")
    home = _home(tmp_path)
    _mcp(home, {})
    base, _pack = _source_pack(tmp_path)

    assert pet_toolkit.install_pack("com.nerve.dsh-pet-hands", home=str(home), dirs=[str(base)])

    table = json.loads((home / ".laji" / "pet-mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert "pet-hands" not in table

