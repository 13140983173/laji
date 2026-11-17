# R平台 数据访问

> **定位**：数据访问（查询 / 更新 / Batch）规范与代码模板。
> **前置**：公共规范（Broker 生命周期、异常、SQL）见 [re-platform-common/guide.md](../re-platform-common/guide.md)。事务边界见 [re-platform-transaction/guide.md](../re-platform-transaction/guide.md)。

## R-MCP（编码前必做）

按 [re-platform-mcp](../re-platform-mcp/guide.md) 执行：

- [ ] QueryExpression / SQL / `DynamicEntity` 所用字段已 `get_entity_details` 校验
- [ ] 选项集、引用实体 logicalName 以 MCP 为准，禁止未校验的硬编码

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

**高频踩坑**：`get()` 返回共享上下文 broker，**禁止调用 close()**。

### SQL 表名规则

表名 = 实体名 + "base"

```java
// 正确
SELECT * FROM accountbase WHERE statecode = 0
// 错误
SELECT * FROM account WHERE statecode = 0
```

### PersistBroker 常用方法

| 方法 | 说明 |
| --- | --- |
| `create(entity)` | 新建 |
| `update(entity)` | 修改 |
| `delete(logicalName, id)` | 删除 |
| `retrieve(logicalName, id)` | 获取单条 |
| `retrieveMultiple(...)` | 分页查询 |
| `query(sql, params)` | SQL查询 |
| `count(sql, params)` | 统计 |
| `executeTransaction(lambda)` | 事务包裹 |

### DynamicEntity 取值

```java
entity.getStringFieldValue("name");           // 文本
entity.getIntFieldValue("statecode");         // 整数
entity.getDecimalFieldValue("amount");        // 小数
entity.getLookupFieldValue("ownerid");        // 查找 → EntityReference
entity.getDateTimeFieldValue("createdon");    // 日期 → RtDateTime
```

## PersistBroker / SqlDbClient

### 获取实例

```java
// 推荐：当前用户身份（带权限控制）
var broker = PersistBrokerFactory.get(); // 框架管理生命周期，不要 close

// 创建新实例
var broker = PersistBrokerFactory.newBroker();

// 指定用户身份
var broker = PersistBrokerFactory.newBroker(userIdentity);

// 仅 newBroker() 创建的实例使用后必须关闭
broker.close();

// newBroker() 推荐使用 try-finally
var broker = PersistBrokerFactory.newBroker();
try {
    // 业务逻辑
} finally {
    broker.close();
}
```

### FilteredPersistBroker（权限控制）

| 方法 | 说明 |
|------|------|
| `filteredCreate(entity: DynamicEntity): UUID` | 新建记录 |
| `filteredUpdate(entity: DynamicEntity): void` | 修改记录 |
| `filteredDelete(logicalName: String, id: UUID): void` | 删除记录 |
| `filteredRetrieve(logicalName: String, id: UUID): DynamicEntity` | 获取单条 |
| `filteredRetrieveMultiple(logicalName: String, sql: String, params: Map<String, Object>): List<DynamicEntity>` | 非分页查询 |
| `filteredRetrieveMultiple(logicalName: String, sql: String, params: Map<String, Object>, orderBy: String, pageSize: int, pageIndex: int): List<DynamicEntity>` | 分页查询 |
| `filteredCount(logicalName: String, sql: String, params: Map<String, Object>): int` | 统计数量 |

### PersistBroker（不控制权限）

| 方法 | 说明 |
|------|------|
| `create(entity: DynamicEntity): UUID` | 新建 |
| `update(entity: DynamicEntity): void` | 修改 |
| `delete(logicalName: String, id: UUID): void` | 删除 |
| `retrieve(logicalName: String, id: UUID): DynamicEntity` | 获取单条 |
| `retrieveMultiple(logicalName: String, sql: String, params: Map<String, Object>, orderBy: String, pageSize: int, pageIndex: int): List<DynamicEntity>` | 分页查询 |
| `count(sql: String, params: Map<String, Object>): int` | 统计 |
| `query(sql: String, params: Map<String, Object>): List<DynamicEntity>` | 执行SQL查询 |
| `execute(sql: String, params: Map<String, Object>): int` | 执行SQL更新/删除，返回影响行数 |

