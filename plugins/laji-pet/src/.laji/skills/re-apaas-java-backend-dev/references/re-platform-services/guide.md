# R平台 常用服务

> **定位**：平台内置服务（OrganizationService 等）调用规范。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。

## 决策速查

### 获取服务实例

```java
// 推荐：@Autowired
@Autowired
private CacheService cacheService;

// 或：ServiceFactory
var cacheService = ServiceFactory.getService(CacheService.class);
```

### 时间处理铁律

**必须使用 `RtDateTime`，禁止使用 `java.util.Date`**

```java
RtDateTime.now()                           // 当前时间
RtDateTime.now().toString("yyyy-MM-dd")    // 格式化
RtDateTime.now().addDays(7)                // 计算
```

### 异常处理

```java
// 业务可预期错误（客户端可见）
throw new RtClientException("客户不存在");

// 系统错误（不反馈给客户端）
throw new RtServerException("内部错误", e);
```

### UUID 与工具方法

```java
import recloud.one.sdk.utils.RtUtil;

UUID newId = RtUtil.newUUID();            // 生成
UUID id = RtUtil.tryParseUUID(str);       // 解析
RtUtil.isNullOrEmpty(str);                // 判空
RtUtil.stringIsBlank(str);                // 字符串为空
```

## 缓存服务

### CacheService

```java
@Autowired
private CacheService cacheService;
// 或
var cacheService = ServiceFactory.getService(CacheService.class);
```

| 方法 | 说明 |
|------|------|
| `set(key, value)` | 设置缓存（默认过期时间） |
| `set(key, value, time)` | 设置缓存（指定秒数） |
| `set(key, value, time, timeUnit)` | 设置缓存（指定时间单位） |
| `get(key)` | 获取缓存 |
| `remove(key)` | 删除缓存 |
| `exists(key)` | 判断是否存在 |

```java
// 缓存字符串
cacheService.set("user:token:" + userId, token, 3600);

// 缓存对象（需序列化）
String json = jsonProvider.serialize(obj);
cacheService.set("config:" + configId, json, 7200);

// 获取并反序列化
String json = cacheService.get("config:" + configId);
if (json != null) {
    var config = jsonProvider.deserializeToBean(Config.class, json);
}

// 缓存不存在时加载
var value = cacheService.get(key);
if (value == null) {
    value = loadFromDb(key);
    cacheService.set(key, value);
}
```

### RedisService

```java
@Autowired
private RedisService redisService;
```

与 CacheService 方法类似，额外支持：
```java
// 缓存不存在时调用loader函数获取并缓存
var value = redisService.get(key, () -> loadFromDb(key));
```

## 文件存储

### FileStorageService

标准类型路径（当前规范约定）：

```java
import recloud.one.core.storage.FileStorageService;
```

```java
@Autowired
private FileStorageService fileStorageService;
// 或
var fileStorageService = ServiceFactory.getService(FileStorageService.class);
```

| 方法 | 说明 |
|------|------|
| `saveFileByBase64String(dbClient, fileModel, contentBase64)` | Base64保存 |
| `saveFileByStream(dbClient, fileModel, contentStream)` | 流保存 |
| `getFileModelByFileId(dbClient, fileId)` | 根据ID获取文件信息 |
| `getFileModelsByObjectId(dbClient, objectId)` | 根据对象ID获取文件列表 |
| `getFileContentBase64String(dbClient, fileId)` | 获取Base64内容 |
| `getFileContentRaw(dbClient, fileId)` | 获取字节数组 |
| `getDownloadAttachmentUrl(dbClient, attachmentId)` | 获取下载URL（默认2天） |
| `getDownloadAttachmentUrl(dbClient, attachmentId, duration)` | 获取带有效期下载URL |
| `getPreviewAttachmentUrl(dbClient, attachmentId, duration)` | 获取预览URL |
| `deleteFileByFileId(dbClient, fileId)` | 删除文件 |
| `deleteFilesByObjectId(dbClient, objectId)` | 删除对象的所有文件 |
| `isFileTypeAllowed(fileExtension)` | 判断文件类型是否允许 |

