# R 平台二开工程基线

> 静态参考文档（非 SKILL）。由 `re-platform/SKILL.md` 引用，描述跨二开项目固定/可变的工程约定。

## 固定项（跨二开项目保持一致）

| 项 | 约定 |
| --- | --- |
| 启动模块 | `recloud-starter` |
| 主类 | `recloud.webhost.Application`（继承 `BaseApplication`） |
| JDK 版本 | 读取 `config.json` → `java.version`（默认 11）|

## 可变项（以具体项目为准）

| 项 | 说明 |
| --- | --- |
| 工程目录布局 | 不强绑定，按各二开项目实际结构识别 |
| 聚合 POM / 平台父 POM | 会随平台版本演进调整，不在 skill 中写死版本 |
| 核心依赖坐标 | 允许随平台与业务模块调整，使用"能力分类"而非固定清单 |
