// 桌宠管家 —— 浏览器半（全量配置版）。
//
// 宿主契约：__ModuleLoader__.load({id, factory}) → factory().apply(ctx) →
// ctx.entries.register({open, mount})。数据全部走 host.mjs 的 /api/*，
// 配置目录由 /api/state 的 catalog 给出，模型清单由同一次 state 的 modelOptions 给出，
// 视觉语言与 .workbuddy/scratch/xiaoxiao-pet-manager-prototype-full.html 一致。
//
// 本文件由 gen-client.cjs 注入原型 CSS 生成，之后可直接维护本文件。

window.__ModuleLoader__.load({
  id: "xiaoxiao-pet-manager",
  factory: function () {
    var PLUGIN_ID = "com.nerve.xiaoxiao-pet-manager";
    var API = "laji-plugin://" + PLUGIN_ID + "/__proxy/api/";
    var ROOT_ID = "xxpm-root";
    var ROOT_CLS = ".xxpm-root";
    var STYLE_ID = "xxpm-style";

    var state = null;
    var UI = null;
    var controls = [];
    var SEARCH = [];
    var PAGE_BY_ID = {};
    var DOMAINS = [];
    var MENU_NODES = [];
    var FEATURES = [];
    var MODEL_OPTIONS = [];
    var PREFS = {};
    var activeDomain = "";
    var activeTab = 0;
    var searchBound = false;
    var modalEl = null;
    var embeddedEl = null;
    var entryHandle = null;
    var resizeHandler = null;
    var themeObserver = null;

    var STYLE = [
      // --xxpm-top 由 openModal() 按宿主 .nd-app-chrome 的底边写入：面板从标题栏下面开始，
      // 不去盖右上角的窗口按钮，右上角也不会被原生 titleBarOverlay 压住。
      ROOT_CLS + "{position:fixed;inset:0;top:var(--xxpm-top,0px);z-index:2147483002;display:none;background:var(--scrim);font:14px/1.6 'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;color:var(--text);color-scheme:var(--scheme);-webkit-app-region:no-drag}",
      ROOT_CLS + ".open{display:block}",
      // 面板内任何元素都不参与系统窗口拖动区，否则拖弹框头顶会把整个应用窗口拖走。
      ROOT_CLS + "," + ROOT_CLS + " *{-webkit-app-region:no-drag}",
      // 宿主给全局 input 上了深色底（本面板没有显式背景色的输入框会变黑底白字），
      // 这里按面板自己的暖色系兜底，并显式声明 color-scheme 让复选/滚动条也走浅色。
      ROOT_CLS + " input:not([type=checkbox]):not([type=radio])," + ROOT_CLS + " textarea," + ROOT_CLS + " select{background:var(--surface)!important;color:var(--text)!important;border-color:var(--line)!important;color-scheme:var(--scheme)}",
      ROOT_CLS + " ::-webkit-scrollbar{width:10px;height:10px}",
      ROOT_CLS + " ::-webkit-scrollbar-track{background:transparent}",
      ROOT_CLS + " ::-webkit-scrollbar-thumb{background:var(--scroll);border-radius:8px;border:2px solid transparent;background-clip:padding-box}",
      ROOT_CLS + " ::-webkit-scrollbar-thumb:hover{background:var(--scrollHover);background-clip:padding-box}",
      ROOT_CLS + " .xxpm-window{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:1240px;max-width:calc(100% - 48px);height:840px;max-height:calc(100% - 24px);background:var(--bg);border-radius:16px;overflow:hidden;box-shadow:0 28px 80px rgba(30,20,10,.4)}",
      ROOT_CLS + ".is-embedded{display:block;position:relative;inset:auto;z-index:auto;background:transparent;width:100%;height:100%;min-height:0}",
      ROOT_CLS + ".is-embedded .xxpm-window{position:static;transform:none;width:100%;height:100%;max-width:none;max-height:none;border-radius:0;box-shadow:none}",
      ROOT_CLS + " [data-ui=pages]{flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden}",
      ROOT_CLS + " .page{flex:1;min-height:0}",
      ROOT_CLS + " .tabpage{flex:1;min-height:0}",
      ROOT_CLS + " .xxpm-x{position:absolute;right:12px;top:10px;z-index:5;border:0;background:var(--surface);color:var(--muted);font-size:18px;cursor:pointer;padding:2px 9px;border-radius:8px}",
      ROOT_CLS + " .xxpm-x:hover{background:var(--quietHover);color:var(--text)}",
      ROOT_CLS + " .flash{outline:2px solid var(--accent);outline-offset:2px;background:var(--amberBg)}",
      ROOT_CLS + " .toast{z-index:30}",
      "",
      // 两套配色：浅色是原本的暖米色；.dark 跟随宿主 <html data-theme="dark">。
      // 所有表面/边框/文字都走下面这些变量，样式表里不要再写死颜色，否则暗色下会漏白块。
      ".xxpm-root{",
      "    --scheme:light;color-scheme:light;",
      "    --bg:#faf8f4;--card:#fffdf9;--surface:#fff;--surface2:#fdfbf7;",
      "    --soft:#f7f2ea;--soft2:#eee8de;--soft3:#e3eaed;--hover:#faf4ea;--sel:#f7ecdf;",
      "    --text:#342f2b;--text2:#5f564e;--muted:#70645b;--faint:#a2958a;",
      "    --line:#e5dfd7;--line2:#eee8de;--border:#cfc4b8;--border2:#d9d1c6;--borderHover:#c9ae95;",
      "    --side:#efeae2;--sideBtn:#fff9f0;--sideBtnText:#603b27;",
      "    --accent:#974c32;--accentHover:#7e3c27;--accentSoft:#f7e9df;--quietHover:#eee6db;",
      "    --ok:#436648;--err:#a12b2b;--switchOn:#8a5138;--switchOff:#c6beb5;",
      "    --blue:#4a6b8a;--blueBg:#edf3f8;--amberBg:#fbf1de;--amber:#8a6338;--red:#a1482f;--redBg:#f7e7e3;",
      "    --scroll:#ded5c9;--scrollHover:#cec2b3;--knob:#fff;--toastBg:#352c25;--scrim:rgba(30,24,18,.42);",
      "  }",
      ".xxpm-root.dark{",
      "    --scheme:dark;color-scheme:dark;",
      "    --bg:#201c19;--card:#272220;--surface:#2d2825;--surface2:#2a2522;",
      "    --soft:#2b2521;--soft2:#332c26;--soft3:#2b3034;--hover:#342d26;--sel:#3c2f26;",
      "    --text:#e9e0d5;--text2:#c6baad;--muted:#a89b8e;--faint:#877b70;",
      "    --line:#3a332e;--line2:#332d28;--border:#453d36;--border2:#4a423a;--borderHover:#6d5748;",
      "    --side:#1b1714;--sideBtn:#3a2c23;--sideBtnText:#f0d8c4;",
      "    --accent:#c07a55;--accentHover:#d18b62;--accentSoft:#3a2b22;--quietHover:#37302a;",
      "    --ok:#8ab894;--err:#e08a80;--switchOn:#c07a55;--switchOff:#4a423c;",
      "    --blue:#9dbfd8;--blueBg:#26333d;--amberBg:#3a2e21;--amber:#d9b585;--red:#e79b90;--redBg:#3d2723;",
      "    --scroll:#4a423b;--scrollHover:#5c534a;--knob:#f4efe8;--toastBg:#3b332c;--scrim:rgba(0,0,0,.58);",
      "  }",
      ".xxpm-root *{box-sizing:border-box}",
      ".xxpm-root button,.xxpm-root input,.xxpm-root select,.xxpm-root textarea{font-family:inherit}",
      ".xxpm-root button{cursor:pointer}",
      "",
      ".xxpm-root .app{display:flex;width:100%;height:840px;background:var(--bg);border:1px solid var(--border2);border-radius:16px;overflow:hidden;box-shadow:0 12px 36px rgba(60,45,30,.13)}",
      ".xxpm-root.narrow .app{max-width:700px;margin:0 auto}",
      ".xxpm-root.narrow .stage-head{max-width:700px;margin-left:auto;margin-right:auto}",
      ".xxpm-root.narrow .topbar{padding:0 14px}",
      ".xxpm-root.narrow .search{width:150px}",
      ".xxpm-root.narrow .globalbar{height:auto;min-height:52px;flex-wrap:wrap;padding:8px 14px;gap:7px}",
      ".xxpm-root.narrow .globalbar .title{font-size:14px;flex:none}",
      ".xxpm-root.narrow .globalbar .acts{margin-left:0;width:100%;order:2;flex-wrap:wrap}",
      ".xxpm-root.narrow .globalbar .acts .btn{flex:1;text-align:center;padding:7px 8px}",
      ".xxpm-root.narrow .tabs{padding:9px 14px 0}",
      ".xxpm-root.narrow .tabpage{padding:14px 14px 28px}",
      "",
      ".xxpm-root .side{width:206px;flex:none;background:var(--side);padding:20px 14px 14px;display:flex;flex-direction:column;border-right:1px solid var(--line)}",
      ".xxpm-root .brand{display:flex;align-items:center;gap:9px;font-size:16px;font-weight:650;padding:0 8px 16px}",
      ".xxpm-root .brand .dot{width:25px;height:25px;border-radius:9px;background:var(--accent);position:relative;flex:none}",
      ".xxpm-root .brand .dot::before{content:\"\";position:absolute;width:11px;height:11px;left:5px;top:5px;border:2px solid #fff;border-right-color:transparent;border-bottom-color:transparent;border-radius:50%}",
      ".xxpm-root .nav{display:flex;flex-direction:column;gap:2px;overflow:auto;min-height:0;flex:1}",
      ".xxpm-root .nav button{display:flex;gap:9px;align-items:center;border:0;background:transparent;color:var(--muted);border-radius:9px;padding:8px 11px;width:100%;text-align:left;font-size:13px;font-weight:600;flex:none}",
      ".xxpm-root .nav button:hover{background:rgba(255,249,240,.7)}",
      ".xxpm-root .nav button.on{background:var(--sideBtn);color:var(--sideBtnText)}",
      ".xxpm-root .nav .ico{width:16px;text-align:center;font-size:13px;font-weight:400}",
      ".xxpm-root .side-note{margin-top:10px;border-top:1px solid var(--line2);padding-top:10px;font-size:11px;color:var(--muted);line-height:1.7;flex:none}",
      "",
      ".xxpm-root .main{flex:1;min-width:0;display:flex;flex-direction:column}",
      ".xxpm-root .topbar{height:44px;flex:none;display:flex;align-items:center;gap:10px;padding:0 20px;border-bottom:1px solid var(--line);font-size:12px;color:var(--muted)}",
      ".xxpm-root .topbar .crumb b{color:var(--text);font-weight:600}",
      ".xxpm-root .topbar .right{margin-left:auto;display:flex;align-items:center;gap:8px}",
      ".xxpm-root .search-wrap{position:relative}",
      ".xxpm-root .search{border:1px solid var(--border);border-radius:8px;background:var(--surface);padding:6px 10px;font-size:12px;width:190px;color:var(--text)}",
      ".xxpm-root .results{position:absolute;right:0;top:34px;width:340px;max-height:290px;overflow:auto;background:var(--surface);border:1px solid var(--border2);border-radius:10px;box-shadow:0 10px 26px rgba(50,38,26,.18);z-index:20;display:none}",
      ".xxpm-root .results.on{display:block}",
      ".xxpm-root .results .r{padding:8px 12px;border-bottom:1px solid var(--line2);font-size:12px;cursor:pointer;display:flex;gap:8px;align-items:center}",
      ".xxpm-root .results .r:hover{background:var(--hover)}",
      ".xxpm-root .results .r .rk{margin-left:auto;font:11px Consolas,monospace;color:var(--faint)}",
      ".xxpm-root .results .empty{padding:12px;font-size:12px;color:var(--muted)}",
      ".xxpm-root .globalbar{height:52px;flex:none;display:flex;align-items:center;gap:9px;padding:0 20px;border-bottom:1px solid var(--line);background:var(--surface2)}",
      ".xxpm-root .globalbar .title{font-size:14px;font-weight:650;margin-right:2px}",
      ".xxpm-root .globalbar .acts{margin-left:auto;display:flex;gap:8px;align-items:center}",
      ".xxpm-root .btn{font-size:12.5px;padding:7px 13px;border-radius:8px;border:1px solid var(--line);background:rgba(128,128,128,.08);color:var(--text);white-space:nowrap}",
      ".xxpm-root .btn:hover{background:var(--quietHover)}",
      ".xxpm-root .btn.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}",
      ".xxpm-root .btn.primary:hover{background:var(--accentHover)}",
      ".xxpm-root .btn.mini{padding:5px 10px;font-size:11.5px}",
      "",
      ".xxpm-root .page{display:none;flex:1;min-height:0;flex-direction:column}",
      ".xxpm-root .page.on{display:flex}",
      ".xxpm-root .tabs{display:flex;gap:4px;padding:10px 20px 0;border-bottom:1px solid var(--line);flex:none;overflow-x:auto;flex-wrap:nowrap}",
      ".xxpm-root .tabs button{border:0;background:transparent;color:var(--muted);padding:8px 13px;font-size:12.5px;border-bottom:2px solid transparent;white-space:nowrap;font-weight:600}",
      ".xxpm-root .tabs button:hover{color:var(--text)}",
      ".xxpm-root .tabs button.on{color:var(--accent);border-bottom-color:var(--accent)}",
      ".xxpm-root .tabpage{display:none;flex:1;min-height:0;overflow:auto;padding:16px 20px 32px}",
      ".xxpm-root .tabpage.on{display:block}",
      ".xxpm-root .intro{font-size:12px;color:var(--muted);margin:0 0 14px;line-height:1.8}",
      ".xxpm-root .group{max-width:940px;margin:0 0 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:13px 16px 16px}",
      ".xxpm-root .group h3{margin:0 0 12px;font-size:12.5px;font-weight:700;letter-spacing:.05em;color:var(--muted);display:flex;align-items:center;gap:8px}",
      ".xxpm-root .group h3::before{content:\"\";width:3px;height:13px;border-radius:2px;background:var(--accent)}",
      ".xxpm-root .form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px 22px}",
      ".xxpm-root.narrow .form{grid-template-columns:1fr}",
      ".xxpm-root .field{display:flex;flex-direction:column;gap:6px;font-weight:600;font-size:12.5px;min-width:0;position:relative}",
      ".xxpm-root .field.wide{grid-column:1/-1}",
      ".xxpm-root .field.dirty .flabel::after{content:\"\";display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--accent);margin-left:6px;vertical-align:middle}",
      ".xxpm-root .flabel{display:flex;align-items:center;gap:6px;flex-wrap:wrap}",
      ".xxpm-root .key{font-weight:400;font-size:10px;color:var(--faint);font-family:Consolas,Monaco,monospace;letter-spacing:0}",
      ".xxpm-root .badge{font-size:10px;font-weight:400;border-radius:999px;padding:1px 7px;background:var(--soft2);color:var(--muted)}",
      ".xxpm-root .badge.restart{background:var(--redBg);color:var(--red)}",
      ".xxpm-root .badge.secret{background:var(--amberBg);color:var(--amber)}",
      ".xxpm-root .badge.global{background:var(--blueBg);color:var(--blue)}",
      ".xxpm-root .line{display:flex;align-items:center;gap:8px}",
      ".xxpm-root .field input[type=range]{accent-color:var(--accent);width:100%;min-width:0}",
      ".xxpm-root .field input[type=number],.xxpm-root .field input[type=text],.xxpm-root .field input[type=password],.xxpm-root .field select,.xxpm-root .field textarea{width:100%;font-size:12.5px;padding:6px 9px;border:1px solid var(--border);border-radius:6px;background:var(--surface);color:var(--text);min-width:0}",
      ".xxpm-root .field input[type=number]{width:88px;flex:none}",
      ".xxpm-root .field textarea{min-height:72px;resize:vertical;line-height:1.7}",
      ".xxpm-root .field input[type=color]{width:44px;height:30px;padding:2px;border:1px solid var(--border);border-radius:6px;background:var(--surface)}",
      ".xxpm-root .field .path{display:flex;gap:6px}",
      ".xxpm-root .field .path input{flex:1}",
      ".xxpm-root .unit{font-size:11.5px;font-weight:400;color:var(--muted);flex:none}",
      ".xxpm-root .field.toggle{flex-direction:row;align-items:center;min-height:30px}",
      ".xxpm-root .toggle{display:flex;align-items:center;justify-content:space-between;width:100%;gap:8px;cursor:pointer}",
      ".xxpm-root .sw{position:relative;display:block;flex:none;width:36px;height:21px}",
      ".xxpm-root .sw input{position:absolute;inset:0;width:100%;height:100%;margin:0;opacity:0;cursor:pointer;z-index:1}",
      ".xxpm-root .sw i{display:block;width:36px;height:21px;border-radius:999px;background:var(--switchOff);transition:background .16s}",
      ".xxpm-root .sw i::after{content:\"\";position:absolute;left:3px;top:3px;width:15px;height:15px;border-radius:50%;background:var(--knob);box-shadow:0 1px 3px rgba(0,0,0,.2);transition:transform .16s}",
      ".xxpm-root .sw input:checked + i{background:var(--switchOn)}",
      ".xxpm-root .sw input:checked + i::after{transform:translateX(15px)}",
      ".xxpm-root .actrow{display:flex;gap:8px;flex-wrap:wrap;align-items:center}",
      ".xxpm-root .actbtn{font-size:12px;padding:6px 12px;border-radius:7px;border:1px solid var(--line);background:var(--surface);color:var(--text)}",
      ".xxpm-root .actbtn:hover{background:var(--quietHover)}",
      ".xxpm-root .note{grid-column:1/-1;font-size:11.5px;color:var(--muted);font-weight:400;background:var(--soft);border-radius:8px;padding:8px 11px;line-height:1.7}",
      ".xxpm-root .flash{outline:2px solid var(--accent) !important;outline-offset:3px;border-radius:8px}",
      "",
      "  /* 总览 */",
      ".xxpm-root .metric-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:16px}",
      ".xxpm-root .metric{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:11px 15px}",
      ".xxpm-root .metric .n{font-size:22px;font-weight:650;line-height:1.2}",
      ".xxpm-root .metric .l{font-size:11.5px;color:var(--muted);margin-top:2px}",
      ".xxpm-root .metric.hl{background:var(--accentSoft);border-color:var(--border2)}",
      ".xxpm-root .dom-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:11px;margin-bottom:18px}",
      ".xxpm-root .dom{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px;cursor:pointer}",
      ".xxpm-root .dom:hover{border-color:var(--borderHover);background:var(--surface)af1}",
      ".xxpm-root .dom h4{margin:0 0 6px;font-size:13.5px;font-weight:650;display:flex;align-items:center;gap:7px}",
      ".xxpm-root .dom h4 span{margin-left:auto;font-size:11px;color:var(--muted);font-weight:400}",
      ".xxpm-root .dom p{margin:0;font-size:11.5px;color:var(--muted);line-height:1.7}",
      ".xxpm-root .dom .pills{margin-top:8px;display:flex;gap:5px;flex-wrap:wrap}",
      ".xxpm-root .pill{font-size:10.5px;background:var(--soft2);border-radius:999px;padding:2px 8px;color:var(--muted)}",
      ".xxpm-root table{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden;table-layout:fixed}",
      ".xxpm-root th,.xxpm-root td{text-align:left;padding:8px 11px;border-bottom:1px solid var(--line2);font-size:12px;vertical-align:top}",
      ".xxpm-root th{background:var(--soft2);font-size:11.5px;font-weight:600;color:var(--muted)}",
      ".xxpm-root tr:last-child td{border-bottom:0}",
      "",
      "  /* 菜单编排 */",
      // 两栏靠 flex-wrap 自己塌：面板窄到放不下 460+240 时右栏换行，别把预览列压出右边缘。
      ".xxpm-root .menu-editor{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-start}",
      ".xxpm-root .me-left{flex:1 1 460px}",
      ".xxpm-root .me-right{flex:1 1 300px;min-width:240px}",
      ".xxpm-root .me-left,.xxpm-root .me-right{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px;min-width:0}",
      ".xxpm-root .me-tools{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px}",
      ".xxpm-root .me-tools button{font-size:11.5px;padding:5px 9px;border:1px solid var(--line);border-radius:6px;background:var(--soft);color:var(--text)}",
      ".xxpm-root .me-tools button:hover{background:var(--quietHover)}",
      ".xxpm-root .me-list{max-height:410px;overflow:auto;border:1px solid var(--line2);border-radius:8px}",
      ".xxpm-root .me-row{display:flex;align-items:center;gap:7px;padding:5px 9px;border-bottom:1px solid var(--line2);font-size:12px;min-height:31px}",
      ".xxpm-root .me-row:last-child{border-bottom:0}",
      ".xxpm-root .me-row:hover{background:var(--hover)}",
      ".xxpm-root .me-row.sel{background:var(--sel)}",
      // 未勾选的项在左栏压暗：这样「左栏勾选 → 右栏预览」一眼能对上，不会以为两边不同步。
      ".xxpm-root .me-row.off{opacity:.5}",
      ".xxpm-root .me-row.off.sel{opacity:.75}",
      ".xxpm-root .me-row.sub{font-weight:650;background:var(--soft)}",
      ".xxpm-root .me-row.child{padding-left:28px;color:var(--text2)}",
      ".xxpm-root .me-row.sep{color:var(--faint);font-style:italic}",
      ".xxpm-root .me-row input[type=checkbox]{accent-color:var(--accent);flex:none}",
      ".xxpm-root .me-row .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}",
      ".xxpm-root .me-row .nm b{font-weight:600}",
      ".xxpm-root .me-row .al{font-size:10.5px;color:var(--accent);background:var(--accentSoft);border-radius:999px;padding:1px 6px}",
      ".xxpm-root .me-row .mv{border:0;background:transparent;color:var(--faint);font-size:11px;padding:0 3px}",
      ".xxpm-root .me-row .mv:hover{color:var(--accent)}",
      ".xxpm-root .me-row .mdel{margin-left:auto;flex:none;border:0;background:transparent;color:var(--faint);font-size:12px;line-height:1;padding:4px 6px;border-radius:5px;cursor:pointer}",
      ".xxpm-root .me-row .mdel:hover{background:var(--redBg);color:var(--err)}",
      ".xxpm-root .me-row .mdel:disabled{opacity:.25;cursor:default}",
      ".xxpm-root .me-preview{background:var(--soft);border-radius:9px;padding:10px;min-height:220px}",
      ".xxpm-root .ctx{background:var(--surface);border:1px solid var(--border2);border-radius:9px;padding:5px;box-shadow:0 5px 14px rgba(60,45,30,.12);max-width:250px}",
      ".xxpm-root .ctx .ci{padding:6px 10px;border-radius:5px;font-size:12px;display:flex;align-items:center;gap:7px}",
      ".xxpm-root .ctx .ci:hover{background:var(--hover)}",
      ".xxpm-root .ctx .ci.child{padding-left:22px;font-size:11.5px;color:var(--text2)}",
      ".xxpm-root .ctx .csep{height:1px;background:var(--line2);margin:4px 6px}",
      ".xxpm-root .ctx .cgrp{font-size:10.5px;color:var(--faint);padding:5px 10px 2px}",
      ".xxpm-root .ctx .cmore{padding:5px 10px;font-size:11px;color:var(--faint)}",
      ".xxpm-root .ctx .csub{margin-left:auto;font-size:10.5px;color:var(--faint)}",
      ".xxpm-root .me-ptitle{font-size:11.5px;color:var(--muted);margin-bottom:8px}",
      ".xxpm-root .ctx .cempty{padding:12px 10px;font-size:11.5px;color:var(--faint);text-align:center}",
      ".xxpm-root .me-count{font-size:11px;color:var(--muted);margin-top:8px;text-align:right}",
      ".xxpm-root .me-hint{font-size:11px;color:var(--muted);margin-top:9px;line-height:1.7}",
      "",
      "  /* 功能卡片 */",
      ".xxpm-root .feature-tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:13px}",
      ".xxpm-root .fcat{margin-bottom:14px}",
      ".xxpm-root .fcat h4{margin:0 0 8px;font-size:12px;color:var(--muted);font-weight:600}",
      ".xxpm-root .fgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:9px}",
      ".xxpm-root .fcard{border:1px solid var(--line);border-radius:10px;background:var(--surface);padding:10px 12px;display:flex;align-items:flex-start;gap:9px;cursor:pointer}",
      ".xxpm-root .fcard:hover{border-color:var(--borderHover)}",
      ".xxpm-root .fcard.on{background:var(--accentSoft);border-color:var(--border2)}",
      ".xxpm-root .fcard .txt{flex:1;min-width:0}",
      ".xxpm-root .fcard b{display:block;font-size:12.5px;font-weight:600}",
      ".xxpm-root .fcard small{display:block;font-size:11px;color:var(--muted);line-height:1.5;margin-top:2px}",
      "",
      "  /* 列表编辑器 */",
      ".xxpm-root .list-editor{border:1px solid var(--line);border-radius:9px;overflow:hidden}",
      ".xxpm-root .li-row{display:flex;gap:8px;align-items:center;padding:8px 10px;border-bottom:1px solid var(--line2);background:var(--surface)}",
      ".xxpm-root .li-row:last-child{border-bottom:0}",
      ".xxpm-root .li-row input{flex:1;min-width:0;border:1px solid var(--border);border-radius:6px;padding:5px 8px;font-size:12px}",
      ".xxpm-root .li-row .del{border:0;background:transparent;color:var(--err);font-size:12px}",
      ".xxpm-root .li-add{margin-top:8px}",
      "",
      "  /* 角色包 */",
      ".xxpm-root .pack-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:11px}",
      ".xxpm-root.narrow .pack-grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}",
      ".xxpm-root .pack{background:var(--surface);border:1px solid var(--line);border-radius:12px;overflow:hidden}",
      ".xxpm-root .pack.current{border-color:var(--accent);box-shadow:0 0 0 2px rgba(151,76,50,.10)}",
      ".xxpm-root .pack .ph{height:110px;background:var(--soft2);display:flex;align-items:flex-end;justify-content:center;overflow:hidden;position:relative}",
      ".xxpm-root .pack:nth-child(even) .ph{background:var(--soft3)}",
      ".xxpm-root .pack .ph svg{height:106px;width:110px;transform:translateY(5px)}",
      ".xxpm-root .pack-flag{position:absolute;top:7px;left:7px;font-size:10px;color:#fff;background:var(--accent);border-radius:999px;padding:2px 8px}",
      ".xxpm-root .pack .pb{padding:9px 11px}",
      ".xxpm-root .pack-line{display:flex;align-items:center;justify-content:space-between;gap:6px}",
      ".xxpm-root .pack b{font-size:13px}",
      ".xxpm-root .pack .pc{display:flex;gap:6px;align-items:center;flex-wrap:wrap;margin-top:9px}",
      ".xxpm-root .pack .pc button{flex:1;min-width:0;white-space:nowrap;text-align:center;font-size:11.5px;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--surface);color:var(--text)}",
      ".xxpm-root .pack .pc button.pk-main{flex:0 0 100%}",
      ".xxpm-root .pack .pc button.on{background:var(--accent);color:#fff;border-color:var(--accent)}",
      "",
      ".xxpm-root .readonly{max-width:940px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-bottom:14px}",
      ".xxpm-root .readonly h4{margin:0 0 8px;font-size:13px}",
      ".xxpm-root .readonly p{margin:4px 0;font-size:12px;color:var(--muted)}",
      ".xxpm-root .diff{max-width:940px;margin-top:14px;border:1px dashed var(--border2);border-radius:10px;background:var(--soft);padding:12px 15px;display:none}",
      ".xxpm-root .diff.on{display:block}",
      ".xxpm-root .diff h4{margin:0 0 8px;font-size:12px;color:var(--muted);font-weight:600}",
      ".xxpm-root .diff pre{margin:0;font:11.5px/1.7 Consolas,Monaco,monospace;color:var(--text2);white-space:pre-wrap;word-break:break-all;max-height:260px;overflow:auto}",
      ".xxpm-root .mdl{display:flex;flex-direction:column;gap:14px;max-width:940px}",
      ".xxpm-root .mdl-head{display:flex;align-items:center;justify-content:flex-end;gap:8px}",
      ".xxpm-root .mdl-group>h4{margin:0 0 9px;font-size:12.5px;font-weight:600;color:var(--muted)}",
      ".xxpm-root .mdl-cards{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px}",
      ".xxpm-root .mdl-card{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}",
      ".xxpm-root .mdl-card:hover{border-color:var(--borderHover)}",
      ".xxpm-root .mdl-card.off{opacity:.62}",
      ".xxpm-root .mdl-card-main{flex:1;min-width:0;cursor:pointer}",
      ".xxpm-root .mdl-card-name{display:flex;align-items:center;gap:8px;font-size:13.5px;font-weight:600;color:var(--text);line-height:1.5}",
      ".xxpm-root .mdl-card-meta{margin-top:2px;font-size:11.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}",
      ".xxpm-root .mdl-card-ops{display:flex;align-items:center;gap:12px;flex:none}",
      ".xxpm-root .mdl-pill{flex:none;border:1px solid var(--line);background:transparent;color:var(--muted);font-size:11px;line-height:1.5;padding:2px 8px;border-radius:999px;cursor:pointer}",
      ".xxpm-root .mdl-pill:hover{border-color:var(--accent);color:var(--accent)}",
      ".xxpm-root .mdl-pill.on{background:var(--accentSoft);border-color:transparent;color:var(--accent);cursor:default;font-weight:600}",
      ".xxpm-root .mdl-del{border:0;background:transparent;color:var(--muted);font-size:11.5px;padding:2px;cursor:pointer}",
      ".xxpm-root .mdl-del:hover{color:var(--err)}",
      ".xxpm-root .mdl-empty{margin:0;padding:18px 4px;font-size:12.5px;color:var(--muted)}",
      ".xxpm-root .mdlg{width:min(600px,calc(100% - 48px))}",
      ".xxpm-root .mdlg .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}",
      ".xxpm-root .mdlg .fld{display:flex;flex-direction:column;gap:6px;min-width:0}",
      ".xxpm-root .mdlg .fld.wide{grid-column:1 / -1}",
      ".xxpm-root .mdlg .fld>span{font-size:12px;color:var(--muted)}",
      ".xxpm-root .mdlg input,.xxpm-root .mdlg select{height:34px;box-sizing:border-box;border:1px solid var(--line);border-radius:8px;background:var(--surface);padding:0 10px;font-size:13px;color:var(--text);outline:none;width:100%}",
      ".xxpm-root .mdlg input:focus,.xxpm-root .mdlg select:focus{border-color:var(--accent)}",
      ".xxpm-root .mdlg .with-btn{display:flex;gap:6px}",
      ".xxpm-root .mdlg .with-btn input{flex:1;min-width:0}",
      ".xxpm-root .mdlg .with-btn .btn{flex:none;padding:0 9px}",
      ".xxpm-root .mdlg .acts{padding-top:2px}",
      ".xxpm-root .mdlg .mdlg-result{font-size:11.5px;color:var(--muted);overflow-wrap:anywhere;max-width:300px}",
      ".xxpm-root .mdlg .mdlg-result.ok{color:var(--ok)}",
      ".xxpm-root .mdlg .mdlg-result.err{color:var(--err)}",
      // 弹层用 absolute 关在面板里（root 就是定位父级），不能用 fixed —— fixed 的包含块是
      // 整个渲染视口，会伸到标题栏下面去：遮住右上角窗口按钮，头顶还变成系统拖动区。
      ".xxpm-root .xxpm-modal,.xxpm-root .xxpm-alert{position:absolute;inset:0;z-index:50;display:none;align-items:center;justify-content:center;background:var(--scrim);-webkit-app-region:no-drag}",
      ".xxpm-root .xxpm-modal.on,.xxpm-root .xxpm-alert.on{display:flex}",
      ".xxpm-root .xxpm-modal .dlg,.xxpm-root .xxpm-alert .dlg{width:min(560px,calc(100% - 48px));background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:0 26px 70px rgba(30,20,10,.32);padding:20px 22px 18px;display:flex;flex-direction:column;gap:12px}",
      ".xxpm-root .xxpm-modal .dlg h4,.xxpm-root .xxpm-alert .dlg h4{margin:0;font-size:15px;font-weight:650;color:var(--text)}",
      ".xxpm-root .xxpm-alert{z-index:60}",
      ".xxpm-root .xxpm-alert .dlg{width:min(380px,calc(100% - 48px))}",
      ".xxpm-root .xxpm-alert .dlg p{margin:0;font-size:13px;line-height:1.7;color:var(--text);white-space:pre-wrap;word-break:break-word}",
      ".xxpm-root .xxpm-alert .dlg p.error{color:var(--err)}",
      ".xxpm-root .xxpm-alert .dlg .acts{display:flex;justify-content:flex-end;align-items:center}",
      ".xxpm-root .xxpm-modal .dlg textarea{width:100%;height:190px;box-sizing:border-box;resize:vertical;border:1px solid var(--line);border-radius:9px;background:var(--surface);padding:10px 12px;font:13px/1.75 'PingFang SC','Microsoft YaHei','Segoe UI',sans-serif;color:var(--text);outline:none}",
      ".xxpm-root .xxpm-modal .dlg textarea:focus{border-color:var(--accent)}",
      ".xxpm-root .xxpm-modal .dlg .acts{display:flex;align-items:center;gap:8px;flex-wrap:wrap}",
      ".xxpm-root .xxpm-modal .dlg .acts .left{margin-right:auto}",
      ".xxpm-root .toast{position:absolute;left:50%;bottom:30px;transform:translate(-50%,14px);background:var(--toastBg);color:#fff;border-radius:10px;padding:10px 17px;font-size:12.5px;opacity:0;pointer-events:none;transition:.22s;z-index:99}",
      ".xxpm-root .toast.on{opacity:1;transform:translate(-50%,0)}",
      "",
      // 放在原型 CSS 之后：同特异性时由这些规则兜底。
      ROOT_CLS + " .app{height:100%;border:0;border-radius:0;box-shadow:none}",
      ROOT_CLS + " .page,.tabpage{flex:1;min-height:0}",
      ROOT_CLS + " .me-row input[type=text]{flex:1;min-width:0;border:1px solid var(--line);border-radius:5px;padding:3px 6px;font-size:11.5px;color:var(--text)}",
      ROOT_CLS + " .me-preview .ctx{max-width:none}",
      ROOT_CLS + " .ctx .ci.off{opacity:.4;text-decoration:line-through}",
      ROOT_CLS + " .fcard input[type=checkbox]{accent-color:var(--accent);flex:none}",
      ROOT_CLS + " .pack .ph>span.xxpm-fallback{font-size:34px;opacity:.55;align-self:center}",
      ROOT_CLS + " .pack .ph img,.pack .ph video{max-height:100%;max-width:100%;object-fit:contain}",
      ROOT_CLS + " .pack{display:flex;flex-direction:column}",
      ROOT_CLS + " .pack .pb{flex:1;display:flex;flex-direction:column}",
      ROOT_CLS + " .pack .pc{margin-top:auto}",
      // 宿主样式库（packages/laji-ui/src/styles.css 等）里有全局 .app / .btn / .brand /
      // .badge 规则。CSS 层叠是逐属性的：我们没显式写的属性会被宿主补上，最致命的是
      // `.app{flex-direction:column}` —— 侧栏与主区上下叠，页面区被压到视口外全白。
      // 这里用更高特异性 + !important 把骨架锁死，不受宿主样式加载顺序影响。
      ROOT_CLS + " .xxpm-window>.app{display:flex!important;flex-direction:row!important;flex-wrap:nowrap!important;align-items:stretch!important;width:100%!important;height:100%!important;min-height:0!important;border:0!important;border-radius:0!important;box-shadow:none!important;overflow:hidden!important}",
      ROOT_CLS + " .app>.side{flex:0 0 206px!important;width:206px!important;min-height:0!important;display:flex!important;flex-direction:column!important}",
      ROOT_CLS + " .app>.main{flex:1 1 auto!important;min-width:0!important;min-height:0!important;display:flex!important;flex-direction:column!important}",
      ROOT_CLS + " .main>.topbar," + ROOT_CLS + " .main>.globalbar{flex:none!important}",
      ROOT_CLS + " .main>[data-ui=pages]{flex:1 1 auto!important;min-height:0!important;display:flex!important;flex-direction:column!important;overflow:hidden!important}",
      ROOT_CLS + " .page.on{display:flex!important;flex-direction:column!important;flex:1 1 auto!important;min-height:0!important}",
      ROOT_CLS + " .tabpage.on{display:block!important;flex:1 1 auto!important;min-height:0!important;overflow:auto!important}",
      ROOT_CLS + " .btn{display:inline-flex!important;align-items:center!important;justify-content:center!important;gap:0!important;line-height:1.6!important;text-transform:none!important;letter-spacing:normal!important}",
      ROOT_CLS + " .brand," + ROOT_CLS + " .badge{text-transform:none!important;letter-spacing:normal!important}",
    ].join("\n");

    // ---------------------------------------------------------------- 工具

    function el(tag, cls, text) {
      var node = document.createElement(tag);
      if (cls) node.className = cls;
      if (text !== undefined && text !== null) node.textContent = text;
      return node;
    }
    function $(sel, root) { return (root || UI).querySelector(sel); }
    function $$(sel, root) { return Array.prototype.slice.call((root || UI).querySelectorAll(sel)); }
    function clone(o) { return JSON.parse(JSON.stringify(o)); }
    function toast(msg) {
      var t = $(".toast");
      if (!t) return;
      t.textContent = msg;
      t.classList.add("on");
      clearTimeout(toast._t);
      toast._t = setTimeout(function () { t.classList.remove("on"); }, 2000);
    }
    // 保存 / 恢复 / 切换等结果一律走居中弹框，不再往标题下面塞一行小字。
    function fb(msg, isError) {
      if (!msg) return;
      var layer = $(".xxpm-alert", UI);
      if (!layer) {
        layer = el("div", "xxpm-alert");
        var dlg = el("div", "dlg");
        dlg.appendChild(el("h4", null, "提示"));
        dlg.appendChild(el("p"));
        var acts = el("div", "acts");
        var ok = el("button", "btn primary", "好");
        acts.appendChild(ok);
        dlg.appendChild(acts);
        layer.appendChild(dlg);
        UI.appendChild(layer);
        ok.addEventListener("click", function () { layer.classList.remove("on"); });
        layer.addEventListener("mousedown", function (ev) {
          if (ev.target === layer) layer.classList.remove("on");
        });
        document.addEventListener("keydown", function (ev) {
          if (ev.key === "Escape" && layer.classList.contains("on")) layer.classList.remove("on");
        });
      }
      layer.querySelector("h4").textContent = isError ? "操作失败" : "提示";
      var body = layer.querySelector("p");
      body.textContent = String(msg);
      body.classList.toggle("error", Boolean(isError));
      layer.classList.add("on");
    }
    function apiGet(path) {
      return fetch(API + path).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      });
    }
    function apiPost(path, body) {
      return fetch(API + path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body || {}),
      }).then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok || data.ok === false) throw new Error(data.error || "HTTP " + r.status);
          return data;
        });
      });
    }
    function previewUrl(file) { return API + "preview?file=" + encodeURIComponent(file); }
    function flash(node) {
      if (!node) return;
      node.scrollIntoView({ block: "center" });
      node.classList.add("flash");
      setTimeout(function () { node.classList.remove("flash"); }, 1600);
    }

    // ---------------------------------------------------------------- 外壳

    function renderShell(container) {
      container.innerHTML = "";
      var win = el("div", "xxpm-window");
      win.setAttribute("role", "dialog");
      win.setAttribute("aria-label", "桌宠管家");
      var app = el("div", "app");

      var side = el("aside", "side");
      var brand = el("div", "brand");
      brand.appendChild(el("span", "dot"));
      brand.appendChild(el("span", null, "桌宠管家"));
      side.appendChild(brand);
      var nav = el("nav", "nav");
      nav.setAttribute("data-ui", "nav");
      side.appendChild(nav);
      app.appendChild(side);

      var main = el("main", "main");
      var topbar = el("div", "topbar");
      var crumb = el("span", "crumb");
      crumb.appendChild(document.createTextNode("小口袋 / "));
      var crumbName = el("b", null, "");
      crumbName.setAttribute("data-ui", "crumb");
      crumb.appendChild(crumbName);
      topbar.appendChild(crumb);
      var right = el("div", "right");
      var wrap = el("div", "search-wrap");
      var search = el("input", "search");
      search.setAttribute("data-ui", "search");
      search.placeholder = "搜索设置";
      search.autocomplete = "off";
      var results = el("div", "results");
      results.setAttribute("data-ui", "results");
      wrap.appendChild(search);
      wrap.appendChild(results);
      right.appendChild(wrap);
      topbar.appendChild(right);

      var bar = el("div", "globalbar");
      var title = el("span", "title", "我的角色");
      title.setAttribute("data-ui", "title");
      bar.appendChild(title);
      var acts = el("div", "acts");
      var save = el("button", "btn primary", "保存设置");
      save.setAttribute("data-ui", "save");
      var reset = el("button", "btn", "恢复默认");
      reset.setAttribute("data-ui", "reset");
      acts.appendChild(save);
      acts.appendChild(reset);
      bar.appendChild(acts);

      var pages = el("div", "");
      pages.setAttribute("data-ui", "pages");
      main.appendChild(topbar);
      main.appendChild(bar);
      main.appendChild(pages);
      app.appendChild(main);
      win.appendChild(app);

      var closer = el("button", "xxpm-x", "✕");
      closer.setAttribute("aria-label", "关闭");
      closer.addEventListener("click", function () { container.classList.remove("open"); });
      win.appendChild(closer);
      win.appendChild(el("div", "toast"));
      container.appendChild(win);

      save.addEventListener("click", saveSettings);
      reset.addEventListener("click", resetSettings);
      container.addEventListener("mousedown", function (e) {
        if (e.target === container) container.classList.remove("open");
      });
      container.addEventListener("click", function (e) {
        if (!e.target.closest(".search-wrap")) results.classList.remove("on");
      });

      resizeHandler = function () { applyWidth(); };
      window.addEventListener("resize", resizeHandler);
    }

    function applyWidth() {
      if (!UI) return;
      var win = $(".xxpm-window");
      UI.classList.toggle("narrow", Boolean(win) && win.clientWidth < 900);
    }

    // ---------------------------------------------------------------- 控件注册

    function reg(f, node, get, initial, loc, payload, set, def) {
      var c = {
        f: f, node: node, get: get, initial: initial,
        def: def === undefined ? initial : def,
        loc: loc, payload: payload || null, set: set || null,
      };
      controls.push(c);
      if (f && f.k) SEARCH.push({ label: f.l || "", key: f.k, loc: loc, node: node });
      return c;
    }

    function fieldValue(f) {
      if (f.k && Object.prototype.hasOwnProperty.call(PREFS, f.k)) return PREFS[f.k];
      return f.d;
    }

    function buildField(f, loc) {
      var cell = el("div", "field" + (f.t === "toggle" ? " toggle" : "") + (f.wide ? " wide" : ""));
      var cur = fieldValue(f);
      var get, initial, def = f.d;

      if (f.t === "action") {
        var ab = el("button", "actbtn", f.l);
        ab.addEventListener("click", function () { toast(f.l); });
        cell.appendChild(ab);
        return cell;
      }
      if (f.t === "note") return null;
      if (f.t === "menu") return buildMenuEditor(f, loc, cell, cur);
      if (f.t === "features") return buildFeatures(f, loc, cell, cur);
      if (f.t === "list") return buildList(f, loc, cell, cur);
      if (f.t === "packs") return buildPacks(f, loc, cell, cur);
      if (f.t === "providers") return buildProviders(f, loc, cell, cur);

      if (f.t === "toggle") {
        var lab = el("label", "toggle");
        lab.appendChild(el("span", "flabel", f.l));
        var sw = el("span", "sw");
        var cb = document.createElement("input");
        cb.type = "checkbox";
        cb.checked = Boolean(cur);
        sw.appendChild(cb);
        sw.appendChild(el("i"));
        lab.appendChild(sw);
        cell.appendChild(lab);
        get = function () { return cb.checked; };
        initial = Boolean(cur);
        def = Boolean(f.d);
        cb.addEventListener("change", updateDirty);
      } else if (f.t === "select") {
        cell.appendChild(el("span", "flabel", f.l));
        var sel = document.createElement("select");
        var opts = f.o || [];
        opts.forEach(function (o) {
          var op = document.createElement("option");
          op.value = String(o[0]);
          op.textContent = o[1];
          sel.appendChild(op);
        });
        sel.value = String(cur);
        cell.appendChild(sel);
        get = function () { return sel.value; };
        initial = String(cur);
        def = String(f.d);
        sel.addEventListener("change", updateDirty);
      } else if (f.t === "range" || f.t === "number") {
        cell.appendChild(el("span", "flabel", f.l));
        var line = el("div", "line");
        var rg = null;
        if (f.t === "range") {
          rg = document.createElement("input");
          rg.type = "range";
          rg.min = f.min; rg.max = f.max; rg.step = f.step; rg.value = cur;
          line.appendChild(rg);
        }
        var nu = document.createElement("input");
        nu.type = "number";
        nu.min = f.min; nu.max = f.max; nu.step = f.step; nu.value = cur;
        line.appendChild(nu);
        if (f.u) line.appendChild(el("span", "unit", f.u));
        cell.appendChild(line);
        if (rg) {
          rg.addEventListener("input", function () { nu.value = rg.value; updateDirty(); });
          nu.addEventListener("input", function () { rg.value = nu.value; updateDirty(); });
        } else nu.addEventListener("input", updateDirty);
        get = function () { return Number(nu.value); };
        initial = Number(cur);
        def = Number(f.d);
      } else {
        // text / textarea / password / path / hotkey / color
        cell.appendChild(el("span", "flabel", f.l));
        var inp;
        if (f.t === "textarea") {
          inp = document.createElement("textarea");
        } else {
          inp = document.createElement("input");
          inp.type = f.t === "color" ? "color" : (f.t === "password" ? "password" : "text");
          if (f.t === "hotkey") inp.placeholder = "点击后按键…";
        }
        inp.value = String(cur === undefined || cur === null ? "" : cur);
        if (f.t === "path") {
          var pathWrap = el("div", "path");
          pathWrap.appendChild(inp);
          var br = el("button", "btn mini", "浏览…");
          br.addEventListener("click", function () { toast("浏览…"); });
          pathWrap.appendChild(br);
          cell.appendChild(pathWrap);
        } else cell.appendChild(inp);
        get = function () { return inp.value; };
        initial = inp.value;
        def = String(f.d === undefined || f.d === null ? "" : f.d);
        inp.addEventListener("input", updateDirty);
      }
      reg(f, cell, get, initial, loc, null, null, def);
      return cell;
    }

    // ---------------------------------------------------------------- 复合控件

    // 模型页照小工位「设置 → 模型」：卡片清单 + 「添加模型」弹框。
    // 卡片一条一个 provider（名称 / Model ID · 端点 / 在用 / 开关 / 删除），
    // 添加走弹框：选服务商预设带出端点与默认 Model ID，可先测试连接再加。
    var MODEL_PRESETS = [
      { id: "deepseek", label: "DeepSeek", baseUrl: "https://api.deepseek.com/v1",
        model: "deepseek-v4-flash", models: ["deepseek-v4-flash", "deepseek-v4-pro"], key: true },
      { id: "groq", label: "Groq（免费额度）", baseUrl: "https://api.groq.com/openai/v1",
        model: "qwen/qwen3.6-27b", models: ["qwen/qwen3.6-27b", "llama-3.3-70b-versatile", "mixtral-8x7b-32768"], key: true },
      { id: "gemini", label: "Google Gemini（免费额度）", baseUrl: "https://generativelanguage.googleapis.com/v1beta/openai",
        model: "gemini-2.0-flash", models: ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-2.5-pro"], key: true },
      { id: "openai", label: "OpenAI / OpenAI 兼容", baseUrl: "https://api.openai.com/v1",
        model: "gpt-4o-mini", models: ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"], key: true },
      { id: "qwen", label: "Qwen（DashScope）", baseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model: "qwen-plus", models: ["qwen-plus", "qwen-turbo", "qwen-max"], key: true },
      { id: "opencode", label: "OpenCode Go（订阅）", baseUrl: "https://opencode.ai/zen/go/v1",
        model: "deepseek-v4.1-flash", models: ["deepseek-v4.1-flash", "deepseek-v4-flash"], key: true },
      { id: "ollama", label: "Ollama（本地）", baseUrl: "http://127.0.0.1:11434/v1",
        model: "qwen2.5-coder:7b", models: ["qwen2.5-coder:7b", "deepseek-r1:7b", "llama3.2:latest"], key: false },
      { id: "custom", label: "自定义 OpenAI 兼容网关", baseUrl: "",
        model: "", models: [], key: true },
    ];

    function presetOf(id) {
      for (var i = 0; i < MODEL_PRESETS.length; i += 1) {
        if (MODEL_PRESETS[i].id === id) return MODEL_PRESETS[i];
      }
      return MODEL_PRESETS[MODEL_PRESETS.length - 1];
    }

    // 盘上只存 base_url，没有 preset id：按端点反查服务商，查不到算自定义。
    function presetIdFor(item) {
      var url = String(item.base_url || "").trim().replace(/\/+$/, "");
      for (var i = 0; i < MODEL_PRESETS.length; i += 1) {
        var p = MODEL_PRESETS[i];
        if (p.id === "custom" || !p.baseUrl) continue;
        if (p.baseUrl.replace(/\/+$/, "") === url) return p.id;
      }
      return "custom";
    }

    function providerDraft(raw) {
      var src = raw;
      if (typeof src === "string") {
        try { src = JSON.parse(src); } catch (e) { src = null; }
      }
      var items = src && Array.isArray(src.items) ? src.items : [];
      return {
        active: src && src.active ? String(src.active) : "",
        items: items.map(function (it) {
          var copy = {};
          for (var k in it) if (k !== "hasKey") copy[k] = it[k];
          copy._key = "";
          return copy;
        }),
      };
    }

    function hasProvider(data, id) {
      return data.items.some(function (it) { return it.id === id; });
    }

    function buildProviders(f, loc, cell, cur) {
      cell.className = "field wide";
      var data = providerDraft(cur);

      var root = el("div", "mdl");
      var head = el("div", "mdl-head");
      var refreshBtn = el("button", "btn mini", "刷新");
      var addBtn = el("button", "btn primary mini", "+ 添加模型");
      head.appendChild(refreshBtn);
      head.appendChild(addBtn);
      root.appendChild(head);

      var group = el("div", "mdl-group");
      group.appendChild(el("h4", null, "云端"));
      var list = el("ul", "mdl-cards");
      group.appendChild(list);
      root.appendChild(group);

      // 人设（System Prompt）是每个角色自己的事，不在模型页出现：
      // 这里只列模型清单，提交时也不带 system_prompt —— 盘上的值原样留着。
      cell.appendChild(root);

      // ---------------------------------------------------------------- 弹框

      var old = $(".xxpm-modal.mdlg-layer", UI);
      if (old) old.remove();
      var layer = el("div", "xxpm-modal mdlg-layer");
      var dlg = el("div", "dlg mdlg");
      var dlgTitle = el("h4", null, "添加模型");
      dlg.appendChild(dlgTitle);
      var grid = el("div", "grid");

      function addField(labelText, wide) {
        var box = el("div", "fld" + (wide ? " wide" : ""));
        box.appendChild(el("span", null, labelText));
        grid.appendChild(box);
        return box;
      }

      var nameInp = document.createElement("input");
      nameInp.placeholder = "留空就用服务商名字";
      addField("模型名称").appendChild(nameInp);

      var presetSel = document.createElement("select");
      MODEL_PRESETS.forEach(function (p) {
        var o = document.createElement("option");
        o.value = p.id;
        o.textContent = p.label;
        presetSel.appendChild(o);
      });
      addField("模型服务商").appendChild(presetSel);

      var modelBox = addField("Model ID");
      var modelWrap = el("div", "with-btn");
      var modelInp = document.createElement("input");
      modelInp.setAttribute("list", "xxpm-model-ids");
      modelInp.autocomplete = "off";
      var dl = document.createElement("datalist");
      dl.id = "xxpm-model-ids";
      var listBtn = el("button", "btn mini", "⟳");
      listBtn.type = "button";
      listBtn.title = "从该服务商拉取模型列表";
      modelWrap.appendChild(modelInp);
      modelWrap.appendChild(listBtn);
      modelBox.appendChild(modelWrap);
      modelBox.appendChild(dl);

      var tierSel = document.createElement("select");
      [["standard", "标准档"], ["fast", "快档"]].forEach(function (p) {
        var o = document.createElement("option");
        o.value = p[0];
        o.textContent = p[1];
        tierSel.appendChild(o);
      });
      addField("档位").appendChild(tierSel);

      var urlInp = document.createElement("input");
      urlInp.placeholder = "https://api.example.com/v1";
      addField("端点", true).appendChild(urlInp);

      var keyInp = document.createElement("input");
      keyInp.type = "password";
      keyInp.placeholder = "sk-…";
      addField("API Key", true).appendChild(keyInp);

      dlg.appendChild(grid);

      var acts = el("div", "acts");
      var testBtn = el("button", "btn mini left", "测试连接");
      testBtn.type = "button";
      var testOut = el("span", "mdlg-result");
      var cancelBtn = el("button", "btn", "取消");
      var okBtn = el("button", "btn primary", "添加模型");
      acts.appendChild(testBtn);
      acts.appendChild(testOut);
      acts.appendChild(cancelBtn);
      acts.appendChild(okBtn);
      dlg.appendChild(acts);
      layer.appendChild(dlg);
      UI.appendChild(layer);

      var dialogMode = "add";
      var dialogEntry = null;

      function say(text, isError) {
        testOut.textContent = String(text || "");
        testOut.className = "mdlg-result" + (isError ? " err" : text ? " ok" : "");
      }
      function fillModels(models) {
        dl.innerHTML = "";
        (models || []).forEach(function (m) {
          var o = document.createElement("option");
          o.value = String(m);
          dl.appendChild(o);
        });
      }
      function applyPreset() {
        var p = presetOf(presetSel.value);
        urlInp.value = p.baseUrl;
        modelInp.placeholder = p.model || "填写模型 ID";
        fillModels(p.models);
        keyInp.placeholder = p.key ? "sk-…" : "本地服务通常不需要";
      }

      presetSel.addEventListener("change", function () {
        applyPreset();
        if (dialogMode === "edit") say("");
      });

      function openDialog(mode, entry) {
        dialogMode = mode;
        dialogEntry = entry || null;
        dlgTitle.textContent = mode === "add" ? "添加模型" : "编辑模型";
        okBtn.textContent = mode === "add" ? "添加模型" : "保存";
        say("");
        keyInp.value = "";
        if (mode === "add") {
          presetSel.value = "deepseek";
          nameInp.value = "";
          modelInp.value = "";
          tierSel.value = "standard";
          applyPreset();
        } else {
          presetSel.value = presetIdFor(entry);
          nameInp.value = String(entry.name || "");
          modelInp.value = String(entry.model || "");
          urlInp.value = String(entry.base_url || "");
          tierSel.value = entry.tier === "fast" ? "fast" : "standard";
          fillModels(presetOf(presetSel.value).models);
          modelInp.placeholder = presetOf(presetSel.value).model || "填写模型 ID";
          keyInp.placeholder = entry.hasKey ? "已保存则留空；输入新值将覆盖" : "sk-…";
        }
        layer.classList.add("on");
        nameInp.focus();
      }
      function closeDialog() { layer.classList.remove("on"); }

      cancelBtn.addEventListener("click", closeDialog);
      layer.addEventListener("mousedown", function (ev) {
        if (ev.target === layer) closeDialog();
      });
      document.addEventListener("keydown", function (ev) {
        if (ev.key === "Escape" && layer.classList.contains("on")) closeDialog();
      });

      function readForm() {
        var preset = presetOf(presetSel.value);
        var model = modelInp.value.trim() || preset.model;
        var baseUrl = urlInp.value.trim();
        if (!/^https?:\/\//i.test(baseUrl)) {
          say("端点必须是 http(s) 地址", true);
          return null;
        }
        if (!model) {
          say("请填写 Model ID", true);
          return null;
        }
        return { preset: preset, model: model, baseUrl: baseUrl };
      }

      testBtn.addEventListener("click", function () {
        var form = readForm();
        if (!form) return;
        say("检测中…");
        testBtn.disabled = true;
        apiPost("test-provider", {
          id: dialogMode === "edit" && dialogEntry ? dialogEntry.id : "",
          base_url: form.baseUrl,
          model: form.model,
          chat_path: (dialogEntry && dialogEntry.chat_path) || "/v1/chat/completions",
          api_key: keyInp.value.trim(),
        }).then(function (r) {
          say(r.message || (r.ok ? "连接成功" : "连接失败"), !r.ok);
        }).catch(function (err) {
          say(String(err.message || err), true);
        }).then(function () { testBtn.disabled = false; });
      });

      listBtn.addEventListener("click", function () {
        var baseUrl = urlInp.value.trim();
        if (!/^https?:\/\//i.test(baseUrl)) { say("端点必须是 http(s) 地址", true); return; }
        say("拉取模型列表…");
        listBtn.disabled = true;
        apiPost("list-models", {
          id: dialogMode === "edit" && dialogEntry ? dialogEntry.id : "",
          base_url: baseUrl,
          api_key: keyInp.value.trim(),
        }).then(function (r) {
          if (!r.ok) { say(r.message || "拉取失败", true); return; }
          var models = (r.models || []).slice();
          fillModels(models);
          if (!models.length) say("该服务商没返回模型列表，手动填 Model ID", true);
          else say("拿到 " + models.length + " 个模型，点 Model ID 选");
        }).catch(function (err) {
          say(String(err.message || err), true);
        }).then(function () { listBtn.disabled = false; });
      });

      okBtn.addEventListener("click", function () {
        var form = readForm();
        if (!form) return;
        var tier = tierSel.value === "fast" ? "fast" : "standard";
        var name = (nameInp.value.trim() || form.preset.label).slice(0, 80);
        if (dialogMode === "add") {
          var id = form.preset.id;
          if (hasProvider(data, id)) {
            var n = 2;
            while (hasProvider(data, id + "-" + n)) n += 1;
            id = id + "-" + n;
          }
          data.items.push({
            id: id,
            name: name,
            base_url: form.baseUrl,
            model: form.model,
            tier: tier,
            enabled: true,
            chat_path: "/v1/chat/completions",
            timeout: 60,
            temperature: 0.7,
            max_tokens: 2048,
            verify_ssl: true,
            thinking: "auto",
            reasoning_effort: "high",
            vision_model: "",
            vision_same_as_chat: true,
            vision_base_url: "",
            _key: keyInp.value.trim(),
          });
          if (!data.active) data.active = id;
        } else if (dialogEntry) {
          dialogEntry.name = name;
          dialogEntry.base_url = form.baseUrl;
          dialogEntry.model = form.model;
          dialogEntry.tier = tier;
          if (keyInp.value.trim()) dialogEntry._key = keyInp.value.trim();
        }
        closeDialog();
        drawCards();
        updateDirty();
      });

      // ---------------------------------------------------------------- 卡片

      function drawCards() {
        list.innerHTML = "";
        if (!data.items.length) {
          list.appendChild(el("li", "mdl-empty", "还没有配置模型，点右上角「添加模型」开始。"));
          return;
        }
        data.items.forEach(function (it) {
          var li = el("li", "mdl-card" + (it.enabled === false ? " off" : ""));
          var main = el("div", "mdl-card-main");
          main.title = "点击编辑";
          var nameRow = el("div", "mdl-card-name");
          nameRow.appendChild(document.createTextNode(it.name || it.id));
          var on = it.id === data.active;
          var pill = el("button", "mdl-pill" + (on ? " on" : ""), on ? "在用" : "设为在用");
          pill.type = "button";
          pill.title = on ? "桌宠当前在用这个模型" : "切换桌宠到该模型";
          pill.addEventListener("click", function (ev) {
            ev.stopPropagation();
            if (on) return;
            data.active = it.id;
            if (it.enabled === false) it.enabled = true;
            drawCards();
            updateDirty();
          });
          nameRow.appendChild(pill);
          main.appendChild(nameRow);
          var meta = el("div", "mdl-card-meta");
          meta.textContent = (it.model || "未设置 Model ID") + (it.base_url ? " · " + it.base_url : "");
          main.appendChild(meta);
          main.addEventListener("click", function () { openDialog("edit", it); });
          li.appendChild(main);

          var ops = el("div", "mdl-card-ops");
          var sw = el("label", "sw");
          var cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = it.enabled !== false;
          cb.title = cb.checked ? "已启用" : "已停用";
          cb.addEventListener("change", function () {
            it.enabled = cb.checked;
            li.classList.toggle("off", !cb.checked);
            updateDirty();
          });
          sw.appendChild(cb);
          sw.appendChild(el("i"));
          ops.appendChild(sw);
          var del = el("button", "mdl-del", "删除");
          del.type = "button";
          del.addEventListener("click", function (ev) {
            ev.stopPropagation();
            data.items = data.items.filter(function (x) { return x.id !== it.id; });
            if (data.active === it.id) data.active = data.items[0] ? data.items[0].id : "";
            drawCards();
            updateDirty();
          });
          ops.appendChild(del);
          li.appendChild(ops);
          list.appendChild(li);
        });
      }

      addBtn.addEventListener("click", function () { openDialog("add", null); });

      function snapshot() {
        return {
          active: data.active || (data.items[0] ? data.items[0].id : ""),
          items: data.items.map(function (it) {
            var copy = {};
            for (var k in it) {
              if (k === "_key" || k === "hasKey" || k.charAt(0) === "_") continue;
              copy[k] = it[k];
            }
            copy.api_key = it._key || "";
            return copy;
          }),
        };
      }
      function raw() { return JSON.stringify(snapshot()); }

      function apply(v) {
        data = providerDraft(v);
        if (!data.active && data.items.length) data.active = data.items[0].id;
        drawCards();
      }

      apply(cur);
      var ctl = reg(f, cell, raw, raw(), loc, { parse: true },
        function (v) { apply(v); },
        raw());

      refreshBtn.addEventListener("click", function () {
        refreshBtn.disabled = true;
        apiGet("state").then(function (next) {
          var fresh = next.catalogPrefs && next.catalogPrefs.chat_providers;
          PREFS.chat_providers = fresh;
          apply(fresh);
          ctl.initial = raw();
          updateDirty();
          toast("已刷新");
        }).catch(function (err) {
          fb("刷新失败：" + (err.message || err), true);
        }).then(function () { refreshBtn.disabled = false; });
      });

      return cell;
    }

    function buildMenuEditor(f, loc, cell, cur) {
      cell.className = "field wide";
      // 取值兜底：目录里这个字段曾经漏了 k，fieldValue() 就拿不到真实布局、
      // 退回插件内置模板——面板显示的是默认菜单，保存时还会把用户布局覆盖掉。
      var source = Array.isArray(cur) && cur.length
        ? cur
        : (Array.isArray(PREFS.context_menu_layout) && PREFS.context_menu_layout.length
          ? PREFS.context_menu_layout
          : MENU_NODES);
      var nodes = clone(source);
      var editor = el("div", "menu-editor");
      var left = el("div", "me-left");
      var right = el("div", "me-right");
      var tools = el("div", "me-tools");
      var selected = -1;
      var flat = [];
      var removedStack = [];
      // 桌宠落盘的节点是 resolve 后的形态（只有 type/id/visible/section，别名与
      // label 都被剥掉了），所以显示名要按 id 回内置模板查，别在面板里露英文 id。
      var LABELS = {};
      (function collectLabels(list) {
        (list || []).forEach(function (n) {
          if (!n) return;
          if (n.id) LABELS[n.id] = n.alias || n.label || n.id;
          if (n.children) collectLabels(n.children);
        });
      })(MENU_NODES);
      function titleOf(n) { return n.alias || n.label || LABELS[n.id] || n.id || ""; }
      // 删除不真的把节点 splice 掉：桌宠 resolve_menu_layout 会把「缺席」的默认项
      // 当成旧布局自动补回来（menu_layout.py 的 merge_default_menu_actions）。
      // 所以删掉的项留在数组里，标 removed + visible:false，桌宠读时过滤掉，
      // 面板渲染时也跳过；这样菜单里不会再出现，也不会被补齐。
      function flatten() {
        flat = [];
        nodes.forEach(function (n, i) {
          if (n.removed) return;
          flat.push({ node: n, depth: 0, index: i });
          (n.children || []).forEach(function (c) {
            if (!c.removed) flat.push({ node: c, depth: 1, index: i });
          });
        });
      }
      function locked(n) { return n.id === "modern_settings" || n.id === "quit"; }
      function move(delta) {
        if (selected < 0) return;
        var row = flat[selected];
        if (row.depth !== 0) return;
        var j = row.index + delta;
        if (j < 0 || j >= nodes.length) return;
        var moved = nodes[row.index];
        var tmp = nodes[row.index]; nodes[row.index] = nodes[j]; nodes[j] = tmp;
        // 子菜单会把 flat 的序号和 nodes 的序号拉开，别用 selected += delta 猜。
        flatten();
        selected = flat.findIndex(function (r) { return r.node === moved; });
        draw(); updateDirty();
      }
      function removeAt(i) {
        var row = flat[i];
        if (!row || locked(row.node)) return;
        removedStack.push({ node: row.node, visible: row.node.visible });
        row.node.removed = true;
        row.node.visible = false;
        selected = -1;
        draw(); updateDirty();
      }
      function undoRemove() {
        var last = removedStack.pop();
        if (!last) return;
        delete last.node.removed;
        last.node.visible = last.visible;
        draw(); updateDirty();
      }
      function restoreMenu() {
        nodes = clone(MENU_NODES);
        removedStack = [];
        selected = -1;
        draw(); updateDirty();
      }
      [["↑ 上移", -1], ["↓ 下移", 1]].forEach(function (p) {
        var b = el("button", null, p[0]);
        b.addEventListener("click", function () { move(p[1]); });
        tools.appendChild(b);
      });
      [["↶ 撤销删除", undoRemove], ["恢复默认菜单", restoreMenu]].forEach(function (p) {
        var b = el("button", null, p[0]);
        b.addEventListener("click", p[1]);
        tools.appendChild(b);
      });
      left.appendChild(tools);
      var list = el("div", "me-list");
      left.appendChild(list);
      var preview = el("div", "me-preview");
      right.appendChild(el("div", "me-ptitle", "预览 · 桌宠右键菜单"));
      right.appendChild(preview);
      editor.appendChild(left);
      editor.appendChild(right);
      cell.appendChild(editor);

      // 预览必须是「桌宠真正会画出来的菜单」：未勾选的项一律不画，分隔线按桌宠
      // menu_layout._normalize_separators 的口径去掉开头/连续/结尾的那几根，
      // 子菜单整块算一项（子项全隐藏时桌宠会连父项一起丢掉）。
      function previewItems() {
        var out = [];
        flat.forEach(function (row) {
          if (row.depth) return;
          var n = row.node;
          if (n.visible === false) return;
          if (n.type === "separator") { out.push({ sep: true }); return; }
          if (n.type === "submenu") {
            var kids = (n.children || []).filter(function (c) { return !c.removed && c.visible !== false; });
            if (!kids.length) return;
            out.push({ label: titleOf(n), count: kids.length });
            return;
          }
          out.push({ label: titleOf(n) });
        });
        var items = [];
        out.forEach(function (it) {
          if (it.sep && (!items.length || items[items.length - 1].sep)) return;
          items.push(it);
        });
        while (items.length && items[items.length - 1].sep) items.pop();
        return items;
      }

      function draw() {
        flatten();
        list.innerHTML = "";
        flat.forEach(function (row, i) {
          var line = el("div", "me-row" + (i === selected ? " sel" : ""));
          if (row.depth) line.classList.add("child");
          if (row.node.visible === false) line.classList.add("off");
          var cb = document.createElement("input");
          cb.type = "checkbox";
          cb.checked = row.node.visible !== false;
          cb.addEventListener("change", function () { row.node.visible = cb.checked; draw(); updateDirty(); });
          line.appendChild(cb);
          var alias = document.createElement("input");
          alias.type = "text";
          alias.value = titleOf(row.node);
          alias.addEventListener("input", function () { row.node.alias = alias.value; updateDirty(); });
          line.appendChild(alias);
          if (!locked(row.node)) {
            var del = el("button", "mdel", "✕");
            del.setAttribute("aria-label", "删除");
            del.addEventListener("click", function (e) {
              e.stopPropagation();
              removeAt(i);
            });
            line.appendChild(del);
          }
          line.addEventListener("click", function (e) {
            if (e.target === cb || e.target === alias || e.target.closest("button")) return;
            selected = i; draw();
          });
          list.appendChild(line);
        });
        preview.innerHTML = "";
        var ctx = el("div", "ctx");
        var items = previewItems();
        var shown = 0;
        items.forEach(function (it) {
          if (shown >= 24) return;
          shown += 1;
          if (it.sep) { ctx.appendChild(el("div", "csep")); return; }
          var row = el("div", "ci", it.label);
          if (it.count) row.appendChild(el("span", "csub", "› " + it.count));
          ctx.appendChild(row);
        });
        if (items.length > 24) ctx.appendChild(el("div", "cmore", "还有 " + (items.length - 24) + " 项…"));
        if (!items.length) ctx.appendChild(el("div", "cempty", "一项都没勾，菜单会是空的"));
        preview.appendChild(ctx);
        var onCount = items.filter(function (it) { return !it.sep; }).length;
        var offCount = flat.filter(function (r) { return r.node.visible === false; }).length;
        preview.appendChild(el("div", "me-count",
          "菜单实际 " + onCount + " 项" + (offCount > 0 ? " · 未勾选 " + offCount + " 项" : "")));
      }
      draw();
      var initialRaw = JSON.stringify(nodes);
      reg({ k: "context_menu_layout", l: "菜单编排", d: JSON.stringify(MENU_NODES) },
        cell, function () { return JSON.stringify(nodes); }, initialRaw, loc, { parse: true },
        function (v) {
          try { nodes = JSON.parse(v); removedStack = []; selected = -1; draw(); } catch (e) {}
        },
        JSON.stringify(MENU_NODES));
      return cell;
    }

    function buildFeatures(f, loc, cell, cur) {
      cell.className = "field wide";
      var enabled = Array.isArray(cur)
        ? cur.slice()
        : (Array.isArray(PREFS.feature_activation) ? PREFS.feature_activation.slice() : []);
      var on = {};
      FEATURES.forEach(function (cat) {
        cat.items.forEach(function (it) { on[it[0]] = enabled.indexOf(it[0]) >= 0; });
      });
      var tools = el("div", "feature-tools");
      [["推荐套件", "rec"], ["全部开启", "all"], ["全部关闭", "none"]].forEach(function (p) {
        var b = el("button", "btn mini", p[0]);
        b.addEventListener("click", function () {
          if (p[1] === "all") Object.keys(on).forEach(function (k) { on[k] = true; });
          if (p[1] === "none") Object.keys(on).forEach(function (k) { on[k] = false; });
          if (p[1] === "rec") {
            Object.keys(on).forEach(function (k) { on[k] = false; });
            ["weather", "todo", "divination", "festival", "voice", "chat"].forEach(function (k) { on[k] = true; });
          }
          draw(); updateDirty();
        });
        tools.appendChild(b);
      });
      cell.appendChild(tools);
      var box = el("div");
      cell.appendChild(box);
      function draw() {
        box.innerHTML = "";
        FEATURES.forEach(function (cat) {
          var sec = el("div", "fcat");
          sec.appendChild(el("h4", null, cat.cat));
          var grid = el("div", "fgrid");
          cat.items.forEach(function (it) {
            var card = el("div", "fcard" + (on[it[0]] ? " on" : ""));
            var cb = document.createElement("input");
            cb.type = "checkbox";
            cb.checked = Boolean(on[it[0]]);
            cb.addEventListener("change", function () { on[it[0]] = cb.checked; draw(); updateDirty(); });
            card.appendChild(cb);
            var txt = el("div", "txt");
            txt.appendChild(el("b", null, it[1]));
            card.appendChild(txt);
            grid.appendChild(card);
          });
          sec.appendChild(grid);
          box.appendChild(sec);
        });
      }
      draw();
      var get = function () {
        return JSON.stringify(Object.keys(on).filter(function (k) { return on[k]; }).sort());
      };
      var def = JSON.stringify(FEATURES.reduce(function (a, c) {
        return a.concat(c.items.map(function (it) { return it[0]; }));
      }, []).sort());
      reg({ k: "feature_activation", l: "功能模块启停", d: def }, cell, get, get(), loc,
        { feature: true }, function (v) {
          var list = [];
          try { list = JSON.parse(v); } catch (e) {}
          Object.keys(on).forEach(function (k) { on[k] = list.indexOf(k) >= 0; });
          draw();
        }, def);
      return cell;
    }

    function buildList(f, loc, cell, cur) {
      cell.className = "field wide";
      var items = Array.isArray(cur) ? clone(cur) : clone(f.items || []);
      var box = el("div", "list-editor");
      cell.appendChild(box);
      var add = el("button", "btn mini li-add", "+ 添加应用");
      cell.appendChild(add);
      function draw() {
        box.innerHTML = "";
        items.forEach(function (it, i) {
          var row = el("div", "li-row");
          var nm = document.createElement("input");
          nm.value = it.name || ""; nm.placeholder = "名称";
          var pa = document.createElement("input");
          pa.value = it.path || ""; pa.placeholder = "路径";
          nm.addEventListener("input", function () { it.name = nm.value; updateDirty(); });
          pa.addEventListener("input", function () { it.path = pa.value; updateDirty(); });
          var del = el("button", "del", "移除");
          del.addEventListener("click", function () { items.splice(i, 1); draw(); updateDirty(); });
          row.appendChild(nm); row.appendChild(pa); row.appendChild(del);
          box.appendChild(row);
        });
        if (!items.length) box.appendChild(el("div", "li-row", "暂无应用"));
      }
      add.addEventListener("click", function () {
        items.push({ name: "新应用", path: "", kind: "application" });
        draw(); updateDirty();
      });
      draw();
      var get = function () { return JSON.stringify(items); };
      var def = JSON.stringify(f.items || []);
      reg({ k: f.k, l: f.label || "列表", d: def }, cell, get, get(), loc, { parse: true },
        function (v) { try { items = JSON.parse(v); draw(); } catch (e) {} }, def);
      return cell;
    }

    function buildPacks(f, loc, cell, cur) {
      cell.className = "field wide";
      var grid = el("div", "pack-grid");
      cell.appendChild(grid);
      var chars = state.characters || [];
      function draw() {
        grid.innerHTML = "";
        chars.forEach(function (c) {
          var card = el("div", "pack" + (c.isCurrent ? " current" : ""));
          var ph = el("div", "ph");
          // laji-plugin:// 自定义协议下 <video> 拿不到画面，所以一律用静态图：
          // 有 frameseq 帧就直接读，只有 webm 的交给后端抽帧抠绿缓存。
          var src = c.preview ? previewUrl(c.preview)
            : (c.previewVideo ? API + "thumb?file=" + encodeURIComponent(c.previewVideo) : "");
          if (src) {
            var img = document.createElement("img");
            img.alt = c.displayName;
            img.loading = "lazy";
            img.src = src;
            img.addEventListener("error", function () {
              if (!img.parentNode) return;
              img.parentNode.replaceChild(el("span", "xxpm-fallback", "🐟"), img);
            });
            ph.appendChild(img);
          } else ph.appendChild(el("span", "xxpm-fallback", "🐟"));
          if (c.isCurrent) ph.appendChild(el("span", "pack-flag", "当前角色"));
          card.appendChild(ph);
          var pb = el("div", "pb");
          var line = el("div", "pack-line");
          line.appendChild(el("b", null, c.displayName));
          pb.appendChild(line);
          var pc = el("div", "pc");
          var b = el("button", (c.isCurrent ? "on " : "") + "pk-main",
            c.isCurrent ? "当前角色 ✓" : "设为当前角色");
          b.addEventListener("click", function () {
            if (c.isCurrent) { toast(c.displayName + " 已是当前角色"); return; }
            apiPost("switch", { cid: c.id })
              .then(function () { return refresh(); })
              .then(function () { fb("已切换为 " + c.displayName); })
              .catch(function (err) { fb("切换失败：" + (err.message || err), true); });
          });
          var e = el("button", null, "我的人设");
          e.addEventListener("click", function () { openPersonaDialog(c); });
          pc.appendChild(b); pc.appendChild(e);
          pb.appendChild(pc);
          card.appendChild(pb);
          grid.appendChild(card);
        });
        if (!chars.length) grid.appendChild(el("div", "li-row", "没有找到角色包"));
      }
      draw();
      // 角色切换即时落盘（/api/switch），不进差量 patch。
      reg({ k: "character", l: "当前角色包", d: "" }, cell,
        function () { return String(cur || ""); }, String(cur || ""), loc, { skip: true });
      return cell;
    }

    // ---------------------------------------------------------------- 人设弹框

    function openPersonaDialog(ch) {
      if (!UI || !ch) return;
      var layer = $(".xxpm-modal.persona-layer", UI);
      if (!layer) {
        layer = el("div", "xxpm-modal persona-layer");
        var dlg = el("div", "dlg");
        dlg.appendChild(el("h4", null, "我的人设"));
        var ta = document.createElement("textarea");
        dlg.appendChild(ta);
        var acts = el("div", "acts");
        var restore = el("button", "btn left", "恢复出厂");
        var cancel = el("button", "btn", "取消");
        var save = el("button", "btn primary", "保存");
        acts.appendChild(restore); acts.appendChild(cancel); acts.appendChild(save);
        dlg.appendChild(acts);
        layer.appendChild(dlg);
        UI.appendChild(layer);

        layer.addEventListener("mousedown", function (ev) {
          if (ev.target === layer) layer.classList.remove("on");
        });
        cancel.addEventListener("click", function () { layer.classList.remove("on"); });
        document.addEventListener("keydown", function (ev) {
          if (ev.key === "Escape" && layer.classList.contains("on")) layer.classList.remove("on");
        });
        function submit(text, done) {
          save.disabled = true; restore.disabled = true;
          apiPost("settings", { persona_target: layer._cid, pet_persona_overrides: text })
            .then(function (res) {
              if (res.rejected && res.rejected.length) throw new Error("配置结构不匹配");
              return refresh();
            })
            .then(function () {
              layer.classList.remove("on");
              toast(done);
            })
            .catch(function (err) { fb("保存失败：" + (err.message || err), true); })
            .then(function () { save.disabled = false; restore.disabled = false; });
        }
        restore.addEventListener("click", function () {
          ta.value = layer._factory || "";
          submit("", "已恢复出厂人设");
        });
        save.addEventListener("click", function () {
          var text = ta.value.trim();
          // 与出厂人设一字不差时不写覆盖，保持「回落出厂」而不是把出厂文本固化。
          submit(text === String(layer._factory || "").trim() ? "" : text, "已保存");
        });
      }
      layer._cid = ch.id;
      layer._factory = ch.factoryPersona || "";
      layer.querySelector("h4").textContent = "我的人设 · " + ch.displayName;
      layer.querySelector("textarea").value = ch.persona || layer._factory;
      layer.classList.add("on");
      layer.querySelector("textarea").focus();
    }

    // ---------------------------------------------------------------- 页面装配

    function buildPages() {
      var nav = $("[data-ui=nav]");
      var pages = $("[data-ui=pages]");
      nav.innerHTML = "";
      pages.innerHTML = "";
      DOMAINS.forEach(function (d) {
        var b = el("button", "");
        b.setAttribute("data-id", d.id);
        b.appendChild(el("span", "ico", d.ico));
        b.appendChild(document.createTextNode(d.name));
        b.addEventListener("click", function () { go(d.id, 0); });
        nav.appendChild(b);

        var page = el("section", "page");
        page.setAttribute("data-id", d.id);
        var tabs = el("div", "tabs");
        page.appendChild(tabs);
        (d.tabs || []).forEach(function (tab, ti) {
          var tb = el("button", ti === 0 ? "on" : "", tab.name);
          tb.setAttribute("data-tab", ti);
          tb.addEventListener("click", function () { switchTab(d.id, ti); });
          tabs.appendChild(tb);
          var tp = el("div", "tabpage" + (ti === 0 ? " on" : ""));
          tp.setAttribute("data-tab", ti);
          (tab.groups || []).forEach(function (g) {
            var fields = (g.fields || []).filter(function (x) { return x && x.t !== "note" && x.t !== "readonly"; });
            var sec = el("section", "group");
            sec.appendChild(el("h3", null, g.title));
            var form = el("div", "form");
            fields.forEach(function (x) {
              var node = buildField(x, { d: d.id, t: ti, dname: d.name, tname: tab.name });
              if (node) form.appendChild(node);
            });
            sec.appendChild(form);
            tp.appendChild(sec);
          });
          page.appendChild(tp);
        });
        pages.appendChild(page);
        PAGE_BY_ID[d.id] = page;
      });
      var first = PAGE_BY_ID[activeDomain] ? activeDomain : (DOMAINS[0] ? DOMAINS[0].id : "");
      go(first, activeTab);
    }

    function go(id, ti) {
      activeDomain = id;
      var d0 = DOMAINS.filter(function (x) { return x.id === id; })[0];
      var max = d0 && d0.tabs ? d0.tabs.length : 1;
      activeTab = Math.max(0, Math.min(max - 1, Number(ti) || 0));
      $$(".page").forEach(function (p) {
        p.classList.toggle("on", p.getAttribute("data-id") === id);
      });
      $$("[data-ui=nav] button").forEach(function (b) {
        b.classList.toggle("on", b.getAttribute("data-id") === id);
      });
      var d = DOMAINS.filter(function (x) { return x.id === id; })[0];
      if (d) {
        $("[data-ui=crumb]").textContent = d.name;
        $("[data-ui=title]").textContent = d.name;
      }
      switchTab(id, activeTab);
      fb("");
      applyWidth();
    }

    function switchTab(id, ti) {
      activeTab = ti;
      var page = PAGE_BY_ID[id];
      if (!page) return;
      $$(".tabs button", page).forEach(function (b) {
        b.classList.toggle("on", Number(b.getAttribute("data-tab")) === ti);
      });
      $$(".tabpage", page).forEach(function (p) {
        p.classList.toggle("on", Number(p.getAttribute("data-tab")) === ti);
      });
      var tp = $('.tabpage[data-tab="' + ti + '"]', page);
      if (tp) tp.scrollTop = 0;
    }

    // ---------------------------------------------------------------- 差量 / 保存

    function patchOf(toDefault) {
      var patch = {};
      controls.forEach(function (c) {
        var cur = c.get();
        var base = toDefault ? c.def : c.initial;
        if (String(cur) === String(base)) return;
        if (c.payload && c.payload.skip) return;
        var key = c.f ? c.f.k : null;
        if (!key) return;
        var v = toDefault ? c.def : cur;
        if (c.payload && c.payload.parse) {
          try { v = JSON.parse(v); } catch (e) { return; }
        } else if (c.payload && c.payload.feature) {
          try { v = { version: 1, enabled: JSON.parse(v) }; } catch (e) { return; }
        }
        patch[key] = v;
      });
      return patch;
    }

    function updateDirty() {
      controls.forEach(function (c) {
        if (c.node && c.node.classList) {
          c.node.classList.toggle("dirty", String(c.get()) !== String(c.initial));
        }
      });
    }

    function showDiff(patch) {
      var box = $("#diffBox");
      if (!box) {
        box = el("div", "diff");
        box.id = "diffBox";
        box.appendChild(el("h4", null, "差量 JSON"));
        var pre = el("pre");
        pre.id = "diffJson";
        box.appendChild(pre);
      }
      var host = $(".page.on .tabpage.on") || $(".page.on .tabpage");
      if (!host) return;
      host.appendChild(box);
      $("#diffJson").textContent = JSON.stringify(patch, null, 2);
      box.classList.add("on");
    }

    function writeResult(res, verb, patch) {
      return refresh().then(function () {
        showDiff(patch);
        var notes = [];
        if (res.skipped && res.skipped.length) notes.push("密钥未写入，请在桌宠小口袋设置");
        if (res.rejected && res.rejected.length) notes.push("部分配置结构不匹配，已跳过");
        fb(verb + (notes.length ? " · " + notes.join(" · ") : ""),
          Boolean(res.rejected && res.rejected.length));
      });
    }

    function saveSettings() {
      var patch = patchOf(false);
      if (!Object.keys(patch).length) { fb("没有改动"); return; }
      apiPost("settings", patch)
        .then(function (res) { return writeResult(res, "已保存", patch); })
        .catch(function (err) { fb("保存失败：" + (err.message || err), true); });
    }

    function resetSettings() {
      var patch = patchOf(true);
      if (!Object.keys(patch).length) { fb("已是默认值"); return; }
      apiPost("settings", patch)
        .then(function (res) { return writeResult(res, "已恢复默认", patch); })
        .catch(function (err) { fb("恢复失败：" + (err.message || err), true); });
    }

    // ---------------------------------------------------------------- 搜索

    function setupSearch() {
      var inp = $("[data-ui=search]");
      var res = $("[data-ui=results]");
      if (searchBound) return;
      searchBound = true;
      function render() {
        var q = inp.value.trim().toLowerCase();
        if (!q) { res.classList.remove("on"); return; }
        var hits = SEARCH.filter(function (e) {
          return (e.label + " " + e.key).toLowerCase().indexOf(q) >= 0;
        }).slice(0, 40);
        res.innerHTML = "";
        if (!hits.length) {
          res.appendChild(el("div", "empty", "没有匹配的设置项"));
          res.classList.add("on");
          return;
        }
        hits.forEach(function (h) {
          var row = el("div", "r");
          row.appendChild(el("span", null, h.loc.dname + " › " + h.loc.tname));
          row.appendChild(el("span", null, h.label));
          row.appendChild(el("span", "rk", h.key));
          row.addEventListener("click", function () {
            res.classList.remove("on");
            inp.value = "";
            go(h.loc.d, h.loc.t);
            flash(h.node);
          });
          res.appendChild(row);
        });
        res.classList.add("on");
      }
      inp.addEventListener("input", render);
      inp.addEventListener("focus", render);
    }

    // ---------------------------------------------------------------- 数据流

    function refresh() {
      return apiGet("state").then(function (next) {
        state = next;
        DOMAINS = (next.catalog && next.catalog.domains) || [];
        MENU_NODES = (next.catalog && next.catalog.menuNodes) || [];
        FEATURES = (next.catalog && next.catalog.features) || [];
        MODEL_OPTIONS = next.modelOptions || [];
        PREFS = next.catalogPrefs || {};
        controls = [];
        SEARCH = [];
        PAGE_BY_ID = {};
        buildPages();
        setupSearch();
        applyWidth();
      }).catch(function (err) {
        fb("读取配置失败：" + (err.message || err), true);
      });
    }

    /**
     * 面板从宿主标题栏（.nd-app-chrome，含右上角窗口按钮）下面开始。
     * 之前 root 是 fixed + inset:0，整块盖住标题栏：右上角窗口按钮被压住，
     * 头顶那条又是宿主的 app-region:drag，拖弹框等于拖整个应用窗口。
     * 这里量一次标题栏底边写进 --xxpm-top；量不到（比如独立预览）就退回 0。
     */
    function syncChromeInset(root) {
      var chrome = document.querySelector(".nd-app-chrome");
      var top = 0;
      if (chrome) {
        var rect = chrome.getBoundingClientRect();
        // 贴在窗口顶上才算标题栏；浮层/滚动出去的顶栏不当高度用。
        if (rect.height > 0 && rect.top <= 1) top = Math.round(rect.bottom);
      }
      root.style.setProperty("--xxpm-top", top + "px");
    }

    // ---------------------------------------------------------------- 主题

    /**
     * 面板跟随宿主主题。Laji 把解析后的主题写在 <html data-theme="light|dark">
     * （renderer/App.tsx 里 setAttribute/dataset.theme），插件脚本本来就跑在宿主
     * 页面里，直接读这个属性；读不到时退回 prefers-color-scheme。
     * 亮/暗两套色值在 STYLE 的 .xxpm-root / .xxpm-root.dark 里。
     */
    function hostDark() {
      var d = document.documentElement;
      var t = (d.getAttribute("data-theme") || "").toLowerCase();
      if (t === "dark") return true;
      if (t === "light") return false;
      if (d.classList.contains("dark")) return true;
      try {
        if (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) return true;
      } catch (e) {}
      return false;
    }
    function applyTheme(root) {
      if (!root) return;
      var dark = hostDark();
      root.classList.toggle("dark", dark);
      root.setAttribute("data-xxpm-theme", dark ? "dark" : "light");
    }
    function watchTheme(root) {
      applyTheme(root);
      if (themeObserver) return;
      themeObserver = new MutationObserver(function () {
        applyTheme(modalEl);
        applyTheme(embeddedEl);
      });
      themeObserver.observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme", "class", "data-workbench-skin"],
      });
    }

    function openModal() {
      if (modalEl) {
        UI = modalEl;
        syncChromeInset(modalEl);
        applyTheme(modalEl);
        modalEl.classList.add("open");
        return;
      }
      var root = document.getElementById(ROOT_ID);
      if (!root) {
        root = document.createElement("div");
        root.className = "xxpm-root";
        root.id = ROOT_ID;
      }
      UI = root;
      syncChromeInset(root);
      watchTheme(root);
      renderShell(root);
      document.body.appendChild(root);
      modalEl = root;
      root.classList.add("open");
      void refresh();
    }

    // ---------------------------------------------------------------- 入口

    return {
      apply: function (ctx) {
        var stale = document.getElementById(ROOT_ID);
        if (stale) stale.remove();
        var staleStyle = document.getElementById(STYLE_ID);
        if (staleStyle) staleStyle.remove();
        var style = document.createElement("style");
        style.id = STYLE_ID;
        style.textContent = STYLE;
        document.head.appendChild(style);

        entryHandle = ctx.entries.register({
          id: "manager",
          label: "桌宠管家",
          icon: "sparkles",
          open: openModal,
          mount: function (container) {
            var wrapper = document.createElement("div");
            wrapper.className = "xxpm-root is-embedded";
            container.appendChild(wrapper);
            UI = wrapper;
            embeddedEl = wrapper;
            watchTheme(wrapper);
            renderShell(wrapper);
            void refresh();
            return function () {
              container.innerHTML = "";
              if (UI === wrapper) UI = null;
              if (embeddedEl === wrapper) embeddedEl = null;
            };
          },
        });

        return function dispose() {
          if (entryHandle) { entryHandle.dispose(); entryHandle = null; }
          if (modalEl) { modalEl.remove(); modalEl = null; }
          embeddedEl = null;
          if (themeObserver) { themeObserver.disconnect(); themeObserver = null; }
          var styleNode = document.getElementById(STYLE_ID);
          if (styleNode) styleNode.remove();
          if (resizeHandler) window.removeEventListener("resize", resizeHandler);
          UI = null;
        };
      },
    };
  },
});
