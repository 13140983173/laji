# R 平台 AsyncJob（工程实践版）

> **定位**：AsyncJob（业务事件触发的异步任务）开发规范与代码模板。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。事务边界见 [re-platform-transaction/guide.md](../re-platform-transaction/guide.md)。

## 决策速查

### AsyncJob vs JobBase 选择

| 维度 | AsyncJob | JobBase |
|------|----------|---------|
| 触发 | 业务事件触发 | 调度平台定时触发 |
| 基类 | `AsyncJobBase` | `JobBase` |
| 事务 | 自行控制，与主流程隔离 | 自行控制 |
| 典型场景 | 审批后异步回写、批处理 | 每日统计、定时通知 |

### 最小结构

```java
@Component
@JobInfo("XxxAsyncJob")
public class XxxAsyncJob extends AsyncJobBase {
    @Override
    public void doExecute(AsyncJobExecutionContext context) {
        var logger = context.getLogger();
        var idObj = context.getParamList().get("id");  // 参数需判空
        var broker = context.getBroker();
        broker.executeTransaction(() -> {
            // 事务内操作
        });
    }
}
```

## 核心模型

当前规范下 AsyncJob 采用 `AsyncJobBase` 子类，不是 BizFunc 包装模式。

```java
@Component
@JobInfo("ClouOrdBillingAfterAgreeJob")
public class ClouOrdBillingAfterAgreeJob extends AsyncJobBase {
    @Override
    public void doExecute(AsyncJobExecutionContext context) {
        var logger = context.getLogger();
        logger.error("===ClouOrdBillingAfterAgreeJob Start===");
        // ...
    }
}
```

## 参数与上下文

```java
Object billingIdObj = context.getParamList().get("billingId");
UUID billingId = RtUtil.tryParseUUID(billingIdObj);
var broker = context.getBroker();
```

- 参数来自 `context.getParamList()`。
- 参数需要显式判空和类型转换。
- 任务内部日志统一打关键开始/结束标记。

## 事务边界

```java
broker.executeTransaction(() -> {
    // 多条写操作
});
```

- AsyncJob 内部事务自行控制。
- 主流程与 AsyncJob 事务隔离，失败不会回滚主流程已提交数据。

## 推荐模板

```java
@Component
@JobInfo("XxxAsyncJob")
public class XxxAsyncJob extends AsyncJobBase {
    @Override
    public void doExecute(AsyncJobExecutionContext context) {
        var logger = context.getLogger();
        logger.info("XxxAsyncJob start");

        Object idObj = context.getParamList().get("id");
        if (idObj == null) {
            logger.warn("missing id");
            return;
        }

        var broker = context.getBroker();
        broker.executeTransaction(() -> {
            // query + update
        });

        logger.info("XxxAsyncJob end");
    }
}
```

## 常见问题

1. 误把 AsyncJob 写成 `FunctionHandler`。
2. 参数未判空直接强转导致空指针。
3. 长事务包太大导致锁冲突。
4. 失败后未记录关键业务上下文，难以排查。

## 本地自测最小路径

1. 优先通过真实业务入口触发（审批通过、业务动作等）。
2. 若无便捷入口，提供仅测试环境可用的触发 API（包装 `ExecuteAsyncJobRequest`）。
3. 验证三件事：任务状态、数据副作用、错误日志。

环境准备与日志排障细则见 `re-platform-local-selftest`。
