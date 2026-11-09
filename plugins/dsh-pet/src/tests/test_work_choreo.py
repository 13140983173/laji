# -*- coding: utf-8 -*-
"""「去开机」演出编排的状态机测试（假宿主，无需 QApplication/真实桌面）。

覆盖：素材解析（本包 / 陌生包）、正常时间轴、无图标降级、走路被钳住的收手、
拉起失败、暖/冷两种启动收尾、用户中途摸她即收手。
"""
from __future__ import annotations

from pet import work_choreo as wc
from pet.taskbar_icon import TaskbarIcon

#: 单测不许碰真实任务栏：按下 = 会真的弹菜单/切窗口，等于干扰用户桌面。
wc._press_start = lambda: True
wc._press_laji = lambda: True
wc._dismiss_start = lambda: None
#: 桌面图标同理：真读一次要 200ms，而且读到的"Laji Agent"会把降级链带偏。
wc._default_locate_desktop = lambda: None
wc._default_double_click = lambda x, y: True

ICON = TaskbarIcon("Electron - 1 个运行窗口", "Appid: com.nerve.laji.agent",
                   858, 672, 902, 720)
#: 兜底目标：任务栏"开始"按钮（真机 Appid = StartButton，位置固定在左边）
START_ICON = TaskbarIcon("开始", "StartButton", 560, 672, 628, 720)

#: 内置 shenshen 的动作名（真实名字，来自 assets/characters/shenshen/videos）
SHENSHEN = {
    "待机呼吸休闲", "东张西望", "点击回应-元气挥手", "点击回应-开心跃动",
    "被鼠标拖拽悬空反馈", "左转奔跑", "螃蟹走路", "漂浮踏步",
    "工作状态-原地踱步张望", "工作状态-忙碌点按", "工作状态-清点归档",
    "工作状态-垂头叹气冒汗", "工作状态-雀跃庆祝", "写代码",
}
MOVES = ["左转奔跑", "螃蟹走路", "漂浮踏步"]


class FakeHost:
    """演出宿主替身：记下每一次播放/冒泡/写入位置。"""

    def __init__(self, names=None, moves=None, *, x=300.0, y=520.0, width=240.0,
                 clip_seconds=2.0, stride_px=220.0, margin=0.0):
        self._names = set(SHENSHEN if names is None else names)
        self._moves = list(MOVES if moves is None else moves)
        self.x = float(x)
        self.y = float(y)
        self.w = float(width)
        self.clip_seconds = float(clip_seconds)
        self.stride_px = float(stride_px)
        self.left_limit = None      # 模拟工作区钳制：x 不许小于它
        self.played: list[str] = []
        self.bubbles: list[str] = []
        self.speeds: list[float] = []
        self.playback_speed = 1.0
        self.facing = "left"
        self.behavior_state = "idle"

    # ---- 素材 ----
    def names(self):
        return set(self._names)

    def moves(self):
        return list(self._moves)

    def stride(self, name):
        return self.stride_px

    def duration(self, name):
        return self.clip_seconds

    # ---- 动作 ----
    def play(self, name):
        if name not in self._names:
            return False
        self.played.append(name)
        return True

    def bubble(self, text, ms=3200):
        self.bubbles.append(text)
        return True

    # ---- 位置 ----
    def pos(self):
        return self.x, self.y

    def set_pos(self, x, y):
        if self.left_limit is not None:
            x = max(x, self.left_limit)
        self.x, self.y = float(x), float(y)

    def set_facing(self, facing):
        self.facing = facing

    def body_width(self):
        return self.w

    def set_speed(self, speed):
        self.playback_speed = float(speed)
        self.speeds.append(float(speed))

    def restore_speed(self):
        self.playback_speed = 1.0

    def state(self):
        return self.behavior_state


def run(engine, *, seconds=30.0, dt=1 / 60, until_idle=True, on_tick=None):
    """把状态机跑到收尾（或跑满 seconds），返回消耗的虚拟秒数。"""
    spent = 0.0
    while spent < seconds:
        engine.tick(dt)
        spent += dt
        if on_tick is not None:
            on_tick(spent)
        if until_idle and not engine.active:
            break
    return spent


