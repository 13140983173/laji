# -*- coding: utf-8 -*-
"""剧目表（``pet/acts/repertoire.py``）：可播集合 → 短名/触发词 → 解析。

关键契约：**只认当前库真实可播的名字**。认不出就返回 ``None``（宁可不演），
绝不返回一个库里不存在的名字——``sprite_behavior.play_once`` 的入口守卫会当场
失败，那正是 ``work_choreo`` 曾经踩过的"假 ACTS"。
"""
from __future__ import annotations

from pathlib import Path

from pet.acts.repertoire import PROMPT_HEADER, ActRepertoire
from pet.acts.vocabulary import VOCABULARY

#: 故意混入一段表里没登记的素材，模拟第三方角色包
NAMES = (
    '点击回应 - 开心跃动',
    '写代码',
    '吃晚餐',
    '摇扇纳凉',
    '小幅度原地 360 度旋转展示',
    '原地转呼啦圈',
)


def _repertoire(names=NAMES):
    return ActRepertoire(names)


def test_entries_follow_the_given_order_and_skip_duplicates():
    repertoire = _repertoire(NAMES + ('写代码',))
    assert len(repertoire) == len(NAMES)
    assert [entry.name for entry in repertoire.entries] == list(NAMES)


def test_short_name_of_registered_act_is_the_human_facing_one():
    repertoire = _repertoire()
    assert repertoire.short_of('点击回应 - 开心跃动') == '开心跃动'
    assert repertoire.short_of('小幅度原地 360 度旋转展示') == '转圈'


def test_unregistered_act_gets_a_usable_short_name_without_craft_prefix():
    entry = _repertoire().entry('原地转呼啦圈')
    assert entry is not None
    assert entry.short == '转呼啦圈'
    assert entry.group == '其他'


def test_resolve_accepts_full_name_short_name_tag_and_partial_name():
    repertoire = _repertoire()
    assert repertoire.resolve('点击回应 - 开心跃动') == '点击回应 - 开心跃动'
    assert repertoire.resolve('开心跃动') == '点击回应 - 开心跃动'
    assert repertoire.resolve('晚饭') == '吃晚餐'
    assert repertoire.resolve('转圈') == '小幅度原地 360 度旋转展示'
    assert repertoire.resolve('没登记的动作') is None  # 名字对不上就不认
    assert repertoire.resolve('呼啦圈') == '原地转呼啦圈'


def test_resolve_accepts_the_near_miss_the_model_actually_wrote():
    """真机证据：宠物会话里模型写过 ``[[act:擦屏幕]]``（清单里叫「擦桌子」），
    差一个字就整段不演。近义说法登记在同一段素材的触发词上，才能演出来。
    """
    repertoire = ActRepertoire(('碎碎念-擦桌碎碎念',))
    assert repertoire.resolve('擦屏幕') == '碎碎念-擦桌碎碎念'


def test_resolve_is_case_and_space_insensitive():
    repertoire = _repertoire()
    assert repertoire.resolve('吃 TOKEN') is None  # 本包里没有这段素材
    assert ActRepertoire(('吃Token',)).resolve(' 吃 token ') == '吃Token'


def test_resolve_returns_none_for_unknown_or_too_short_queries():
    repertoire = _repertoire()
    assert repertoire.resolve('') is None
    assert repertoire.resolve('完全不存在的动作') is None
    # 单字不做包含匹配：否则「好」会命中「好看/好耶」，等于乱抽风
    assert repertoire.resolve('好') is None


def test_resolve_only_ever_returns_playable_names():
    repertoire = _repertoire()
    for query in ('写代码', '晚饭', '热', '转圈', '呼啦圈', '胡扯'):
        resolved = repertoire.resolve(query)
        assert resolved is None or resolved in NAMES


def test_short_names_are_unique_even_when_material_names_collide():
    repertoire = ActRepertoire(('写代码', '写代码（另一个）'))
    shorts = [entry.short for entry in repertoire.entries]
    assert len(set(shorts)) == len(shorts)
    assert shorts[0] == '写代码'


def test_prompt_block_lists_groups_in_order_and_costs_little():
    repertoire = _repertoire()
    block = repertoire.prompt_block()
    assert block.startswith(PROMPT_HEADER)
    assert '情绪：开心跃动' in block
    assert '工作：写代码' in block
    assert '吃：吃晚餐' in block
    assert '其他：转呼啦圈' in block
    # 素材真名不进清单（太长、模型会改写）
    assert '点击回应' not in block
    assert '小幅度原地' not in block
    # 短小是设计目标：45 段素材全列也不过三百来字
    assert len(block) < 400


def test_empty_repertoire_produces_no_prompt_block():
    repertoire = ActRepertoire(())
    assert not repertoire
    assert repertoire.prompt_block() == ''
    assert repertoire.resolve('写代码') is None


# ------------------------------------------------------------ 与真实素材池对账
def _shipped_one_shot_clips():
    """内置角色包里真正能演的一段性素材（目录就是权威口径）。

    这里不能用 ``catalog.ACTS``：那是旧版单目录布局的静态缺省清单（51 条），
    而实际角色包是按 ``videos/`` 子目录扫描的（单是 random/ 就有 89 段）。
    用静态清单对账会得到一个「全部登记」的假绿。
    """
    root = (Path(__file__).resolve().parents[1]
            / 'assets' / 'characters' / 'shenshen' / 'videos')
    if not root.is_dir():
        return None
    by_folder: dict[str, list[str]] = {}
    for path in sorted(root.rglob('*')):
        if path.suffix.lower() not in ('.webm', '.gif'):
            continue
        rel = path.relative_to(root)
        folder = rel.parts[0].lower() if len(rel.parts) > 1 else ''
        by_folder.setdefault(folder, []).append(path.stem)
    one_shot: list[str] = []
    for folder, names in by_folder.items():
        if folder in ('idle', 'turn', 'drag'):
            continue
        one_shot.extend(names)
    return one_shot


def test_vocabulary_covers_every_playable_clip_of_the_shipped_pack():
    """内置角色包的每一段一段性表演都必须在语义表里登记。

    素材名是美术定的，手写一百条必然有拼错/漏写的时候；拼错的后果不是报错，而是
    那段素材退到「其他」组、短名变成一个长名字——模型基本不会再选它。这条断言把
    “没登记”变成一个红灯，而不是坐等体验变差。
    """
    playable = _shipped_one_shot_clips()
    if playable is None:
        return  # 素材未随包下发：无从对账
    repertoire = ActRepertoire(playable)
    unregistered = [entry.name for entry in repertoire.entries if entry.group == '其他']
    assert unregistered == [], f'语义表漏登记：{unregistered}'


def test_no_registered_name_is_missing_from_the_shipped_pack():
    """反向对账：表里条目应该在真实素材里存在（否则是白占一行、模型点了没反应）。"""
    playable = _shipped_one_shot_clips()
    if playable is None:
        return
    names = set(playable)
    missing = sorted(key for key in VOCABULARY if key not in names)
    assert missing == [], f'语义表里有素材不存在的条目：{missing}'


def test_every_short_name_resolves_back_to_its_own_clip():
    playable = _shipped_one_shot_clips()
    if playable is None:
        return
    repertoire = ActRepertoire(playable)
    wrong = [(entry.short, repertoire.resolve(entry.short), entry.name)
             for entry in repertoire.entries
             if repertoire.resolve(entry.short) != entry.name]
    assert wrong == []
