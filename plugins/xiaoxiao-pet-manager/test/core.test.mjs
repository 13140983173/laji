// lib/core.mjs 的单元测试（node --test）。
import * as assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, writeFileSync as wf, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

import {
  applyConfigOp,
  buildCatalogState,
  buildState,
  getPath,
  mergeDeep,
  planSettingsPatch,
  setPath,
  cleanPersonaOverrides,
  clientSettingsSchema,
  discoverCharacterDir,
  FACTORY_PERSONAS,
  FACTORY_SELF_CALL,
  findPetHome,
  insideRoot,
  opacityPercent,
  packCharacterRoots,
  readSetting,
  safeId,
  SETTINGS_FIELDS,
  SETTINGS_SCHEMA,
  settingsField,
  splitPerPetState,
  writeMainSlotCharacter,
  writeSetting,
  CATALOG_FIELDS,
} from "../lib/core.mjs";
import { catalogStats, CATALOG } from "../lib/catalog.mjs";

function makeTemp() {
  return mkdtempSync(path.join(tmpdir(), "xxpm-test-"));
}

// ---------------------------------------------------------------- safeId / insideRoot

test("safeId 拒绝路径穿越与空值", () => {
  assert.equal(safeId("../etc"), null);
  assert.equal(safeId("a/b"), null);
  assert.equal(safeId(""), null);
  assert.equal(safeId(null), null);
  assert.equal(safeId("shenshen"), "shenshen");
  assert.equal(safeId("whale-maid-gpt"), "whale-maid-gpt");
});

