/**
 * 任务中心的纯逻辑层：不碰 DOM、不碰网络，可在 node 里单测。
 *
 * 输入是宿主给的 `RunListEntry[]`（apps/laji-agent/src/shared/run-list.ts:18），
 * 输出是界面直接能画的任务行。所有"猜"的地方都留空并标出原因 —— 宁可不显示，也不编。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LajiTaskStore = api;
})(typeof self !== "undefined" ? self : this, function () {
  /** run-list.ts:16 —— 这三个状态才算"还活着"。 */
  const ACTIVE = { created: true, executing: true, awaiting: true };

  const PHASE = { created: "queued", executing: "running", awaiting: "waiting" };

  /** 状态 → 颜色点。认不出来的状态用 unknown，不硬塞进任何一类。 */
  function phaseOf(status) {
    if (PHASE[status]) return PHASE[status];
    if (ACTIVE[status]) return "running";
    if (status === undefined || status === null || status === "") return "unknown";
    return "closed";
  }

  const PHASE_TEXT = {
    waiting: "等你决定",
    running: "正在做",
    queued: "排队",
    closed: "已收口",
    unknown: "状态未知",
  };

  function keyOf(task) {
    return (task.workspaceRoot || "") + "\u0000" + task.runId;
  }

  const HOUR = 3600 * 1000;

  /** 0.995^小时 —— Generative Agents 的取用衰减（设计文档 §3）。 */
  function recency(atMs, now) {
    if (!atMs) return 0;
    return Math.pow(0.995, Math.max(0, now - atMs) / HOUR);
  }

  /**
   * 重要性：只用手上真有的信号，每一项都能对用户说清。
   * 返回 { score, reasons[] }，reasons 直接显示在行下面的灰字里。
   */
  function importance(task, now) {
    const reasons = [];
    let score = 0;
    if (task.phase === "waiting") {
      score += 0.5;
      reasons.push({ code: "waiting", text: "有人在等你" });
    }
    const waitedMin = task.sinceActivityMs / 60000;
    if (task.phase === "running" && waitedMin >= 30) {
      score += 0.2;
      reasons.push({ code: "stale", text: `已经 ${Math.floor(waitedMin)} 分钟没新动作` });
    }
    if (task.phase === "queued" && task.ageMs / 60000 >= 10) {
      score += 0.1;
      reasons.push({ code: "starved", text: "排队超过 10 分钟（并发名额满了）" });
    }
    if (task.attention && task.attention.kind === "approval") {
      score += 0.3;
      reasons.push({ code: "approval", text: "需要批准不可逆操作" });
    }
    return { score: Math.min(1, score), reasons };
  }

  /** 同分时的确定性扰动：ACT-R 的噪声项，防止某一行永远钉在第一位。 */
  function jitter(id) {
    let h = 0;
    for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 997;
    return (h % 100) / 1000;
  }

  function score(task, now) {
    const imp = importance(task, now);
    return 0.4 * recency(task.latestActivityAtMs || task.createdAtMs, now) + 0.6 * imp.score + jitter(task.id || task.runId);
  }

  /** 注意力列表：只放"必须由人看"的，附理由。没有理由的东西不上榜。 */
  function attentionList(tasks, now) {
    return tasks
      .map((task) => {
        const imp = importance(task, now || Date.now());
        const reasons = imp.reasons.slice();
        if (task.attention && task.attention.why) reasons.unshift({ code: task.attention.kind || "attention", text: task.attention.why });
        if (reasons.length === 0) return null;
        return { task, reasons, score: imp.score + jitter(task.id || task.runId) };
      })
      .filter(Boolean)
      .sort((a, b) => b.score - a.score);
  }

  /**
   * 把 RunListEntry 归一成任务行。
   * 丢掉：草稿行（还没 CreateRun）、子 agent（属于父任务内部）、定时任务的 run
   * —— 三者与"人的一件事"不是同一层（见设计文档 §2）。
   */
  function normalizeRows(rows, opts) {
    const now = (opts && opts.now) || Date.now();
    const include = (opts && opts.include) || {};
    const out = [];
    for (const row of rows || []) {
      if (!row || !row.runId) continue;
      if (row.isDraft && !include.drafts) continue;
      if (row.subagent && !include.subagents) continue;
      if (row.scheduleJobId && !include.scheduled) continue;
      const createdAtMs = row.createdAtMs || now;
      const latestActivityAtMs = row.latestActivityAtMs || createdAtMs;
      out.push({
        id: `${row.workspaceRoot || ""}:${row.runId}`,
        runId: row.runId,
        workspaceRoot: row.workspaceRoot || "",
        title: row.title || row.prompt || "(未命名任务)",
        prompt: row.prompt || "",
        status: row.status,
        phase: phaseOf(row.status),
        modelId: row.modelId || null,
        mode: row.mode || null,
        turnCount: row.turnCount || 1,
        parentRunId: row.parentRunId || null,
        createdAtMs,
        latestActivityAtMs,
        ageMs: Math.max(0, now - createdAtMs),
        sinceActivityMs: Math.max(0, now - latestActivityAtMs),
        attention: null,
        /** 详情数据（时间线 / 改动 / 胶囊 / 进度）：宿主给了就用，没给就是 null —— 不编。 */
        detail: row.detail || null,
      });
    }
    return out;
  }

  /** 把插件事件（approval / questions / plan / error）贴到对应任务上。 */
  function attachEvents(tasks, events) {
    const byRun = new Map(tasks.map((t) => [t.runId, t]));
    for (const ev of events || []) {
      const t = byRun.get(ev.runId);
      if (!t) continue;
      const kind = ev.kind === "questions" ? "questions" : ev.kind;
      t.attention = {
        kind,
        why:
          kind === "approval"
            ? ev.title || "等你批准一个操作"
            : kind === "questions"
              ? ev.title || "等你回答一个问题"
              : kind === "plan"
                ? ev.title || "等你确认计划"
                : ev.message || "任务报错",
        atMs: ev.atMs || Date.now(),
      };
    }
    return tasks;
  }

  function matchesQuery(task, q) {
    if (!q) return true;
    const needle = q.trim().toLowerCase();
    if (!needle) return true;
    return (task.title + "\n" + task.prompt + "\n" + task.workspaceRoot).toLowerCase().includes(needle);
  }

  function filterTasks(tasks, f) {
    const o = f || {};
    return tasks.filter((t) => {
      if (o.view === "active" && t.phase === "closed") return false;
      if (o.view === "waiting" && t.phase !== "waiting") return false;
      if (o.view === "running" && t.phase !== "running") return false;
      if (o.view === "queued" && t.phase !== "queued") return false;
      if (o.view === "closed" && t.phase !== "closed") return false;
      if (o.workspace && t.workspaceRoot !== o.workspace) return false;
      if (o.status && t.status !== o.status) return false;
      if (o.onlyAttention && !t.attention) return false;
      return matchesQuery(t, o.q);
    });
  }

  function sortTasks(tasks, mode, now) {
    const arr = tasks.slice();
    if (mode === "oldest") arr.sort((a, b) => a.createdAtMs - b.createdAtMs);
    else if (mode === "longest") arr.sort((a, b) => b.ageMs - a.ageMs);
    else if (mode === "attention") arr.sort((a, b) => score(b, now) - score(a, now));
    else arr.sort((a, b) => (b.latestActivityAtMs || 0) - (a.latestActivityAtMs || 0));
    return arr;
  }

  function counts(tasks) {
    const c = { total: tasks.length, waiting: 0, running: 0, queued: 0, closed: 0 };
    for (const t of tasks) {
      if (c[t.phase] !== undefined) c[t.phase] += 1;
    }
    return c;
  }

  /** 按工作区聚集，工作区内的顺序保持传入顺序（调用方先排好）。 */
  function groupByWorkspace(tasks) {
    const map = new Map();
    for (const t of tasks) {
      const ws = t.workspaceRoot || "(未知工作区)";
      if (!map.has(ws)) map.set(ws, []);
      map.get(ws).push(t);
    }
    return Array.from(map, ([workspace, items]) => ({ workspace, items }));
  }

  function shortWorkspace(p) {
    if (!p) return "(未知)";
    const parts = p.replace(/\\/g, "/").replace(/\/+$/, "").split("/");
    const last = parts[parts.length - 1] || p;
    return last;
  }

  function fmtDuration(ms) {
    if (ms === null || ms === undefined || ms < 0) return "—";
    const s = Math.floor(ms / 1000);
    if (s < 60) return s + "s";
    const m = Math.floor(s / 60);
    if (m < 60) return m + "m" + (s % 60 ? String(s % 60).padStart(2, "0") + "s" : "");
    const h = Math.floor(m / 60);
    return h + "h" + String(m % 60).padStart(2, "0") + "m";
  }

  function fmtAgo(ms, now) {
    if (!ms) return "—";
    const d = Math.max(0, (now || Date.now()) - ms);
    if (d < 60 * 1000) return "刚刚";
    return fmtDuration(d) + "前";
  }

  return {
    ACTIVE,
    PHASE_TEXT,
    phaseOf,
    keyOf,
    recency,
    importance,
    score,
    attentionList,
    normalizeRows,
    attachEvents,
    filterTasks,
    sortTasks,
    counts,
    groupByWorkspace,
    shortWorkspace,
    fmtDuration,
    fmtAgo,
  };
});
