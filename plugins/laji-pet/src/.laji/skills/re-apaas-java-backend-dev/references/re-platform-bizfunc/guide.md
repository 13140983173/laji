# R平台 业务函数开发

> **定位**：BizFunc（业务函数）开发规范与代码模板。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。实体元数据校验及 `biz_func_prompt` 用法见 [re-platform-mcp/guide.md](../re-platform-mcp/guide.md)。

## 决策速查

### BizFunc vs Plugin 选择

| 维度 | BizFunc | Plugin |
|------|---------|--------|
| 触发 | 主动调用 | 事件触发 |
| 返回值 | **必须有** | 无 |
| 参数 | 可自定义 | 固定为实体 |
| 适合 | 批量处理、复杂计算、前端按钮调用 | 数据联动、校验、自动触发 |

### FunctionExecutionContext 速查

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `getTenantCode()` | String | 当前租户 |
| `getUserIdentity()` | UserIdentity | 当前用户 |
| `getOrganizationService()` | OrganizationService | 组织服务 |
| `getBroker()` | PersistBroker | 数据库操作 |
| `getTracingService()` | TracingService | 日志记录 |

### 三类文件结构

```
Request 类  ←── 继承 OrganizationRequest  ←── @InArgument 定义输入参数
    │
    ▼
Handler 类  ←── 实现 FunctionHandler       ←── @FunctionInfo + 业务逻辑
    │
    ▼
Response 类  ←── 继承 OrganizationResponse  ←── @OutArgument 定义输出参数
```

### 代码规则

1. **函数名必须以 `EntityPrefix` 值为前缀**（如 `new_`）
2. Request 继承 `OrganizationRequest`，用 `@InArgument`
3. Response 继承 `OrganizationResponse`，用 `@OutArgument`
4. Handler 实现 `FunctionHandler<Request, Response>`，用 `@FunctionInfo`
5. 不要在 Handler 中直接抛客户端异常，用 Response 返回错误
6. 事务由框架管理，禁止手动 `executeTransaction()`

## 基本模板

### 1. Request 类

```java
@Data
@EqualsAndHashCode(callSuper = true)
public class QueryOrderListRequest extends OrganizationRequest {

    @InArgument  // 输入参数
    private UUID customerId;

    @InArgument
    private String status;

    @InArgument(required = false)
    private Integer pageSize;
}
```

### 2. Response 类

```java
@Data
@EqualsAndHashCode(callSuper = true)
public class QueryOrderListResponse extends OrganizationResponse {

    @OutArgument  // 输出参数
    private List<OrderInfo> orderList;

    @OutArgument
    private Integer totalCount;

    @Data
    public static class OrderInfo {
        private UUID orderId;
        private String orderNo;
        private BigDecimal amount;
    }
}
```

### 3. Handler 类

```java
@FunctionInfo(name = "new_queryOrderList")  // 必须以EntityPrefix为前缀
public class QueryOrderListHandler
        implements FunctionHandler<QueryOrderListRequest, QueryOrderListResponse> {

    @Override
    public QueryOrderListResponse execute(QueryOrderListRequest request,
                                          FunctionExecutionContext context) {
        var service = context.getOrganizationService();
        var broker = context.getBroker();

        // 业务逻辑
        var orderList = queryOrders(service, broker,
            request.getCustomerId(), request.getStatus());

        // 构建响应
        var response = new QueryOrderListResponse();
        response.setOrderList(orderList);
        response.setTotalCount(orderList.size());
        return response;
    }

    private List<OrderInfo> queryOrders(OrganizationService service,
                                       PersistBroker broker,
                                       UUID customerId,
                                       String status) {
        // 查询逻辑
        // ...
    }
}
```

## FunctionExecutionContext 方法

| 方法 | 返回值 | 说明 |
|------|--------|------|
| `getTenantCode()` | String | 当前租户 |
| `getUserIdentity()` | UserIdentity | 当前用户 |
| `getOrganizationService()` | OrganizationService | 组织服务 |
| `getBroker()` | PersistBroker | 数据库操作 |
| `getTracingService()` | TracingService | 日志记录 |

## 完整示例

### 示例1：获取客户统计信息

