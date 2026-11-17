# R 平台 Server 模式（优先）

> **定位**：Server 模式（Controller → Server/Service → DataAccess）开发规范与代码模板。

## 决策速查

### 核心要点

- **分层**：`Controller -> Server(Service) -> DAO/Broker/OrganizationService`
- **命名**：Server 接口 `XxxServer`，实现 `XxxServerImpl` + `@Service`，DTO `XxxRequest/XxxResponse`
- **Broker**：`PersistBrokerFactory.get()` 禁止 close；`newBroker()` 必须 try-finally close
- **事务**：标准业务流用 `ExecuteTransactionRequest`（触发 Plugin），纯批处理用 `broker.executeTransaction`
- **与 Command**：旧 Command 保持不动，新代码优先 server，不做大范围重构

### Server vs Command 选型

| 维度 | Server 模式 | Command 模式 |
|------|-----------|-------------|
| 结构 | `XxxServer` 接口 + `XxxServerImpl` 实现 | `XxxCommand` 类 + `execute()` 方法 |
| 适合 | 简单 CRUD、单实体操作、可注入多个 Server 的编排 | 多实体事务、复杂业务流程（转化、批量操作） |
| 事务 | 手动 `executeTransaction` | 同上，集中在 `execute()` 中 |
| 参考 | ClouAccountServer | LeadConvertCommand |

## 目标

在二开项目中，新增后端逻辑优先采用 server 模式：

`Controller -> Server(Service) -> DAO/Broker/OrganizationService`

Command 模式与 server 模式兼容，已有 Command 保持不动，新代码优先 server。

## 命名与结构

| 类型 | 规则 |
| --- | --- |
| Server 接口 | `XxxServer` |
| Server 实现 | `XxxServerImpl` + `@Service` |
| DTO | `XxxRequest` / `XxxResponse` |

## 模板

```java
public interface ClouAccountServer {
    RestResult<String> syncAccountToSap(SyncAccountToSapRequest request);
}
```

```java
@Service
public class ClouAccountServerImpl extends BaseCommand implements ClouAccountServer {

    @Resource
    private OrganizationService organizationService;

    @Override
    public RestResult<String> syncAccountToSap(SyncAccountToSapRequest request) {
        var broker = PersistBrokerFactory.get();
        // get() 不要 close
        var account = broker.retrieve("account", request.getAccountId());
        if (account == null) {
            throw new RtClientException("客户不存在");
        }
        return new RestResult<>("成功");
    }
}
```

## 事务规则

- 单一写操作：直接调用 broker/service。
- 多写操作必须一致：按场景选择事务实现。
- 事务里先查后写，尽量缩短锁持有时间。

### 事务实现选择（补充关键决策）

| 场景 | 推荐方式 | 是否触发 Plugin |
| --- | --- | --- |
| 标准业务流（依赖 Plugin/校验/联动） | `ExecuteTransactionRequest` | ✅ 触发 |
| 纯数据批处理（性能优先） | `broker.executeTransaction(() -> { ... })` | ❌ 不触发 |

> 不要默认把所有 Server 事务都写成 `executeTransaction(lambda)`。  
> 是否要触发 Plugin 链路是第一决策条件。

详见 `re-platform-transaction` 的“executeTransaction vs ExecuteTransactionRequest”章节。

## 与 Command 的关系

- 旧模块已有 `BaseCommand`：保持不动，按现状迭代。
- 新模块建议以 server 为主，必要时在 server 内调用现有 Command。
- 不做大规模”Command 改 Server”重构，避免引入回归。

### 为什么需要继承 BaseCommand

当 Service 实现类需要访问平台上下文信息（当前用户 ID、租户、语言等）或调用 `getAdminOrganizationService()`、`getBroker()`、`getOrganizationService()`、`getLangHelper()`、`getLangId()` 等方法时，**必须继承 `BaseCommand`**。`BaseCommand` 提供了以下关键能力：

| 方法 | 说明 |
| --- | --- |
| `getAdminOrganizationService()` | 获取管理员级别的 OrganizationService（跨用户/跨租户操作） |
| `getOrganizationService()` | 获取当前用户上下文的 OrganizationService |
| `getBroker()` | 获取 PersistBroker（数据读写） |
| `getLangHelper()` | 获取多语言帮助类 |
| `getLangId()` | 获取当前语言 ID |

如果不需要上述上下文能力（纯 Spring Bean 注入即可），则不需要继承 `BaseCommand`。

```java
// 需要上下文 → 继承 BaseCommand
@Service
public class AccountInsightServiceImpl extends BaseCommand implements AccountInsightService {

    @Resource
    private AuthorizedContextAccessor authorizedContextAccessor;

    public void someMethod(String name) {
        // 直接使用 BaseCommand 提供的方法
        EntityCollection ec = getAdminOrganizationService().retrieveMultiple(qe);
        List<DynamicEntity> list = getBroker().retrieveMultiple(“account”, sql, params);
    }
}

// 不需要上下文 → 纯 Service 即可
@Service
public class SimpleReportServerImpl implements SimpleReportServer {
    @Resource
    private OrganizationService organizationService;
    // 直接注入 Spring Bean
}
```

## 常见误区

- 在 Controller 里写完整业务流程。
- 在 `PersistBrokerFactory.get()` 上手动 `close()`。
- Server 中抛出底层 SQL 原始错误给前端。

## 最小落地清单

1. Controller 只保留参数校验和路由。
2. Server 承载业务编排。
3. 数据访问集中到 server/dao，不散落在 Controller。
4. 事务边界写在 server 层。
