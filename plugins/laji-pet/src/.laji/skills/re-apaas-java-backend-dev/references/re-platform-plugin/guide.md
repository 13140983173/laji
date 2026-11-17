# R平台 插件开发

> **定位**：Plugin（实体事件扩展点）开发规范与代码模板。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。实体元数据校验及 `plugin_prompt` 用法见 [re-platform-mcp/guide.md](../re-platform-mcp/guide.md)。分层约定见 `.cursor/rules/r-platform-java-development.mdc`。

## 决策速查

### 最关键的一条规则

**Pre 阶段**修改 entity 后**不需要**调用 `broker.update()`（自动持久化）。
**Post 阶段**修改 entity 后**必须**调用 `broker.update()`（主操作已完成）。

### Pre vs Post 决策速查

| 阶段 | 修改 entity | 持久化方式 | 能阻止主操作 | 典型场景 |
|------|-----------|-----------|-------------|---------|
| **PreCreate/PreUpdate** | 直接改 `getEntity()` 字段 | **自动**，无需 update | ✅ 抛异常 | 校验、默认值、字段联动 |
| **PostCreate/PostUpdate** | — | **必须** `broker.update()` | ❌ | 关联记录、通知、状态联动 |
| **PreDelete** | — | — | ✅ 抛异常 | 关联检查 |
| **PostDelete** | — | 无法恢复 | ❌ | 日志、级联清理 |

### 事件阶段选择策略

字段联动计算、保存前校验类需求 → **默认覆盖 PreCreate + PreUpdate**，除非业务明确「只在编辑时触发」。

PreCreate 不查 DB、不设 filterAttributes；PreUpdate 可能需要 retrieve DB 兜底 + filterAttributes 优化。

### 11 条代码规则

1. `@Component` + `@Slf4j` 注解 + 继承 `PluginBase`（推荐加 `@Scope("prototype")`）
2. 实现 `getSteps()` 和 `executePlugin()`
3. 业务异常用 `RtClientException` / `DuplicateRecordException`（含 errorCode i18n），系统异常用 `RtServerException`；不用 legacy 的 `InvalidPluginExecutionException`
4. 异常文案必须走 i18n：`getLangHelper().get(key, defaultMessage)`
5. 捕获的异常必须再抛或记 error 日志，不要吞掉
6. 用 `getBroker()`，禁止 `PersistBrokerFactory.newBroker()`
7. Pre 阶段改 entity 后不调 update；Post 阶段必须 update
8. 事务由框架管理，禁止手动 `executeTransaction()`
9. 操作同一实体时 `getDepth()` 防递归
10. 辅助方法只做纯逻辑，数据访问集中在 `executePlugin`
11. 单元测试用 Testable 子类模式，测试文件放 `recloud-starter/src/test/java`

---

## 基本结构

```java
@Component
public class OrderStatusPlugin extends PluginBase {

    @Override
    public List<IPersistBrokerPluginStep> getSteps() {
        var step = new PersistBrokerPluginStep();
        step.setEntityName("saleorder");                              // 实体名称
        step.setEventType(PersistBrokerPluginEventTypes.PostUpdate);  // 事件类型
        step.setFilterAttributes("new_orderstatus");                 // 触发字段（可选）
        step.setOrder(0);                                            // 执行顺序（值越大优先级越高）
        step.setAsync(false);                                        // 同步/异步
        return List.of(step);
    }

    @Override
    public void executePlugin() throws SQLException {
        // 业务逻辑
    }
}
```

---

## 事件阶段选择策略

### 字段联动 / 字段校验类需求：默认覆盖 PreCreate + PreUpdate

对于「字段联动计算」「保存前校验」类需求，**默认同时覆盖 PreCreate 和 PreUpdate**，除非业务明确说「只在编辑时触发」。

```java
@Override
public List<IPersistBrokerPluginStep> getSteps() {
    return List.of(preCreateStep(), preUpdateStep());
}

private PersistBrokerPluginStep preCreateStep() {
    var step = new PersistBrokerPluginStep();
    step.setEntityName("pmi_specialcreditrelease");
    step.setEventType(PersistBrokerPluginEventTypes.PreCreate);
    step.setOrder(10);
    return step;
}

private PersistBrokerPluginStep preUpdateStep() {
    var step = new PersistBrokerPluginStep();
    step.setEntityName("pmi_specialcreditrelease");
    step.setEventType(PersistBrokerPluginEventTypes.PreUpdate);
    step.setFilterAttributes("field1,field2"); // Update 时可设置触发字段
    step.setOrder(10);
    return step;
}
```

