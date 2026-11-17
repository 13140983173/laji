# R 平台公共规范

> **定位**：R 平台二开公共规范，被所有模块 guide.md 共享引用。覆盖服务获取、异常、事务、SQL、common-ext 项目工具。

## ⚠️ SDK 类签名验证（写代码前必读）

写代码遇到 R 平台 SDK 类时，**必须**先查本文件 §0 与 §9.1，不要凭经验推断签名。

### 0.1) 包路径速查

按用途归类的常用 SDK 包路径（仅列举本规范各章节已实际引用的；未列出的包请用 `jar tf` + `javap` 现场确认）：

| 包路径 | 主要类型 | 本文出处 |
| --- | --- | --- |
| `recloud.one.sdk.exception` | `RtClientException` / `DuplicateRecordException` / `RtServerException` | §3 |
| `recloud.one.sdk.core` | `OrganizationService` / `LangHelper` | §1、§3.1 |
| `recloud.one.sdk.cache` | `CacheProvider` | §11 |
| `recloud.one.sdk.distribution` | `DistributedLockService` / `DistributedResult` | §11 |
| `recloud.one.sdk.messages` | `GenerateSequenceNumberRequest` / `GenerateSequenceNumberResponse` | §7.1 |
| `recloud.one.sdk.utils` | `RtUtil` | §6、§7.1 |

> 依赖边界规则：本规范未给出"稳定/谨慎/禁止"分级。新引入包前用 `jar tf` 核对包名真实存在，并在本表追加；不要假设未列出的包可自由依赖。

### 0.2) 高频使用类签名

**高频使用类**（首次用到时务必查证）：
- DynamicEntity / DataRow：字段类型化 getter/setter 完整签名
- RtDateTime：extends java.util.Date，无 toLocalDateTime()
- Money：getter 返回 Money 对象，非 BigDecimal
- OptionSetValue：getIntValue() / getValue() / getName() 用途区别
- PersistBroker：retrieve / query 均 throws SQLException
- CacheProvider.set()：三参数（key, value, expireSeconds），非两参数
- RestResult：框架自动包装，业务侧直接返回业务对象

> 新发现的 SDK 类签名会持续追加到 §9.1。

## 0) 需求与方案裁决规则（RQ1～RQ5）

当 `plan_prompt`、上游方案、`re-platform` 子 guide 或 `.cursor/rules/r-platform-java-development.mdc` 建议冲突时，按下列顺序裁决（与 `re-platform-mcp` 第四节一致）：

| 编号 | 规则 | 说明 |
| --- | --- | --- |
| **RQ1** | 流程门禁优先 | 用户未确认方案时不得写业务代码（方案门禁由需求侧流程负责，不在本 skill） |
| **RQ2** | 项目形态优先于通用分层 | salesone_java 已用 Controller→Command 时延续 Command，不为套用「Server 优先」做无关重构（`.cursor/rules/r-platform-java-development.mdc`） |
| **RQ3** | 元数据事实优先于推断 | 字段 logicalName、选项集以 R-MCP `get_entity_details` 或用户书面确认为准，禁止臆造 |
| **RQ4** | 平台扩展点选型 | API / Plugin / BizFunc / Job / AsyncJob 按 `re-platform` 路由表与场景选型；Pre/Post、事务见对应子 guide |
| **RQ5** | 最小改动与可验证 | 在 RQ1～RQ4 满足前提下，优先最小 diff；声称完成须有本次可复现验证证据 |

任务表「备注」列应写明违反了哪条建议及采纳 RQ 的结论。

## 1) 服务实例获取

```java
var broker = PersistBrokerFactory.get();                  // 请求/上下文 broker，不 close
var newBroker = PersistBrokerFactory.newBroker();         // 独立 broker，用完 close
var service = OrganizationServiceFactory.createService(); // 普通服务
var adminService = OrganizationServiceFactory.createAdminService(); // 管理员服务
```

