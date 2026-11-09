window.__ModuleLoader__.load({
  id: "dsh-notify",
  factory: (require) => {
    var module = { exports: {} };
    var exports = module.exports;

    // ---------------------------------------------------------------------
    // 消息通知 — 浏览器半。
    //
    // 入口自己造：控制台里宿主还没有「插件面板注册」这个贡献类型，鲸鱼壁纸也是
    // 自己往 body 插齿轮（#whale-pond-gear）。这里同样插一个铃铛，位置在窗口
    // 右上角、皮肤快切按钮左边。
    //
    // 配置与凭据不在这边：面板只是 host 进程（lib/host.mjs）的一张表单，
    // 读写都走 laji-plugin://<id>/__proxy/...。
    // ---------------------------------------------------------------------
    var PLUGIN_ID = "com.nerve.dsh-notify";
    var PANEL_ID = "dsh-notify-panel";
    var STYLE_ID = "dsh-notify-style";
    var TOAST_ID = "dsh-notify-toast";
    var MODAL_ID = "dsh-notify-modal";
    var BASE = "laji-plugin://" + PLUGIN_ID + "/__proxy/";
    var VERSION = "0.1.0";

    var EVENT_META = {
      approval: { label: "审批请求", color: "#cca700" },
      questions: { label: "提问待选", color: "#4c8fe0" },
      error: { label: "运行错误", color: "#f14c4c" },
      plan: { label: "计划待确认", color: "#4ec9b0" },
    };

    var CHANNEL_META = {
      sms: { label: "短信", icon: "📱" },
      mail: { label: "邮件", icon: "✉️" },
      wecom: { label: "企业微信", icon: "💬" },
    };

    var refs = { panel: null, toast: null, body: null, banner: null, saved: null };
    var config = null;
    var secrets = { sms: false, mail: false };
    var activeTab = "chan";
    /** 当前打开着弹框的渠道名；null = 没开。 */
    var modalChan = null;
    var disposed = false;

    // 入口句柄：宿主用它更新红点、收回入口（插件不自己往右上角钉浮钮）。
    var entryHandle = null;
    /** 非空表示面板被插件中心嵌进去了（定位交给宿主，自己不再 fixed）。 */
    var embedHost = null;

    var STYLE = "";
    // 渠道配置弹框：挂在 body 下（不能进面板内部，面板有 transform，fixed 会被关进去）。
    STYLE += [
      "#" + MODAL_ID + "{position:fixed;inset:0;z-index:2147483003;display:none;place-items:center;background:rgba(0,0,0,.45)}",
      "#" + MODAL_ID + ".open{display:grid}",
      "#" + MODAL_ID + " *{box-sizing:border-box}",
      "#" + MODAL_ID + " .npm-card{width:700px;max-width:calc(100vw - 32px);max-height:calc(100vh - 80px);display:flex;flex-direction:column;background:var(--laji-editorWidget-background,#252526);border:1px solid var(--laji-widget-border,#3a3a3a);border-radius:12px;box-shadow:0 24px 70px rgba(0,0,0,.55);color:var(--laji-foreground,#d4d4d4);font-size:13px;font-family:var(--laji-font-family,system-ui);overflow:hidden}",
      "#" + MODAL_ID + " .npm-head{display:flex;align-items:center;gap:9px;padding:12px 14px;border-bottom:1px solid var(--laji-panel-border,#2b2b2b)}",
      "#" + MODAL_ID + " .npm-ico{width:28px;height:28px;flex:none;border-radius:7px;display:grid;place-items:center;background:rgba(128,128,128,.16);font-size:14px}",
      "#" + MODAL_ID + " .npm-title{font-weight:600;font-size:13.5px}",
      "#" + MODAL_ID + " .npm-x{margin-left:auto;background:none;border:none;color:inherit;opacity:.6;font-size:17px;cursor:pointer;padding:0 3px}",
      "#" + MODAL_ID + " .npm-x:hover{opacity:1}",
      "#" + MODAL_ID + " .npm-body{flex:1;min-height:0;overflow:auto;padding:14px 16px 16px;display:grid;grid-template-columns:1fr 1fr;gap:11px 14px;align-content:start;scrollbar-width:thin;scrollbar-color:#4a4a4a transparent}",
      "#" + MODAL_ID + " .npm-body::-webkit-scrollbar{width:10px;height:10px}",
      "#" + MODAL_ID + " .npm-body::-webkit-scrollbar-track{background:transparent}",
      "#" + MODAL_ID + " .npm-body::-webkit-scrollbar-thumb{background:#4a4a4a;border-radius:6px;border:2px solid transparent;background-clip:content-box}",
      "#" + MODAL_ID + " .npm-body::-webkit-scrollbar-thumb:hover{background:#5f5f5f;background-clip:content-box}",
      "#" + MODAL_ID + " .npm-body::-webkit-scrollbar-button{display:none;height:0;width:0}",
      "#" + MODAL_ID + " .npm-foot{display:flex;align-items:center;gap:8px;padding:9px 14px;border-top:1px solid var(--laji-panel-border,#2b2b2b);background:var(--laji-editor-background,#1e1e1e)}",
      "#" + MODAL_ID + " .npm-spacer{flex:1}",
      "#" + MODAL_ID + " .npm-btn{font:inherit;font-size:12px;padding:4px 11px;border-radius:6px;border:1px solid var(--laji-widget-border,#3a3a3a);background:rgba(128,128,128,.14);color:inherit;cursor:pointer}",
      "#" + MODAL_ID + " .npm-btn:hover{background:rgba(128,128,128,.24)}",
      "#" + MODAL_ID + " .npm-btn.primary{background:#2f6fbf;border-color:#2f6fbf;color:#fff}",
      "#" + MODAL_ID + " .npm-btn:disabled{opacity:.55;cursor:default}",
      "#" + MODAL_ID + " .np-field{display:grid;gap:5px;align-content:start}",
      "#" + MODAL_ID + " .np-field.wide,#" + MODAL_ID + " .np-opt.wide{grid-column:1/-1}",
      "#" + MODAL_ID + " .npm-group{grid-column:1/-1;display:flex;align-items:center;gap:9px;font-size:11px;letter-spacing:.03em;color:var(--laji-descriptionForeground,#9d9d9d);margin-top:4px}",
      "#" + MODAL_ID + " .npm-group:first-child{margin-top:0}",
      "#" + MODAL_ID + " .npm-group:after{content:'';flex:1;height:1px;background:rgba(128,128,128,.18)}",
      "#" + MODAL_ID + " .npm-tpl{grid-column:1/-1;padding:11px 12px;border:1px solid rgba(128,128,128,.2);border-radius:9px;background:rgba(128,128,128,.055);gap:8px;display:grid}",
      "#" + MODAL_ID + " .np-field label{font-size:11px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + MODAL_ID + " .np-field input,#" + MODAL_ID + " .np-field select{font:inherit;font-size:12px;color:var(--laji-input-foreground,#e6e6e6);background:var(--laji-input-background,#2a2a2a);border:1px solid var(--laji-input-border,#3c3c3c);border-radius:6px;padding:5px 8px;width:100%}",
      "#" + MODAL_ID + " .np-field input:focus,#" + MODAL_ID + " .np-field select:focus{outline:none;border-color:#2f6fbf}",
      "#" + MODAL_ID + " .np-field textarea{font:inherit;font-size:12px;line-height:1.5;color:var(--laji-input-foreground,#e6e6e6);background:var(--laji-input-background,#2a2a2a);border:1px solid var(--laji-input-border,#3c3c3c);border-radius:6px;padding:6px 8px;width:100%;min-height:66px;resize:vertical;font-family:var(--laji-font-family,system-ui)}",
      "#" + MODAL_ID + " .np-field textarea:focus{outline:none;border-color:#2f6fbf}",
      "#" + MODAL_ID + " .npm-chips{display:flex;gap:5px;flex-wrap:wrap;margin-left:4px}",
      "#" + MODAL_ID + " .npm-reset{margin-left:auto;font:inherit;font-size:10.5px;padding:4px 8px;border-radius:6px;border:1px solid transparent;background:transparent;color:var(--laji-descriptionForeground,#8f8f8f);cursor:pointer}",
      "#" + MODAL_ID + " .npm-reset:hover{background:rgba(128,128,128,.16);color:var(--laji-foreground,#d4d4d4)}",
      "#" + MODAL_ID + " .npm-chip{font:inherit;font-size:10.5px;line-height:1;padding:4px 9px;border-radius:6px;border:1px solid rgba(128,128,128,.28);background:rgba(128,128,128,.12);color:var(--laji-descriptionForeground,#b0b0b0);cursor:pointer}",
      "#" + MODAL_ID + " .npm-chip:hover{background:rgba(47,111,191,.22);border-color:rgba(47,111,191,.55);color:var(--laji-foreground,#e6e6e6)}",
      "#" + MODAL_ID + " .npm-tip{font-size:10.5px;margin-top:1px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + MODAL_ID + " .npm-editbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap}",
      "#" + MODAL_ID + " .npm-chips{display:flex;gap:5px;flex-wrap:wrap;flex:1}",
      "#" + MODAL_ID + " .npm-frame{grid-column:1/-1;width:100%;height:152px;border:1px solid rgba(0,0,0,.12);border-radius:6px;background:#fff;display:none}",
      "#" + MODAL_ID + " .npm-preview{background:#fff;color:#1f1f1f;border:1px solid rgba(0,0,0,.12);border-radius:6px;padding:9px 11px;font-size:12px;line-height:1.62;white-space:pre-wrap;word-break:break-word;min-height:54px;max-height:152px;overflow:auto}",
      "#" + MODAL_ID + " .npm-preview .quote{border-left:3px solid #dcdcdc;padding-left:8px;color:#666;margin:2px 0}",
      "#" + MODAL_ID + " .npm-preview code{background:#f0f0f0;border-radius:3px;padding:1px 4px;font-family:ui-monospace,Consolas,monospace}",
      "#" + MODAL_ID + " .npm-preview a{color:#0b62c4}",
      "#" + MODAL_ID + " .EasyMDEContainer{grid-column:1/-1;width:100%}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror{background:var(--laji-input-background,#2a2a2a);color:var(--laji-input-foreground,#e6e6e6);border:1px solid var(--laji-input-border,#3c3c3c);border-radius:6px;font-size:12px;line-height:1.62;padding:6px 2px}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-focused{border-color:#2f6fbf}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-cursor{border-left-color:var(--laji-foreground,#d4d4d4)}",
      "#" + MODAL_ID + " .EasyMDEContainer .cm-s-easymde .cm-header,#" + MODAL_ID + " .EasyMDEContainer .cm-s-easymde .cm-strong{color:inherit}",
      "#" + MODAL_ID + " .editor-toolbar{border:none;border-top:none;padding:0 0 5px;opacity:1;display:flex;gap:2px;flex-wrap:wrap}",
      "#" + MODAL_ID + " .editor-toolbar button{width:26px;height:24px;padding:0;border:1px solid transparent;border-radius:5px;background:transparent;color:var(--laji-descriptionForeground,#aaa);font-size:11px;line-height:1;display:inline-flex;align-items:center;justify-content:center}",
      "#" + MODAL_ID + " .editor-toolbar button:hover{background:rgba(128,128,128,.2);color:var(--laji-foreground,#e6e6e6);border-color:transparent}",
      "#" + MODAL_ID + " .editor-toolbar button:before{display:none}",
      "#" + MODAL_ID + " .editor-toolbar i.separator{display:none}",
      "#" + MODAL_ID + " .editor-statusbar{display:none}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-scroll::-webkit-scrollbar{width:9px;height:9px}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-scroll::-webkit-scrollbar-track{background:transparent}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-scroll::-webkit-scrollbar-thumb{background:#4a4a4a;border-radius:6px;border:2px solid transparent;background-clip:content-box}",
      "#" + MODAL_ID + " .EasyMDEContainer .CodeMirror-scroll::-webkit-scrollbar-button{display:none;height:0;width:0}",
      "#" + MODAL_ID + " .np-opt{display:flex;align-items:center;gap:9px;padding:4px 0;font-size:12px}",
      "#" + MODAL_ID + " input[type=checkbox]{appearance:none;-webkit-appearance:none;width:15px;height:15px;border-radius:4px;border:1px solid #4a4a4a;background:#171717;cursor:pointer;margin:0;display:inline-grid;place-items:center;font-size:10px;color:#fff}",
      "#" + MODAL_ID + " input[type=checkbox]:checked{background:#2f6fbf;border-color:#2f6fbf}",
      "#" + MODAL_ID + " input[type=checkbox]:checked:after{content:'\\2713'}",
    ].join("\n");
    STYLE += [
      "#" + PANEL_ID + "{position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);z-index:2147483001;width:424px;max-width:calc(100vw - 32px);max-height:calc(100vh - 60px);display:none;flex-direction:column;background:var(--laji-editorWidget-background,#252526);border:1px solid var(--laji-widget-border,#3a3a3a);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.6);color:var(--laji-foreground,#d4d4d4);font-size:13px;font-family:var(--laji-font-family,system-ui);overflow:hidden}",
      "#" + PANEL_ID + ".open{display:flex}",
      "#" + PANEL_ID + " *{box-sizing:border-box}",
      "#" + PANEL_ID + " .np-head{display:flex;align-items:center;gap:8px;padding:12px 14px 10px;border-bottom:1px solid var(--laji-panel-border,#2b2b2b)}",
      "#" + PANEL_ID + " .np-badge{width:22px;height:22px;border-radius:6px;display:grid;place-items:center;background:#2f6fbf;color:#fff;font-size:11px}",
      "#" + PANEL_ID + " .np-title{font-weight:600;font-size:13.5px}",
      "#" + PANEL_ID + " .np-ver{font-size:10.5px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + PANEL_ID + " .np-x{margin-left:auto;background:none;border:none;color:inherit;opacity:.6;font-size:17px;cursor:pointer;padding:0 3px}",
      "#" + PANEL_ID + " .np-x:hover{opacity:1}",
      /* 嵌入插件中心时：宿主自己画标题（图标+名字+id），这行只留版本号，× 也由宿主管。 */
      "#" + PANEL_ID + ".is-embedded .np-head{padding:8px 16px;border-bottom:none}",
      "#" + PANEL_ID + ".is-embedded .np-badge,#" + PANEL_ID + ".is-embedded .np-title,#" + PANEL_ID + ".is-embedded .np-x{display:none}",
      "#" + PANEL_ID + ".is-embedded .np-ver{margin-left:auto;font-size:11px;opacity:.6}",
      "#" + PANEL_ID + ".is-embedded .np-body{flex:1;min-height:0;overflow:auto}",
      "#" + PANEL_ID + " .np-tabs{display:flex;gap:16px;padding:0 14px;border-bottom:1px solid var(--laji-panel-border,#2b2b2b)}",
      "#" + PANEL_ID + " .np-tab{background:none;border:none;border-bottom:2px solid transparent;color:var(--laji-descriptionForeground,#9d9d9d);font:inherit;font-size:12.5px;padding:7px 0;margin-bottom:-1px;cursor:pointer}",
      "#" + PANEL_ID + " .np-tab.on{color:var(--laji-foreground,#d4d4d4);border-bottom-color:#2f6fbf}",
      "#" + PANEL_ID + " .np-body{flex:1;min-height:0;overflow:auto;padding:10px 14px 14px}",
      "#" + PANEL_ID + " .np-body::-webkit-scrollbar{width:9px;height:9px}",
      "#" + PANEL_ID + " .np-body::-webkit-scrollbar-thumb{background:rgba(128,128,128,.32);border-radius:5px;border:2px solid transparent;background-clip:padding-box}",
      "#" + PANEL_ID + " .np-body::-webkit-scrollbar-thumb:hover{background:rgba(128,128,128,.55);background-clip:padding-box}",
      "#" + PANEL_ID + " .np-body::-webkit-scrollbar-track{background:transparent}",
      "#" + PANEL_ID + " .np-pane{display:none}",
      "#" + PANEL_ID + " .np-pane.on{display:block}",
      "#" + PANEL_ID + " .np-group{display:flex;justify-content:space-between;align-items:center;margin:12px 0 6px;font-size:11px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + PANEL_ID + " .np-group:first-child{margin-top:2px}",
      "#" + PANEL_ID + " .np-chan{border:1px solid var(--laji-panel-border,#2b2b2b);border-radius:8px;background:var(--laji-sideBar-background,#181818);margin-bottom:8px;overflow:hidden}",
      "#" + PANEL_ID + " .np-chan.on{border-color:rgba(47,111,191,.5)}",
      "#" + PANEL_ID + " .np-chan-head{display:flex;align-items:center;gap:9px;padding:9px 10px;cursor:pointer}",
      "#" + PANEL_ID + " .np-ico{width:26px;height:26px;flex:none;border-radius:7px;display:grid;place-items:center;background:rgba(128,128,128,.16);font-size:13px}",
      "#" + PANEL_ID + " .np-chan-name{font-size:12.5px;font-weight:500}",
      "#" + PANEL_ID + " .np-chan-note{font-size:11px;color:var(--laji-descriptionForeground,#9d9d9d);margin-top:1px}",
      "#" + PANEL_ID + " .np-chev{font-size:10px;color:var(--laji-descriptionForeground,#9d9d9d);transition:transform .15s}",
      "#" + PANEL_ID + " .np-field{display:grid;gap:3px}",
      "#" + PANEL_ID + " .np-field label{font-size:11px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + PANEL_ID + " .np-field input,#" + PANEL_ID + " .np-field select{font:inherit;font-size:12px;color:var(--laji-input-foreground,#e6e6e6);background:var(--laji-input-background,#2a2a2a);border:1px solid var(--laji-input-border,#3c3c3c);border-radius:6px;padding:5px 8px;width:100%}",
      "#" + PANEL_ID + " .np-field input:focus,#" + PANEL_ID + " .np-field select:focus{outline:none;border-color:#2f6fbf}",
      "#" + PANEL_ID + " .np-row2{display:grid;grid-template-columns:1fr 92px;gap:7px}",
      "#" + PANEL_ID + " .np-safe{font-size:11px;color:#4ec9b0;display:flex;gap:6px;align-items:center}",
      "#" + PANEL_ID + " .np-safe:before{content:'\u25cf';font-size:8px}",
      "#" + PANEL_ID + " .np-switch{position:relative;flex:none;width:30px;height:17px;border-radius:999px;background:#3d3d3d;border:none;cursor:pointer}",
      "#" + PANEL_ID + " .np-switch:after{content:'';position:absolute;top:2px;left:2px;width:13px;height:13px;border-radius:50%;background:#b9b9b9;transition:.15s}",
      "#" + PANEL_ID + " .np-switch.on{background:#2f6fbf}",
      "#" + PANEL_ID + " .np-switch.on:after{transform:translateX(13px);background:#fff}",
    ].join("\n");
    STYLE += [
      "#" + PANEL_ID + " table{width:100%;border-collapse:collapse;font-size:11.5px}",
      "#" + PANEL_ID + " th{font-weight:500;color:var(--laji-descriptionForeground,#9d9d9d);font-size:10.5px;text-align:center;padding:6px 4px;border-bottom:1px solid var(--laji-panel-border,#2b2b2b)}",
      "#" + PANEL_ID + " th:first-child{text-align:left}",
      "#" + PANEL_ID + " th:not(:first-child),#" + PANEL_ID + " td:not(:first-child){width:56px}",
      "#" + PANEL_ID + " th{white-space:nowrap}",
      "#" + PANEL_ID + " td{padding:8px 4px;text-align:center;border-bottom:1px solid rgba(128,128,128,.15);vertical-align:top}",
      "#" + PANEL_ID + " td:first-child{text-align:left}",
      "#" + PANEL_ID + " .np-ev{display:flex;align-items:center;gap:6px;font-size:12px}",
      "#" + PANEL_ID + " .np-dot{width:6px;height:6px;border-radius:50%;flex:none}",
      "#" + PANEL_ID + " input[type=checkbox]{appearance:none;-webkit-appearance:none;width:15px;height:15px;border-radius:4px;border:1px solid #4a4a4a;background:#171717;cursor:pointer;margin:0;display:inline-grid;place-items:center;font-size:10px;color:#fff}",
      "#" + PANEL_ID + " input[type=checkbox]:checked{background:#2f6fbf;border-color:#2f6fbf}",
      "#" + PANEL_ID + " input[type=checkbox]:checked:after{content:'\u2713'}",
      "#" + PANEL_ID + " .np-opt{display:flex;align-items:center;gap:9px;padding:7px 0;font-size:12px}",
      "#" + PANEL_ID + " .np-opt .np-hint{font-size:10.5px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + PANEL_ID + " .np-time{font:inherit;font-size:11.5px;background:var(--laji-input-background,#2a2a2a);border:1px solid var(--laji-input-border,#3c3c3c);border-radius:6px;padding:3px 6px;width:70px;color:inherit}",
      "#" + PANEL_ID + " .np-log{display:flex;gap:9px;padding:8px 0;border-bottom:1px solid rgba(128,128,128,.15);font-size:11.5px}",
      "#" + PANEL_ID + " .np-log .t{width:72px;flex:none;font-size:10.5px;color:var(--laji-descriptionForeground,#9d9d9d)}",
      "#" + PANEL_ID + " .np-log .sub{font-size:10.5px;color:var(--laji-descriptionForeground,#9d9d9d);margin-top:1px}",
      "#" + PANEL_ID + " .np-pill{flex:none;align-self:flex-start;font-size:10px;padding:1px 6px;border-radius:999px;border:1px solid var(--laji-panel-border,#2b2b2b);color:var(--laji-descriptionForeground,#9d9d9d);white-space:nowrap}",
      "#" + PANEL_ID + " .np-pill.ok{color:#4ec9b0;border-color:rgba(78,201,176,.4)}",
      "#" + PANEL_ID + " .np-pill.fail{color:#ff9d9d;border-color:rgba(241,76,76,.45)}",
      "#" + PANEL_ID + " .np-empty{padding:22px 0;text-align:center;color:var(--laji-descriptionForeground,#9d9d9d);font-size:11.5px}",
      "#" + PANEL_ID + " .np-foot{flex:none;display:flex;align-items:center;gap:8px;padding:9px 14px;border-top:1px solid var(--laji-panel-border,#2b2b2b);background:var(--laji-editor-background,#1e1e1e)}",
      "#" + PANEL_ID + " .np-btn{font:inherit;font-size:12px;padding:4px 11px;border-radius:6px;border:1px solid var(--laji-widget-border,#3a3a3a);background:rgba(128,128,128,.14);color:inherit;cursor:pointer}",
      "#" + PANEL_ID + " .np-btn:hover{background:rgba(128,128,128,.24)}",
      "#" + PANEL_ID + " .np-btn.primary{background:#2f6fbf;border-color:#2f6fbf;color:#fff}",
      "#" + PANEL_ID + " .np-btn.primary:hover{background:#3b7fd4}",
      "#" + PANEL_ID + " .np-btn:disabled{opacity:.5;cursor:default}",
      "#" + PANEL_ID + " .np-spacer{flex:1}",
      "#" + PANEL_ID + " .np-saved{font-size:11px;color:#4ec9b0;opacity:0;transition:opacity .2s}",
      "#" + PANEL_ID + " .np-saved.on{opacity:1}",
      "#" + PANEL_ID + " .np-banner{margin-bottom:9px;padding:7px 9px;border-radius:6px;font-size:11px;border:1px solid rgba(241,76,76,.45);background:rgba(241,76,76,.1);color:#ffb4b4;display:none}",
      "#" + PANEL_ID + " .np-banner.on{display:block}",
      "#" + TOAST_ID + "{position:fixed;right:18px;bottom:18px;z-index:2147483002;display:none;align-items:center;gap:9px;width:304px;padding:10px 12px;background:var(--laji-editorWidget-background,#252526);border:1px solid var(--laji-widget-border,#3a3a3a);border-left:3px solid #2f6fbf;border-radius:8px;box-shadow:0 14px 40px rgba(0,0,0,.6);font-size:12px;color:var(--laji-foreground,#d4d4d4);font-family:var(--laji-font-family,system-ui)}",
      "#" + TOAST_ID + ".on{display:flex}",
      "#" + TOAST_ID + " .np-tick{color:#4ec9b0;font-size:13px}",
      "#" + TOAST_ID + " b{display:block;font-weight:600}",
      "#" + TOAST_ID + " span{font-size:11px;opacity:.75}",
    ].join("\n");

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text != null) node.textContent = text;
      return node;
    }

    function api(path, options) {
      return fetch(BASE + path, options).then(function (res) {
        return res.json().then(function (data) {
          if (!res.ok || data.ok === false) throw new Error(data.error || "服务返回 " + res.status);
          return data;
        });
      });
    }

    function post(path, payload) {
      return api(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(payload || {}),
      });
    }

    function toast(title, body) {
      if (!refs.toast) return;
      refs.toast.innerHTML = "";
      refs.toast.appendChild(el("span", "np-tick", "\u2713"));
      var box = el("div", "");
      box.appendChild(el("b", "", title));
      box.appendChild(el("span", "", body || ""));
      refs.toast.appendChild(box);
      refs.toast.classList.add("on");
      clearTimeout(refs.toastTimer);
      refs.toastTimer = setTimeout(function () {
        refs.toast.classList.remove("on");
      }, 3600);
    }

    function notice(text) {
      if (!refs.banner) return;
      refs.banner.textContent = text || "";
      refs.banner.classList.toggle("on", Boolean(text));
    }

    // ── 渠道表单：字段表驱动，免得三个渠道写三份 UI ──────────────
    var FIELDS = {
      sms: [
        { type: "group", label: "通道" },
        { key: "provider", label: "服务商", type: "select", wide: true, options: [
          ["aliyun", "阿里云短信"],
          ["webhook", "自建 Webhook"],
        ] },
        { key: "phones", label: "手机号（多个用逗号分隔）", type: "text", list: true, wide: true, placeholder: "13800000000" },
        { key: "sign", label: "短信签名", type: "text", placeholder: "与模板审核的签名一致" },
        { key: "templateCode", label: "模板 CODE", type: "text", placeholder: "SMS_000000000", hint: "模板变量 ${kind} ${title}" },
        { key: "accessKeyId", label: "AccessKeyId", type: "text", wide: true },
        { key: "accessKeySecret", label: "AccessKeySecret", type: "password", secret: "sms", wide: true },
        { key: "webhook", label: "自建 Webhook", type: "text", wide: true, placeholder: "https://" },
      ],
      mail: [
        { type: "group", label: "连接" },
        { key: "host", label: "SMTP 服务器", type: "text", wide: true, placeholder: "smtp.example.com" },
        { key: "port", label: "端口", type: "number" },
        { key: "secure", label: "SSL / TLS", type: "check" },
        { key: "user", label: "账号", type: "text" },
        { key: "pass", label: "密码 / 授权码", type: "password", secret: "mail" },
        { key: "from", label: "发件人", type: "text", wide: true, placeholder: "laji@example.com" },
        { key: "to", label: "收件人（多个用逗号分隔）", type: "text", list: true, wide: true },
        { type: "group", label: "消息模板" },
        { key: "subject", label: "主题模板", type: "text", template: true, reset: "[{{事件}}] {{标题}}" },
        { key: "html", label: "HTML 正文", type: "check", off: true, wide: true },
        { key: "body", label: "正文模板", type: "textarea", rows: 6, template: true, preview: "mail", reset: "{{事件}}：{{标题}}\n{{会话}}\n\n{{详情}}" },
      ],
      wecom: [
        { type: "group", label: "连接" },
        { key: "webhook", label: "群机器人 Webhook", type: "text", wide: true, placeholder: "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…" },
        { key: "mention", label: "提醒人（@all 或 userid，逗号分隔）", type: "text", wide: true },
        { type: "group", label: "消息模板" },
        { key: "template", label: "正文模板", type: "textarea", rows: 6, template: true, preview: "wecom", reset: "**{{事件}}** {{标题}}\n> {{会话}}\n\n{{详情}}" },
      ],
    };

    function splitList(value) {
      return String(value || "")
        .split(/[,.;\uff0c\u3001\s]+/)
        .map(function (item) {
          return item.trim();
        })
        .filter(Boolean);
    }

    function withClass(node, cls, on) {
      node.classList.toggle(cls, Boolean(on));
      return node;
    }

    function switchEl(on, onChange) {
      var btn = el("button", "np-switch" + (on ? " on" : ""));
      btn.type = "button";
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.onclick = function (e) {
        e.stopPropagation();
        onChange(!btn.classList.contains("on"));
      };
      return btn;
    }

    var TEMPLATE_VARS = ["事件", "标题", "会话", "详情"];
    var SAMPLE_MESSAGE = { 事件: "运行错误", 标题: "任务失败", 会话: "鲸落 · 未至之境", 详情: "bash 退出码 1" };
    var WECOM_TONE = { info: "#909399", comment: "#909399", gray: "#909399", warning: "#e6a23c", orange: "#e6a23c", green: "#3eb575", red: "#f14c4c" };
    // 渠道表单里所有模板字段的预览函数；勾选 HTML 这类开关后要统一重刷
    var templateSyncers = [];

    function renderTemplate(text, values) {
      return String(text || "").replace(/\{\{\s*([^{}]+?)\s*\}\}/g, function (all, key) {
        return Object.prototype.hasOwnProperty.call(values, key) ? values[key] : all;
      });
    }

    function escapeHtml(text) {
      return String(text).replace(/[&<>]/g, function (ch) {
        return ch === "&" ? "&amp;" : ch === "<" ? "&lt;" : "&gt;";
      });
    }

    /** 企业微信 markdown 子集：加粗 / 斜体 / 删除线 / 引用 / 链接 / 代码 / <font color>。 */
    function inlineMarkdown(text) {
      return escapeHtml(text)
        .replace(/&lt;font color="([a-z]+)"&gt;/gi, function (all, tone) {
          return '<span style="color:' + (WECOM_TONE[tone] || tone) + '">';
        })
        .replace(/&lt;\/font&gt;/gi, "</span>")
        .replace(/`([^`]+)`/g, "<code>$1</code>")
        .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
        .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<i>$2</i>")
        .replace(/~~([^~]+)~~/g, "<s>$1</s>")
        .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
    }

    function markdownToHtml(text) {
      return String(text || "")
        .split(/\r?\n/)
        .map(function (line) {
          var quote = line.indexOf("> ") === 0;
          var html = inlineMarkdown(quote ? line.slice(2) : line);
          return '<div class="' + (quote ? "quote" : "line") + '">' + (html || "&nbsp;") + "</div>";
        })
        .join("");
    }

    function htmlDocument(fragment) {
      return (
        '<!doctype html><meta charset="utf-8"><style>' +
        'html,body{margin:0;padding:0;background:#fff;color:#1f1f1f;font:13px/1.65 system-ui,"Segoe UI",sans-serif}' +
        "a{color:#0b62c4}code{background:#f0f0f0;border-radius:3px;padding:1px 4px;font-family:ui-monospace,Consolas,monospace}" +
        ".line{margin:0}.quote{border-left:3px solid #d8d8d8;padding-left:8px;color:#666;margin:2px 0}" +
        "</style>" +
        (fragment || '<span style="color:#aaa">预览为空</span>')
      );
    }

    var VENDOR_BASE = "laji-plugin://" + PLUGIN_ID + "/lib/vendor/";
    var vendorPromise = null;
    var mdeInstances = [];
    // 图标字体没有随包发，按钮一律用文字（EasyMDE 自带的 fa 图标会变空白）。
    var MD_BUTTONS = [
      ["nd-bold", "加粗", "B", "**", "**"],
      ["nd-italic", "斜体", "I", "*", "*"],
      ["nd-strike", "删除线", "S", "~~", "~~"],
      ["nd-quote", "引用", "❝", "> ", ""],
      ["nd-code", "行内代码", "</>", "`", "`"],
      ["nd-link", "链接", "🔗", "[", "](https://)"],
      ["nd-color", "橙色字", "色", '<font color="warning">', "</font>"],
    ];

    /** EasyMDE（单文件含 CodeMirror）从插件目录按需拉，拉不到就退回纯 textarea。 */
    function loadVendor() {
      if (vendorPromise) return vendorPromise;
      vendorPromise = new Promise(function (resolve) {
        if (window.EasyMDE) return resolve(window.EasyMDE);
        var link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = VENDOR_BASE + "easymde.min.css";
        document.head.appendChild(link);
        var script = document.createElement("script");
        script.src = VENDOR_BASE + "easymde.min.js";
        script.onload = function () {
          resolve(window.EasyMDE || null);
        };
        script.onerror = function () {
          resolve(null);
        };
        document.head.appendChild(script);
      });
      return vendorPromise;
    }

    /** 纯函数版 toggle：返回新文本与光标，textarea 与 CodeMirror 共用。 */
    function toggleText(value, start, end, before, after) {
      if (!after) {
        var lineStart = value.lastIndexOf("\n", start - 1) + 1;
        var prefixed = value.slice(lineStart, lineStart + before.length) === before;
        return {
          text: prefixed
            ? value.slice(0, lineStart) + value.slice(lineStart + before.length)
            : value.slice(0, lineStart) + before + value.slice(lineStart),
          caret: Math.max(0, prefixed ? start - before.length : start + before.length),
        };
      }

      var picked = value.slice(start, end);
      if (picked.length > before.length + after.length && picked.indexOf(before) === 0 && picked.slice(-after.length) === after) {
        var bare = picked.slice(before.length, picked.length - after.length);
        return { text: value.slice(0, start) + bare + value.slice(end), caret: start + bare.length };
      }

      // 光标紧贴闭合/开启标记才算“已应用”，否则会把旁边的无关标记一起吃掍
      if (start === end) {
        var closeIdx = value.indexOf(after, start);
        var openedAt = start - before.length;
        if (openedAt >= 0 && value.slice(openedAt, start) === before && closeIdx >= 0) {
          var inside = value.slice(start, closeIdx);
          if (inside.indexOf("\n") < 0 && inside.indexOf(after) < 0) {
            return {
              text: value.slice(0, openedAt) + inside + value.slice(closeIdx + after.length),
              caret: openedAt + inside.length,
            };
          }
        }
        if (value.slice(start, start + after.length) === after) {
          var openIdx = value.lastIndexOf(before, start - 1);
          if (openIdx >= 0) {
            var body = value.slice(openIdx + before.length, start);
            if (body.indexOf("\n") < 0 && body.indexOf(before) < 0) {
              return {
                text: value.slice(0, openIdx) + body + value.slice(start + after.length),
                caret: openIdx + body.length,
              };
            }
          }
        }
      }

      return {
        text: value.slice(0, start) + before + picked + after + value.slice(end),
        caret: start + before.length + picked.length,
      };
    }

    /** 在 CodeMirror 上执行一次幂等语法操作。 */
    function applyMarkup(editor, before, after) {
      var cm = editor.codemirror;
      var start = cm.indexFromPos(cm.getCursor("from"));
      var end = cm.indexFromPos(cm.getCursor("to"));
      var next = toggleText(cm.getValue(), start, end, before, after);
      var caret = cm.posFromIndex(next.caret);
      cm.setValue(next.text);
      cm.setSelection(caret, caret);
      cm.focus();
    }

    /**
     * 模板字段：EasyMDE 编辑器 + 变量胶囊 + 恢复默认 + 渠道原生预览。
     * EasyMDE 还没到货时先用普通 textarea，到货后原地升级。
     */
    function attachTemplate(wrap, input, field, conf) {
      var mde = null;

      var bar = el("div", "npm-editbar");
      var chips = el("div", "npm-chips");
      TEMPLATE_VARS.forEach(function (name) {
        var chip = el("button", "npm-chip", name);
        chip.type = "button";
        chip.onclick = function () {
          var token = "{{" + name + "}}";
          if (mde) {
            mde.codemirror.replaceSelection(token);
            mde.codemirror.focus();
          } else {
            insertAtCaret(input, token, "");
          }
        };
        chips.appendChild(chip);
      });
      bar.appendChild(chips);

      var reset = el("button", "npm-reset", "恢复默认");
      reset.type = "button";
      reset.onclick = function () {
        var text = field.reset || "";
        if (mde) {
          mde.value(text);
          conf[field.key] = text;
          sync();
        } else {
          input.value = text;
          conf[field.key] = text;
          commit(input, text.length);
        }
      };
      bar.appendChild(reset);
      wrap.insertBefore(bar, input);

      var preview = null;
      var frame = null;
      var sync = function () {
        if (!preview) return;
        var raw = mde ? mde.value() : input.value;
        var text = renderTemplate(raw, SAMPLE_MESSAGE);
        if (field.preview === "mail" && conf.html) {
          preview.style.display = "none";
          frame.style.display = "block";
          frame.srcdoc = htmlDocument(text);
          return;
        }
        frame.style.display = "none";
        preview.style.display = "block";
        if (field.preview === "wecom") preview.innerHTML = markdownToHtml(text);
        else preview.textContent = text;
      };

      if (field.preview) {
        preview = el("div", "npm-preview");
        frame = el("iframe", "npm-frame");
        frame.setAttribute("sandbox", "");
        frame.setAttribute("title", "预览");
        wrap.appendChild(preview);
        wrap.appendChild(frame);
        templateSyncers.push(sync);
      }

      // 只有多行字段才值得上 CodeMirror：单行的邮件主题套个富文本编辑器只是噪音。
      if (input.tagName !== "TEXTAREA") {
        sync();
        return;
      }

      loadVendor().then(function (EasyMDE) {
        if (!EasyMDE || !input.parentNode) return;
        var instance = new EasyMDE({
          element: input,
          initialValue: conf[field.key] === undefined || conf[field.key] === null ? "" : String(conf[field.key]),
          autoDownloadFontAwesome: false,
          spellChecker: false,
          status: false,
          minHeight: "118px",
          toolbar: MD_BUTTONS.map(function (b) {
            return {
              name: b[0],
              title: b[1],
              action: function (editor) {
                applyMarkup(editor, b[3], b[4]);
              },
            };
          }),
        });
        MD_BUTTONS.forEach(function (b) {
          var node = instance.toolbarElements[b[0]];
          if (node) node.textContent = b[2];
        });
        instance.codemirror.on("change", function () {
          conf[field.key] = instance.value();
          if (preview) sync();
        });
        mdeInstances.push(instance);
        mde = instance;
        sync();
      });

      sync();
    }

    /** textarea 回退路径：与 CodeMirror 共用 toggleText。 */
    function insertAtCaret(input, before, after) {
      var value = input.value;
      var start = input.selectionStart == null ? value.length : input.selectionStart;
      var end = input.selectionEnd == null ? start : input.selectionEnd;
      var next = toggleText(value, start, end, before, after);
      input.value = next.text;
      commit(input, next.caret);
    }

    function commit(input, caret) {
      input.dispatchEvent(new Event("input"));
      input.focus();
      input.selectionStart = input.selectionEnd = Math.max(0, caret);
    }

    function fieldRow(field, conf) {
      if (field.type === "group") return el("div", "npm-group", field.label);
      var wide = field.wide || field.template || field.type === "textarea";
      var wrap = el("div", field.type === "check" ? "np-opt" : "np-field");
      if (wide) wrap.classList.add("wide");
      if (field.template) wrap.classList.add("npm-tpl");
      var input;
      if (field.type === "check") {
        input = el("input");
        input.type = "checkbox";
        input.checked = field.off ? conf[field.key] === true : conf[field.key] !== false;
        input.onchange = function () {
          conf[field.key] = input.checked;
          templateSyncers.forEach(function (fn) {
            fn();
          });
        };
        wrap.appendChild(input);
        wrap.appendChild(el("span", "", field.label));
        return wrap;
      }
      wrap.appendChild(el("label", "", field.label));
      if (field.type === "textarea") {
        input = el("textarea");
        input.rows = field.rows || 3;
        input.value = conf[field.key] == null ? "" : conf[field.key];
        input.oninput = function () {
          conf[field.key] = input.value;
        };
        wrap.appendChild(input);
        if (field.template) attachTemplate(wrap, input, field, conf);
        else if (field.hint) wrap.appendChild(el("div", "npm-tip", field.hint));
        return wrap;
      }
      if (field.type === "select") {
        input = el("select");
        field.options.forEach(function (pair) {
          var opt = el("option", "", pair[1]);
          opt.value = pair[0];
          input.appendChild(opt);
        });
        input.value = conf[field.key] || field.options[0][0];
        input.onchange = function () {
          conf[field.key] = input.value;
        };
      } else {
        input = el("input");
        input.type = field.type;
        if (field.type === "number") input.min = "1";
        if (field.list) input.value = (conf[field.key] || []).join(", ");
        else input.value = conf[field.key] == null ? "" : conf[field.key];
        if (field.placeholder) input.placeholder = field.placeholder;
        if (field.secret) {
          input.type = "password";
          if (secrets[field.secret]) input.placeholder = "已保存，留空则不变";
        }
        input.oninput = function () {
          if (field.list) conf[field.key] = splitList(input.value);
          else if (field.type === "number") conf[field.key] = Number(input.value) || 0;
          else conf[field.key] = input.value;
        };
      }
      if (field.narrow) input.style.width = "100%";
      wrap.appendChild(input);
      if (field.template) attachTemplate(wrap, input, field, conf);
      else if (field.hint) wrap.appendChild(el("div", "npm-tip", field.hint));
      return wrap;
    }

    function channelCard(name) {
      var meta = CHANNEL_META[name];
      var conf = config.channels[name];
      var card = withClass(el("div", "np-chan"), "on", conf.on);

      var head = el("div", "np-chan-head");
      head.appendChild(el("div", "np-ico", meta.icon));
      var text = el("div", "");
      text.style.flex = "1";
      text.appendChild(el("div", "np-chan-name", meta.label));
      var note = "";
      if (name === "sms" && conf.phones.length) note = conf.phones.length + " 个号码";
      if (name === "mail" && conf.to.length) note = conf.to.length + " 个收件人";
      if (name === "wecom" && conf.webhook) note = "已配置 Webhook";
      if (note) text.appendChild(el("div", "np-chan-note", note));
      head.appendChild(text);
      head.appendChild(el("div", "np-chev", "\u203a"));
      head.appendChild(
        switchEl(conf.on, function (value) {
          conf.on = value;
          renderBody();
        }),
      );
      // 整行点开一个弹框：面板本体只有 424 宽，内联展开会把 SMTP 那张表挤成两行。
      head.onclick = function () {
        openChannel(name);
      };
      card.appendChild(head);
      return card;
    }

    function closeModal() {
      modalChan = null;
      mdeInstances.forEach(function (instance) {
        try {
          instance.toTextArea();
        } catch (err) {
          // 实例已经随节点一起被删时 CodeMirror 会抛，忽略即可
        }
      });
      mdeInstances = [];
      var node = document.getElementById(MODAL_ID);
      if (node) node.remove();
    }

    /** 弹框字段直接改在 config 上，任何关闭方式都要把服务端配置重拉一遍才算回滚。 */
    function cancelModal() {
      closeModal();
      load();
    }

    function openChannel(name) {
      modalChan = name;
      renderModal();
    }

    /** 渠道设置弹框：字段直接绑在 config 上，“取消”靠重拉服务端配置回滚。 */
    function renderModal() {
      var stale = document.getElementById(MODAL_ID);
      if (stale) stale.remove();
      if (!modalChan || !config) return;
      var name = modalChan;
      var meta = CHANNEL_META[name];
      var conf = config.channels[name];

      var mask = el("div", "open");
      mask.id = MODAL_ID;
      mask.onclick = function (e) {
        if (e.target === mask) cancelModal();
      };

      var card = el("div", "npm-card");
      var head = el("div", "npm-head");
      head.appendChild(el("div", "npm-ico", meta.icon));
      var title = el("div");
      title.appendChild(el("div", "npm-title", meta.label + " 设置"));
      head.appendChild(title);
      var x = el("button", "npm-x", "\u00d7");
      x.type = "button";
      x.onclick = cancelModal;
      head.appendChild(x);
      card.appendChild(head);

      var body = el("div", "npm-body");
      FIELDS[name].forEach(function (field) {
        body.appendChild(fieldRow(field, conf));
      });
      card.appendChild(body);

      var foot = el("div", "npm-foot");
      var testBtn = el("button", "npm-btn", "发送测试");
      testBtn.type = "button";
      testBtn.onclick = function () {
        testBtn.disabled = true;
        testBtn.textContent = "发送中…";
        post("config", config)
          .then(function () {
            return post("test", { channel: name });
          })
          .then(function (res) {
            testBtn.disabled = false;
            testBtn.textContent = "发送测试";
            if (res.ok) toast(meta.label + " 测试已发出");
            else notice(meta.label + " 测试失败：" + (res.error || "未知错误"));
          })
          .catch(function (err) {
            testBtn.disabled = false;
            testBtn.textContent = "发送测试";
            notice(meta.label + " 测试失败：" + err.message);
          });
      };
      foot.appendChild(testBtn);
      foot.appendChild(el("div", "npm-spacer"));
      var cancel = el("button", "npm-btn", "取消");
      cancel.type = "button";
      cancel.onclick = cancelModal;
      foot.appendChild(cancel);
      var ok = el("button", "npm-btn primary", "保存");
      ok.type = "button";
      ok.onclick = function () {
        save(function () {
          closeModal();
        });
      };
      foot.appendChild(ok);
      card.appendChild(foot);

      mask.appendChild(card);
      document.body.appendChild(mask);
    }

    function sectionTitle(text) {
      var row = el("div", "np-group");
      row.appendChild(el("span", "", text));
      return row;
    }

    function renderChannels() {
      refs.body.appendChild(sectionTitle("推送渠道"));
      ["wecom", "mail", "sms"].forEach(function (name) {
        refs.body.appendChild(channelCard(name));
      });
    }

    function renderEvents() {
      var table = el("table");
      var head = el("tr");
      head.appendChild(el("th", "", "事件"));
      Object.keys(CHANNEL_META).forEach(function (name) {
        head.appendChild(el("th", "", CHANNEL_META[name].label));
      });
      table.appendChild(head);

      Object.keys(EVENT_META).forEach(function (kind) {
        var meta = EVENT_META[kind];
        var row = el("tr");
        var cell = el("td");
        var line = el("div", "np-ev");
        var dot = el("span", "np-dot");
        dot.style.background = meta.color;
        line.appendChild(dot);
        line.appendChild(el("span", "", meta.label));
        cell.appendChild(line);
        row.appendChild(cell);
        Object.keys(CHANNEL_META).forEach(function (name) {
          var td = el("td");
          var box = el("input");
          box.type = "checkbox";
          box.checked = Boolean(config.events[kind] && config.events[kind][name]);
          box.onchange = function () {
            config.events[kind][name] = box.checked;
          };
          td.appendChild(box);
          row.appendChild(td);
        });
        table.appendChild(row);
      });
      refs.body.appendChild(sectionTitle("哪些事件要通知"));
      refs.body.appendChild(table);

      refs.body.appendChild(sectionTitle("发送策略"));
      var only = el("label", "np-opt");
      var onlyBox = el("input");
      onlyBox.type = "checkbox";
      onlyBox.checked = config.policy.onlyUnfocused !== false;
      onlyBox.onchange = function () {
        config.policy.onlyUnfocused = onlyBox.checked;
      };
      only.appendChild(onlyBox);
      only.appendChild(el("span", "", "仅当窗口不在前台时推送"));
      refs.body.appendChild(only);

      var quiet = el("div", "np-opt");
      var quietBox = el("input");
      quietBox.type = "checkbox";
      quietBox.checked = config.policy.quiet.on !== false;
      quietBox.onchange = function () {
        config.policy.quiet.on = quietBox.checked;
        renderBody();
      };
      quiet.appendChild(quietBox);
      quiet.appendChild(el("span", "", "免打扰时段"));
      var start = el("input", "np-time");
      start.value = config.policy.quiet.start;
      start.oninput = function () {
        config.policy.quiet.start = start.value;
      };
      var end = el("input", "np-time");
      end.value = config.policy.quiet.end;
      end.oninput = function () {
        config.policy.quiet.end = end.value;
      };
      if (config.policy.quiet.on === false) {
        start.disabled = true;
        end.disabled = true;
      }
      quiet.appendChild(start);
      quiet.appendChild(el("span", "np-hint", "至"));
      quiet.appendChild(end);
      refs.body.appendChild(quiet);

      var max = el("div", "np-opt");
      max.appendChild(el("span", "", "每小时最多"));
      var maxInput = el("input", "np-time");
      maxInput.type = "number";
      maxInput.min = "1";
      maxInput.value = String(config.policy.hourlyMax || 10);
      maxInput.oninput = function () {
        config.policy.hourlyMax = Number(maxInput.value) || 10;
      };
      max.appendChild(maxInput);
      max.appendChild(el("span", "np-hint", "条"));
      refs.body.appendChild(max);
    }

    function renderLog() {
      var host = refs.body;
      var loading = el("div", "np-empty", "读取中…");
      host.appendChild(loading);
      api("log?limit=40")
        .then(function (res) {
          loading.remove();
          if (disposed) return;
          var rows = res.rows || [];
          if (!rows.length) {
            host.appendChild(el("div", "np-empty", "还没有发送记录"));
            return;
          }
          rows.forEach(function (row) {
            var item = el("div", "np-log");
            var at = new Date(row.at);
            var time = String(at.getHours()).padStart(2, "0") + ":" + String(at.getMinutes()).padStart(2, "0");
            item.appendChild(el("div", "t", time));
            var main = el("div", "");
            main.style.flex = "1";
            main.style.minWidth = "0";
            main.appendChild(el("div", "", row.title || (EVENT_META[row.kind] || {}).label || row.kind));
            if (row.sessionTitle) main.appendChild(el("div", "sub", row.sessionTitle));
            if (row.results) {
              var fails = row.results.filter(function (r) {
                return !r.ok;
              });
              if (fails.length) main.appendChild(el("div", "sub", fails.map(function (r) {
                return CHANNEL_META[r.channel].label + " 失败：" + (r.error || "");
              }).join(" / ")));
            }
            item.appendChild(main);
            var pill;
            if (row.skipped) pill = el("span", "np-pill", "已跳过");
            else {
              var okAll = (row.results || []).every(function (r) {
                return r.ok;
              });
              pill = el("span", "np-pill" + (okAll ? " ok" : " fail"), (row.results || []).map(function (r) {
                return CHANNEL_META[r.channel].label;
              }).join(" ") || "—");
            }
            item.appendChild(pill);
            host.appendChild(item);
          });
        })
        .catch(function (err) {
          loading.textContent = "读取记录失败：" + err.message;
        });
    }

    function renderBody() {
      if (!refs.body) return;
      refs.body.innerHTML = "";
      refs.body.appendChild(refs.banner);
      if (!config) {
        refs.body.appendChild(el("div", "np-empty", "正在连接插件服务…"));
        return;
      }
      if (activeTab === "chan") renderChannels();
      else if (activeTab === "ev") renderEvents();
      else renderLog();
    }

    function setTab(tab) {
      closeModal();
      activeTab = tab;
      Array.prototype.forEach.call(refs.tabs.children, function (btn) {
        btn.classList.toggle("on", btn.dataset.tab === tab);
      });
      renderBody();
    }

    function save(onDone) {
      if (!config || !refs.saveBtn) return;
      var btn = refs.saveBtn;
      btn.disabled = true;
      post("config", config)
        .then(function (res) {
          config = res.config;
          secrets = res.secrets || secrets;
          notice("");
          refs.saved.classList.add("on");
          clearTimeout(refs.savedTimer);
          refs.savedTimer = setTimeout(function () {
            refs.saved.classList.remove("on");
          }, 2000);
          renderBody();
        })
        .catch(function (err) {
          notice("保存失败：" + err.message);
        })
        .then(function () {
          btn.disabled = false;
          if (typeof onDone === "function") onDone();
        });
    }

    function load() {
      return api("config")
        .then(function (res) {
          config = res.config;
          if (res.secrets) secrets = res.secrets;
          notice("");
        })
        .catch(function (err) {
          notice("连不上插件服务：" + err.message + "。停用再启用一次插件试试。");
        })
        .then(function () {
          renderBody();
        });
    }

    function buildUi() {
      var style = document.createElement("style");
      style.id = STYLE_ID;
      style.textContent = STYLE;
      document.head.appendChild(style);

      // Esc 关弹框（弹框不在面板 DOM 里，所以监听挂在 document 上）。
      document.addEventListener("keydown", function (ev) {
        if (ev.key !== "Escape") return;
        if (!document.getElementById(MODAL_ID)) return;
        ev.stopPropagation();
        cancelModal();
      });

      // 入口那颗图标改由宿主画（右缘栏的插件托盘），插件不再往 body 里插固定定位的铃铛。
      var panel = el("div");
      panel.id = PANEL_ID;

      var head = el("div", "np-head");
      head.appendChild(el("div", "np-badge", "🔔"));
      head.appendChild(el("div", "np-title", "消息通知"));
      head.appendChild(el("div", "np-ver", "v" + VERSION));
      var close = el("button", "np-x", "\u00d7");
      close.type = "button";
      close.onclick = function () {
        togglePanel(false);
      };
      head.appendChild(close);
      panel.appendChild(head);

      var tabs = el("div", "np-tabs");
      [
        ["chan", "渠道"],
        ["ev", "事件"],
        ["log", "发送记录"],
      ].forEach(function (pair) {
        var btn = el("button", "np-tab" + (pair[0] === activeTab ? " on" : ""), pair[1]);
        btn.type = "button";
        btn.dataset.tab = pair[0];
        btn.onclick = function () {
          setTab(pair[0]);
        };
        tabs.appendChild(btn);
      });
      panel.appendChild(tabs);
      refs.tabs = tabs;

      var body = el("div", "np-body");
      var banner = el("div", "np-banner");
      body.appendChild(banner);
      panel.appendChild(body);
      refs.body = body;
      refs.banner = banner;

      var foot = el("div", "np-foot");
      var saved = el("span", "np-saved", "已保存");
      foot.appendChild(saved);
      refs.saved = saved;
      foot.appendChild(el("div", "np-spacer"));
      var reload = el("button", "np-btn", "重新读取");
      reload.type = "button";
      reload.onclick = function () {
        config = null;
        renderBody();
        load();
      };
      foot.appendChild(reload);
      var saveBtn = el("button", "np-btn primary", "保存");
      saveBtn.type = "button";
      saveBtn.onclick = save;
      foot.appendChild(saveBtn);
      refs.saveBtn = saveBtn;
      panel.appendChild(foot);

      document.body.appendChild(panel);
      refs.panel = panel;

      var toastNode = el("div");
      toastNode.id = TOAST_ID;
      document.body.appendChild(toastNode);
      refs.toast = toastNode;

      renderBody();
    }

    function togglePanel(force) {
      if (!refs.panel) return;
      var open = force == null ? !refs.panel.classList.contains("open") : Boolean(force);
      refs.panel.classList.toggle("open", open);
      if (!open) closeModal();
      if (open) {
        // 看过就是看过了：（面板里有完整的发送记录，入口不再留红点。
        if (entryHandle) entryHandle.setBadge(0);
        load();
      }
    }

    var dispatched = new Set();

    function handleEvent(event) {
      if (disposed || !config || config.enabled === false) return;
      var matrix = config.events[event.kind];
      if (!matrix) return;
      var chosen = ["sms", "mail", "wecom"].filter(function (name) {
        return matrix[name] && config.channels[name] && config.channels[name].on;
      });
      if (!chosen.length) return;
      var key = event.kind + ":" + event.runId + ":" + event.callId;
      if (dispatched.has(key)) return;
      dispatched.add(key);
      if (dispatched.size > 200) dispatched.clear();
      post("notify", { event: event, focused: document.hasFocus() })
        .then(function (res) {
          var done = (res.delivered || []).filter(function (item) {
            return item.ok;
          });
          if (done.length) {
            toast(
              event.title,
              "已推送 " +
                done
                  .map(function (item) {
                    return CHANNEL_META[item.channel].label;
                  })
                  .join(" · "),
            );
            if (entryHandle) entryHandle.setBadge(1);
          }
          if (activeTab === "log" && refs.panel && refs.panel.classList.contains("open")) renderBody();
        })
        .catch(function (err) {
          console.warn("[notify] 推送失败：", err.message);
        });
    }

    exports.apply = function (ctx) {
      // 单实例：启用两次也只有一块面板。
      if (document.getElementById(PANEL_ID)) return function () {};
      buildUi();
      // 入口交给宿主画（右缘栏的插件托盘）：插件只声明一颗铃铛和 open()，
      // 位置、层级、拖动全归宿主 —— 不再需要自己钉右上角、也不跟窗口控制按钮抢位。
      if (ctx && ctx.entries && typeof ctx.entries.register === "function") {
        entryHandle = ctx.entries.register({
          id: "panel",
          label: "消息通知",
          icon: "bell",
          open: function () {
            togglePanel(true);
          },
          // 插件中心右侧：把这块面板直接搬进去（嵌入态由宿主 CSS 接管定位/边框）。
          mount: function (host) {
            var panel = refs.panel;
            if (!panel || !host) return function () {};
            embedHost = host;
            panel.classList.add("is-embedded");
            host.appendChild(panel);
            togglePanel(true);
            return function () {
              embedHost = null;
              panel.classList.remove("is-embedded");
              togglePanel(false);
              // 还回 body：插件自己弹窗（entry.open）的那条路还得能走。
              if (panel.parentNode !== document.body) document.body.appendChild(panel);
            };
          },
        });
      }
      load();
      var off = null;
      if (ctx && ctx.events && typeof ctx.events.on === "function") {
        off = ctx.events.on("*", handleEvent);
      }
      return function () {
        disposed = true;
        if (typeof off === "function") off();
        if (entryHandle) {
          entryHandle.dispose();
          entryHandle = null;
        }
        [PANEL_ID, TOAST_ID, STYLE_ID, MODAL_ID].forEach(function (id) {
          var node = document.getElementById(id);
          if (node) node.remove();
        });
        refs = { panel: null, toast: null, body: null, banner: null, saved: null };
        dispatched.clear();
      };
    };

    return module.exports;
  },
});