# ---------------------------------------------------------------- 素材解析
def test_resolve_prefers_exact_then_keyword():
    assert wc.resolve_action(SHENSHEN, "press") == "工作状态-忙碌点按"
    assert wc.resolve_action(SHENSHEN, "done") == "工作状态-雀跃庆祝"
    # 陌生角色包：没有「工作状态-*」，靠关键词也要能接上
    foreign = {"待机", "按一下开关", "整理桌面", "欢呼雀跃"}
    assert wc.resolve_action(foreign, "press") == "按一下开关"
    assert wc.resolve_action(foreign, "file") == "整理桌面"
    assert wc.resolve_action(foreign, "done") == "欢呼雀跃"
    # 完全没有对应素材：返回 None，绝不硬造一个名字
    assert wc.resolve_action({"待机"}, "press") is None


def test_pick_walk_prefers_run_then_falls_back():
    # 「漂浮踏步」是唯一全程直立的走姿（左转奔跑中段横躺、螃蟹走路前倾 30~45°），
    # 所以它排第一，不是按文件名好看程度排的。
    assert wc.pick_walk(MOVES) == "漂浮踏步"
    assert wc.pick_walk(["左转奔跑"]) == "左转奔跑"
    assert wc.pick_walk(["螃蟹走路"]) == "螃蟹走路"
    assert wc.pick_walk(["只有这个"]) == "只有这个"
    assert wc.pick_walk([]) is None


# ---------------------------------------------------------------- 正常一场
def test_happy_path_walks_presses_and_celebrates():
    host = FakeHost()
    launched = []
    engine = wc.WorkEngine(
        host,
        locate=lambda: ICON,
        launch=lambda text="": launched.append(text) or True,
        running=lambda: True,          # 已经在跑：暖路径，收尾快
    )
    assert engine.start("") is True
    run(engine)

    # 走过去：从左边靠向图标左侧（不压住图标）
    assert host.x < 300.0 + 1e-6 or host.x > 300.0, "位置应发生变化"
    assert abs(host.x - (ICON.left - host.w / 2 - 10)) < 2.0
    assert host.facing == "right"

    # 动作按意图依次播放过
    assert host.played[0] == "工作状态-原地踱步张望"
    assert "漂浮踏步" in host.played
    assert "工作状态-忙碌点按" in host.played
    assert "工作状态-清点归档" in host.played
    assert host.played[-1] == "工作状态-雀跃庆祝"

    # 气泡顺序
    assert host.bubbles[0] == "找到 Laji 啦"
    assert any("敲到了" in b for b in host.bubbles)
    assert host.bubbles[-1].startswith("开门营业")

    # 暖启动 + 按到了：按下本身就是"恢复窗口"，不再补发 deep link
    # （补发会让 Laji 重播 9 秒启动动画——这条是产品决定，不是漏调）。
    assert launched == []
    assert engine._pressed is True
    assert host.playback_speed == 1.0
    assert engine.state == wc.STATE_IDLE


def test_cold_launch_still_fires_deep_link_when_press_misses():
    """冷启动（进程没在跑）时按钮多半不存在，按不到就必须走 deep link。"""
    host = FakeHost()
    launched = []
    engine = wc.WorkEngine(
        host,
        locate=lambda: ICON,
        launch=lambda text="": launched.append(text) or True,
        running=lambda: False,
        press_laji=lambda: False,
    )
    assert engine.start("") is True
    run(engine)
    assert launched == [""]
    assert engine._pressed is False


def test_walk_speed_stays_physical_and_bounded():
    host = FakeHost(clip_seconds=10.0, stride_px=220.0)   # 1x 只有 22px/s
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True, running=lambda: True)
    engine.start()
    engine.tick(1 / 60)          # scan
    run(engine, seconds=1.2, until_idle=False)
    assert engine.state == wc.STATE_WALK
    assert host.playback_speed > 1.0
    assert host.playback_speed <= wc.Timeline().walk_speed_max


