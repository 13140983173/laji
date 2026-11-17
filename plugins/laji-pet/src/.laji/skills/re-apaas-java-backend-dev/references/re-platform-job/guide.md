# R平台 定时任务开发

> **定位**：定时任务（JobBase，调度平台触发）开发规范与代码模板。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。实体元数据校验及 `job_prompt` 用法见 [re-platform-mcp/guide.md](../re-platform-mcp/guide.md)。
> 注意：AsyncJob 与 JobBase 是两套模型。AsyncJob 请使用 `re-platform-asyncjob`。

## 决策速查

### JobExecuteContext 速查

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `getTenantCode()` | String | 当前租户编码 |
| `getUserIdentity()` | UserIdentity | 管理员身份 |
| `getOrganizationService()` | OrganizationService | 组织服务 |
| `getBroker()` | PersistBroker | 数据库操作 |
| `getJobParam()` | String | 任务参数（JSON 字符串） |
| `getLogger()` | TracingService | 日志记录器 |

### 代码规则

1. 继承 `JobBase`，添加 `@Component` + `@JobInfo`
2. 实现 `doExecute()`
3. 通过 `jobExecuteContext` 获取所有服务
4. 异常必须再抛，不要吞掉
5. 记录关键日志（开始/结束/处理数量/失败数）
6. 多写操作需要事务时用 `executeTransaction()`（见 [re-platform-transaction](../re-platform-transaction/guide.md)）
7. SQL 表名必须白名单校验，禁止拼接外部输入

### 失败处理

| 场景 | 处理 |
|------|------|
| 参数解析失败 | `throw new RtClientException("参数错误")` |
| 数据库操作失败 | `throw new RtServerException(e)` |
| 单条记录处理失败 | 记录日志后继续，最后汇总失败数 |

## 基本结构

```java
@Component
@JobInfo("DemoJob")  // Job名称，一般与类名一致
public class DemoJob extends JobBase {

    @Override
    public void doExecute() throws Exception {
        // 任务逻辑
    }
}
```

## JobExecuteContext 方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `getTenantCode()` | String | 当前租户编码 |
| `getUserIdentity()` | UserIdentity | 管理员身份 |
| `getOrganizationService()` | OrganizationService | 组织服务 |
| `getBroker()` | PersistBroker | 数据库操作 |
| `getJobParam()` | String | 任务参数（JSON字符串） |
| `getLogger()` | TracingService | 日志记录器 |

## 完整示例

### 示例1：每日客户统计报表

```java
@Component
@JobInfo("DailyAccountReportJob")
public class DailyAccountReportJob extends JobBase {

    @Override
    public void doExecute() throws Exception {
        var logger = jobExecuteContext.getLogger();
        var broker = jobExecuteContext.getBroker();
        var service = jobExecuteContext.getOrganizationService();

        logger.info("开始执行每日客户统计任务");

        // 获取今日日期范围
        var today = RtDateTime.now();
        var startDate = today.toString("yyyy-MM-dd") + " 00:00:00";
        var endDate = today.addDays(1).toString("yyyy-MM-dd") + " 00:00:00";

        // 统计今日新增客户数
        var newAccountSql = """
            SELECT COUNT(*) FROM accountbase
            WHERE createdon >= :startDate AND createdon < :endDate AND statecode = 0
            """;
        int newAccountCount = broker.count(newAccountSql,
            Map.of("startDate", startDate, "endDate", endDate));

        // 统计今日活跃客户数（有跟进记录的客户）
        var activeAccountSql = """
            SELECT COUNT(DISTINCT new_accountid) FROM salevisitbase
            WHERE new_visittime >= :startDate AND new_visittime < :endDate AND statecode = 0
            """;
        int activeAccountCount = broker.count(activeAccountSql,
            Map.of("startDate", startDate, "endDate", endDate));

        // 创建统计记录
        var report = new DynamicEntity("dailyreport");
        report.setStringFieldValue("new_reportdate", today.toString("yyyy-MM-dd"));
        report.setIntFieldValue("new_newaccountcount", newAccountCount);
        report.setIntFieldValue("new_activeaccountcount", activeAccountCount);
        report.setLookupFieldValue("ownerid",
            new EntityReference("systemuser", jobExecuteContext.getUserIdentity().getUserId()));
        broker.create(report);

        logger.info("每日客户统计任务完成：新增{}个，活跃{}个", newAccountCount, activeAccountCount);
    }
}
```

### 示例2：订单超时提醒

