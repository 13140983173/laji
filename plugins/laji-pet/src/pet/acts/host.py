# -*- coding: utf-8 -*-
"""壳拓扑下的演出面：把 PetWindow 的两个洞搬到适配器上。

为什么需要这一层
----------------
聊天窗只认 ``pet_window`` 上的两个洞：``act_repertoire()``（提示词里那份短名
清单）和 ``request_act(cue)``（模型点完之后真正开演）。overlay 拓扑没有
``PetWindow``，聊天窗拿到的是 ``app._OverlayChatHost``——它原本只转发定位与
头像，两个洞都缺。缺了不报错，只是**静默失联**：清单取不到 → ``act_prompt_block``
返回空串（模型压根不知道能演）；请求无人接收 → 模型写了标记也白写。

契约对齐
--------
本模块与 ``window.py`` 的同名方法逐条对齐（同一份 ``ActRepertoire`` 名字口径、
同一个 ``ActDirector`` 闸门、同一行 ``chat act`` 日志）。差异只在"素材从哪来、
播给谁"：窗口自己拿着 ``self.acts/clicks/moves`` 与 ``play_once``；壳这边读
``shell.cats`` 与 ``shell.request_link_anim``。
"""
from __future__ import annotations

import logging

from ..catalog import FRAME_MS
from .cue import user_asked
from .director import ActDirector
from .hint import act_cooldown_seconds, act_enabled
from .repertoire import ActRepertoire

logger = logging.getLogger(__name__)


def _cats(shell) -> dict:
    """壳上的素材分类表；读不到就当空（宁可没有演出，不许影响聊天）。"""
    try:
        cats = getattr(shell, 'cats', None)
    except Exception:  # noqa: BLE001 - 分类表在换角色瞬间可能正在重建
        return {}
    return cats if isinstance(cats, dict) else {}


class ChatActHost:
    """聊天侧看到的"桌宠"：一个壳也能演出。

    只读壳上的四个面：``config``（开关与冷却）、``cats``（能演哪些名字）、
    ``lib.frames``（时长）、``request_link_anim``（开演）。
    """

    def __init__(self, shell, config=None) -> None:
        self._shell = shell
        # 壳上没有"真配置"（它的 ``config`` 只是身份载体），开关/冷却必须由
        # 建宿主的一方把实例配置递进来，否则设置页里关掉「演出」不生效。
        self._config = config
        self._repertoire_cache = None
        self._director = None

    # ------------------------------------------------------------------ 清单
    def act_repertoire(self) -> ActRepertoire:
        """当前可演的一次性素材（动作/点击回应/移动），换角色后按新名字重建。"""
        cats = _cats(self._shell)
        names = (
            tuple(cats.get('acts') or ())
            + tuple(cats.get('clicks') or ())
            + tuple(cats.get('moves') or ())
        )
        cached = self._repertoire_cache
        if cached is not None and cached[0] == names:
            return cached[1]
        repertoire = ActRepertoire(names)
        self._repertoire_cache = (names, repertoire)
        return repertoire

    # ------------------------------------------------------------------ 闸门
    def act_director(self) -> ActDirector:
        if self._director is None:
            self._director = ActDirector(
                self.act_repertoire().resolve,
                duration=self._act_duration_seconds,
                enabled=lambda: act_enabled(self._config),
                cooldown=lambda: act_cooldown_seconds(self._config),
            )
        return self._director

    def _act_duration_seconds(self, name: str):
        """一段素材播完要多久（帧数 × 帧长）；查不到就交给闸门跳过时长判断。"""
        try:
            frames = int(self._shell.lib.frames(name))
        except Exception:  # noqa: BLE001 - 壳还没装素材/换角色中
            return None
        return (frames * FRAME_MS) / 1000.0 if frames > 0 else None

    # ------------------------------------------------------------------ 开演
    def request_act(self, cue) -> bool:
        """聊天侧提的演出请求；返回是否真的演了（日志与窗口侧同一行）。"""
        if not cue:
            return False
        decision = self.act_director().decide(
            getattr(cue, 'queries', ()), reply_chars=getattr(cue, 'reply_chars', 0),
            user_asked=user_asked(cue))
        logger.info('chat act %s', decision.describe())
        if not decision.accepted:
            return False
        self._shell.request_link_anim(decision.name)
        return True


__all__ = ['ChatActHost']