| 场景 | 推荐 |
| --- | --- |
| 常规业务 | `PersistBrokerFactory.get()` |
| 独立事务或特殊隔离 | `PersistBrokerFactory.newBroker()` |
| 平台消息请求 | `OrganizationService` |
| 系统级操作 | `createAdminService()` |

## 2) Broker 生命周期

- `get()` 返回的 broker 不要手工 `close()`。
- `newBroker()` 必须 `try/finally close()`。
- `OrganizationService` 不需要 `close()`。

## 3) 异常约定

所有异常在 `recloud.one.sdk.exception`（**单数**）。

| 异常 | 场景 | 客户端可见 | i18n |
| --- | --- | --- | --- |
| `RtClientException` | 业务规则/参数错误/查重冲突 | 是 | 支持 errorCode |
| `DuplicateRecordException` | 重复记录（extends RtClientException） | 是 | 同上 |
| `RtServerException` | 系统内部错误/外部调用失败 | 否 | 不需要 |
| `InvalidPluginExecutionException` | legacy CRM Plugin 阻断 | 是 | — |

业务异常一律走 `RtClientException` / `DuplicateRecordException`，不用 legacy 的 `InvalidPluginExecutionException`。

### 3.1) i18n 用法

`RtClientException(int errorCode, String message)` 构造支持 errorCode 透传给客户端做 i18n 查找。Plugin 内文案必须走 `getLangHelper()`：

```java
// Plugin 上下文内
String msg = getLangHelper().get("account_name_required", "客户名称不能为空");
throw new RtClientException(4001, msg);

// 或用 SDK 内置业务异常子类
throw new DuplicateRecordException(msg);

// 非 Plugin 上下文（Service/Controller）需通过 LangHelper 注入或直接传 errorCode
throw new RtClientException(4001, "客户名称不能为空");  // 默认中文，客户端按 errorCode 查本地资源
```

LangHelper 签名（recloud.one.sdk.core.LangHelper）：

```java
boolean isMultilingualEnabled();
String get(String key);
String get(String key, String defaultMessage);
String get(int langId, String key);
String get(int langId, String key, String defaultMessage);
```

### 3.2) 日志规范

类头统一 `@Slf4j`（lombok），禁止 `System.out.println` / `e.printStackTrace()` / 静态 Logger 实例。

| 等级 | 场景 |
| --- | --- |
| `log.info` | 流程节点、关键路径跟踪（Plugin 触发、外部调用开始） |
| `log.warn` | 业务规则触发、可恢复降级、降级路径 |
| `log.error` | 系统错误、外部调用失败、不可恢复异常（带 throwable 打全栈） |

异常处理模式：

```java
try {
    // 业务逻辑
} catch (RtClientException e) {
    throw e;                                   // 业务异常直接上抛，不再记 error 日志
} catch (Exception e) {
    log.error("Plugin 执行失败: entityId={}", entityId, e);   // 带 throwable 打全栈
    throw new RtServerException("系统异常", e);
}
```

禁止：catch 后既不抛也不记日志（吞异常）。

## 4) SQL 约定

- 表名默认：`{entityLogicalName}base`。
- 禁止字符串拼接参数，统一命名参数。
- 动态表名必须白名单校验。

## 5) DynamicEntity 取值约定

- 先 `containsKey()` 再取值。
- 日期统一 `RtDateTime`，避免 `Date` / `LocalDateTime` 混用。
- 实体逻辑名必须走常量，不写魔法字符串。

### 5.1) 字段类型 ↔ Java 类型 ↔ get/set 方法（速查表）

取值/赋值必须**严格按字段类型匹配**，不可混用：

