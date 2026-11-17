# R-MCP 桥接（re-platform-mcp）

> **定位**：连接 **R-MCP**（`user-R-MCP`）与项目 **re-platform** 规范体系。
> **原则**：有 MCP 时元数据优先 MCP；无 MCP 或无 descriptor 时立即降级，不反复重试。任务拆分以任务表 + 上游方案的构建顺序为权威；有 `plan_prompt` 则调用并合并；代码规范以各模块 guide.md 与项目 Java 规则为准。
> **时机表**：本文档为 MCP 调用的唯一权威表。

## 决策速查

### MCP 调用时机

| 阶段 | 调用 | 说明 |
|-------|------|------|
| 需求澄清 | `get_entity_details`（可选） | 需求澄清时对齐 logicalName |
| 方案设计 | `get_entity_details`（**必填**） | 设计前获取实体字段元数据 |
| 任务拆分 | `plan_prompt`（有 descriptor 时**必填**） | 任务拆分，与构建顺序合并 |
| 编码 | `plugin_prompt` 等（按需） | 编码时按任务类型选用 |

> 「需求澄清 / 方案设计 / 任务拆分 / 验收」等阶段由上游需求侧流程负责（不在本 skill）；本表只规定这些阶段各自该调哪个 MCP。

### 降级策略

MCP 不可用时：标注降级 → 从代码/jar 反推字段 → 列出待确认清单 → **用户书面确认后才能进入编码阶段**。

## 快速索引

| 项 | 说明 |
| --- | --- |
| MCP 服务名 | `user-R-MCP`（显示名 R-MCP） |
| 调用前 | 若仓库存在 `mcps/user-R-MCP/tools/*.json` 与 `prompts/*.json`，先读取 descriptor；不存在则直接降级 |
| 上游编排 | 需求侧流程（需求澄清 / 分流 / 任务拆分，不在本 skill） |
| 下游实现 | `re-platform-*` 子 guide、项目 Java 规则（`.cursor/rules/r-platform-java-development.mdc`） |
| 冲突裁决 | `re-platform-common` **RQ1～RQ5** |

---

## 〇、能力自检（每次进入任务拆分或首次涉及 MCP 时）

1. 若 `mcps/user-R-MCP/tools/` 存在，列出实际 tool；不存在则标注「R-MCP tools descriptor 不可用」并进入第五节降级。
2. 若 `mcps/user-R-MCP/prompts/` 存在，列出实际 prompt；不存在或无 descriptor 时标注「plan_prompt 不可用，任务拆分以任务表 + 构建顺序为权威」。
3. 可选：调用 `echo` 验证连通。

| 能力 | 环境有 descriptor | 环境无 descriptor |
| --- | --- | --- |
| `get_entity_details` 等 tool | 按第三节表调用 | 走第五节降级；**禁止反复重试** |
| `plan_prompt` | 任务拆分时**必须**调用一次，结果与构建顺序合并 | **不调用**；任务拆分以任务表 + 上游方案构建顺序为权威，任务表注明「plan_prompt 不可用」 |
| `plugin_prompt` 等 | 编码阶段可按任务类型选用 | 不调用；直接按子 guide 编码 |

---

## 一、Tools（元数据）

| 工具 | 何时调用 | 参数 | 产出用法 |
| --- | --- | --- | --- |
| `get_all_entity_metadata` | 用户只说中文实体名、logicalName 不确定 | 无 | 对齐 logicalName，写入需求/方案「实体列表」 |
| `get_entity_details` | 方案设计、每任务编码前、字段/选项集有疑问 | `logicalNameList: string[]` | 元数据摘要；代码字段名 |
| `echo` | 自检 MCP 连通 | 按 schema | 失败则走第五节 |

**元数据摘要（禁止全文 dump）**：

```markdown
## 元数据摘要（R-MCP，环境：{说明}）

| 实体 logicalName | 显示名 | 本需求涉及字段（logicalName / 类型 / 备注） | 来源 |
| --- | --- | --- | --- |
| account | 客户 | name / String；… | R-MCP / SDK 常量 / 现有代码 / 用户确认 |
```

来源口径：

- R-MCP 返回的业务字段：标 `R-MCP`。
- MCP 未返回但 SDK / 现有代码稳定存在的系统字段（如 `statecode`）：可使用，但须标 `SDK 常量` 或 `现有代码` 并注明证据。
- 降级场景由用户确认的字段：标 `用户确认`，编码阶段前不得再扩展未确认字段。

---

## 二、Prompts（仅当 descriptor 存在）

| Prompt | 何时调用 | 必填参数 | 与 guide 关系 |
| --- | --- | --- | --- |
| `plan_prompt` | **任务拆分时**（有 descriptor 时必调一次） | `userRequirements` | 与任务表、构建顺序**合并**；冲突 → RQ1～RQ5 |
| `plugin_prompt` | 编码阶段，任务含 Plugin | `userRequirements`、`mainEntityName` | 须经 `re-platform-plugin` + 项目 Java 规则改写 |
| `biz_func_prompt` | 编码阶段，BizFunc | `userRequirements` | → `re-platform-bizfunc` |
| `job_prompt` | 编码阶段，Job | `userRequirements` | → `re-platform-job` |

**任务拆分流程**：

