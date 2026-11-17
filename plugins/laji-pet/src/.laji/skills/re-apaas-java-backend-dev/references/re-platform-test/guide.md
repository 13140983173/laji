# R 平台测试（分阶段双轨）

> **定位**：分阶段双轨测试策略（单元测试 + 集成测试）与代码模板。
> **前置**：执行命令、本地启动与排障见 [re-platform-local-selftest/guide.md](../re-platform-local-selftest/guide.md)。
> Plugin 拦截类需求：**规则下沉可测类 + Service 触发集成测**，见本文「Plugin 集成测专章」。

## 决策速查

### 双轨策略

| 轨道 | 内容 | 门槛 |
| --- | --- | --- |
| **B：单元测试** | JUnit5 + Mockito | **必须有**；不依赖PG/租户 |
| **A：集成测试** | @SpringBootTest + 测试租户 | 有最小测试租户后补充 |

### Mock 类型速查（高频）

| 类型 | 包名 |
| --- | --- |
| `PersistBroker` | `recloud.one.sdk.data` |
| `DynamicEntity` | `recloud.one.sdk.data.model` |
| `DataTable` / `DataRow` | `recloud.one.sdk.data.model` |
| `InvalidPluginExecutionException` | `recloud.one.sdk.exception` | legacy；新代码断言 `RtClientException` / `DuplicateRecordException` |

### Plugin 集成测关键点

- **造数**：预置「已存在」记录用 `broker.execute` INSERT `{entity}base`（绕过Plugin）
- **触发**：验证拦截用 `OrganizationService.create/update`（走完整Plugin链）
- **查重**：用 `broker.query` + `LIMIT 1`，慎用 `broker.count`（命名参数缓存问题）

### Maven 命令

```bash
# 仅单元测试
mvn -pl <startup-module> -am test -Dtest=<CheckerTest>

# 集成测试（本地有库）
mvn -pl <startup-module> -am test -Dtest=<XxxIT>

# CI跳过集成
export R_TEST_SKIP_INTEGRATION=true
```

### 落地清单（必做）

- [ ] `spring-boot-starter-test` 已加入启动模块
- [ ] `base/TestUtil` 已填**真实**租户与用户
- [ ] 每个 PreCreate 校验 Plugin：`*Checker` 单测 + IT
- [ ] 查重SQL用 `query` + `LIMIT 1`
- [ ] 每个 bug fix 至少1条回归单测

## 总体策略

原则：**能用单测覆盖的规则不要只靠集成测**；每个 PreCreate 校验类 Plugin 建议 1 个 Checker 单测类 + 1 个 IT（可选 `@Tag("integration")`）。单元测试覆盖 `*Checker` / Server / Command 纯逻辑；集成测试用 `@SpringBootTest` + 测试租户 + 完整 Plugin/Service 链。

## 目录约束

测试用例统一放在**启动模块**的 `src/test/java`（如 `recloud-starter`），不要分散到 `recloud-salesone-*` 等业务 jar。

```text
<startup-module>/src/test/java/
  ├─ base/
  │   ├─ SpringBootBaseTest.java
  │   ├─ TestUser.java
  │   └─ TestUtil.java
  ├─ <业务包>/*Test.java          # 单元测试
  ├─ <业务包>/*IT.java            # 集成测试（建议 @Tag("integration")）
  └─ <业务包>/*TestDataHelper.java # SQL 造数等（按需）
```

启动模块 `pom.xml` 需声明：

```xml
<dependency>
  <groupId>org.springframework.boot</groupId>
  <artifactId>spring-boot-starter-test</artifactId>
  <scope>test</scope>
</dependency>
```

## 项目测试环境登记（必填，勿用占位符）

在仓库或 `doc/` 维护本表，Agent 不得臆造 `administrator` 等通用账号。

| 项 | 示例（salesone/pmidev） | 说明 |
| --- | --- | --- |
| 默认租户 | `pmidev` | 与 `application-*.yml` / `db.setting` 一致 |
| 管理员 `domainname` | `pmiadmin` | `SELECT domainname FROM systemuserbase WHERE isdisabled=false` 核对 |
| 库连接 | `db.setting` 或配置中心 | 集成测前确认可连 |

环境变量（覆盖默认值）：

