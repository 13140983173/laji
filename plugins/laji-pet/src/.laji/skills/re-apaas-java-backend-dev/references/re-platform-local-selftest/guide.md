# 本地开发与自测路径

> **定位**：本地开发启动、联调与快速回归操作指南（适用于 API / Plugin / Job / AsyncJob）。

## 决策速查

### 关键提醒

**首次 mvn 操作前必须执行编译环境预检**：读取 `.claude/config.json` 的 `java.version` / `java.home` → 设置 `JAVA_HOME` → `mvn -version` 确认版本匹配。详见下方「编译环境预检」章节。

### 快速启动

```bash
# IDE 启动
运行 recloud.webhost.Application，参数 --spring.profiles.active=local

# Maven 启动
mvn -pl <startup-module> -am spring-boot:run -Dspring-boot.run.profiles=local
```

### 测试命令

```bash
# 单元测试
mvn -pl <startup-module> -am -Dtest='*Test' test

# 集成测试
mvn -pl <startup-module> -am -Dtest='*IT,*IntegrationTest,*ABTest' test
```

## 0. 目标

把”写完代码”变成可执行闭环：
`本地启动 -> 手动触发 -> 验证数据库/返回值 -> 看日志 -> 回归测试`

## 1. 编译环境预检（首次 mvn 前必做）

> **为什么**：JDK 版本不匹配是 Maven 静默失败的第一大原因（三次实战全部命中）。
> maven-compiler-plugin fork 的 javac 进程失败时，错误输出会被吞掉，`-X` 调试也无法看到具体错误。

### 步骤

1. **读取配置**：从 `.claude/config.json` 的 `java` 节读取 `version` 和 `home`
   - `version`：项目要求的 JDK 主版本号（如 21），未配置时默认 11
   - `home`：JDK 安装绝对路径，优先于系统 `JAVA_HOME`

2. **设置环境**：
   - 若 `home` 非空 → `export JAVA_HOME=<home>; export PATH=$JAVA_HOME/bin:$PATH`
   - 若 `home` 为空但 `version` 非空 → 搜索系统可用 JDK 并提示用户补充 `home` 配置
     - Windows：`ls /d/work/environment/JDK/*/bin/javac.exe`（按实际路径调整）
     - macOS：`/usr/libexec/java_home -V` 或 `ls /Library/Java/JavaVirtualMachines/*/Contents/Home/bin/javac`
   - 若两者均为空 → 跳过，使用系统默认 JDK（风险自担）

3. **验证**：
   ```bash
   mvn -version
   ```
   确认输出的 `Java version` 主版本号与 pom.xml 的 `maven.compiler.source/target`（或 `release`）匹配。

4. **不匹配时的处理**：
   - 停止编译，告知用户具体版本差异
   - 提示补充 `.claude/config.json` 的 `java.home` 值
   - 或提供临时 `export` 命令让用户确认后执行

### Maven 构建规范

- 统一使用 `mvn clean compile` / `mvn clean test`，**不用增量编译**（多模块项目增量编译缺少依赖 class 文件会导致失败）
- 跨模块新增类后，必须先 `mvn install -DskipTests`，再跑依赖模块的测试（仅 `compile` 不够）
- 测试命令的 `-pl` 模块必须与测试文件所在模块一致：
  ```bash
  # 测试在 recloud-starter 中
  mvn clean test -pl recloud-starter -am -Dtest=SomeTest -Dsurefire.failIfNoSpecifiedTests=false
  ```

### Windows 特殊注意

- 直接调 `javac` 编译含中文的源码时必须加 `-encoding UTF-8`
- Maven 编译时 `pom.xml` 的 `project.build.sourceEncoding=UTF-8` 已生效，无需额外参数

## 2. 环境准备清单

以下是必备最小环境（具体参数由项目提供）：

- 配置中心可访问（`recloud.config.url` + `recloud.config.secret-key`）。
- 二开服务配置：`application-*.yml` / `bootstrap.yml` 已配置配置中心参数。
- 启动模块：`<startup-module>`（通常 `recloud-starter`）。

