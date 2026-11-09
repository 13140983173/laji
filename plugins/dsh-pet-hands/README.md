# 伙伴的手（dsh-pet-hands）

让 Laji 的桌宠能真的看见并操作你这台电脑：读窗口控件树、点按钮、输入文字、截图。
动手之前它会先说一句「我准备点『保存』，可以吗」。

## 它解决的问题

桌宠原来只会**演**。要让它像人，它得能感知你桌面上真实发生的事，并且在你让它
帮忙时真的动手。这个插件把这两件事接进 Laji：

```
你的话 ──► 模型 ──► pet-hands MCP ──► cua-driver ──► 你的桌面
                                  └─► look.py（宿主侧，零 token）
```

## 前置条件

清单里声明了一条依赖：

```toml
[[dependencies]]
id = "cua-driver"
required = true
```

所以**装插件的时候窑主会自己把它备到位**，你不用先手动准备。三步：

1. `detect()` —— 先在 PATH 里找 `cua-driver`，再试 `%LOCALAPPDATA%\cua-driver`
   等常见目录；找到了还要 `cua-driver status` 是 running 才算可用。
2. `install()` —— 缺了就调官方安装器（Windows：`irm https://cua.ai/driver/install.ps1`；
   macOS/Linux：`curl … install.sh | bash`）。都不需要管理员权限。
3. `verify()` —— 再跑 `cua-driver doctor`，过了才算装好。

任何一步挂掉，插件安装当场报错，不会显示成「装好了」——空着 5 个工具让用户猜，
比安装失败难懂得多。Windows 安装器写的是**用户 PATH**，所以第一次装完要重启 Laji，
新进程才看得见它（`needsRestart`）。

清单里只有 `id`，没有 URL / 版本 / 安装命令：那三项一旦能由插件提供，装一个插件
就等于让它执行任意远端脚本。宿主只认 `apps/laji-agent/src/main/host-deps.ts` 白名单里的 id。

自动装失败时手动兜底：

```
cua-driver doctor
cua-driver autostart enable
cua-driver status      # 必须是 running
```

不在 `PATH` 里时设一个用户环境变量 `PET_HANDS_CUA_BIN=<可执行文件绝对路径>`——
`[[contributions.mcp]]` 没有额外的 env 传参通道可以给到它，只能靠继承宿主环境。

**不要**装 `cua-perception` 扩展：那是 AGPL-3.0-only，而 Cua Driver、daemon、
`cua` 命令、各语言 SDK 都是 MIT。本插件只用后者。

## 装进 Laji

插件目录：`packs/plugins/dsh-pet-hands/`，随应用打包。装完会有两条贡献生效：

| 贡献 | 落点 | 作用 |
|---|---|---|
| `[[contributions.mcp]]` | 自定义 MCP 配置里的 `pet-hands` | 给模型 5 个工具 |
| `[[contributions.skills]]` | `<lajiRoot>/skills/pet-hands/` | 教模型何时动手、何时先问 |

`server.py` 只用 Python 标准库，**不需要** `requirements.txt`，也不用建 venv：
清单里的 `command = "${python}"` 会落到插件 venv（没有则系统 Python）。

## Python 从哪来（装机前先看这段）

`${python}` 的展开链是 `venvPython(pluginDir) ?? findPython()`
（`apps/laji-agent/src/main/astrbot-bridge.ts:97`）。而 `findPython()` **只按 PATH 试**
`python3` / `python` / `py -3` 三个命令，**不会去扫安装目录**。

所以“用安装包装了 Python、但没勾 Add Python to PATH”的机器上，它会展开成裸 `python`，
spawn 直接 ENOENT，插件看起来装了却没有任何工具。两种解法：

1. **设 `LAJI_PYTHON`**（`findPython()` 的最高优先级，绝对路径直用）：

   ```powershell
   setx LAJI_PYTHON "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
   ```

   设完要重启 Laji（环境变量在启动时读）。

2. **在插件目录建 venv**（`venvPython()` 优先于一切）：

   ```powershell
   cd packs\plugins\dsh-pet-hands
   & "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
   ```

装完自检一条命令就知道通没通：

```powershell
python packs\plugins\dsh-pet-hands\look.py
```

能打出几行控件摘要 = 解释器和 cua-driver 都对了。报“找不到 python” → 走上面第 1 条；
报“找不到 cua-driver” → 回前置条件里那段手动兜底。

## 五个工具

| 工具 | 干什么 | 什么时候用 |
|---|---|---|
| `look` | 前台控件树 / 窗口列表 / 应用列表 | 动手前，或回答「我在干嘛」 |
| `act` | 点击 / 双击 / 右键 / 滚动 / 拖拽 / 输入 / 按键 | 已经用 `look` 看到了目标 |
| `run_steps` | 一次发多步动作 | 填表、连点，省往返 |
| `screen` | 截图存 PNG，只回路径 | 控件树是空壳（Canvas / 游戏） |
| `raw` | 透传任意 cua-driver 原生工具 | 上面盖不到时 |