| 变量 | 作用 |
| --- | --- |
| `R_TEST_TENANT` | 测试租户 |
| `R_TEST_USER` | 测试用户 `domainname` |
| `R_TEST_SKIP_INTEGRATION=true` | CI 无库时跳过集成测 |

## 阶段 0：单元测试（立即执行）

- 建立 JUnit5 + Mockito。
- **PreCreate/校验类 Plugin**：业务规则抽到 `XxxChecker` / `XxxValidator`（无 Spring），Plugin 只委托。
- Mock `PersistBroker` 时用 **`DataTable` / `DataRow`**（见下文 Mock 速查）。

### 可单测逻辑下沉（Plugin 推荐）

```text
AccountDuplicateCheckPlugin  → 委托 → AccountDuplicateChecker（单测主体）
```

单测覆盖：分支、trim、空名称跳过、异常文案、`broker.query` 参数。

### 单元测试模板

```java
@ExtendWith(MockitoExtension.class)
class AccountDuplicateCheckerTest {

    @Mock
    private PersistBroker broker;

    @Test
    void checkNoDuplicate_throwsWhenQueryNotEmpty() throws SQLException {
        var rows = new DataTable();
        rows.add(new DataRow());
        when(broker.query(anyString(), eq(Map.of("name", "A", "taxno", "1")))).thenReturn(rows);

        assertThrows(RtClientException.class,
                () -> AccountDuplicateChecker.checkNoDuplicate(broker, "A", "1"));
    }
}
```

## 阶段 1：集成测试

- `@SpringBootTest(classes = Application.class)` 继承 `SpringBootBaseTest`。
- 至少 1 条写入 + 1 条权限/拦截（按模块）。
- 集成类建议 `@Tag("integration")` + `@EnabledIf("base.TestUtil#isIntegrationEnabled")`（见 `TestUtil` 模板）。

### 标准基类（与 SDK 对齐）

> `TenantConfiguration` 方法名为 **`getTenantCofiguration`**（SDK 拼写），升级后需重新核对。

`base/SpringBootBaseTest.java`：

```java
@BeforeEach
void setUp() {
    AuthorizedContextUtil.setAnonymousUserInfo4UnitTest(TestUtil.getTestTenant(), TestUser.Administrator);
    tenantConfiguration.getTenantCofiguration(TestUtil.getTestTenant());
}
```

`base/TestUser.java`：

```java
public final class TestUser {
    public static final String Administrator =
            System.getenv().getOrDefault("R_TEST_USER", "<project-admin-domainname>");
}
```

`base/TestUtil.java`：

```java
public final class TestUtil {
    public static final String DEFAULT_TEST_TENANT = "<project-tenant>";

    public static String getTestTenant() {
        var env = System.getenv("R_TEST_TENANT");
        return (env != null && !env.isBlank()) ? env.trim() : DEFAULT_TEST_TENANT;
    }

    public static boolean isIntegrationEnabled() {
        return !"true".equalsIgnoreCase(System.getenv("R_TEST_SKIP_INTEGRATION"));
    }

    public static void runOnContext(String userCode, CheckedNoReturnFunction fn) throws Exception {
        AuthorizedContextUtil.setTemporaryPrincipal(userCode, getTestTenant());
        try { fn.invoke(); } finally { AuthorizedContextUtil.clearTemporaryPrincipal(); }
    }
}
```

### 通用集成模板（无 Plugin 拦截）

```java
@Test
void create_smoke() throws Exception {
    TestUtil.runOnContext(TestUser.Administrator, () -> {
        var service = OrganizationServiceFactory.createService();
        var entity = new DynamicEntity("account");
        entity.setStringFieldValue("name", "IT-" + RtUtil.newUUID());
        UUID id = service.create(entity);
        try {
            Assertions.assertNotNull(id);
        } finally {
            service.delete(EntityNameConstants.ACCOUNT, id);
        }
    });
}
```

## Plugin 集成测专章

### 造数：不要假设 create 绕过 Plugin

| 方式 | 是否走 PreCreate Plugin | 用途 |
| --- | --- | --- |
| `OrganizationService.create` | ✅ 走 | **触发拦截**、验证文案 |
| `PersistBroker.create` / `get().create` | ✅ 走（实测） | 不宜作「无 Plugin 造数」 |
| `createAdminService().create` | ✅ 走（实测） | 同上 |
| **`broker.execute` INSERT `{entity}base`** | ❌ 不走 | **预置已存在数据** |