test("insideRoot 挡住逃出根目录的路径", () => {
  const root = makeTemp();
  try {
    mkdirSync(path.join(root, "anim"));
    const good = path.join(root, "anim", "f_0001.webp");
    wf(good, "x");
    assert.equal(insideRoot(root, good), path.resolve(good));
    const evil = path.join(root, "..", "outside.webp");
    assert.equal(insideRoot(root, evil), null);
    assert.equal(insideRoot(root, path.join(root, "missing.webp")), path.resolve(path.join(root, "missing.webp")));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------- 角色发现

test("discoverCharacterDir 认 frameseq 包（character.json + anim 帧）", () => {
  const root = makeTemp();
  try {
    const ver = path.join(root, "shenshen", "2.0.0-base-640x360");
    const idleClip = path.join(ver, "anim", "idle", "待机呼吸");
    mkdirSync(idleClip, { recursive: true });
    wf(path.join(idleClip, "f_0001.webp"), "fake");
    writeFileSync(
      path.join(ver, "character.json"),
      JSON.stringify({
        schema: 1,
        id: "shenshen",
        name: "深颈",
        clips: [
          { name: "待机呼吸", category: "idle", dir: "anim/idle/待机呼吸", frames: 1 },
          { name: "点头", category: "click", dir: "anim/click/点头", frames: 2 },
        ],
      }),
      "utf8",
    );
    const c = discoverCharacterDir(root, "shenshen", "本机");
    assert.ok(c);
    assert.equal(c.name, "深颈");
    assert.equal(c.clipCount, 2);
    assert.equal(c.categories.idle, 1);
    assert.ok(c.preview && c.preview.endsWith("f_0001.webp"), "预览取 idle 首帧");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("discoverCharacterDir 认 manifest 包（aboutme-pets 格式）", () => {
  const root = makeTemp();
  try {
    const idle = path.join(root, "catgirl-gemini", "frameseq", "idle", "待机呼吸.gb3fa41e69f55");
    mkdirSync(idle, { recursive: true });
    wf(path.join(idle, "f_0001.webp"), "fake");
    writeFileSync(
      path.join(root, "catgirl-gemini", "manifest.json"),
      JSON.stringify({ name: "猫耳娘·Gemini批次" }),
      "utf8",
    );
    const c = discoverCharacterDir(root, "catgirl-gemini", "aboutme-pets");
    assert.ok(c);
    assert.equal(c.kind, "manifest");
    assert.equal(c.name, "猫耳娘·Gemini批次");
    assert.equal(c.clipCount, 1);
    assert.ok(c.preview && c.preview.endsWith("f_0001.webp"));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("discoverCharacterDir 对乱 id 直接拒绝", () => {
  assert.equal(discoverCharacterDir(makeTemp(), "../evil", "x"), null);
});

test("packCharacterRoots 扫出插件包 characters 目录（Dirent 回归）", () => {
  const plugins = makeTemp();
  try {
    const chars = path.join(plugins, "aboutme-pets", "characters", "catgirl-gemini");
    mkdirSync(chars, { recursive: true });
    writeFileSync(path.join(plugins, "aboutme-pets", "laji.plugin.toml"), "x", "utf8");
    const roots = packCharacterRoots(plugins);
    assert.equal(roots.length, 1, "必须扫到带 characters 的包");
    assert.equal(roots[0].source, "aboutme-pets");
    assert.ok(roots[0].dir.endsWith(path.join("aboutme-pets", "characters")));
  } finally {
    rmSync(plugins, { recursive: true, force: true });
  }
});

test("discoverCharacterDir manifest 包统计 videos webm 并给 previewVideo", () => {
  const root = makeTemp();
  try {
    // whale-maid 系真实形态：frameseq 空壳，动作全在 videos/<cat>/<名>.webm
    mkdirSync(path.join(root, "whale-maid-extra", "frameseq", "idle"), { recursive: true });
    const vid = path.join(root, "whale-maid-extra", "videos", "idle");
    mkdirSync(vid, { recursive: true });
    wf(path.join(vid, "沙发打瞌睡.webm"), "v");
    wf(path.join(vid, "站着晃神打瞌睡.webm"), "v");
    mkdirSync(path.join(root, "whale-maid-extra", "videos", "random"), { recursive: true });
    wf(path.join(root, "whale-maid-extra", "videos", "random", "转圈.webm"), "v");
    writeFileSync(
      path.join(root, "whale-maid-extra", "manifest.json"),
      JSON.stringify({ name: "蓝毛小女仆·新动作包" }),
      "utf8",
    );
    const c = discoverCharacterDir(root, "whale-maid-extra", "aboutme-pets");
    assert.ok(c);
    assert.equal(c.clipCount, 3);
    assert.equal(c.categories.idle, 2);
    assert.equal(c.categories.random, 1);
    assert.ok(c.previewVideo && c.previewVideo.endsWith("沙发打瞌睡.webm"), "预览视频取 idle 第一个");
    assert.equal(c.preview, null, "没有逐帧就没有图预览");
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------- 桌宠家

test("findPetHome 优先 laji 变体", () => {
  const appData = makeTemp();
  try {
    const laji = path.join(appData, "dsh-pet-standalone-laji");
    const other = path.join(appData, "dsh-pet-standalone-foo");
    mkdirSync(path.join(other, "characters"), { recursive: true });
    writeFileSync(path.join(other, "config.json"), "{}", "utf8");
    assert.equal(findPetHome(appData), other, "没有 laji 变体时任一变体可用");
    mkdirSync(laji, { recursive: true });
    writeFileSync(path.join(laji, "config.json"), "{}", "utf8");
    assert.equal(findPetHome(appData), laji);
  } finally {
    rmSync(appData, { recursive: true, force: true });
  }
});

test("findPetHome 找不到返回 null", () => {
  assert.equal(findPetHome(makeTemp()), null);
  assert.equal(findPetHome(null), null);
});

// ---------------------------------------------------------------- 配置写操作

test("applyConfigOp switch 写 character 键", () => {
  const next = applyConfigOp({ character: "a" }, "switch", { cid: "shenshen" });
  assert.equal(next.character, "shenshen");
  assert.throws(() => applyConfigOp({}, "switch", { cid: "../evil" }));
  assert.throws(() => applyConfigOp({}, "unknown-op", {}));
});

test("applyConfigOp alias 增删", () => {
  let next = applyConfigOp({}, "alias", { cid: "shenshen", alias: "222" });
  assert.equal(next.character_aliases.shenshen, "222");
  next = applyConfigOp(next, "alias", { cid: "shenshen", alias: "  " });
  assert.ok(!("shenshen" in next.character_aliases), "空别名 = 删除");
});

test("applyConfigOp persona 增删并截断", () => {
  let next = applyConfigOp({}, "persona", { cid: "shenshen", text: "  嘴甜心坏  " });
  assert.equal(next.pet_persona_overrides.shenshen, "嘴甜心坏");
  next = applyConfigOp(next, "persona", { cid: "shenshen", text: "" });
  assert.deepEqual(next.pet_persona_overrides, {});
  const long = "x".repeat(5000);
  next = applyConfigOp(next, "persona", { cid: "shenshen", text: long });
  assert.equal(next.pet_persona_overrides.shenshen.length, 4000);
});

test("applyConfigOp settings 数值夹到边界内", () => {
  const next = applyConfigOp({}, "settings", { spawn_scale: 99, pet_opacity: -3 });
  assert.equal(next.spawn_scale, 4.0);
  assert.equal(next.pet_opacity, 10, "pet_opacity 口径是百分比 10-100");
  const full = applyConfigOp({}, "settings", { pet_opacity: 100 });
  assert.equal(full.pet_opacity, 100);
});

test("opacityPercent 把 0-1 浮点口径归一成百分比", () => {
  assert.equal(opacityPercent(1), 100, "历史脏数据 1 = 全不透明");
  assert.equal(opacityPercent(0.5), 50);
  assert.equal(opacityPercent(85), 85, "百分比口径原样通过");
  assert.equal(opacityPercent(undefined), 100);
  assert.equal(opacityPercent("junk"), 100);
});

test("cleanPersonaOverrides 丢弃非法键、截断并字符串化", () => {
  const out = cleanPersonaOverrides({ "ok-id": " hi ", "../bad": "x", junk: 42 });
  assert.deepEqual(out, { "ok-id": "hi", junk: "42" });
  assert.deepEqual(cleanPersonaOverrides(null), {});
  assert.deepEqual(cleanPersonaOverrides([1]), {});
});

// ---------------------------------------------------------------- 小口袋设置表

test("小口袋设置表：键唯一、默认值对齐桌宠、且全在 reload 白名单内", () => {
  const keys = SETTINGS_FIELDS.map((f) => f.key);
  assert.equal(new Set(keys).size, keys.length, "schema 出现重复键");
  assert.equal(settingsField("scale").def, 0.72, "catalog.DEFAULT_SCALE");
  assert.equal(settingsField("spawn_scale").def, 0.72);
  assert.equal(settingsField("pet_opacity").def, 100);
  assert.equal(settingsField("click_sound_volume").def, 0.7, "def 是磁盘口径 0.70，UI 显示 70");
  assert.equal(settingsField("quiet_minutes_default").def, 30);
  assert.equal(settingsField("unknown-key"), null);

  // 源码在仓库里时逐键核对：不在白名单的键外部写 config.json 不会被运行期读到。
  const here = path.dirname(fileURLToPath(import.meta.url));
  const py = path.resolve(here, "../../dsh-pet/src/pet/config.py");
  if (existsSync(py)) {
    const src = readFileSync(py, "utf8");
    const start = src.indexOf("for key in (");
    const end = src.indexOf("\n        ):", start);
    assert.ok(start > 0 && end > start, "没找到 config.py 的 reload 白名单块");
    const whitelist = new Set(
      [...src.slice(start, end).matchAll(/"([a-z][a-z0-9_]*)"/g)].map((m) => m[1]),
    );
    assert.deepEqual(keys.filter((k) => !whitelist.has(k)), [], "这些键外部写入不会热生效");
  }
});

test("readSetting / writeSetting 对齐桌宠落盘口径", () => {
  const vol = settingsField("click_sound_volume");
  assert.equal(writeSetting(vol, 70), 0.7, "UI 百分比 → 落盘 0-1 浮点");
  assert.equal(writeSetting(vol, 100), 1);
  assert.equal(readSetting(vol, 0.7), 70);
  assert.equal(readSetting(vol, vol.def), 70, "缺失回落磁盘默认值再换算");
  assert.equal(clientSettingsSchema()[4].fields[1].uiDef, 70, "恢复默认要提交 UI 值 70");

  const op = settingsField("pet_opacity");
  assert.equal(writeSetting(op, 35), 35);
  assert.equal(writeSetting(op, 999), 100);
  assert.equal(writeSetting(op, -5), 10);
  assert.equal(readSetting(op, 0.4), 40, "旧 0-1 浮点口径归一成百分比");

  const sel = settingsField("quiet_minutes_default");
  assert.equal(writeSetting(sel, "60"), 60);
  assert.equal(writeSetting(sel, "7"), undefined, "非法档位不能写盘");
  assert.equal(readSetting(sel, 7), 30);

  const tog = settingsField("on_top");
  assert.equal(writeSetting(tog, false), false);
  assert.equal(readSetting(tog, "false"), false, "字符串 false 不能被当成 True");
});

test("applyConfigOp settings 只写 schema 键、按口径换算", () => {
  const next = applyConfigOp({ keep: 1 }, "settings", {
    click_sound_volume: 45,
    throw_strength: "crazy",
    scale: 0.85,
    on_top: false,
    quiet_minutes_default: 7,
    evil_key: "x",
  });
  assert.equal(next.keep, 1);
  assert.equal(next.click_sound_volume, 0.45);
  assert.equal(next.throw_strength, "crazy");
  assert.equal(next.scale, 0.85);
  assert.equal(next.on_top, false);
  assert.equal("quiet_minutes_default" in next, false);
  assert.equal("evil_key" in next, false);
});

test("buildState 给缺失的设置键补桌宠默认值", () => {
  const home = makeTemp();
  try {
    wf(path.join(home, "config.json"), JSON.stringify({
      pet_opacity: 0.5, click_sound_volume: 0.2, on_top: false,
    }));
    const state = buildState({ petHome: home, pluginsRoot: makeTemp() });
    assert.equal(state.prefs.scale, 0.72);
    assert.equal(state.prefs.pet_opacity, 50);
    assert.equal(state.prefs.click_sound_volume, 20);
    assert.equal(state.prefs.on_top, false);
    assert.equal(state.prefs.quiet_minutes_default, 30);
    assert.equal(state.settingsSchema.length, SETTINGS_SCHEMA.length);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

// ---------------------------------------------------------------- buildState

test("buildState 汇总角色 + 覆盖字段 + 当前标记", () => {
  const home = makeTemp();
  try {
    mkdirSync(path.join(home, "characters", "shenshen", "v1", "anim", "idle", "呼吸"), { recursive: true });
    wf(path.join(home, "characters", "shenshen", "v1", "anim", "idle", "呼吸", "f_0001.webp"), "f");
    writeFileSync(
      path.join(home, "characters", "shenshen", "v1", "character.json"),
      JSON.stringify({ id: "shenshen", name: "深颈", clips: [{ name: "呼吸", category: "idle", dir: "anim/idle/呼吸" }] }),
      "utf8",
    );
    writeFileSync(
      path.join(home, "config.json"),
      JSON.stringify({
        character: "shenshen",
        character_aliases: { shenshen: "小颈" },
        pet_persona_overrides: { shenshen: "嘴甜心坏" },
        spawn_scale: 1.5,
      }),
      "utf8",
    );
    const plugins = makeTemp();
    try {
    const state = buildState({ petHome: home, pluginsRoot: plugins });
    assert.equal(state.current, "shenshen");
    assert.equal(state.spawnScale, 1.5);
    assert.equal(state.characters.length, 1);
    const c = state.characters[0];
    assert.equal(c.displayName, "小颈");
    assert.equal(c.persona, "嘴甜心坏", "有覆盖时 persona = 覆盖");
    assert.equal(c.personaOverride, "嘴甜心坏");
    assert.equal(c.selfCall, "鱼鱼");
    assert.ok(c.factoryPersona.includes("嘴甜心坏"), "出厂人设进状态");
    assert.equal(c.isCurrent, true);
    assert.ok(c.preview.endsWith("f_0001.webp"));
    } finally {
      rmSync(plugins, { recursive: true, force: true });
    }
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("buildState 桌宠家角色优先于包内同名角色", () => {
  const home = makeTemp();
  const plugins = makeTemp();
  try {
    // 包里：aboutme 格式
    const packDir = path.join(plugins, "aboutme-pets", "characters", "shenshen", "frameseq", "idle", "呼吸");
    mkdirSync(packDir, { recursive: true });
    wf(path.join(packDir, "f_0001.webp"), "f");
    writeFileSync(
      path.join(plugins, "aboutme-pets", "characters", "shenshen", "manifest.json"),
      JSON.stringify({ name: "包里的深颈" }),
      "utf8",
    );
    // 本机：frameseq 格式
    const localDir = path.join(home, "characters", "shenshen", "v1");
    mkdirSync(localDir, { recursive: true });
    writeFileSync(
      path.join(localDir, "character.json"),
      JSON.stringify({ id: "shenshen", name: "本机深颈", clips: [] }),
      "utf8",
    );
    writeFileSync(path.join(home, "config.json"), "{}", "utf8");
    const state = buildState({ petHome: home, pluginsRoot: plugins });
    assert.equal(state.characters.length, 1, "同名只出一张卡");
    assert.equal(state.characters[0].name, "本机深颈");
  } finally {
    rmSync(home, { recursive: true, force: true });
    rmSync(plugins, { recursive: true, force: true });
  }
});

test("buildState current 优先取 slot-0 档案，无 slot 退回全局键", () => {
  const home = makeTemp();
  try {
    // 两个最小角色包（不出动画也出卡）
    mkdirSync(path.join(home, "characters", "shenshen", "v1"), { recursive: true });
    writeFileSync(
      path.join(home, "characters", "shenshen", "v1", "character.json"),
      JSON.stringify({ id: "shenshen", name: "深颈", clips: [] }),
      "utf8",
    );
    const gpt = path.join(home, "characters", "whale-maid-gpt");
    mkdirSync(gpt, { recursive: true });
    writeFileSync(path.join(gpt, "manifest.json"), JSON.stringify({ name: "阿蓝" }), "utf8");
    writeFileSync(path.join(home, "config.json"), JSON.stringify({ character: "shenshen" }), "utf8");
    // 没有 slot 档案：看全局键
    let state = buildState({ petHome: home, pluginsRoot: makeTemp() });
    assert.equal(state.current, "shenshen");
    // slot 档案说了算（每宠键真值；全局那份只是出厂残留）
    writeFileSync(
      path.join(home, "config-slot-0.json"),
      JSON.stringify({ version: 4, character: "whale-maid-gpt", facing: "left" }),
      "utf8",
    );
    state = buildState({ petHome: home, pluginsRoot: makeTemp() });
    assert.equal(state.current, "whale-maid-gpt");
    assert.equal(state.characters.find((c) => c.id === "whale-maid-gpt").isCurrent, true);
    assert.equal(state.characters.find((c) => c.id === "shenshen").isCurrent, false);
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("writeMainSlotCharacter 只改 character 其余键不动；无档案返回 false", () => {
  const home = makeTemp();
  try {
    assert.equal(writeMainSlotCharacter(home, "catgirl-gemini"), false, "没有 slot 档案不动");
    const slotPath = path.join(home, "config-slot-0.json");
    writeFileSync(slotPath, JSON.stringify({ version: 4, character: "shenshen", facing: "left", scale: 0.5 }), "utf8");
    assert.equal(writeMainSlotCharacter(home, "catgirl-gemini"), true);
    const slot = JSON.parse(readFileSync(slotPath, "utf8"));
    assert.equal(slot.character, "catgirl-gemini");
    assert.equal(slot.facing, "left");
    assert.equal(slot.scale, 0.5);
    assert.equal(slot.version, 4);
    assert.throws(() => writeMainSlotCharacter(home, "../evil"));
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("出厂人设表覆盖五个内置角色且与自称成对", () => {
  const ids = Object.keys(FACTORY_PERSONAS).sort();
  assert.deepEqual(ids, [
    "catgirl-gemini",
    "shenshen",
    "whale-maid-claude",
    "whale-maid-extra",
    "whale-maid-gpt",
  ]);
  for (const id of ids) {
    assert.ok(FACTORY_PERSONAS[id].length > 20, id + " 有正文");
    assert.equal(typeof FACTORY_SELF_CALL[id], "string", id + " 有自称（可为空串也不该缺键）");
  }
});

// ---------------------------------------------------------------- 全量配置落地

test("配置目录规模与复合控件登记", () => {
  const s = catalogStats();
  assert.equal(s.domains, 9);
  assert.equal(s.tabs, 15);
  assert.equal(s.items, 193);
  assert.equal(s.fields, 128);
  // AI 域收敛成小工位模型页一个 tab，字段只有一个复合 providers。
  assert.ok(CATALOG_FIELDS.some((f) => f.key === "chat_providers" && f.compound === "providers"));
  assert.ok(!CATALOG_FIELDS.some((f) => f.key.startsWith("chat.providers.") || f.key === "chat.active_provider"));
  const chatDomain = CATALOG.domains.find((d) => d.id === "chat");
  assert.deepEqual(chatDomain.tabs.map((t) => t.name), ["模型"]);
  // 互动域只留点击音效 / 自言自语：趣味（每日一签）、天气与全局快捷键不在这块面板里露出。
  const interaction = CATALOG.domains.find((d) => d.id === "interaction");
  assert.deepEqual(interaction.tabs.map((t) => t.name), ["点击与音效", "自言自语"]);
  assert.ok(!CATALOG_FIELDS.some((f) => f.key.startsWith("divination_")));
  // 自动化与联动只留提醒、主动识屏；菜单只留编排、快捷启动。
  const automation = CATALOG.domains.find((d) => d.id === "automation");
  assert.deepEqual(automation.tabs.map((t) => t.name), ["提醒与免打扰", "主动识屏"]);
  const menu = CATALOG.domains.find((d) => d.id === "menu");
  assert.deepEqual(menu.tabs.map((t) => t.name), ["菜单编排", "快捷启动"]);
  // 常规页只剩应用与启动：余额 / 峰谷提示那页撤掉。
  const general = CATALOG.domains.find((d) => d.id === "general");
  assert.deepEqual(general.tabs.map((t) => t.name), ["应用与启动"]);
  assert.ok(!CATALOG_FIELDS.some((f) => f.key.startsWith("balance_")));
  // 功能页整域移除：模块开关只在独立「桌宠设置」窗口里配。
  assert.ok(!CATALOG.domains.some((d) => d.id === "features"));
  assert.ok(!CATALOG_FIELDS.some((f) => f.key === "feature_activation"));
  assert.ok(!CATALOG_FIELDS.some((f) => f.key.startsWith("context_menu_appearance.") || f.key.startsWith("agent_link.")));
  assert.ok(!CATALOG_FIELDS.some((f) => f.key.startsWith("dynamic_island.")));
  assert.ok(CATALOG_FIELDS.some((f) => f.key === "context_menu_layout" && f.compound === "menu"));
  assert.ok(CATALOG_FIELDS.some((f) => f.key === "character" && f.compound === "packs"));
  // 人设改在卡片弹框里编辑，不再占一个设置 tab。
  const characters = CATALOG.domains.find((d) => d.id === "characters");
  assert.equal(characters.tabs.length, 1);
  assert.equal(characters.tabs[0].name, "角色卡");
  assert.ok(!CATALOG_FIELDS.some((f) => f.key === "pet_persona_overrides" || f.key === "persona_target"));
});

test("写计划：全局键 / 每宠键分流，音量按 0-1 落盘", () => {
  const plan = planSettingsPatch(
    { pet_opacity: 85, click_sound_volume: 42, scale: 0.85, autostart_wanted: true },
    { global: {}, slot: {} },
  );
  assert.equal(plan.globalPatch.pet_opacity, 85);
  assert.equal(plan.globalPatch.autostart_wanted, true);
  assert.equal(plan.slotPatch.click_sound_volume, 0.42);
  assert.equal(plan.slotPatch.scale, 0.85);
  assert.deepEqual(plan.rejected, []);
});

test("写计划：菜单编排包成桌宠认识的结构并清洗节点", () => {
  const nodes = [{ type: "action", id: "chat", label: "AI 对话", visible: true, junk: 1 }];
  const plan = planSettingsPatch({ context_menu_layout: nodes }, { global: {}, slot: {} });
  const layout = plan.globalPatch.context_menu_layout;
  assert.equal(layout.schema_version, 1);
  assert.equal(layout.layout_id, "user");
  assert.deepEqual(layout.nodes, [{ type: "action", id: "chat", label: "AI 对话", visible: true }]);
  const cleared = planSettingsPatch({ context_menu_layout: null }, { global: {}, slot: {} });
  assert.equal(cleared.globalPatch.context_menu_layout, null);
});

test("splitPerPetState：已迁移时每宠键只留 slot 档案，全局独有值先补进 slot", () => {
  // 未迁移：原样返回，全局键仍是真值。
  const untouched = splitPerPetState({ character: "a", pet_opacity: 80 }, null);
  assert.equal(untouched.slot, null);
  assert.equal(untouched.global.character, "a");
  // 已迁移：每宠键从全局摘除，全局键（pet_opacity 不是每宠键）保留。
  const slot = { character: "a", scale: 0.5 };
  const out = splitPerPetState(
    { character: "b", scale: 0.7, self_talk_enabled: false, pet_opacity: 80 },
    slot,
  );
  assert.equal("character" in out.global, false);
  assert.equal("scale" in out.global, false);
  assert.equal(out.global.pet_opacity, 80);
  assert.equal(out.slot.character, "a", "slot 已有的键不被全局旧值覆盖（真值在 slot）");
  assert.equal(out.slot.scale, 0.5);
  assert.equal(out.slot.self_talk_enabled, false, "slot 缺的键用全局值补上，不丢");
  assert.equal(out.carried, 1, "只有 self_talk_enabled 是从全局补的");
  // 不改传入对象。
  assert.deepEqual(slot, { character: "a", scale: 0.5 });
});

test("splitPerPetState：全局无每宠键时不动 slot（carried=0）", () => {
  const out = splitPerPetState({ pet_opacity: 80 }, { character: "a" });
  assert.equal(out.carried, 0);
  assert.deepEqual(out.global, { pet_opacity: 80 });
  assert.deepEqual(out.slot, { character: "a" });
});

test("写计划：菜单项删除占位强制隐藏且留在布局里，不会被默认模板补回", () => {
  const nodes = [
    { type: "action", id: "weather", label: "查看天气", visible: true, removed: true },
    { type: "action", id: "chat", label: "AI 对话", removed: true, junk: 1 },
    { type: "submenu", id: "music", label: "音乐", visible: true, children: [
      { type: "action", id: "music_next", label: "切歌", visible: true, removed: true },
    ] },
  ];
  const plan = planSettingsPatch({ context_menu_layout: nodes }, { global: {}, slot: {} });
  const out = plan.globalPatch.context_menu_layout.nodes;
  assert.equal(out.length, 3, "删除项仍留在 nodes 里，否则桌宠会按默认模板补回来");
  assert.equal(out[0].id, "weather");
  assert.equal(out[0].removed, true);
  assert.equal(out[0].visible, false);
  assert.equal(out[1].visible, false, "没写 visible 的删除项也要强制隐藏");
  assert.equal(out[1].junk, undefined);
  assert.equal(out[2].children[0].removed, true);
  assert.equal(out[2].children[0].visible, false);
});

test("写计划：功能卡只替换登记模块，保留桌宠侧其它 id", () => {
  const plan = planSettingsPatch(
    { feature_activation: { version: 1, enabled: ["chat", "voice"] } },
    { global: { feature_activation: { version: 1, enabled: ["chat", "third_party_ext"] } }, slot: {} },
  );
  assert.deepEqual(plan.globalPatch.feature_activation, {
    version: 1, enabled: ["chat", "third_party_ext", "voice"],
  });
});

test("写计划：模型清单整份提交，切在用同时关自动路由", () => {
  const global = {
    chat: {
      auto_route: true,
      active_provider: "custom",
      providers: {
        opencode: { name: "OpenCode Go（订阅）", base_url: "https://opencode.ai/zen/go/v1", model: "m1", api_key_ref: "provider/opencode", tier: "standard" },
        deepseek: { name: "deepseek", base_url: "https://api.deepseek.com/v1", model: "m2", api_key_ref: "provider/deepseek" },
        fast: { name: "fast", base_url: "https://api.deepseek.com/v1", model: "m2", api_key_ref: "provider/fast" },
      },
    },
  };
  const plan = planSettingsPatch({
    chat_providers: {
      active: "deepseek",
      system_prompt: "新提示",
      items: [
        { id: "opencode", name: "OpenCode Go（订阅）", base_url: "https://opencode.ai/zen/go/v1", model: "m1" },
        { id: "deepseek", name: "deepseek", base_url: "https://api.deepseek.com/v2", model: "m2-new" },
      ],
    },
  }, { global, slot: {}, effective: global });
  assert.equal(getPath(plan.globalPatch, "chat.active_provider"), "deepseek");
  assert.equal(getPath(plan.globalPatch, "chat.auto_route"), false);
  assert.equal(getPath(plan.globalPatch, "chat.default_system_prompt"), "新提示");
  // 清单里没出现的 fast 即删除；tier 这类未展示字段原样保留。
  assert.deepEqual(Object.keys(plan.globalPatch.chat.providers).sort(), ["deepseek", "opencode"]);
  assert.equal(plan.globalPatch.chat.providers.deepseek.base_url, "https://api.deepseek.com/v2");
  assert.equal(plan.globalPatch.chat.providers.deepseek.model, "m2-new");
  assert.equal(plan.globalPatch.chat.providers.opencode.tier, "standard");
  assert.deepEqual(plan.replacePaths, ["chat.providers"]);
  assert.deepEqual(plan.rejected, []);
});

test("写计划：模型档位 standard / fast 落盘，未知档位退回标准档", () => {
  const global = {
    chat: {
      auto_route: false,
      active_provider: "a",
      providers: { a: { name: "a", base_url: "https://x/v1", model: "m", api_key_ref: "provider/a" } },
    },
  };
  const plan = planSettingsPatch({
    chat_providers: {
      active: "a",
      items: [
        { id: "a", name: "a", base_url: "https://x/v1", model: "m", tier: "fast" },
        { id: "b", name: "b", base_url: "https://y/v1", model: "m2", tier: "狂暴" },
      ],
    },
  }, { global, slot: {}, effective: global });
  assert.equal(plan.globalPatch.chat.providers.a.tier, "fast");
  assert.equal(plan.globalPatch.chat.providers.b.tier, "standard");
});

test("写计划：模型清单空或坏结构拒绝，坏父结构也拒绝", () => {
  const global = { chat: { providers: { a: { name: "A" } } } };
  const empty = planSettingsPatch({ chat_providers: { active: "a", items: [] } }, { global, slot: {} });
  assert.ok(empty.rejected.some((r) => r.key === "chat_providers"));
  assert.equal(empty.globalPatch.chat, undefined);
  const broken = planSettingsPatch({ chat_providers: "不是 JSON" }, { global, slot: {} });
  assert.ok(broken.rejected.some((r) => r.key === "chat_providers"));
  const bad = planSettingsPatch(
    { "context_menu_appearance.theme": "dark" },
    { global: { context_menu_appearance: [] }, slot: {} },
  );
  assert.equal(bad.globalPatch.context_menu_appearance, undefined);
  assert.ok(bad.rejected.some((r) => r.key === "context_menu_appearance.theme"));
});

test("写计划：密钥不落盘，未知键拒绝，人设合成 map", () => {
  const plan = planSettingsPatch({
    voice_chime_doubao_api_key: "sk-secret",
    totally_unknown_key: 1,
    pet_persona_overrides: "嘴甜心坏",
    persona_target: "shenshen",
  }, { global: { pet_persona_overrides: { "whale-maid-gpt": "保留" } }, slot: {}, current: "shenshen" });
  assert.equal(plan.skipped.length, 1);
  assert.ok(plan.rejected.some((r) => r.key === "totally_unknown_key"));
  assert.deepEqual(plan.globalPatch.pet_persona_overrides, {
    "whale-maid-gpt": "保留", shenshen: "嘴甜心坏",
  });
  assert.equal(JSON.stringify(plan).includes("sk-secret"), false);
});

test("写计划：只切编辑对象不清空任何人设", () => {
  const plan = planSettingsPatch({ persona_target: "whale-maid-gpt" }, {
    global: { pet_persona_overrides: { shenshen: "原文" } }, slot: {}, current: "shenshen",
  });
  assert.equal(plan.globalPatch.pet_persona_overrides, undefined);
});

test("mergeDeep 保留兄弟键", () => {
  const out = mergeDeep(
    { chat: { enabled: true, providers: { a: { model: "old" } } }, scale: 0.72 },
    { chat: { providers: { a: { model: "new" } } } },
  );
  assert.equal(out.chat.enabled, true);
  assert.equal(out.chat.providers.a.model, "new");
  assert.equal(out.scale, 0.72);
  const obj = {};
  assert.equal(setPath(obj, "a.b.c", 1), true);
  assert.equal(getPath(obj, "a.b.c"), 1);
  assert.equal(setPath({ a: [] }, "a.b", 1), false);
});

test("buildCatalogState 带全量目录与 UI 口径当前值", () => {
  const home = makeTemp();
  writeFileSync(path.join(home, "config.json"), JSON.stringify({
    pet_opacity: 0.5,
    click_sound_volume: 0.2,
    character: "shenshen",
    context_menu_layout: null,
    feature_activation: { version: 1, enabled: ["chat"] },
  }));
  const s = buildCatalogState({ petHome: home, pluginsRoot: makeTemp() });
  assert.equal(s.catalog.domains.length, 9);
  assert.equal(s.catalogPrefs.pet_opacity, 50);
  assert.equal(s.catalogPrefs.click_sound_volume, 20);
  assert.equal(s.catalogPrefs.context_menu_layout.length, 34);
  // 功能域已从面板移除，prefs 里不再有 feature_activation（写在盘上不受影响）。
  assert.equal(s.catalogPrefs.feature_activation, undefined);
});

test("模型清单来自 chat.providers，自动路由 / 手选口径与客户端一致", () => {
  const home = makeTemp();
  const providers = {
    opencode: { name: "OpenCode Go（订阅）", model: "deepseek-v4.1-flash", base_url: "https://opencode.ai/zen/go/v1", enabled: true },
    deepseek: { name: "deepseek", model: "deepseek-v4-flash", base_url: "https://api.deepseek.com/v1", enabled: false },
    "deepseek-2": { name: "fast", model: "deepseek-v4-flash", base_url: "https://api.deepseek.com/v1", enabled: false, tier: "fast" },
  };
  const file = path.join(home, "config.json");
  writeFileSync(file, JSON.stringify({ chat: { auto_route: true, active_provider: "custom", providers } }));
  const auto = buildCatalogState({ petHome: home, pluginsRoot: makeTemp() });
  assert.equal(auto.modelOptions.length, 3);
  assert.equal(auto.modelOptions[0].name, "OpenCode Go（订阅）");
  assert.equal(auto.modelOptions[2].tier, "fast");
  assert.equal(auto.chatAutoRoute, true);
  assert.equal(auto.providerEditor.active, "opencode");
  assert.deepEqual(auto.providerEditor.items.map((i) => i.id), ["opencode", "deepseek", "deepseek-2"]);
  assert.equal(auto.providerEditor.items[0].name, "OpenCode Go（订阅）");
  assert.equal(auto.providerEditor.items[0].hasKey, false);
  assert.equal(auto.catalogPrefs.chat_providers.items.length, 3);

  const cfg = JSON.parse(readFileSync(file, "utf8"));
  cfg.chat.auto_route = false;
  cfg.chat.active_provider = "deepseek";
  writeFileSync(file, JSON.stringify(cfg));
  const manual = buildCatalogState({ petHome: home, pluginsRoot: makeTemp() });
  assert.equal(manual.chatAutoRoute, false);
  assert.equal(manual.providerEditor.active, "deepseek");
});

test("盘上 active_provider 无效时，模型页按真实在用的卡展示", () => {
  const global = {
    chat: {
      auto_route: true,
      active_provider: "custom",
      providers: {
        opencode: { name: "OpenCode Go（订阅）", base_url: "https://opencode.ai/zen/go/v1", enabled: true },
        deepseek: { name: "deepseek", base_url: "https://api.deepseek.com/v1", enabled: false },
      },
    },
  };
  const home = makeTemp();
  writeFileSync(path.join(home, "config.json"), JSON.stringify(global));
  const s = buildCatalogState({ petHome: home, pluginsRoot: makeTemp() });
  assert.equal(s.providerEditor.active, "opencode");
  const first = s.providerEditor.items.find((i) => i.id === "opencode");
  assert.equal(first.name, "OpenCode Go（订阅）");
  assert.equal(first.base_url, "https://opencode.ai/zen/go/v1");
});

test("人设弹框：空文本删除覆盖回落出厂，其它角色不受影响", () => {
  const plan = planSettingsPatch({
    persona_target: "whale-maid-extra",
    pet_persona_overrides: "",
  }, {
    global: { pet_persona_overrides: { shenshen: "原文", "whale-maid-extra": "自定义" } },
    slot: {}, current: "shenshen",
  });
  assert.deepEqual(plan.globalPatch.pet_persona_overrides, { shenshen: "原文" });
  assert.equal(plan.rejected.length, 0);
  assert.ok(plan.written.includes("pet_persona_overrides"));
});

// ---------------------------------------------------------------- 目录复合控件

test("复合控件字段必须自带 k：漏了 k 面板会退回内置模板并覆盖用户数据", () => {
  const compound = [];
  for (const d of CATALOG.domains) {
    for (const tab of d.tabs) {
      for (const g of tab.groups || []) {
        for (const f of g.fields || []) {
          if (!f || !["menu", "features", "packs", "providers", "list", "models"].includes(f.t)) continue;
          compound.push(f);
        }
      }
    }
  }
  assert.ok(compound.length >= 4, "复合控件数量异常");
  for (const f of compound) {
    // 前端 fieldValue() 只按 f.k 取 catalogPrefs；复合控件没 k 就拿到 undefined，
    // 菜单会退回插件内置模板（保存即把用户布局覆盖成默认菜单），功能页会全关。
    assert.equal(typeof f.k, "string", "复合控件缺 k: " + JSON.stringify(f).slice(0, 80));
  }
  const keys = new Set(CATALOG_FIELDS.map((f) => f.key));
  // 功能域整域移除后只剩菜单复合控件还在面板里；feature_activation 不该再被登记。
  for (const key of ["context_menu_layout"]) {
    assert.ok(keys.has(key), "collectFields 少了 " + key);
  }
  assert.ok(!keys.has("feature_activation"));
});