**重要**：使用SQL时，**表名 = 实体名 + "base"**

### 示例

```java
var broker = PersistBrokerFactory.get();
// 查询
var sql = """
    SELECT * FROM accountbase
    WHERE statecode = 0 AND name LIKE :name
    ORDER BY createdon DESC
    """;
var params = Map.of("name", "%" + keyword + "%");
var list = broker.retrieveMultiple("account", sql, params, "createdon DESC", 20, 1);

// 统计
var countSql = "SELECT COUNT(*) FROM accountbase WHERE statecode = 0";
int total = broker.count(countSql, Map.of());

// 创建
var entity = new DynamicEntity("account");
entity.setStringFieldValue("name", "新客户");
broker.create(entity);

// 更新
entity.setStringFieldValue("name", "更新后的名称");
broker.update(entity);

// 删除
broker.delete("account", entity.getId());
```

## OrganizationService

### 获取实例

```java
// 当前用户（推荐）
var service = OrganizationServiceFactory.createService();

// 指定用户
var service = OrganizationServiceFactory.createService(userId);

// 管理员（跳过权限校验）
var adminService = OrganizationServiceFactory.createAdminService();
```

### 方法

| 方法 | 说明 |
|------|------|
| `create(entity)` | 创建实体 |
| `retrieve(entityName, entityId, columnSet)` | 查询单条 |
| `retrieveMultiple(query)` | 查询多条 |
| `update(entity)` | 更新实体 |
| `delete(entityName, entityId)` | 删除实体 |
| `assign(target, assignee)` | 分派 |
| `activate(target)` | 激活 |
| `deactivate(target)` | 停用 |
| `invokeFunction(functionName, paramList)` | 调用业务函数 |

**注意**：OrganizationService 操作受权限控制，如不需要权限控制可使用管理员服务或 PersistBroker。

## DynamicEntity 字段操作

### 取值

```java
entity.getStringFieldValue("name");              // 文本 → String
entity.getIntFieldValue("statecode");             // 整数 → Integer
entity.getDecimalFieldValue("amount");            // 小数 → BigDecimal
entity.getBooleanFieldValue("isvip");             // 布尔 → Boolean
entity.getDateTimeFieldValue("createdon");        // 日期时间 → RtDateTime
entity.getPicklistFieldValue("status");           // 选项集 → OptionSetValue
entity.getLookupFieldValue("ownerid");            // 查找 → EntityReference
entity.getMoneyFieldValue("total");              // 金额 → Money/BigDecimal
entity.getPartyListFieldValue("attendees");       // 参与人列表 → List<EntityReference>
```

### 设值

```java
entity.setStringFieldValue("name", "公司A");
entity.setIntFieldValue("statecode", 0);
entity.setDecimalFieldValue("amount", new BigDecimal("1000.00"));
entity.setBooleanFieldValue("isvip", true);
entity.setDateTimeFieldValue("createdon", RtDateTime.now());
entity.setPicklistFieldValue("status", new OptionSetValue(1));
entity.setLookupFieldValue("ownerid", new EntityReference("systemuser", userId));
```

### 常用方法

```java
entity.getId()                              // 获取ID
entity.setId(UUID)                          // 设置ID
entity.getLogicalName()                      // 获取实体名
entity.setLogicalName(String)                // 设置实体名
entity.containsKey("fieldname")             // 判断字段是否存在
entity.getFieldFormattedValue("fieldname")   // 获取格式化值
entity.toEntityReference()                   // 转换为EntityReference
```

### 判空

```java
if (entity.containsKey("name") && entity.getStringFieldValue("name") != null) {
    // 安全取值
}
```

## QueryExpression 查询

### 基础查询

```java
var query = new QueryExpression("account");
query.getColumnSet().addColumns("accountid", "name", "telephone1", "ownerid");

var ec = service.retrieveMultiple(query);
for (var entity : ec.getEntities()) {
    System.out.println(entity.getStringFieldValue("name"));
}
```