造数 SQL 注意：

- 表名 `{logicalName}base`（如 `accountbase`）。
- 补全 `statecode`、`ownerid`、`createdby/modifiedby`、`createdon/modifiedon` 等必填列。
- `ownerid` 用 `SELECT systemuserid FROM systemuserbase WHERE domainname = :code` 解析。
- `finally` 中 `broker.delete` 或清理 SQL。

### 触发与断言

```java
// 1. SQL 造数（绕过 Plugin）
UUID existingId = AccountTestDataHelper.insertAccount(broker, name, taxNo);

// 2. 普通 Service 创建 → 走完整 Plugin 链
var ex = assertThrows(RtClientException.class,
        () -> OrganizationServiceFactory.createService().create(duplicate));

assertTrue(ex.getMessage().contains("已存在"));
// 若业务有 formatXxxMessage(name)，可与精确文案 equals
```

- 断言 **`RtClientException`**（业务异常，客户端可见类型）。
- 不要断言 Plugin 内部未包装类型。
- 测试数据名称加 **UUID 后缀**，避免污染环境。

### 查重类 Plugin 集成测覆盖

按多字段唯一性拦截时，至少覆盖：

- `PreCreate`：名称 + 税号完全匹配时抛 `RtClientException` / `DuplicateRecordException`，文案包含重复记录名称和税号。
- 拦截后未落库：异常后查询新记录不存在。
- `PreUpdate`：只改名称、只改税号、只改其他字段时都能正确合并当前记录再查重。
- 自排除：保存原值或只改非查重字段不应命中自己。
- 可用状态过滤：已删除 / 停用记录不应参与重复判断（以项目确认的 `statecode` / 删除标识为准）。
- 原值匹配：`EqualWithCase`、大小写、空格 / trim 行为与需求一致，并有 IT 证据。

### 清理策略

- 触发 Plugin 用 `OrganizationService.create/update`，不要用 SQL 触发。
- 预置「已存在」记录可用 SQL 直写；清理隔离测试数据可用 SQL delete，前提是测试数据有 UUID 后缀且无预期关联记录。
- 若造数产生关联副作用，优先用平台 delete 或项目 helper 清理。
- `finally` 中清理所有可能创建的 ID；异常拦截路径也要查询确认未落库。

### PersistBroker：查重用 `query`，慎用 `count`

同一 SQL 字符串多次 `broker.count(..., 不同 Map)` 时，**命名参数可能缓存导致第二次绑定错误**（实测 `taxno` 误判重复）。

推荐：

```java
// ✅ 存在性判断
var rows = broker.query("""
    SELECT accountid FROM accountbase
    WHERE statecode = 0 AND name = :name AND COALESCE(new_taxno, '') = :taxno
    LIMIT 1
    """, Map.of("name", name, "taxno", taxNo));
if (!rows.isEmpty()) { throw new RtClientException(4001, getLangHelper().get("xxx_duplicated", "记录已存在")); }

// ⚠️ 避免：同一 SQL 常量连续多次 broker.count
```

## executeTransaction mock 模式

Command / Job 中使用 `broker.executeTransaction(() -> { ... })` 时，单元测试需要 mock 该方法直接执行 lambda：

```java
// Mock broker 的 executeTransaction：直接执行传入的 lambda
when(broker.executeTransaction(any(Runnable.class))).thenAnswer(invocation -> {
    Runnable lambda = invocation.getArgument(0);
    lambda.run();
    return null;
});
```

这样事务内的所有 `broker.retrieve()`、`broker.create()`、`broker.update()` 调用都会被同一个 mock broker 处理，无需额外配置。

**适用场景**：LeadConvertCommand 等多实体事务类 Command、Job 中使用 executeTransaction 的逻辑。

## Mock / 类型速查

