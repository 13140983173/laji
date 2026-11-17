# R平台 事务规范

> **定位**：事务边界规范（Broker 获取方式、手动事务模板、executeTransaction 用法、常见陷阱）。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。

## 决策速查

### Broker 生命周期铁律

```java
// ✅ 上下文 broker（框架管理，禁止 close）
var broker = PersistBrokerFactory.get();

// ✅ 独立 broker（必须 close）
try (var broker = PersistBrokerFactory.newBroker()) {
    // ...
}
```

**禁止**：`@Autowired PersistBroker`（多租户环境下可能指向错误租户）

### 事务场景划分

| 场景 | 事务方式 | 手动包裹 |
| --- | --- | --- |
| **Plugin** `executePlugin()` | 自动（框架管） | ❌ 禁止 |
| **BizFunc** `execute()` | 自动（框架管） | ❌ 禁止 |
| **Custom API** `ServiceImpl` | 手动 | ✅ 必须 |
| **OpenAPI** `ServiceImpl` | 手动 | ✅ 必须 |
| **Job** `doExecute()` | 手动 | ✅ 必须 |

### Custom API 分流决策

| 业务目标 | 推荐方式 | 触发Plugin链 |
| --- | --- | --- |
| 标准业务流（必须触发Plugin/权限校验） | `ExecuteTransactionRequest` | ✅ 触发 |
| 批处理/导入导出/底层维护 | `executeTransaction(lambda)` | ❌ 不触发 |

### 高频陷阱速查

| 陷阱 | 错误示例 | 正确做法 |
| --- | --- | --- |
| newBroker忘记close | `newBroker(); query();` | `try (var broker = newBroker()) {...}` |
| Plugin内newBroker | `try (var broker = newBroker()) {...}` | `getBroker()` 共享主事务 |
| 嵌套事务 | `executeTransaction(() -> executeTransaction(() -> {...}))` | 外层失败时内层已提交，用newBroker独立 |
| Plugin/BizFunc手工包事务 | `executePlugin() { broker.executeTransaction(() -> {...}); }` | 直接用 `getBroker()` 操作 |
| 事务范围过大 | 查询也放进事务 | 查询放外面，最小化事务范围 |

---

## Broker 获取方式决策树

```
需要操作数据库？
│
├─ Controller / Service（Custom API / OpenAPI）
│   └─ PersistBrokerFactory.get()     ← 线程单例，框架管理，不需要 close()
│
├─ Job
│   └─ jobExecuteContext.getBroker()  ← 框架注入，不需要 close()
│      或 PersistBrokerFactory.get()
│
├─ Plugin / BizFunc
│   └─ getBroker() / getContext().getBroker()  ← 框架已开启事务，共享主事务
│
└─ 以下场景 → newBroker() + try-finally（独立事务，必须手动 close）
    ├─ 测试代码（隔离环境）
    ├─ 需要与主事务解耦的操作（如日志记录）
    └─ 并发任务（避免连接共享冲突）
```

### get() vs newBroker()

| 维度 | `get()` | `newBroker()` |
|------|---------|--------------|
| 实例 | 线程单例 | 每次新建 |
| 生命周期 | 框架管理，**不要 close()** | 手动管理，**必须 close()** |
| 事务 | 无事务，需手动 `executeTransaction()` | 同上 |
| 多租户 | 自动随上下文切换 | 需自行管理租户 |
| 适用 | 常规业务操作 | 测试、独立事务、并发 |

**⚠️ 禁止 `@Autowired PersistBroker`**：多租户环境下可能指向错误租户。

> 事务场景划分、Custom API 分流决策见本文档开头「决策速查」。

### 同一事务内的服务混用

`PersistBrokerFactory.get()` 获取的 broker 与 `OrganizationService` 在**同一个事务上下文**中：
一个操作提交，另一个也能看到。

---

## 手动事务模板

### Custom API / OpenAPI — ServiceImpl