**PreCreate vs PreUpdate 的逻辑差异**：

| 方面 | PreCreate | PreUpdate |
|------|-----------|-----------|
| payload 完整性 | 新建时 payload 包含所有字段 | 可能只包含变更字段 |
| DB 查询 | 不需要 retrieve DB | payload 缺字段时需 retrieve DB 兜底 |
| filterAttributes | 不设置（新建一定触发） | 设置触发字段以优化性能 |
| 源字段缺失 | 直接按 null/默认值处理 | 需合并 DB 当前值 |

```java
@Override
public void executePlugin() throws SQLException {
    var entity = getEntity();
    if (isCreateMessage()) {
        // 直接从 payload 取值，不查 DB
        calculateAndSet(entity, entity);
    } else if (isUpdateMessage()) {
        // payload 可能只含部分字段，retrieve DB 兜底
        var dbEntity = getBroker().retrieve(getPrimaryEntityName(), getPrimaryEntityId());
        calculateAndSet(entity, dbEntity != null ? dbEntity : entity);
    }
}
```

---

## 辅助方法设计原则

Plugin 中辅助方法（private helper）应**只做纯逻辑**，不调数据访问 API：

```java
// ✅ 正确：数据访问集中在 executePlugin 中
@Override
public void executePlugin() throws SQLException {
    DynamicEntity dbEntity = null;
    if (isUpdateMessage()) {
        dbEntity = getBroker().retrieve(getPrimaryEntityName(), getPrimaryEntityId());
    }
    var value = resolveFieldValue(getEntity(), dbEntity, "field_name");
    // ...
}

// 纯逻辑 helper，不抛 SQLException
private BigDecimal resolveFieldValue(DynamicEntity payload, DynamicEntity dbEntity, String fieldName) {
    if (payload.containsKey(fieldName)) {
        return payload.getDecimalFieldValue(fieldName);
    }
    if (dbEntity != null && dbEntity.containsKey(fieldName)) {
        return dbEntity.getDecimalFieldValue(fieldName);
    }
    return BigDecimal.ZERO;
}

// ❌ 错误：helper 中调 getBroker().retrieve() 会抛 SQLException
private BigDecimal resolveFieldValue(DynamicEntity payload, String fieldName) {
    if (payload.containsKey(fieldName)) return payload.getDecimalFieldValue(fieldName);
    var dbEntity = getBroker().retrieve(...); // SQLException 传播问题
    // ...
}
```

**好处**：异常处理集中在 `executePlugin`（已声明 `throws SQLException`），helper 方法保持简单、易测试。

---

## Pre 阶段 vs Post 阶段行为差异

这是 Plugin 开发中最容易出错的地方：

| 阶段 | 修改 entity 的方式 | 持久化方式 | 能阻止主操作 |
|------|-------------------|-----------|-------------|
| **PreCreate / PreUpdate** | 直接修改 `getEntity()` 的字段 | **自动持久化**，无需调用 update | ✅ 可以（抛出异常） |
| **PostCreate / PostUpdate** | — | 必须调用 `broker.update(entity)` | ❌ 不能（主操作已完成） |
| **PreDelete** | — | — | ✅ 可以（抛出异常阻止删除） |
| **PostDelete** | — | 无法恢复已删除数据 | ❌ 不能 |

**典型错误**：
- 在 `PostUpdate` 里修改 entity 后忘记 `broker.update()`
- 在 `PreUpdate` 里调用 `broker.update()`（多余，且可能导致重复触发）

---

## Broker 使用规则

```java
@Override
public void executePlugin() throws SQLException {
    var broker = getBroker();  // ✅ 正确：共享主事务，框架管理生命周期

    // ❌ 禁止：PersistBrokerFactory.newBroker() 会创建独立事务
    // try (var broker = PersistBrokerFactory.newBroker()) { ... }
    // 这个 broker 不在主事务中，主事务回滚不受影响
}
```

---

## 异常与日志