```java
// 保存文件
var fileModel = new FileModel();
fileModel.setObjectId(accountId);
fileModel.setObjectType("account");
fileModel.setFileName("contract.pdf");
fileModel.setFileExtension("pdf");
fileModel.setFileSize(fileSize);

String fileId = fileStorageService.saveFileByBase64String(
    broker, fileModel, base64Content);

// 下载文件
var url = fileStorageService.getDownloadAttachmentUrl(broker, fileId);
// url 可用于前端下载

// 删除文件
fileStorageService.deleteFileByFileId(broker, fileId);
```

## 消息队列

### MessageQueueService

```java
@Autowired
private MessageQueueService messageQueueService;
// 或
var messageQueueService = ServiceFactory.getService(MessageQueueService.class);
```

**定义消息内容**：
```java
public class OrderMessageContent extends BaseMessageContent {
    private UUID orderId;
    private String orderNo;
    private BigDecimal amount;
    // getter/setter
}
```

**发送消息**：
```java
var content = new OrderMessageContent();
content.setOrderId(orderId);
content.setOrderNo(orderNo);
content.setAmount(amount);

var message = new QueuedMessage();
message.setTopic("order.completed");        // topic
message.setMessageContent(content);
// message.setPartition(0);                 // 分区（与key二选一）
// message.setKey(orderId.toString());      // 消息key

messageQueueService.send(message);
```

**QueuedMessage 属性**：
| 属性 | 说明 |
|------|------|
| `topic` | 消息主题 |
| `partition` | 分区号（与key二选一） |
| `key` | 消息key（与partition二选一） |
| `messageContent` | 消息内容（继承BaseMessageContent） |

## 分布式锁

### DistributedLockService

```java
@Autowired
private DistributedLockService lockService;
// 或
var lockService = ServiceFactory.getService(DistributedLockService.class);
```

```java
import java.util.concurrent.TimeUnit;

// 尝试加锁（waitTime=-1无等待，leaseTime=-1用默认值）
var result = lockService.tryLock("order:process:" + orderId,
    -1,           // waitTime
    30,           // leaseTime
    TimeUnit.SECONDS,
    () -> {
        // 业务逻辑
        return processOrder(orderId);
    });

// 一直等待锁
var result = lockService.lock("order:process:" + orderId,
    30,
    TimeUnit.SECONDS,
    () -> {
        return processOrder(orderId);
    });

// 获取结果
if (result.isSuccess()) {
    var orderResult = result.getResult();
} else {
    // 获取锁失败
}
```

## 多语言

### LangHelper

```java
@Autowired
private LangHelper langHelper;
// 或
var langHelper = ServiceFactory.getService(LangHelper.class);
```

**选项集**：
```java
// 获取所有选项
var options = langHelper.getOptions("account", "new_type");
// options: [{value: 1, label: "客户"}, {value: 2, label: "供应商"}]

// 获取值对应的标签
var label = langHelper.getLabel("account", "new_type", 1);
// label: "客户"

// 获取选项显示名称
var displayName = langHelper.getPicklistDisplayName("account", "new_type", statusValue);
```

**多语言文本**：
```java
// 获取多语言文本
var text = langHelper.get("message.order.success");
var text = langHelper.get("message.order.success", "Default message");  // 带默认值

// 指定语言
var textZh = langHelper.get("zh-CN", "message.order.success");
var textEn = langHelper.get("en-US", "message.order.success");

// 获取业务数据本地化标签
var localizedLabel = langHelper.getBusinessDataLocalizedLabel(
    "account", accountId, "new_industry", "zh-CN");
```

## JSON 处理

### JsonProvider

```java
@Autowired
private JsonProvider jsonProvider;
// 或
var jsonProvider = ServiceFactory.getService(JsonProvider.class);
```