### 条件查询

```java
var query = new QueryExpression("account");
query.getColumnSet().addColumns("accountid", "name", "createdon");

// 条件
var criteria = query.getCriteria();
criteria.addCondition("statecode", ConditionOperator.Equal, 0);                    // 等于
criteria.addCondition("name", ConditionOperator.Like, "%科技%");                      // 模糊
criteria.addCondition("createdon", ConditionOperator.GreaterEqual, startDate);      // 大于等于
criteria.addCondition("new_type", ConditionOperator.In, List.of(1, 2, 3));          // IN
criteria.addCondition("description", ConditionOperator.IsNull);                      // 为空
```

#### Equal vs EqualWithCase

- `Equal` 用于普通等值查询；其大小写行为受平台 / 数据库排序规则影响，不要默认等同于原值匹配。
- `EqualWithCase` 用于要求原值、大小写敏感的标识字段，如税号、外部编码、序列号。
- 若需求写明「原值匹配」或大小写敏感，优先使用 `ConditionOperator.EqualWithCase`；字段、操作符行为须在集成测中验证。

### 关联查询

```java
var query = new QueryExpression("account");
query.getColumnSet().addColumns("accountid", "name");

// 关联联系人
var link = new LinkEntity(
    "account",                    // 主实体
    "contact",                    // 关联实体
    "accountid",                  // 主实体字段
    "accountid",                  // 关联实体字段
    JoinOperator.LeftOuter        // 连接类型
);
link.getColumns().addColumns("fullname", "mobilephone");
link.getLinkCriteria().addCondition("statecode", ConditionOperator.Equal, 0);
query.getLinkEntities().add(link);
```

### 分页与排序

```java
// 分页
var paging = new PagingInfo(1, 20);  // 第1页，每页20条
paging.setReturnTotalRecordCount(true);
query.setPageInfo(paging);

// 排序
query.addOrder("createdon", OrderType.Descending);

// 执行
var ec = service.retrieveMultiple(query);
int total = ec.getTotalRecordCount();
```

### 条件操作符

| 操作符 | 说明 |
|--------|------|
| `Equal / NotEqual` | 等于/不等于 |
| `EqualWithCase` | 大小写敏感等值匹配（用于税号/编码等原值匹配字段） |
| `Like / NotLike` | 模糊匹配 |
| `BeginsWith / EndsWith` | 开头/结尾匹配 |
| `GreaterThan / LessThan` | 大于/小于 |
| `GreaterEqual / LessEqual` | 大于等于/小于等于 |
| `In / NotIn` | 在集合中 |
| `IsNull / IsNotNull` | 为空/不为空 |
| `Between` | 区间 |
| `And / Or` | 组合条件 |

## FilterExpression 条件构造器

`FilterExpression` 用于在 `PersistBroker.filteredRetrieveMultiple()` 等方法中构建 SQL 级别的过滤条件，独立于 `QueryExpression`。

### 基础用法

```java
FilterExpression filter = new FilterExpression();

// 设置多条件连接符
filter.setFilterOperator(LogicalOperator.Or);  // Or / And

// 添加条件：字段、运算符、值
filter.addCondition("systemuserid", ConditionOperator.Equal, "a");
filter.addCondition("domainname", ConditionOperator.Equal, "b");

// 嵌套子条件组（可多层）
FilterExpression sub = new FilterExpression();
sub.setFilterOperator(LogicalOperator.And);
sub.addCondition("statecode", ConditionOperator.Equal, 0);
filter.addFilter(sub);
```

### 常用运算符

| 操作符 | 说明 | 示例值 |
|--------|------|--------|
| `Equal / NotEqual` | 等于/不等于 | `"a"`、`0` |
| `Like / NotLike` | 模糊匹配 | `"%科技%"` |
| `In / NotIn` | 在集合中 | `List.of("a","b")` 或 `"a","b","c"` 可变参数 |
| `Between / NotBetween` | 区间（闭区间） | `List.of("a", "b")` 或 `"a","b"` 可变参数；**小值在前** |
| `IsNull / IsNotNull` | 为空/不为空 | `null`（第二个参数填 null 或 `"a"` 均可） |
| `GreaterThan / LessThan` | 大于/小于 | `startDate`、`endDate` |
| `GreaterEqual / LessEqual` | 大于等于/小于等于 | `startDate`、`endDate` |

