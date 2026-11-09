# 任务中心（`com.nerve.task-center`）

把所有工作区的 daemon run 汇成一张表：**谁在跑、跑到哪、卡在哪、等你什么**。
侧栏仍然是一行一个会话，这里是可以筛、能排序、能批量看的全量视图。

## 工程结构

```
packs/plugins/laji-task-center/
├─ laji.plugin.toml      清单：一个 workbench 入口，无网络权限
├─ lib/
│  ├─ client.js          UI：入口注册 + 面板（列表 / 详情 / 页签 / 键盘）
│  ├─ store.js           纯逻辑：归约、注意力排序、筛选、分组、格式化（可单测）
│  └─ panel.css          样式（只吃宿主的 --laji-* 变量，不写死配色）
├─ test/
│  ├─ store.test.cjs     store 的单测（node test/store.test.cjs）
│  └─ panel-harness.html 不装插件也能看 UI 的独立壳
└─ README.md
```

## 宿主能力面（插件能拿到什么）

由 `apps/laji-agent/src/renderer/visual-plugins.ts` 的 `createPluginContext()` 提供：

| 能力 | 说明 |
| --- | --- |
| `ctx.id` | 插件 id |
| `ctx.entries.register({ id, label, icon, open, mount })` | 右缘活动栏里一颗图标；`handle.setBadge(n)` 用来点红点 |
| `ctx.events.on(kind, fn)` | 只读事件流：`approval / questions / plan / error`（`apps/laji-agent/src/renderer/plugin-events.ts`） |
| `ctx.runs.list()` | 转发到 `runs:list`，返回 `RunListEntry[]`（`apps/laji-agent/src/shared/run-list.ts:18`） |
| `ctx.runs.open({ runId, workspaceRoot })` | 切到那次会话 |
| `ctx.runs.dismiss({ workspaceRoot, sessionRootRunId })` | 从侧栏移除（daemon 记录保留） |

插件**不**直接连 daemon：不读 `%TEMP%/laji-engine-<pid>/laji/daemon.endpoint`，不持有凭据。
所有动作都落在已有的 IPC handler 上，权限与校验跟主界面完全一致。

## 字段映射

`RunListEntry` → 界面里的「任务」：

| 界面 | 来源 |
| --- | --- |
| 标题 | `title`（超过 40 码点已截断，`RUN_TITLE_CHARS`） |
| 状态 | `status`：`created` 排队 / `executing` 在做 / `awaiting` 等你 / `finished·failed·cancelled` 收口 |
| 工作区 | `workspaceRoot` |
| 轮次 | `turnCount` |
| 耗时 | `now - createdAtMs` |
| 最近活动 | `latestActivityAtMs` |
| 模型 | `modelId`（`null` 时显示“默认模型”，不猜） |

**不显示的东西**（宁可空着也不编）：没有 todo 就没有百分比；没有 `RunMetrics` 就没有 token 数。
胶囊（跨任务结论）属于设计文档 C1 阶段，当前插件在对应页签显示“未启用”，不画假数据。

## 筛选与排序

- 视图：等你 / 在做 / 排队 / 收口 / 全部
- 过滤器：工作区、状态、只看等你、关键词（标题 + prompt）
- 排序：注意力（recency 0.995^小时 + importance 可解释项）/ 最近活动 / 创建时间 / 耗时
- 注意力只排序，**不替你做决定**；每条都能说清“为什么在这”。

## 开发

```bash
node packs/plugins/laji-task-center/test/store.test.cjs                 # 纯逻辑单测
start packs/plugins/laji-task-center/test/panel-harness.html           # 看 UI（用内置样例行）
```

装进 Laji：把本目录放进 `packs/plugins/`，在插件中心启用。
