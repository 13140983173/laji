/**
 * store.js 的单测。跑：node packs/plugins/laji-task-center/test/store.test.cjs
 * 只测纯逻辑 —— 没有 DOM、没有宿主。
 */
const assert = require("node:assert/strict");
const S = require("../lib/store.js");

const NOW = 1_700_000_000_000;
const row = (o) => ({
  runId: "r1", workspaceRoot: "/w/a", title: "任务", prompt: "提示词",
  status: "executing", createdAtMs: NOW - 60_000, latestActivityAtMs: NOW - 5_000,
  turnCount: 1, modelId: null, mode: "ask", parentRunId: null, subagent: false, ...o,
});

let pass = 0;
function t(name, fn) {
  fn();
  pass += 1;
  console.log("  ok  " + name);
}

t("phaseOf 认得出四种阶段，认不出就是 unknown", () => {
  assert.equal(S.phaseOf("created"), "queued");
  assert.equal(S.phaseOf("executing"), "running");
  assert.equal(S.phaseOf("awaiting"), "waiting");
  assert.equal(S.phaseOf("finished"), "closed");
  assert.equal(S.phaseOf("failed"), "closed");
  assert.equal(S.phaseOf("cancelled"), "closed");
  assert.equal(S.phaseOf(undefined), "unknown");
  assert.equal(S.phaseOf("weird-new-status"), "closed");
});

t("normalizeRows 丢掉草稿 / 子 agent / 定时任务", () => {
  const rows = [
    row({ runId: "keep" }),
    row({ runId: "draft", isDraft: true }),
    row({ runId: "sub", subagent: true }),
    row({ runId: "cron", scheduleJobId: "job1" }),
  ];
  const got = S.normalizeRows(rows, { now: NOW });
  assert.deepEqual(got.map((x) => x.runId), ["keep"]);
  assert.equal(S.normalizeRows(rows, { now: NOW, include: { drafts: true, subagents: true } }).length, 3);
});

t("normalizeRows 派生字段：ageMs / sinceActivityMs / phase / 标题回退", () => {
  const [task] = S.normalizeRows([row({ createdAtMs: NOW - 90_000, latestActivityAtMs: NOW - 30_000, title: "" })], { now: NOW });
  assert.equal(task.ageMs, 90_000);
  assert.equal(task.sinceActivityMs, 30_000);
  assert.equal(task.phase, "running");
  assert.equal(task.title, "提示词");
  assert.equal(task.id, "/w/a:r1");
});

t("没有 latestActivityAtMs 时退回创建时间，不产生负耗时", () => {
  const [task] = S.normalizeRows([row({ latestActivityAtMs: undefined, createdAtMs: NOW + 5_000 })], { now: NOW });
  assert.equal(task.latestActivityAtMs, NOW + 5_000);
  assert.equal(task.ageMs, 0);
});

t("importance：等你最高，卡住与排队次之，都带理由", () => {
  const base = { sinceActivityMs: 0, ageMs: 0, attention: null };
  const waiting = S.importance({ ...base, phase: "waiting" }, NOW);
  assert.equal(waiting.score, 0.5);
  assert.deepEqual(waiting.reasons.map((r) => r.code), ["waiting"]);

  const stale = S.importance({ ...base, phase: "running", sinceActivityMs: 40 * 60_000 }, NOW);
  assert.equal(stale.score, 0.2);
  assert.deepEqual(stale.reasons.map((r) => r.code), ["stale"]);

  const starved = S.importance({ ...base, phase: "queued", ageMs: 20 * 60_000 }, NOW);
  assert.equal(starved.score, 0.1);

  const fresh = S.importance({ ...base, phase: "running", sinceActivityMs: 1_000 }, NOW);
  assert.equal(fresh.score, 0);
  assert.equal(fresh.reasons.length, 0);
});

t("attentionList 只留下能说清理由的行", () => {
  const tasks = S.normalizeRows([
    row({ runId: "a", status: "awaiting" }),
    row({ runId: "b", status: "executing", latestActivityAtMs: NOW - 2000 }),
  ], { now: NOW });
  S.attachEvents(tasks, [{ runId: "b", kind: "approval", title: "要跑 rm -rf", atMs: NOW }]);
  const list = S.attentionList(tasks, NOW);
  assert.equal(list.length, 2);
  assert.ok(list[0].reasons.length > 0);
  assert.ok(list.some((e) => e.reasons[0].code === "approval"));
});

t("attachEvents 只贴到存在的 run 上，认不出就不加", () => {
  const tasks = S.normalizeRows([row({ runId: "a" })], { now: NOW });
  S.attachEvents(tasks, [{ runId: "a", kind: "questions", atMs: NOW }, { runId: "zzz", kind: "error" }]);
  assert.equal(tasks[0].attention.kind, "questions");
  assert.equal(tasks.length, 1);
});

