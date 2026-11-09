# Laji 插件库

Laji 官方插件的发布仓库。客户端插件市场通过下面这个地址读取清单：

```
https://raw.githubusercontent.com/13140983173/laji/main/pluginhub/index.json
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
    "owner": "13140983173",
    "repo": "laji",
    "ref": "main",
    "path": "plugins/dsh-whale-pond"
  }
}
```

## 素材策略

素材随插件一起入库。客户端的远程安装只认仓库归档与逐文件下载，没有 Release 附件下载能力，
素材放在 Release 上等于装不出完整插件：

| 内容 | 位置 | 说明 |
| --- | --- | --- |
| `laji.plugin.toml`、`lib/`、`src/*.py` 等源码 | 仓库内 | 体积小，可读可 review |
| `aboutme-pets/characters/`（约 1.3 GB / 1234 文件） | 仓库内 | 最大单文件 6.7 MB，低于 GitHub 100 MB 硬限 |
| `dsh-pet/src/assets/`（约 1.5 GB / 25681 文件） | 仓库内 | 最大单文件 2.1 MB |
| 安装包等构建产物（如 424 MB 的 `laji-pet-bundle-setup.exe`） | Release 附件 | 单文件超过 GitHub 100 MB 硬限，不能入库 |

仓库根 `.gitignore` 已放开这两个素材目录。`plugins/dsh-pet/src/.gitignore` 是上游自带的规则
（忽略 `assets/characters/*/frameseq/` 等派生物），入库时用 `git add -f` 覆盖，不改上游文件。

素材体积使仓库明显超过 GitHub 的 1 GB 建议值。首次克隆会比较慢，客户端走归档下载不受影响。

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
