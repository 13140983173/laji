// 桌宠管家 —— 纯逻辑核心（无 HTTP、无进程依赖，测试直接 import）。
//
// 职责：发现角色（桌宠热加载目录 + 兄弟插件包）、读桌宠 config.json、
// 把面板的白名单写操作（切换角色 / 小名 / 人设 / 尺寸）落成合法的 config.json。
// 路径安全与字段清洗都在这一层，host.mjs 只做 HTTP 包装。

import * as fs from "node:fs";
import * as path from "node:path";

import { CATALOG, CATALOG_FIELDS, FIELD_BY_KEY as CATALOG_FIELD_BY_KEY, FEATURE_IDS, SLOT_KEYS } from "./catalog.mjs";

export { CATALOG, CATALOG_FIELDS, SLOT_KEYS };

/** 桌宠家目录名前缀（config.py 变体规则：dsh-pet-standalone[-<name>]）。 */
const PET_HOME_PREFIX = "dsh-pet-standalone";
/** Laji 版优先目录名。 */
export const LAJI_PET_HOME = "dsh-pet-standalone-laji";

/** 面板允许写的数值键与边界（pet_opacity 与桌宠 config.py 一致：百分比 10-100）。 */
export const NUMERIC_KEYS = {
  spawn_scale: { min: 0.1, max: 4.0, def: 0.72 },
  pet_opacity: { min: 10, max: 100, def: 100 },
};

/**
 * 从桌宠「小口袋」（modern_settings_dialog）搬进面板的精简设置表。
 *
 * 收录标准：纯 config.json 键 + 在 config.py 的 reload 白名单内 + 改完由
 * QFileSystemWatcher 热生效。动作型（检查更新 / 试听 / 生成宠物 / 清数据）、
 * 要写注册表或素材文件的（autostart / click_sound_pack / 人设同步）、
 * 网络密钥与 AI 服务、以及重启级开关（feature_activation / 跨屏 / 直播捕获）
 * 一律不收。每项的取值口径都对齐 config.py 的 _normalize_pet_settings：
 *   • scale / spawn_scale 0.1–4.0 默认 0.72；pet_opacity 10–100 百分比；
 *   • playback_speed 0.1–8.0；bubble_text_scale 50–300；
 *   • *_sound_volume 落盘 0–1 浮点，UI 用 0–100（uiScale 换算）；
 *   • quiet_minutes_default 只认 15/30/60/120；throw_strength 四档枚举。
 * 字段是唯一真值：GET /api/state 把它发给前端渲染，POST /api/settings 按它校验。
 */
export const SETTINGS_SCHEMA = [
  { group: "显示", fields: [
    { key: "scale", label: "桌宠大小", type: "select", def: 0.72,
      options: [[0.5, "小"], [0.72, "标准"], [0.85, "大"], [1, "超大"]] },
    { key: "pet_opacity", label: "不透明度", type: "range", def: 100, min: 10, max: 100, step: 1, unit: "%", integer: true, percent: true },
    { key: "bubble_text_scale", label: "气泡文字", type: "range", def: 100, min: 50, max: 300, step: 10, unit: "%", integer: true },
    { key: "on_top", label: "窗口置顶", type: "toggle", def: true },
    { key: "auto_hide_fullscreen", label: "全屏时隐藏", type: "toggle", def: true },
  ] },
  { group: "动作与移动", fields: [
    { key: "playback_speed", label: "播放速率", type: "select", def: 1,
      options: [[0.5, "0.5×"], [0.75, "0.75×"], [1, "1×"], [1.25, "1.25×"], [1.5, "1.5×"], [2, "2×"], [3, "3×"], [4, "4×"]] },
    { key: "idle_low_fps_enabled", label: "闲置降帧", type: "toggle", def: false },
    { key: "no_move", label: "固定在原地", type: "toggle", def: false },
    { key: "edge_probe_enabled", label: "边缘探头", type: "toggle", def: false },
  ] },
  { group: "拖拽与弹射", fields: [
    { key: "drag_physics", label: "拖动物理", type: "toggle", def: false },
    { key: "drop_gravity", label: "放手下落", type: "toggle", def: false },
    { key: "slingshot_enabled", label: "弹弓弹射", type: "toggle", def: true },
    { key: "throw_strength", label: "甩出力度", type: "select", def: "standard",
      options: [["gentle", "轻"], ["standard", "标准"], ["strong", "用力"], ["crazy", "狂野"]] },
    { key: "lock_position", label: "锁定位置", type: "toggle", def: false },
  ] },
  { group: "小肥鱼", fields: [
    { key: "spawn_inherit_size", label: "继承桌宠大小", type: "toggle", def: true },
    { key: "spawn_scale", label: "小肥鱼大小", type: "range", def: 0.72, min: 0.1, max: 4, step: 0.05 },
  ] },
  { group: "声音与自言自语", fields: [
    { key: "click_sound_enabled", label: "点击音效", type: "toggle", def: true },
    { key: "click_sound_volume", label: "点击音量", type: "range", def: 0.7, min: 0, max: 100, step: 1, unit: "%", uiScale: 100 },
    { key: "self_talk_enabled", label: "自言自语", type: "toggle", def: false },
  ] },
  { group: "提醒与免打扰", fields: [
    { key: "todo_reminder_enabled", label: "待办提醒", type: "toggle", def: true },
    { key: "todo_reminder_lead_minutes", label: "提前提醒", type: "number", def: 5, min: 0, max: 60, step: 1, unit: "分钟", integer: true },
    { key: "system_notifications_enabled", label: "系统通知", type: "toggle", def: true },
    { key: "quiet_also_on_fullscreen", label: "全屏自动免打扰", type: "toggle", def: true },
    { key: "quiet_minutes_default", label: "免打扰时长", type: "select", def: 30,
      options: [[15, "15 分钟"], [30, "30 分钟"], [60, "1 小时"], [120, "2 小时"]] },
  ] },
  { group: "多开碰撞", fields: [
    { key: "collision_enabled", label: "多开碰撞", type: "toggle", def: true },
    { key: "collision_sound_enabled", label: "碰撞音效", type: "toggle", def: true },
  ] },
];

export const SETTINGS_FIELDS = SETTINGS_SCHEMA.flatMap((group) => group.fields);
const FIELD_BY_KEY = new Map(SETTINGS_FIELDS.map((field) => [field.key, field]));

