# Laji 插件库

Laji 官方插件的发布仓库。客户端插件市场通过下面这个地址读取清单：

```
https://raw.githubusercontent.com/lucongming/plugins/main/pluginhub/index.json
```

对应 `apps/desktop/src/main/plugin-hub.ts` 里的 `DEFAULT_PLUGINHUB_CATALOG_URL`。

## 仓库结构

```
pluginhub/index.json      市场清单（客户端唯一读取的入口）
plugins/<插件目录>/       插件本体：laji.plugin.toml + 源码
```

`index.json` 的一行对应一个插件，`install.path` 指向它在仓库里的目录：

```json
{
  "id": "com.nerve.dsh-whale-pond",
  "name": "小鲸鱼壁纸（DSH）",
  "version": "1.2.0",
  "install": {
    "type": "github",
    "owner": "lucongming",
    "repo": "plugins",
    "ref": "main",
    "path": "plugins/dsh-whale-pond"
  }
}
```

## 素材策略

仓库只放源码，不放构建产物和素材大包：

| 内容 | 位置 | 原因 |
| --- | --- | --- |
| `laji.plugin.toml`、`lib/`、`src/*.py` 等源码 | 仓库内 | 体积小，需可读可 review |
| `dsh-pet/src/assets/`（约 1.5 GB） | Release 附件 | 超过仓库合理体积 |
| `aboutme-pets/characters/`（约 1.3 GB） | Release 附件 | 同上 |
| `laji-pet-bundle-setup.exe`（424 MB）等构建产物 | Release 附件 | 单文件超过 GitHub 100 MB 硬限 |

这两个目录已在 `.gitignore` 里排除。发版时把它们打成 zip 挂到对应 tag 的 Release 上。
在该机制落地前，用客户端随包分发的 `packs/plugins/` 目录获取完整素材。

## 发布流程

1. 在 `plugins/<插件目录>/laji.plugin.toml` 里升 `version`；
2. 同步 `pluginhub/index.json` 里同一 `id` 的 `version` 与 `description`；
3. 更新 `updated_at`；
4. 提交并推 `main`；
5. 素材有变更时，另打 zip 挂 Release。

## 客户端现状

市场列表读取已通，但**远程安装尚未实现**：`apps/desktop/src/main/plugin-store.ts`
的 `install()` 无论 `install.type` 写 `github` 还是 `raw`，都只会回落到本地随包目录，
找不到就报 `install source not available for <id> (v1 supports bundled packs only)`。
清单里的 `type`/`owner`/`repo`/`ref`/`path` 是为随后的下载器预留的字段。

## 开发时指向本仓库

客户端优先用本地文件，覆盖的是清单地址而不是插件目录：

```powershell
$env:NERVE_PLUGINHUB_CATALOG_URL = "https://raw.githubusercontent.com/<owner>/<repo>/main/pluginhub/index.json"
```

本地调试可直接指向文件：`$env:NERVE_PLUGINHUB_CATALOG_URL = "file:///D:/path/to/index.json"`。
