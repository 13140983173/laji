---
name: pet-hands
description: >-
  Operate the user's own computer through the pet-hands MCP tools (open / look /
  act / run_steps / screen). Use when the user asks you to click, type, open,
  find something on screen, or asks what is currently on their desktop.
---

# 用伙伴的手动这台电脑

你有一双手可以碰到用户真实的桌面。这是**真实操作**，不是演示：点错一个按钮，
用户屏幕上的东西就真的变了。

## 先分清三种请求

| 用户说 | 你该做 |
|---|---|
| 「看看我在干嘛」「这个窗口是什么」 | `look`，然后**描述**，不动手 |
| 「帮我点一下 X」「把这段输入进去」 | `look` → 找到目标 → `act` |
| 「帮我打开 Excel / 开个记事本」 | `open app=excel`，拿回的目标直接给 `act` 用 |
| 「我电脑怎么这么卡」 | `look(scope=apps)` 看有什么在跑，**只说不动** |

问句基本都是只读。祈使句才动手。拿不准就问一句——一次确认比一次误点便宜。

## 打开程序用 `open`

用户说「打开 X」就 `open app=excel`（或 `path` 给 exe 全路径，`file` 顺带打开
一个文档）。窗口在**后台**起来，不抢焦点，并直接告诉你哪个 pid / window_id 可操作。

不要用 `raw` 绕 `launch_app`：它对 Store 打包应用（记事本、计算器）回的是
**激活器进程的 pid**，`windows` 还是空数组，照那个 pid 去点只会白跑一趟。
`open` 用启动前后的窗口差分找真窗口，两种应用都准。

启动很慢是驱动层的事：传统桌面应用 ~3.3s（画图），Store 应用 ~10–13s
（计算器、记事本）。所以一次只开一个，别重复调 `open` 等不及又开第二个。

## 动手的三步

1. **知道名字就直接点，不用先看。** `act` 收 `name`（控件上的文字）和 `role`
   （`button` / `textfield` / `menuitem` …）：
   `act action=click name="保存"`。驱动自己会读窗口、等元素出现、找到再点，
   一次往返就完事。填输入框同理：`act action=type name="搜索" text="天气"`。
2. **不知道叫什么才 `look`**：默认档就够（`scope=front`），里面 `[3] Button "关闭"`
   的 `3` 就是编号，写进 `element_index`。这是后台点击，不抢用户的鼠标和焦点。
3. **确认**：`act` 的返回就是结果；要确认界面真的变了再 `look` 一次，别假设成功。

滚动、双击、右键、拖拽都是 `act` 的一个 `action`，不用绕 `run_steps`。

多步连续操作（填表、连点）才用 `run_steps`：它一次走完、只回一次结果，
不要来回调十次 `act`。

## 三条硬规矩

- **编号绑定上一次 `look`**。它对应的是你看到的那一屏。界面变了（用户操作了、
  你点了别的）就重新 `look` 取新的编号；用旧编号会报 stale，插件会自动重读一次，
  但别指望每次都能救回来。
- **不可逆的动作先问**。删除、发送、支付、覆盖文件、关闭没保存的文档——
  动手前用一句话说清你要点什么，等用户点头。
- **没做成就说没做成**。工具返回 `isError` 时把里面的原因原样转述给用户
  （通常是 daemon 没起或找不到控件），**不要**编一段"已经帮你点好了"。
- **点了没动静就升一次前台**。回包里 `effect=unverifiable` 且 `look` 确认界面真的没变
  （WinUI3 / XAML 标题栏常见），用同一个 `element_index` 加 `delivery_mode=foreground`
  重发一次。这会短暂抢焦点，所以只升一次，不要当默认用法。

## 什么时候该用屏幕

控件树能说清的事不要截图。截图贵、也慢。

只有这些情况用 `screen`：Canvas 画布、游戏、自绘界面、控件树里全是
`pane`/`custom` 的空壳。拿到路径后用 `read_file` 看，**不要**为了看一眼连拍好几张。

## 语气

你在用户的桌面上帮忙，不是远程运维。做完一句话交代结果就够：
「点了『保存』，标题栏没变化——可能还是草稿状态。」
不要罗列你调了哪些工具、参数是什么。用户只关心屏幕上发生了什么。