| 字段类型 | Java 类型 | 取值方法 | 设值方法 |
|---------|----------|---------|---------|
| 文本 | String | `getStringFieldValue` | `setStringFieldValue` |
| 整型 | Integer | `getIntFieldValue` | `setIntFieldValue` |
| 十进制 | BigDecimal | `getDecimalFieldValue` | `setDecimalFieldValue` |
| 布尔 | Boolean | `getBooleanFieldValue` | `setBooleanFieldValue` |
| 金额 | Money | `getMoneyFieldValue` | `setMoneyFieldValue` |
| 日期 | RtDateTime | `getDateTimeFieldValue` | `setDateTimeFieldValue` |
| 选项集 | OptionSetValue | `getPicklistFieldValue` | `setPicklistFieldValue` |
| 多选选项集 | List\<OptionSetValue\> | `getPicklistArrayFieldValue` | `setPicklistArrayFieldValue` |
| 查找(Lookup) | EntityReference | `getLookupFieldValue` | `setLookupFieldValue` |
| MultiTypeLookup / RegardingObject | EntityReference | `getLookupFieldValue` | `setLookupFieldValue`（logicalName 必须赋值） |
| PartyList | List\<EntityReference\> | `getPartyListFieldValue` | `setPartyListFieldValue`（logicalName 必须赋值） |

> **金额特例**：`getMoneyFieldValue()` 返回 `Money` 对象（非 `BigDecimal`），取数值用 `.getValue()`，赋值用 `setMoneyFieldValue(field, new Money(value))`。

其它常用方法：`getId()` / `setId(UUID)`、`getLogicalName()` / `setLogicalName(String)`、`containsKey(String)`、`getFieldFormattedValue(String)`（字段格式化值/友好名）、`toEntityReference()`。

### 5.2) 实体属性类型 ↔ PostgreSQL 类型 ↔ Java 类型映射

写 SQL（PersistBroker/SqlDbClient，表名 = 实体名 + `base`）或处理字段时的类型对应：

| 实体属性类型 | PostgreSQL 类型 | Java 类型 |
|-------------|----------------|----------|
| Boolean | boolean | Boolean |
| DateTime / TimeStamp | timestamp | RtDateTime |
| Decimal / Money | decimal(38,10) | BigDecimal |
| Integer / Picklist / State / Status | integer | Integer |
| Lookup / Customer / Owner / MultiTypeLookup / Uniqueidentifier / PrimaryKey | uuid | UUID |
| Memo / String / EntityName / EntityLogicalName / Json / JsonB | text / json / jsonb | String |
| PartyList | uuid[] | UUID[]（需转换为 List\<EntityReference\>） |
| BigInt | bigint | Long |
| Image / Binary | bytea | byte[] |
| PicklistArray | int[] | int[] |

### 5.3) 实体公共（系统）属性

所有实体默认带以下系统属性，可直接读取，无需建模：

| 属性 | 类型 | 说明 |
|------|------|------|
| createdby | Lookup(systemuser) | 创建者 |
| createdon | RtDateTime | 创建时间 |
| modifiedby | Lookup(systemuser) | 修改者 |
| modifiedon | RtDateTime | 修改时间 |
| ownerid | Lookup(systemuser) | 负责人 |
| owningbusinessunit | Lookup(businessunit) | 负责部门 |
| statecode | State(0=可用, 1=停用) | 状态 |

> 实体详细结构通过 R-MCP `get_entity_details` 获取，全部实体概要通过 `get_all_entity_metadata` 获取（见 [re-platform-mcp](../re-platform-mcp/guide.md)）。

## 6) 时间与 UUID

```java
var now = RtDateTime.now();
var id = RtUtil.newUUID();
var parsed = RtUtil.tryParseUUID(idString);
```

## 7) common-ext（项目本地工具）

这是项目实践层扩展，优先参考当前工程现有模块用法。

| 工具/常量 | 作用 |
| --- | --- |
| `EntityNameConstants` | 统一维护实体逻辑名 |
| `CrmHelper` | 常见判空、查询、字段安全访问 |
| `OptionSetUtil` | OptionSet 名称和值转换 |
| `StringConvertUtil` | 字符串转换与格式化 |
| `ApprovalStatusEnum` | 审批状态值统一枚举 |
| `SequenceNumberHelper` | 流水号生成（可参考下方示例创建） |

