/**
 * 任务中心的**唯一一份** markup。插件（lib/client.js）和原型
 * （docs/prototypes/task-center.html）都调它，所以两边不可能长得不一样。
 *
 * 纯字符串生成：不碰 DOM、不绑事件，可在 node 里直接断言输出。
 * 事件靠 data-view / data-act / data-tab / data-id 委托，宿主那一侧实现。
 *
 * 视觉口径（对齐成熟列表类产品，不是自创）：
 * - 13px 正文、11.5px 元数据、列表层只留必要信息，细节留到选中之后（Linear 的列表口径）；
 * - 状态不只靠颜色 —— 点是形状 + 右侧文字标签（“不要只用颜色表达状态”）；
 * - 数字一律 tabular-nums，只有 id / 路径用等宽；
 * - 不动画、不发光、不用彩色药丸堆信息。
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.LajiTaskView = api;
})(typeof self !== "undefined" ? self : this, function () {
  function esc(s) {
    return String(s === null || s === undefined ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }

  /** 状态短标签：中文两字，右侧固定宽度对齐，扫一列就认得出来。 */
  const STATUS_LABEL = {
    executing: "在做",
    created: "排队",
    awaiting: "等你",
    finished: "完成",
    failed: "失败",
    cancelled: "取消",
  };

  const PHASE_ORDER = ["waiting", "running", "queued", "closed", "unknown"];
  const PHASE_LABEL = {
    waiting: "等你决定",
    running: "在做",
    queued: "排队",
    closed: "已收口",
    unknown: "状态未知",
  };

  function shortStatus(t) {
    return STATUS_LABEL[t.status] || t.status || "未知";
  }

  function railItem(id, label, n, extra) {
    return (
      '<button type="button" class="tc-rail-item" data-view="' + esc(id) + '">' +
      '<span class="tc-rail-name">' + esc(label) + "</span>" +
      '<span class="tc-num' + (extra ? " is-alert" : "") + '">' + (n === undefined ? "" : n) + "</span></button>"
    );
  }

  function head(S, state, c) {
    c = c || {};
    return (
      '<header class="tc-head">' +
        '<div class="tc-brand"><h1>任务中心</h1>' +
          '<span class="tc-chip" title="在做 + 等你">' + (c.running || 0) + " 在做 · " + (c.waiting || 0) + " 等你</span>" +
        "</div>" +
        '<div class="tc-tools">' +
          '<label class="tc-search"><input data-ref="q" type="search" spellcheck="false" ' +
            'placeholder="搜索任务 / 提示词 / 工作区" value="' + esc(state.q) + '" />' +
            '<span class="tc-kbd">/</span></label>' +
          '<select class="tc-select" data-ref="sort" aria-label="排序">' +
            '<option value="attention"' + (state.sort === "attention" ? " selected" : "") + ">注意力</option>" +
            '<option value="recent"' + (state.sort === "recent" ? " selected" : "") + ">最近活动</option>" +
            '<option value="oldest"' + (state.sort === "oldest" ? " selected" : "") + ">创建时间</option>" +
            '<option value="longest"' + (state.sort === "longest" ? " selected" : "") + ">耗时</option>" +
          "</select>" +
          '<button type="button" class="tc-btn" data-act="only" aria-pressed="' + String(!!state.onlyAttention) + '">只看等你</button>' +
          '<button type="button" class="tc-btn" data-act="refresh" title="重新读取（R）">刷新</button>' +
          '<button type="button" class="tc-btn tc-btn-icon" data-act="close" title="关闭（Esc）">✕</button>' +
        "</div>" +
      "</header>"
    );
  }

  function rail(S, state, tasks, c) {
    let h = '<nav class="tc-rail"><div class="tc-rail-label">状态</div>';
    h += railItem("active", "进行中", c.total - c.closed);
    h += railItem("waiting", "等你决定", c.waiting, c.waiting > 0);
    h += railItem("running", "在做", c.running);
    h += railItem("queued", "排队", c.queued);
    h += railItem("closed", "已收口", c.closed);
    h += railItem("all", "全部", c.total);
    h += '<div class="tc-rail-label">工作区</div>';
    const groups = S.groupByWorkspace(tasks);
    if (!groups.length) h += '<div class="tc-rail-empty">没有工作区</div>';
    for (const g of groups) {
      h += railItem(g.workspace, S.shortWorkspace(g.workspace), g.items.length);
    }
    return h + "</nav>";
  }

  function row(S, t, selected) {
    const why = t.attention && t.attention.why ? t.attention.why : "";
    return (
      '<div class="tc-row" data-id="' + esc(t.id) + '" role="option" tabindex="-1" aria-selected="' +
        String(selected) + '">' +
        '<span class="tc-state" data-phase="' + t.phase + '" title="' + esc(PHASE_LABEL[t.phase]) + '"></span>' +
        '<span class="tc-main">' +
          '<span class="tc-title">' + esc(t.title) + "</span>" +
          (why ? '<span class="tc-inline">· ' + esc(why) + "</span>"
               : t.prompt ? '<span class="tc-inline">' + esc(t.prompt) + "</span>" : "") +
        "</span>" +
        '<span class="tc-cell ws" title="' + esc(t.workspaceRoot) + '">' + esc(S.shortWorkspace(t.workspaceRoot)) + "</span>" +
        '<span class="tc-cell num">' + S.fmtDuration(t.ageMs) + "</span>" +
        '<span class="tc-cell num">' + t.turnCount + "</span>" +
        '<span class="tc-cell st">' + esc(shortStatus(t)) + "</span>" +
      "</div>"
    );
  }

  function cols() {
    return (
      '<div class="tc-cols"><span></span><span>任务</span><span>工作区</span>' +
      '<span class="r">耗时</span><span class="r">轮次</span><span class="r">状态</span></div>'
    );
  }

  function list(S, state, tasks) {
    if (!tasks.length) {
      return (
        '<div class="tc-empty"><p class="tc-empty-t">' + esc(state.emptyTitle || "这里没有任务") + "</p>" +
        '<p class="tc-empty-d">' + esc(state.emptyHint || "没有在跑的任务时这一栏就是空的 —— 不塞占位行。") + "</p></div>"
      );
    }
    const buckets = new Map(PHASE_ORDER.map((p) => [p, []]));
    for (const t of tasks) {
      if (!buckets.has(t.phase)) buckets.set(t.phase, []);
      buckets.get(t.phase).push(t);
    }
    let h = "";
    for (const phase of buckets.keys()) {
      const items = buckets.get(phase);
      if (!items.length) continue;
      h +=
        '<section class="tc-group">' +
          '<div class="tc-group-head"><span class="tc-state" data-phase="' + phase + '"></span>' +
            "<span>" + esc(PHASE_LABEL[phase] || phase) + "</span>" +
            '<span class="tc-num">' + items.length + "</span></div>" +
          items.map((t) => row(S, t, t.id === state.selectedId)).join("") +
        "</section>";
    }
    return cols() + '<div class="tc-groups">' + h + "</div>";
  }

  function note(text) {
    return '<p class="tc-note">' + esc(text) + "</p>";
  }

  function section(title, body) {
    return '<section class="tc-sec"><h3>' + esc(title) + "</h3>" + body + "</section>";
  }

  function paneOverview(S, t) {
    const d = t.detail || {};
    const rows = [
      ["状态", (PHASE_LABEL[t.phase] || t.phase) + " · " + (t.status || "?")],
      ["工作区", t.workspaceRoot || "—"],
      ["模型", t.modelId || "默认模型（daemon 配置）"],
      ["批准模式", t.mode || "未知"],
      ["耗时", S.fmtDuration(t.ageMs)],
      ["轮次", String(t.turnCount)],
      ["最近活动", S.fmtAgo(t.latestActivityAtMs, Date.now())],
      ["run", t.runId],
    ];
    let h = '<dl class="tc-kv">' + rows
      .map((r) => '<dt>' + esc(r[0]) + '</dt><dd' + (r[0] === "run" || r[0] === "工作区" ? ' class="mono"' : "") + ">" + esc(r[1]) + "</dd>")
      .join("") + "</dl>";
    h += section("提示词", '<p class="tc-para">' + esc(t.prompt || "（没有记录）") + "</p>");
    if (d.progress) {
      const pct = Math.round((d.progress.done / Math.max(1, d.progress.total)) * 100);
      h += section("进度",
        '<div class="tc-progress"><div class="tc-progress-bar"><i style="width:' + pct + '%"></i></div>' +
        '<span class="tc-num">' + d.progress.done + " / " + d.progress.total + "</span></div>");
    } else {
      h += section("进度", note("没有 todo 事件，就不显示百分比 —— 不猜。"));
    }
    h += '<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-act="open">打开会话</button>' +
      '<button type="button" class="tc-btn" data-act="dismiss">从侧栏移除</button>' +
      '<button type="button" class="tc-btn" data-act="cancel" disabled title="要 daemon 的取消接口（设计文档 C3）">终止</button></div>';
    return h;
  }

  function paneTimeline(S, t) {
    const evs = (t.detail && t.detail.timeline) || [];
    if (!evs.length) return note("时间线要逐条 RunEvent（ToolCallStarted / TodosUpdated / FilesChanged…）。宿主现在只给 run 列表，等 C0 事件桥。");
    return '<ol class="tc-tl">' + evs.map((e) =>
      '<li class="tc-tl-item" data-kind="' + esc(e.cls || "info") + '">' +
        '<span class="tc-tl-at">' + esc(e.at || "") + "</span>" +
        '<span class="tc-tl-text">' + esc(e.text) + "</span></li>"
    ).join("") + "</ol>";
  }

  function paneChanges(S, t, tasks) {
    const fs = (t.detail && t.detail.changes) || [];
    if (!fs.length) return note("FilesChanged 只给路径与行数、没有 hunk 区间，所以冲突判定只能到 L0/L1（同路径 / 时间窗重叠）。");
    const mine = fs.map((f) => f.path);
    const clashes = [];
    for (const other of tasks) {
      if (other.id === t.id) continue;
      const theirs = ((other.detail && other.detail.changes) || []).map((f) => f.path);
      const hit = theirs.filter((p) => mine.includes(p));
      if (hit.length) clashes.push({ other, hit });
    }
    let h = '<ul class="tc-files">' + fs.map((f) =>
      '<li><span class="tc-file">' + esc(f.path) + '</span>' +
      '<span class="tc-diff"><i class="add">+' + f.added + '</i><i class="del">-' + f.removed + "</i></span></li>"
    ).join("") + "</ul>";
    if (clashes.length) {
      h += section("与其它任务改同一文件", clashes.map((c) =>
        '<p class="tc-clash">' + esc(c.other.title) + '：<span class="mono">' + esc(c.hit.join(", ")) + "</span></p>"
      ).join(""));
    }
    return h;
  }

  function paneCapsules(S, t) {
    const caps = (t.detail && t.detail.capsules) || [];
    if (!caps.length) return note("胶囊把这次尝试的结论（带失效条件）沉淀下来给别的任务注入，属于 C1 阶段。");
    return caps.map((k) =>
      '<article class="tc-cap' + (k.live ? "" : " is-dead") + '">' +
        '<div class="tc-cap-h"><span class="tc-kind" data-kind="' + esc(k.kind) + '">' + esc(k.kind) + "</span>" +
        (k.live ? '<span class="tc-cap-state">生效中</span>'
               : '<span class="tc-cap-state" data-dead="1">已失效 · ' + esc(k.dead || "") + "</span>") + "</div>" +
        '<p class="tc-cap-b">' + esc(k.body) + "</p>" +
        '<div class="tc-cap-f"><span class="mono">' + esc(k.refs) + '</span>' +
        '<span class="tc-cap-inv">失效：' + esc(k.invalidWhen) + "</span></div></article>"
    ).join("");
  }

  function paneApproval(S, t) {
    if (!t.attention) return note("这个任务现在不需要你介入。");
    return '<div class="tc-ask"><p class="tc-ask-w">' + esc(t.attention.why) + "</p>" +
      '<p class="tc-ask-m">决定之后任务才会继续。批准动作走会话自己的确认 —— 插件不代办、也不伪造一条批准事件。</p>' +
      '<div class="tc-actions"><button type="button" class="tc-btn tc-btn-primary" data-act="open">到上下文里决定</button>' +
      '<button type="button" class="tc-btn" data-act="dismiss">先移开</button></div></div>';
  }

  const TABS = [
    ["overview", "概览"], ["timeline", "时间线"], ["changes", "改动"],
    ["capsules", "胶囊"], ["approval", "等你"],
  ];

  function detail(S, state, tasks) {
    const t = tasks.find((x) => x.id === state.selectedId);
    if (!t) {
      return '<div class="tc-empty tc-empty-detail"><p class="tc-empty-t">选一个任务</p>' +
        '<p class="tc-empty-d">概览、时间线、改动、胶囊、等你什么 —— 都在这里展开。</p></div>';
    }
    const body = state.tab === "timeline" ? paneTimeline(S, t)
      : state.tab === "changes" ? paneChanges(S, t, tasks)
      : state.tab === "capsules" ? paneCapsules(S, t)
      : state.tab === "approval" ? paneApproval(S, t)
      : paneOverview(S, t);
    const meta = [t.modelId || "默认模型", t.mode || "模式未知", S.fmtDuration(t.ageMs), t.turnCount + " 轮"];
    return '<div class="tc-dhead">' +
        '<div class="tc-crumb">' + esc(S.shortWorkspace(t.workspaceRoot)) + ' <span>/</span> <span class="mono">' + esc(t.runId) + "</span></div>" +
        '<h2>' + esc(t.title) + "</h2>" +
        '<div class="tc-dmeta">' + meta.map((m) => "<span>" + esc(m) + "</span>").join("") + "</div>" +
      '</div><div class="tc-tabs" role="tablist">' +
        TABS.map((p) => {
          const badge = p[0] === "approval" && t.attention ? '<i class="tc-tab-dot"></i>' : "";
          return '<button type="button" role="tab" data-tab="' + p[0] + '" aria-selected="' + String(state.tab === p[0]) + '">' + p[1] + badge + "</button>";
        }).join("") +
      '</div><div class="tc-dbody">' + body + "</div>";
  }

  function foot(S, state, c, opts) {
    return '<footer class="tc-foot"><span class="tc-foot-src">' + esc(opts.source || "") + "</span>" +
      '<span class="tc-foot-grow"></span>' +
      '<span class="tc-hints">' +
        "J/K 移动 · / 搜索 · R 刷新 · Esc 返回" +
      "</span></footer>";
  }

  /**
   * 整页 markup。`opts.visible` 是已经筛/排好的任务（列表区用它），
   * `tasks` 是全集（计数、分组、详情共用）。
   */
  function render(S, tasks, state, opts) {
    const o = opts || {};
    const c = S.counts(tasks);
    const visible = o.visible || tasks;
    const selected = tasks.some((t) => t.id === state.selectedId);
    return '<div class="tc-root' + (selected ? "" : " is-nodetail") + '">' +
      head(S, state, c) +
      '<div class="tc-body">' +
        rail(S, state, tasks, c) +
        '<main class="tc-listpane" data-ref="rows">' + list(S, state, visible) + "</main>" +
        '<aside class="tc-detailpane">' + detail(S, state, tasks) + "</aside>" +
      "</div>" +
      foot(S, state, c, o) + "</div>";
  }


  return { esc, head, rail, list, detail, foot, render, STATUS_LABEL, PHASE_LABEL, shortStatus };
});
