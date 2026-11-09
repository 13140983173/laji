# NOTICE — 桌宠素材扩展包（aboutme-pets）

## 来源

素材取自 **https://github.com/hunmer/aboutme-pets**（Aboutme 宠物商店目录，main 分支），
四个动作包：`pets/dsh1`（166）、`pets/gpt`（193）、`pets/claude`（166）、`pets/gemini`（100）。
上游素材归属 **https://github.com/PC2005-cloud/dsh-pet**（dsh1 固定提交
b78e3fcf92ac78cee569aed7cc27eeb2a8d51757；其余批次为该角色的 AI 生成衍生批次的二次转换）。

## 许可

- 上游**代码** MIT（见上游 LICENSE-*.txt），**不覆盖素材限制**。
- 上游**素材**：**禁止商用**；二创在公开渠道须署名上述上游仓库。
  本包的 WebM 是精灵图的格式转换（派生物），**不授予额外授权，沿用上述限制**。
- 只接入了 dsh1/gpt/claude/gemini 四包；`pets/dsh`（101 动作）与 dsh-pet 插件内置的
  106 段 WebM 同源，未重复引入。

## 格式转换记录

- 上游形态：透明 WebP 精灵图，640×360 / 8 列网格 / 12fps / 每动作 180 或 360 帧。
- 本包形态：VP9 alpha 透明 WebM（yuva420p，crf 20，realtime 档），画布与帧率不变，
  逐帧从网格裁出直通编码，无缩放无重采样——脚底锚位（y=330）与上游一致。
- 分类映射：pet 播放器六分类 ← aboutme 九分类（待机/名称含"待机呼吸发呆瞌睡"等 → idle，
  点击回应/回应 → click，拖拽 → drag，移动 → move，其余全部 → random）。
- 转换脚本：`tools/convert.py`（下载器 `tools/download.py`，ghfast.top 加速、断点续传；
  两者可复现本包全部产物）。
