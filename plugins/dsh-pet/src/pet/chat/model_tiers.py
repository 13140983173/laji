"""一句话问答分流：这一轮该走「快档」还是「标准档」模型。

判定口径直接复刻引擎的 Tier-1 规则意图（`crates/laji-intent/src/rules.rs`）：纯算术、
「别用工具」、「怎么选/对比」算闲聊；带文件后缀或工程动词的算正经任务。桌宠只取规则层，
不跟引擎的 LLM refine —— 那一层要多一次模型往返，比直接答还慢。

引擎没有「先问意图再选模型」的入口：意图是在 run 内部 0.02s 产出的，那时
`CreateRun` 早已带着 profile 走了（见 `model_routing.rs` 的 `route_turn`：手动 profile
优先级最高）。所以桌宠按同一套规则自己判，判歪了最多多花一次快档的钱。
"""

from __future__ import annotations

TIERS = ("standard", "fast")
TIER_LABELS = {"standard": "标准档", "fast": "快档"}

# 实现类 / 读仓库类关键词（对齐 laji-intent 的 CODE_TASK_NEEDLES）
CODE_TASK_NEEDLES = (
    "写", "修", "改", "实现", "添加", "导出", "功能", "接口", "bug", "fix", "implement",
    "add", "export", "create", "refactor", "write", "patch", "开发", "编码", "grep",
    "搜索", "codebase", "read_file", "apply_patch", "controller", "service", "migration",
    "测试", "test", "lint", "build", "cargo", "npm",
)

# 通用/off-repo 口语模式
GENERAL_PATTERNS = (
    "天气", "weather", "气温", "下雨", "翻译", "translate", "什么意思", "是什么",
    "who is", "what is", "how is the weather", "今天怎么样", "明天呢", "hello",
    "你好", "谢谢", "thanks",
)

NO_TOOLS_PATTERNS = (
    "不要调用工具", "不要工具", "别调用工具", "不用工具", "无需工具",
    "don't use tools", "do not use tools", "no tools",
)

CONSULT_PATTERNS = (
    "怎么选", "如何选择", "选哪个", "哪个好", "区别", "对比", "选型",
    " compare ", "comparison", "which one", "difference between", " vs ", " versus ",
)

FILE_SUFFIXES = (
    ".tsx", ".ts", ".jsx", ".js", ".rs", ".go", ".java", ".py", ".md", ".json",
    ".yaml", ".yml", ".toml", ".css", ".html", ".vue", ".sql",
)

# 超过这个长度就不算「一句话问答」：用户显然在交代一件事，别拿快档赌
FAST_TURN_MAX_CHARS = 48

_TRIM_TAIL = "?？.。=＝"
_TOKEN_TRIM = "`'\"()（），。；;,"


def normalize_tier(value) -> str:
    """档位名容错：老配置没这个键、或被手改成乱七八糟的值，一律回落到标准档。"""
    text = str(value or "").strip().lower()
    return text if text in TIERS else "standard"


def _is_pure_arithmetic(prompt: str) -> bool:
    text = prompt.strip().rstrip(_TRIM_TAIL).strip()
    if not text or len(text) > 64:
        return False
    for ch in text:
        if ch.isascii() and (ch.isdigit() or ch in "+-*/%(). ="):
            continue
        if ch in "＋－×÷＝":
            continue
        return False
    return any(ch.isascii() and ch.isdigit() for ch in text)


def _has_code_task(prompt: str) -> bool:
    lower = prompt.lower()
    return any(needle in lower for needle in CODE_TASK_NEEDLES)


def _has_file_reference(prompt: str) -> bool:
    for token in prompt.split():
        cleaned = token.strip(_TOKEN_TRIM)
        if any(cleaned.endswith(suffix) for suffix in FILE_SUFFIXES):
            return True
    return False


def is_fast_turn(prompt: str, *, has_attachments: bool = False) -> bool:
    """这一轮是不是「一句话问答」。

    带附件一定是正经任务（读文件/看图），不参与分流 —— 附件走快档模型很容易答歪。
    """
    text = str(prompt or "").strip()
    if not text or has_attachments:
        return False
    if _is_pure_arithmetic(text):
        return True
    lower = text.lower()
    if any(pattern in lower for pattern in NO_TOOLS_PATTERNS):
        return True
    if any(pattern in f" {lower} " for pattern in CONSULT_PATTERNS):
        return True
    if _has_file_reference(text) or _has_code_task(text):
        return False
    if any(pattern in lower for pattern in GENERAL_PATTERNS):
        return True
    return len(text) <= FAST_TURN_MAX_CHARS and "/" not in text


def pick_fast(providers, prompt: str, *, usable=None, has_attachments: bool = False):
    """从快档模型里挑一个接这轮问答；判成正经任务或没有可用快档时返回 None。

    `usable(provider_id)` 交付调用方判断「现在真能发请求」（本地端点或 Key 已就位）。
    一个都不能用就退回标准档：宁可慢，也不要弹一句「先去配 Key」打断闲聊。
    """
    if not is_fast_turn(prompt, has_attachments=has_attachments):
        return None
    pool = [
        provider
        for provider in providers or ()
        if normalize_tier(getattr(provider, "tier", "")) == "fast"
        and getattr(provider, "enabled", True)
        and str(getattr(provider, "model", "") or "").strip()
    ]
    if not pool:
        return None
    if usable is None:
        return pool[0]
    for provider in pool:
        try:
            if usable(provider.provider_id):
                return provider
        except Exception:  # noqa: BLE001 - 判据坏掉不该拖垮发送
            continue
    return None
