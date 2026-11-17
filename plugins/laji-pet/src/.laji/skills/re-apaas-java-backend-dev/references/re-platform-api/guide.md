# R 平台 API 开发

> **定位**：自定义 API / Controller 开发规范（分层、注解、错误处理、返回约定）。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。实体元数据校验见 [re-platform-mcp/guide.md](../re-platform-mcp/guide.md)。分层约定见 `.cursor/rules/r-platform-java-development.mdc`。

## 决策速查

### 分层原则（优先 server 模式）

默认分层：`Controller -> Server/Service -> DataAccess`。

- 新需求优先走 server 模式（与既有后端规范一致）。
- 现有 Command 逻辑可延续，不强制重构。
- Controller 仅做参数、鉴权、路由、返回，不承载复杂业务。

### Controller 基类选择（两种都支持）

| 基类 | 适用场景 |
| --- | --- |
| `HiddenApiController` | 项目内部 API（多数项目常用） |
| `BaseController` | 通用 API 基类（新模块可用） |

规则：两者都支持，按模块历史保持一致，避免同一模块风格混乱。

### 常用注解

| 注解 | 用途 |
| --- | --- |
| `@OpenApi` | 对外开放接口（第三方调用） |
| `@LoginNotRequired` | 跳过登录校验 |
| `@Anonymous` | 匿名访问 |
| `@ReturnRawApiResult` | 返回原始对象，不包 `ApiResult` |
| `@RouteInfo` | 路由元信息 |

### 错误处理

- 业务可预期错误：`RtClientException`
- 系统错误：`RtServerException`
- 不吞异常，记录上下文日志后抛出

## 返回约定

默认返回（被框架包装）：

```json
{
  "ErrorCode": 0,
  "Message": "",
  "Data": {}
}
```

使用 `@ReturnRawApiResult` 时返回原始对象。

## Broker 使用

API 层统一使用 `PersistBrokerFactory.get()`（禁止 close）；独立事务场景见 [re-platform-common/guide.md](../re-platform-common/guide.md) §1-2。

## API 模板（server 优先）

```java
@RestController
@RequestMapping("ClouAccount")
public class ClouAccountController extends HiddenApiController {

    @Resource
    private ClouAccountServer clouAccountServer;

    @PostMapping("/syncAccountToSap")
    public RestResult<String> syncAccountToSap(@RequestBody SyncAccountToSapRequest request) {
        if (request == null || request.getType() == null) {
            throw new RtClientException("参数不能为空");
        }
        return clouAccountServer.syncAccountToSap(request);
    }
}
```

## InternalApiService 调用

系统由多个服务组成，服务间接口调用需签名授权。用 `InternalApiService` 简化调用，统一异常处理，不在 Controller 里手工拼装 HTTP 客户端。

### 获取实例

```java
@Resource
private InternalApiService internalApiService;
// 或
var internalApiService = ServiceFactory.getService(InternalApiService.class);
```

### URL 签名

```java
String url = "api/account/list?pageIndex=1&pageSize=10"; // 相对路径
String signedUrl = internalApiService.getSignedUrl(url);
```

### 接口调用（GET / POST 及重载）

```java
String body = internalApiService.get("api/workflow/task/complete_list/" + processId);

// GET（指定服务名）
String result = internalApiService.get("CRM", "api/account/list");

// POST
String result = internalApiService.post("api/account/create", body);
// POST（指定服务名并反序列化为目标类型）
Account account = internalApiService.post("CRM", "api/account/create", body, Account.class);
```

> **传相对路径即可**：不需要拼完整路径或 `/t/<tenantCode>`、`timestamp` 等，签名与租户上下文由 `InternalApiService` 统一处理。