1. `get_entity_details`（方案设计已做且环境未变可省略重做）。
2. **若**存在 `plan_prompt` descriptor → 调用一次，保存摘要。
3. **无论是否有 plan_prompt**：用任务表（`T-01…` 结构）+ 上游方案构建顺序产出任务表。
4. 有 plan 时：合并进任务表「备注」；与构建顺序冲突 → RQ1～RQ5 + 项目 Java 规则。

---

## 三、各阶段 MCP 调用时机（唯一时机表）

| 阶段 | MCP 动作 | 产出物 |
| --- | --- | --- |
| 需求澄清 | 可选 `get_all_entity_metadata` | 澄清清单中的 logicalName |
| 方案设计 | **必须** `get_entity_details`（或降级确认） | 方案元数据摘要 |
| 任务拆分 | 有 plan_prompt 则调用 + **必做**任务表 | 任务表；plan 摘要（若有） |
| 编码 | 每任务前 `get_entity_details`；有 `*_prompt` 则可选 | 代码字段名一致 |
| 提案 / 方案评审 | `get_entity_details` | 提案附录元数据摘要 |
| 自测 | 一般不调用；选项异常再查 | — |

> 上表阶段由上游需求侧流程划分（不在本 skill）；本 skill 只负责各阶段对应的 MCP 调用。

---

## 四、优先级与禁止项

**优先级**：上游方案门禁（不在本 skill）→ re-platform / 项目 Java 规则 → `get_entity_details` 事实 → prompt 建议（仅当存在 descriptor）。

**禁止**：

- 未校验且未降级确认时编造 picklist / logicalName。
- 将 prompt 输出**直接提交**为最终代码。
- **无 descriptor 时反复调用** `plan_prompt` / `*_prompt`。
- 有 `plan_prompt` 却跳过任务拆分的任务表（仅贴 plan 原文不合并）。

---

## 五、大结果处理协议

当 MCP 工具返回结果超过 token 上限时（如 `get_all_entity_metadata_json` 返回 200K+ 字符），结果会自动落地到临时文件。此时遵循以下降级策略：

1. **已知实体 logicalName** → 直接调用 `get_entity_details(["logicalName"])`，不调用 `get_all_entity_metadata` 全量接口
2. **不知 logicalName** → 调用 `get_all_entity_metadata`，结果落地后用 `Grep` 搜索目标实体名（不强行读取整个文件）
3. **`get_entity_details` 也超限** → 用 Node.js 解析落地文件（Python 在 Windows 环境下可能不稳定，exit code 49 等异常）
4. **所有 MCP 方式失败** → 从项目源码搜索已有代码确认字段名（`EntityNameConstants.java`、现有 Plugin），降级需在方案中标注「元数据未通过 R-MCP 校验」

```bash
# 方案 3 示例：Node.js 解析落地文件
node -e "const data = JSON.parse(require('fs').readFileSync('<file_path>','utf8')); console.log(JSON.stringify(data.filter(e => e.logicalName === 'target_entity'), null, 2))"
```

---

## 六、降级策略

触发：MCP 未启用、鉴权失败、`echo` 失败、工具超时、**无对应 descriptor**、**prompts 目录不存在**。

1. 方案/任务表标注「元数据未通过 R-MCP 校验」或「plan_prompt 不可用」。
2. 从仓库代码反推字段名。
3. **编码阶段前**用户书面确认 logicalName 列表（或提供元数据导出）。
4. 任务拆分**仍须**产出完整任务表（任务表 + 构建顺序）。

### plan_prompt 不可用的处理流程

当 `mcps/user-R-MCP/prompts/` 目录不存在或无 `plan_prompt` descriptor 时：

1. **不要反复尝试调用** `plan_prompt`，也不要尝试构造 fallback prompt。
2. 任务表备注列标注「plan_prompt 不可用，以构建顺序为权威」。
3. 任务拆分直接使用任务表（`T-xx` 结构）+ 方案设计产出的构建顺序拆分。
4. 若构建顺序不够细，参考 `re-platform-plugin` / `re-platform-api` 等子 guide 的实现粒度补充。
5. 不降级整体流程——任务表是任务拆分的必需产出，`plan_prompt` 是可选增强。

### 前端表单工具降级

当 MCP 表单工具（`set_value_change_handler` / `set_customize_button` 等控件事件工具、`set_form_load_handler` / `set_form_unload_handler`、`backup_object` 等）对特定表单返回异常时（通常因 LayoutJson 结构复杂度导致后端解析失败）：

1. 将脚本内容保存到工程内约定的临时脚本目录（如 `<工程>/frontend-scripts/REQ-xxx/frontend-script.js`）
2. 在任务表中标注「需平台 UI 手动更新」，记录失败的 MCP 工具名和报错信息
3. 不反复重试，直接降级为人工操作
4. 在方案中明确标注哪些前端变更为手动操作，不声称已完成

---

## 七、子 guide 编码前检查

- [ ] 本任务实体已 `get_entity_details` 或降级确认
- [ ] 字段已写入任务行或元数据摘要
- [ ] 若用 `*_prompt` 且 descriptor 存在，输出已按 guide 改写

---

## 八、CallMcpTool 示例

```json
{ "server": "user-R-MCP", "toolName": "get_entity_details", "arguments": { "logicalNameList": ["account"] } }
```

`plan_prompt` 按当前环境 prompts API 与 descriptor 调用；**调用前必须完成第〇节自检**。
