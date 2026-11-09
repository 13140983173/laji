"""工作台设置 → 模型页：照拄 agent 视图的做法（工具行 + 云端/本地分组 + 开关 + 删除）

锁定六件事：清单能反映每个模型的可用状态、页面上没有任何"选哪个"的控件
（用哪个由 ``ChatSettings.auto_pick`` 每轮自动挑）、自动路由的挑选规则、
开关与删除真能落盘、「添加模型」对话框能写出一个完整 provider、
以及这页绝不碰 agent 视图那两份配置（``User/settings.json`` / ``config.toml``）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QCheckBox,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QWidget,
)

from pet.chat.models import ChatSettings, ProviderConfig  # noqa: E402
from pet.config import Config  # noqa: E402
from pet.workstation_window import (  # noqa: E402
    _AddModelDialog,
    _WsChatModelPage,
    _WsSettingsDialog,
    _WsSwitch,
)


@pytest.fixture(autouse=True)
def _isolate_engine_config(tmp_path, monkeypatch):
    """模型页保存会顺带把桌宠清单镜像进引擎配置。

    这条镜像不能写真实的 ``%LOCALAPPDATA%\\laji\\config.toml``，也不该去连本机
    daemon（测试机和开发机可能正跑着一个）——两条都在这里换成临时路径 / 不可用。
    """
    from pet.agent_link import daemon_client
    from pet.chat import engine_profiles

    target = tmp_path / "engine.toml"
    monkeypatch.setattr(engine_profiles, "engine_config_path", lambda: target)
    monkeypatch.setattr(daemon_client, "AVAILABLE", False)
    return target


def _config_with_three(tmp_path) -> Config:
    config = Config(base=str(tmp_path / "home"))
    config.resolve_api_key = lambda provider: ""  # 不碰 keyring
    settings = ChatSettings.defaults()
    settings.providers = {
        "openai-main": ProviderConfig("openai-main", name="DeepSeek 官方", model="deepseek-v4-flash"),
        "api-2": ProviderConfig(
            "api-2",
            name="本地 Ollama",
            base_url="http://127.0.0.1:11434/v1",
            model="qwen3:8b",
        ),
        "api-3": ProviderConfig("api-3", name="备用网关", model="glm-4.6"),
    }
    settings.active_provider = "openai-main"
    config.set_chat_settings(settings)
    assert config.save()
    return config


def _page(config, refreshed: list) -> _WsChatModelPage:
    QApplication.instance() or QApplication([])
    return _WsChatModelPage(config, refresh_chat=lambda: refreshed.append(1))


def _dialog(config, pet_hook=None, pet_attr="on_open_chat_settings"):
    """小工位设置弹窗；win 用真 QWidget，owner 用短路桩。"""
    pet_window = SimpleNamespace(**({pet_attr: pet_hook} if pet_hook else {}))
    owner = SimpleNamespace(config=config, settings=None, pet_window=pet_window)
    win = QWidget()
    win.owner = owner
    return _WsSettingsDialog(win), owner


def _row_texts(page) -> list[str]:
    return [label.text() for label in page.findChildren(QLabel) if label.objectName() == "SetRowName"]


def _pill_texts(page) -> list[str]:
    return [label.text() for label in page.findChildren(QLabel) if label.objectName() == "SetBadge"]


# ---------------------------------------------------------------- 清单


def test_lists_every_provider_grouped_by_endpoint(tmp_path):
    config = _config_with_three(tmp_path)
    page = _page(config, [])

    # 云端一组、本地一组：和 agent 视图的 cloudGroup / localGroup 同构
    assert _row_texts(page) == ["DeepSeek 官方", "备用网关", "本地 Ollama"]
    groups = [label.text() for label in page.findChildren(QLabel) if label.objectName() == "SetGroup"]
    assert groups == ["云端", "本地"]
    # 本地地址不需要 key，排第一能用的，所以它是"在用"；其余没 key 就是缺 Key
    assert _pill_texts(page) == ["缺 Key", "缺 Key", "在用"]


def test_page_toolbar_matches_agent_view(tmp_path):
    """用哪个不用选：工具行只有「刷新」+「+ 添加模型」，每行多一个「删除」。"""
    config = _config_with_three(tmp_path)
    page = _page(config, [])

    assert page.findChildren(QRadioButton) == []
    buttons = [b.text() for b in page.findChildren(QPushButton)]
    assert buttons == ["刷新", "+ 添加模型", "删除", "删除", "删除"]


def test_does_not_touch_agent_settings(tmp_path):
    config = _config_with_three(tmp_path)
    page = _page(config, [])

    assert not list(tmp_path.rglob("settings.json")), "写了 agent 视图的 User/settings.json"
    assert not list(tmp_path.rglob("config.toml")), "写了引擎的 config.toml"


# ---------------------------------------------------------------- 自动挑选


def test_auto_route_is_on_by_default():
    assert ChatSettings.from_dict({}).auto_route is True
    assert ChatSettings.from_dict({"auto_route": False}).auto_route is False


def test_auto_picks_first_usable_provider(tmp_path):
    config = _config_with_three(tmp_path)
    settings = config.chat_settings()
    assert settings.auto_pick() == ("api-2", settings.providers["api-2"]), "本地地址算可用"
    assert settings.active_config.provider_id == "api-2", "没手动选的时候自动就该生效"


def test_auto_falls_back_to_manual_when_nothing_usable(tmp_path):
    config = _config_with_three(tmp_path)
    settings = config.chat_settings()
    settings.providers["api-2"].base_url = "https://api.example.com/v1"
    assert settings.auto_pick() is None
    assert settings.active_config.provider_id == "openai-main", "全不可用时退回 active_provider"


def test_key_snapshot_makes_remote_provider_usable(tmp_path):
    config = _config_with_three(tmp_path)
    config.data["chat"]["providers"]["api-3"]["api_key"] = "sk-plain"
    settings = config.chat_settings()
    assert settings.key_ready == frozenset({"api-3"})
    settings.providers["api-2"].base_url = "https://api.example.com/v1"
    assert settings.active_config.provider_id == "api-3"


def test_manual_route_does_not_touch_keychain(tmp_path):
    config = _config_with_three(tmp_path)
    config.data["chat"]["auto_route"] = False
    reads: list = []
    config.resolve_api_key = lambda provider: reads.append(provider.provider_id) or ""

    settings = config.chat_settings()
    assert reads == [], "关掉自动就不用探钥匙串"
    assert settings.key_ready == frozenset()
    assert settings.active_config.provider_id == "openai-main"


def test_local_endpoint_detection():
    assert ChatSettings.is_local_endpoint("http://127.0.0.1:11434/v1")
    assert ChatSettings.is_local_endpoint("http://localhost:1234/v1")
    assert ChatSettings.is_local_endpoint("http://[::1]:8080/v1")
    assert not ChatSettings.is_local_endpoint("https://api.deepseek.com")
    assert not ChatSettings.is_local_endpoint("")


# ---------------------------------------------------------------- 设置弹窗


def test_settings_dialog_has_two_pages_with_model_page(tmp_path):
    config = _config_with_three(tmp_path)
    dialog, _owner = _dialog(config)

    assert dialog.pages.count() == 2, "设置里应当是 外观 / 模型 两页"
    assert dialog.pages.widget(1) is dialog.model_page
    assert _row_texts(dialog.model_page) == ["DeepSeek 官方", "备用网关", "本地 Ollama"]


def test_new_model_button_reaches_pet_window_hook(tmp_path):
    config = _config_with_three(tmp_path)
    calls: list = []
    dialog, _owner = _dialog(config, pet_hook=lambda: calls.append(1))

    assert dialog._open_chat_model_settings() is True
    QApplication.processEvents()
    assert calls == [1], "没走 pet_window 上的 AI 设置入口"


def test_new_model_button_falls_back_to_own_dialog(tmp_path):
    """owner 那边没接回调时不能"点了没反应"：自己开一个 AI 设置。"""
    config = _config_with_three(tmp_path)
    dialog, _owner = _dialog(config)  # pet_window 上没有 on_open_chat_settings

    assert dialog._open_chat_model_settings() is True
    created = dialog._chat_settings_dialog
    assert created is not None
    assert created.windowTitle() == "AI 对话设置"
    created.close()
    QApplication.processEvents()


def test_refresh_reloads_chat_window_settings(tmp_path):
    config = _config_with_three(tmp_path)
    dialog, owner = _dialog(config)
    assert owner.settings is None

    dialog._refresh_chat_consumers()
    assert owner.settings is not None
    assert owner.settings.active_provider == "openai-main"
    assert owner.settings.auto_route is True


# ---------------------------------------------------------------- 开关 / 删除


def test_switch_disables_provider_and_persists(tmp_path):
    config = _config_with_three(tmp_path)
    page = _page(config, [])   # 行序：云端…、云端…、本地

    boxes = page.findChildren(_WsSwitch)
    assert [box.isChecked() for box in boxes] == [True, True, True]
    boxes[2].setChecked(False)  # 停用本地 Ollama

    assert config.chat_settings().providers["api-2"].enabled is False
    on_disk = json.loads(next(tmp_path.rglob("config.json")).read_text(encoding="utf-8"))
    assert on_disk["chat"]["providers"]["api-2"]["enabled"] is False, "没落盘"
    # 停用后卡片只留开关，不再挂一个「已停用」徽标：能用的只剩停用那个，
    # 自动模式回退到 active_provider（openai-main）
    assert _pill_texts(page) == ["在用", "缺 Key"]


def test_disabled_provider_is_skipped_by_auto_pick(tmp_path):
    config = _config_with_three(tmp_path)
    settings = config.chat_settings()
    assert settings.auto_pick()[0] == "api-2"
    settings.providers["api-2"].enabled = False
    config.set_chat_settings(settings)
    assert config.chat_settings().auto_pick() is None, "停用的还被挑中了"


def test_delete_removes_provider(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    page = _page(config, [])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )

    page._delete("api-3")

    assert set(config.chat_settings().providers) == {"openai-main", "api-2"}
    assert _row_texts(page) == ["DeepSeek 官方", "本地 Ollama"]


def test_delete_kept_when_user_cancels(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    page = _page(config, [])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: QMessageBox.StandardButton.No,
    )

    page._delete("api-3")

    assert "api-3" in config.chat_settings().providers


def test_delete_active_provider_moves_active_pointer(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    page = _page(config, [])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *a, **k: QMessageBox.StandardButton.Yes,
    )

    page._delete("openai-main")

    settings = config.chat_settings()
    assert settings.active_provider and settings.active_provider != "openai-main"


# ---------------------------------------------------------------- 添加模型


def _add_dialog(config) -> _AddModelDialog:
    QApplication.instance() or QApplication([])
    return _AddModelDialog(config, None)


def test_add_dialog_prefills_preset(tmp_path):
    config = _config_with_three(tmp_path)
    dialog = _add_dialog(config)

    assert dialog._preset.currentData() == "deepseek"
    assert dialog._endpoint.text() == "https://api.deepseek.com/v1"
    assert dialog._endpoint.isReadOnly(), "预设端点不应该被改"
    assert dialog._model.currentText() == "deepseek-v4-flash"
    assert [dialog._model.itemText(i) for i in range(dialog._model.count())] == [
        "deepseek-v4-flash",
        "deepseek-v4-pro",
    ], "Model ID 应该带建议"
    dialog.close()


def test_add_dialog_offers_opencode_preset(tmp_path):
    """OpenCode Go 是订阅网关：端点填对就行，session 头由 providers 按 host 自动补。"""
    config = _config_with_three(tmp_path)
    dialog = _add_dialog(config)
    labels = [dialog._preset.itemData(i) for i in range(dialog._preset.count())]
    assert "opencode" in labels

    dialog._preset.setCurrentIndex(labels.index("opencode"))
    assert dialog._endpoint.text() == "https://opencode.ai/zen/go/v1"
    assert dialog._model.currentText() == "deepseek-v4.1-flash"
    assert "kimi-k3.1-pro" in [dialog._model.itemText(i) for i in range(dialog._model.count())]
    dialog.close()


def test_add_dialog_custom_preset_makes_endpoint_editable(tmp_path):
    config = _config_with_three(tmp_path)
    dialog = _add_dialog(config)

    dialog._preset.setCurrentIndex(dialog._preset.count() - 1)  # 自定义
    assert not dialog._endpoint.isReadOnly()
    assert dialog._model.currentText() == ""
    dialog.close()


def test_add_dialog_saves_provider_with_key(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    stored: list = []
    monkeypatch.setattr(
        "pet.chat.models.SecretStore.set",
        lambda self, ref, value: stored.append((ref, value)) is None or True,
    )
    dialog = _add_dialog(config)

    dialog._name.setText("我的 DeepSeek")
    dialog._key.setText("sk-test-123")
    dialog._submit()

    pid = dialog.saved_provider_id
    assert pid == "deepseek"
    provider = config.chat_settings().providers[pid]
    assert provider.name == "我的 DeepSeek"
    assert provider.model == "deepseek-v4-flash"
    assert provider.base_url == "https://api.deepseek.com/v1"
    assert provider.enabled is True
    assert stored == [(f"provider/{pid}", "sk-test-123")], "Key 应该进钥匙串"
    body = next(tmp_path.rglob("config.json")).read_text(encoding="utf-8")
    assert "sk-test-123" not in body, "Key 不能明文落盘"


def test_add_dialog_avoids_id_collision(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    monkeypatch.setattr("pet.chat.models.SecretStore.set", lambda self, ref, value: True)
    first = _add_dialog(config)
    first._submit()
    second = _add_dialog(config)
    second._submit()

    assert (first.saved_provider_id, second.saved_provider_id) == ("deepseek", "deepseek-2")


def test_add_dialog_refuses_empty_model_id(tmp_path):
    config = _config_with_three(tmp_path)
    dialog = _add_dialog(config)
    before = dict(config.chat_settings().providers)

    dialog._preset.setCurrentIndex(dialog._preset.count() - 1)  # 自定义，Model ID 空
    dialog._submit()

    assert dialog.saved_provider_id is None
    assert dict(config.chat_settings().providers) == before
    assert "Model ID" in dialog._result.text()
    dialog.close()


def test_add_dialog_test_button_asks_for_missing_key(tmp_path):
    config = _config_with_three(tmp_path)
    dialog = _add_dialog(config)

    dialog._run_test()  # 远端预设 + 空 key：不发请求，直接提示

    assert dialog._test_thread is None
    assert "API Key" in dialog._result.text()
    dialog.close()


# ---------------------------------------------------------------- 引擎镜像


def test_save_mirrors_pet_models_into_engine_config(tmp_path, _isolate_engine_config):
    """保存后桌宠清单要能被引擎读到：只写自己的 managed block，名字带 pet- 前缀。"""
    config = _config_with_three(tmp_path)
    page = _page(config, [])

    boxes = page.findChildren(_WsSwitch)
    boxes[0].setChecked(False)  # 任一次保存都该带上完整清单

    text = _isolate_engine_config.read_text(encoding="utf-8")
    assert "# >>> laji-pet-model-profiles" in text
    assert 'name = "pet-openai-main"' in text
    assert 'model_id = "deepseek-v4-flash"' in text
    assert 'name = "pet-api-3"' in text, "停用的模型也留在镜像里，引擎按名字点名"
    assert "\n[model.routing" not in text, "绝不写 agent 视图的路由"


def test_mirror_keeps_agent_profiles_untouched(tmp_path, _isolate_engine_config):
    agent = '\n'.join(
        [
            "# laji-config-version = 1",
            "",
            "# >>> laji-model-profiles (managed by Laji Desktop)",
            "[[model.profiles]]",
            'name = "deepseek-deepseek-chat"',
            'provider = "openai_compatible"',
            'model_id = "deepseek-chat"',
            "# <<< laji-model-profiles",
            "",
            "[model.routing]",
            'default = "deepseek"',
        ]
    )
    _isolate_engine_config.write_text(agent, encoding="utf-8")
    config = _config_with_three(tmp_path)
    page = _page(config, [])

    page.findChildren(_WsSwitch)[0].setChecked(False)

    text = _isolate_engine_config.read_text(encoding="utf-8")
    assert text.startswith("# laji-config-version = 1"), "agent 的开头被改了"
    assert 'name = "deepseek-deepseek-chat"' in text
    assert '[model.routing]' in text and 'default = "deepseek"' in text, "agent 路由被改了"
    assert text.index("laji-model-profiles") < text.index("laji-pet-model-profiles")


# ---------------------------------------------------------------- 档位


def test_add_dialog_defaults_to_standard_tier(tmp_path):
    dialog = _add_dialog(_config_with_three(tmp_path))

    assert [dialog._tier.itemData(i) for i in range(dialog._tier.count())] == [
        "standard",
        "fast",
    ]
    assert dialog._tier.currentData() == "standard", "默认不该抢快档"
    dialog.close()


def test_add_dialog_saves_fast_tier(tmp_path, monkeypatch):
    config = _config_with_three(tmp_path)
    monkeypatch.setattr("pet.chat.models.SecretStore.set", lambda self, ref, value: True)
    dialog = _add_dialog(config)

    dialog._key.setText("sk-test-123")
    dialog._tier.setCurrentIndex(dialog._tier.findData("fast"))
    dialog._submit()

    provider = config.chat_settings().providers[dialog.saved_provider_id]
    assert provider.tier == "fast"
    body = next(tmp_path.rglob("config.json")).read_text(encoding="utf-8")
    assert '"tier": "fast"' in body, "档位要落盘，重启后还在"


def test_card_marks_fast_tier(tmp_path):
    config = _config_with_three(tmp_path)
    page = _page(config, [])
    provider = config.chat_settings().providers["openai-main"]
    provider.tier = "fast"

    texts = [label.text() for label in page._provider_row("openai-main", provider).findChildren(QLabel)]

    assert any(text.startswith("快档") for text in texts), "卡片上要能看出这是快档模型"