说明：
- 数据库连接、登录鉴权等参数优先由配置中心下发，不要求每个项目在本地重复维护。
- 仅在离线调试或配置中心不可用时，才需要本地覆盖 DB/登录配置。

### 2.1 本地启动前置条件（必须满足才能启动 Application）

`recloud.webhost.Application` 启动需要以下条件，**缺少任一项启动会失败**：

| 条件 | 说明 | 缺失时的表现 |
| --- | --- | --- |
| 配置中心地址 | `recloud.config.url` + `recloud.config.secret-key` | 启动报连接超时或鉴权失败 |
| 数据库连接 | 由配置中心下发或本地 `application-*.yml` 配置 | 启动报数据源初始化失败 |
| 测试租户 | 用于 `AuthorizedContextUtil` 设置上下文 | 接口调用报权限异常 |

**当本地启动条件不满足时**：
- 不要强行尝试启动，会浪费时间。
- 改用**单元测试覆盖全部业务分支**作为等价验证证据。
- 在任务表中标注「本地启动不可行，以单测覆盖作为验证证据」。

推荐把以下变量整理为团队共享文档：

```text
recloud.config.url=
recloud.config.secret-key=
TEST_TENANT=
```

## 3. 本地启动

### 3.1 IDE 启动

- 运行 `recloud.webhost.Application`（或项目约定主类）。
- 启动参数使用本地 profile，例如：`--spring.profiles.active=local`。

### 3.2 Maven 启动（可选）

```bash
mvn -pl <startup-module> -am spring-boot:run -Dspring-boot.run.profiles=local
```

## 4. 测试如何跑

### 4.1 单元测试（阶段 0）

```bash
mvn -pl <startup-module> -am -Dtest='*Test' test
```

### 4.2 集成测试（阶段 1）

```bash
mvn -pl <startup-module> -am -Dtest='*IT,*IntegrationTest,*ABTest' test
```

### 4.3 推荐的”拆分开关”

如果项目需要分离单测/集测，建议约定：
- `-DskipITs=true`：仅跑单测
- `-DskipUTs=true`：仅跑集测

（具体由项目 `pom.xml` 的 surefire/failsafe 配置落地）

## 5. 手动验证路径

### 5.1 API 验证

- 用 Postman / curl 直接调本地接口。
- 至少验证：成功路径 + 参数错误路径 + 权限路径。

curl 示例：

```bash
curl -X POST 'http://localhost:<port>/<api-path>' \
  -H 'Content-Type: application/json' \
  -d '{"id":"<id>"}'
```

### 5.2 Plugin 验证

最小路径：
1. 构造一条能触发插件的 create/update/delete 操作（API 或 SQL 前置+API提交）。
2. 查询副作用实体/字段是否符合预期。
3. 检查日志中是否出现插件执行标记。

建议每个关键 Plugin 都有 1 条集成测试覆盖触发链路。

### 5.3 AsyncJob 验证

- 优先通过业务入口触发（例如审批通过后触发）。
- 本地调试可提供“测试触发入口”：
  - 调用 `ExecuteAsyncJobRequest`
  - 或提供仅测试环境可用的内部 API 包装触发
- 验证任务状态 + 结果副作用 + 错误日志。

### 5.4 Job 验证

- 本地通过调度平台手动触发一次。
- 或在测试代码中直接调用 Job 执行入口（仅测试环境）。

## 6. 日志与排障

### 6.1 日志去哪看

- 开发机默认先看控制台输出。
- 文件日志路径按 `logback-*.xml` / `logging.file.path` 配置。
- Plugin/Job/AsyncJob 关键节点必须打开始/结束日志和关键参数。

### 6.2 最小日志规范

至少包含：
- traceId / 业务主键
- 触发类型（API / Plugin / Job / AsyncJob）
- 输入参数摘要
- 结果状态（success/fail）与异常栈

### 6.3 常见排障顺序

1. 先确认是否真正触发（请求、调度、审批事件）。
2. 再确认上下文（tenant/user）。
3. 再查数据库副作用。
4. 最后看是否被事务回滚或权限拦截。