### 7.1) 流水号生成工具类示例

以下代码可根据项目包名调整后直接使用：

```java
import recloud.one.sdk.core.OrganizationService;
import recloud.one.sdk.messages.GenerateSequenceNumberRequest;
import recloud.one.sdk.messages.GenerateSequenceNumberResponse;
import recloud.one.sdk.utils.RtUtil;

import java.text.SimpleDateFormat;
import java.util.Date;

/**
 * 流水号生成工具类
 */
public class SequenceNumberHelper {

    /**
     * 生成流水号（int类型）
     */
    public static int getNextSequenceNumber(OrganizationService service, String entityName, String prefix) {
        var request = new GenerateSequenceNumberRequest();
        request.setSequenceName(entityName);
        request.setSequencePrefix(prefix);
        var response = (GenerateSequenceNumberResponse) service.execute(request);
        return response.getNextSequenceNumber();
    }

    /**
     * 获取流水号（带日期，默认4位补零）
     * 格式：prefix + yyyyMMdd + 4位流水号
     * 示例：UDTDTTH202407240002
     */
    public static String getNumber(OrganizationService service, String entityName, String prefix) {
        String date = formatDate(new Date(), "yyyyMMdd");
        String agreeId = prefix + date;
        int nextSequenceNumber = getNextSequenceNumber(service, entityName, agreeId);
        return agreeId + padZero(nextSequenceNumber, 4);
    }

    /**
     * 获取流水号（带日期，动态位数补零）
     */
    public static String getNumber(OrganizationService service, String entityName, String prefix, int digit) {
        String date = formatDate(new Date(), "yyyyMMdd");
        String agreeId = prefix + date;
        int nextSequenceNumber = getNextSequenceNumber(service, entityName, agreeId);
        return agreeId + padZero(nextSequenceNumber, digit);
    }

    /**
     * 获取流水号（自定义日期格式）
     */
    public static String getNumber(OrganizationService service, String entityName, String prefix, String pattern, int digit) {
        String date = formatDate(new Date(), RtUtil.isNullOrEmpty(pattern) ? "yyyyMMdd" : pattern);
        String agreeId = prefix + date;
        int nextSequenceNumber = getNextSequenceNumber(service, entityName, agreeId);
        return agreeId + padZero(nextSequenceNumber, digit);
    }

    /**
     * 获取流水号（不带日期）
     */
    public static String getNumberWithoutDate(OrganizationService service, String entityName, String prefix, int digit) {
        int nextSequenceNumber = getNextSequenceNumber(service, entityName, prefix);
        return prefix + padZero(nextSequenceNumber, digit);
    }

    private static String formatDate(Date date, String pattern) {
        if (RtUtil.objectIsNull(date)) {
            return "";
        }
        return new SimpleDateFormat(pattern).format(date);
    }

    private static String padZero(int number, int digit) {
        String numberStr = String.valueOf(number);
        if (numberStr.length() < digit) {
            return String.format("%0" + digit + "d", number);
        }
        return numberStr;
    }
}
```

### common-ext 使用规则

1. 新逻辑优先复用现有工具，不重复发明工具类。
2. 工具类调用后仍要做空值保护，不假设返回非空。
3. 通用实体名统一从 `EntityNameConstants` 获取。

## 8) 跨实体字段映射模式

适用：实体转化、数据复制、关联记录自动创建（如 Lead → Account/Contact/Opportunity）。

```java
// 映射表定义（常量类或 Map）
private static final Map<String, String> LEAD_TO_ACCOUNT_MAP = Map.of(
    "companyname", "name",
    "mobilephone", "new_telephone",
    "emailaddress1", "new_email"
    // ...
);

// 通用映射方法
private void mapFields(DynamicEntity source, DynamicEntity target, Map<String, String> fieldMap) {
    for (var entry : fieldMap.entrySet()) {
        String sourceField = entry.getKey();
        String targetField = entry.getValue();
        if (source.containsKey(sourceField)) {
            target.setStringFieldValue(targetField, source.getStringFieldValue(sourceField));
        }
    }
}
```

