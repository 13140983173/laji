# 桌宠「找 Laji」设计与实现方案

> 目标：桌宠点「打工」时，不是黑箱里弹出一个窗口，而是**当着用户的面把另一个应用找出来、叫醒**。
> 状态：设计定稿，待实现。真机已验证的部分会标 ✅，未验证的标 ⚠️。

---

## 1. 一句话结论

内部 11ms 就知道 `LajiAgent.exe` 在哪，但这**不能**用来省掉过程。
屏幕上必须演满约 3.9 秒：走近 → 按开始 → 进搜索框 → 逐字打 `laji` → 指着结果戳开 → 雀跃。

「知道答案」和「演一遍找答案」不矛盾，是两条互不干扰的轨。

---

## 2. 问题：现在为什么"走到搜索框就停了"

真机日志（`probe_live2`，2026-10-31）：

```
[15.15s] ③ choreo.start() -> True  kind=desktop target_x=362.6
[28.56s]  press  spr=(203,506) faced=left pressed=True launch=True
[28.97s]  press  ...
[29.78s]  boot   ...          ← 按完直接进等待，中间什么都没有
[32.63s] ④ 结束 reason= 窗口可见=False
```

三个结论：

1. **不是权限问题。** 桌宠进程与用户同权限，`SendInput` 全局键盘、UIA 点任意控件、起 `explorer` 全都做得到。日志里 `pressed=True launch=True` 说明按下去是成功的。
2. **是代码缺口。** `press` 阶段结束后直接 `_enter(STATE_BOOT)` 等窗口可见，中间**没有"输入 / 认结果 / 点结果"任何一环**。用户看到的"走到搜索框"其实是走到了开始按钮旁边，然后没有任何后续动作。
3. **走路太慢。** 内置素材 `左转奔跑` 步速只有 12px/s，倍速上限 6× 也只能到 68px/s，780px 要走 11.5 秒。这段必须换运动方式，不是调参数。

---

## 3. 设计原则：双轨制

| 轨 | 耗时 | 职责 | 是否可见 |
|---|---|---|---|
| **内轨 know** | ~11ms | 决定"去哪找、找到没有、失败了退哪一级" | 不可见（只进日志） |
| **外轨 show** | 3.9s（cinema） | 决定"看起来怎么找" | 全程可见 |

内轨的结论**只用于校验和兜底**，不用于跳过演出。
外轨的每一幕都必须有对应的真实系统调用——演的是假的"思考"，做的是真的操作。

---

## 4. 内轨：怎么查找（真实来源，按优先级）

