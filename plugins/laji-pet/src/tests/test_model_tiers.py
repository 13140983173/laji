"""一句话问答分流：意图判定与 provider 选择（见 chat/model_tiers.py）。"""

from pet.chat.models import ChatSettings, ProviderConfig
from pet.chat.model_tiers import is_fast_turn, normalize_tier, pick_fast


def _provider(pid: str, tier: str = "standard", api_key: str = "k") -> ProviderConfig:
    return ProviderConfig(
        provider_id=pid,
        name=pid,
        base_url="https://api.example.com",
        model="m-x",
        api_key=api_key,
        tier=tier,
    )


def _settings(*, fast: bool = True, auto_route: bool = True, fast_key: str = "k") -> ChatSettings:
    providers = {"main": _provider("main")}
    if fast:
        providers["fasty"] = _provider("fasty", "fast", fast_key)
    settings = ChatSettings(providers=providers, active_provider="main", auto_route=auto_route)
    settings.key_ready = frozenset(pid for pid, p in providers.items() if p.api_key)
    return settings


def test_normalize_tier_falls_back_to_standard():
    assert normalize_tier("fast") == "fast"
    assert normalize_tier(" FAST ") == "fast"
    assert normalize_tier("") == "standard"
    assert normalize_tier("turbo") == "standard"


def test_tier_survives_roundtrip():
    provider = _provider("fasty", "fast")
    restored = ProviderConfig.from_dict("fasty", provider.to_dict())
    assert restored.tier == "fast"
    # 老配置文件里没有 tier 键，读出来就是标准档，不会意外抢快档
    legacy = {k: v for k, v in provider.to_dict().items() if k != "tier"}
    assert ProviderConfig.from_dict("fasty", legacy).tier == "standard"


def test_short_question_is_fast_turn():
    assert is_fast_turn("1+1=?")
    assert is_fast_turn("你好呀")
    assert is_fast_turn("Rust 和 Go 怎么选？")
    assert is_fast_turn("今天天气怎么样")


def test_task_is_not_fast_turn():
    assert not is_fast_turn("把 src/main.py 里的 bug 修一下")
    assert not is_fast_turn("给设置页加一个导出按钮，按现在的卡片样式来写")
    assert not is_fast_turn("")
    assert not is_fast_turn("你好", has_attachments=True)


def test_long_sentence_is_not_fast_turn():
    prompt = "我想问一下关于这个问题的详细说明" * 4
    assert not is_fast_turn(prompt)


def test_route_config_uses_fast_model_for_small_talk():
    settings = _settings()
    assert settings.route_config("你好").provider_id == "fasty"
    assert settings.route_config("1+1=?").provider_id == "fasty"


def test_route_config_keeps_active_model_for_real_work():
    settings = _settings()
    assert settings.route_config("把 src/main.py 的报错修掉").provider_id == "main"


def test_route_config_respects_manual_choice():
    settings = _settings(auto_route=False)
    assert settings.route_config("你好").provider_id == "main"


def test_route_config_without_fast_model_uses_active():
    settings = _settings(fast=False)
    assert settings.route_config("你好").provider_id == "main"


def test_fast_model_without_key_is_skipped():
    settings = _settings(fast_key="")
    assert pick_fast(settings.providers.values(), "你好", usable=settings.usable_for_request) is None
    assert settings.route_config("你好").provider_id == "main"


def test_pick_fast_needs_enabled_model():
    provider = _provider("fasty", "fast")
    provider.enabled = False
    assert pick_fast([provider], "你好") is None
    provider.enabled = True
    provider.model = "  "
    assert pick_fast([provider], "你好") is None