def test_floaty_gait_decouples_walk_from_playback_speed():
    """漂浮步态：位移按期望时长走完，动画倍速固定小值。

    真机根因：内置「左转奔跑」第 1~56 帧是原地转身（身体横躺 90°），56~118
    帧才位移。旧实现拿步幅（120px/10s ≈ 12px/s）反推倍速、撞上 6 倍上限，
    结果是"横躺 0.4 秒 → 猛冲一下 → 原地站 0.8 秒"循环播放——用户录屏里
    看到的"斜着 + 一卡一卡"就是这两个来源。
    """
    host = FakeHost(clip_seconds=10.04, stride_px=90.0, x=200.0, width=108.0)
    tl = wc.Timeline(walk_seconds=2.8)
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True, running=lambda: True,
                           timeline=tl)
    assert engine.start() is True
    assert engine._walk_name == "漂浮踏步"
    run(engine, seconds=1.2, until_idle=False)
    assert engine.state == wc.STATE_WALK
    # 位移速度按 2.8 秒走完剩余距离算，而不是 9px/s 的自然漂速
    assert engine._px_per_s > 100.0
    # 动画倍速是固定小值，不再被位移速度拽着跑
    assert host.playback_speed == tl.walk_anim_speed
    # 一趟位移里不该出现重播（重播 = 又从头飘一遍，视觉上会"卡一下"）
    assert host.played.count("漂浮踏步") == 1


def test_no_laji_icon_falls_back_to_start_button():
    """任务栏没有 Laji 按钮时，走去开始菜单翻，而不是"原地按一下"。

    真机背景：Laji 收在托盘（窗口 hide）时，任务栏按钮**会消失**。那时旧实现
    拿不到目标，直接进 press 播点按——用户看到的是"根本没动，只有头顶冒字"。
    """
    host = FakeHost()
    engine = wc.WorkEngine(host, locate=lambda: None,
                           launch=lambda text="": True, running=lambda: True,
                           locate_start=lambda: START_ICON)
    assert engine.start() is True
    assert engine._target_kind == "start"
    assert engine._target_x is not None          # 有落点 = 会真的走
    run(engine)
    assert "工作状态-原地踱步张望" in host.played   # 演的是"翻找"，不是"点按"
    assert host.x != 300.0                        # 真的挪了位置
    assert any("另找" in b or "翻" in b for b in host.bubbles)


def test_no_icon_at_all_still_launches_without_walking():
    """两处目标都找不到时，仍要把 Laji 拉起来——不能把她钉死在原地。"""
    host = FakeHost()
    engine = wc.WorkEngine(host, locate=lambda: None,
                           launch=lambda text="": True, running=lambda: True,
                           locate_start=lambda: None)
    assert engine.start() is True
    assert engine._target_x is None
    run(engine)
    assert host.x == 300.0


def test_walk_gives_up_when_clamped_by_work_area():
    host = FakeHost(x=300.0)
    host.left_limit = 300.0           # 一步也不许动（模拟身体被工作区钳死）
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True, running=lambda: True)
    engine.start()
    run(engine, seconds=8.0, until_idle=False)
    # 不许原地蹬腿到超时：0.4s 内就该放弃走位进入"按"
    assert engine.state in (wc.STATE_PRESS, wc.STATE_BOOT, wc.STATE_DONE,
                            wc.STATE_IDLE)


def test_launch_failure_stops_the_show():
    host = FakeHost()
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": False, running=lambda: False)
    engine.start()
    run(engine)
    assert engine.state == wc.STATE_IDLE
    assert engine.reason == "没找到入口"
    assert any("敲不动" in b for b in host.bubbles)
    assert "工作状态-雀跃庆祝" not in host.played   # 没开成就不庆祝


def test_launch_failure_plays_stall_not_silence():
    """按不动也拉不起时必须演「没找到」这一幕。

    旧实现走到这里直接 ``cancel()``：用户看完"敲了一下"就没了，既没有失败
    动作也没有结论句——和"站着不动"没差别。库里明明有「工作状态-垂头叹气
    冒汗」，只是没人调它。
    """
    host = FakeHost()
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": False, running=lambda: False)
    engine.start()
    run(engine)
    assert "工作状态-垂头叹气冒汗" in host.played, "失败必须播叹气，不许静默收手"
    assert host.played[-1] == "工作状态-垂头叹气冒汗"
    assert engine.reason == "没找到入口"
    assert any("不在家" in b or "没动静" in b for b in host.bubbles), "失败要说清哪一步没成"


def test_stall_line_differs_by_where_it_looked():
    """翻开始菜单 vs 敲任务栏，说的话不能一样——用户得知道她找过哪儿。"""
    host = FakeHost()
    engine = wc.WorkEngine(host, locate=lambda: None,
                           locate_start=lambda: START_ICON,
                           launch=lambda text="": False, running=lambda: False)
    engine.start()
    run(engine)
    assert engine.reason == "没找到入口"
    assert any("开始菜单也翻遍" in b for b in host.bubbles)