```java
@Component
@JobInfo("OrderTimeoutReminderJob")
public class OrderTimeoutReminderJob extends JobBase {

    @Override
    public void doExecute() throws Exception {
        var logger = jobExecuteContext.getLogger();
        var broker = jobExecuteContext.getBroker();

        logger.info("开始执行订单超时提醒任务");

        // 查询超7天未处理的订单
        var timeoutDays = 7;
        var sql = """
            SELECT saleorderid, new_orderno, new_accountid, new_duedate, ownerid
            FROM saleorderbase
            WHERE statecode = 0 AND new_orderstatus = 0
            AND new_duedate < :deadline
            AND NOT EXISTS (
                SELECT 1 FROM systemalertbase
                WHERE new_orderid = saleorderbase.saleorderid
                AND new_alerttype = 'order_timeout'
                AND createdon > :lastCheckTime
            )
            """;
        var deadline = RtDateTime.now().addDays(-timeoutDays).toString("yyyy-MM-dd");
        var lastCheckTime = RtDateTime.now().toString("yyyy-MM-dd HH:mm:ss");

        var timeoutOrders = broker.retrieveMultiple("saleorder", sql,
            Map.of("deadline", deadline, "lastCheckTime", lastCheckTime),
            null, 0, 0);

        for (var order : timeoutOrders) {
            createTimeoutAlert(order, broker);
            logger.info("已创建订单超时提醒: {}", order.getStringFieldValue("new_orderno"));
        }

        logger.info("订单超时提醒任务完成，共处理{}条", timeoutOrders.size());
    }

    private void createTimeoutAlert(DynamicEntity order, PersistBroker broker) throws SQLException {
        var alert = new DynamicEntity("systemalert");
        alert.setStringFieldValue("new_alerttype", "order_timeout");
        alert.setLookupFieldValue("new_orderid",
            new EntityReference("saleorder", order.getId()));
        alert.setStringFieldValue("new_content",
            "订单 " + order.getStringFieldValue("new_orderno") + " 已超过7天未处理");
        alert.setLookupFieldValue("ownerid", order.getLookupFieldValue("ownerid"));
        alert.setIntFieldValue("statecode", 0);
        broker.create(alert);
    }
}
```

### 示例3：数据同步任务（带参数）

```java
@Component
@JobInfo("DataSyncJob")
public class DataSyncJob extends JobBase {

    @Override
    public void doExecute() throws Exception {
        var logger = jobExecuteContext.getLogger();
        var param = jobExecuteContext.getJobParam();

        // 解析任务参数（JSON格式）
        if (param == null || param.isEmpty()) {
            throw new RtClientException("任务参数不能为空");
        }

        var config = jsonProvider.deserializeToBean(SyncConfig.class, param);
        var entityName = config.getEntityName();
        var targetUrl = config.getTargetUrl();

        logger.info("开始同步数据: entity={}, target={}", entityName, targetUrl);

        var broker = jobExecuteContext.getBroker();

        // 表名必须经过白名单校验，禁止将外部输入直接拼接 SQL
        var validEntities = Set.of("account", "contact", "saleorder", "salevisit");
        if (!validEntities.contains(entityName)) {
            throw new RtClientException("不支持的实体类型: " + entityName);
        }
        // SQL 只拼接表名后缀，前缀固定，安全可控
        var sql = """
            SELECT * FROM """ + entityName + """base
            WHERE statecode = 0 AND new_syncstatus = 0
            """;

        var pendingRecords = broker.retrieveMultiple(entityName, sql, Map.of(), null, 0, 0);

        int successCount = 0;
        int failCount = 0;

        for (var record : pendingRecords) {
            try {
                syncRecord(record, targetUrl, broker);
                successCount++;
            } catch (Exception e) {
                failCount++;
                logger.error("同步记录失败: {}", record.getId(), e);
            }
        }

        logger.info("数据同步完成: 成功{}条，失败{}条", successCount, failCount);
    }

    private void syncRecord(DynamicEntity record, String targetUrl, PersistBroker broker) throws SQLException {
        // 调用外部API同步
        // ...

        // 更新同步状态
        record.setIntFieldValue("new_syncstatus", 1);  // 已同步
        record.setDateTimeFieldValue("new_synctime", RtDateTime.now());
        broker.update(record);
    }

    @Data
    public static class SyncConfig {
        private String entityName;
        private String targetUrl;
        private String apiKey;
    }
}
```

## 代码规则

1. 必须继承 `JobBase`
2. 必须添加 `@Component` 和 `@JobInfo` 注解
3. 必须实现 `doExecute()` 方法
4. 使用 `jobExecuteContext` 获取服务
5. 异常必须再次抛出，不要吞掉
6. 记录关键日志便于排查
7. **多个数据库操作需要事务保证时，用 `jobExecuteContext.getBroker()` 获取 broker，调用 `executeTransaction()` 包裹**：详见 [re-platform-transaction](../re-platform-transaction/guide.md)

## 失败处理

- 参数解析失败 → `throw new RtClientException("参数错误: " + e.getMessage())`
- 数据库操作失败 → `throw new RtServerException(e)`
- 外部调用失败 → 记录日志后继续处理其他记录，最后汇总失败数

## 日志记录

```java
var logger = jobExecuteContext.getLogger();

logger.info("任务开始: 参数={}", param);
logger.info("处理记录: id={}, name={}", id, name);
logger.warn("跳过无效记录: id={}", id);
logger.error("处理失败: id={}", id, e);  // 包含异常堆栈
```

## 本地自测最小路径

1. 通过调度平台手动触发一次 Job（推荐）。
2. 验证参数解析、数据库副作用、日志输出。
3. 异常场景下确认失败记录和重试策略是否符合预期。

完整的本地启动/日志定位/排障顺序见 `re-platform-local-selftest`。

---

> **公共参考**：服务实例获取、DynamicEntity操作、SQL规范、异常处理、时间处理、UUID、数据类型映射等，详见 [re-platform-common](../re-platform-common/guide.md) |