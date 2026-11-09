/**
 * 预览用样本：形状与 `RunListEntry` 一致，额外带 `detail`（时间线 / 改动 / 胶囊 / 进度）。
 *
 * `detail` 是「C0 事件桥接上以后插件会拿到的东西」的样子 —— 现在真实宿主不给，
 * 所以插件在真机上这几个页签是空态；这里用它把设计意图画出来。
 */
(function () {
  var now = Date.now();
  var ago = function (m) { return now - m * 60000; };

  var rows = [
    {
      runId: "r-auth2", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "auth 重写：把 refresh 串行化", prompt: "重写 auth 的 token 刷新，避免并发 refresh 打出多个失效 token",
      status: "awaiting", createdAtMs: ago(134), latestActivityAtMs: ago(2), turnCount: 3,
      modelId: "claude-sonnet-4.6", mode: "ask",
      detail: {
        progress: { done: 4, total: 6 },
        timeline: [
          { at: "10:02:11", cls: "tool", text: "Read packages/laji-client-core/src/auth/refresh.ts" },
          { at: "10:03:40", cls: "tool", text: "Edit refresh.ts（+38 / -12）" },
          { at: "10:05:02", cls: "tool", text: "run: npm test -- auth → 11 passed" },
          { at: "10:06:18", cls: "wait", text: "请求批准：删除 node_modules 后重装依赖" },
        ],
        changes: [
          { path: "packages/laji-client-core/src/auth/refresh.ts", added: 38, removed: 12 },
          { path: "packages/laji-client-core/src/auth/refresh.test.ts", added: 61, removed: 0 },
        ],
        capsules: [
          { kind: "finding", body: "refresh 并发会打爆旧 token：加 singleflight 后必现消失", refs: "refresh.ts:64", invalidWhen: "refresh 队列换成 daemon 侧单写", live: true },
          { kind: "decision", body: "用 singleflight 而不是全局锁，锁会拖慢冷启动 300ms", refs: "试过 r-auth1", invalidWhen: "并发超过 50/s", live: true },
        ],
      },
    },
    {
      runId: "r-e2e", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "迁移 e2e 到 vitest", prompt: "把 jest 换成 vitest，保留 --watch 能力",
      status: "executing", createdAtMs: ago(401), latestActivityAtMs: ago(0.2), turnCount: 1,
      modelId: "claude-sonnet-4.6", mode: "observe",
      detail: {
        progress: { done: 2, total: 7 },
        timeline: [
          { at: "09:20:04", cls: "tool", text: "Bash: pnpm add -D vitest" },
          { at: "09:26:31", cls: "tool", text: "Edit vitest.config.ts（新建）" },
        ],
        changes: [{ path: "vitest.config.ts", added: 44, removed: 0 }, { path: "package.json", added: 3, removed: 8 }],
        capsules: [{ kind: "blocker", body: "jest 的 setupFiles 里有 3 个 CJS-only 桩，vitest 下要改成 ESM", refs: "test/setup.cjs", invalidWhen: "桩改成 ESM 之后", live: true }],
      },
    },
    {
      runId: "r-flicker", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "修复侧栏闪烁", prompt: "侧栏每 200ms 重渲染一次，滚动位置丢失",
      status: "executing", createdAtMs: ago(41), latestActivityAtMs: ago(0.1), turnCount: 1,
      modelId: "claude-sonnet-4.6", mode: "observe",
      detail: {
        timeline: [{ at: "10:31:02", cls: "tool", text: "Grep: runs:list → 3 处订阅" }],
        changes: [],
        capsules: [{ kind: "finding", body: "闪烁来自 runs:list 每秒一次的全量 setState，不是 CSS", refs: "sidebar.tsx:88", invalidWhen: "改成 diff 更新之后", live: true }],
      },
    },
    {
      runId: "r-webhook", workspaceRoot: "D:\\workspace\\pay-svc",
      title: "Stripe webhook 联调", prompt: "三条事件落到本地表，跑通签名校验",
      status: "created", createdAtMs: ago(900), latestActivityAtMs: ago(900), turnCount: 1,
      modelId: null, mode: "ask", detail: null,
    },
    {
      runId: "r-doc", workspaceRoot: "D:\\workspace\\notes",
      title: "整理 11 月复盘", prompt: "把 11 月复盘整理成一篇文档，附三次事故的时间线",
      status: "executing", createdAtMs: ago(600), latestActivityAtMs: ago(120), turnCount: 4,
      modelId: "gpt-5.1", mode: "observe", detail: { progress: { done: 1, total: 3 } },
    },
    {
      runId: "r-readme", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "收口 README 的任务栏一节", prompt: "写清任务栏的作用",
      status: "finished", createdAtMs: ago(1900), latestActivityAtMs: ago(1500), turnCount: 2,
      modelId: "claude-sonnet-4.6", mode: "ask",
      detail: {
        changes: [{ path: "README.md", added: 26, removed: 2 }],
        capsules: [{ kind: "decision", body: "任务栏只放「正在跑 + 等你」两类，已完成不进栏", refs: "README.md:41", invalidWhen: "用户要求保留最近 5 条", live: true }],
      },
    },
    {
      runId: "r-i18n", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "补 en 文案", prompt: "补英文文案",
      status: "failed", createdAtMs: ago(2600), latestActivityAtMs: ago(2500), turnCount: 1,
      modelId: "claude-sonnet-4.6", mode: "observe", detail: null,
    },
    {
      runId: "r-flaky", workspaceRoot: "D:\\workspace\\waf\\Nerve-agent",
      title: "定位 flaky 用例 settings.spec", prompt: "settings.spec 偶发超时",
      status: "finished", createdAtMs: ago(3200), latestActivityAtMs: ago(3100), turnCount: 5,
      modelId: "claude-sonnet-4.6", mode: "observe",
      detail: {
        capsules: [
          { kind: "finding", body: "超时来自 fake timer 与 await 混用，不是机器慢", refs: "settings.spec.ts:120", live: true },
          { kind: "finding", body: "旧的 retry:3 会把真失败也吞掉", refs: "jest.config.js:7", invalidWhen: "用例数超过 500", live: false, dead: "jest 已换 vitest" },
        ],
      },
    },
  ];

  var events = [
    { runId: "r-auth2", kind: "approval", title: "要删除 node_modules 并重装依赖（不可逆）", atMs: now - 120000 },
  ];

  var api = { rows: rows, events: events };
  if (typeof module === "object" && module.exports) module.exports = api;
  else (typeof self !== "undefined" ? self : window).LajiTaskFixtures = api;
})();
