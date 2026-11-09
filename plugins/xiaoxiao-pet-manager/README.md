# 桌宠管家（xiaoxiao-pet-manager）

工作台右缘插件托盘里多一颗 ✨ 入口，点开就是一块桌宠管理面板：
浏览全部桌宠角色（预览图 / 动画数 / 来源包）、切换当前角色、给每个角色单独改
**小名** 与 **专属人设**，常用外观项（大小 / 不透明度）直接拖滑条。

## 数据来源（只读 + 白名单写）

| 内容 | 位置 | 权限 |
|---|---|---|
| 桌宠配置 | `%APPDATA%\dsh-pet-standalone-laji\config.json` | 读 + 白名单键写 |
| 本机角色 | `%APPDATA%\dsh-pet-standalone-laji\characters\` | 只读（预览帧） |
| 插件自带角色 | `packs/plugins/*/characters\`（aboutme-pets 等） | 只读（预览帧） |

写操作只允许：`character`（当前角色）、`character_aliases`（小名）、
`pet_persona_overrides`（专属人设）、`spawn_scale` / `pet_opacity`（外观数值）。
其余配置请用「打开配置文件」直接改 config.json，桌宠的配置 watcher 会自动热应用。

## 生效时机

- **小名 / 人设 / 外观数值**：桌宠运行中由配置 watcher 去抖后热应用，保存即生效。
- **当前角色**：桌宠的启动项（`config.character`），切换后**下次启动登场**；
  运行中的桌宠请重启（托盘退出 → 重新拉起）。

## 与上游的关系

UI 参照 [yshuang722-spec/xiaoxiao-zhuochong](https://github.com/yshuang722-spec/xiaoxiao-zhuochong)
（MIT）的控制页视觉语言：暖米色侧边栏、角色卡片网格、奶油色卡片、圆角开关。
只借鉴版式与配色，未复制其代码，也未打包其角色素材 —— 详见 `NOTICE.md`。

## 测试

```bash
node --test test/
```
