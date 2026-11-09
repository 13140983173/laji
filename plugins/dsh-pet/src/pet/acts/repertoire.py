# -*- coding: utf-8 -*-
"""剧目表：把"当前角色包能播的素材名"变成「模型能念、系统能解析」的一层。

三件事，缺一不可：

1. **可播集合是唯一事实来源**。角色包换了，素材名和数量都变（内置包 40+ 段，
   第三方包可能只有十来段）。所以这里从不拿 ``catalog.ANIM_FILES`` 当清单，只吃
   调用方给的**当前库可播名字**——名字不存在就绝不给出，否则 ``play_once`` 的
   入口守卫会当场失败、留一段"假 ACTS"（``work_choreo`` 已经踩过这一坑）。

2. **解析只认可播集合**。模型说的可能是短名（``写代码``）、触发词（``晚饭``）、
   半个素材名（``傲娇生气``）甚至一句描述（``有点困``）。一律先收敛成当前库里
   真实存在的素材名；收敛不到就宁可不演，绝不硬播。

3. **给模型的清单要短**。分类分行、只列短名：45 段素材约 250 字，每轮都能放进
   系统提示；素材全名动辄十几个字，既贵又容易被模型改写。

本模块不依赖 Qt，也不读配置——它只接受一个名字集合，纯函数式，好测。
"""
from __future__ import annotations

import re

from .vocabulary import GROUP_ORDER, GROUP_OTHER, LEGACY_NAMES, VOCABULARY

#: 空白（含全角空格）：比较时先抹掉——模型常写「吃 Token」「写 代码」
_SPACES = re.compile(r'[\s\u3000]+')
#: 括号补充说明：「点击回应 - 傲娇生气（侧身展示）」里的表演说明不是语义的一部分
_PAREN = re.compile(r'[（(][^（()）]*[)）]')
#: 素材名里的分段符：「点击回应 - 开心跃动」
_SEGMENT = re.compile(r'\s*[-–—－]\s*')
#: 引号类包裹：模型爱写「[[act:「写代码」]]」
_QUOTES = '「」『』“”‘’"\'《》'

#: 短名的兜底长度上限（表里没登记的素材才用得上）
_SHORT_MAX_CHARS = 8

#: 合成短名时剥掉的工艺前缀（"原地"说的是美术，不是语义）
_CRAFT_PREFIXES = ('小幅度原地', '小幅度', '原地', '整体')

#: 单字形态不参与包含匹配：``吃`` 会命中所有吃的动作，那是抽风而不是理解
_MIN_CONTAINS_CHARS = 2

#: 提示词抬头。措辞要求：说清"能给",也说清"别滥用"——模型对"什么时候不用"的
#: 敏感度远低于"能用什么"，不写后者等于默认每句都演。
PROMPT_HEADER = (
    '【演出】你的身体也跟着话动。想演一下的时候，在整条回复的最后写一个标记：[[act:短名]]\n'
    '- 短名只能取下面清单里的一个，写错没有任何效果。\n'
    '- 一条回复最多一个标记；平淡的一问一答不用，通常聊三到五句才用一次。\n'
    '- 标记不会显示给用户，所以不必解释它，也不要写「我演一下」这类过渡句。\n'
    '- 把话说完整，标记只放在最后。'
)


class ActEntry:
    """一段可演素材：真名、给模型的短名、分类、触发词。"""

    __slots__ = ('name', 'short', 'group', 'tags')

    def __init__(self, name: str, short: str, group: str,
                 tags: tuple[str, ...] = ()) -> None:
        self.name = name
        self.short = short
        self.group = group
        self.tags = tuple(tags)

    def __repr__(self) -> str:  # pragma: no cover - 诊断用
        return f'ActEntry({self.name!r}, short={self.short!r}, group={self.group!r})'

    def __eq__(self, other) -> bool:
        if not isinstance(other, ActEntry):
            return NotImplemented
        return (self.name, self.short, self.group, self.tags) == (
            other.name, other.short, other.group, other.tags)

    def __hash__(self) -> int:
        return hash((self.name, self.short))

    def forms(self) -> tuple[str, ...]:
        """这个名字的所有可比较形态（归一小写、去括号与分段）。"""
        raw = str(self.name or '')
        forms = {_norm(raw)}
        forms.update(_norm(part) for part in _SEGMENT.split(raw) if part.strip())
        forms.add(_norm(self.short))
        return tuple(form for form in forms if form)


def _norm(text: str) -> str:
    """归一：去引号、去括号补充、去所有空白、小写。只用于比较，不用于显示。"""
    cleaned = str(text or '').strip()
    for quote in _QUOTES:
        cleaned = cleaned.replace(quote, '')
    cleaned = _PAREN.sub('', cleaned)
    return _SPACES.sub('', cleaned).casefold()


def _shorten(name: str) -> str:
    """给表里没登记的素材合成一个短名（尽量留下语义，剥掉工艺前缀）。"""
    text = _PAREN.sub('', str(name or '')).strip()
    parts = [part.strip() for part in _SEGMENT.split(text) if part.strip()]
    text = parts[-1] if parts else text
    for prefix in _CRAFT_PREFIXES:
        if text.startswith(prefix) and len(text) > len(prefix) + 1:
            text = text[len(prefix):]
            break
    return text[:_SHORT_MAX_CHARS] or str(name or '')[:_SHORT_MAX_CHARS]