> 该模板适用于“不依赖 Plugin 链”的场景。  
> 若该业务必须触发 Plugin/标准校验，请改用 `ExecuteTransactionRequest`。

```java
@Service
public class OrderServiceImpl implements OrderService {

    @Override
    public UUID createOrder(CreateOrderRequest request) {
        var broker = PersistBrokerFactory.get();  // 框架注入，不要 new，不要 close

        UUID orderId = broker.executeTransaction(() -> {
            // 1. 创建订单
            var order = new DynamicEntity("saleorder");
            order.setStringFieldValue("new_orderno", generateOrderNo());
            order.setLookupFieldValue("new_accountid",
                new EntityReference("account", request.getAccountId()));
            order.setDecimalFieldValue("new_totalamount", request.getAmount());
            broker.create(order);

            // 2. 创建订单明细
            for (var item : request.getItems()) {
                var detail = new DynamicEntity("saleorderdetail");
                detail.setLookupFieldValue("new_orderid",
                    new EntityReference("saleorder", order.getId()));
                detail.setUUIDFieldValue("new_productid", item.getProductId());
                detail.setIntFieldValue("new_qty", item.getQty());
                broker.create(detail);
            }

            // 3. 更新客户统计
            var account = broker.retrieve("account", request.getAccountId());
            var currentAmount = account.getDecimalFieldValue("new_totalamount");
            account.setDecimalFieldValue("new_totalamount",
                currentAmount.add(request.getAmount()));
            broker.update(account);

            return order.getId();
        });

        return orderId;
    }
}
```

### Job — doExecute

```java
@Component
@JobInfo("DataSyncJob")
public class DataSyncJob extends JobBase {

    @Override
    public void doExecute() throws Exception {
        var logger = jobExecuteContext.getLogger();
        var broker = jobExecuteContext.getBroker();  // 框架注入，不要 new

        var config = jsonProvider.deserializeToBean(SyncConfig.class,
            jobExecuteContext.getJobParam());

        broker.executeTransaction(() -> {
            // 查询待同步数据
            var sql = """
                SELECT * FROM accountbase
                WHERE statecode = 0 AND new_syncstatus = 0
                LIMIT 100
                """;
            var records = broker.retrieveMultiple("account", sql, Map.of(), null, 0, 0);

            for (var record : records) {
                syncToExternal(record, config.getTargetUrl());
                record.setIntFieldValue("new_syncstatus", 1);
                record.setDateTimeFieldValue("new_synctime", RtDateTime.now());
                broker.update(record);  // 在事务内，每条都即时提交
            }

            logger.info("同步完成，共处理 {} 条", records.size());
        });
    }
}
```

---

## executeTransaction(lambda) vs ExecuteTransactionRequest

| 维度 | `executeTransaction(lambda)` | `ExecuteTransactionRequest` |
|------|-----------------------------|-----------------------------|
| 触发插件 | ❌ 不触发 | ✅ 触发 |
| 权限检查 | ❌ 不检查 | ✅ 检查 |
| 性能 | 高（无额外开销） | 标准（有插件链路） |
| 适用场景 | 底层批量操作、导入导出、数据修复 | 标准业务流、需要触发校验/联动 |

**决策：**
- 标准业务操作（需要 Plugin 参与）→ `ExecuteTransactionRequest`
- 批量数据处理、性能优先 → `executeTransaction(lambda)`

### 代码对照（避免误用）

```java
// ✅ 需要触发 Plugin 的标准业务流
var request = new ExecuteTransactionRequest();
request.add(new UpdateRequest().withTarget(orderEntity));
request.add(new UpdateRequest().withTarget(accountEntity));
organizationService.execute(request); // 进入标准链路，触发 Plugin
```

```java
// ✅ 不依赖 Plugin 链的批处理
broker.executeTransaction(() -> {
    broker.update(entity1);
    broker.update(entity2);
});
```

---

