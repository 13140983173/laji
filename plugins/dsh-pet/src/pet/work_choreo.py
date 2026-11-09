# -*- coding: utf-8 -*-
"""「去开机」演出编排：看一眼 → 走过去 → 按一下 → 等她开机 → 雀跃 / 没找着就叹气。

六幕与素材的对应（内置包 ``shenshen`` 全都有现成的，不需要另做动画）::

    scan   工作状态-原地踱步张望     找到 Laji 啦
    walk   左转奔跑（按步幅反推倍速）  过去敲一下…
    press  工作状态-忙碌点按          敲到了，等她开机…
    boot   工作状态-清点归档          引擎点火中，鱼在踩风箱
    stall  工作状态-垂头叹气冒汗       敲了半天没动静，她好像不在家…
    done   工作状态-雀跃庆祝          开门营业！老板请检阅

失败幕**不是可选项**：按不动、拉不起、22 秒等不到进程，三条路都落到 ``stall``。
旧实现在 press 失败时直接 ``cancel()``——观众看完"敲了一下"就没了，等于白演。

**为什么单独一个模块**（而不是塞进 ``sprite_behavior``）
-------------------------------------------------------
``sprite_behavior`` 是常驻状态机（idle/move/turn/click/drag），它的位移计划是
「随机方向 + 随机距离 + 步幅整圈量化」，目标点由它自己掷骰。本次要的是**走到
任务栏那颗图标旁边**——目标由外部给定。往那个状态机里塞一个"指定目标"分支，
等于改所有入口的语义（掷骰、预测预热、菜单移动全都会看见它），风险不对等。

这里只**组合**既有能力，一行既有行为都不改：

* 播动作 → ``behavior.play_once(sprite, name)``（``switch_clip`` 同一条路）
* 挪位置 → ``sprite.set_pos()``（唯一位置入口，自带工作区钳制）
* 冒泡   → ``shell.show_bubble()``
* 拉起   → ``agent_bridge.open_laji_in_background()``（deep link 语义全保留）

任何一环不满足（没素材 / 没图标 / 被用户抓起来）就**原地收手**：调用方接着走
老路径，用户看到的至少不比现在差。

动作语义层
----------
角色包不同、素材名不同：内置 ``shenshen`` 叫「工作状态-忙碌点按」，别的包可能
叫「按」「敲」。所以这里只认**意图**，按「首选精确名 → 关键词」在当前库的可播
集合里解析；解析不到就跳过该步，绝不硬播一个不存在的名字（那会让
``play_once`` 的入口守卫直接失败、留一段假 ACTS）。

时间轴是**可用性驱动**的：走路时长按素材步幅算（脚不滑），启动等待按
``laji_running()`` 的真实翻转收尾，不写死"等 12 秒"。
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)

#: 状态机（对外可读，日志/诊断用）
STATE_IDLE = "idle"
STATE_SCAN = "scan"
STATE_WALK = "walk"
STATE_PRESS = "press"
STATE_BOOT = "boot"
STATE_STALL = "stall"
STATE_DONE = "done"

#: 用户接管（点击/拖拽/被扔出去）时立刻收手——她正在被摸头，别硬演开会。
_USER_STATES = frozenset({"click", "drag", "thrown"})

#: 意图 → (首选精确名, 关键词)。关键词按顺序在**库的可播集合**里找子串。
ACTION_HINTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "scan": (("工作状态-原地踱步张望", "东张西望"), ("踱步", "张望", "观察")),
    "press": (("工作状态-忙碌点按", "原地敲击桌面互动"),
              ("点按", "敲击", "敲", "拍", "按")),
    "file": (("工作状态-清点归档",), ("归档", "清点", "整理")),
    "stall": (("工作状态-垂头叹气冒汗",), ("叹气", "冒汗", "喘气")),
    "done": (("工作状态-雀跃庆祝", "点击回应-开心跃动"), ("雀跃", "庆祝", "欢呼")),
}

#: 走路素材偏好（越靠前越先试）。最后兜底取库里的任意 move。
#:
#: **顺序是踩出来的，别随手改**。内置包三段走姿逐帧看过的真实姿态：
#:
#: * 「漂浮踏步」——全程直立，body 只有上下微浮；``move_strides`` 的 curve
#:   从第 10 帧起线性升到 221 帧，是**匀速位移**。唯一适合"循环边走"的一段。
#: * 「左转奔跑」——第 1~56 帧**原地转身**（身体横躺 90°，curve 全 0），
#:   56~118 帧才位移，118 帧后原地站到结尾。拿它循环走，每圈都会横一下。
#: * 「螃蟹走路」——中段身体**前倾 30~45°**（真·螃蟹姿态），看着就是斜的。
WALK_HINTS: tuple[str, ...] = ("漂浮踏步", "漂浮", "踏步", "左转奔跑", "奔跑", "小跑",
                               "螃蟹走路", "走路")

#: 「漂浮/滑行」类步态判据：脚不着地，不存在脚与地面的同步关系。
_FLOATY_HINTS: tuple[str, ...] = ("漂浮", "飘", "滑")

#: 启动等待期间的气泡（按秒排；超时也不报错，只是不再说话）
BOOT_LINES: tuple[tuple[float, str], ...] = (
    (0.0, "正在准备牛马资料…"),
    (3.6, "引擎点火中，鱼在踩风箱"),
    (7.6, "就快开门了！"),
)

#: 打开**别的应用**时等她开门的台词。上面那三句是 Laji 自己的梗，套到豆包身上
#: 就穿帮了（"引擎点火中"跟豆包没关系）。
OPEN_BOOT_LINES: tuple[tuple[float, str], ...] = (
    (0.0, "敲门中…"),
    (2.4, "听见里面有动静了"),
    (5.0, "再等等，门要开了"),
)


# ---------------------------------------------------------------- 三档节奏
#: 演出档位：同一套六幕，三种"她现在多闲"。
#:
#: * ``cinema`` —— 完整演出（默认）。走位 / 每幕台词 / 循环等待全给足。
#: * ``quick``  —— 快节奏。幕序不变（她仍然走过去、仍然按下去），每幕时长压到
#:   一半上下，台词时长缩短，走路按 1.5 秒走完。
#: * ``silent`` —— 不演。不走路、不播动作、不唠嗑，直接把它点亮，两句
#:   （"点它"/"开好啦"）收尾。已经开着的话连点都不点，一句"本来就在这儿"。
#:
#: 三档**只改时间轴与动作取舍**，不改幕序与失败判据——降档不许降级成"假成功"。
PACE_CINEMA = "cinema"
PACE_QUICK = "quick"
PACE_SILENT = "silent"
PACE_CHOICES: tuple[str, ...] = (PACE_CINEMA, PACE_QUICK, PACE_SILENT)
DEFAULT_PACE = PACE_CINEMA

#: 给设置页/菜单用的中文名与说明（同一份文案，两处不许各写一份）。
PACE_LABELS: dict[str, str] = {
    PACE_CINEMA: "完整演出",
    PACE_QUICK: "快节奏",
    PACE_SILENT: "安静不演",
}
PACE_HINTS: dict[str, str] = {
    PACE_CINEMA: "六幕全演：看她一眼、走过去、按下去、等开门、雀跃（约 5~8 秒）",
    PACE_QUICK: "同样的六幕，每幕压到一半上下，走路 1.5 秒到位（约 2~3 秒）",
    PACE_SILENT: "不走路也不播动作，直接把应用点亮，只留两句气泡（约 1 秒）",
}


def normalize_pace(value: Any) -> str:
    """把任意输入归一到一个合法档位（脏值一律回 ``cinema``，不猜用户意图）。"""
    text = str(value or "").strip().lower()
    return text if text in PACE_CHOICES else DEFAULT_PACE


@dataclass
class Timeline:
    """时长/阈值（全部可注入，测试里改成毫秒级）。"""

    #: 档位名（只用于诊断/日志，不参与判定——行为差异全部落在下面的字段上）。
    pace: str = DEFAULT_PACE
    #: 档位开关：不走路 / 不播动作 / 不唠嗑（"必要台词"不受 talk 管）。
    walk: bool = True
    animate: bool = True
    talk: bool = True
    #: 台词显示时长的缩放（quick 缩短，silent 不用管）
    line_scale: float = 1.0

    scan_s: float = 0.85
    press_s: float = 1.15
    stall_s: float = 2.4           # 没找到时的叹气时长（素材 4.9s，不播满）
    done_s: float = 1.9
    boot_timeout_s: float = 22.0   # 冷启动本机 ~19s（点下去时已过 ~4s，留足余量）
    boot_settle_s: float = 0.8     # 主窗出现后再等她两口气，别抢在她前面庆祝
    warm_boot_s: float = 0.9       # 按下去时本来就在:只当"提到前台"
    boot_poll_s: float = 0.4
    walk_seconds: float = 2.8      # 走完这段的期望时长（用来反推播放倍速）
    walk_speed_max: float = 6.0    # 播放倍速上限：再快就成电风扇了
    walk_anim_speed: float = 1.6   # 漂浮/滑行类步态的固定倍速（位移与动画解耦）
    walk_min_px: float = 16.0      # 这么近就不用走了
    walk_min_px_per_s: float = 30.0  # 最低地面速度：低于它每帧不到 0.5px，像卡住
    stand_gap_px: float = 10.0     # 站定时与图标留的缝（别压住图标）

    @classmethod
    def for_pace(cls, pace: Any = None) -> "Timeline":
        """按档位造一条时间轴；``cinema`` 就是默认值本身（一个数都不改）。

        为什么用「整条时间轴替换」而不是"给每幕加一个 if"：档位是**观看节奏**，
        它同时影响时长、动作取舍、台词密度三件事。用一个对象把这三样打包，加档
        位就只改这张表，不需要在六个 ``_tick_*`` 里各判一次。
        """
        pace = normalize_pace(pace)
        if pace == PACE_CINEMA:
            return cls(pace=pace)
        if pace == PACE_QUICK:
            return cls(
                pace=pace,
                line_scale=0.75,
                scan_s=0.45,
                press_s=0.75,
                stall_s=1.6,
                done_s=1.1,
                boot_settle_s=0.5,
                warm_boot_s=0.6,
                walk_seconds=1.5,
            )
        # silent：不走路、不播动作、只剩必要台词。等待上限照旧（是真等它开门，
        # 不是演出来的时长），但"落定"判得更急——她已经不演了，别赖在那儿。
        return cls(
            pace=pace,
            walk=False,
            animate=False,
            talk=False,
            scan_s=0.0,
            press_s=0.0,
            stall_s=1.4,
            done_s=0.9,
            boot_settle_s=0.3,
            warm_boot_s=0.35,
        )


def resolve_action(names, key: str) -> str | None:
    """在 ``names``（库的可播集合）里解析出意图 ``key`` 对应的素材名。"""
    exact, keywords = ACTION_HINTS.get(key, ((), ()))
    for name in exact:
        if name in names:
            return name
    ordered = sorted(names)          # 稳定顺序：同一份库每次解析结果一致
    for kw in keywords:
        for name in ordered:
            if kw in name:
                return name
    return None


def pick_walk(moves) -> str | None:
    """从 move 池里挑一段走姿：先按偏好名，再取第一个可用的。"""
    pool = [m for m in moves if m]
    if not pool:
        return None
    for hint in WALK_HINTS:
        for name in pool:
            if hint in name:
                return name
    return sorted(pool)[0]


# ---------------------------------------------------------------- 演出本体
class WorkEngine:
    """演出状态机（**不碰 Qt**：``tick(dt)`` 由外面的定时器喂）。

    宿主（``host``）只需实现十几个小方法，见 :class:`ShellHost`；测试里用假宿主
    就能把整条时间轴跑完，不需要 QApplication。
    """

    def __init__(
        self,
        host,
        *,
        locate: Callable[[], Any] | None = None,
        launch: Callable[[], bool] | None = None,
        running: Callable[[], bool] | None = None,
        timeline: Timeline | None = None,
        locate_start: Callable[[], Any] | None = None,
        locate_desktop: Callable[[], Any] | None = None,
        press_start: Callable[[], bool] | None = None,
        press_laji: Callable[[], bool] | None = None,
        double_click: Callable[[int, int], bool] | None = None,
        dismiss_start: Callable[[], None] | None = None,
    ) -> None:
        self.host = host
        self.cfg = timeline or Timeline()
        self._locate = locate or _default_locate
        self._locate_start = locate_start or _default_locate_start
        self._locate_desktop = locate_desktop or _default_locate_desktop
        self._press_start = press_start or _press_start
        self._press_laji = press_laji or _press_laji
        self._double_click = double_click or _default_double_click
        self._dismiss_start = dismiss_start or _dismiss_start
        self._launch = launch or _default_launch
        self._running = running or _default_running

        self.state = STATE_IDLE
        self._t = 0.0            # 当前阶段已用时长（超时/轮询用）
        self._loop_t = 0.0       # 当前这段演出动画已播时长（循环重播用）
        self._total = 0.0
        self._text = ""
        self._icon = None
        self._clips: dict[str, str | None] = {}
        self._walk_name: str | None = None
        self._seg = 0.0          # 当前这段演出动画的时长（用于循环重播）
        self._speed = 1.0
        self._target_x: float | None = None
        self._facing = "left"
        self._px_per_s = 0.0
        self._boot_started_at: float | None = None
        self._boot_poll_at = 0.0
        self._boot_line = 0
        self._warm = False
        self._launch_ok = False
        self._stall = 0.0        # 走不动（被工作区钳住）的累计时长
        self._stall_anchor: float | None = None   # 进 stall 时的 x（判总位移）
        self._reason = ""
        self._stall_reason = ""      # 进 stall 时定的收尾原因（结束才写进 reason）
        self._target_kind = "laji"   # "laji" = 走到任务栏图标；"start" = 兜底去开始菜单
        self._pressed = False        # 是否真的按下了开始按钮（决定收尾要不要收菜单）
        # 指定目标（app_target.AppGoal）：None = 老路径「开 Laji」。
        # 非 None 时 _plan_target 不再猜，直接用 goal 给的落点与激活动作。
        self._goal = None

    # ------------------------------------------------------------ 查询
    @property
    def active(self) -> bool:
        return self.state not in (STATE_IDLE,)

    @property
    def reason(self) -> str:
        """上一轮是怎么收的（诊断/日志用）。"""
        return self._reason

    def _who(self) -> str:
        """台词里怎么称呼目标（老路径是固定的人名）。"""
        return self._goal.label if self._goal is not None else "Laji"

    def _is_up(self) -> bool:
        """它现在是不是已经开着了（等门开的判据）。

        指定目标时看**窗口可见**（进程起来不等于门开了），老路径沿用 Laji 自己
        那套进程探测，保持原来的超时/假成功判定不变。
        """
        if self._goal is not None:
            from .app_target import window_visible

            return bool(_safe(lambda: window_visible(self._goal.label), False))
        return bool(_safe(self._running, False))

    # ------------------------------------------------------------ 启动
    def start(self, text: str = "", goal=None, pace: Any = None) -> bool:
        """开演；返回 False = 这场戏开不了（素材全缺），调用方走老路径。

        ``goal`` 为 ``app_target.AppGoal`` 时演「去打开某个应用」；为 None 时是
        原来的「去开 Laji」。两条路共用同一套走位/说话/失败收尾，只是目标来源不同。

        ``pace`` 是三档节奏（见 ``PACE_CHOICES``）；为 None 时沿用当前时间轴
        （默认 ``cinema``）。每场都重算一次，用户在设置里改档不用重启桌宠。
        """
        if self.active:
            return True
        if pace is not None:
            self.cfg = Timeline.for_pace(pace)
        host = self.host
        names = set(host.names() or ())
        self._clips = {k: resolve_action(names, k) for k in ACTION_HINTS}
        self._walk_name = pick_walk(host.moves() or [])
        # 不看动画的档位（silent）不做素材前置检查：它压根不播，没有素材也不该
        # 因此退化成"什么都没发生"。
        if (not any(self._clips.values()) and self._walk_name is None
                and self.cfg.animate):
            self._reason = "没有可用素材"
            return False

        self._goal = goal
        self._text = str(text or "")
        self._warm = self._is_up()
        self._launch_ok = False
        self._stall_reason = ""
        self._boot_started_at = None
        self._boot_line = 0
        self._total = 0.0
        if not self.cfg.walk and self._warm:
            # 安静档 + 本来就开着：连点都不用点，一句"在这儿呢"就收（别去按一个
            # 已经在最前面的窗口——那可能把它最小化，等于帮倒忙）。
            self._launch_ok = True
            self._target_x = None
            self._reason = "完成"
            self._enter(STATE_DONE)
            log.debug("work_choreo: 安静档，目标已在前台 → 直接收尾")
            return True
        self._plan_target()
        self._enter(STATE_SCAN)
        log.debug("work_choreo: 开演 pace=%s icon=%s clips=%s walk=%s",
                  self.cfg.pace, getattr(self, "_icon", None), self._clips,
                  self._walk_name)
        return True

    def cancel(self, reason: str = "取消") -> None:
        if not self.active:
            return
        self._restore_speed()
        self.state = STATE_IDLE
        self._reason = reason
        log.debug("work_choreo: 收手（%s）", reason)

    # ------------------------------------------------------------ 每帧
    def tick(self, dt: float) -> None:
        if not self.active:
            return
        dt = max(0.0, min(float(dt), 0.25))   # 掉帧/挂起后别一步跨过整段
        if host_state := _safe(self.host.state, None):
            if host_state in _USER_STATES:
                self.cancel("用户接管")
                return
        self._t += dt
        self._loop_t += dt
        self._total += dt
        getattr(self, f"_tick_{self.state}")(dt)

    # ---- scan：先看她一眼，确认目标 --------------------------------
    def _tick_scan(self, _dt: float) -> None:
        if self._t >= self.cfg.scan_s:
            self._enter(STATE_WALK)

    # ---- walk：按步幅算速度，别让她滑行 ----------------------------
    def _tick_walk(self, dt: float) -> None:
        if self._target_x is None:
            self._enter(STATE_PRESS)
            return
        x, y = self.host.pos()
        remain = self._target_x - x
        if abs(remain) <= 1.0:
            self._enter(STATE_PRESS)
            return
        step = min(abs(remain), self._px_per_s * dt)
        self.host.set_pos(x + (step if remain > 0 else -step), y)
        after = self.host.pos()[0]
        if abs(after - x) < 0.05:
            # 位置被工作区钳住（她要走到任务栏边、但身体不许出台）：
            # 继续演下去只会原地蹬腿——收手，当她已经走到最近处。
            #
            # 判据是「这一小段里**总共**没挪动」，不是「这一帧没挪动」：慢速
            # 走位每帧只推进 0.2~0.3px（内置包 natural 步速只有 12px/s），
            # 按单帧阈值判会把正常走位判成被钳住——实测就是这样只走 7px 就
            # 收手，看起来像"原地按了一下"。
            if self._stall <= 0.0:
                self._stall_anchor = x
            self._stall += dt
            if self._stall >= 0.4 and abs(after - self._stall_anchor) < 1.0:
                self._enter(STATE_PRESS)
                return
        else:
            self._stall = 0.0
            self._stall_anchor = None
        self.host.set_facing("right" if remain > 0 else "left")
        if self._seg > 0 and self._loop_t >= self._seg - 0.05:
            self._replay(self._walk_name)   # 走姿循环：一段播完就续上
            self._loop_t = 0.0

    # ---- press：真正按下（走 deep link，不动真鼠标）----------------
    def _tick_press(self, _dt: float) -> None:
        if self._t >= self.cfg.press_s:
            if not self._launch_ok:
                # 按不到、也拉不起：不许静默收手。观众刚看完"敲了一下"，
                # 必须给一个"没成"的动作和一句话，否则整场戏等于没演。
                self._stall_reason = "没找到入口"
                self._enter(STATE_STALL)
                return
            self._enter(STATE_BOOT)

    # ---- stall：没找着 / 没开成，叹气收场 --------------------------
    def _tick_stall(self, _dt: float) -> None:
        if self._t >= self.cfg.stall_s:
            self._restore_speed()
            self.state = STATE_IDLE
            self._reason = self._stall_reason or "没找到入口"

    # ---- boot：等她开机（进程翻转 + 窗口落定）---------------------
    def _tick_boot(self, dt: float) -> None:
        cfg = self.cfg
        if self._warm:
            if self._t >= cfg.warm_boot_s:
                self._enter(STATE_DONE)
            return
        if self._t >= cfg.boot_timeout_s:
            # 超时不能一律当成功：进程从头到尾没出现过，就是没开成——这时去雀跃
            # 等于假报"开门营业"。进程起来了、只是窗口没落定，仍按成功收（窗口
            # 检测本身可能失灵，不该因此判失败）。
            if self._boot_started_at is None:
                self._stall_reason = (f"点了{self._goal.label}，可它就是不开"
                                      if self._goal is not None else "启动超时")
                self._enter(STATE_STALL)
            else:
                self._enter(STATE_DONE)
            return
        if self._t >= self._boot_poll_at:
            self._boot_poll_at = self._t + cfg.boot_poll_s
            if self._boot_started_at is None and self._is_up():
                self._boot_started_at = self._t
            if (self._boot_started_at is not None
                    and self._t - self._boot_started_at >= cfg.boot_settle_s):
                self._enter(STATE_DONE)
                return
        lines = OPEN_BOOT_LINES if self._goal is not None else BOOT_LINES
        while (self._boot_line < len(lines)
               and self._t >= lines[self._boot_line][0]):
            self._say(lines[self._boot_line][1], 3400)
            self._boot_line += 1
        if self._seg > 0 and self._loop_t >= self._seg - 0.05:
            self._replay(self._clips.get("file") or self._clips.get("stall"))
            self._loop_t = 0.0

    # ---- done：雀跃一下，收工 --------------------------------------
    def _tick_done(self, _dt: float) -> None:
        if self._t >= self.cfg.done_s:
            self._restore_speed()
            self.state = STATE_IDLE
            self._reason = "完成"

    # ------------------------------------------------------------ 转场
    def _enter(self, state: str) -> None:
        self.state = state
        self._t = 0.0
        self._loop_t = 0.0
        cfg = self.cfg
        if state == STATE_SCAN:
            self._replay(self._clips.get("scan"))
            who = self._who()
            if self._target_kind == "startmenu":
                self._say(f"{who}在开始菜单里，我去翻翻", 1900)
            elif self._target_kind == "start":
                self._say("Laji 不在任务栏，我去另找", 1900)
            elif self._target_kind == "desktop":
                self._say("任务栏没有，桌面上有它", 1900)
            else:
                self._say(f"找到 {who} 啦", 1700)
        elif state == STATE_WALK:
            self._plan_walk_speed()
            self._replay(self._walk_name)
            if self._target_kind in ("start", "startmenu"):
                self._say("去开始菜单翻翻…", 1700)
            elif self._target_kind == "desktop":
                self._say("去点桌面那个图标…", 1700)
            else:
                self._say("过去敲一下…", 1700)
        elif state == STATE_PRESS:
            self._restore_speed()            # 走姿倍速不许带到按/等阶段
            self._seg = cfg.press_s
            if self._goal is not None:
                # 外部指定的目标：动作已经在 goal.activate 里写好了（桌面双击 /
                # 开始菜单翻到它再 Invoke）。菜单要 1~2 秒才弹完，放后台线程跑，
                # 否则 16ms 的动画帧会被卡住，看起来像她突然死机。
                from .app_target import activate_async

                self._replay(self._clips.get("press") or self._clips.get("scan"))
                self._pressed = True
                quiet = getattr(self._goal, "activate_quiet", None)
                if not self.cfg.animate and callable(quiet):
                    # 安静档：不弹开始菜单，直接把它拉起来（省掉翻菜单那 2 秒）。
                    # 走不通（没有 exe/lnk）就退回正常路径，别为了"快"把事办砸。
                    self._launch_ok = bool(_safe(quiet, False))
                if not self._launch_ok:
                    activate_async(self._goal)
                    self._launch_ok = True
                log.debug("work_choreo: 点亮目标 %s（%s）quiet=%s", self._goal.label,
                          self._goal.kind, not self.cfg.animate)
                self._must_say(f"找到{self._goal.label}了，点它！", 2000)
                self._boot_poll_at = 0.0
                return
            if self._target_kind == "start":
                # 走到开始按钮就是为了真按：不按，这一刻就是假动作。
                self._pressed = _safe(self._press_start, False)
                log.debug("work_choreo: 按开始按钮 → %s", self._pressed)
                self._launch_ok = self._fire_launch()
            elif self._target_kind == "desktop":
                # 双击桌面快捷方式 = 真的把 Laji 起出来；不再补 deep link
                # （补了等于开两次，还会重播 9 秒启动动画）。
                ok = _safe(lambda: self._double_click(
                    int(self._icon.center_x), int(self._icon.center_y)), False)
                self._pressed = bool(ok)
                log.debug("work_choreo: 双击桌面图标 → %s", ok)
                self._launch_ok = bool(ok) or self._fire_launch()
            else:
                # 任务栏按钮能按就真按（等于用户手点）；窗口本来就是收着的，
                # 按下去才是"恢复"而不是"再开一个"。
                self._pressed = _safe(self._press_laji, False)
                log.debug("work_choreo: 按任务栏按钮 → %s", self._pressed)
                self._launch_ok = (True if (self._pressed and self._warm)
                                   else self._fire_launch())
            if self._target_kind == "start":
                self._replay(self._clips.get("press") or self._clips.get("scan"))
                self._must_say("翻到了，等她开门…" if self._launch_ok else "翻不动…",
                               2000)
            elif self._target_kind == "desktop":
                self._replay(self._clips.get("press") or self._clips.get("scan"))
                self._must_say("点开了，等她开门…" if self._launch_ok else "点不动…",
                               2000)
            else:
                self._replay(self._clips.get("press") or self._clips.get("scan"))
                self._must_say("敲到了，等她开机…" if self._launch_ok else "敲不动…",
                               2600)
            self._boot_poll_at = 0.0
        elif state == STATE_BOOT:
            self._seg = self._clip_seconds(self._clips.get("file"))
            self._replay(self._clips.get("file") or self._clips.get("stall")
                         or self._clips.get("scan"))
        elif state == STATE_STALL:
            self._restore_speed()
            self._seg = cfg.stall_s
            if self._pressed and self._target_kind == "start":
                _safe(self._dismiss_start, None)   # 菜单还开着：收回，别留半截现场
            self._replay(self._clips.get("stall") or self._clips.get("scan"))
            self._must_say(self._stall_line(), 3600)
        elif state == STATE_DONE:
            self._restore_speed()
            self._seg = cfg.done_s
            if self._pressed and self._target_kind == "start":
                _safe(self._dismiss_start, None)   # 窗口起来了，把开始菜单收回去
            self._replay(self._clips.get("done") or self._clips.get("press"))
            if self._goal is not None:
                self._must_say(f"{self._goal.label}开好啦！", 3200)
            else:
                self._must_say("开门营业！老板请检阅", 3200)

    def _stall_line(self) -> str:
        """没找着时说什么：按「找过哪几处」分开，别一律"失败了"。"""
        if self._launch_ok:
            if self._goal is not None:
                return f"点了{self._goal.label}，可它就是不开…"
            return "叫了半天没人应门…要不再点我一次试试"
        if self._goal is not None:
            return {
                "startmenu": f"开始菜单翻遍了，没有{self._goal.label}…",
                "desktop": "桌面上那个图标点不动…",
            }.get(self._target_kind, f"没找到{self._goal.label}…")
        return {
            "start": "开始菜单也翻遍了，真的没有她…",
            "desktop": "桌面上那个图标也点不动…",
        }.get(self._target_kind, "敲了半天没动静，她好像不在家…")

    def _replay(self, name: str | None) -> None:
        # 安静档不换动作：她现在播什么就让它接着播，别为一场"看不见的戏"切素材。
        if not self.cfg.animate:
            return
        if name:
            if not self.host.play(name):
                log.debug("work_choreo: 播不动 %s", name)

    # ------------------------------------------------------------ 说话
    def _say(self, text: str, ms: int = 1900) -> None:
        """**可省**的台词：silent 档一句不冒（档位越低话越少）。"""
        if not text or not self.cfg.talk:
            return
        try:
            self.host.bubble(text, int(max(600, ms * self.cfg.line_scale)))
        except Exception:
            log.debug("work_choreo: 冒泡失败", exc_info=True)

    def _must_say(self, text: str, ms: int = 2600) -> None:
        """**必要**的台词（"点它"/"开好啦"/"没找着"）：任何档位都要说。

        为什么会话分两档：降档该降的是"看她一眼""引擎点火中"这类陪衬，不是
        "它到底开没开"这类结论。全砍掉会变成"她自己动了一下，结果不明"。
        """
        if not text:
            return
        try:
            self.host.bubble(text, int(max(600, ms * self.cfg.line_scale)))
        except Exception:
            log.debug("work_choreo: 冒泡失败", exc_info=True)

    def _fire_launch(self) -> bool:
        """按下 = 交给 agent_bridge（deep link 的 force/run_id/workspace 语义全在）。"""
        try:
            return bool(self._launch(self._text))
        except TypeError:
            try:
                return bool(self._launch())
            except Exception:
                log.debug("work_choreo: 拉起失败", exc_info=True)
                return False
        except Exception:
            log.debug("work_choreo: 拉起失败", exc_info=True)
            return False

    def _clip_seconds(self, name: str | None) -> float:
        if not name:
            return 0.0
        try:
            base = float(self.host.duration(name) or 0.0)
        except Exception:
            return 0.0
        if base <= 0:
            return 0.0
        return base / max(self._speed, 0.01) if self._speed > 1.0 else base

    # ------------------------------------------------------------ 目标点
    def _plan_target(self) -> None:
        if self._goal is not None:
            # 目标由 app_target 定好了（可能来自桌面图标，也可能是开始菜单里
            # 的一格）。这里不再猜，只按它给的落点算"站哪儿"。
            self._icon = self._goal
            self._target_kind = str(self._goal.kind)
        else:
            self._icon = _safe(self._locate, None)
            self._target_kind = "laji"
            if self._icon is None:
                # Laji 收在托盘、或者根本没开时，任务栏上**没有它的按钮**（窗口
                # 一 hide 按钮就消失）。这时"走过去点图标"没有目标。
                #
                # 退一级：桌面图标。它是真实可点的（双击 = 真的启动），而且正好
                # 对应"去桌面找到 laji agent.exe 再打开"这条最符合直觉的路。
                desktop = _safe(self._locate_desktop, None)
                if desktop is not None:
                    self._icon = desktop          # 字段口径与任务栏图标一致
                    self._target_kind = "desktop"
                else:
                    # 再退一级：开始菜单。按下去菜单会真的弹出来。
                    self._icon = _safe(self._locate_start, None)
                    self._target_kind = "start"
        self._target_x = None
        self._px_per_s = 0.0
        icon = self._icon
        if icon is None or self._walk_name is None:
            return
        if not self.cfg.walk:
            # 安静档：目标点照记（收尾台词要用它的名字），但**不产生位移**。
            # walk 幕看到 target_x=None 直接进 press，她原地不动。
            return
        # UIA 在 DPI-aware 进程（Qt 一旦初始化就是）里返回的是**物理像素**，
        # 而 sprite.pos 活在 Qt 逻辑像素世界里（1920 宽屏 = 1280 逻辑）。
        # 不换算的话会按 1.5 倍偏差的落点走过去，永远停不到图标上方。
        scale_fn = getattr(self.host, "screen_scale", None)
        scale = max(0.5, float(_safe(scale_fn, 1.0) or 1.0)) if callable(scale_fn) else 1.0
        left = float(icon.left) / scale
        right = float(icon.right) / scale
        center = float(icon.center_x) / scale
        x, _y = self.host.pos()
        half = max(12.0, float(_safe(self.host.body_width, 0.0) or 0.0)) / 2.0
        gap = self.cfg.stand_gap_px
        if x + half <= center:
            target = left - half - gap      # 从左边靠过去
            self._facing = "right"
        else:
            target = right + half + gap     # 从右边靠过去
            self._facing = "left"
        if abs(target - x) < self.cfg.walk_min_px:
            return
        self._target_x = target
        self._facing = "right" if target > x else "left"

    def _plan_walk_speed(self) -> None:
        """定位移速度与动画倍速。

        两种步态两套算法：

        * **落地走姿**（脚着地）：按「步幅 ÷ 片段时长」反推真实地面速度，
          再拿期望时长倒推倍速——脚不打滑。
        * **漂浮/滑行**（脚不着地）：位移与动画**解耦**。脚不沾地就没有"脚与
          地面同步"这回事，硬算步幅反而是死路：内置「漂浮踏步」只有 90px/10s
          ≈ 9px/s，走 780px 要 31 倍速，撞上 6 倍上限就只能在原地飘 14 秒。
          所以位移直接按 ``walk_seconds`` 走完，动画自己按固定小倍速飘。
        """
        self._px_per_s = 0.0
        name = self._walk_name
        if not name or self._target_x is None:
            return
        try:
            stride = float(self.host.stride(name) or 0.0)
            base = float(self.host.duration(name) or 0.0)
        except Exception:
            return
        if base <= 0:
            return
        x, _y = self.host.pos()
        dist = abs(self._target_x - x)
        if any(k in name for k in _FLOATY_HINTS):
            self._px_per_s = dist / max(self.cfg.walk_seconds, 0.1)
            self._speed = max(1.0, min(self.cfg.walk_speed_max,
                                       self.cfg.walk_anim_speed))
            self._seg = base / self._speed
            self.host.set_speed(self._speed)
            return
        if stride <= 0:
            return
        natural = stride / base                       # 1x 播放时的真实步速（px/s）
        # 下限：内置素材的「左转奔跑」是 120px/10.04s ≈ 12px/s——那 10 秒里
        # 显然不全是走（有起势/收势），按它当步速会让她以 0.2px/帧蠕动，
        # 肉眼等同"没动"。给一个地面速度下限，播放倍速随之提上去（变成小跑），
        # 既好看也符合"赶紧过去按一下"的意图。
        want = max(dist / max(self.cfg.walk_seconds, 0.1), natural,
                   self.cfg.walk_min_px_per_s)
        speed = max(1.0, min(self.cfg.walk_speed_max, want / natural))
        self._speed = speed
        self._px_per_s = natural * speed
        self._seg = base / speed
        self.host.set_speed(speed)

    def _restore_speed(self) -> None:
        if self._speed != 1.0:
            self._speed = 1.0
            try:
                self.host.restore_speed()
            except Exception:
                log.debug("work_choreo: 速度复位失败", exc_info=True)


# ---------------------------------------------------------------- 宿主适配
class ShellHost:
    """把 ``OverlayShell``（sprite 世界）/ ``PetWindow``（旧窗世界）抹平成演出
    需要的那十几个动作。只读/调用公开面，不碰私有状态。
    """

    def __init__(self, shell, sprite=None) -> None:
        self.shell = shell
        self._sprite = sprite
        self._saved_speed: float | None = None

    @property
    def sprite(self):
        return self._sprite if self._sprite is not None else getattr(self.shell, "sprite", None)

    # ---- 素材查询 ----
    def names(self) -> set:
        lib = getattr(self.sprite, "library", None)
        fn = getattr(lib, "names", None)
        try:
            return set(fn()) if callable(fn) else set()
        except Exception:
            return set()

    def moves(self) -> list:
        lib = getattr(self.sprite, "library", None)
        try:
            from . import catalog

            cats = catalog.build_categories(
                list(self.names()),
                getattr(lib, "manifest", None),
                getattr(lib, "folder_map", None),
                getattr(lib, "folder_files", None),
            )
            return list(cats.get("moves") or [])
        except Exception:
            log.debug("work_choreo: 取 move 池失败", exc_info=True)
            return []

    def stride(self, name: str) -> float:
        lib = getattr(self.sprite, "library", None)
        try:
            from . import catalog

            table = getattr(lib, "move_strides", None) or {}
            base = table.get(name, catalog.MOVE_STRIDE_DEFAULT_PX)
            return float(base) * float(getattr(self.sprite, "scale", 1.0) or 1.0)
        except Exception:
            return 0.0

    def duration(self, name: str) -> float:
        lib = getattr(self.sprite, "library", None)
        fn = getattr(lib, "duration", None)
        try:
            return float(fn(name)) if callable(fn) else 0.0
        except Exception:
            return 0.0

    # ---- 动作/位置 ----
    def play(self, name: str) -> bool:
        sprite = self.sprite
        if sprite is None:
            return False
        behavior = self._behavior()
        if behavior is not None:
            try:
                return bool(behavior.play_once(sprite, name))
            except Exception:
                log.debug("work_choreo: play_once 失败 %s", name, exc_info=True)
        fn = getattr(self.shell, "switch_clip", None)
        try:
            return bool(fn(name)) if callable(fn) else False
        except Exception:
            return False

    def bubble(self, text: str, ms: int = 3200) -> bool:
        fn = getattr(self.shell, "show_bubble", None)
        try:
            return bool(fn(text, int(ms))) if callable(fn) else False
        except TypeError:
            try:
                return bool(fn(text))       # 旧签名只有 text
            except Exception:
                return False
        except Exception:
            return False

    def pos(self) -> tuple[float, float]:
        """**身体中心**（不是 sprite 左上角）。

        真 sprite 的 ``pos`` 是立绘画布左上角，画布比身体大一圈（内置包
        body_box=[212,60,428,330]，scale 0.5 → 身体只有 108×135，且左偏 106px）。
        拿画布左上角当"她在哪"会让靠边判定整体左偏一整个画布，实测后果是：
        她明明离图标还有 200px，却算出"只差 11px"而原地不动。
        所以对外统一成身体中心，``set_pos`` 再换算回左上角。
        """
        sprite = self.sprite
        try:
            p = sprite.pos
            if callable(p):          # 假宿主/旧窗世界把它写成方法
                p = p()
            ox, oy = self._body_center_offset()
            return float(p.x()) + ox, float(p.y()) + oy
        except Exception:
            return 0.0, 0.0

    def _body_center_offset(self) -> tuple[float, float]:
        """身体中心相对 ``sprite.pos`` 的偏移（拿不到 body_box 时按 0 处理）。"""
        sprite = self.sprite
        try:
            r = sprite.rect()
            b = sprite.body_rect()
            return (b.x() + b.width() / 2.0 - r.x(),
                    b.y() + b.height() / 2.0 - r.y())
        except Exception:
            return 0.0, 0.0

    def set_pos(self, x: float, y: float) -> None:
        sprite = self.sprite
        try:
            from PySide6.QtCore import QPointF

            ox, oy = self._body_center_offset()
            sprite.set_pos(QPointF(float(x) - ox, float(y) - oy))
        except Exception:
            log.debug("work_choreo: set_pos 失败", exc_info=True)

    def set_facing(self, facing: str) -> None:
        sprite = self.sprite
        try:
            if getattr(sprite, "facing", None) != facing:
                sprite.facing = facing
        except Exception:
            pass

    def body_width(self) -> float:
        """身体框宽度（不是画布宽度）：站定距离按身体算，不按透明边算。"""
        sprite = self.sprite
        try:
            return float(sprite.body_rect().width())
        except Exception:
            try:
                return float(sprite.rect().width())
            except Exception:
                return 0.0

    def screen_scale(self) -> float:
        """UIA 的物理像素 → Qt 逻辑像素的换算比（150% 缩放 = 1.5）。

        任务栏 UIA 在 DPI-aware 进程里返回物理像素，而 sprite.pos 活在 Qt
        逻辑像素世界里（1920 宽的屏 = 1280 逻辑单位）。不换算就会按 1.5 倍
        偏差的落点走，永远停不到图标上方。
        """
        try:
            from PySide6.QtGui import QGuiApplication

            scr = QGuiApplication.primaryScreen()
            dpr = float(scr.devicePixelRatio()) if scr is not None else 1.0
            return dpr if dpr >= 0.5 else 1.0
        except Exception:
            return 1.0

    def set_speed(self, speed: float) -> None:
        sprite = self.sprite
        if sprite is None:
            return
        # 记下用户速率原值：restore_speed 要写回去，否则「复位」只是把 clip
        # 速率改回被加速过的 playback_speed，等于没复位（真机表现为演完还是
        # 一路小跑）。
        if self._saved_speed is None:
            try:
                self._saved_speed = float(getattr(sprite, "playback_speed", 1.0) or 1.0)
            except Exception:
                self._saved_speed = 1.0
        try:
            sprite.playback_speed = float(speed)
        except Exception:
            pass
        # 光写 playback_speed 只对**下一次** bind_clip 生效；正在播的那条 clip
        # 收不到，走位看上去还是 1x（小跑像慢动作）。set_flight_anim_speed 是
        # sprite 自己的「把当前 clip 速率推上去」入口，factor 传 1.0 即
        # 用户速率 × 1 = 我们要的速度。
        fn = getattr(sprite, "set_flight_anim_speed", None)
        try:
            if callable(fn):
                fn(1.0)
        except Exception:
            log.debug("work_choreo: 推 clip 速率失败", exc_info=True)

    def restore_speed(self) -> None:
        sprite = self.sprite
        if sprite is None:
            return
        if self._saved_speed is not None:
            try:
                sprite.playback_speed = self._saved_speed
            except Exception:
                pass
        self._saved_speed = None
        fn = getattr(sprite, "reset_playback_speed", None)
        try:
            if callable(fn):
                fn()
            else:
                sprite.playback_speed = 1.0
        except Exception:
            pass

    def state(self) -> str | None:
        behavior = self._behavior()
        if behavior is None:
            return None
        try:
            return behavior.state_of(self.sprite)
        except Exception:
            return None

    def _behavior(self):
        sprite = self.sprite
        if sprite is None:
            return None
        host_for = getattr(self.shell, "host_for_sprite", None)
        try:
            if callable(host_for):
                beh = getattr(host_for(sprite), "behavior", None)
                if beh is not None:
                    return beh
        except Exception:
            pass
        return getattr(self.shell, "behavior", None)


# ---------------------------------------------------------------- Qt 外壳
def _make_qt_wrapper():
    """惰性拿 PySide6：纯逻辑测试（假宿主）不该为此付 Qt 的启动成本。"""
    from PySide6.QtCore import QObject, Qt, QTimer

    class WorkChoreo(QObject):
        """一只壳一份的演出器；``start()`` 返回 False 时调用方走老路径。"""

        def __init__(self, shell, sprite=None, parent=None) -> None:
            super().__init__(parent)
            self.host = ShellHost(shell, sprite)
            self.engine = WorkEngine(self.host)
            self._timer = QTimer(self)
            self._timer.setInterval(16)
            self._timer.setTimerType(Qt.TimerType.PreciseTimer)
            self._timer.timeout.connect(self._on_tick)
            self._last = time.monotonic()

        @property
        def active(self) -> bool:
            return self.engine.active

        def start(self, text: str = "", goal=None) -> bool:
            # 每场都现读一次档位：改设置后下一场立刻生效，不用重启桌宠。
            ok = self.engine.start(text, goal, pace=_pace_from_shell(self.shell))
            if ok:
                self._last = time.monotonic()
                self._timer.start()
            return ok

        def cancel(self, reason: str = "取消") -> None:
            self.engine.cancel(reason)
            self._timer.stop()

        def _on_tick(self) -> None:
            now = time.monotonic()
            dt = now - self._last
            self._last = now
            self.engine.tick(dt)
            if not self.engine.active:
                self._timer.stop()

    return WorkChoreo


class _LazyChoreo:
    """``WorkChoreo`` 的惰性代理：第一次 ``start`` 才构造 Qt 对象。"""

    def __init__(self, shell, sprite=None) -> None:
        self._shell = shell
        self._sprite = sprite
        self._impl = None

    def _ensure(self):
        if self._impl is None:
            self._impl = _make_qt_wrapper()(self._shell, self._sprite)
        return self._impl

    @property
    def active(self) -> bool:
        return bool(self._impl and self._impl.active)

    def start(self, text: str = "", goal=None) -> bool:
        try:
            return bool(self._ensure().start(text, goal))
        except Exception:
            log.debug("work_choreo: 起演失败，走老路", exc_info=True)
            return False

    def cancel(self, reason: str = "取消") -> None:
        if self._impl is not None:
            self._impl.cancel(reason)


def choreo_for(shell, sprite=None):
    """取（并缓存）这只壳的演出器；壳不具备演出面时返回 ``None``。

    只给**主 sprite** 演：子宠有各自的宿主窗，走过去会走出自己的窗口。
    """
    if shell is None:
        return None
    main = getattr(shell, "sprite", None)
    if sprite is not None and main is not None and sprite is not main:
        return None
    for attr in ("show_bubble", "sprite"):
        if not hasattr(shell, attr):
            return None
    choreo = getattr(shell, "_work_choreo", None)
    if choreo is None:
        choreo = _LazyChoreo(shell, sprite if sprite is not None else main)
        try:
            shell._work_choreo = choreo
        except Exception:
            log.debug("work_choreo: 挂缓存失败", exc_info=True)
    return choreo


# ---------------------------------------------------------------- 默认依赖
def _config_of(obj) -> Any:
    """从壳/宿主上摸出 config（OverlayShell 是 ``_config``，PetWindow 是 ``config``）。"""
    for attr in ("config", "_config"):
        cfg = getattr(obj, attr, None)
        if cfg is not None and hasattr(cfg, "get"):
            return cfg
    return None


def _pace_from_shell(shell) -> str:
    """读当前档位；读不到（旧壳/测试替身）就当 ``cinema``，不抛。"""
    cfg = _config_of(shell)
    if cfg is None:
        return DEFAULT_PACE
    try:
        return normalize_pace(cfg.get("open_app_pace", DEFAULT_PACE))
    except Exception:
        return DEFAULT_PACE


def _default_locate():
    from . import taskbar_icon

    taskbar_icon.invalidate()          # 要"现在"的位置，不吃旧缓存
    return taskbar_icon.locate()


def _default_locate_start():
    from . import taskbar_icon

    taskbar_icon.invalidate()
    return taskbar_icon.locate_start()


def _press_start() -> bool:
    from . import taskbar_icon

    return taskbar_icon.press_start()


def _press_laji() -> bool:
    from . import taskbar_icon

    return taskbar_icon.press_laji()


def _default_locate_desktop():
    from . import desktop_icon

    desktop_icon.invalidate()
    return desktop_icon.locate()


def _default_double_click(x: int, y: int) -> bool:
    from . import desktop_icon

    return desktop_icon.double_click(x, y)


def _dismiss_start() -> None:
    from . import taskbar_icon

    taskbar_icon.dismiss_start()


def _default_launch(text: str = ""):
    from .agent_bridge import open_laji_in_background

    return bool(open_laji_in_background(str(text or ""), force=True))


def _default_running() -> bool:
    """主窗是否**已经可见**（不是"进程在不在"）。

    用 ``agent_window.visible()`` 而不是 ``laji_running()``：后者在 spawn 后
    1 秒内就为真，而主窗还要 8～19 秒——用它收尾会让演出提前庆祝然后干等。
    """
    try:
        from . import agent_window

        return bool(agent_window.visible())
    except Exception:
        from .agent_bridge import laji_running

        return bool(laji_running())


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default
