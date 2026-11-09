/**
 * view.js 的单测 —— markup 是纯字符串，所以不用浏览器就能断言。
 * 跑：node packs/plugins/laji-task-center/test/view.test.cjs
 */
const assert = require("node:assert/strict");
const S = require("../lib/store.js");
const V = require("../lib/view.js");
const FIX = require("./fixtures.js");

let pass = 0;
function t(name, fn) {
  fn();
  pass += 1;
  console.log("  ok  " + name);
}

const NOW = Date.now();
const tasks = S.attachEvents(S.normalizeRows(FIX.rows, { now: NOW }), FIX.events);
const state = { view: "all", q: "", sort: "attention", onlyAttention: false, selectedId: tasks[0].id, tab: "overview" };

t("整页渲染：三栏结构齐全，且只有一个 root", () => {
  const html = V.render(S, tasks, state, { visible: tasks, source: "test" });
  for (const cls of ["tc-root", "tc-head", "tc-rail", "tc-listpane", "tc-detailpane", "tc-foot"]) {
    assert.ok(html.includes(cls), "缺 " + cls);
  }
  assert.equal((html.match(/class="tc-root/g) || []).length, 1);
});

t("按阶段分组，等你决定排在最前", () => {
  const html = V.render(S, tasks, state, { visible: tasks });
  const heads = [...html.matchAll(/class="tc-group-head"[^>]*>[\s\S]*?<span>([^<]+)<\/span>/g)].map((m) => m[1]);
  assert.equal(heads[0], "等你决定");
  assert.ok(heads.includes("在做"));
  assert.equal(new Set(heads).size, heads.length, "同一阶段不能出现两次");
});

t("状态不只靠颜色：右列有文字标签", () => {
  const html = V.render(S, tasks, state, { visible: tasks });
  assert.ok(/class="tc-cell st">等你</.test(html));
  assert.ok(/class="tc-cell st">在做</.test(html));
});

t("数字列是 tabular 等宽，工作区只显示末段", () => {
  const row = V.list(S, state, tasks.filter((t) => t.runId === "r-e2e"));
  assert.ok(row.includes('class="tc-cell num"'));
  assert.ok(row.includes(">Nerve-agent<"));
  // 完整路径可以出现在 data-id / title 里，但可见文本只留末段
  const visibleText = row.replace(/<[^>]+>/g, " ");
  assert.ok(!visibleText.includes("D:\\workspace"), visibleText);
});

t("未选中时不渲染右栏占位以外的详情", () => {
  const html = V.render(S, tasks, { ...state, selectedId: null }, { visible: tasks });
  assert.ok(html.includes("is-nodetail"));
  assert.ok(html.includes("选一个任务"));
});

t("详情五个页签，等你页签有提示点", () => {
  const d = V.detail(S, state, tasks);
  for (const label of ["概览", "时间线", "改动", "胶囊", "等你"]) assert.ok(d.includes(label), "缺页签 " + label);
  assert.ok(d.includes("tc-tab-dot"), "有待批事件时应有提示点");
});

t("详情占位不留假数据：没有 todo 就写明不猜", () => {
  const noProgress = tasks.find((t) => t.runId === "r-webhook");
  const d = V.detail(S, { ...state, selectedId: noProgress.id }, tasks);
  assert.ok(d.includes("不猜"));
  assert.ok(!d.includes("tc-progress-bar"));
});

t("改动页能算出与其它任务改同一文件", () => {
  const e2e = tasks.find((t) => t.runId === "r-e2e");
  const fake = tasks.concat([{ ...e2e, id: "x", runId: "x", title: "另一个任务" }]);
  const d = V.detail(S, { ...state, selectedId: e2e.id, tab: "changes" }, fake);
  assert.ok(d.includes("与其它任务改同一文件"));
  assert.ok(d.includes("vitest.config.ts"));
});

t("胶囊失效态有明确标记", () => {
  const flaky = tasks.find((t) => t.runId === "r-flaky");
  const d = V.detail(S, { ...state, selectedId: flaky.id, tab: "capsules" }, tasks);
  assert.ok(d.includes("is-dead"));
  assert.ok(d.includes("已失效"));
});

t("空列表给的是解释，不是占位行", () => {
  const html = V.render(S, tasks, { ...state, selectedId: null }, { visible: [] });
  assert.ok(html.includes("这里没有任务"));
  assert.ok(!html.includes("tc-row"));
});

t("用户输入一律转义", () => {
  const evil = S.normalizeRows(
    [{ runId: "e", workspaceRoot: "/w", title: '<img src=x onerror="a">', prompt: "</span><script>", status: "executing" }],
    { now: NOW }
  );
  const html = V.render(S, evil, { ...state, selectedId: "x" }, { visible: evil });
  assert.ok(!html.includes("<img src=x"));
  assert.ok(!html.includes("<script>"));
  assert.ok(html.includes("&lt;img src=x"));
});

t("没有 undefined / NaN 漏进页面", () => {
  const html = V.render(S, tasks, state, { visible: tasks });
  assert.ok(!html.includes("undefined"), "出现了 undefined");
  assert.ok(!html.includes("NaN"), "出现了 NaN");
});

console.log("\n" + pass + " passed");