### 异常类型选型

| 场景 | 异常类 | 客户端可见 | i18n |
|------|--------|-----------|------|
| 业务规则阻断（参数空、状态非法、查重冲突） | `RtClientException` 或 `DuplicateRecordException` | 是 | errorCode 透传 |
| 系统错误（DB 异常、外部调用失败、NPE） | `RtServerException(msg, cause)` | 否 | 不需要 |
| legacy CRM 阻断（不推荐新代码使用） | `InvalidPluginExecutionException` | 是 | — |

异常包路径：`recloud.one.sdk.exception`（**单数**）。

```java
// Pre 阶段业务校验失败：抛 RtClientException 阻止主操作
String msg = getLangHelper().get("account_name_required", "客户名称不能为空");
throw new RtClientException(4001, msg);

// 查重冲突：用 SDK 内置业务异常子类
throw new DuplicateRecordException(
    getLangHelper().get("quotedetail_product_existed", "产品已存在，不可重复添加"));

// 系统错误：包装为 RtServerException
try {
    externalService.invoke(req);
} catch (Exception e) {
    log.error("外部系统调用失败: entityId={}", entityId, e);
    throw new RtServerException("外部系统调用失败", e);
}

// Post 阶段：无法阻止主操作，不抛业务异常，改记日志
if (resp == null || !"0".equals(resp.getCode())) {
    log.error("推送失败: resp={}", JsonUtil.toJsonStr(resp));
}
```

### i18n 多语言机制

`RtClientException(int errorCode, String message)` 构造的 `errorCode` 会被框架透传给客户端，客户端按 errorCode 查本地化资源；`message` 作为默认中文兜底。

Plugin 内文案通过 `getLangHelper()`（recloud.one.sdk.core.LangHelper）取：

```java
public interface LangHelper {
    boolean isMultilingualEnabled();
    String get(String key);
    String get(String key, String defaultMessage);
    String get(int langId, String key);
    String get(int langId, String key, String defaultMessage);
}
```

实战示例（参考 salesone_java `QuoteDetailPlugin`）：

```java
throw new DuplicateRecordException(
    getLangHelper().get("quotedetail_product_existed", "产品已存在，不可重复添加"));
```

### 日志规范

类头统一 `@Slf4j`（lombok），禁止 `System.out.println` / `e.printStackTrace()` / 静态 Logger 字段。

| 等级 | 场景 |
|------|------|
| `log.info` | 流程节点、关键路径跟踪（Plugin 触发、外部调用开始） |
| `log.warn` | 业务规则触发、可恢复降级 |
| `log.error` | 系统错误、外部调用失败（带 throwable 打全栈） |

异常处理模板：

```java
try {
    // 业务逻辑
} catch (RtClientException e) {
    throw e;                                              // 业务异常直接上抛，不再记 error
} catch (Exception e) {
    log.error("Plugin 执行失败: entityId={}", getEntity().getId(), e);
    throw new RtServerException("Plugin 执行失败", e);
}
```

禁止：catch 后既不抛也不记日志（吞异常）。

### 测试断言技巧

集成测试中（参考 `re-platform-test`「Plugin 集成测专章」）：

```java
// 准备数据：用 SQL 直写 base 表预置「已存在」记录
PersistBroker broker = PersistBrokerFactory.get();
UUID existingId = TestDataHelper.insertAccount(broker, name, taxNo);

// 触发拦截：OrganizationService.create 走完整 Plugin 链
OrganizationService service = OrganizationServiceFactory.createService();
RtClientException ex = Assertions.assertThrows(
    RtClientException.class,
    () -> service.create(duplicateAccount)
);
Assertions.assertTrue(ex.getMessage().contains("已存在"));
```

> **造数说明（实测）**：`PersistBroker.create` 与 `createAdminService().create` **仍会执行 PreCreate Plugin**。  
> 预置「已存在」数据请用 **SQL 直写 base 表** 或项目文档化的专用方式，详见 `re-platform-test`。

⚠️ Plugin 抛 `RtClientException` 后，SDK 内部链路（PersistBrokerImpl.create → PluginRunner → PluginBase.execute）可能再包一层 `InvalidPluginExecutionException`（cause 是原异常）。测试断言用 `RtClientException` 或校验 `getMessage()` 文案，避免直接依赖 SDK 内部包装类型。