class ActRepertoire:
    """当前角色包的剧目表。"""

    def __init__(self, names, vocabulary: dict | None = None) -> None:
        if vocabulary is None:
            seed = dict(VOCABULARY)
            # 旧命名也建一份索引：老角色包/老文档里抄下来的名字照样能解析到同一段素材
            for legacy, current in LEGACY_NAMES.items():
                entry = VOCABULARY.get(current)
                if entry is not None:
                    seed.setdefault(legacy, entry)
        else:
            seed = vocabulary
        #: 素材名 → 表里的登记（按归一形态建索引，兼容全角/空格差异）
        by_norm_seed = {_norm(key): value for key, value in seed.items()}
        entries: list[ActEntry] = []
        used_shorts: set[str] = set()
        seen: set[str] = set()
        for raw in names or ():
            name = str(raw or '').strip()
            if not name or name in seen:
                continue
            seen.add(name)
            entry = self._build_entry(name, by_norm_seed, used_shorts)
            used_shorts.add(_norm(entry.short))
            entries.append(entry)
        self.entries: tuple[ActEntry, ...] = tuple(entries)
        self._by_name = {entry.name: entry for entry in self.entries}

    @staticmethod
    def _build_entry(name: str, by_norm_seed: dict,
                     used_shorts: set[str]) -> ActEntry:
        seed = by_norm_seed.get(_norm(name))
        if seed is None:
            return ActEntry(name, _shorten(name), GROUP_OTHER)
        short, group, tags = seed
        # 短名冲突（同一个角色包里两段素材撞了短名）：后到的那段退回素材名本身，
        # 保证"短名 → 素材"永远是单值映射，模型点到什么就是什么。
        if _norm(short) in used_shorts:
            short = _shorten(name)
        if _norm(short) in used_shorts:
            short = name
        return ActEntry(name, str(short), str(group), tuple(tags))

    # ------------------------------------------------------------ 查询
    def __len__(self) -> int:
        return len(self.entries)

    def __bool__(self) -> bool:
        return bool(self.entries)

    def entry(self, name: str) -> ActEntry | None:
        return self._by_name.get(str(name or '').strip())

    def short_of(self, name: str) -> str:
        found = self.entry(name)
        return found.short if found is not None else str(name or '')

    def groups(self) -> tuple[str, ...]:
        """出现过的分类，按提示词要用的顺序（未登记分类垫底）。"""
        present = {entry.group for entry in self.entries}
        ordered = tuple(group for group in GROUP_ORDER if group in present)
        return ordered + ((GROUP_OTHER,) if GROUP_OTHER in present else ())

    def resolve(self, query: str) -> str | None:
        """把模型的叫法收敛成**当前库里真实存在的**素材名；认不出返回 ``None``。

        匹配优先级（高到低）：素材名/短名完全相同 → 某形态包含它 → 它包含某形态
        → 触发词完全相同/包含。同分取**表里靠前**的那条，保证同一个说法每次
        收敛到同一段素材（可复现，不会因为集合遍历顺序抖动）。
        """
        wanted = _norm(query)
        if not wanted:
            return None
        best_name = ''
        best_score = 0.0
        for index, entry in enumerate(self.entries):
            score = _best_score(wanted, entry)
            if score <= 0:
                continue
            # 同分时靠前优先：扣掉一点点序号（严格小于任何实际分差的下限）
            score -= index * 1e-4
            if score > best_score:
                best_score, best_name = score, entry.name
        return best_name or None

    # ------------------------------------------------------------ 提示词
    def prompt_block(self) -> str:
        """给模型看的演出说明 + 短名清单；没有可演素材时返回空串。"""
        if not self.entries:
            return ''
        lines = [PROMPT_HEADER]
        for group in self.groups():
            shorts = [entry.short for entry in self.entries if entry.group == group]
            if shorts:
                lines.append(f'{group}：' + ' '.join(shorts))
        return '\n'.join(lines)

    def grouped_shorts(self) -> dict[str, tuple[str, ...]]:
        """``{分类: (短名, ...)}``（测试与设置页预览用）。"""
        grouped: dict[str, list[str]] = {}
        for entry in self.entries:
            grouped.setdefault(entry.group, []).append(entry.short)
        return {group: tuple(shorts) for group, shorts in grouped.items()}


def _best_score(wanted: str, entry: ActEntry) -> float:
    """一个候选条目对这个说法的匹配分；0 = 不匹配。"""
    forms = entry.forms()
    tags = tuple(_norm(tag) for tag in entry.tags)
    tags = tuple(tag for tag in tags if tag)
    score = 0.0
    for form in forms:
        if form == wanted:
            return 1000.0 + len(form)
        if len(wanted) >= _MIN_CONTAINS_CHARS and len(form) >= _MIN_CONTAINS_CHARS:
            if wanted in form:
                score = max(score, 500.0 - (len(form) - len(wanted)))
            elif form in wanted:
                score = max(score, 300.0 - (len(wanted) - len(form)))
    for tag in tags:
        if tag == wanted:
            score = max(score, 800.0 + len(tag))
        elif len(wanted) >= _MIN_CONTAINS_CHARS and len(tag) >= _MIN_CONTAINS_CHARS:
            if wanted in tag:
                score = max(score, 200.0 - (len(tag) - len(wanted)))
            elif tag in wanted:
                score = max(score, 150.0 - (len(wanted) - len(tag)))
    return score


__all__ = ['ActEntry', 'ActRepertoire', 'PROMPT_HEADER']
