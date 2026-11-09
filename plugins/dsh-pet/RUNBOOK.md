# 桌宠运行与打包手册

桌宠（dsh-pet）在本仓有两种跑法：**本地跑源码**（改代码即时生效，日常开发用）和 **打包成 exe**（交付/给同事试用）。本文给出两条路的准确命令、产物位置和踩过的坑。

---

## 0. 速查

| 用途 | 位置 |
| --- | --- |
| 仓库根 | `D:\workspace\waf\Nerve-agent\Laji` |
| 插件目录 | `packs\plugins\dsh-pet` |
| 源码 | `packs\plugins\dsh-pet\src` |
| Python 环境 | `D:\workspace\waf\.venvs\dsh-pet`（Python 3.13.14） |
| 打包脚本 | `packs\plugins\dsh-pet\build_laji_pet.py` |
| 打包产物 | `packs\plugins\dsh-pet\bin\laji-pet\laji-pet.exe`（onedir，必须整个目录） |
| 配置与日志 | `%APPDATA%\dsh-pet-standalone-laji\` |
| 素材 | `packs\plugins\dsh-pet\src\assets\characters\shenshen\` |

---

## 1. 环境准备（只需一次）

依赖：PySide6-Essentials + **PySide6-Addons**、Pillow、imageio-ffmpeg、grpc、protobuf、comtypes、keyring、psutil 等，清单见 `src/requirements.txt`。

> 两个 PySide6 包都要装（同版本）：`multimedia` 只在 Addons 里，而语音报时/「立即试听」的播放出口
> （`chime_service._ensure_player`）只有 `QMediaPlayer` 一条路。只装 Essentials 时构建不会报错，
> `--collect-all` 只能收个寂寞，产物里就没有 `Qt6Multimedia.dll`；症状是**合成成功却一声不响**
> （2026-10-31 实机定位）。验证一行：`python -c "import PySide6.QtMultimedia"`。

```powershell
# 建环境
"C:\Users\EDY\.workbuddy\binaries\python\versions\3.13.12\python.exe" -m venv "D:\workspace\waf\.venvs\dsh-pet"

# 装依赖（国内用阿里云镜像，PyPI 官方源只有几十 KB/s）
cd "D:\workspace\waf\.venvs\dsh-pet"
.\Scripts\python.exe -m pip install -i https://mirrors.aliyun.com/pypi/simple/ `
    PySide6-Essentials PySide6-Addons Pillow imageio-ffmpeg keyring pywin32-ctypes certifi `
    pycaw tzdata lunar-python psutil grpcio protobuf comtypes pytest ruff pyinstaller
```

验证：

```powershell
D:\workspace\waf\.venvs\dsh-pet\Scripts\python.exe -c "import PySide6, PIL, comtypes, grpc; print('deps ok')"
```

> 环境会被安全软件误杀清空（历史上发生过两次，和 `laji-dev\...\node_modules` 一起没的）。报「缺模块」时先确认目录还在，别急着改代码。

---

## 2. 本地跑源码（不打包，日常开发用）

```powershell
cd D:\workspace\waf\Nerve-agent\Laji\packs\plugins\dsh-pet\src
D:\workspace\waf\.venvs\dsh-pet\Scripts\python.exe -m pet
```

改 `src\pet\**`、`src\assets\**` 后**重启进程**即可生效，不需要重新打包。

### 2.1 在 IDE / 终端里启动时必须清环境变量

如果是从 Claude/WorkBuddy 这类宿主的终端里启动，宿主会注入三个变量，会把桌宠的拉起链路弄坏：

```powershell
$env:PYTHONPATH = $null            # 宿主的安全删除 shim，会让桌宠清理 frameseq 时被拦截
$env:NODE_OPTIONS = $null          # --require node-language-shim.cjs，同上
$env:ELECTRON_RUN_AS_NODE = $null  # 桌宠拉起的 Electron 会被当 Node 跑，崩在 app.setName
```

在**普通 PowerShell 窗口**或双击启动时没有这个问题，不用处理。

### 2.2 不想看到控制台窗口

```powershell
cd D:\workspace\waf\Nerve-agent\Laji\packs\plugins\dsh-pet\src
D:\workspace\waf\.venvs\dsh-pet\Scripts\pythonw.exe -m pet
```

`src\run.bat` 就是这一条的封装（用系统 PATH 里的 `pythonw`，没激活 venv 时会失败）。

### 2.3 停止

```powershell
taskkill /IM laji-pet.exe /F      # 打包版
Get-Process python | Where-Object { $_.Path -like "*dsh-pet*" } | Stop-Process -Force   # 源码版
```

---

## 3. 打包

```powershell
cd D:\workspace\waf\Nerve-agent\Laji
D:\workspace\waf\.venvs\dsh-pet\Scripts\python.exe packs\plugins\dsh-pet\build_laji_pet.py
```