def test_boot_timeout_without_process_stalls_instead_of_celebrating():
    """22 秒都没等到进程，不能去雀跃——那是假报"开门营业"。"""
    host = FakeHost()
    engine = wc.WorkEngine(
        host, locate=lambda: ICON, launch=lambda text="": True,
        running=lambda: False,                      # 永远起不来
        timeline=wc.Timeline(boot_timeout_s=1.0, boot_poll_s=0.2),
    )
    engine.start()
    run(engine)
    assert "工作状态-雀跃庆祝" not in host.played
    assert "工作状态-垂头叹气冒汗" in host.played
    assert engine.reason == "启动超时"
    assert any("没人应门" in b for b in host.bubbles)


def test_cold_boot_finishes_when_process_appears():
    host = FakeHost()
    started = {"t": 0.0}
    engine = wc.WorkEngine(
        host, locate=lambda: ICON, launch=lambda text="": True,
        running=lambda: started["t"] >= 3.0,      # 3 秒后进程才起来
        timeline=wc.Timeline(boot_settle_s=0.6),
    )

    def mark(spent):
        if started["t"] == 0.0 and engine.state == wc.STATE_BOOT:
            started["t"] = 3.0

    engine.start()
    run(engine, on_tick=mark)
    assert "工作状态-雀跃庆祝" in host.played
    assert engine.state == wc.STATE_IDLE


def test_no_assets_declines_so_caller_can_fall_back():
    host = FakeHost(names={"随便什么"}, moves=[])
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True)
    assert engine.start() is False
    assert engine.active is False


def test_user_grabbing_pet_cancels_and_restores_speed():
    host = FakeHost(clip_seconds=10.0)
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True, running=lambda: True)
    engine.start()
    run(engine, seconds=2.0, until_idle=False)
    assert host.playback_speed > 1.0        # 已经在跑走姿
    host.behavior_state = "drag"
    engine.tick(1 / 60)
    assert engine.state == wc.STATE_IDLE
    assert engine.reason == "用户接管"
    assert host.playback_speed == 1.0


def test_choreo_for_refuses_secondary_sprites():
    class Shell:
        sprite = object()

        def show_bubble(self, *a, **k):
            return True

    assert wc.choreo_for(Shell(), Shell.sprite) is not None
    assert wc.choreo_for(Shell(), object()) is None    # 子宠不演
    assert wc.choreo_for(object()) is None             # 没有气泡面也不演


# ---------------------------------------------------------------- 真机回归
# 下面两条都是真机跑出来的缺陷，假宿主默认参数（每帧好几 px）永远碰不到。

class _Box:
    """QRect 的最小替身：只要 x/y/width/height 四件套。"""

    def __init__(self, x, y, w, h):
        self._r = (x, y, w, h)

    def x(self):
        return self._r[0]

    def y(self):
        return self._r[1]

    def width(self):
        return self._r[2]

    def height(self):
        return self._r[3]


class _Point:
    def __init__(self, x, y):
        self._x, self._y = x, y

    def x(self):
        return self._x

    def y(self):
        return self._y


class _Sprite:
    """真 PetSprite 的位置口径：``pos`` 是**画布左上角**（属性，不是方法），
    画布比身体大一圈（内置包 640×360 画布 / body_box=[212,60,428,330]，scale 0.5）。
    """

    def __init__(self):
        self.pos = _Point(100.0, 200.0)
        self.facing = "left"
        self.playback_speed = 1.0

    def rect(self):
        return _Box(0, 0, 320, 360)

    def body_rect(self):
        return _Box(106, 30, 108, 135)

    def body_local(self):
        return _Box(106, 30, 108, 135)

    def set_pos(self, p):
        self.pos = p


def test_host_reads_and_writes_body_center_not_canvas_origin():
    sprite = _Sprite()
    host = wc.ShellHost(object(), sprite)
    # 画布左上角 (100,200) + 身体偏移 (106,30) + 半个身体 (54,67.5)
    cx, cy = host.pos()
    assert (round(cx, 1), round(cy, 1)) == (260.0, 297.5)
    assert host.body_width() == 108        # 身体宽，不是画布 320
    host.set_pos(300.0, 400.0)
    assert (round(sprite.pos.x(), 1), round(sprite.pos.y(), 1)) == (140.0, 302.5)