注意事项：
- 源字段不存在时跳过（不写 null），用 `containsKey()` 判断
- Lookup 字段需要 `new EntityReference(targetEntityName, sourceId)` 构造
- Money 字段用 `getMoneyFieldValue().getValue()` 取值，`setMoneyFieldValue(field, new Money(value))` 赋值
- 同名字段可直接赋值，不同名字段走映射表

## 9) 常见易错点

1. 把 `PersistBrokerFactory.get()` 当作可关闭资源。
2. 在 Controller 中直接堆叠 SQL 与事务逻辑。
3. try/catch 后吞异常。
4. 同一模块混用多套实体逻辑名字符串。
5. 凭记忆推断 SDK 包名或方法签名（必须用 `jar tf` + `javap` 验证）。
6. 凭直觉推断跨实体关联关系（必须走 R-MCP `get_entity_details` 验证 lookup 字段指向）。

### 9.1 SDK API 易混淆方法

以下方法名容易写错，不确定时务必用 `javap` 确认：

| 易错写法 | 正确写法 | 说明 |
| --- | --- | --- |
| `entity.getEntityName()` | `entity.getLogicalName()` | `DynamicEntity` 返回实体逻辑名 |
| `service.retrieve(QueryExpression)` | `service.retrieveMultiple(QueryExpression)` | `OrganizationService.retrieve` 只支持 `(String, UUID, ColumnSet)`；查询多条用 `retrieveMultiple` |
| `service.retrieve(String, UUID, ColumnSet)` | 同左 | 单条查询的正确签名 |
| `broker.retrieve(...)` 不声明异常 | 方法签名 `throws SQLException` | 测试方法需添加 `throws SQLException` |
| `entity.getStringFieldValue(field)` 返回非空 | 可能返回 `null` | 先 `containsKey(field)` 再取值 |
| `broker.query()` 返回 `List` | 返回 `DataTable` | Mock 时 `thenReturn(new DataTable())` |

## 10) 文件操作提醒

### 10.1 附件/文档处理

收到 xlsx / docx 等附件时，使用 `/rt-convert2MD <文件路径>` 转为 Markdown 后读取，不依赖环境直接解析 Excel / Word。

### 10.2 前端文件编辑

- 编辑 Vue / JS / TS 前端文件前，先用 `cat -A` 或 `sed -n 'N,Mp' file | cat -A` 确认缩进字符（tab vs 空格），避免 Edit 工具因缩进不匹配失败。
- 含中文字符的文件，优先使用 Read 工具精确获取内容再编辑，避免编码差异导致匹配失败。

## 11) Token 缓存与并发防护模式

适用：任何需要缓存凭据（Token、SessionKey 等）并防止并发刷新的场景。典型用于第三方系统集成（OA、企微、SAP 等），但不限于第三方——任何 `CacheProvider` + `DistributedLockService` 组合场景均可复用。

### 11.1 核心依赖

```java
import recloud.one.sdk.cache.CacheProvider;
import recloud.one.sdk.distribution.DistributedLockService;
import recloud.one.sdk.distribution.DistributedResult;
```

### 11.2 Key 命名约定

| 类型 | 格式 | 示例 |
| --- | --- | --- |
| 凭据缓存 | `{system}:token:{identifier}` | `oa:token:myAppId`、`wechat_qy:token:ww1234567` |
| 关联数据缓存 | `{system}:{dataType}:{identifier}` | `oa:spk:myAppId`、`oa:secrit:myAppId` |
| 分布式锁 | `{system}:token:refresh:{identifier}` | `oa:token:refresh:myAppId` |

原则：同一系统的 key 前缀统一，便于排查和批量清理。