- 脚本会先 `taskkill` 掉旧的 `laji-pet.exe`（否则 `_internal` 里的 DLL 被锁），再调 PyInstaller。
- 构建清单（收哪些包、哪些数据、排除什么）**只在 `src\laji-pet.spec` 一处**，别在命令行上再加 `--collect-all`。
- 耗时约 **4~5 分钟**，产物 `bin\laji-pet\laji-pet.exe`，整个目录约 **707 MB**（2026-10-31 实测；其中素材 `assets` 占 460 MB，Qt 占约 44 MB）。
- 打完后 `bin\laji-pet\` 会被整体替换，**旧的不会自动备份**。要留底先手动改名：

```powershell
Move-Item "packs\plugins\dsh-pet\bin\laji-pet" "packs\plugins\dsh-pet\bin\laji-pet.prev-20261031"
```

### 3.1 onedir，不能单独拿走 exe

产物是 `--onedir`：`laji-pet.exe`（13.4 MB）只负责引导，真正的东西在旁边的 `_internal\`（Qt、Python 运行时、素材）。**拷给别人要整个 `laji-pet` 文件夹**，只发 exe 会启动即崩。

### 3.2 启动打包版

```powershell
& "D:\workspace\waf\Nerve-agent\Laji\packs\plugins\dsh-pet\bin\laji-pet\laji-pet.exe"
```

---

## 4. 三条启动路径的关系

| 方式 | 谁拉起 | 用在哪 |
| --- | --- | --- |
| 源码 `python -m pet` | 手动 | 日常开发、改代码 |
| 打包 `laji-pet.exe` | 手动 / Laji 托管 | 交付、给同事试 |
| Laji 插件托管 | Laji 主进程 | 正式装机形态 |

Laji 托管由 `laji.plugin.toml` 的 `[[contributions.apps]]` 定义，靠环境变量占位，**变量没设就跳过该条**，所以不会双开：

- `LAJI_DSH_PET_PYTHON` → 源码运行（`pythonw.exe -m pet`，workdir 指向 `src`）
- `LAJI_DSH_PET_EXE` → 打包版 exe

两个都别设。

---

## 5. 验证「打工」演出

右键桌宠 → **「打工」**（托盘图标右键的「打工」走同一条路）。

正常表现分五段，总计约 6.5 秒（Laji 收在托盘时）：

1. **看见** 0.9s — 转头望向任务栏
2. **走去** 1.5s — 小跑过去，落在图标正上方
3. **按下** 0.6s — 抬手按图标
4. **门开** 1.0s — Laji 窗口弹出（冷启动要 15~22s，她会站着等）
5. **雀跃** 1.9s — 收工

判据：

| 看到什么 | 结论 |
| --- | --- |
| 走过去 → 按 → 弹窗 → 雀跃 | 正常 |
| 原地扭两下就雀跃 | 走位判定错了（`pos()` / `body_width()`） |
| 走了但离图标很远就按 | 落点算法有问题 |
| 走过去按了但 Laji 不弹 | 演出没问题，是 deep link / 托盘唤起挂了 |
| 只冒气泡不走路 | `choreo.start()` 返回 False，回落老路径 |

定位演出中途有没有开演、走了多少，看日志里的 `work_choreo` 行：

```
%APPDATA%\dsh-pet-standalone-laji\pet-<PID>.log
```

---

## 6. 单元测试

```powershell
cd D:\workspace\waf\Nerve-agent\Laji\packs\plugins\dsh-pet\src
D:\workspace\waf\.venvs\dsh-pet\Scripts\python.exe -m pytest tests/test_work_choreo.py -q
```

13 项应全过。测试用假宿主跑完整时间轴，**跑得快但覆盖不到真机**——真机的窗口坐标、DPI、素材帧率都靠它测不出来，交付前必须手动跑一遍第 5 节。

---

## 7. 排错速查

| 症状 | 原因 / 处理 |
| --- | --- |
| 启动即收到 `about_to_quit` 静默退出 | 从宿主后台任务里启动，会话结束被连带终止。改用普通终端或双击 |
| `SAFE_DELETE_BULK_CONFIRM_REQUIRED` | 宿主的 `PYTHONPATH` shim，清掉该变量 |
| 拉起的 Laji 崩在 `app.setName` | `ELECTRON_RUN_AS_NODE=1` 泄漏，清掉该变量 |
| 打包报 `_internal` 文件被占用 | 旧实例没停干净，`taskkill /IM laji-pet.exe /F` 后重试 |
| 缺 `PySide6` / 缺模块 | venv 被安全软件清空，按第 1 节重建 |
| 桌宠不动、只有 idle | 素材帧序列没生成完，首次启动要等 ffmpeg 转帧（日志有「帧序列供给」行） |
| 走路速度像电风扇 | `walk_speed_max` 上限 6 倍，目标太远时会顶到上限，属正常 |

---

## 8. 与 Laji 的联动

- 桌宠读 `%APPDATA%\Laji Agent\pet-link\laji.jsonl`（宿主按 `agent-event/v1` 契约写入）来切动画和气泡。
- 「打工」拉 Laji 走 `laji-agent://` deep link，由 `src\pet\agent_bridge.py` 负责；`src\pet\work_choreo.py` 是那段走去按图标的演出编排，`taskbar_icon.py` 用 UIA 定位任务栏图标，`agent_window.py` 用 ctypes 判窗口是否真的可见。
- 表盘上的事件、气泡文案改动见 `src\pet\` 下对应模块，改完不用打包也能验。