def test_slow_walk_creeps_all_the_way_without_being_called_stuck():
    """每帧只挪 0.2px 时也要走完全程。

    真机实测：内置「左转奔跑」是 120px / 10.04s ≈ 12px/s，按单帧 `moved < 0.5`
    判钳制会立刻误判——她只走了 7px 就停在原地按，用户看到的是"根本没走过去"。
    """
    # 显式只给落地走姿：漂浮类会走「位移与动画解耦」分支，不再是蠕动速度
    host = FakeHost(moves=["左转奔跑"], clip_seconds=10.04, stride_px=120.0,
                    x=300.0, width=108.0)
    # 关掉地面速度下限、拉长期望时长 → 逼出"每帧 0.2px"的蠕动速度
    tl = wc.Timeline(walk_min_px_per_s=0.0, walk_seconds=100.0)
    engine = wc.WorkEngine(host, locate=lambda: ICON,
                           launch=lambda text="": True, running=lambda: True,
                           timeline=tl)
    assert engine.start() is True
    assert engine._target_x is not None
    target = engine._target_x
    run(engine, seconds=120.0, until_idle=True)
    assert abs(host.x - target) <= 1.0, f"只走到 {host.x}，目标 {target}"
    assert engine.reason == "完成"


class _DeskIcon:
    """桌面图标的替身（字段口径与 desktop_icon.DesktopIcon 一致）。"""

    name = "Laji Agent"
    left, top, right, bottom = 224, 331, 299, 384

    @property
    def center_x(self):
        return (self.left + self.right) // 2

    @property
    def center_y(self):
        return (self.top + self.bottom) // 2


def test_no_taskbar_button_goes_to_desktop_icon_and_double_clicks():
    """任务栏没按钮时，桌面上那个图标是真实可点的——走过去双击它。

    真机实测：Laji 收进托盘后任务栏按钮消失，但桌面 `Laji Agent.lnk` 一直都在
    （UIA 读得到坐标），双击就是真启动，比"走去开始菜单按一下、后台另开进程"
    诚实得多。
    """
    host = FakeHost(x=600.0)
    clicks = []
    engine = wc.WorkEngine(
        host,
        locate=lambda: None,                       # 任务栏没有 Laji
        locate_desktop=lambda: _DeskIcon(),        # 桌面有
        double_click=lambda x, y: clicks.append((x, y)) or True,
        launch=lambda text="": False,              # 双击已启动，不该再补 deep link
        running=lambda: True,
    )
    assert engine.start("") is True
    assert engine._target_kind == "desktop"
    run(engine)

    assert clicks == [(261, 357)], "双击的必须是图标中心（物理像素）"
    # 站在图标右侧、不压住它
    assert abs(host.x - (_DeskIcon.right + host.w / 2 + 10)) < 2.0
    assert host.facing == "left"
    assert engine.reason == "完成"


def test_desktop_icon_double_click_failure_still_fires_deep_link():
    """双击落空（图标被拖走/被窗口挡住）时不能干等，补 deep link。"""
    host = FakeHost(x=600.0)
    launched = []
    engine = wc.WorkEngine(
        host,
        locate=lambda: None,
        locate_desktop=lambda: _DeskIcon(),
        double_click=lambda x, y: False,
        launch=lambda text="": launched.append(text) or True,
        running=lambda: True,
    )
    assert engine.start("") is True
    run(engine)
    assert launched == [""]


# ---------------------------------------------------------------- 任意应用
class _Goal:
    """app_target.AppGoal 的替身：只保留引擎会用到的那几个字段。"""

    def __init__(self, label="豆包", kind="startmenu", left=60.0, right=120.0,
                 top=500.0, bottom=560.0):
        self.label = label
        self.kind = kind
        self.left, self.right = left, right
        self.top, self.bottom = top, bottom
        self.exe = ""
        self.lnk = ""
        self.calls = 0

    @property
    def center_x(self):
        return (self.left + self.right) / 2.0

    @property
    def center_y(self):
        return (self.top + self.bottom) / 2.0

    def activate(self):
        self.calls += 1
        return True