| 方法 | 说明 |
|------|------|
| `serialize(obj)` | 序列化对象为JSON字符串 |
| `deserialize(targetType, str)` | 反序列化（Class） |
| `deserializeObj(classes, object)` | 反序列化对象 |
| `deserializeToBean(targetType, str)` | 反序列化为Bean（TypeSafe） |
| `deserializeToBean(valueTypeRef, str)` | 反序列化（TypeReference） |

```java
// 序列化
String json = jsonProvider.serialize(obj);

// 反序列化
MyClass obj = jsonProvider.deserialize(MyClass.class, json);

// TypeReference方式（复杂泛型）
var typeRef = new TypeReference<List<Order>>() {};
List<Order> orders = jsonProvider.deserializeToBean(typeRef, json);
```

## 时间处理

**必须使用 `RtDateTime`，禁止使用 `java.util.Date`**

### 创建时间

```java
RtDateTime.now()                                   // 当前时间
RtDateTime.now(timeZone)                           // 指定时区
RtDateTime.of(timeMillis)                           // 从时间戳
RtDateTime.of(date)                                // 从Date转换
RtDateTime.of(dateStr, "yyyy-MM-dd")               // 从字符串
RtDateTime.of(dateStr, "yyyy-MM-dd HH:mm:ss")      // 带时间
```

### 格式化

```java
RtDateTime.now().toString("yyyy-MM-dd")
RtDateTime.now().toString("yyyy-MM-dd HH:mm:ss")
RtDateTime.now().toString("yyyy年MM月dd日")
```

### 计算

```java
RtDateTime.now().addDays(1)                        // 加1天
RtDateTime.now().addDays(-7)                       // 减7天
RtDateTime.now().addMonths(1)                      // 加1月
RtDateTime.now().addYears(-1)                      // 减1年
```

### 比较

```java
var date1 = RtDateTime.of("2024-01-01", "yyyy-MM-dd");
var date2 = RtDateTime.of("2024-12-31", "yyyy-MM-dd");

date1.isBefore(date2)                              // date1 < date2
date1.isAfter(date2)                               // date1 > date2
date1.equals(date2)                               // date1 == date2
```

### SQL 中的使用

```java
var sql = """
    SELECT * FROM accountbase
    WHERE createdon >= :startDate AND createdon < :endDate
    """;
var params = Map.of(
    "startDate", RtDateTime.now().addDays(-30).toString("yyyy-MM-dd"),
    "endDate", RtDateTime.now().toString("yyyy-MM-dd")
);
```

## 异常处理

```java
// 业务异常 - 反馈给客户端（WARN级别）
throw new RtClientException("客户不存在");
throw new RtClientException("CUSTOMER_NOT_FOUND", "客户不存在");
throw new RtClientException("错误信息 {}", "参数");  // 支持占位符

// 服务器异常 - 不反馈给客户端（ERROR级别）
throw new RtServerException("内部错误");
throw new RtServerException("操作失败", e);
throw new RtServerException(e);
```

### 获取错误码

```java
try {
    // 业务逻辑
} catch (RtClientException e) {
    String errorCode = e.getErrorCode();
    String message = e.getMessage();
    // 处理
}
```

## UUID 生成

```java
import recloud.one.sdk.utils.RtUtil;

// 生成新UUID
UUID newId = RtUtil.newUUID();

// 从字符串解析
UUID id = RtUtil.tryParseUUID(stringValue);
```

## 常用工具

### RtUtil

```java
RtUtil.isNullOrEmpty(str)          // 判空
RtUtil.stringIsBlank(str)          // 字符串为空
RtUtil.stringIsNotBlank(str)       // 字符串非空
RtUtil.newUUID()                   // 生成UUID
RtUtil.tryParseUUID(str)          // 解析UUID
```

---

> **公共参考**：服务实例获取、DynamicEntity操作、SQL规范、异常处理、时间处理、UUID、数据类型映射等，详见 [re-platform-common](../re-platform-common/guide.md) |