| 优先级 | 来源 | 实现 | 实测 |
|---|---|---|---|
| 1 | 开始菜单 lnk 内嵌明文路径 | 读 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\**\*.lnk` 里的路径字节 | ✅ 11ms 命中 `D:\tmp\LajiAgent\LajiAgent.exe` |
| 2 | 安装根目录已知位置 | `%LOCALAPPDATA%` / `Program Files` 下一层扫 `LajiAgent.exe` | ✅ |
| 3 | 运行中进程 | 枚举进程 exe 路径 | ✅ |

同时探测三件事（决定走哪一幕）：

- `laji_running()`：进程是否存活
- `taskbar_icon.locate()`：任务栏有没有她的按钮（窗口 hide 后按钮会消失，所以这一项常为空）
- `desktop_icon.locate()`：桌面有没有快捷方式（`FindWindowEx(Progman→SHELLDLL_DefView→SysListView32)`，0.2ms 拿句柄 + 20ms `ElementFromHandle`；✅ 实测 180ms 全流程）

⚠️ UIA 在 DPI-aware 进程返回**物理像素**（1920×1080），而 `sprite.pos` 活在 Qt 逻辑像素（1280×720）。所有坐标必须除以 `devicePixelRatio`，否则落点整体偏 1.5 倍。

---

## 5. 外轨：五幕演出

预算是 3.9s（cinema）。每幕都是"动画 + 真实调用"成对出现。

### 幕 1 · 走近（0.0 – 1.3s）

- 动作：抬头 → 思考气泡「Laji 在哪呢」（≤0.45s，再长就像卡了）→ 滑行到开始按钮左侧
- 真实调用：`sprite.set_pos()` 逐帧插值
- **关键决定：不播步行动画，用滑行/连跳。** 距离 >400px 时切"连跳"（3 段弧形，每段 0.25s），<400px 时才播走姿 clip。
- 落点：开始按钮中心 −78px（身体中心口径，不是画布左上角）

### 幕 2 · 按开始（1.5s）

- 动作：气泡「按一下开始」→ 任务栏按钮下压 140ms
- 真实调用：`UIA ToggleButton.Toggle()`
- ✅ 已验证：`pressed=True launch=True`，菜单真的弹出来
- ⚠️ 坑：开始按钮是 ToggleButton，`GetCurrentPattern(Invoke)` 返回空指针，只能 `Toggle()`

### 幕 3 · 进框打字（1.9 – 2.4s）

- 动作：搜索框焦点高亮 + 宠物手指伸向搜索框 → 逐字输入 `laji`
- 真实调用：`SetFocus()` on `SearchTextBox` → 逐字符 `SendInput`（VK + scan code）
- 节奏：每字 95ms ± 25ms 随机抖动（固定间隔会显得机械）
- ⚠️ 未验证：Win11 开始菜单是 XAML 岛，`SendInput` 能否稳定吃进搜索框必须先单点验证（见 §9）
- 保险：若 `SendInput` 不生效，降级用 `ValuePattern.SetValue("laji")`（少了逐字感，但能出结果）

### 幕 4 · 认结果（2.4 – 2.9s）

- 动作：结果列表浮现 → 宠物举手指向命中项 → 念一句
- 真实调用：UIA 读 `SearchApp` 窗口的 ListItem，比对 `Name`
- 等待：结果异步渲染，轮询 0.6～1.2s；超时按"零结果"处理
- **保留一次"看错"**：首条是「Laji Agent 帮助文档」时，先指它、念"咦，这是文档…"，再移到第二条「Laji Agent」。一击必中反而假。

### 幕 5 · 戳开收尾（2.9 – 3.9s）

- 动作：宠物前倾戳一下 → 结果项闪一下 → 菜单收起 → 主窗出现 → 雀跃 + 「找到啦！」
- 真实调用：`InvokePattern.Invoke()` → `agent_window.visible()` 轮询 → 收尾
- **绝不动真实光标**：`Invoke()` 不移动鼠标，不抢用户的指针
- ⚠️ 冷启动 8～19 秒：这段不能干站着，沿用 `BOOT_LINES`（0 / 3.6 / 7.6s 三条进度台词 + 张望动作）

---

## 6. 降级链（找不到怎么办）

| 级 | 判断 | 动作 | 耗时 |
|---|---|---|---|
| 1 | 任务栏有按钮 | 按一下就回来，不搜索 | 1.9s |
| 2 | 开始菜单搜得到 | 按开始 → 打字 → 戳结果 | 3.9s |
| 3 | 结果里有但不是头条 | 逐条比名字，点对的那条 | +0.4s |
| 4 | 零结果 | 飞回桌面双击快捷方式 | 5.4s |
| 5 | 桌面也没有 | `explorer /select,"<exe>"` 打开目录 + 摊手说话 | 1.2s |

第 5 级的原则：**嘴上认输，手上给路。** 不装死，把 exe 位置摆到用户眼前。

---

## 7. 三档节奏（已实现，2026-10-31）

设置项：`open_app_pace`，默认 `cinema`（设置 → 自动化与联动 → 打开应用 → 演出节奏）

档位定义只有一份：`pet/work_choreo.py` 的 `PACE_CHOICES / PACE_LABELS / Timeline.for_pace`；
设置页（`pet/settings_open_app.py`）、配置清洗（`config.normalize_open_app_pace`）、
演出引擎三处共读，不会出现"设置里写着快，演出来是完整"。

| 档位 | 真机实测（打开豆包，冷启动） | 行为 |
|---|---|---|
| `cinema` | **8.8s** | 六幕全演：看她一眼 → 走过去（约 2.8s）→ 播「忙碌点按」真按开始菜单 → 翻到它 → 等开门 → 雀跃 |
| `quick` | **5.5s** | 幕序不变、动作照播，每幕时长压到一半上下，走路 1.5s 到位 |
| `silent` | **3.3s** | 不走路、不播动作、不唠嗑；**不弹开始菜单**（`AppGoal.activate_quiet` 直拉 exe / shell 打开 lnk），只留「点它」「开好啦」两句 |

**三档都不砍失败判据**：降档降的是"看不看得到过程"，不是"它到底开没开"。
`silent` 已经在前台时连点都不点（点一个已激活的窗口可能把它最小化），直接一句收尾。

> 设计期乐观估计是 cinema 3.9s / quick 0.9s / silent 0.25s。真机上做不到那么短：
> `silent` 省掉了走路与菜单（2×~1.6s），但**等应用真的画出窗口**是真实时间
> （豆包冷启动 ~2s），那一段不该被"压"——压它就是假报开门。所以数字按实测重写。

quick / silent 仍然"看起来在做事"，只是把过程压缩，不是黑箱。

---

## 7.5 两个入口，同一条演出（2026-10-31）

「打开 X」有两个入口，落到**同一个** `open_named_app` → `work_choreo`：

| 入口 | 谁在听 | 什么时候出发 |
|---|---|---|
| 桌宠气泡（`quick_chat`） | 桌宠进程自己：`open_intent.parse(text)` | 气泡里一回车就起步，不等模型 |
| Laji 主聊天窗（Composer / 新建任务） | 宿主主进程：`main/open-intent.ts` 的 `parseOpenIntent` | 消息投向 Agent **之前**就地认出（`dispatchSession` 的 send / beginTask） |

主聊天窗这条链路：

```text
renderer  postSession({type:"send", text})
   → main   dispatchSession → parseOpenIntent(text)   ← 本地规则，0 延迟、不问模型
   → 命中   写一行 pet-link/laji.jsonl：{event:"pet/open-app", app:"豆包"}
   → 桌宠   CustomAgentMonitor tail 到 → AgentLinkManager._on_pet_command
   →         app.open_named_app("豆包") → 走过去 / 点亮（与气泡完全同一条）