### In / NotIn

```java
// 可变参数
FilterExpression filter = new FilterExpression();
filter.addCondition("systemuserid", ConditionOperator.In, "a", "b", "c");

// List 方式
List<String> ids = List.of("a", "b", "c");
filter.addCondition("systemuserid", ConditionOperator.In, ids);
```

### Between / NotBetween

```java
// 小值在前（a < b）
FilterExpression filter = new FilterExpression();
filter.addCondition("createdon", ConditionOperator.Between, startDate, endDate);

// List 方式
filter.addCondition("createdon", ConditionOperator.Between, List.of(startDate, endDate));
```

### Null / NotNull

```java
FilterExpression filter = new FilterExpression();
filter.addCondition("emailaddress1", ConditionOperator.IsNull, null);
filter.addCondition("emailaddress1", ConditionOperator.IsNotNull, null);
```

### 与 PersistBroker 配合使用

```java
FilterExpression filter = new FilterExpression();
filter.setFilterOperator(LogicalOperator.And);
filter.addCondition("statecode", ConditionOperator.Equal, 0);
filter.addCondition("name", ConditionOperator.Like, "%科技%");

// 配合 FilteredPersistBroker 使用
var broker = PersistBrokerFactory.get();
var sql = """
    SELECT * FROM accountbase
    WHERE statecode = 0
    ORDER BY createdon DESC
    """;
// filter 作为查询条件传入
var result = broker.filteredRetrieveMultiple("account", sql, filter, null, 20, 1);
```

### 嵌套条件示例

```java
FilterExpression filter = new FilterExpression();
filter.setFilterOperator(LogicalOperator.And);

// 条件组1：状态 = 正常 AND 名称模糊匹配
FilterExpression group1 = new FilterExpression();
group1.setFilterOperator(LogicalOperator.And);
group1.addCondition("statecode", ConditionOperator.Equal, 0);
group1.addCondition("name", ConditionOperator.Like, "%科技%");
filter.addFilter(group1);

// 条件组2：ID IN [...]
FilterExpression group2 = new FilterExpression();
group2.setFilterOperator(LogicalOperator.Or);
group2.addCondition("ownerid", ConditionOperator.In, "user1", "user2");
filter.addFilter(group2);
```

## 事务控制

```java
var broker = PersistBrokerFactory.get();
var result = broker.executeTransaction(() -> {
    // 业务逻辑
    broker.create(entity1);
    broker.create(entity2);
    return entity1.getId();  // 返回值
});
```

## SQL 注意事项

1. **表名**：使用 PersistBroker 时，表名 = 实体名 + "base"
2. **参数**：使用命名参数 `:paramName`
3. **类型**：参数类型需与数据库类型匹配
4. **注入**：禁止字符串拼接SQL，必须使用参数化查询

```java
// 正确
var sql = "SELECT * FROM accountbase WHERE name LIKE :name";
var result = broker.query(sql, Map.of("name", keyword));

// 错误（SQL注入风险）
var sql = "SELECT * FROM accountbase WHERE name LIKE '%" + keyword + "%'";
```

## 代码规则

1. `PersistBrokerFactory.get()` 返回的 broker 不要 `close()`；`newBroker()` 创建的 broker 必须 `close()`
2. 实体属性先 `containsKey()` 再取值
3. SQL表名 = 实体名 + "base"
4. 时间字段使用 `RtDateTime`
5. UUID 使用 `RtUtil.newUUID()` 生成

---

> **公共参考**：服务实例获取、DynamicEntity操作、SQL规范、异常处理、时间处理、UUID、数据类型映射等，详见 [re-platform-common](../re-platform-common/guide.md) |