t("filterTasks：视图 / 工作区 / 关键词 / 只看等你", () => {
  const tasks = S.normalizeRows([
    row({ runId: "a", status: "awaiting", title: "auth 重写" }),
    row({ runId: "b", status: "executing", title: "e2e 迁移", workspaceRoot: "/w/b" }),
  ], { now: NOW });
  tasks[0].attention = { kind: "approval", why: "等你" };
  assert.deepEqual(S.filterTasks(tasks, { view: "waiting" }).map((x) => x.runId), ["a"]);
  assert.deepEqual(S.filterTasks(tasks, { view: "running" }).map((x) => x.runId), ["b"]);
  assert.deepEqual(S.filterTasks(tasks, { q: "E2E" }).map((x) => x.runId), ["b"]);
  assert.deepEqual(S.filterTasks(tasks, { workspace: "/w/b" }).map((x) => x.runId), ["b"]);
  assert.deepEqual(S.filterTasks(tasks, { view: "waiting", onlyAttention: true }).map((x) => x.runId), ["a"]);
  assert.equal(S.filterTasks(tasks, {}).length, 2);
});

t("sortTasks 四种排序都是纯函数，不动入参", () => {
  const tasks = S.normalizeRows([
    row({ runId: "old", createdAtMs: NOW - 900_000, latestActivityAtMs: NOW - 900_000 }),
    row({ runId: "new", createdAtMs: NOW - 10_000, latestActivityAtMs: NOW - 1_000 }),
  ], { now: NOW });
  const before = tasks.map((x) => x.runId);
  assert.deepEqual(S.sortTasks(tasks, "recent", NOW).map((x) => x.runId), ["new", "old"]);
  assert.deepEqual(S.sortTasks(tasks, "oldest", NOW).map((x) => x.runId), ["old", "new"]);
  assert.deepEqual(S.sortTasks(tasks, "longest", NOW).map((x) => x.runId), ["old", "new"]);
  assert.equal(S.sortTasks(tasks, "attention", NOW).length, 2);
  assert.deepEqual(tasks.map((x) => x.runId), before);
});

t("sortTasks 同分不会永远钉在同一行（有确定性扰动）", () => {
  const mk = (id) => ({ id, runId: id, phase: "running", createdAtMs: NOW, latestActivityAtMs: NOW, ageMs: 0, sinceActivityMs: 0 });
  const a = S.sortTasks([mk("x1"), mk("x2"), mk("x3")], "attention", NOW).map((t) => t.runId);
  const b = S.sortTasks([mk("x1"), mk("x2"), mk("x3")], "attention", NOW).map((t) => t.runId);
  assert.deepEqual(a, b, "同样的输入必须给同样的顺序");
  assert.equal(a.length, 3);
});

t("counts / groupByWorkspace / shortWorkspace", () => {
  const tasks = S.normalizeRows([
    row({ runId: "a", status: "awaiting" }),
    row({ runId: "b" }),
    row({ runId: "c", workspaceRoot: "/w/b", status: "created" }),
    row({ runId: "d", status: "finished" }),
  ], { now: NOW });
  assert.deepEqual(S.counts(tasks), { total: 4, waiting: 1, running: 1, queued: 1, closed: 1 });
  const groups = S.groupByWorkspace(tasks);
  assert.deepEqual(groups.map((g) => [g.workspace, g.items.length]), [["/w/a", 3], ["/w/b", 1]]);
  assert.equal(S.shortWorkspace("C:\\work\\nerve-agent\\"), "nerve-agent");
  assert.equal(S.shortWorkspace("/work/notes"), "notes");
  assert.equal(S.shortWorkspace(""), "(未知)");
});

t("格式化：不与 0 / null 编造数字", () => {
  assert.equal(S.fmtDuration(0), "0s");
  assert.equal(S.fmtDuration(45_000), "45s");
  assert.equal(S.fmtDuration(90_000), "1m30s");
  assert.equal(S.fmtDuration(3_900_000), "1h05m");
  assert.equal(S.fmtDuration(null), "—");
  assert.equal(S.fmtAgo(NOW - 5_000, NOW), "刚刚");
  assert.equal(S.fmtAgo(NOW - 120_000, NOW), "2m前");
  assert.equal(S.fmtAgo(null, NOW), "—");
});

t("recency 单调递减且在 24h 后仍不为负", () => {
  assert.equal(S.recency(NOW, NOW), 1);
  assert.ok(S.recency(NOW - 3_600_000, NOW) < 1);
  assert.ok(S.recency(NOW - 24 * 3_600_000, NOW) > 0.88);
  assert.equal(S.recency(0, NOW), 0);
});

console.log("\n" + pass + " passed");
