"""从一句话里认出「打开某个东西」，并挡掉三种不该动手的句子。

只做**本地规则**，不调模型。三个理由：

1. 零延迟——话说完她就能起步，不用等一轮 LT；
2. 不幻觉——模型偶尔会把"打开了吗"当成指令，规则不会；
3. 离线可用——用户没配 Key 时这段照样生效。

代价是覆盖面有限（只说"豆包在哪"不会动手），所以规则刻意保守：**只认动词 +
宾语都很明确的句子**，宁可漏，不可错——桌宠擅自弹开始菜单比不弹更烦人。
"""
from __future__ import annotations

import re
import unicodedata

#: 动词。长的放前面，正则交替按顺序匹配。
_VERBS = ("打开", "启动", "运行", "开一下", "帮我开", "给我开", "开开")

_POST = re.compile(r"(?:打开|启动|运行|开一下|帮我开|给我开|开开)(?:一下|下|个)?\s*(.+)")
_PRE = re.compile(r"(?:把|将)\s*(.+?)\s*(?:打开|启动|运行|开一下|开开)")

#: 出现在动词前就说明"这不是命令"的词。
_QUESTION = ("怎么", "如何", "怎样", "为什么", "为啥", "哪里", "哪儿",
             "能不能", "可不可以", "会不会", "要不要", "是不是", "是不是")
_NEGATIVE = ("别", "不要", "不用", "甭", "没必要", "先不", "不")

#: 宾语里要剥掉的尾巴/客套。
_TAIL = re.compile(r"[。！？!?，,、\s]+$|(?:吧|呢|啊|呗|嘛|好吗|可以吗|谢谢|一下)+$")
_HEAD = re.compile(r"^(?:请|帮我|给我|麻烦|你|能不能|可以)+")

_MAX_LEN = 24


def _normalize(text: str) -> str:
    # 全角字母数字 → 半角（"Ｄ盘" 这种），保留中文
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    return normalized.replace("\u3000", " ").strip()


def _is_question(text: str, verb_at: int) -> bool:
    """动词前 4 个字里出现疑问词 = 在问，不是在下命令。"""
    head = text[max(0, verb_at - 4):verb_at]
    return any(q in head for q in _QUESTION)


def _is_negative(text: str, verb_at: int) -> bool:
    head = text[max(0, verb_at - 3):verb_at]
    return any(n in head for n in _NEGATIVE)


def _clean(target: str) -> str:
    t = _HEAD.sub("", target.strip())
    prev = None
    while t != prev:                 # 尾巴可能叠压（"一下吧"）
        prev = t
        t = _TAIL.sub("", t).strip()
    return t[:_MAX_LEN]


def parse(text: str) -> str | None:
    """返回要打开的目标名/路径；不是在叫她动手就返回 ``None``。

    认三种句式：「打开 X」「帮我开一下 X」「把 X 打开」。
    """
    raw = _normalize(text)
    if not raw or len(raw) > 120:
        return None
    # 句尾一个「吗」就翻案：「打开豆包了吗」「你能打开豆包吗」都是问句。
    # 只认「吗」——「嘛」多是撒娇（「帮我打开嘛」），那是真命令。
    if re.sub(r"[。！？!?，,\s]+$", "", raw).endswith("吗"):
        return None

    for pattern in (_POST, _PRE):
        for match in pattern.finditer(raw):
            verb_at = match.start()
            if _is_question(raw, verb_at) or _is_negative(raw, verb_at):
                continue
            target = _clean(match.group(1))
            if target and target not in _VERBS:
                return target
    return None
