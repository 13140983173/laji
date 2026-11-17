# 第三方系统对接通用规范

> **定位**：本 guide 是第三方系统对接的**规范入口**，提供认证模式选择和实现 Checklist。
> **代码模板**（Token 缓存、配置获取、脱敏、过期重试）统一沉淀在 [re-platform-common](../re-platform-common/guide.md) §11，本 guide 不重复贴代码。

---

## 一、决策速查

### 认证模式选择器

对接新系统时，**先判断其认证方式**，再按对应模板实现：

```
第三方系统认证方式判断树
│
├─ 是否需要预注册/密钥交换？
│   ├─ 是 → 【RSA验签模式】（如泛微 OA）
│   │       特征：注册获取公钥 → 加密 secret 获取 token → header 传 token
│   │       参考：本 guide 第三节（实现骨架，泛微 OA 为例）
│   │
│   └─ 否 → 继续判断
│
├─ Token 获取方式？
│   ├─ GET 请求，ID + secret 明文 → 【AccessToken 模式】（如企业微信）
│   │       特征：GET 获取 access_token → URL 参数传 token → JSON 请求体
│   │
│   ├─ POST 请求，需签名/加密 → 【签名 Token 模式】（如钉钉、飞书）
│   │       特征：构造签名字串 → POST 获取 token → header 传 token
│   │
│   └─ 长期不变的密钥 → 【APIKey 模式】（如天眼查）
│           特征：请求头固定传 key → 无 token 刷新逻辑
│
└─ 是否需要 OAuth2 授权？
    └─ 是 → 【OAuth2 模式】（如企微部分高级接口）
            特征：授权码 → access_token + refresh_token → 定时刷新
```

选择完成后，记录到任务表备注列（如"认证模式：AccessToken"）。

---

## 二、实现 Checklist

每新增一套第三方系统，按以下步骤执行：

### Step 1：枚举扩展
- [ ] `ThirdSystemEnum` 新增枚举值
- [ ] 确认 `pmi_apilog.pmi_third_system` 选项集已同步（如有）

### Step 2：配置类
- [ ] 新建 `XxxConfig`（baseUrl、timeout、认证相关字段）
- [ ] 系统参数路径：`recloud.salesone.pmi.common.config.XxxConfig`
- [ ] 配置获取遵循 `re-platform-common` §11.8 模板

### Step 3：模型对象
- [ ] `XxxApiRequest`：通用业务请求（apiPath、requestBody、apiName）
- [ ] `XxxApiResponse`：通用业务响应（statusCode、body）
- [ ] `XxxTokenResponse`：Token 接口响应（按实际字段定制）
- [ ] 业务专用 Request/Response（如 `WeChatQySendRequest`）

### Step 4：策略实现
- [ ] 新建 `XxxInvokeStrategy implements ThirdPartyInvokeStrategy<REQ, RESP>`
- [ ] 或 extends `AbstractThirdPartyInvokeStrategy`（如已提取基类）
- [ ] `@Service` 注解（Spring 自动注册到 `ThirdPartyInvoker`）
- [ ] `getSystemType()` 返回对应枚举
- [ ] Token 管理遵循 `re-platform-common` §11.1～11.6
- [ ] HTTP 构建：Content-Type、鉴权位置、超时设置
- [ ] 异常处理：Token 失败 → `RtServerException`，参数校验失败 → `RtClientException`
- [ ] 日志脱敏遵循 `re-platform-common` §11.9

### Step 5：Service 封装
- [ ] `XxxService` 接口 + `XxxServiceImpl` 实现
- [ ] 注入 `ThirdPartyInvoker`
- [ ] 参数校验 → 组装 Request → 调用 Invoker → 解析响应
- [ ] 过期重试遵循 `re-platform-common` §11.10 模板

### Step 6：Controller（如需要）
- [ ] `PmiXxxController extends HiddenApiController`
- [ ] `@RequestMapping("/PmiXxx")` + `@PostMapping` / `@GetMapping`
- [ ] 参数校验（与 Service 层双重保险）

### Step 7：编译验证
- [ ] `mvn compile` 通过
- [ ] JDK 版本与 `config.json` 一致（Stage -1 已检查）

---

## 三、策略接口与路由

所有第三方系统通过统一的策略模式路由，新增系统无需改动现有代码：

```
ThirdPartyInvokeStrategy<REQ, RESP>    ← 策略接口（已有）
    │
    ├── OaInvokeStrategy               ← OA 实现
    ├── WeChatQyInvokeStrategy         ← 企微实现
    ├── XxxInvokeStrategy              ← 新增系统
    │
ThirdPartyInvoker                      ← 统一路由（自动注入所有 @Service 实现）
```

策略接口和 `ThirdPartyInvoker` 的骨架见上文；泛微 OA 的 RSA 验签具体实现未随本 skill 分发，按此骨架自行实现。

---

## 四、常见错误码速查

| 系统 | Token 过期码 | Token 无效码 | 频率限制码 |
| --- | --- | --- | --- |
| 企业微信 | 42001 | 40014 | 45009 |
| 钉钉 | 40001 | 40014 | — |
| 飞书 | 99991663 | 99991661 | — |
| 泛微 OA | 自定义（看 `status` 字段） | 自定义 | — |

> 对接新系统时，在其官方文档中查找 token 过期/无效的错误码，填入 Service 层的 `TOKEN_EXPIRED_CODES` 集合。

---

## 五、与现有 guide 的关系

```
re-platform (技术总入口)
    │
    ├─► re-platform-common §11    ← Token 缓存/配置/脱敏/重试 代码模板
    │
    ├─► re-platform-thirdparty    ← 本 guide：认证选择器 + Checklist
    │       │
    │       └─► （OA 特化：RSA 验签，按本 guide 骨架自行实现）
    │
    ├─► re-platform-api           ← Controller/API 规范
    └─► re-platform-test          ← 测试规范
```

---

## 六、演进路线

| 阶段 | 内容 | 状态 |
| --- | --- | --- |
| Phase 1 | OA 策略 + 企微策略 + 通用规范 | ✅ 已完成 |
| Phase 2 | 提取 `AbstractThirdPartyInvokeStrategy` 基类（代码重构） | 待定 |
| Phase 3 | 钉钉、飞书、用友/金蝶接入 | 按需 |
| Phase 4 | 平台化 Starter（yaml 配置驱动接入） | 长期 |