```java
// ==================== Request ====================
@Data
@EqualsAndHashCode(callSuper = true)
public class GetCustomerStatsRequest extends OrganizationRequest {

    @InArgument(description = "客户ID")
    private UUID customerId;

    @InArgument(description = "统计周期(天)", required = false)
    private Integer periodDays = 30;
}

// ==================== Response ====================
@Data
@EqualsAndHashCode(callSuper = true)
public class GetCustomerStatsResponse extends OrganizationResponse {

    @OutArgument(description = "客户ID")
    private UUID customerId;

    @OutArgument(description = "总订单数")
    private Integer totalOrders;

    @OutArgument(description = "总金额")
    private BigDecimal totalAmount;

    @OutArgument(description = "最近拜访次数")
    private Integer recentVisits;

    @OutArgument(description = "客户评级")
    private String rating;
}

// ==================== Handler ====================
@FunctionInfo(name = "new_getCustomerStats")
public class GetCustomerStatsHandler
        implements FunctionHandler<GetCustomerStatsRequest, GetCustomerStatsResponse> {

    @Override
    public GetCustomerStatsResponse execute(GetCustomerStatsRequest request,
                                            FunctionExecutionContext context) {
        var broker = context.getBroker();
        var customerId = request.getCustomerId();
        var periodDays = request.getPeriodDays();

        var response = new GetCustomerStatsResponse();
        response.setCustomerId(customerId);

        try {
            // 查询订单统计
            var orderSql = """
                SELECT COUNT(*) as cnt, COALESCE(SUM(new_totalamount), 0) as total
                FROM saleorderbase
                WHERE new_accountid = :customerId AND statecode = 0
                AND createdon >= :startDate
                """;
            var startDate = RtDateTime.now().addDays(-periodDays).toString("yyyy-MM-dd");
            var orderData = broker.query(orderSql,
                Map.of("customerId", customerId, "startDate", startDate));

            if (orderData != null && !orderData.isEmpty()) {
                response.setTotalOrders(orderData.get(0).getIntFieldValue("cnt"));
                response.setTotalAmount(orderData.get(0).getDecimalFieldValue("total"));
            }

            // 查询拜访次数
            var visitSql = """
                SELECT COUNT(*) FROM salevisitbase
                WHERE new_accountid = :customerId AND statecode = 0
                AND new_visittime >= :startDate
                """;
            int visitCount = broker.count(visitSql,
                Map.of("customerId", customerId, "startDate", startDate));
            response.setRecentVisits(visitCount);

            // 查询客户评级
            var customer = broker.retrieve("account", customerId);
            if (customer != null && customer.containsKey("new_rating")) {
                response.setRating(customer.getStringFieldValue("new_rating"));
            }

        } catch (SQLException e) {
            throw new RtServerException("查询客户统计失败", e);
        }

        return response;
    }
}
```

### 示例2：批量分配客户

```java
// ==================== Request ====================
@Data
@EqualsAndHashCode(callSuper = true)
public class BatchAssignAccountsRequest extends OrganizationRequest {

    @InArgument(description = "客户ID列表")
    private List<UUID> accountIds;

    @InArgument(description = "分配给的用户ID")
    private UUID assigneeId;

    @InArgument(description = "是否发送通知", required = false)
    private Boolean sendNotification = true;
}

// ==================== Response ====================
@Data
@EqualsAndHashCode(callSuper = true)
public class BatchAssignAccountsResponse extends OrganizationResponse {

    @OutArgument(description = "成功数量")
    private Integer successCount;

    @OutArgument(description = "失败数量")
    private Integer failCount;

    @OutArgument(description = "失败记录")
    private List<FailedRecord> failedRecords;

    @Data
    public static class FailedRecord {
        private UUID accountId;
        private String reason;
    }
}

// ==================== Handler ====================
@FunctionInfo(name = "new_batchAssignAccounts")
public class BatchAssignAccountsHandler
        implements FunctionHandler<BatchAssignAccountsRequest, BatchAssignAccountsResponse> {

    @Override
    public BatchAssignAccountsResponse execute(BatchAssignAccountsRequest request,
                                               FunctionExecutionContext context) {
        var service = context.getOrganizationService();
        var broker = context.getBroker();

        var response = new BatchAssignAccountsResponse();
        var successCount = 0;
        var failCount = 0;
        var failedRecords = new ArrayList<BatchAssignAccountsResponse.FailedRecord>();

        for (UUID accountId : request.getAccountIds()) {
            try {
                // 创建分派请求
                var target = new EntityReference("account", accountId);
                var assignee = new EntityReference("systemuser", request.getAssigneeId());
                var assignRequest = new AssignRequest();
                assignRequest.setTarget(target);
                assignRequest.setAssignee(assignee);

                service.execute(assignRequest);

                // 发送通知（如需要）
                if (Boolean.TRUE.equals(request.getSendNotification())) {
                    sendNotification(broker, accountId, request.getAssigneeId());
                }

                successCount++;

            } catch (Exception e) {
                failCount++;
                var failed = new BatchAssignAccountsResponse.FailedRecord();
                failed.setAccountId(accountId);
                failed.setReason(e.getMessage());
                failedRecords.add(failed);
            }
        }

        response.setSuccessCount(successCount);
        response.setFailCount(failCount);
        response.setFailedRecords(failedRecords);

        return response;
    }

    private void sendNotification(PersistBroker broker, UUID accountId, UUID assigneeId) {
        // 发送通知逻辑
    }
}
```

## 代码规则

1. **函数名必须以系统参数 `EntityPrefix` 值为前缀**（如 `new_`）
2. Request 继承 `OrganizationRequest`，使用 `@InArgument`
3. Response 继承 `OrganizationResponse`，使用 `@OutArgument`
4. Handler 实现 `FunctionHandler<Request, Response>`，使用 `@FunctionInfo`
5. 不要在 Handler 中直接抛出客户端异常，用 Response 返回错误信息
6. **事务由框架自动管理，禁止手动包裹 `executeTransaction()`**：详见 [re-platform-transaction](../re-platform-transaction/guide.md)

## 调用方式

业务函数可以被以下方式调用：

1. **前端脚本**：通过工作流或按钮调用
2. **后端代码**：
```java
var service = OrganizationServiceFactory.createService();
var paramList = new ArrayList<>();
paramList.add(request);
var result = service.invokeFunction("new_queryOrderList", paramList);
```
3. **其他业务函数**：通过 `FunctionExecutionContext` 或直接调用

## 失败处理

- 参数校验失败 → 在 Response 中设置错误字段，不要抛异常
- 数据库异常 → `throw new RtServerException(e)`
- 业务逻辑错误 → 在 Response 中包含错误信息