```

三条边界，都是为了不把事情做复杂：

1. **走事件文件而不是新开 IPC**：宿主与桌宠是两个进程，`pet-link/laji.jsonl`
   是唯一已经存在的下行通道；指令行只带**应用名**（正文不出主进程）。
2. **不参与状态机**：`pet/open-app` 在 `normalize_event_state` 里不认识 → 返回空，
   不改动画、不误报 working；只有 `_on_pet_command` 认它。
3. **重投不重开**：桌宠按 `(应用名, ts)` 记住最近一条，文件轮转/重连回灌不会开第二遍；
   新指令（新 ts）照常执行——「再开一次」是合法诉求。

**已知边界**：模型并不知道桌宠已经接管，它仍可能自己 spawn 一次（甚至写 ps1 再验证进程）。
那是"第二个执行者"，不是这条链路的失败；要消掉它得在提示词层告诉模型「桌面应用由桌宠打开」。

---

## 8. 交互细则（顺滑靠这几条）

1. **起步不拖**：思考气泡 ≤0.45s，动作立刻接上。超过 0.5s 的静止会被读成"卡了"。
2. **不移动真实光标**：全程 `Invoke` / `SendInput`，用户鼠标指针不动。
3. **可打断**：用户抓宠物、拖拽、扔出去 → 立刻 `cancel()`（已有 `_USER_STATES` 机制）。
4. **礼貌规则**：最近 1.5s 内有键鼠输入 → 自动降档（cinema → silent）或延后 3s 再演。桌宠帮忙的前提是不添乱。
5. **失败也要有话说**：每一级降级都配一句台词，不能静默重试。

---

## 9. 三个必须避开的坑

### 坑 1 · 会开两次窗口

`Invoke()` 结果项本身已经启动进程。若再调 `open_laji_in_background()` 补一刀，就是双开 + 重播启动动画。
**规则：戳成功 → 跳过 deep link。** 现有 `_fire_launch()` 调用点要加条件。

### 坑 2 · 中途取消留半截字

用户抓住宠物时 `cancel()` 只把状态切回 idle，搜索框里还留着 `laj`、开始菜单还开着。
**规则：cancel 必须清理** —— `Esc` 关菜单 + 清空输入 + 宠物站直。

### 坑 3 · 抢用户焦点

演出会强占键盘焦点。如果用户此刻正在打字，我们会打断他。
**规则：见 §8.4 礼貌规则**，切档前先看最后一次输入时间。

---

## 10. 代码改动清单

目录：`Nerve-agent/Laji/packs/plugins/dsh-pet/src/pet/`

| 文件 | 改动 |
|---|---|
| `work_choreo.py` | `PRESS` 与 `BOOT` 之间插 `STATE_SEARCH`；`_target_kind == "start"` 时不再"按完就 launch"；新增 `search_s` 等时间参数 |
| `start_search.py`（新增） | `open()` / `focus_box()` / `read_results()` / `invoke(item)` / `dismiss()` |
| `screen_input.py`（新增） | `type_text(str)` 逐字 `SendInput`；`key(vk)`；单/双击 |
| `agent_locator.py` | 已有，`find()` 复用，无需改 |
| `desktop_icon.py` | 已有 `double_click()`，无需改 |
| `taskbar_icon.py` | 已有 `press_start()` / `dismiss_start()`，无需改 |
| `app.py` | `open_laji_work()` 里接 `laji_find_style` 设置项 |

保持"不碰 Qt 的纯逻辑 + 可注入假宿主"的分层：`WorkEngine` 里新增的阶段仍只调 `host.*` 和注入进来的一批 callable，测试用假宿主跑完整时间轴。

**主聊天窗接管（2026-10-31 新增，见 §7.5）落在宿主侧**，不在本目录：

| 文件 | 改动 |
|---|---|
| `apps/laji-agent/src/main/open-intent.ts`（新增） | `parseOpenIntent(text)`：与 `pet/open_intent.py` 同口径的保守规则；主进程就地认「打开 X」 |
| `apps/laji-agent/src/main/pet-dsh.ts` | `openApp(name)`：写指令行 `{event:"pet/open-app", app}`；指令行不参与状态去重 |
| `apps/laji-agent/src/main/ipc.ts` | `IpcDeps.onUserPrompt`：`dispatchSession` 在投递 send / beginTask 之前旁路通知（不阻断） |
| `apps/laji-agent/src/main/index.ts` | 注入：命中 → `dshPetRef.openApp(app)` |
| `pet/agent_link/__init__.py` | `_on_pet_command`：`pet/open-app` → `open_named_app`；按 `(应用名, ts)` 挡重投 |

---

## 11. 时间参数默认值

| 参数 | 默认 | 说明 |
|---|---|---|
| `think_s` | 0.45 | 思考气泡停留 |
| `walk_seconds` | 0.8 | 期望滑完的时间（反推速度） |
| `walk_min_px_per_s` | 240 | 屏幕尺度滑行下限（原 30 太慢） |
| `hop_px` | 400 | 超过这个距离改用连跳 |
| `press_s` | 0.25 | 按下到菜单弹出 |
| `type_gap_ms` | 95 | 每字间隔（±25 抖动） |
| `result_wait_s` | 1.2 | 等结果渲染上限 |
| `poke_s` | 0.2 | 戳一下 |
| `boot_settle_s` | 0.8 | 窗口出现后再等两口气 |
| `total_cinema_s` | 3.9 | 到"雀跃"为止的预算 |

---

## 12. 验证计划（分三步，不许跳）

**第 1 步 · 单点验证打字（必须先过）**
打开开始菜单 → 找 `SearchTextBox` → `SetFocus` → `SendInput` 打 `laji` → 读结果列表 → `Esc` 关闭。**不点任何东西。**
过不了这一步，后面全是空演。

**第 2 步 · 干跑整条时间轴**
假宿主跑 `WorkEngine` 的五个状态，断言每幕耗时、每幕调用次数、`Invoke` 后没有多余 launch。

**第 3 步 · 真机端到端**
把 Laji 收进托盘 → 右键「打工」→ 录屏看全程；检查：单开、无半截字、用户鼠标不动。

---

## 13. 风险与未决

| 项 | 状态 | 备注 |
|---|---|---|
| `SendInput` 能否入 Win11 搜索框 | ⚠️ 待验证 | 第 1 步解决；备选 `ValuePattern.SetValue` |
| 搜索框 UIA 名称随系统语言变化 | ⚠️ 待验证 | `zh-CN` / `en-US` 的 `Name` 不同，需按 `AutomationId` 找 |
| 开始菜单弹出动画期间能否立即 SetFocus | ⚠️ 待验证 | 可能要等 ~250ms |
| 滑行是否破坏现有走姿节奏 | 待定 | 需要实机看一段再定 hop vs walk 的分界 |
| 冷启动 8～19s 的等待体感 | 待优化 | 现有三条进度台词可再加"张望"动作 |

---

## 附录

- 交互原型：`.workbuddy/scratch/laji-pet-find-flow-prototype.html`（四个剧本 + 0.5× 慢放 + 实现映射表）
- 真机探针：`.workbuddy/scratch/probe_live2.py`（端到端）、`probe_start_patterns.py`（开始按钮模式）
- 已有排错文档：`RUNBOOK.md`