---

## 查重类 PreCreate / PreUpdate Plugin 模式

适用：按多个字段识别唯一性、在保存前弹窗并阻止保存。

- Step 使用 `PreCreate` + `PreUpdate`；抛 `RtClientException` / `DuplicateRecordException`（带 errorCode + i18n 文案），不要在 Post 阶段做保存拦截。
- `setFilterAttributes` 覆盖所有查重字段；Update 时若 payload 只带部分字段，必须用 `getPrimaryEntityId()` + `ColumnSet` 查询当前记录并合并后再查重。
- 查重条件只查可用记录：通常 `statecode = 0`；字段名和值需来自 R-MCP、SDK 常量或现有代码，并在元数据摘要记录来源。
- Update 查重必须排除当前记录 ID，避免原值保存或只改其他字段时误拦截。
- 原值匹配、大小写敏感的编码/税号类字段优先用 `ConditionOperator.EqualWithCase` 或等价 SQL，并补集成测证明平台行为。
- 使用当前用户服务还是 admin service 要显式说明；若用 admin service，CR 中记录权限可见性风险。
- 无数据库唯一索引时，Plugin 只能做应用层拦截，仍存在并发窗口；方案中记录风险或补偿策略。
- 测试至少覆盖：Checker 单测；IT 验证 create 重复拦截、update 部分字段补齐、自排除、拦截后未落库。

---

## 事件类型

| 类型 | 说明 | 常见场景 |
|------|------|----------|
| `PreCreate` | 创建前 | 数据初始化、默认值设置、校验 |
| `PostCreate` | 创建后 | 关联记录自动创建、发送通知 |
| `PreUpdate` | 更新前 | 变更校验、数据锁定 |
| `PostUpdate` | 更新后 | 状态联动、字段同步、触发流程 |
| `PreDelete` | 删除前 | 关联数据检查、权限校验 |
| `PostDelete` | 删除后 | 级联删除、日志记录 |
| `PreAssign` | 分派前 | 分派规则校验 |
| `PostAssign` | 分派后 | 分派通知、权限更新 |
| `PreActivate` | 激活前 | 激活条件校验 |
| `PostActivate` | 激活后 | 激活初始化 |
| `PreDeactivate` | 停用前 | 停用条件校验 |
| `PostDeactivate` | 停用后 | 停用处理、数据归档 |
| `PreRetrieveMultiple` | 查询前 | 数据过滤、查询拦截 |

---

## PluginBase 常用方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `getContext()` | `IPersistBrokerPluginContext` | 插件上下文 |
| `getEntity()` | `DynamicEntity` | 当前操作的实体 |
| `getBroker()` | `PersistBroker` | 数据库操作（**已在事务中，不要 newBroker()**） |
| `getOrganizationService()` | `OrganizationService` | 组织服务 |
| `getOrganizationServiceAdmin()` | `OrganizationService` | 管理员权限服务 |
| `getPrimaryEntityId()` | `UUID` | 主实体 ID |
| `getPrimaryEntityName()` | `String` | 主实体名称 |
| `getMessageName()` | `String` | 消息名称（create/update/delete） |
| `getStageEnum()` | `PipelineStageEnum` | 管道阶段 |
| `getDepth()` | `int` | 递归深度（防无限递归） |
| `isCreateMessage()` | `boolean` | 是否创建消息 |
| `isUpdateMessage()` | `boolean` | 是否更新消息 |
| `isDeleteMessage()` | `boolean` | 是否删除消息 |

### 校验便捷方法（会抛出异常）

```java
sureMessageNameIsCreate()       // 确保是创建操作
sureMessageNameIsUpdate()       // 确保是更新操作
sureMessageNameIsDelete()       // 确保是删除操作
surePrimaryEntityIs("entity")  // 确保是特定实体
surePreOperationStage()         // 确保是 Pre 阶段
surePostOperationStage()        // 确保是 Post 阶段
```

---

## 完整示例

主 SKILL.md 只保留关键规则。需要完整代码样例时再读取本文件下方的「完整示例代码」段：