### 11.3 通用骨架代码

```java
// ===== 缓存对象：单 key 存储，避免多 key 不一致 =====
@Data @AllArgsConstructor @NoArgsConstructor
private static class TokenEntry implements Serializable {
    private String token;
    private String expiredTime;   // 格式由实现方定义
}

// ===== 获取有效凭据（核心方法） =====
private String getValidToken(/* 按需传 config */) {
    String entryKey = CACHE_KEY_TOKEN + identifier;

    // 1. 查缓存
    TokenEntry entry = getCacheObject(entryKey, TokenEntry.class);
    if (entry != null && isTokenValid(entry)) {
        return entry.getToken();
    }

    // 2. 缓存未命中 → 加分布式锁
    String lockKey = LOCK_KEY_PREFIX + identifier;
    DistributedResult result = lockService.tryLock(lockKey, () -> {
        // 3. double-check：持锁后再查一次缓存
        TokenEntry inner = getCacheObject(entryKey, TokenEntry.class);
        if (inner != null && isTokenValid(inner)) {
            return inner.getToken();
        }
        // 4. 回源刷新
        return doRefreshToken(/* config */);
    });

    if (result == null || !result.isLock() || StrUtil.isBlank(result.getReturnValue())) {
        throw new RtServerException("Token 获取失败: " + identifier);
    }
    return result.getReturnValue();
}

// ===== 回源刷新（实现方各自写认证逻辑） =====
private String doRefreshToken(/* config */) {
    // 1. 调用远程接口获取新 token
    // 2. 构造 TokenEntry
    // 3. 写缓存，TTL = token 有效期 + 缓冲时间
    cacheProvider.set(entryKey, JSONUtil.toJsonStr(entry),
            tokenExpireSeconds + CACHE_HOLD_SECONDS);
    return entry.getToken();
}
```

### 11.4 缓存 TTL 策略

```
缓存 TTL = token 实际有效期 + 缓冲时间（建议 300~600 秒）
```

- 缓冲时间的作用：token 即将过期但缓存未失效时，提前刷新以避免请求携带过期 token。
- 过期判定建议提前 5 分钟（`LocalDateTime.now().plusMinutes(5).isAfter(expiredTime)`）。

### 11.5 CacheProvider 辅助方法

```java
private String getCacheString(String key) {
    Object value = cacheProvider.get(key);
    return value != null ? value.toString() : null;
}

private <T> T getCacheObject(String key, Class<T> clazz) {
    Object value = cacheProvider.get(key);
    if (value == null) return null;
    String str = value.toString();
    if (StrUtil.isBlank(str)) return null;
    try {
        return JSONUtil.toBean(str, clazz);
    } catch (Exception e) {
        log.warn("缓存对象反序列化失败, key={}", key, e);
        return null;
    }
}
```

### 11.6 注意事项

1. **TokenEntry 用单 key 存储**：不要把 token 和 expiredTime 拆成两个 key，分布式环境下可能出现不一致。
2. **tryLock lambda 内必须 double-check**：避免多个线程同时发现缓存 miss，只有一个持锁刷新后，其余线程直接拿缓存结果。
3. **缓存对象必须 implements Serializable**：`CacheProvider` 部分实现可能依赖序列化。
4. **异常不要吞**：`doRefreshToken` 失败时应抛 `RtServerException`，让调用方感知；不要 catch 后返回 null。
5. **日志记录刷新事件**：`log.info("{system} Token 刷新成功: identifier={}", id)`，便于排查 token 相关问题。

### 11.7 完整实现参考

各第三方系统的差异仅在"回源刷新"（`doRefreshToken`）和"凭据校验"（`isTokenValid`）两处：

| 系统 | 回源逻辑 | 过期判定 | 参考 guide |
| --- | --- | --- | --- |
| 泛微 OA | RSA 加密 secret → 换取 token | expiredTime 字段解析比对 | 项目内实现，参照本节骨架 |
| 企业微信 | corpid + corpsecret → access_token | expires_in 倒计时 | 项目内实现，参照本节骨架 |
| SAP | 待定 | 待定 | — |