def _sync_activate(monkeypatch):
    """把「后台线程点亮」换成同步调用：测的是引擎时序，不要跟线程赛跑。"""
    from pet import app_target

    def _run(goal):
        if goal is not None and goal.activate is not None:
            goal.activate()
        return None

    monkeypatch.setattr(app_target, "activate_async", _run)


def test_goal_walks_lights_it_and_cheers(monkeypatch):
    """指定目标时：走到落点 → 播「按」→ 点亮一次 → 等门开 → 雀跃。"""
    _sync_activate(monkeypatch)
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: True)

    goal = _Goal()
    host = FakeHost(x=600.0)
    engine = wc.WorkEngine(host)
    assert engine.start("", goal) is True

    run(engine)
    assert goal.calls == 1, "必须真的点亮，且只点一次（点两次会开两个窗口）"
    assert engine.reason == "完成"
    # 站位：贴着 120 右缘、站在它右边
    assert abs(host.x - (goal.right + host.w / 2 + 10)) < 2.0
    assert host.facing == "left"
    assert "工作状态-忙碌点按" in host.played
    assert "工作状态-雀跃庆祝" in host.played
    assert any(goal.label in b for b in host.bubbles), "台词要念目标名，不许说 Laji"


def test_goal_lines_never_mention_laji(monkeypatch):
    """打开豆包时冒出的每一句都不许出现「Laji」——最刺眼的一版 bug。"""
    _sync_activate(monkeypatch)
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: True)

    host = FakeHost(x=900.0)
    engine = wc.WorkEngine(host)
    engine.start("", _Goal(label="豆包"))
    run(engine)
    assert not any("Laji" in b or "laji" in b for b in host.bubbles), host.bubbles


def test_goal_that_never_opens_stalls_with_reason(monkeypatch):
    """点下去了但窗口始终不来：走失败幕，并说清是"点了它不开"。"""
    _sync_activate(monkeypatch)
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: False)

    host = FakeHost(x=600.0)
    engine = wc.WorkEngine(host)
    engine.start("", _Goal())
    run(engine)

    assert engine.state == wc.STATE_IDLE
    assert "不开" in engine.reason
    assert any("不开" in b for b in host.bubbles)
    assert "工作状态-垂头叹气冒汗" in host.played, "失败要真的播叹气，不能只弹字"
    assert "工作状态-雀跃庆祝" not in host.played


def test_goal_kind_desktop_uses_double_click_path(monkeypatch):
    """桌面目标：走位用图标框，点亮交给 goal.activate（内部是双击）。"""
    _sync_activate(monkeypatch)
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: True)

    goal = _Goal(kind="desktop", left=200.0, right=240.0)
    host = FakeHost(x=700.0)
    engine = wc.WorkEngine(host)
    assert engine.start("", goal) is True
    run(engine)
    assert engine._target_kind == "desktop"
    assert goal.calls == 1
    assert abs(host.x - (goal.right + host.w / 2 + 10)) < 2.0


# ---------------------------------------------------------------- 三档节奏
def test_pace_timeline_cinema_is_untouched():
    """cinema 档必须与默认时间轴逐位相同——加档之前的行为不许动。"""
    base = wc.Timeline()
    cinema = wc.Timeline.for_pace(wc.PACE_CINEMA)
    assert cinema == base
    # 脏值/空值一律回 cinema，别猜
    assert wc.Timeline.for_pace("turbo") == base
    assert wc.Timeline.for_pace(None) == base
    assert wc.normalize_pace(" QUICK ") == wc.PACE_QUICK


def test_pace_quick_is_shorter_but_keeps_every_act():
    """quick 档只压时长，不许砍幕——她仍然要走过去、仍然要按下去。"""
    quick = wc.Timeline.for_pace(wc.PACE_QUICK)
    base = wc.Timeline()
    assert quick.walk and quick.animate and quick.talk
    assert quick.scan_s < base.scan_s
    assert quick.press_s < base.press_s
    assert quick.done_s < base.done_s
    assert quick.walk_seconds < base.walk_seconds


def test_pace_silent_skips_walking_and_clips():
    """silent 档：不走路、不播动作、不唠嗑（必要结论照说）。"""
    silent = wc.Timeline.for_pace(wc.PACE_SILENT)
    assert (silent.walk, silent.animate, silent.talk) == (False, False, False)
    assert silent.scan_s == 0.0 and silent.press_s == 0.0