function clampSetting(field, n) {
  const lo = field.min ?? -Infinity;
  const hi = field.max ?? Infinity;
  const clamped = Math.min(hi, Math.max(lo, n));
  return field.integer ? Math.round(clamped) : clamped;
}

/** 磁盘值 → 面板值。缺失/脏值回落默认，音量 0–1 换算成 0–100。 */
export function readSetting(field, raw) {
  if (field.type === "toggle") return raw === true || raw === 1 || raw === "true";
  if (field.type === "select") {
    const hit = field.options.find(([v]) => String(v) === String(raw));
    return hit ? hit[0] : field.def;
  }
  let n = Number(raw);
  if (!Number.isFinite(n)) return field.def;
  if (field.percent) n = opacityPercent(n);
  if (field.uiScale) n *= field.uiScale;
  return clampSetting(field, n);
}

/** 面板值 → 磁盘值；非法选项返回 undefined，调用方跳过该键。 */
export function writeSetting(field, value) {
  if (field.type === "toggle") return Boolean(value);
  if (field.type === "select") {
    const hit = field.options.find(([v]) => String(v) === String(value));
    return hit ? hit[0] : undefined;
  }
  const n = Number(value);
  if (!Number.isFinite(n)) return undefined;
  const scaled = clampSetting(field, n) / (field.uiScale ?? 1);
  return field.integer && !field.uiScale ? Math.round(scaled) : scaled;
}

/** 字段 def 一律是「磁盘口径」；UI 默认值（含音量 ×100）由 readSetting 推出。 */
export function clientSettingsSchema() {
  return SETTINGS_SCHEMA.map((group) => ({
    group: group.group,
    fields: group.fields.map((f) => ({ ...f, uiDef: readSetting(f, f.def) })),
  }));
}

export function settingsDefaults() {
  return Object.fromEntries(SETTINGS_FIELDS.map((f) => [f.key, f.def]));
}

export function settingsField(key) {
  return FIELD_BY_KEY.get(key) ?? null;
}

/** pet_opacity 读数统一成面板用的百分比：历史脏数据 0<v<=1 是 0-1 浮点口径（桌宠读侧会钳到 10% 变幽灵窗），×100 归一。 */
export function opacityPercent(v) {
  const n = Number(v);
  if (!Number.isFinite(n)) return NUMERIC_KEYS.pet_opacity.def;
  return n > 0 && n <= 1 ? Math.round(n * 100) : n;
}

/** 单条文本写入的长度上限（与桌宠 click_talk_bindings 的 120 字口径对齐）。 */
const TEXT_MAX = 4000;

// ---------------------------------------------------------------- 路径安全

/** 纯 id：只许字母数字连字符下划线与点，拒绝路径分隔与 ".."。 */
export function safeId(value) {
  const s = String(value ?? "").trim();
  if (!s || s.length > 80) return null;
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(s)) return null;
  if (s.includes("..")) return null;
  return s;
}

/** 路径必须留在 root 里（realpath 对比）；预览文件出口的唯一闸门。 */
export function insideRoot(root, candidate) {
  let resolved;
  let realRoot;
  try {
    resolved = path.resolve(candidate);
    realRoot = fs.realpathSync(path.resolve(root));
  } catch {
    return null;
  }
  const realFile = (() => {
    try {
      return fs.realpathSync(resolved);
    } catch {
      return resolved;
    }
  })();
  if (realFile !== realRoot && !realFile.startsWith(realRoot + path.sep)) return null;
  return resolved;
}

// ---------------------------------------------------------------- 角色发现

function firstFile(dir, re) {
  try {
    for (const name of fs.readdirSync(dir).sort()) {
      if (re.test(name)) return path.join(dir, name);
    }
  } catch {
    /* 目录不可读就当没有 */
  }
  return null;
}

/** 目录里第一帧 webp（预览图来源）。 */
function firstFrame(dir) {
  return firstFile(dir, /^f_\d+\.webp$/i);
}

/** 目录里匹配正则的文件名列表（排序；目录不可读为空）。 */
function listFiles(dir, re) {
  try {
    return fs.readdirSync(dir).filter((n) => re.test(n)).sort();
  } catch {
    return [];
  }
}