- PreCreate：创建前自动填充字段，直接改 `getEntity()`，不调用 `update`
- PostUpdate：事后联动关联实体，必须显式 `broker.update`
- PreDelete：删除前校验，抛 `RtClientException` 阻止删除
- PostCreate：创建后建立关联记录

---

## 递归防护

Plugin 中操作同一实体可能触发自身递归，通过 `getDepth()` 限制：

```java
@Override
public void executePlugin() throws SQLException {
    // 递归深度超过 5，停止执行，防止无限循环
    if (getContext().getDepth() > 5) {
        getContext().getTracingService().warn("插件递归深度超限，停止执行");
        return;
    }

    var entity = getEntity();
    var broker = getBroker();

    // 避免重复处理：标记已处理，再操作同一实体
    if (entity.containsKey("new_processed_flag")
        && Boolean.TRUE.equals(entity.getBooleanFieldValue("new_processed_flag"))) {
        return;  // 已处理过，不再触发
    }

    // 业务逻辑...
    entity.setBooleanFieldValue("new_processed_flag", true);
    broker.update(entity);
}
```

### 跨实体联动的递归防护（补充）

当 A 实体 Plugin 更新 B 实体，而 B 实体 Plugin 又回写 A 实体时，会形成跨实体循环。

建议同时做三层防护：
1. `getDepth()` 上限（防止无限链式触发）；
2. 业务幂等标记（如 `new_processed_flag`、流水号、来源标识）；
3. 触发条件收窄（`filterAttributes` + 状态前后值判断）。

```java
@Override
public void executePlugin() throws SQLException {
    if (getContext().getDepth() > 3) {
        return;
    }

    var entity = getEntity();
    if (entity.containsKey("new_sync_source")
        && "account_plugin".equals(entity.getStringFieldValue("new_sync_source"))) {
        return; // 已由对端联动回写，避免回环
    }

    var accountId = entity.getUUIDFieldValue("new_accountid");
    if (accountId == null) {
        return;
    }

    var account = new DynamicEntity("account", accountId);
    account.setStringFieldValue("new_sync_source", "saleorder_plugin");
    getBroker().update(account);
}
```

---

## 异步插件约束

`step.setAsync(true)` 时有以下约束：

- ❌ **不能** throw 异常阻止主操作（主操作已提交）
- ❌ **不能** 做业务校验（校验结果不影响主流程）
- ❌ **不能** 获取主操作的返回结果
- ✅ **适合**：日志记录、消息通知、刷新缓存、异步数据同步
- ✅ **必须**：自行处理异常和失败（主事务已提交，不会回滚）

```java
@Override
public List<IPersistBrokerPluginStep> getSteps() {
    var step = new PersistBrokerPluginStep();
    step.setEntityName("saleorder");
    step.setEventType(PersistBrokerPluginEventTypes.PostUpdate);
    step.setFilterAttributes("new_orderstatus");
    step.setOrder(0);
    step.setAsync(true);  // 异步，不阻塞主流程
    return List.of(step);
}

@Override
public void executePlugin() throws SQLException {
    // 发送通知，失败了自己记日志，不影响主事务
    try {
        sendNotification(getEntity());
    } catch (Exception e) {
        getContext().getTracingService().error("发送通知失败", e);
    }
}
```

---

## 代码规则

1. 类必须添加 `@Component` 注解
2. 必须继承 `PluginBase`
3. 必须实现 `getSteps()` 和 `executePlugin()` 方法
4. **业务异常用 `RtClientException` / `DuplicateRecordException`，系统异常用 `RtServerException`**，文案必须走 `getLangHelper().get(key, default)` i18n；不用 legacy 的 `InvalidPluginExecutionException`
5. 捕获的异常必须再次抛出或记日志，不要吞掉
6. **使用 `getBroker()`**，禁止 `PersistBrokerFactory.newBroker()`（会脱离主事务）
7. **Pre 阶段修改 entity 后不需要调用 update**（自动持久化）
8. **Post 阶段修改 entity 必须调用 `broker.update()`**（主操作已完成）
9. **事务由框架自动管理，禁止手动包裹 `executeTransaction()`**
10. 操作同一实体时注意递归防护（`getDepth()`）

---

## 失败处理