| 类型 | 包名 |
| --- | --- |
| `PersistBrokerFactory` | `recloud.one.sdk.data.broker` |
| `PersistBroker` | `recloud.one.sdk.data` |
| `DynamicEntity` | `recloud.one.sdk.data.model` |
| `DataTable` / `DataRow` | `recloud.one.sdk.data.model` |
| `InvalidPluginExecutionException` | `recloud.one.sdk.exception` | legacy CRM 用法，新代码 Plugin 异常用 `RtClientException` / `DuplicateRecordException` |
| `OrganizationServiceFactory` | `recloud.one.core` |
| `RtUtil` | `recloud.one.sdk.utils` |

`broker.query` 返回 **`DataTable`**，单测 `thenReturn(new DataTable())` 或带 `DataRow` 的非空表。

## 环境与 Maven 命令

### 多模块项目测试命令模板

测试文件统一放在启动模块（如 `recloud-starter`），但业务代码在 `recloud-salesone-*` 子模块中。以下为标准命令模板：

```bash
# 跑指定单元测试（-am 同时构建依赖模块，否则找不到业务类）
mvn clean test -pl recloud-starter -am \
  -Dtest=<package>.<TestClassName> \
  -Dsurefire.failIfNoSpecifiedTests=false

# 跑指定包下所有测试
mvn clean test -pl recloud-starter -am \
  -Dtest="<package>.*Test" \
  -Dsurefire.failIfNoSpecifiedTests=false

# 集成测试（本地有测试库）
mvn clean test -pl recloud-starter -am \
  -Dtest=<package>.<XxxIT> \
  -Dsurefire.failIfNoSpecifiedTests=false

# CI 跳过集成
export R_TEST_SKIP_INTEGRATION=true
```

### 关键参数说明

| 参数 | 作用 | 为什么必须 |
| --- | --- | --- |
| `-pl recloud-starter` | 指定测试运行模块 | 测试类在 starter 中，不在业务 jar 中 |
| `-am` | 同时构建依赖模块（Also Make） | 不加则 starter 编译测试时找不到业务模块的类 |
| `-Dsurefire.failIfNoSpecifiedTests=false` | 无匹配测试时不失败 | `-am` 会让所有 reactor 模块执行 surefire，业务模块无匹配测试会报错 |
| `clean` | 全量重新编译 | 增量编译可能缺少新增类的 class 文件 |

### 常见错误与对策

| 现象 | 原因 | 解决 |
| --- | --- | --- |
| `package does not exist` / `cannot find symbol` | 缺少 `-am` | 加 `-am` 同时构建依赖模块 |
| 指定 `-Dtest=XxxTest` 后其他模块报 No tests were executed | `-Dtest` 会传递给所有 reactor 模块 | 加 `-Dsurefire.failIfNoSpecifiedTests=false` |
| 全量测试中既有测试失败 | 与本次需求无关的既有问题 | 单独跑本次需求的测试类确认通过；在任务表中标注既有失败清单 |

## 阶段 2

- Plugin/AsyncJob/Workflow 关键路径扩展 IT。
- CI：PR 默认单测；夜间或 manual 跑 `@Tag("integration")`。

## 覆盖策略

| 层 | 优先级 | 建议 |
| --- | --- | --- |
| `*Checker` / Server 纯逻辑 | 高 | Mockito 单测 |
| Plugin PreCreate 拦截 | 高 | Checker 单测 + 1～2 条 IT |
| Controller | 中 | 关键 API 集成 |
| 工具类 | 中 | 单测 |

## 落地清单

- [ ] `spring-boot-starter-test` 已加入启动模块
- [ ] `base/TestUtil` 已填**真实**租户与用户（非占位符）
- [ ] 每个 PreCreate 校验 Plugin：`*Checker` 单测 +（可选）`*IT`
- [ ] Plugin IT 造数用 SQL 或项目认可的绕过方式，**不用**「broker.create 绕过」假设
- [ ] 查重/存在性 SQL 用 `query` + `LIMIT 1`
- [ ] CI 配置 `R_TEST_SKIP_INTEGRATION` 或 surefire excludeGroups
- [ ] 每个 bug fix 至少 1 条回归单测

## 与其它文档联动

| 文档 | 关系 |
| --- | --- |
| `re-platform-plugin` | 集成测造数、异常类型、Pre/Post 行为 |
| `re-platform-data` | `{entity}base`、命名参数、`query` |
| 验证证据与 Maven 命令 | `re-platform-local-selftest/guide.md` |
| `re-platform-local-selftest` | 启动、联调、日志 |