三条设计约束：

- **截图永远落盘**。`park_blobs()` 把长 base64 解码成 PNG 写到
  `%LOCALAPPDATA%\laji\pet-hands\shots\`，模型只拿到路径（实测 `get_window_state`
  不是每次都带图，只有 `include_screenshot: true` 才带；CLI 还有 `--screenshot-out-file`）。
- **结果超过 12000 字符就截断**，并告诉模型怎么缩小范围（先 `scope=windows`）。
- **失败回 `isError` 而不是崩溃**。daemon 没起时模型读到的是
  「执行 `cua-driver autostart enable`」，不是一句死掉的堆栈。

## 不走模型的那条路：`look.py`

`server.py` 是给**模型**用的，每调一次都是一轮工具往返。`look.py` 是给**程序**用的：

```powershell
python packs/plugins/dsh-pet-hands/look.py                 # 前台摘要，几行
python packs/plugins/dsh-pet-hands/look.py --scope windows  # 窗口列表
python packs/plugins/dsh-pet-hands/look.py --json           # 原始结构，排查用
```

输出是压缩过的（去掉 `pane`/`group` 这类容器噪音，只留带名字的控件），**零 token**。
桌宠想“知道你在干什么”、想判断该不该搭话，走这条。

## 边界（重要）

- **闲聊面默认用不了这些工具**。`[context.chat_surface] allow_mcp = false` 是默认值，
  为了防止 MCP 的 schema 把闲聊的 prompt 撞大。想对着桌宠直接说“帮我点那个按钮”，
  得把这项打开；否则在带工具的工作面（coding / agent 面）里用。
- **能力就是这五个动词**。没有录制宏、没有光标主题、没有跨屏拖拽——不是没做完，
  是不想把 60 多个工具的 schema 和攻击面都挂给模型。真要那些，用 `raw` 单个透传。
- **它真的会动你的电脑**。没有沙箱：`act` 点下去就是真点击。安全的依赖是
  “不可逆动作先问”那条技能规则 + 宿主自己的审批链，不是 MCP 这层。

## 实测结论（2026-11，cua-driver 0.38.0，Windows 11）

写第一版时手上没有运行中的驱动，表里原本全是「按文档假设」。下面是真机跑完的结果。

| 项 | 假设 | 实测 |
|---|---|---|
| CLI 形态 | `cua-driver call <tool> <json>` | ✅ 成立。注意 PowerShell 5.1 会剥掉 JSON 引号，必须走 stdin：`'{"pid":1}' \| cua-driver call get_window_state` |
| exit code | `1` = daemon 未运行 | ⚠️ 未验证（没停 daemon）。但拒绝时的 stdout 确实是 JSON（`{"refusal":{…}}` 或 `{"code":…}`），`_driver_error_text` 的解析方向对 |
| 原生工具名 | 8 个 | ⚠️ 都存在，但 `get_accessibility_tree` **语义不同**：它是「桌面概览：进程 + 可见窗口」，不是前台控件树（见下） |
| 参数名 | `element_token` / `include_screenshot` / `app` / `window_id` | ✅ 全部成立；`element_token` 形如 `s00000002:0`（`<snapshot_id>:<row>`） |
| 截图字段 | base64 内联 + `saved_to` | ❌ 不是。`get_window_state` 回的是结构化 JSON，截图要 `include_screenshot: true` 才带；CLI 还有 `--screenshot-out-file` 直接落盘 |

### 跑出来的五个真问题

1. **`look` 默认档接错了工具（已修）。** `front` → `get_accessibility_tree` 拿到的是
   `smss.exe` / `csrss.exe` 这样的进程清单，21880 字符，一个控件都没有。
   现在改成 `list_windows` 选前台 → `get_window_state`：同一个 Chrome 窗口
   给出 `[0] Button "最小化"` 这类真控件。
2. **`key` 强制前台是错解（已修）。** `press_key` 走 PostMessage，不更新修饰键状态，
   `ctrl+a` 只会打出字符 `a`；而原来的补偿是 `delivery_mode: foreground`，等于整轮
   抢走焦点。现在组合键改走 `hotkey`（XAML 走 UIA accelerator，Win32 走 SendInput
   且只做一次短暂前台交换后恢复），background 被拒才升级一次 foreground。
3. **体积差 60 倍。** 同一个 Typora 窗口：`tree_markdown` 1314 字符、`elements`
   78062 字符、误用的 `get_accessibility_tree` 21880 字符。摘要只取 markdown。
4. **点击被拆成了三次往返（已修）。** `get_window_state` 从 0.35 起默认只回
   `tree_markdown`，**不带 element_token**；而 markdown 里的 `[3]` 只是行号。
   于是模型要点一个按钮得走 `look` → `look(scope=tree)`（78KB）→ `act`，
   每次 1.5–3.8s，这就是“不流畅”的真因。驱动文档写明了
   `element_token = <snapshot_id>:<row>`，所以现在插件自己记 `snapshot_id`，
   `act` 直接收 `element_index=3`，把那一跳去掉（技能文档也改成了三步）。
   更进一步：`act` 也收 `name` / `role`（"点保存"这种已知操作），由驱动自己
   读树、等元素、定位——连那一次 `look` 都省了，实测单次 1.0s（前台投递 2.3s）。
   注意 `run_steps` 的前台投递要求目标窗口已经是前台，否则直接回
   `foreground_unavailable`；插件在 `delivery_mode=foreground` 时先 `bring_to_front`。
5. **WinUI3 上一次“成功”的点击可能什么都没干。** 记事本（WinUI3）标题栏的
   `Button "最大化" actions=[invoke]`：后台点击返回 `delivery.mode=background` +
   `effect=unverifiable`，**不报错**，但窗口边界 1426x721 一动不动；同一 token
   加 `delivery_mode=foreground`（SendInput, route=global_input）
   一次就变成 1920x1010。另发现两个坑：
   - `element_token` 和 `window_id` **不能一起下发**：两个都给会被当成坐标点击走
     `synthetic_events`（也是 no-op）。现在有 token 就不带 `window_id`。
   - `act` 里 `app` 曾被原样透给驱动（`click: unknown argument app` 整批被拒），
     而且 `app` 从未参与目标解析。现在统一在 `_resolve_target` 里解析成
     `pid`/`window_id`，`app_name`/`title` 不下发。

   因为驱动不会把这种 no-op 当错误，插件把“怎么升级”写进了回包的 `next` 字段，
   并把 `delivery_mode` 提成了 `act` 的一等参数（默认仍是 background，不抢焦点）。

### 延迟实测（2026-11，cua-driver 0.38.0，Windows 11）

同一条链路上逐项量过（记事本 + Chrome，前台/指定 app 两种解析都测）：

| 操作 | 改之前 | 改之后 |
| --- | --- | --- |
| `look` 前台窗口（不带 app） | 4387 / 6577 / 4686 ms | 1027 / 1039 / 1239 ms |
| `look` 指定 app | 4194 / 2197 / 1061 ms | 1036 / 1182 / 1473 ms |
| `act` 一次点击（含解析目标） | 4753 ms | 1037 ms |
| 一次「看一眼 + 点一下」 | ~10s（还得先多跳 2 次） | ~2.1s |

钱花在哪，改成什么：

1. **每次解析目标都跑一次 `list_windows`（3.0–3.8s）。** 改成前台窗口用
   `GetForegroundWindow`（微秒级）、按 app 找窗口用 `EnumWindows`（本地系统调用）。
2. **`get_window_state` 默认 `include_screenshot: true`**，多花 ~0.6s 还把 base64 写盘。
   `look` 现在默认关掉；要图用 `screen`（它才真落盘并返回路径）。
3. **文档类窗口会把整篇正文内联进 markdown**：记事本打开 1278 行的 txt 时
   markdown 是 **75860 字符**，而可点的只有 74 个元素。现在 `_shrink_markdown()`
   把 `[N]` 行全留、正文续行限流 → **7950 字符**，且实测 `[71][72][73]` 标题栏按钮一个没丢。
4. **超长回包以前是硬切字符串**，会把 JSON 切断。现在按字段长度逐级收窄，结构始终完整。

剩下的地板：驱动自身的 UIA 走查 ~0.9–1.5s，避免不了（除非走 `browser_*` 的 DOM 快路径）。
`act` 的每次调用仍是一个新 Python 进程，冷启动成本比 Windows-MCP 这类常驻进程高。

### 体积预算（比延迟更容易出隐问题）

驱动默认 `max_elements: 250`，这是个 **节点** 预算，不是元素数。实测 Laji 窗口里
它只走完 173 个元素，而完整树是 500 个（`truncated: node_budget`）。
模型看不见的按钮，它会当成不存在——所以现在 `look` 会明说“还有节点没走完”，
并给出 `extra={"max_elements":800}` / `extra={"query":"…"}` 两条退路。

回包体积现在分三层控制，且**每一层都不切 JSON**：

| 层 | 作用 | 实测效果 |
| --- | --- | --- |
| 单行截断 200 字符 | 终端/日志回显被内联成一个节点的 name | 2KB 单行 → 214 字符 |
| 字符预算 9000 | 编号行优先，续行让位 | Laji 窗口 86562 → 9196 字符 |
| `render()` 按字段收窄 | 只在超 12000 时才动手，保持结构完整 | 10700 字符，不再半截 JSON |

超预算时可点元素会被截掉，但会明确报“还有 N 个可点元素没列出，不代表不存在”。
`scope=tree` 的退路分支同样封顶 200 个 elements（原单窗口 78062 字符）。

## 许可

本插件 MIT。它**调用**本地安装的 Cua Driver（MIT），不捆绑任何 Cua 代码。
完全不用 FSL-1.1-MIT 那部分（Cua Spaces / Keyvault / teleport / streaming）。