## 常见陷阱

### 陷阱1：newBroker() 后忘记 close()

```java
// ❌ 错误：连接泄漏
var broker = PersistBrokerFactory.newBroker();
broker.query("SELECT ...");
// 忘记 close

// ✅ 正确：try-finally
try (var broker = PersistBrokerFactory.newBroker()) {
    broker.query("SELECT ...");
}

// ✅ 正确：手动管理
var broker = PersistBrokerFactory.newBroker();
try {
    broker.query("SELECT ...");
} finally {
    broker.close();
}
```

### 陷阱2：Plugin 内使用 newBroker()

```java
// ❌ 错误：脱离主事务，主事务回滚不受影响
@Override
public void executePlugin() throws SQLException {
    try (var broker = PersistBrokerFactory.newBroker()) {
        var entity = new DynamicEntity("log");
        broker.create(entity);  // 不受主事务控制
    }
}

// ✅ 正确：使用 getBroker()
@Override
public void executePlugin() throws SQLException {
    var broker = getBroker();  // 共享主事务
    var entity = new DynamicEntity("log");
    broker.create(entity);  // 主事务失败时一起回滚
}
```

### 陷阱3：嵌套事务导致外层意外回滚

```java
// ⚠️ 风险：内层 rollback 会导致外层也失败
broker.executeTransaction(() -> {
    broker.create(entity1);
    try {
        broker.executeTransaction(() -> {
            broker.create(entity2);
            throw new RuntimeException("内层失败");
        });
    } catch (Exception ignored) { }
    broker.create(entity3);  // 外层已经标记 rollback，这里会失败
});

// ✅ 正确：需要独立事务的操作，用 newBroker() 在事务外处理
broker.executeTransaction(() -> {
    broker.create(entity1);
});

try (var logBroker = PersistBrokerFactory.newBroker()) {
    logBroker.executeTransaction(() -> {
        var log = new DynamicEntity("error_log");
        logBroker.create(log);  // 独立事务，不影响主事务
    });
}
```

### 陷阱4：事务范围过大

```java
// ❌ 错误：查询也放进事务，占用连接时间过长
broker.executeTransaction(() -> {
    for (int i = 0; i < 1000; i++) {
        broker.query("SELECT * FROM account WHERE id = :id", Map.of("id", ids[i]));
    }
    broker.create(entity);
});

// ✅ 正确：查询放外面，最小化事务范围
List<DynamicEntity> data = new ArrayList<>();
for (int i = 0; i < 1000; i++) {
    data.add(broker.query("SELECT * FROM account WHERE id = :id",
        Map.of("id", ids[i])).get(0));
}

broker.executeTransaction(() -> {
    broker.create(entity);
});
```

### 陷阱5：Plugin / BizFunc 中手工 executeTransaction

```java
// ❌ Plugin 中错误示例：再次包事务
@Override
public void executePlugin() throws SQLException {
    var broker = getBroker();
    broker.executeTransaction(() -> {    // 不允许
        broker.update(entity);
    });
}
```

风险：
- 事务边界与框架边界冲突，行为不可预测；
- 异常传播可能导致外层主事务状态异常；
- 排查问题时难以判断回滚来源。

```java
// ❌ BizFunc 中错误示例：重复开事务
@Override
public XxxResponse execute(XxxRequest request, FunctionExecutionContext context) {
    var broker = getBroker();
    broker.executeTransaction(() -> {    // 不允许
        broker.create(entity);
    });
    return new XxxResponse();
}
```

正确做法：
- Plugin / BizFunc 直接使用 `getBroker()` 执行业务操作；
- 若确需标准消息链，改由调用方在 API/Server 层使用 `ExecuteTransactionRequest`。

---

## 公共参考

> **公共参考**：服务实例获取、DynamicEntity操作、SQL规范、异常处理、时间处理、UUID、数据类型映射等，详见 [re-platform-common](../re-platform-common/guide.md)