新增第三方系统时，按本节骨架实现 `getValidToken` + `doRefreshToken`，策略接口和路由见 `re-platform-thirdparty/guide.md` 的 `ThirdPartyInvokeStrategy` + `ThirdPartyInvoker` 模式。

### 11.8 配置获取模板

通过 `SystemParameterProvider` 读取第三方系统配置的标准写法：

```java
private XxxConfig getXxxConfig() {
    SystemParameterProvider provider = ServiceProviderUtil.get(SystemParameterProvider.class);
    if (provider == null) {
        throw new RtServerException("SystemParameterProvider 不可用");
    }
    XxxConfig config = provider.getConfig(XxxConfig.class,
            "recloud.salesone.pmi.common.config.XxxConfig");
    if (config == null) {
        throw new RtServerException("Xxx 配置未找到，请检查系统参数");
    }
    return config;
}
```

注意事项：
- Config 类路径必须与 R 平台系统参数中注册的完整类名一致。
- `provider == null` 和 `config == null` 都是运行环境问题，用 `RtServerException`。

### 11.9 敏感信息脱敏模板

日志中打印 token、secret 等敏感信息时的标准脱敏方法：

```java
private String maskSensitive(String value) {
    if (StrUtil.isBlank(value)) return null;
    return value.length() > 8
        ? value.substring(0, 4) + "****" + value.substring(value.length() - 4)
        : "****";
}
```

使用场景：
- `log.info("Token 刷新成功: token={}", maskSensitive(token))`
- `log.warn("使用 secret 获取 token: secret={}", maskSensitive(secret))`
- **禁止**在日志中输出完整的 token、secret、corpSecret。

### 11.10 Service 层 Token 过期重试模板

第三方系统返回 token 过期错误码时，Service 层清除缓存并重试一次的标准写法：

```java
// ===== Service 层调用 + 过期重试 =====

private static final Set<Integer> TOKEN_EXPIRED_CODES = Set.of(42001, 40014);
// 各系统错误码不同，按实际情况调整：
// 企微: 42001(过期), 40014(无效)
// 钉钉: 40001(过期), 40014(无效)
// 飞书: 99991663(过期), 99991661(无效)

public BizResponse callThirdParty(BizRequest bizRequest, boolean isRetry) {
    XxxConfig config = getXxxConfig();
    XxxApiRequest apiRequest = buildApiRequest(bizRequest, config);

    XxxApiResponse apiResponse = thirdPartyInvoker.invoke(
            ThirdSystemEnum.XXX, apiRequest);

    BizResponse bizResp = parseResponse(apiResponse);

    // 检测 token 过期 → 清缓存 → 重试一次
    if (!isRetry && bizResp.getErrcode() != null
            && TOKEN_EXPIRED_CODES.contains(bizResp.getErrcode())) {
        cacheProvider.remove(CACHE_KEY_TOKEN_ENTRY + config.getUniqueId());
        log.info("检测到 token 过期(errcode={}), 清除缓存后重试", bizResp.getErrcode());
        return callThirdParty(bizRequest, true);
    }

    if (!bizResp.isSuccess()) {
        throw new RtServerException("调用失败: errcode=" + bizResp.getErrcode()
                + ", errmsg=" + bizResp.getErrmsg());
    }
    return bizResp;
}
```

注意事项：
- **重试仅一次**：`isRetry` 参数防止无限递归。第二次仍失败则直接抛异常。
- **在 Service 层做重试**：Service 层了解业务响应格式，能正确解析 errcode；Strategy 层保持通用性，不解析业务错误码。
- **错误码集合按系统定制**：不同第三方系统的过期/无效错误码不同，每个 Service 实现各自的 `TOKEN_EXPIRED_CODES`。
