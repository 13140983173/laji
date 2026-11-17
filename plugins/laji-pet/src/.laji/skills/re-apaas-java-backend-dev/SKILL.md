---
name: re-apaas-java-backend-dev
version: 1.1.1
description: |
  R 平台（recloud-one）二开总入口。
  进入技术实现阶段后，涉及 R 平台 API、Plugin、BizFunc、Job、AsyncJob、数据访问、事务、权限、测试时激活。
  仅做技术规范路由和实现约束；需求澄清/方案门禁不在本入口（由需求侧流程负责）。
  涉及实体字段、logicalName、R-MCP、元数据查询、任务拆分时同时参考 references/re-platform-mcp/guide.md。
---

# R 平台二开总入口（通用版）

## 快速索引卡（入口 / 依赖 / 输出）

| 项 | 说明 |
| --- | --- |
| 入口 | 已进入开发阶段，需要按 R 平台规范实现具体模块（API/Plugin/Job/Data/事务等） |
| 依赖 | 上游需求澄清/方案门禁不在本入口（由需求侧流程负责）；元数据与任务分解由 `references/re-platform-mcp/guide.md`（R-MCP）提供 |
| 输出 | 实现代码 + 测试代码 + 可复现验证证据（编译/测试/接口行为）；关键实体元数据摘要（来自 MCP 或降级确认） |

## 触发规则（统一格式）

### 触发条件

- 需求已进入开发执行，且涉及 R 平台实现模块（API、Plugin、BizFunc、Job、AsyncJob、Data、事务、权限、测试）。
- 需要在既有分层约束下确定具体实现方式或模块路由。

### 不触发条件

- 仍处于需求澄清/方案评审阶段，尚未进入编码落地。
- 纯研究性讨论，或非 R 平台项目。

### 典型示例

- “新增一个客户创建前校验的 Plugin，按规范怎么实现？”
- “这个接口需要 Controller + Server + 事务，如何按 R 平台分层落地？”

## 项目视角约定

- 当前上下文是二开工程，不是平台源码仓库。
- 业务优先使用 server 模式（`Controller -> Service/Server -> DAO/Broker`）。
- Command 模式与 server 模式都支持，已有逻辑可延续；新逻辑优先 server 模式。
- Controller 基类 `HiddenApiController` / `BaseController` 均支持，按模块现状一致性选择。
- 元数据建模通过 R 平台 UI 完成，不在代码里直接建模；编码前**优先**通过 R-MCP `get_entity_details` 获取 logicalName/字段/选项（见 `references/re-platform-mcp/guide.md`）。

## 工程基线与 SDK 边界

- **工程基线**（启动模块 / 主类 / JDK / 可变项）见 [`references/project-baseline.md`](references/project-baseline.md)。
- **SDK API 边界与类速查**（包路径分类、高频类签名、易混淆方法）见 [`references/re-platform-common/guide.md`](references/re-platform-common/guide.md) §0 与 §9.1。

## 核心决策速查（精简版）

进入具体模块前，下面四张表覆盖了 R 平台二开最高频的选型决策。完整决策表与代码模板见对应模块 `guide.md` 顶部「决策速查」章节。

### Plugin Pre/Post 决策

| 阶段 | 持久化方式 | 阻断主操作 | 典型场景 |
|------|-----------|-----------|---------|
| PreCreate / PreUpdate | 自动（无需 `update()`） | ✅ 抛异常 | 校验、默认值、字段联动 |
| PostCreate / PostUpdate | 必须 `broker.update()` | ❌ | 关联记录、通知、状态联动 |
| PreDelete | — | ✅ 抛异常 | 关联检查 |
| PostDelete | 无法恢复 | ❌ | 日志、级联清理 |

详见 `references/re-platform-plugin/guide.md`。

### 事务场景划分

| 扩展点 | 事务方式 | 手动包裹 |
| --- | --- | --- |
| Plugin `executePlugin()` | 框架自动 | ❌ 禁止 |
| BizFunc `execute()` | 框架自动 | ❌ 禁止 |
| Custom API `ServiceImpl` | 手动 | ✅ 必须 |
| Job `doExecute()` | 手动 | ✅ 必须 |

详见 `references/re-platform-transaction/guide.md`。

### BizFunc vs Plugin 选型

| 维度 | BizFunc | Plugin |
|------|---------|--------|
| 触发 | 主动调用 | 事件触发 |
| 返回值 | 必须有 | 无 |
| 适合 | 批量处理、复杂计算、前端按钮调用 | 数据联动、校验、自动触发 |

详见 `references/re-platform-bizfunc/guide.md`。

### AsyncJob vs JobBase 选型

| 维度 | AsyncJob | JobBase |
|------|----------|---------|
| 触发 | 业务事件触发 | 调度平台定时触发 |
| 基类 | `AsyncJobBase` | `JobBase` |
| 典型场景 | 审批后异步回写、批处理 | 每日统计、定时通知 |

详见 `references/re-platform-asyncjob/guide.md`。

## 模块参考路由

本 skill 是 R 平台开发唯一顶层入口。具体 API / Plugin / BizFunc / Job / 数据访问等资料收敛在 `references/re-platform-*/guide.md`，需要细节时按下表读取对应文件。