| 阶段 | 校验失败怎么办 |
|------|--------------|
| **PreCreate / PreUpdate / PreDelete** | 抛出 `RtClientException` 阻止操作 |
| **PostCreate / PostUpdate / PostDelete** | 无法阻止主操作，只能记日志或异步处理 |
| **PreAssign / PreActivate** | 抛出 `RtClientException` 阻止操作 |

---

## 触发条件设置

```java
// 只在特定字段变更时触发（逗号分隔）
step.setFilterAttributes("field1,field2");

// 多个实体/事件
@Override
public List<IPersistBrokerPluginStep> getSteps() {
    return List.of(
        createOrderStep(),
        updateAccountStep()
    );
}

private PersistBrokerPluginStep createOrderStep() {
    var step = new PersistBrokerPluginStep();
    step.setEntityName("saleorder");
    step.setEventType(PersistBrokerPluginEventTypes.PostCreate);
    step.setOrder(0);
    step.setAsync(false);
    return step;
}
```

### filterAttributes 决策树

`setFilterAttributes` 控制 Plugin 仅在指定字段参与 Update 时触发。**不是所有场景都应设置**：

| 场景 | 是否设置 | 说明 |
| --- | --- | --- |
| 仅在状态/类型等关键字段变更时触发 | **设** | `setFilterAttributes("status")`，优化性能，避免无关更新触发 |
| 已审核/已提交等状态下反复修改其他字段也需触发 | **不设** | 状态值不变但反馈/备注变更时仍需校验或联动 |
| 需要监听实体的所有变更 | **不设** | 任何字段变化都要执行逻辑 |
| PreCreate（新建一定触发） | **不设** | 新建时 payload 包含所有字段，filterAttributes 无意义 |

判断口诀：**"只在字段变化时"设，"在某状态下"不设**。

未设置时的注意：每次 Update 都会触发，需要在 `executePlugin()` 首行做状态/条件判断提前 return，避免无效执行。

---

## 事务说明

Plugin 的所有操作在**框架自动管理的事务**中：
- 主操作（create/update/delete）和 Plugin 操作在**同一个事务**
- 任一环节失败，整个事务回滚
- **禁止**在 Plugin 内手动 `executeTransaction()`（嵌套事务行为不可预期）

## 本地自测最小路径

1. 先确认触发条件（实体、事件、`filterAttributes`）是否满足。
2. 通过 API 或业务入口执行一次 create/update/delete。
3. 查询插件副作用（字段回写/关联实体变更）。
4. 查看日志确认执行路径（开始/结束/关键分支）。

如果需要完整本地路径（环境、启动、日志定位、调试顺序），配合 `re-platform-local-selftest`。

---

## Plugin 单元测试的正确姿势

### 直接测 Plugin 本身（推荐）

通过子类注入 mock 的方式绕开框架依赖，不需要额外抽 Service 层：

```java
private static class TestableOrderPlugin extends OrderStatusPlugin {
    private DynamicEntity testEntity;
    private PersistBroker testBroker;
    void setTestEntity(DynamicEntity e) { this.testEntity = e; }
    void setBroker(PersistBroker b) { this.testBroker = b; }
    @Override public DynamicEntity getEntity() { return testEntity; }
    @Override public PersistBroker getBroker() { return testBroker; }
}

@Test
void shouldThrowWhenAccountMissing() {
    plugin.setTestEntity(makeEntity(null));
    when(testBroker.retrieve(any(), any())).thenReturn(null);
    assertThrows(RtClientException.class, () -> plugin.executePlugin());
}
```

### 反模式：为了测试额外抽 Service 层

不要为了"方便测试"而额外造出 Service/Helper 类。如果 Plugin 本身的逻辑可以测，就直接测 Plugin。额外分层会在生产代码中引入不必要的耦合和重复。

**适合抽 Service：** 同一段逻辑需要被多个地方调用，或业务逻辑足够复杂值得独立管理。

**不适合抽：** 只是为了解决"PluginBase 难 mock"的问题，或业务逻辑本身就是 Plugin 的全部职责。

### 测试文件位置

单元测试统一放在**启动模块**（如 `recloud-starter`）的 `src/test/java` 下，不分散到业务模块。

---

> **公共参考**：服务实例获取、DynamicEntity操作、SQL规范、异常处理、时间处理、UUID、数据类型映射等，详见 [re-platform-common](../re-platform-common/guide.md)
