/**
 * 任务中心 · 插件接线层（浏览器半侧）。
 *
 * 它只做四件事：拿数据、维护 state、把 markup 交给 lib/view.js、把点击/键盘转成 state。
 * 没有任何 HTML 字符串 —— 所以插件和原型不可能长得不一样（原型也引 view.js）。
 *
 * 数据来源：宿主给的 `ctx.runs.*`（转发到已有 IPC）。插件不连 daemon、不持凭据。
 */
(function () {
  var PLUGIN_ID = "com.nerve.task-center";
  var STYLE_ID = "tc-style";
  var BASE = new URL("./", import.meta.url);

  window.__ModuleLoader__.load({
    id: PLUGIN_ID,
    factory: function () {
      var module = { exports: {} };
      var api = {};

      var S = null;
      var V = null;
      var refs = {};
      var ctxRuns = null;
      var ctxEvents = null;
      var handle = null;
      var timer = 0;
      var offEvents = null;
      var initPromise = null;

      var state = {
        tasks: [],
        view: "active",
        q: "",
        sort: "attention",
        onlyAttention: false,
        selectedId: null,
        tab: "overview",
        loaded: false,
        error: "",
      };

      function injectStyle() {
        if (document.getElementById(STYLE_ID)) return;
        var link = document.createElement("link");
        link.id = STYLE_ID;
        link.rel = "stylesheet";
        link.href = new URL("panel.css", BASE).href;
        document.head.appendChild(link);
      }

      async function loadModules() {
        if (!S) {
          await import(new URL("store.js", BASE).href);
          S = window.LajiTaskStore;
        }
        if (!V) {
          await import(new URL("view.js", BASE).href);
          V = window.LajiTaskView;
        }
      }

      function visibleTasks() {
        var known = { active: 1, waiting: 1, running: 1, queued: 1, closed: 1, all: 1 };
        var byView = known[state.view] ? (state.view === "all" ? "" : state.view) : "";
        var list = S.filterTasks(state.tasks, {
          view: byView,
          q: state.q,
          onlyAttention: state.onlyAttention,
        });
        if (!known[state.view]) {
          list = list.filter(function (t) { return t.workspaceRoot === state.view; });
        }
        return S.sortTasks(list, state.sort, Date.now());
      }

      function currentTask() {
        for (var i = 0; i < state.tasks.length; i++) {
          if (state.tasks[i].id === state.selectedId) return state.tasks[i];
        }
        return null;
      }

      function opts() {
        return {
          visible: visibleTasks(),
          source: state.error ? "读取失败：" + state.error : ctxEvents ? "事件桥已连接" : "仅轮询（3s）",
        };
      }

      function cacheRefs() {
        refs.root = document.querySelector(".tc-root");
        if (!refs.root) return;
        refs.q = refs.root.querySelector('[data-ref="q"]');
        refs.sort = refs.root.querySelector('[data-ref="sort"]');
        refs.rows = refs.root.querySelector('[data-ref="rows"]');
        refs.detail = refs.root.querySelector(".tc-detailpane");
      }

      /** 整页重画：切换视图、改排序、刷新数据时用。 */
      function paintAll() {
        if (!S || !V) return;
        var existing = document.querySelector(".tc-root");
        var embedded = existing ? existing.classList.contains("is-embedded") : false;
        var host = existing ? existing.parentNode : document.body;
        var keepDisplay = existing ? existing.style.display : "";
        var shell = document.createElement("div");
        shell.innerHTML = V.render(S, state.tasks, state, opts());
        var next = shell.firstElementChild;
        if (existing) existing.replaceWith(next);
        else host.appendChild(next);
        if (embedded) next.classList.add("is-embedded");
        next.style.display = keepDisplay;
        cacheRefs();
        scrollToSelection();
        syncBadge();
      }

      /** 只重画列表区和详情：打字、选中、切页签时用（不打断输入焦点）。 */
      function paintList() {
        if (!V) return;
        var full = V.render(S, state.tasks, state, opts());
        var pick = function (sel) {
          var tpl = document.createElement("div");
          tpl.innerHTML = full;
          return tpl.querySelector(sel);
        };
        var rows = pick('[data-ref="rows"]');
        var detail = pick(".tc-detailpane");
        if (refs.rows && rows) refs.rows.innerHTML = rows.innerHTML;
        if (refs.detail && detail) refs.detail.innerHTML = detail.innerHTML;
        var hasSel = !!currentTask();
        if (refs.root) refs.root.classList.toggle("is-nodetail", !hasSel);
        syncBadge();
      }

      function scrollToSelection() {
        if (!refs.rows || !state.selectedId) return;
        var row = refs.rows.querySelector('[data-id="' + state.selectedId.replace(/"/g, '\\"') + '"]');
        if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
      }

      function syncBadge() {
        if (handle && handle.setBadge) handle.setBadge(S.counts(state.tasks).waiting);
      }

      function recentEvents() {
        try {
          return (ctxEvents && typeof ctxEvents.recent === "function" && ctxEvents.recent()) || [];
        } catch (e) {
          return [];
        }
      }

      async function refresh() {
        try {
          var rows = ctxRuns && typeof ctxRuns.list === "function" ? await ctxRuns.list() : [];
          state.tasks = S.attachEvents(S.normalizeRows(rows, { now: Date.now() }), recentEvents());
          state.error = "";
        } catch (err) {
          state.tasks = [];
          state.error = String((err && err.message) || err);
        }
        state.loaded = true;
        if (!currentTask()) {
          var first = visibleTasks()[0];
          state.selectedId = first ? first.id : null;
          state.tab = "overview";
        }
        paintAll();
      }

      function selectBy(delta) {
        var list = visibleTasks();
        if (!list.length) return;
        var i = -1;
        for (var k = 0; k < list.length; k++) if (list[k].id === state.selectedId) i = k;
        var next = Math.max(0, Math.min(list.length - 1, (i === -1 ? 0 : i) + delta));
        state.selectedId = list[next].id;
        state.tab = "overview";
        paintList();
        scrollToSelection();
      }

      function onClick(e) {
        var nav = e.target.closest("[data-view]");
        if (nav) {
          state.view = nav.dataset.view;
          state.selectedId = null;
          return void refresh();
        }
        var tab = e.target.closest("[data-tab]");
        if (tab) {
          state.tab = tab.dataset.tab;
          return paintList();
        }
        var row = e.target.closest(".tc-row");
        if (row) {
          state.selectedId = row.dataset.id;
          state.tab = "overview";
          paintList();
          scrollToSelection();
          return;
        }
        var act = e.target.closest("[data-act]");
        if (!act) return;
        var a = act.dataset.act;
        if (a === "refresh") return void refresh();
        if (a === "close") return closePanel();
        if (a === "only") {
          state.onlyAttention = !state.onlyAttention;
          paintAll();
          return;
        }
        var t = currentTask();
        if (!t) return;
        if (a === "open") {
          if (ctxRuns && ctxRuns.open) ctxRuns.open({ runId: t.runId, workspaceRoot: t.workspaceRoot });
          return;
        }
        if (a === "dismiss" && ctxRuns && ctxRuns.dismiss) {
          var p = ctxRuns.dismiss({ workspaceRoot: t.workspaceRoot, sessionRootRunId: t.runId });
          if (p && p.then) p.then(function () { state.selectedId = null; void refresh(); });
        }
      }

      function onKey(e) {
        var tag = (e.target && e.target.tagName) || "";
        var typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
        if (e.key === "Escape") {
          if (typing && e.target === refs.q && refs.q.value) {
            refs.q.value = "";
            state.q = "";
            paintList();
            return;
          }
          if (typing) return;
          return closePanel();
        }
        if (typing) return;
        if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); return selectBy(1); }
        if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); return selectBy(-1); }
        if (e.key === "/") { e.preventDefault(); return refs.q && refs.q.focus(); }
        if (e.key === "r") return void refresh();
        if (e.key === "Enter") {
          var t = currentTask();
          if (t && ctxRuns && ctxRuns.open) ctxRuns.open({ runId: t.runId, workspaceRoot: t.workspaceRoot });
        }
      }

      function onInput(e) {
        if (!e.target.matches || !e.target.matches('[data-ref="q"]')) return;
        state.q = e.target.value;
        paintList();
      }

      function onChange(e) {
        if (!e.target.matches || !e.target.matches('[data-ref="sort"]')) return;
        state.sort = e.target.value;
        paintAll();
      }

      function openPanel() {
        if (!refs.root) return void boot().then(openPanel);
        refs.root.style.display = "";
        refs.root.classList.remove("is-embedded");
        void refresh();
        clearInterval(timer);
        timer = setInterval(function () {
          if (document.visibilityState === "visible") void refresh();
        }, 3000);
      }

      function closePanel() {
        if (refs.root) refs.root.style.display = "none";
        clearInterval(timer);
        timer = 0;
      }

      function boot() {
        if (initPromise) return initPromise;
        initPromise = loadModules().then(function () {
          paintAll();
          document.addEventListener("keydown", onKey);
          document.addEventListener("input", onInput);
          document.addEventListener("change", onChange);
          if (refs.root) refs.root.addEventListener("click", onClick);
          closePanel();
        });
        return initPromise;
      }

      api.apply = function (ctx) {
        injectStyle();
        ctxRuns = (ctx && ctx.runs) || null;
        ctxEvents = (ctx && ctx.events) || null;
        if (ctx && ctx.entries && ctx.entries.register) {
          handle = ctx.entries.register({
            id: "task-center",
            label: "任务中心",
            icon: "list",
            open: openPanel,
            mount: function (host) {
              var disposed = false;
              void boot().then(function () {
                if (disposed || !refs.root) return;
                refs.root.classList.add("is-embedded");
                refs.root.style.display = "";
                if (refs.root.parentNode !== host) host.appendChild(refs.root);
                void refresh();
              });
              return function () {
                disposed = true;
                closePanel();
              };
            },
          });
        }
        if (ctxEvents && typeof ctxEvents.on === "function") {
          offEvents = ctxEvents.on("*", function () { void refresh(); });
        }
        void boot().then(function () { void refresh(); });

        return function () {
          clearInterval(timer);
          document.removeEventListener("keydown", onKey);
          document.removeEventListener("input", onInput);
          document.removeEventListener("change", onChange);
          if (typeof offEvents === "function") offEvents();
          if (handle && handle.dispose) handle.dispose();
          if (refs.root) refs.root.remove();
          refs = {};
          S = null;
          V = null;
          handle = null;
          offEvents = null;
          initPromise = null;
        };
      };

      module.exports = api;
      return module.exports;
    },
  });
})();