def _opens_after_press(monkeypatch):
    """窗口可见探针：第一次（开演前）判"没开"，之后判"开了"。

    为什么不能一律 True：``start`` 里那次探测决定"本来就开着"——一律 True 会让
    每条安静档用例都走"已在前台直接收尾"，永远测不到点下去那一段。
    """
    state = {"n": 0}

    def _vis(_name):
        state["n"] += 1
        return state["n"] > 1

    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", _vis)
    return state


def test_silent_goal_stays_put_and_only_says_two_lines(monkeypatch):
    """安静档真机口径：她一动不动、一个动作都不播，只留"点它"/"开好啦"。"""
    _opens_after_press(monkeypatch)

    goal = _Goal()
    host = FakeHost(x=600.0)
    engine = wc.WorkEngine(host)
    assert engine.start("", goal, pace=wc.PACE_SILENT) is True
    run(engine)

    assert goal.calls == 1, "该点的还得点——安静不等于不干活"
    assert host.x == 600.0, "安静档不许移动（走位是演出的一部分）"
    assert host.played == [], "安静档一个动作都不播"
    assert len(host.bubbles) == 2, host.bubbles          # 点它 / 开好啦
    assert any("开好啦" in b for b in host.bubbles)
    assert engine.reason == "完成"


def test_silent_uses_quiet_activation_when_available(monkeypatch):
    """安静档优先走"不弹菜单"的直拉；直拉失败才退回弹菜单那条路。"""
    _opens_after_press(monkeypatch)
    from pet import app_target
    handed: list = []                      # 落到"弹菜单那条路"的目标
    monkeypatch.setattr(app_target, "activate_async", lambda goal: handed.append(goal))

    class _QuietGoal(_Goal):
        def __init__(self):
            super().__init__()
            self.quiet_calls = 0
            self.quiet_ok = True

        def activate_quiet(self):
            self.quiet_calls += 1
            return self.quiet_ok

    goal = _QuietGoal()
    engine = wc.WorkEngine(FakeHost(x=600.0))
    engine.start("", goal, pace=wc.PACE_SILENT)
    run(engine)
    assert goal.quiet_calls == 1
    assert goal.calls == 0, "直拉成功就不许再弹菜单（会开两次）"
    assert handed == [], "直拉成功就不该再排一次后台激活"

    # 直拉走不通（没有 exe/lnk）→ 退回正常路径，宁可慢也别不办
    _opens_after_press(monkeypatch)        # 换一份新探针：上一场已经把"已开着"用掉了
    goal2 = _QuietGoal()
    goal2.quiet_ok = False
    engine2 = wc.WorkEngine(FakeHost(x=600.0))
    engine2.start("", goal2, pace=wc.PACE_SILENT)
    run(engine2)
    assert handed == [goal2], "直拉失败必须补一次正常激活"


def test_silent_skips_press_when_target_already_up(monkeypatch):
    """已经开着的：安静档连点都不点，直接一句收尾（点它可能把它最小化）。"""
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: True)

    goal = _Goal()
    host = FakeHost(x=600.0)
    engine = wc.WorkEngine(host)
    assert engine.start("", goal, pace=wc.PACE_SILENT) is True
    run(engine)
    assert goal.calls == 0, "目标已在前台，不许再点"
    assert engine.reason == "完成"
    assert any("开好啦" in b for b in host.bubbles)


def test_quick_pace_finishes_sooner_than_cinema(monkeypatch):
    """同一场戏：quick 用的虚拟时间必须明显少于 cinema。"""
    from pet import app_target
    monkeypatch.setattr(app_target, "window_visible", lambda name: True)
    _sync_activate(monkeypatch)

    def play(pace):
        host = FakeHost(x=600.0)
        engine = wc.WorkEngine(host)
        engine.start("", _Goal(), pace=pace)
        return run(engine)

    quick = play(wc.PACE_QUICK)
    cinema = play(wc.PACE_CINEMA)
    assert quick < cinema * 0.75, (quick, cinema)
    # 幕序不变：quick 仍然播了「按」与「雀跃」
    host = FakeHost(x=600.0)
    engine = wc.WorkEngine(host)
    engine.start("", _Goal(), pace=wc.PACE_QUICK)
    run(engine)
    assert "工作状态-忙碌点按" in host.played
    assert "工作状态-雀跃庆祝" in host.played