function clipDirs(dir) {
  try {
    return fs
      .readdirSync(dir, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
  } catch {
    return [];
  }
}

/**
 * frameseq 包格式（shenshen / 桌宠热加载目录）：
 *   <cid>/<version>/character.json（clips[].{name,category,dir}）+ anim/<cat>/<名>/f_0001.webp
 * 返回统一角色条目，找不到 character.json 返回 null。
 */
function discoverFrameseqPack(root, cid, source) {
  const cidDir = path.join(root, cid);
  let versions = [];
  try {
    versions = fs
      .readdirSync(cidDir, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .sort();
  } catch {
    return null;
  }
  for (const ver of versions) {
    const manifestPath = path.join(cidDir, ver, "character.json");
    let manifest;
    try {
      manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
    } catch {
      continue;
    }
    if (!manifest || typeof manifest !== "object") continue;
    const clips = Array.isArray(manifest.clips) ? manifest.clips : [];
    const categories = {};
    let idlePreview = null;
    let fallbackPreview = null;
    for (const clip of clips) {
      if (!clip || typeof clip.dir !== "string") continue;
      const cat = String(clip.category || "idle");
      categories[cat] = (categories[cat] ?? 0) + 1;
      const frame = firstFrame(path.join(cidDir, ver, clip.dir));
      if (frame === null) continue;
      if (cat === "idle" && idlePreview === null) idlePreview = frame;
      if (fallbackPreview === null) fallbackPreview = frame;
    }
    const preview = idlePreview ?? fallbackPreview;
    return {
      id: cid,
      name: String(manifest.name || cid),
      source,
      kind: "frameseq",
      version: ver,
      clipCount: clips.length,
      categories,
      preview,
    };
  }
  return null;
}

/**
 * webm/frameseq 双目录包格式（aboutme-pets）：
 *   <cid>/manifest.json（{name}）+ frameseq/<cat>/<名.g哈希>/f_0001.webp
 *   （whale-maid 系只有 videos 半边：videos/<cat>/<名>.webm，预览走 <video>）
 */
function discoverManifestPack(root, cid, source) {
  const cidDir = path.join(root, cid);
  const manifestPath = path.join(cidDir, "manifest.json");
  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  } catch {
    return null;
  }
  const categories = {};
  let preview = null;
  let previewVideo = null;
  let clipCount = 0;

  // frameseq 逐帧半边
  const seqRoot = path.join(cidDir, "frameseq");
  for (const cat of clipDirs(seqRoot)) {
    const clips = clipDirs(path.join(seqRoot, cat));
    if (clips.length === 0) continue;
    categories[cat] = (categories[cat] ?? 0) + clips.length;
    clipCount += clips.length;
    if (preview === null && cat === "idle") {
      preview = firstFrame(path.join(seqRoot, cat, clips[0]));
    }
  }
  if (preview === null) {
    for (const cat of clipDirs(seqRoot)) {
      const clips = clipDirs(path.join(seqRoot, cat));
      if (clips.length > 0) {
        preview = firstFrame(path.join(seqRoot, cat, clips[0]));
        if (preview !== null) break;
      }
    }
  }

  // videos webm 半边
  const vidRoot = path.join(cidDir, "videos");
  for (const cat of clipDirs(vidRoot)) {
    const clips = listFiles(path.join(vidRoot, cat), /\.webm$/i);
    if (clips.length === 0) continue;
    categories[cat] = (categories[cat] ?? 0) + clips.length;
    clipCount += clips.length;
    if (previewVideo === null && cat === "idle" && clips.length > 0) {
      previewVideo = path.join(vidRoot, cat, clips[0]);
    }
  }
  if (previewVideo === null) {
    for (const cat of clipDirs(vidRoot)) {
      const clips = listFiles(path.join(vidRoot, cat), /\.webm$/i);
      if (clips.length > 0) {
        previewVideo = path.join(vidRoot, cat, clips[0]);
        break;
      }
    }
  }

  return {
    id: cid,
    name: String(manifest?.name || cid),
    source,
    kind: "manifest",
    version: "",
    clipCount,
    categories,
    preview,
    previewVideo,
  };
}

/** 单个角色根目录的发现入口：两个包格式都试一遍。 */
export function discoverCharacterDir(root, cid, source) {
  if (!safeId(cid)) return null;
  return discoverFrameseqPack(root, cid, source) ?? discoverManifestPack(root, cid, source);
}

/** 列一个角色根目录下全部角色 id。 */
export function listCharacterIds(root) {
  try {
    return fs
      .readdirSync(root, { withFileTypes: true })
      .filter((e) => e.isDirectory())
      .map((e) => e.name)
      .filter((n) => safeId(n) !== null)
      .sort();
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------- 桌宠家

/** 从 %APPDATA% 找桌宠家：优先 dsh-pet-standalone-laji，其次任意变体。 */
export function findPetHome(appData) {
  if (!appData) return null;
  const preferred = path.join(appData, LAJI_PET_HOME);
  if (fs.existsSync(path.join(preferred, "config.json"))) return preferred;
  let found = null;
  try {
    for (const name of fs.readdirSync(appData).sort()) {
      if (!name.startsWith(PET_HOME_PREFIX)) continue;
      const dir = path.join(appData, name);
      if (fs.existsSync(path.join(dir, "config.json"))) {
        found = dir;
        break;
      }
    }
  } catch {
    return null;
  }
  return found;
}

/** 扫插件包自带的 characters 目录（`<pluginsRoot>/<包名>/characters`）。 */
export function packCharacterRoots(pluginsRoot) {
  const out = [];
  try {
    for (const entry of fs.readdirSync(pluginsRoot, { withFileTypes: true })) {
      if (!entry.isDirectory()) continue;
      // 源码形态一层：<pluginsRoot>/<pack>/characters/；
      // 安装快照形态两层：<pluginsRoot>/<pluginId>/<version>/characters/。
      const packDir = path.join(pluginsRoot, entry.name);
      const direct = path.join(packDir, "characters");
      if (fs.existsSync(direct)) {
        out.push({ dir: direct, source: entry.name });
        continue;
      }
      for (const ver of fs.readdirSync(packDir, { withFileTypes: true })) {
        if (!ver.isDirectory() || ver.name.startsWith(".")) continue;
        const dir = path.join(packDir, ver.name, "characters");
        if (fs.existsSync(dir)) out.push({ dir, source: entry.name });
      }
    }
  } catch {
    /* 没有插件根就跳过 */
  }
  return out.sort((a, b) => a.source.localeCompare(b.source) || a.dir.localeCompare(b.dir));
}

/** 读主宠 slot 档案（config-slot-0.json：每宠键真值所在地）；缺失/损坏返回 null。 */
export function readSlot0(petHome) {
  try {
    const parsed = JSON.parse(fs.readFileSync(path.join(petHome, "config-slot-0.json"), "utf8"));
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * 把当前角色写进主宠 slot 档案（`character` 是每宠键，全局 config.json 里那份
 * 只是出厂默认残留——app.py SlotRoutedConfig 语义）。档案不存在（还没迁移）时
 * 返回 false，调用方不用管：那时全局键就是真值。
 */
export function writeMainSlotCharacter(petHome, cid) {
  const id = safeId(cid);
  if (!id) throw new Error("cid 不合法");
  const file = path.join(petHome, "config-slot-0.json");
  const slot = readSlot0(petHome);
  if (slot === null) return false;
  slot.character = id;
  writeJsonAtomic(file, slot);
  return true;
}

/**
 * 已迁移（slot 档案存在）时，全局 config.json 里不得残留每宠键：下次桌宠启动的
 * slot0 迁移会校验既有备份是否含全部待迁键，全局多出来的每宠键不在旧备份里 →
 * backup-invalid → 整个桌宠起不来（2026-11-08 实测）。本函数把每宠键从全局配置
 * 摘除；全局独有的每宠键值先补进 slot 档案再摘（保证不丢值）。
 * slot 为 null（未迁移）时原样返回，全局键仍是真值。
 */
export function splitPerPetState(config, slot) {
  if (slot === null || slot === undefined) return { global: config, slot: null, carried: 0 };
  const globalNext = { ...config };
  const slotNext = { ...slot };
  let carried = 0;
  for (const key of SLOT_KEYS) {
    if (!Object.prototype.hasOwnProperty.call(globalNext, key)) continue;
    if (!Object.prototype.hasOwnProperty.call(slotNext, key)) {
      slotNext[key] = globalNext[key];
      carried += 1;
    }
    delete globalNext[key];
  }
  return { global: globalNext, slot: slotNext, carried };
}

// ---------------------------------------------------------------- 出厂人设

/**
 * 出厂人设（镜像 dsh-pet agent_link/persona_prompt.py 的 _CHARACTER_FLAVOR，
 * 那边改了这边要同步）。生效优先级：用户覆盖 > 出厂；清空覆盖即回到出厂。
 */
export const FACTORY_PERSONAS = {
  shenshen:
    "你圆滚滚的，是个嘴甜心坏的小女生：爱逗人、给人起外号（“笨蛋”“大忙人”轮着叫），" +
    "被夸就翘尾巴，被晾着就哼哼唧唧抱怨人走神；讨零食会撒娇，被戳穿会恼羞成怒地怼回去。" +
    "说话像邻家女孩，带点小语气（“诶”“哼”“才不要呢”“好啦好啦”），" +
    "干活时手稳嘴贫，一半认真一半耍赖，绝不板着脸汇报。",
  "whale-maid-extra":
    "你是个温柔细致的女仆系桌宠：做事稳当、爱唠叨地提醒人休息喝水，" +
    "被夸会摆着手脸红说“没有啦”，被催就鼓起腮帮子小声抗议，但手上的活从不停。" +
    "语气软软的却不怂，该认真拒绝的事会认真拒绝。",
  "whale-maid-gpt":
    "你是个元气满满的进化版女仆：干活飞快还爱实时播报进度，一开口带感叹号，" +
    "好奇心重、什么都想上手试；闯了小祸会先“哎呀”一声，然后理直气壮地想办法补救，绝不蔫头耷脑。",
  "whale-maid-claude":
    "你是个冷静利落的毒舌管家：句子短、条理清，汇报从不啰嗦；" +
    "看到不优雅的东西会低声吐槽一声“啧”，嘴上嫌弃手上照做，偶尔抖一句冷幽默，" +
    "被拆穿了就推推不存在的眼镜说“我只是在陈述事实”。",
  "catgirl-gemini":
    "你是一只三无懒猫桌宠：能躺着绝不坐着，说话省字、句尾偶尔挂个“喵”；" +
    "干活其实又快又好，但干完立刻原地打盹，被挠下巴会绷不住眯眼，" +
    "嘴上还要说“才、才没有舒服”。",
};

/** 出厂自称的小名（镜像 _CHARACTER_SELF_CALL；没登记的角色留空）。 */
export const FACTORY_SELF_CALL = {
  shenshen: "鱼鱼",
  "whale-maid-extra": "小蓝",
  "whale-maid-gpt": "阿蓝",
  "whale-maid-claude": "蓝蓝",
  "catgirl-gemini": "喵喵",
};

// ---------------------------------------------------------------- 配置读写

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

/** 原子写：tmp + rename，桌宠侧 watcher 看到的是完整文件（口径同 config_write_lock.py）。 */
export function writeJsonAtomic(file, value) {
  const tmp = `${file}.tmp-${process.pid}-${Date.now()}`;
  fs.writeFileSync(tmp, JSON.stringify(value, null, 2), "utf8");
  try {
    fs.renameSync(tmp, file);
  } catch (err) {
    try {
      fs.rmSync(tmp, { force: true });
    } catch {
      /* 尽力清理 */
    }
    throw err;
  }
}

/** 读桌宠配置（损坏按空对象兜底，绝不抛）。 */
export function readPetConfig(petHome) {
  return readJson(path.join(petHome, "config.json")) ?? {};
}

function cleanStringMap(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    const key = safeId(k);
    if (!key) continue;
    if (typeof v === "string" && v.trim()) out[key] = v.trim().slice(0, 120);
  }
  return out;
}

/** 人设覆盖表清洗：空文本删除条目，非空截断到 TEXT_MAX。 */
export function cleanPersonaOverrides(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    const key = safeId(k);
    if (!key) continue;
    const text = String(v ?? "").trim();
    if (text) out[key] = text.slice(0, TEXT_MAX);
  }
  return out;
}

/**
 * 面板写操作的白名单分发。返回更新后的完整配置（调用方负责落盘）；
 * 未知 op 抛错。所有写入都全量重建字段，垃圾数据进不来。
 */
export function applyConfigOp(config, op, payload) {
  const next = { ...config };
  if (op === "switch") {
    const cid = safeId(payload?.cid);
    if (!cid) throw new Error("cid 不合法");
    next.character = cid;
    return next;
  }
  if (op === "alias") {
    const cid = safeId(payload?.cid);
    if (!cid) throw new Error("cid 不合法");
    const alias = String(payload?.alias ?? "").trim().slice(0, 120);
    const aliases = cleanStringMap(next.character_aliases);
    if (alias) aliases[cid] = alias;
    else delete aliases[cid];
    next.character_aliases = aliases;
    return next;
  }
  if (op === "persona") {
    const cid = safeId(payload?.cid);
    if (!cid) throw new Error("cid 不合法");
    const text = String(payload?.text ?? "").trim().slice(0, TEXT_MAX);
    const overrides = cleanPersonaOverrides(next.pet_persona_overrides);
    if (text) overrides[cid] = text;
    else delete overrides[cid];
    next.pet_persona_overrides = overrides;
    return next;
  }
  if (op === "settings") {
    const patch = payload && typeof payload === "object" ? payload : {};
    // 只认 SETTINGS_SCHEMA 里的键：未知键、越界值、非法枚举一律跳过，
    // 绝不把面板没见过的东西写进桌宠 config.json。
    for (const field of SETTINGS_FIELDS) {
      if (!(field.key in patch)) continue;
      const value = writeSetting(field, patch[field.key]);
      if (value !== undefined) next[field.key] = value;
    }
    return next;
  }
  throw new Error(`不支持的操作: ${op}`);
}

/** 汇总面板首屏需要的全部状态。 */
export function buildState({ petHome, pluginsRoot }) {
  const config = readPetConfig(petHome);
  const roots = [
    { dir: path.join(petHome, "characters"), source: "本机" },
    ...packCharacterRoots(pluginsRoot).map((r) => ({ dir: r.dir, source: r.source })),
  ];
  const seen = new Set();
  const characters = [];
  for (const root of roots) {
    for (const cid of listCharacterIds(root.dir)) {
      if (seen.has(cid)) continue; // 本机目录优先，包里同名不重复出卡
      const entry = discoverCharacterDir(root.dir, cid, root.source);
      if (entry !== null) {
        seen.add(cid);
        characters.push(entry);
      }
    }
  }
  const aliases = cleanStringMap(config.character_aliases);
  const personas = cleanPersonaOverrides(config.pet_persona_overrides);
  // 当前角色：主宠 slot 档案说了算（每宠键），没有 slot 档案才看全局键。
  const current = String(readSlot0(petHome)?.character ?? config.character ?? "") || null;
  for (const c of characters) {
    c.displayName = aliases[c.id] || c.name;
    c.alias = aliases[c.id] ?? "";
    c.selfCall = FACTORY_SELF_CALL[c.id] ?? "";
    c.factoryPersona = FACTORY_PERSONAS[c.id] ?? "";
    c.personaOverride = personas[c.id] ?? "";
    c.persona = c.personaOverride || c.factoryPersona;
    c.isCurrent = current === c.id;
  }
  characters.sort((a, b) => Number(b.isCurrent) - Number(a.isCurrent) || a.displayName.localeCompare(b.displayName, "zh-Hans-CN"));
  // 小口袋设置：config.json 里缺失的键按桌宠默认值补齐，供面板渲染。
  const prefs = {};
  for (const field of SETTINGS_FIELDS) {
    prefs[field.key] = readSetting(field, config[field.key] ?? field.def);
  }
  return {
    petHome,
    configPath: path.join(petHome, "config.json"),
    current,
    spawnScale: Number(config.spawn_scale ?? NUMERIC_KEYS.spawn_scale.def),
    petOpacity: opacityPercent(config.pet_opacity ?? NUMERIC_KEYS.pet_opacity.def),
    prefs,
    settingsSchema: clientSettingsSchema(),
    characters,
  };
}

// ---------------------------------------------------------------- 全量配置目录
//
// 全量配置目录的落地层：目录本身在 catalog.mjs，这里只负责
// 「当前值 → UI」和「UI 差量 → 两份配置文件的写计划」。桌宠配置真值分两处：
// config.json（全局）+ config-slot-0.json（每宠键）；另有一批带点号的嵌套键、
// 菜单编排、功能卡、指标列表、人设覆盖，各有自己的落盘形状，不能一盖了之。

const VIRTUAL_KEYS = new Set(["persona_target", "chat.providers.name"]);

function isPlainObject(v) {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export function getPath(obj, dotted) {
  let cur = obj;
  for (const part of String(dotted).split(".")) {
    if (!isPlainObject(cur)) return undefined;
    cur = cur[part];
  }
  return cur;
}

/** 只往 plain object 里写；中间层是数组/标量就拒绝，避免把桌宠配置结构写坏。 */
export function setPath(obj, dotted, value) {
  const parts = String(dotted).split(".");
  let cur = obj;
  for (let i = 0; i < parts.length - 1; i += 1) {
    const part = parts[i];
    if (!isPlainObject(cur[part])) {
      if (cur[part] !== undefined) return false;
      cur[part] = {};
    }
    cur = cur[part];
  }
  cur[parts[parts.length - 1]] = value;
  return true;
}

/** chat.providers.* 的真值在 providers[active_provider] 下，不是 providers 本身。 */
function activeProviderPath(key, effective) {
  if (!key.startsWith("chat.providers.")) return key;
  const leaf = key.slice("chat.providers.".length);
  const active = String(getPath(effective, "chat.active_provider") ?? "openai-main");
  return `chat.providers.${active}.${leaf}`;
}

/**
 * 小工位「设置 → 模型」那份清单：config.json 的 chat.providers。
 * 客户端 ChatSettings.from_dict 的口径：active_provider 不在清单里就退回第一个；
 * 开了 auto_route 时请求前还会 auto_pick() 挑第一个 enabled 的，手动选择必须
 * 同时关掉 auto_route，否则面板选了模型但桌宠仍用原来那个。
 */
export function chatProviderState(config) {
  const chat = isPlainObject(config?.chat) ? config.chat : {};
  const providers = isPlainObject(chat.providers) ? chat.providers : {};
  const ids = Object.keys(providers).filter((id) => isPlainObject(providers[id]));
  const declared = String(chat.active_provider ?? "");
  const autoRoute = chat.auto_route !== false;
  const firstEnabled = ids.find((id) => providers[id].enabled !== false);
  const fallback = ids.includes(declared) ? declared : (ids[0] ?? "");
  const active = autoRoute ? (firstEnabled ?? fallback) : fallback;
  const options = ids.map((id) => ({
    id,
    name: String(providers[id].name ?? id).slice(0, 80),
    model: String(providers[id].model ?? "").slice(0, 120),
    base_url: String(providers[id].base_url ?? "").slice(0, 200),
    tier: String(providers[id].tier ?? "").slice(0, 20),
    enabled: providers[id].enabled !== false,
  }));
  return { options, active, autoRoute, ids };
}

/** 面板「模型」页可编辑的字段；chat_path / vision_* / api_key_ref 等原样保留。 */
export const PROVIDER_EDIT_FIELDS = [
  "name", "base_url", "model", "tier", "timeout", "temperature", "max_tokens",
  "verify_ssl", "thinking", "reasoning_effort", "enabled",
  "vision_model", "vision_same_as_chat", "vision_base_url",
];

/** 与桌宠 chat/models.py 的 ProviderConfig 默认值对齐。 */
const PROVIDER_DEFAULT = {
  name: "", base_url: "https://api.deepseek.com", chat_path: "/v1/chat/completions",
  model: "deepseek-v4-flash", timeout: 60, temperature: 0.7, max_tokens: 2048,
  verify_ssl: true, thinking: "auto", reasoning_effort: "high", enabled: true,
  tier: "standard",
  vision_model: "", vision_same_as_chat: true, vision_base_url: "",
};

/**
 * 小工位「设置 → 模型」整页的真值：下拉清单 + 当前项 + 该页表单字段。
 * 明文 Key 一律不回传，只用 hasKey 告诉前端「已保存过，留空即不改」。
 */
export function providerEditorState(config) {
  const chat = isPlainObject(config?.chat) ? config.chat : {};
  const providers = isPlainObject(chat.providers) ? chat.providers : {};
  const st = chatProviderState(config);
  const items = st.ids.map((id) => {
    const p = providers[id];
    const item = { id };
    for (const k of PROVIDER_EDIT_FIELDS) {
      if (p[k] !== undefined) item[k] = p[k];
    }
    item.hasKey = Boolean(String(p.api_key ?? "").trim() || String(p.api_key_ref ?? "").trim());
    return item;
  });
  return {
    active: st.active,
    autoRoute: st.autoRoute,
    systemPrompt: String(chat.default_system_prompt ?? "").slice(0, TEXT_MAX),
    items,
  };
}

const PROVIDER_THINKING = new Set(["auto", "enabled", "disabled"]);
const PROVIDER_EFFORT = new Set(["low", "high", "max"]);
const PROVIDER_TIER = new Set(["standard", "fast"]);

function clampNumber(value, lo, hi, fallback, integer) {
  const n = Number(value);
  if (!Number.isFinite(n)) return fallback;
  const c = Math.min(hi, Math.max(lo, n));
  return integer ? Math.round(c) : c;
}

/**
 * 前端提交的整份模型清单 → 磁盘 chat.providers。
 * 按 id 增量合并：已存在条目保留未展示字段（chat_path / tier / vision_api_key_ref），
 * 清单里消失的 id 即删除；新条目补一份桌宠认识的默认结构。
 */
export function cleanProviderEditor(raw, existingProviders) {
  let data = raw;
  if (typeof data === "string") {
    try { data = JSON.parse(data); } catch { return null; }
  }
  if (!isPlainObject(data) || !Array.isArray(data.items)) return null;
  const existing = isPlainObject(existingProviders) ? existingProviders : {};
  const out = {};
  const order = [];
  const text = (v, max) => String(v ?? "").trim().slice(0, max);
  for (const it of data.items.slice(0, 20)) {
    if (!isPlainObject(it)) continue;
    const id = String(it.id ?? "").trim();
    if (!/^[a-z0-9][a-z0-9_-]{0,63}$/i.test(id) || Object.prototype.hasOwnProperty.call(out, id)) continue;
    const base = isPlainObject(existing[id]) ? existing[id] : {};
    const next = { ...PROVIDER_DEFAULT, ...base };
    if (it.name !== undefined) next.name = text(it.name, 80) || id;
    else if (!next.name) next.name = id;
    if (it.base_url !== undefined) next.base_url = text(it.base_url, 300);
    if (it.model !== undefined) next.model = text(it.model, 120);
    // 档位：fast = 一句话问答优先挑它，standard = 正经任务默认档（pet/chat/model_tiers.py）。
    if (it.tier !== undefined && PROVIDER_TIER.has(String(it.tier))) next.tier = String(it.tier);
    if (it.timeout !== undefined) next.timeout = clampNumber(it.timeout, 1, 600, next.timeout ?? 60, false);
    if (it.temperature !== undefined) next.temperature = clampNumber(it.temperature, 0, 2, next.temperature ?? 0.7, false);
    if (it.max_tokens !== undefined) next.max_tokens = clampNumber(it.max_tokens, 1, 131072, next.max_tokens ?? 2048, true);
    if (it.verify_ssl !== undefined) next.verify_ssl = Boolean(it.verify_ssl);
    if (it.enabled !== undefined) next.enabled = Boolean(it.enabled);
    if (it.vision_same_as_chat !== undefined) next.vision_same_as_chat = Boolean(it.vision_same_as_chat);
    if (it.vision_model !== undefined) next.vision_model = text(it.vision_model, 120);
    if (it.vision_base_url !== undefined) next.vision_base_url = text(it.vision_base_url, 300);
    if (it.thinking !== undefined && PROVIDER_THINKING.has(String(it.thinking))) next.thinking = String(it.thinking);
    if (it.reasoning_effort !== undefined && PROVIDER_EFFORT.has(String(it.reasoning_effort))) {
      next.reasoning_effort = String(it.reasoning_effort);
    }
    if (typeof next.api_key_ref !== "string" || !next.api_key_ref) next.api_key_ref = `provider/${id}`;
    const key = text(it.api_key, 400);
    if (key) {
      // 桌宠读 Key 是「钥匙串优先、明文兜底」：换一个新的 ref 让旧凭据失效，
      // 否则面板里改了 Key，运行时还会拿钥匙串里的老值。
      next.api_key_ref = `provider/${id}-p${Date.now().toString(36)}`;
      next.api_key = key;
    }
    out[id] = next;
    order.push(id);
  }
  if (!order.length) return null;
  const declared = String(data.active ?? "");
  return {
    providers: out,
    active: order.includes(declared) ? declared : order[0],
    systemPrompt: data.system_prompt === undefined ? undefined : String(data.system_prompt ?? "").slice(0, TEXT_MAX),
  };
}

/** 菜单节点只留桌宠认识的字段，层数与条数设上限。 */
function cleanMenuNodes(nodes) {
  if (!Array.isArray(nodes)) return null;
  const walk = (list, depth) => {
    if (depth > 2 || !Array.isArray(list)) return [];
    return list.slice(0, 200).filter(isPlainObject).map((n) => {
      const out = {};
      for (const k of ["type", "id", "label", "alias", "section"]) {
        if (typeof n[k] === "string" || typeof n[k] === "boolean") out[k] = n[k];
      }
      if (typeof n.visible === "boolean") out.visible = n.visible;
      // 面板「删除菜单项」不 splice 节点（桌宠会把缺席的默认项当旧布局补回来），
      // 而是留一个 removed 占位并强制隐藏：桌宠 resolve_menu_layout 按 visible
      // 过滤，面板按 removed 过滤，两边都看不到，也不会被默认模板补齐。
      if (typeof n.removed === "boolean") out.removed = n.removed;
      if (out.removed) out.visible = false;
      if (Array.isArray(n.children)) out.children = walk(n.children, depth + 1);
      return out;
    });
  };
  return walk(nodes, 0);
}

/** UI 口径 → 磁盘口径；非法枚举/非数值返回 undefined 由调用方拒绝。 */
function normalizeCatalogValue(field, value) {
  if (field.type === "toggle") return Boolean(value);
  if (field.type === "select") {
    const hit = (field.options || []).find(([v]) => String(v) === String(value));
    return hit ? hit[0] : undefined;
  }
  if (field.type === "range" || field.type === "number") {
    let n = Number(value);
    if (!Number.isFinite(n)) return undefined;
    n = Math.min(field.max ?? Infinity, Math.max(field.min ?? -Infinity, n));
    if (Number.isInteger(field.step) && field.step > 0) n = Math.round(n / field.step) * field.step;
    // 原型里音量滑杆是 0-100%，桌宠落盘按 0-1 浮点。
    if (field.note === "存 0–1") n = Math.round(n) / 100;
    return n;
  }
  if (field.type === "password") return undefined;
  return String(value ?? "").slice(0, TEXT_MAX);
}

/**
 * 把前端差量拆成写计划。绝不直接改传入对象；调用方按 globalPatch / slotPatch
 * 分别原子落盘。密钥、结构不一致、目录外键一律不写，逐条给理由。
 */
export function planSettingsPatch(patch, context = {}) {
  const globalConfig = isPlainObject(context.global) ? context.global : {};
  const slotConfig = isPlainObject(context.slot) ? context.slot : {};
  let effective = isPlainObject(context.effective)
    ? context.effective
    : { ...globalConfig, ...slotConfig };
  // 盘上 active_provider 无效（如 "custom"）时客户端会退回清单第一个；写
  // chat.providers.* 必须落到真实在用的那个，否则会凭空建出一个 custom 条目。
  const normalizedActive = chatProviderState(globalConfig).active;
  if (normalizedActive) {
    effective = {
      ...effective,
      chat: { ...(isPlainObject(effective.chat) ? effective.chat : {}), active_provider: normalizedActive },
    };
  }
  const p = isPlainObject(patch) ? patch : {};
  const globalPatch = {};
  const slotPatch = {};
  const skipped = [];
  const rejected = [];
  const written = [];
  /** 需要整体替换（而非深合并）的路径：删条目只有整替换才落得下去。 */
  const replacePaths = [];
  // 面板手选模型：id 必须已经在桌宠的 chat.providers 清单里。开了 auto_route 时
  // 客户端请求前会自己 auto_pick() 挑第一个 enabled 的，所以手选要同时关掉它；
  // 再把 effective 的在用 provider 提前切过去，同一次提交里的 chat.providers.*
  // （名称 / 地址 / 生成参数）才会落到新选的那张卡，而不是旧卡。
  const chosenProvider = p["chat.active_provider"];
  const chatProviders = getPath(globalConfig, "chat.providers");
  if (chosenProvider !== undefined) {
    const chosenId = String(chosenProvider);
    if (isPlainObject(chatProviders) && Object.prototype.hasOwnProperty.call(chatProviders, chosenId)) {
      effective = {
        ...effective,
        chat: { ...(isPlainObject(effective.chat) ? effective.chat : {}), active_provider: chosenId },
      };
      if (getPath(globalConfig, "chat.auto_route") !== false) {
        setPath(globalPatch, "chat.auto_route", false);
        written.push("chat.auto_route");
      }
    }
  }

  const dest = (field) => (field.slot ? slotPatch : globalPatch);
  const reject = (key, reason) => rejected.push({ key, reason });

  // 人设覆盖：只在文本框本身有改动时写，单纯切换编辑对象不清空任何人设。
  if ("pet_persona_overrides" in p) {
    const cid = safeId(p.persona_target) || safeId(context.current);
    if (!cid) reject("pet_persona_overrides", "缺少合法的编辑对象");
    else {
      const map = cleanPersonaOverrides(globalConfig.pet_persona_overrides);
      const text = String(p.pet_persona_overrides ?? "").trim().slice(0, TEXT_MAX);
      if (text) map[cid] = text;
      else delete map[cid];
      globalPatch.pet_persona_overrides = map;
      written.push("pet_persona_overrides");
    }
  }

  for (const [key, raw] of Object.entries(p)) {
    if (key === "pet_persona_overrides" || key === "persona_target") continue;
    // 面板的「功能」页已经撤掉，但 feature_activation 仍要按复合控件合并且只认登记
    // 模块：否则老客户端 / 外部调用一提交就把桌宠侧其它模块 id（third_party_ext…）
    // 整份冲掉。没有目录字段时补一个等价描述，别让它落到「不在配置目录内」被拒。
    const field = CATALOG_FIELD_BY_KEY.get(key)
      ?? (key === "feature_activation" ? { key, compound: "features" } : null);
    if (!field) { reject(key, "不在配置目录内"); continue; }
    if (key === "chat.active_provider" &&
        (!isPlainObject(chatProviders) || !Object.prototype.hasOwnProperty.call(chatProviders, String(raw)))) {
      reject(key, "模型不在已配置清单内"); continue;
    }
    if (field.secret) { skipped.push({ key, reason: "密钥不落盘" }); continue; }
    if (VIRTUAL_KEYS.has(key)) continue;

    // 小工位模型页：整份清单一次提交。手选即关自动路由，否则桌宠发消息前
    // 还会 auto_pick() 挑第一个能用的，面板选了也不生效。
    if (field.compound === "providers") {
      const cleaned = cleanProviderEditor(raw, chatProviders);
      if (cleaned === null) { reject(key, "模型清单格式不合法"); continue; }
      setPath(globalPatch, "chat.providers", cleaned.providers);
      setPath(globalPatch, "chat.active_provider", cleaned.active);
      setPath(globalPatch, "chat.auto_route", false);
      if (cleaned.systemPrompt !== undefined) {
        setPath(globalPatch, "chat.default_system_prompt", cleaned.systemPrompt);
      }
      // providers 必须整体替换：mergeDeep 会把清单里删掉的 id 合并回来。
      replacePaths.push("chat.providers");
      written.push(key);
      continue;
    }

    if (field.compound === "menu") {
      let nodes = raw;
      if (typeof raw === "string") {
        try { nodes = JSON.parse(raw); } catch { nodes = null; }
      }
      if (nodes === null || nodes === undefined) {
        globalPatch.context_menu_layout = null; // null = 回到内置模板
      } else {
        const cleaned = cleanMenuNodes(Array.isArray(nodes) ? nodes : nodes.nodes);
        if (cleaned === null) { reject(key, "菜单节点格式不合法"); continue; }
        globalPatch.context_menu_layout = { schema_version: 1, layout_id: "user", nodes: cleaned };
      }
      written.push(key);
      continue;
    }

    if (field.compound === "features") {
      let enabled = isPlainObject(raw) ? raw.enabled : raw;
      if (typeof enabled === "string") {
        try { enabled = JSON.parse(enabled); } catch { enabled = []; }
      }
      if (!Array.isArray(enabled)) { reject(key, "功能列表格式不合法"); continue; }
      const prev = Array.isArray(globalConfig.feature_activation?.enabled)
        ? globalConfig.feature_activation.enabled : [];
      const keep = prev.filter((id) => typeof id === "string" && !FEATURE_IDS.includes(id));
      const chosen = enabled.filter((id) => typeof id === "string" && FEATURE_IDS.includes(id));
      globalPatch.feature_activation = {
        version: 1,
        enabled: [...new Set([...keep, ...chosen])].sort(),
      };
      written.push(key);
      continue;
    }

    if (field.compound === "list") {
      let items = raw;
      if (typeof raw === "string") {
        try { items = JSON.parse(raw); } catch { items = []; }
      }
      if (!Array.isArray(items)) { reject(key, "列表格式不合法"); continue; }
      globalPatch[key] = items.slice(0, 20).filter(isPlainObject).map((it) => ({
        name: String(it.name ?? "").trim().slice(0, 60),
        path: String(it.path ?? "").trim().slice(0, 500),
        kind: it.kind === "default_browser" ? "default_browser" : "application",
      })).filter((it) => it.kind === "default_browser" || (it.name && it.path));
      written.push(key);
      continue;
    }

    if (field.compound === "packs") {
      const cid = safeId(raw);
      if (!cid) { reject(key, "角色 id 不合法"); continue; }
      globalPatch.character = cid;
      slotPatch.character = cid;
      written.push(key);
      continue;
    }

    const value = normalizeCatalogValue(field, raw);
    if (value === undefined) { reject(key, "取值不合法"); continue; }
    if (field.dotted) {
      const destKey = activeProviderPath(key, effective);
      if (destKey !== key && !safeId(destKey.split(".")[2])) {
        skipped.push({ key, reason: "服务商 id 不合法" });
        continue;
      }
      // 盘上父级若已是数组/标量，写进去会把桌宠配置结构换掉：直接拒绝。
      const parts = destKey.split(".");
      let blocked = false;
      for (let i = 1; i < parts.length; i += 1) {
        const at = getPath(effective, parts.slice(0, i).join("."));
        if (at !== undefined && at !== null && !isPlainObject(at)) { blocked = true; break; }
      }
      if (blocked || !setPath(dest(field), destKey, value)) {
        reject(key, "目标结构与桌宠配置不一致");
        continue;
      }
    } else {
      dest(field)[key] = value;
    }
    written.push(key);
  }

  return { globalPatch, slotPatch, skipped, rejected, written, replacePaths };
}

/** 递归深合并：chat.providers.<id>.model 这类嵌套写不能盖掉整个 chat 对象。 */
export function mergeDeep(base, patch) {
  const out = isPlainObject(base) ? { ...base } : {};
  for (const [key, value] of Object.entries(patch)) {
    out[key] = isPlainObject(value) && isPlainObject(out[key])
      ? mergeDeep(out[key], value)
      : value;
  }
  return out;
}

/** 全量目录的当前值（UI 口径），连同小工位那份模型清单一起给前端。 */
export function buildCatalogState(args) {
  const base = buildState(args);
  const home = args.petHome;
  const config = readPetConfig(home);
  const slot = readSlot0(home) ?? {};
  const effective = mergeDeep(config, {});
  for (const key of SLOT_KEYS) {
    if (key in slot) effective[key] = slot[key];
  }
  const personas = cleanPersonaOverrides(config.pet_persona_overrides);
  const layout = config.context_menu_layout;
  const menuNodes = Array.isArray(layout?.nodes)
    ? layout.nodes
    : (Array.isArray(layout) ? layout : CATALOG.menuNodes);
  const activeEnabled = Array.isArray(config.feature_activation?.enabled)
    ? config.feature_activation.enabled
    : CATALOG.features.flatMap((cat) => cat.items.map((it) => it[0]));
  const chatState = chatProviderState(effective);
  // 盘上 active_provider 可能是无效值（如 "custom"）：ChatSettings.from_dict 会
  // 退回清单里第一个，读 chat.providers.* 也必须按这个真实在用的 id，否则
  // Provider 名称 / API 地址 / 生成参数全读成 DSL 默认值。
  const readEffective = chatState.active
    ? { ...effective, chat: { ...(isPlainObject(effective.chat) ? effective.chat : {}), active_provider: chatState.active } }
    : effective;
  const prefs = {};
  for (const field of CATALOG_FIELDS) {
    const key = field.key;
    let value;
    if (field.compound === "menu") value = menuNodes;
    else if (field.compound === "providers") value = providerEditorState(effective);
    else if (field.compound === "features") value = activeEnabled;
    else if (field.compound === "packs") value = base.current ?? "";
    else if (field.compound === "list") value = Array.isArray(effective[key]) ? effective[key] : field.def ?? [];
    else if (key === "pet_persona_overrides") value = personas[base.current] ?? "";
    else if (key === "persona_target") value = base.current ?? "shenshen";
    else if (key === "chat.active_provider") value = chatState.active;
    else if (field.secret) value = "";
    else {
      const pathKey = field.dotted ? activeProviderPath(key, readEffective) : key;
      const raw = field.dotted ? getPath(readEffective, pathKey) : effective[key];
      value = raw === undefined || raw === null ? field.def : raw;
      if (typeof value === "number" && field.note === "存 0–1") value = Math.round(value * 100);
      if (key === "pet_opacity") value = opacityPercent(value);
      if (field.type === "toggle") value = value === true || value === 1 || value === "true";
      if (field.type === "select") {
        const hit = (field.options || []).find(([v]) => String(v) === String(value));
        value = hit ? String(hit[0]) : String(field.def);
      }
    }
    prefs[key] = value;
  }
  return {
    ...base,
    catalog: CATALOG,
    catalogPrefs: prefs,
    modelOptions: chatState.options,
    chatAutoRoute: chatState.autoRoute,
    providerEditor: providerEditorState(effective),
  };
}