| 任务 | 主参考 | 可能用到 |
| --- | --- | --- |
| 实体元数据 / 任务分解（R-MCP） | `references/re-platform-mcp/guide.md` | 各业务参考 |
| 自定义 API | `references/re-platform-api/guide.md` | `re-platform-server`, `re-platform-common`, `re-platform-mcp` |
| Server/Service 业务层 | `references/re-platform-server/guide.md` | `re-platform-common`, `re-platform-transaction` |
| Plugin | `references/re-platform-plugin/guide.md` | `re-platform-common`, `re-platform-transaction`, `re-platform-mcp` |
| BizFunc | `references/re-platform-bizfunc/guide.md` | `re-platform-common`, `re-platform-data`, `re-platform-mcp` |
| Job / AsyncJob | `references/re-platform-job/guide.md`, `references/re-platform-asyncjob/guide.md` | `re-platform-transaction`, `re-platform-mcp` |
| 数据访问 | `references/re-platform-data/guide.md` | `re-platform-common`, `re-platform-mcp` |
| 平台服务调用 | `references/re-platform-services/guide.md` | `re-platform-common` |
| 事务 | `references/re-platform-transaction/guide.md` | `re-platform-job`, `re-platform-asyncjob` |
| 公共规范 | `references/re-platform-common/guide.md` | `re-platform-test` |
| SDK 类速查 | `references/re-platform-common/guide.md` §0、§9.1 | — |
| 测试 | `references/re-platform-test/guide.md` | 对应业务参考 |
| 本地启动/自测/debug | `references/re-platform-local-selftest/guide.md` | `re-platform-test`, `re-platform-api`, `re-platform-plugin` |
| 泛微 OA 集成（第三方对接特例） | `references/re-platform-thirdparty/guide.md` | `re-platform-common` §11 |
| 第三方系统对接 | `references/re-platform-thirdparty/guide.md` | `re-platform-common` §11 |

## 读取顺序卡

按任务类型选择最小必要资料，避免一次性加载全部 references：

| 任务类型 | 推荐读取顺序 |
| --- | --- |
| API / 接口 | 本文件 → `references/re-platform-common/guide.md` → `references/re-platform-api/guide.md` → `references/re-platform-server/guide.md` → `references/re-platform-data/guide.md` → `references/re-platform-test/guide.md` |
| Plugin | 本文件 → `references/re-platform-common/guide.md` → `references/re-platform-mcp/guide.md` → `references/re-platform-plugin/guide.md` → `references/re-platform-transaction/guide.md` → `references/re-platform-test/guide.md` |
| BizFunc | 本文件 → `references/re-platform-common/guide.md` → `references/re-platform-mcp/guide.md` → `references/re-platform-bizfunc/guide.md` → `references/re-platform-data/guide.md` → `references/re-platform-test/guide.md` |
| Job / AsyncJob | 本文件 → `references/re-platform-common/guide.md` → `references/re-platform-job/guide.md` 或 `references/re-platform-asyncjob/guide.md` → `references/re-platform-transaction/guide.md` → `references/re-platform-test/guide.md` |
| 数据查询 / SQL | 本文件 → `references/re-platform-common/guide.md` → `references/re-platform-data/guide.md` → `references/re-platform-transaction/guide.md` |
| 本地验证 | 本文件 → 具体实现参考 → `references/re-platform-local-selftest/guide.md` → `references/re-platform-test/guide.md` |
| 泛微 OA / 第三方集成 | `references/re-platform-thirdparty/guide.md` |
| 第三方系统对接（非 OA） | `references/re-platform-thirdparty/guide.md` → `references/re-platform-common/guide.md` §11 |

## 与其他流程 skill 的边界

- 需求侧流程（不在本入口）：需求澄清、分流、任务拆分、proposal/design 评审与验收门禁。
- `re-apaas-java-backend-dev`（本 skill）：R 平台二开技术实现规范与路由。
- `references/re-platform-mcp/guide.md`：R-MCP 调用时机、元数据摘要格式、降级策略。

大需求的分流与方案评审由需求侧流程负责（不在本入口）；本 skill 仅提供 R 平台技术决策输入（扩展点选型、Pre/Post、事务边界、数据访问方式、测试策略），各决策点的参考资料见上方「模块参考路由」表。

---

## 执行契约（I/O）

- **输入**：已确认需求/任务、实施路径、目标模块、实体元数据摘要（优先 R-MCP）、任务拆分任务表。
- **输出**：模块实现代码 + 测试代码 + 可复现验证证据（编译/测试/接口日志）+ 关键设计决策说明。
- **完成判定**：通过当前阶段验证（至少单元测试）、行为符合本 skill 规范（Plugin Pre/Post、事务边界等）、结果可复现可回归。

---

## 三条执行纪律

1. **不凭感觉报完成**：声称完成前必须给到本次会话新鲜验证结果。
2. **先找根因再修**：先复现、再定位、再做最小改动。
3. **测试分层推进**：当前至少补单元测试；具备租户条件后补本地单实例集成测试。

> 协作确认关卡（proposal/design 评审、上线前风险）由需求侧流程统一管理，不在本入口重复。
