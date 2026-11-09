window.__ModuleLoader__.load({
	id: "dsh-whale-pond",
	factory: (require) => {
		var module = { exports: {} };
		var exports = module.exports;

		// ---------------------------------------------------------------------
		// 小鲸鱼壁纸 — dsh-whale-pond
		// 把 whale_pond.html 的自留地铺在整个 DSH Web 界面背后：
		// 一块 canvas 沉在最底层（z-index:-1、pointer-events:none），再把界面
		// 自己用到的 --dsw-alias-bg-* 面板色按原色降透明度 —— 界面变成半透
		// 玻璃，海就在它后面。不拦鼠标、不抢键盘：鼠标只当提灯，光点自己
		// 游过来被鲸鱼吃掉。主题切换时重新取色。
		// ---------------------------------------------------------------------
		var CANVAS_ID = "whale-pond-canvas";
		var STYLE_ID = "whale-pond-style";
		var NL = String.fromCharCode(10);
		var CSS_TEXT = [
			"#" + CANVAS_ID + "{position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:-1;pointer-events:none;display:block;opacity:1}"
		].join(NL);
		var TOKENS = [
			["--dsw-alias-bg-base", 1.0],
			["--dsw-alias-bg-layer-1", 1.235],
			["--dsw-alias-bg-layer-2", 1.235],
			["--dsw-alias-bg-layer-3", 1.353],
			["--dsw-alias-bg-overlay", 2.118],
			["--dsw-alias-bg-module-platform", 1.176],
			["--dsw-alias-bg-multi-select", 1.412],
			["--dsw-specific-sidebar-fill", 1.324]
		];
		function translucent(value, alpha){
			if(!value) return null;
			var probe = document.createElement("div");
			probe.style.cssText = "position:fixed;left:-9999px;top:0;width:1px;height:1px";
			probe.style.background = value;
			document.body.appendChild(probe);
			var rgb = getComputedStyle(probe).backgroundColor;
			document.body.removeChild(probe);
			var parts = rgb.match(/[0-9.]+/g);
			if(!parts || parts.length < 3) return null;
			if(parts.length > 3 && parseFloat(parts[3]) === 0) return null;
			return "rgba(" + parts[0] + "," + parts[1] + "," + parts[2] + "," + alpha + ")";
		}
		function makeTokenApplier(){
		  // 主题把 --dsw-alias-bg-* 定义在 body 上（不是 html），所以要写 body；
		  // body 还要一条 inline 的 background:transparent —— 只有 inline+important 压得住主题规则。
		  var applied = [];
		  function el(){ return document.body || document.documentElement; }
		  function clear(){
		    var t = el();
		    for(var i = 0; i < applied.length; i++) t.style.removeProperty(applied[i]);
		    applied = [];
		  }
		  return {
		    apply: function(){
		      var t = el();
		      if(typeof HOOKS !== "undefined" && HOOKS.getMode && HOOKS.getMode() !== "wall"){ clear(); return; }
		      clear();
		      t.style.setProperty("background", "transparent", "important");
		      applied.push("background");
		      var cs = getComputedStyle(t);
		      for(var k = 0; k < TOKENS.length; k++){
		        var out = translucent(cs.getPropertyValue(TOKENS[k][0]), S.glass * TOKENS[k][1]);
		        if(out){ t.style.setProperty(TOKENS[k][0], out, "important"); applied.push(TOKENS[k][0]); }
		      }
		    },
		    reset: clear
		  };
		}
		// =====================================================================
		// 控制台（2026-10-17 用户要求：把之前改过的参数做成能自己选的选项）
		// 面板挂在 document.body 上；只有齿轮按钮和打开后的面板会接收鼠标事件，
		// 其余时间对宿主界面零影响。设置存 localStorage，改完立刻生效。
		// =====================================================================
		var PANEL_ID = "whale-pond-panel";
		var GEAR_ID = "whale-pond-gear";
		var POWER_ID = "whale-pond-power";   // 一键停用/恢复（2026-10-17：要能真的停掉）
		var GRIP_ID = "whale-pond-grip";     // 小窗右下角的缩放手柄（2026-10-18）
		var HINT_ID = "whale-pond-hint";     // 「点击画面或按 Esc 退出」提示条
		var S_KEY = "whale-pond-settings-v1";
		var W_KEY = "whale-pond-words-v1";   // 词库单独存：整份设置回写/恢复默认都动不到它
		var HOOKS = {};                 // start() 内部回填：tokens / canvas / respawn
		var S_KEYS = ["enabled","glass","brightness","count","speed","attract","ar","ak","ring","popToken","popWord","pad","padR","padM","padPower","flow","breathe","breatheRate","motion","quality","words"];
		var S_DEFAULTS = {
			enabled: true,   // 总开关：false = 真停（动画停、玻璃撤掉、界面回原样），齿轮与面板留着
			glass: 0.34,      // 界面面板不透明度（越小海越明显）
			brightness: 1.6,  // 画布亮度
			count: 400,       // 目标光点数
			speed: 1.0,       // 漂移速度倍率
			attract: true,    // 鼠标洋流
			ar: 340,          // 吸引半径（硬边界）
			ak: 1.0,          // 吸引强度倍率
			ring: true,       // 画吸引范围光环
			popToken: true,   // 吃光点冒 "-1 token"
			popWord: true,    // 吃掉词冒字
			pad: true,        // 右下角发射台
			padR: 170,        // 发射台半径
			padM: 132,        // 圆心距右下角两边
			padPower: 4.0,    // 弹射力度（4.0 ≈ 弹出 4 倍圈直径）
			flow: 1.0,        // 运动强度：飘落快慢 / 洋流急缓 / 漩涡松紧
			breathe: false,   // 呼吸灯：每个光点按自己的相位一明一暗
			breatheRate: 1.0, // 呼吸快慢
			motion: "drift",  // 运动方式：drift 漂移 / fall 飘落 / rise 上浮 / current 洋流 / swirl 漩涡
			quality: 1.0,     // 内部清晰度：乘在 devicePixelRatio 上，再有 260 万像素硬上限（卡就调低）
			words: null       // 词库：null = 用内建的 10 个词；数组 = 用户自己编的
		};
		var S = {};
		for(var _si = 0; _si < S_KEYS.length; _si++) S[S_KEYS[_si]] = S_DEFAULTS[S_KEYS[_si]];
		function sDerive(){
			S.ar2 = S.ar * S.ar;
			S.capA = Math.round(S.count * 1.4);
			S.capB = Math.round(S.count * 1.45);
			S.restock = Math.round(S.count * 0.85);
			S.whalePower = 8.5 * S.padPower;
			S.whaleCap = 350 * S.padPower;
		}
		function sLoad(){
			try{
				var raw = localStorage.getItem(S_KEY);
				if(raw){
					var o = JSON.parse(raw);
					for(var i = 0; i < S_KEYS.length; i++){
						var k = S_KEYS[i];
						if(o && o[k] !== undefined && typeof o[k] === typeof S_DEFAULTS[k]) S[k] = o[k];
					}
				}
			}catch(e){}
			// 词库（2026-10-17 用户要求：控制台里能直接编词库）：
			// null = 用 whale_pond.html 里那份内建词表，非空数组 = 用户自己编的。
			// 2026-10-17 修「改了的词库无法保存」：词库改存 W_KEY，不再和其余设置挤在一个对象里 ——
			// 这样「恢复默认」或任何一次整份设置回写都不会再把它抹成 null。旧版把 words 写在
			// S_KEY 里，这里仍读一次做迁移；读到的脏值（类型不对 / 混进数字 / 单个词过长 /
			// 超量 / 重复）在这里修干净，然后无条件回写一次，localStorage 自愈。
			var wRaw = S.words;
			try{
				var wr = localStorage.getItem(W_KEY);
				if(wr == null){                      // 还没有独立的词库键 → 从旧版设置对象里搬一次
					var bo = JSON.parse(localStorage.getItem(S_KEY) || "null");
					if(bo && bo.words !== undefined) wr = JSON.stringify(bo.words);
				}
				if(wr != null) wRaw = JSON.parse(wr);
			}catch(e){}
			S.words = sNormWords(wRaw);
			wSave();                             // 归一化后的值回写（wSave 对 null 也写，避免又被迁移回来）
			if(sClamp()) sSave();
			sDerive();
		}
		var W_MAX = 200, W_LEN = 24;
		function sNormWords(v){
			if(!v || Object.prototype.toString.call(v) !== "[object Array]") return null;
			var out = [];
			for(var i = 0; i < v.length && out.length < W_MAX; i++){
				if(typeof v[i] !== "string") continue;
				var s = v[i].replace(/[\r\n\t]+/g, " ").trim().slice(0, W_LEN);
				if(!s || out.indexOf(s) >= 0) continue;
				out.push(s);
			}
			return out.length ? out : null;
		}
		function parseWords(txt){
			return sNormWords(String(txt == null ? "" : txt).split(/[\n\r,，、;；]+/));
		}
		function applyWords(){
			if(!HOOKS.applyWords) return;           // start() 还没跑：词库在那个作用域里
			HOOKS.applyWords(S.words);              // null = 回内建
			refreshWords();
		}
		function refreshWords(){
			for(var i = 0; i < valRefs.length; i++){
				var r = valRefs[i];
				if(!r.ta) continue;
				var custom = !!(S.words && S.words.length);
				var list = custom ? S.words : (HOOKS.wordsDefault || []);
				// 正在输入时别回写 textarea，否则光标会跳
				if(document.activeElement !== r.ta) r.ta.value = list.join("\n");
				if(r.cnt) r.cnt.textContent = list.length + " 个" + (custom ? "（自定义）" : "（内建）")
					+ (custom ? " · 已保存" + (wSavedAt ? " " + wSavedAt : "") : "");
			}
		}
		function onWordsInput(e){
			S.words = parseWords(e && e.target ? e.target.value : "");
			wSave();                              // 立刻落盘（原先防抖 320ms，关得太快就白改了）
			wSavedAt = wStamp();
			applyWords();
		}
		// 夹紧：localStorage 里的数字必须落在 CTL 滑杆区间内。
		// 不夹的话（用户手改 localStorage，或将来下调某个滑杆上限让旧值越界）
		// 引擎会真按越界值跑，而 <input range> 会被浏览器自动夹到 min/max ——
		// 面板显示与实际行为分家。真页面实测 count=5000：引擎每帧 9268 个圆
		// （= 上限 2100 的 4 倍），面板却写着 5000、滑杆卡在 2100。
		// 返回是否有值被改动，让 sLoad 回写一次、localStorage 自愈。
		function sClamp(){
			if(typeof CTL === "undefined" || !CTL) return false;
			var changed = false;
			for(var i = 0; i < CTL.length; i++){
				var c = CTL[i];
				if(c[0] === "s"){                      // 下拉选项：值必须在选项表里，否则回默认
					var sk = c[1], sok = false;
					for(var j = 0; j < c[3].length; j++) if(c[3][j][0] === S[sk]) sok = true;
					if(!sok){ S[sk] = S_DEFAULTS[sk]; changed = true; }
					continue;
				}
				if(c[0] !== "r") continue;
				var k = c[1], v = S[k], lo = c[3], hi = c[4];
				if(typeof v !== "number" || !isFinite(v)){ S[k] = S_DEFAULTS[k]; changed = true; continue; }
				if(v < lo) v = lo;
				if(v > hi) v = hi;
				if(v !== S[k]){ S[k] = v; changed = true; }
			}
			return changed;
		}
		function wSave(){
			try{                                  // 词库自己一个键：null 也写成 "null"，
				if(S.words && S.words.length) localStorage.setItem(W_KEY, JSON.stringify(S.words));
				else localStorage.setItem(W_KEY, "null");   // 免得下次启动又被旧版设置对象迁移回来
			}catch(e){}
		}
		var wSavedAt = "";
		function wStamp(){
			var d = new Date(), p = function(n){ return (n < 10 ? "0" : "") + n; };
			return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
		}
		function sSave(){
			try{
				var o = {};
				for(var i = 0; i < S_KEYS.length; i++) if(S_KEYS[i] !== "words") o[S_KEYS[i]] = S[S_KEYS[i]];
				localStorage.setItem(S_KEY, JSON.stringify(o));
			}catch(e){}
		}
		var PANEL_CSS = [
			"#" + GEAR_ID + "{position:fixed;right:14px;top:46px;width:30px;height:30px;border-radius:50%;z-index:2147483000;",
			"background:rgba(8,14,22,.72);border:1px solid rgba(255,168,96,.35);color:rgba(255,196,120,.9);",
			"font:15px/28px -apple-system,'Segoe UI',system-ui,sans-serif;text-align:center;cursor:pointer;",
			"opacity:.55;transition:opacity .15s;-webkit-user-select:none;user-select:none;backdrop-filter:blur(3px)}",
			"#" + GEAR_ID + ":hover{opacity:1}",
			"#" + POWER_ID + "{position:fixed;right:52px;top:46px;width:30px;height:30px;border-radius:50%;z-index:2147483000;",
			"background:rgba(8,14,22,.72);border:1px solid rgba(255,168,96,.28);color:rgba(255,196,120,.85);",
			"font:12px/28px -apple-system,'Segoe UI',system-ui,sans-serif;text-align:center;cursor:pointer;",
			"opacity:.38;transition:opacity .15s,color .15s;-webkit-user-select:none;user-select:none;backdrop-filter:blur(3px)}",
			"#" + POWER_ID + ":hover{opacity:1}",
			"#" + POWER_ID + ".off{color:#ffb066;border-color:rgba(255,168,96,.62);background:rgba(255,168,96,.14);opacity:.85}",
			"#" + PANEL_ID + "{position:fixed;right:14px;top:84px;width:334px;max-height:78vh;overflow:auto;z-index:2147483001;",
			"display:none;background:rgba(6,11,18,.95);border:1px solid rgba(255,168,96,.28);border-radius:12px;",
			"padding:14px 14px 12px;box-shadow:0 18px 50px rgba(0,0,0,.6);color:#cfe3f2;backdrop-filter:blur(9px);",
			"font:13px/1.55 -apple-system,'Segoe UI',system-ui,sans-serif}",
			"#" + PANEL_ID + " input[type=range]{width:100%;accent-color:#ffb066;margin:3px 0 0}",
			"#" + PANEL_ID + " input[type=checkbox]{accent-color:#ffb066;width:15px;height:15px;cursor:pointer;margin:0}",
			"#" + PANEL_ID + " .wp-g{margin:13px 0 6px;font-size:11px;letter-spacing:.18em;color:#7d94a8;",
			"border-top:1px solid rgba(255,168,96,.13);padding-top:8px}",
			"#" + PANEL_ID + " .wp-words{width:100%;box-sizing:border-box;min-height:76px;resize:vertical;border-radius:7px;",
			"border:1px solid rgba(255,168,96,.22);background:rgba(255,255,255,.045);color:#d8e8f5;padding:6px 7px;",
			"font:12px/1.5 ui-monospace,Consolas,'Courier New',monospace;outline:none}",
			"#" + PANEL_ID + " .wp-words:focus{border-color:rgba(255,168,96,.55)}",
			"#" + PANEL_ID + " .wp-sel{width:100%;box-sizing:border-box;border-radius:7px;border:1px solid rgba(255,168,96,.22);",
			"background:rgba(255,255,255,.045);color:#d8e8f5;padding:5px 6px;font-size:12px;outline:none}",
			"#" + PANEL_ID + " .wp-sel:focus{border-color:rgba(255,168,96,.55)}",
			"#" + PANEL_ID + " .wp-foot{display:flex;gap:8px;margin-top:15px}",
			"#" + PANEL_ID + " .wp-btn{flex:1;text-align:center;padding:6px 0;border-radius:7px;cursor:pointer;",
			"border:1px solid rgba(255,168,96,.28);color:#ffc484;background:rgba(255,168,96,.06)}",
			"#" + PANEL_ID + " .wp-btn:hover{background:rgba(255,168,96,.16)}",
			"#" + PANEL_ID + " .wp-btn.wp-on{background:rgba(255,168,96,.22);border-color:rgba(255,168,96,.7);color:#ffe0b8}",
			"#" + GRIP_ID + "{position:fixed;width:22px;height:22px;z-index:2147482991;display:none;cursor:nwse-resize;",
			"border-radius:0 0 12px 0;background:linear-gradient(135deg,transparent 0 44%,rgba(255,176,102,.55) 44% 51%,transparent 51% 61%,rgba(255,176,102,.34) 61% 68%,transparent 68%)}",
			"#" + HINT_ID + "{position:fixed;left:50%;bottom:32px;transform:translateX(-50%);z-index:2147483003;pointer-events:none;",
			"background:rgba(4,10,17,.66);border:1px solid rgba(255,168,96,.26);color:rgba(255,214,170,.92);border-radius:999px;",
			"padding:7px 16px;font:12px/1.4 -apple-system,'Segoe UI',system-ui,sans-serif;letter-spacing:.05em;opacity:0;",
			"transition:opacity .45s;backdrop-filter:blur(6px)}"
		].join(NL);
		var CTL = [
			["g", "开关"],
			["c", "enabled", "启用壁纸", "关掉 = 真停：动画停、玻璃背景撤掉、界面回到原样（齿轮和这个面板还在）。也可以直接点右上角那个 ■"],
			["g", "看海"],
			["b", "viewFull", "全屏屏保", "整片海铺满屏幕、盖住界面文字，专心看鲸鱼吃光点。点击画面或按 Esc 退出"],
			["b", "viewMini", "小窗摸鱼", "一个可以拖动、右下角能缩放的小窗，浮在界面上。点击画面或按 Esc 退出"],
			["b", "viewWall", "回到壁纸", "恢复成界面背后那片半透明的海"],
			["g", "界面"],
			["r", "glass", "面板不透明度", 0.15, 0.75, 0.01, "越小，海越明显"],
			["r", "brightness", "画布亮度", 1.0, 2.2, 0.05, ""],
			["g", "海"],
			["r", "count", "光点数量", 150, 2100, 10, "越多越热闹，也越费电"],
			["r", "speed", "光点速度", 0.4, 9.0, 0.05, "1.0 = 现在的速度"],
			["g", "鼠标（提灯）"],
			["c", "attract", "洋流吸引光点", "把光点赶向鲸鱼嘴边"],
			["r", "ar", "吸引半径", 150, 600, 10, "只在这个半径内有拉力", "px"],
			["r", "ak", "吸引强度", 0.4, 2.0, 0.05, ""],
			["c", "ring", "显示吸引范围光环", ""],
			["g", "吃光点"],
			["c", "popToken", "飘字「-1 token」", ""],
			["c", "popWord", "飘字「吃掉「词」」", ""],
			["g", "右下角发射台"],
			["c", "pad", "启用发射台", "鼠标进圈才通电"],
			["r", "padR", "圈半径", 100, 260, 5, "", "px"],
			["r", "padM", "距右下角", 60, 260, 5, "", "px"],
			["r", "padPower", "弹射力度", 1.0, 40.0, 0.5, "4.0 ≈ 4 倍圈直径；40 会把鲸鱼甩出屏幕几秒"],
			["g", "光点运动"],
			["s", "motion", "运动方式", [["drift","漂移（原样）"],["fall","从上往下飘落"],["rise","从下往上浮"],["current","洋流：成片流线"],["swirl","漩涡：绕中心打转"]], "和上面的鼠标吸引、发射台叠加生效，改完立刻变"],
			["r", "flow", "运动强度", 0.2, 3.0, 0.1, "飘落更快 / 洋流更急 / 漩涡更紧"],
			["c", "breathe", "呼吸灯（一明一暗）", "每个光点按自己的相位慢慢变亮变暗"],
			["r", "breatheRate", "呼吸快慢", 0.2, 3.0, 0.1, "越大闪得越快"],
			["g", "性能"],
			["r", "quality", "内部清晰度", 0.5, 1.5, 0.05, "只影响背景壁纸的渲染分辨率：调低更顺、几乎看不出差别"],
			["i", "perf", "运行状态"],
			["g", "词库（鲸鱼吃的词）"],
			["w", "words", "词库", "一行一个词，逗号 / 顿号也行；最多 200 个、每个 24 字。改一下存一下，刷新也不会丢。清空 = 回到内建那 10 个词；下面的「恢复默认」不会动词库"]
		];
		var panelEl = null, gearEl = null, powerEl = null, valRefs = [], viewBtns = [];
		function mkEl(tag, css, txt){
			var d = document.createElement(tag);
			if(css) d.style.cssText = css;
			if(txt != null) d.textContent = txt;
			return d;
		}
		function fmtVal(v, unit){
			var s = (Math.round(v * 100) / 100).toString();
			return unit ? s + unit : s;
		}
		function refreshValues(){
			for(var i = 0; i < valRefs.length; i++){
				var r = valRefs[i];
				if(r.out) r.out.textContent = fmtVal(S[r.key], r.unit);
				if(r.range) r.range.value = S[r.key];
				if(r.box) r.box.checked = !!S[r.key];
				if(r.sel) r.sel.value = S[r.key];
			}
			refreshWords();
			refreshGear();
			refreshView();
		}
		var perfTimer = 0, perfEl = null;
		var qTimer = 0;
		// 「内部清晰度」滑杆每拖一格都会走到 resize()，而 resize 要重新分配画布缓冲 + 重烘离屏图；
		// 逐格做会拖出一条卡顿带 —— 拖动期间只更新数字，停手 260ms 之后才真正改分辨率。
		function qResizeSoon(){
			if(qTimer) clearTimeout(qTimer);
			qTimer = setTimeout(function(){ qTimer = 0; if(HOOKS.resizeCanvas) HOOKS.resizeCanvas(); }, 260);
		}
		function refreshPerf(){
			if(!perfEl) return;
			if(!S.enabled){ perfEl.textContent = "已停用 · 动画停、玻璃已撤（勾「启用壁纸」或点右上角 ■ 就回来）"; return; }
			var p = HOOKS.perfInfo ? HOOKS.perfInfo() : null;
			if(!p){ perfEl.textContent = "（壁纸还没起来）"; return; }
			var eff = Math.round(p.quality * 100) / 100;
			perfEl.textContent = "帧率 " + p.fps + " · 单帧 " + p.cost + "ms · 清晰度 " + eff + "× · 缓冲 " + p.buf + " · 光点 " + p.count;
		}
		function applyCanvasFilter(){
			if(HOOKS.canvas) HOOKS.canvas.style.filter = "brightness(" + S.brightness + ") saturate(1.12)";
		}
		function refreshGear(){
			if(powerEl){
				powerEl.textContent = S.enabled ? "\u25a0" : "\u25b6";
				powerEl.title = S.enabled ? "停用壁纸（动画停、界面复原）" : "重新启用壁纸";
				powerEl.className = S.enabled ? "" : "off";
			}
			if(gearEl){
				gearEl.title = S.enabled ? "鲸鱼壁纸设置" : "鲸鱼壁纸已停用 · 点齿轮重新开";
				gearEl.style.opacity = S.enabled ? "" : "0.3";
			}
		}
		// 「看海」按钮的当前模式高亮（2026-10-18）。模式本身在 start() 里，
		// 面板只通过 HOOKS.getMode / HOOKS.setMode 与它说话。
		function viewKeyOf(m){ return m === "full" ? "viewFull" : (m === "mini" ? "viewMini" : "viewWall"); }
		function refreshView(){
			var m = HOOKS.getMode ? HOOKS.getMode() : "wall";
			var cur = viewKeyOf(m);
			for(var i = 0; i < viewBtns.length; i++) viewBtns[i].el.className = "wp-btn" + (viewBtns[i].key === cur ? " wp-on" : "");
		}
		HOOKS.refreshView = refreshView;
		function syncLive(key){
			if(key === undefined || key === "enabled"){
				if(HOOKS.setEnabled) HOOKS.setEnabled(!!S.enabled);
				if(HOOKS.tokens){ if(S.enabled) HOOKS.tokens.apply(); else HOOKS.tokens.reset(); }
				if(S.enabled && HOOKS.respawn) HOOKS.respawn(S.count);
				refreshGear();
			}
			if(key === undefined || key === "brightness") applyCanvasFilter();
			if((key === undefined || key === "glass") && S.enabled){ if(HOOKS.tokens) HOOKS.tokens.apply(); }
			if((key === undefined || key === "count") && HOOKS.respawn) HOOKS.respawn(S.count);
			if(key === undefined){ if(HOOKS.resizeCanvas) HOOKS.resizeCanvas(); }
			else if(key === "quality") qResizeSoon();
			if(key === undefined || key === "words") applyWords();
			refreshValues();
		}
		function applyChange(key, v){
			S[key] = v;
			sDerive(); sSave(); syncLive(key);
		}
		function onKey(e){
			if(e.key !== "Escape") return;
			// 屏保/小窗优先：Esc 先退出看海模式（这一步同样要吃掉事件，否则宿主也会取消生成）
			var vmode = HOOKS.getMode ? HOOKS.getMode() : "wall";
			if(vmode !== "wall"){
				e.preventDefault(); e.stopPropagation();
				if(HOOKS.setMode) HOOKS.setMode("wall");
				togglePanel(false);
				return;
			}
			var open = !!(panelEl && panelEl.style.display === "block");
			// 面板开着时必须吃掉这次 Escape。宿主（React 根容器在 body 里）比 document
			// 的冒泡监听更早拿到事件，事后 stopPropagation 救不回来 —— DSH 里 Escape 是
			// 「取消生成 / 关弹窗」，穿透过去就是真事故（夹具实测 hostSawEsc 1）。
			// 所以监听注册在捕获阶段（见 buildPanel 末尾），这里再阻止继续下发。
			if(open){ e.preventDefault(); e.stopPropagation(); }
			togglePanel(false);
		}
		function buildPanel(){
			if(panelEl || !document.body) return;
			gearEl = mkEl("div", "", "\u2699");
			gearEl.id = GEAR_ID;
			gearEl.title = "鲸鱼壁纸设置";
			gearEl.addEventListener("mousedown", function(e){ e.stopPropagation(); });
			gearEl.addEventListener("click", function(e){ e.stopPropagation(); togglePanel(); });
			document.body.appendChild(gearEl);
			powerEl = mkEl("div", "", "\u25a0");
			powerEl.id = POWER_ID;
			powerEl.addEventListener("mousedown", function(e){ e.stopPropagation(); });
			powerEl.addEventListener("click", function(e){ e.stopPropagation(); applyChange("enabled", !S.enabled); });
			document.body.appendChild(powerEl);
			panelEl = mkEl("div", "", "");
			panelEl.id = PANEL_ID;
			panelEl.addEventListener("mousedown", function(e){ e.stopPropagation(); });
			panelEl.addEventListener("click", function(e){ e.stopPropagation(); });
			var head = mkEl("div", "display:flex;align-items:center;justify-content:space-between;margin-bottom:4px", "");
			head.appendChild(mkEl("div", "font-size:14px;letter-spacing:.06em;color:#ffc484", "鲸鱼壁纸 · 控制台"));
			var x = mkEl("div", "cursor:pointer;padding:0 4px;font-size:17px;line-height:1;color:#8fa8bd", "\u00d7");
			x.addEventListener("click", function(){ togglePanel(false); });
			head.appendChild(x);
			panelEl.appendChild(head);
			valRefs = [];
			for(var i = 0; i < CTL.length; i++){
				var c = CTL[i];
				if(c[0] === "g"){ var g = mkEl("div", "", c[1]); g.className = "wp-g"; panelEl.appendChild(g); continue; }
				var key = c[1], row = mkEl("div", "margin:9px 0", "");
				if(c[0] === "c"){
					var lab = mkEl("label", "display:flex;align-items:center;gap:9px;cursor:pointer", "");
					var box = document.createElement("input");
					box.type = "checkbox";
					box.checked = !!S[key];
					box.addEventListener("change", (function(k, b){ return function(){ applyChange(k, b.checked); }; })(key, box));
					lab.appendChild(box);
					lab.appendChild(mkEl("span", "color:#d8e8f5", c[2]));
					row.appendChild(lab);
					if(c[3]) row.appendChild(mkEl("div", "margin-left:24px;font-size:11px;color:#7d94a8", c[3]));
					valRefs.push({ key: key, box: box, out: null, range: null });
				} else if(c[0] === "i"){
					perfEl = mkEl("div", "font-size:11px;color:#7d94a8;margin-top:2px;font-variant-numeric:tabular-nums", "");
					row.appendChild(perfEl);
					valRefs.push({ key: key, perf: true, range: null, box: null, out: null });
				} else if(c[0] === "w"){
					row.appendChild(mkEl("div", "color:#d8e8f5;margin-bottom:4px", c[2]));
					var ta = document.createElement("textarea");
					ta.className = "wp-words";
					ta.rows = 5;
					ta.spellcheck = false;
					ta.placeholder = "一行一个词";
					// 在词库里打字时别把按键喂给宿主界面（React 根容器在 body 上，冒泡被拦下它就拿不到
					// 这次 keydown）；面板自己的 Escape 仍走捕获，不受影响。
					ta.addEventListener("keydown", function(e){ e.stopPropagation(); });
					ta.addEventListener("input", onWordsInput);
					ta.addEventListener("change", onWordsInput);
					row.appendChild(ta);
					if(c[3]) row.appendChild(mkEl("div", "font-size:11px;color:#7d94a8;margin-top:3px", c[3]));
					var cnt = mkEl("div", "font-size:11px;color:#ffc484;margin-top:2px", "");
					row.appendChild(cnt);
					valRefs.push({ key: key, ta: ta, cnt: cnt, range: null, box: null, out: null });
				} else if(c[0] === "b"){
					// 「看海」整行按钮：点完立刻切模式，并把面板收起来（全屏时面板本来就被盖住）
					var vb = mkEl("div", "", c[2]);
					vb.className = "wp-btn";
					vb.style.margin = "5px 0 0";
					vb.addEventListener("click", (function(k){ return function(){
						if(HOOKS.setMode) HOOKS.setMode(k === "viewFull" ? "full" : (k === "viewMini" ? "mini" : "wall"));
						togglePanel(false);
					}; })(key));
					row.appendChild(vb);
					if(c[3]) row.appendChild(mkEl("div", "font-size:11px;color:#7d94a8;margin-top:3px", c[3]));
					viewBtns.push({ key: key, el: vb });
				} else if(c[0] === "s"){
					row.appendChild(mkEl("div", "color:#d8e8f5;margin-bottom:4px", c[2]));
					var sel = document.createElement("select");
					sel.className = "wp-sel";
					for(var oi = 0; oi < c[3].length; oi++){
						var op = document.createElement("option");
						op.value = c[3][oi][0];
						op.textContent = c[3][oi][1];
						sel.appendChild(op);
					}
					sel.value = S[key];
					sel.addEventListener("mousedown", function(e){ e.stopPropagation(); });
					sel.addEventListener("click", function(e){ e.stopPropagation(); });
					sel.addEventListener("change", (function(k, el){ return function(){ applyChange(k, el.value); }; })(key, sel));
					row.appendChild(sel);
					if(c[4]) row.appendChild(mkEl("div", "font-size:11px;color:#7d94a8;margin-top:3px", c[4]));
					valRefs.push({ key: key, sel: sel, ta: null, cnt: null, range: null, box: null, out: null });
				} else {
					var top = mkEl("div", "display:flex;justify-content:space-between;align-items:baseline", "");
					top.appendChild(mkEl("span", "color:#d8e8f5", c[2]));
					var out = mkEl("span", "color:#ffc484;font-variant-numeric:tabular-nums", "");
					top.appendChild(out);
					row.appendChild(top);
					var range = document.createElement("input");
					range.type = "range"; range.min = c[3]; range.max = c[4]; range.step = c[5]; range.value = S[key];
					range.addEventListener("input", (function(k, r){ return function(){ applyChange(k, parseFloat(r.value)); }; })(key, range));
					row.appendChild(range);
					if(c[6]) row.appendChild(mkEl("div", "font-size:11px;color:#7d94a8", c[6]));
					valRefs.push({ key: key, range: range, box: null, out: out, unit: c[7] || "" });
				}
				panelEl.appendChild(row);
			}
			var foot = mkEl("div", "", "");
			foot.className = "wp-foot";
			var reset = mkEl("div", "", "恢复默认（词库保留）");
			reset.className = "wp-btn";
			reset.addEventListener("click", function(){
				// 词库不在重置范围内：它单独存 W_KEY，用户自己编的词不该被一键清掉
				for(var i = 0; i < S_KEYS.length; i++) if(S_KEYS[i] !== "words") S[S_KEYS[i]] = S_DEFAULTS[S_KEYS[i]];
				perfEl = null;
				sDerive(); sSave(); syncLive();
			});
			var close = mkEl("div", "", "关闭");
			close.className = "wp-btn";
			close.addEventListener("click", function(){ togglePanel(false); });
			foot.appendChild(reset); foot.appendChild(close);
			panelEl.appendChild(foot);
			document.body.appendChild(panelEl);
			document.addEventListener("keydown", onKey, true);
			refreshValues();
		}
		function togglePanel(force){
			buildPanel();
			if(!panelEl) return;
			var open = (typeof force === "boolean") ? force : (panelEl.style.display !== "block");
			panelEl.style.display = open ? "block" : "none";
			if(open){
				refreshValues(); refreshPerf();
				if(!perfTimer) perfTimer = setInterval(refreshPerf, 1000);
			} else if(perfTimer){ clearInterval(perfTimer); perfTimer = 0; }
		}
		function panelMount(){ buildPanel(); applyCanvasFilter(); }
		function panelUnmount(){
			document.removeEventListener("keydown", onKey, true);
			if(panelEl && panelEl.parentNode) panelEl.parentNode.removeChild(panelEl);
			if(gearEl && gearEl.parentNode) gearEl.parentNode.removeChild(gearEl);
			if(powerEl && powerEl.parentNode) powerEl.parentNode.removeChild(powerEl);
			if(perfTimer){ clearInterval(perfTimer); perfTimer = 0; }
			if(qTimer){ clearTimeout(qTimer); qTimer = 0; }
			panelEl = null; gearEl = null; powerEl = null; perfEl = null; valRefs = []; viewBtns = [];
		}
		function start(canvas){
			var cv = canvas, cx = canvas.getContext('2d');
			var W = 0, H = 0, DPR = 1, raf = 0, alive = true, frames = 0;
			var timers = [];
			var whisperText = '', whisperAlpha = 0;
			var reduce = false;
			try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduce = false; }
			function resize(){
			  DPR = perfDPR();
			  if(VIEW === 'mini' && mini){ W = Math.max(220, Math.round(mini.w)); H = Math.max(150, Math.round(mini.h)); }
			  else { W = window.innerWidth; H = window.innerHeight; }
			  cv.width = Math.floor(W * DPR); cv.height = Math.floor(H * DPR);
			  cv.style.width = W + 'px'; cv.style.height = H + 'px';
			  cx.setTransform(DPR, 0, 0, DPR, 0, 0);
			}
						var fCost=16,qLast=0,framesW=0,fpsShown=0,minInt=26;
			function fnow(){ try{ return performance.now(); }catch(e){ return Date.now(); } }
			function perfDPR(){
			  var q=(typeof S.quality==='number'&&S.quality>0)?S.quality:1;
			  var d=Math.min(window.devicePixelRatio||1,1.5)*q;
			  var px=W*H*d*d, cap=2600000;
			  if(px>cap) d*=Math.sqrt(cap/px);
			  return Math.max(0.35,d);
			}
			HOOKS.resizeCanvas = function(){ resize(); };
			HOOKS.perfInfo = function(){ return { fps:fpsShown, cost:Math.round(fCost*10)/10, dpr:Math.round(DPR*100)/100, quality:(typeof S.quality==='number'?S.quality:1), count:motes.length, buf:cv.width+'x'+cv.height }; };
			window.addEventListener('resize', resize); resize();
			var bgC=null,bgX=null,bgT=-1e9,vgC=null,vgX=null;
			function bakeBG(){
			  if(!bgC){ bgC=document.createElement('canvas'); bgX=bgC.getContext('2d'); }
			  var qw=Math.max(1,Math.round(cv.width/4)), qh=Math.max(1,Math.round(cv.height/4));
			  if(bgC.width!==qw||bgC.height!==qh){ bgC.width=qw; bgC.height=qh; }
			  var g=bgX; g.setTransform(DPR/4,0,0,DPR/4,0,0); g.globalAlpha=1; g.globalCompositeOperation='source-over';
			  var lg=g.createLinearGradient(0,0,0,H);
			  lg.addColorStop(0,'#051524'); lg.addColorStop(.5,'#03101c'); lg.addColorStop(.82,'#020b14'); lg.addColorStop(1,'#010609');
			  g.fillStyle=lg; g.fillRect(0,0,W,H);
			  g.globalCompositeOperation='lighter';
			  for(var i=0;i<5;i++){
			    var sx=W*(0.10+i*0.20)+Math.sin(T*0.00012+i)*80, wd=90+i*26;
			    var sg=g.createLinearGradient(sx,0,sx+wd*0.6,H);
			    sg.addColorStop(0,'rgba(120,200,255,0.06)'); sg.addColorStop(1,'rgba(120,200,255,0)');
			    g.fillStyle=sg;
			    g.beginPath(); g.moveTo(sx,0); g.lineTo(sx+wd,0); g.lineTo(sx+wd*2.1,H); g.lineTo(sx+wd*0.9,H); g.closePath(); g.fill();
			  }
			  g.globalCompositeOperation='source-over';
			}
			function bakeVG(){
			  if(!vgC){ vgC=document.createElement('canvas'); vgX=vgC.getContext('2d'); }
			  if(vgC.width!==cv.width||vgC.height!==cv.height){ vgC.width=cv.width; vgC.height=cv.height; }
			  var g=vgX; g.setTransform(1,0,0,1,0,0); g.clearRect(0,0,vgC.width,vgC.height); g.setTransform(DPR,0,0,DPR,0,0); g.globalAlpha=1; g.globalCompositeOperation='source-over';
			  var vg=g.createRadialGradient(W*0.5,H*0.45,Math.min(W,H)*0.30,W*0.5,H*0.5,Math.max(W,H)*0.80);
			  vg.addColorStop(0,'rgba(0,0,0,0)'); vg.addColorStop(1,'rgba(0,0,0,0.66)');
			  g.fillStyle=vg; g.fillRect(0,0,W,H);
			}

var T=0,last=0;
var motes=[],ripples=[],pops=[],bubbles=[],jellies=[];
var CORE=null,HALO=null,CB=null,HB=null,BA=[1,0.55,0.22];
			var lamp={x:-999,y:-999,on:false,vx:0,vy:0};
var eaten=0,wordsEaten=0;
var TYPES=[
  {col:'250,190,120',r:1.9},
  {col:'110,225,255',r:1.6},
  {col:'180,160,255',r:2.1},
  {col:'255,214,130',r:1.5}
];
var WORDS=['潮汐','盐','月光','鲸落','暗流','礁石','海雾','星光','潮声','深蓝'];
HOOKS.words = WORDS; HOOKS.wordsDefault = WORDS.slice();
HOOKS.applyWords = function(list){
  var src = (list && list.length) ? list : HOOKS.wordsDefault;
  if(!src || !src.length) return;
  HOOKS.words.length = 0;
  for(var i = 0; i < src.length; i++) HOOKS.words.push(src[i]);
  for(var j = 0; j < motes.length; j++){
    var m = motes[j];
    if(m.w && HOOKS.words.indexOf(m.w) < 0) m.w = HOOKS.words[Math.floor(Math.random() * HOOKS.words.length)];
  }
};
HOOKS.applyWords(S.words);
function rnd(a,b){ return a+(b-a)*Math.random(); }
function pop(x,y,txt,col){ pops.push({x:x,y:y,txt:txt,col:col||'180,235,255',life:1}); }

function spawn(type,x,y){
			if(motes.length>S.capA) return;
  var t = type===undefined ? (Math.random()<.45?0:(Math.random()<.62?1:2)) : type;
  motes.push({ x: x===undefined? rnd(0,W):x, y: y===undefined? rnd(0,H):y,
    vx:rnd(-.25,.25), vy:rnd(-.15,.15), ph:rnd(0,6.28), t:t,
			    r:TYPES[t].r, w:null });
}
			for(var i=0;i<S.count;i++) spawn();
function spawnWord(x,y){
			if(motes.length>S.capB) return;
  var m={x:x===undefined? rnd(30,W-30):x, y:y===undefined? rnd(40,H*0.85):y, vx:rnd(-.12,.12), vy:rnd(-.08,.08),
			    ph:rnd(0,6.28), t:0, r:11,
    w:WORDS[Math.floor(Math.random()*WORDS.length)]};
  motes.push(m);
}

for(var i=0;i<8;i++) jellies.push({x:rnd(0,1), y:rnd(0,1), r:rnd(16,34), ph:rnd(0,6.28), sp:rnd(0.10,0.26), hue:Math.random()<0.5?1:0});

			var whale={x:0,y:0,ang:0,flip:1,bx:0,by:0};
function whaleAt(t){ return { x: W*0.5+Math.sin(t*0.00013)*W*0.35+Math.sin(t*0.00047)*W*0.07,
                               y: H*0.44+Math.sin(t*0.00021+1.7)*H*0.17+Math.sin(t*0.00059)*H*0.045 }; }

var whispers=['','这里没有到期预警，只有水母。','今天不问海。','鲸鱼不解释，鲸鱼只是游。','有人给我钱让我自己玩，那我就玩得认真一点。','深海里没人催你。','我把它们吃下去，它们就变成我的了。','水面上的事，等浮上去再说。'];
var wi=1, lastWhisper=0;


function drawWhale(){
  var tail=Math.sin(T*0.0016)*0.20;
  cx.save();
  cx.translate(whale.x,whale.y);
  cx.scale(whale.flip,1);
  cx.rotate(Math.sin(T*0.0006)*0.045);
  cx.globalCompositeOperation='lighter';
  var au=cx.createRadialGradient(0,0,12,0,0,124);
  au.addColorStop(0,'rgba(130,205,255,0.10)');
  au.addColorStop(0.55,'rgba(110,190,255,0.045)');
  au.addColorStop(1,'rgba(110,190,255,0)');
  cx.fillStyle=au;
  cx.beginPath(); cx.arc(0,0,124,0,6.2832); cx.fill();
  cx.save();
  cx.translate(-64,-1); cx.rotate(tail);
  cx.fillStyle='rgba(38,92,140,0.96)';
  cx.beginPath();
  cx.moveTo(6,-4);
  cx.bezierCurveTo(-12,-8,-30,-24,-40,-36);
  cx.bezierCurveTo(-28,-26,-14,-16,-4,-11);
  cx.bezierCurveTo(-9,-4,-9,4,-4,11);
  cx.bezierCurveTo(-14,16,-28,26,-38,36);
  cx.bezierCurveTo(-26,26,-10,10,6,4);
  cx.closePath(); cx.fill();
  cx.restore();
  var bg=cx.createLinearGradient(0,-30,0,26);
  bg.addColorStop(0,'rgba(104,178,232,0.97)');
  bg.addColorStop(0.5,'rgba(52,112,164,0.97)');
  bg.addColorStop(1,'rgba(18,48,78,0.97)');
  cx.fillStyle=bg;
  cx.beginPath();
  cx.moveTo(-64,-3);
  cx.bezierCurveTo(-36,-31,20,-33,54,-17);
  cx.bezierCurveTo(71,-10,75,3,61,12);
  cx.bezierCurveTo(40,20,16,22,-4,22);
  cx.bezierCurveTo(-32,22,-52,15,-64,5);
  cx.closePath(); cx.fill();
  cx.strokeStyle='rgba(190,235,255,0.30)'; cx.lineWidth=1;
  cx.beginPath();
  cx.moveTo(-62,-3);
  cx.bezierCurveTo(-36,-29,20,-31,53,-16);
  cx.stroke();
  cx.fillStyle='rgba(178,222,255,0.22)';
  cx.beginPath();
  cx.moveTo(44,13);
  cx.bezierCurveTo(10,25,-30,24,-60,8);
  cx.bezierCurveTo(-24,20,18,20,46,12);
  cx.closePath(); cx.fill();
  cx.strokeStyle='rgba(12,36,60,0.75)'; cx.lineWidth=1.2;
  cx.beginPath();
  cx.moveTo(57,6);
  cx.bezierCurveTo(46,13,34,16,20,15);
  cx.stroke();
  cx.fillStyle='rgba(34,86,132,0.95)';
  cx.beginPath();
  cx.moveTo(22,15);
  cx.bezierCurveTo(12,34,-6,46,-24,42);
  cx.bezierCurveTo(-10,34,2,26,6,13);
  cx.closePath(); cx.fill();
  cx.fillStyle='rgba(242,252,255,0.96)';
  cx.beginPath(); cx.arc(44,-5,2.9,0,6.2832); cx.fill();
  cx.fillStyle='rgba(16,38,58,0.95)';
  cx.beginPath(); cx.arc(44.9,-5,1.5,0,6.2832); cx.fill();
  for(var i=0;i<6;i++){
    var lx=-52+i*19, ly=4+Math.sin(i*2.2)*5;
    cx.fillStyle='rgba(150,235,255,'+(0.28+0.32*Math.sin(T*0.003+i))+')';
    cx.beginPath(); cx.arc(lx,ly,1.4,0,6.2832); cx.fill();
  }
  cx.restore();
  if(Math.random()<0.02){
    var bx=whale.x+whale.flip*6, by=whale.y-30;
    for(var i=0;i<3;i++) bubbles.push({x:bx+rnd(-7,7),y:by-rnd(0,12),r:rnd(1.2,3.2),sp:rnd(0.35,0.95),life:1,ph:rnd(0,6)});
  }
}

function drawJelly(j){
  var x=j.x*W, y=j.y*H, pulse=1+0.13*Math.sin(T*0.0016+j.ph);
  var r=j.r*pulse;
  var col=j.hue? '190,220,255':'200,255,240';
  cx.save(); cx.globalCompositeOperation='lighter';
  cx.fillStyle='rgba('+col+',0.10)';
  cx.beginPath(); cx.ellipse(x,y,r,r*0.82,0,Math.PI,0,true); cx.fill();
  cx.strokeStyle='rgba('+col+',0.34)'; cx.lineWidth=1;
  cx.beginPath(); cx.ellipse(x,y,r,r*0.82,0,Math.PI,0,true); cx.stroke();
  for(var k=0;k<5;k++){
    var off=(k-2)/2.2, len=r*(2.1+0.5*Math.sin(T*0.0013+k));
    cx.beginPath();
    cx.moveTo(x+off*r*0.7,y);
    for(var s=1;s<=4;s++){
      var t2=s/4;
      cx.lineTo(x+off*r*0.7+Math.sin(T*0.002+t2*4+k)*r*0.28*t2, y+len*t2);
    }
    cx.strokeStyle='rgba('+col+','+(0.24-0.04*k)+')'; cx.stroke();
  }
  cx.restore();
}

			function frame(ts){
			  if(!alive) return;
			  if(!S.enabled){ running = false; return; }
			  if(reduce && frames > 120){ running = false; return; }
			  raf = requestAnimationFrame(frame);
			  if(document.hidden) return;
			  if(!last) last = ts;
			  if(ts - last > 600) minInt = 26;
			  var dt = Math.min(120, ts - last);
			  if(dt < minInt) return;
			  frames++; var fT0 = fnow();
			  last = ts; T += dt;
			if(lamp.on){ lamp.vx *= 0.80; lamp.vy *= 0.80; }
			var LZR = S.padR, LZX = W - S.padM, LZY = H - S.padM;
			var lzOn = false;
			if(S.pad && lamp.on){ var lzx = lamp.x - LZX, lzy = lamp.y - LZY; lzOn = (lzx*lzx + lzy*lzy) < LZR*LZR; }
			var w=whaleAt(T), w2=whaleAt(T+260);
			if(lzOn && (w.x-LZX)*(w.x-LZX)+(w.y-LZY)*(w.y-LZY) < (LZR+58)*(LZR+58)){
			  var wzx=w.x-LZX, wzy=w.y-LZY, wz=Math.sqrt(wzx*wzx+wzy*wzy)+1;
			  var wux, wuy;
			  if(wz<26){ wux=-0.7071; wuy=-0.7071; } else { wux=wzx/wz; wuy=wzy/wz; }
			  var wf=S.whalePower*(1-0.117647*(wz/(LZR+58)));
			  whale.bx+=wux*wf; whale.by+=wuy*wf;
			}
			whale.bx*=0.978; whale.by*=0.978;
			var wbl=Math.sqrt(whale.bx*whale.bx+whale.by*whale.by);
			var wcap=S.whaleCap; if(wbl>wcap){ whale.bx*=wcap/wbl; whale.by*=wcap/wbl; }
			whale.x=w.x+whale.bx; whale.y=w.y+whale.by;
			whale.ang=Math.atan2(w2.y-w.y,w2.x-w.x);
			whale.flip = Math.cos(whale.ang)<0? -1:1;
			if(!vgC||vgC.width!==cv.width||vgC.height!==cv.height) bakeVG();
			if(T-bgT>1000||!bgC){ bakeBG(); bgT=T; }
			cx.setTransform(1,0,0,1,0,0);
			cx.drawImage(bgC,0,0,cv.width,cv.height);
			cx.setTransform(DPR,0,0,DPR,0,0);
  for(var i=0;i<jellies.length;i++){
    var j=jellies[i];
    j.y-=j.sp*dt/16000; j.x+=Math.sin(T*0.00017+j.ph)*0.00006;
    if(j.y<-0.12){ j.y=1.12; j.x=rnd(0.05,0.95); j.r=rnd(16,34); }
    if(j.x<-0.05) j.x=1.05; if(j.x>1.05) j.x=-0.05;
    drawJelly(j);
  }
  cx.save(); cx.globalCompositeOperation='lighter';
			for(var i=motes.length-1;i>=0;i--){
			  var m=motes[i];
			var mv=S.flow*S.speed;
			if(S.motion==='fall'||S.motion==='rise'){
			  m.vy+=0.012*(S.motion==='fall'?1:-1)*mv; m.vx+=Math.sin(T*0.0011+m.ph)*0.0030*mv;
			} else if(S.motion==='current'){
			  var cfx=Math.sin(m.y*0.0032+T*0.00030)*0.9+0.55, cfy=Math.sin(m.x*0.0026-T*0.00021)*0.85;
			  m.vx+=(cfx*0.055*mv-m.vx*0.03); m.vy+=(cfy*0.055*mv-m.vy*0.03);
			} else if(S.motion==='swirl'){
			  var sdx=m.x-W*0.5, sdy=m.y-H*0.5, sd=Math.sqrt(sdx*sdx+sdy*sdy)+1, sk=0.075*mv;
			  m.vx+=(-sdy/sd*sk-sdx/sd*0.010*mv)-m.vx*0.012; m.vy+=(sdx/sd*sk-sdy/sd*0.010*mv)-m.vy*0.012;
			} else {
			  var a=Math.sin(m.y*0.0055+T*0.00035+m.ph)*1.15+Math.sin(m.x*0.0034-T*0.00022)*0.85;
			  m.vx+=Math.cos(a)*0.034*S.speed; m.vy+=(Math.sin(a)*0.026-0.006)*S.speed;
			}
			var dmp=0.986;
			if(S.attract && lamp.on && !(m.lz>0)){
			  var ldx=lamp.x-m.x, ldy=lamp.y-m.y, ld2=ldx*ldx+ldy*ldy;
			if(ld2<S.ar2){
			    var ld=Math.sqrt(ld2)+1, lf=1-ld/S.ar;
			    dmp=0.986-0.026*lf;
			    if(ld<110){ var pd=0.050*S.ak*(1-ld/110)*lf; m.vx-=ldx/ld*pd; m.vy-=ldy/ld*pd; }
			    m.vx+=(ldx*0.0012*S.ak+lamp.vx*0.12)*lf+ldy*0.0008*lf;
			    m.vy+=(ldy*0.0012*S.ak+lamp.vy*0.12)*lf-ldx*0.0008*lf;
			  }
			}
			for(var r=0;r<ripples.length;r++){
			  var rp=ripples[r], rdx=m.x-rp.x, rdy=m.y-rp.y, rd=Math.sqrt(rdx*rdx+rdy*rdy)+1;
			  if(Math.abs(rd-rp.r)<34){ var f2=(1-rd/(rp.max+1))*0.9; m.vx+=rdx/rd*f2; m.vy+=rdy/rd*f2; }
			}
			if(S.pad && lzOn){
			  var mzx=m.x-LZX, mzy=m.y-LZY, mz2=mzx*mzx+mzy*mzy;
			  if(mz2<LZR*LZR){
			    var mz=Math.sqrt(mz2)+1, mf=S.padPower*(1-0.625*mz/LZR);
			    m.vx+=mzx/mz*mf; m.vy+=mzy/mz*mf; m.lz=56;
			  }
			}
			if(m.lz>0){ m.lz--; m.vx*=0.996; m.vy*=0.996; } else { m.vx*=dmp; m.vy*=dmp; }
			var sp2=m.vx*m.vx+m.vy*m.vy;
			var cap=m.lz>0? 6*S.padPower : 8*S.speed;
			if(sp2>cap*cap){ var sk=cap/Math.sqrt(sp2); m.vx*=sk; m.vy*=sk; }
			m.x+=m.vx; m.y+=m.vy;
			if(S.breathe){ var bs=Math.sin(T*0.0011*S.breatheRate+m.ph); m.bz=1+0.42*bs; m.br=bs>0.33?0:(bs>-0.33?1:2); } else { m.bz=1; m.br=0; }
			  if(m.x<-28) m.x=W+28; if(m.x>W+28) m.x=-28;
			  if(m.y<-28) m.y=H+28; if(m.y>H+28) m.y=-28;
			}
			if(!CORE){ CORE=[]; HALO=[]; CB=[]; HB=[];
			  for(var ti=0;ti<TYPES.length;ti++){ CORE.push('rgba('+TYPES[ti].col+',0.85)'); HALO.push('rgba('+TYPES[ti].col+',0.10)');
			    var cb=[],hb=[]; for(var bl=0;bl<BA.length;bl++){ cb.push('rgba('+TYPES[ti].col+','+(0.85*BA[bl]).toFixed(3)+')'); hb.push('rgba('+TYPES[ti].col+','+(0.10*BA[bl]).toFixed(3)+')'); }
			    CB.push(cb); HB.push(hb); } }
			var bN=S.breathe?BA.length:1;
			for(var bl=0;bl<bN;bl++){
			  for(var ti=0;ti<TYPES.length;ti++){
			    cx.fillStyle=(bN>1?CB[ti][bl]:CORE[ti]); cx.beginPath();
			    for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(q.w||q.t!==ti||(bN>1&&(q.br||0)!==bl)) continue; var cr=q.r*(q.bz||1); cx.moveTo(q.x+cr,q.y); cx.arc(q.x,q.y,cr,0,6.2832); }
			    cx.fill();
			    cx.fillStyle=(bN>1?HB[ti][bl]:HALO[ti]); cx.beginPath();
			    for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(q.w||q.t!==ti||(bN>1&&(q.br||0)!==bl)) continue; var hr=q.r*(q.bz||1)*4.2; cx.moveTo(q.x+hr,q.y); cx.arc(q.x,q.y,hr,0,6.2832); }
			    cx.fill();
			  }
			}
			for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(!q.w) continue; cx.font='12px Georgia,serif'; cx.textAlign='center'; cx.fillStyle='rgba(160,225,255,0.42)'; cx.fillText(q.w,q.x,q.y); }
			if(S.ring && lamp.on){
			  var lp=0.5+0.5*Math.sin(T*0.0024);
			  cx.lineWidth=1;
			  cx.strokeStyle='rgba(150,215,255,'+(0.05+0.05*lp)+')';
			  cx.beginPath(); cx.arc(lamp.x,lamp.y,86+9*lp,0,6.2832); cx.stroke();
			  cx.strokeStyle='rgba(120,190,255,'+(0.03+0.03*lp)+')';
			  cx.beginPath(); cx.arc(lamp.x,lamp.y,S.ar-6+8*lp,0,6.2832); cx.stroke();
			}
			if(S.pad){
			var lzp = 0.5 + 0.5*Math.sin(T*0.0026);
			cx.lineWidth = 1.2;
			cx.strokeStyle = 'rgba(255,168,96,' + (lzOn ? (0.26 + 0.22*lzp) : 0.10) + ')';
			cx.beginPath(); cx.arc(LZX, LZY, LZR, 0, 6.2832); cx.stroke();
			cx.strokeStyle = 'rgba(255,140,70,' + (lzOn ? (0.14 + 0.12*lzp) : 0.05) + ')';
			cx.beginPath(); cx.arc(LZX, LZY, LZR*0.58, 0, 6.2832); cx.stroke();
			if(lzOn){
			  var lzg = cx.createRadialGradient(LZX, LZY, 8, LZX, LZY, LZR);
			  lzg.addColorStop(0, 'rgba(255,150,80,0.15)');
			  lzg.addColorStop(1, 'rgba(255,120,60,0)');
			  cx.fillStyle = lzg; cx.beginPath(); cx.arc(LZX, LZY, LZR, 0, 6.2832); cx.fill();
			}
			}
  cx.restore();
  drawWhale();
  cx.save(); cx.globalCompositeOperation='lighter';
  for(var i=ripples.length-1;i>=0;i--){
    var rp=ripples[i]; rp.r+=1.9; rp.a*=0.975;
    if(rp.r>rp.max||rp.a<0.01){ ripples.splice(i,1); continue; }
    cx.strokeStyle='rgba(150,220,255,'+rp.a+')'; cx.lineWidth=1.1;
    cx.beginPath(); cx.arc(rp.x,rp.y,rp.r,0,6.2832); cx.stroke();
    cx.strokeStyle='rgba(150,220,255,'+(rp.a*0.4)+')';
    cx.beginPath(); cx.arc(rp.x,rp.y,rp.r*0.62,0,6.2832); cx.stroke();
  }
  for(var i=bubbles.length-1;i>=0;i--){
    var b=bubbles[i]; b.y-=b.sp; b.x+=Math.sin(T*0.002+b.ph)*0.35; b.life-=0.004;
    if(b.life<=0||b.y<-20){ bubbles.splice(i,1); continue; }
    cx.strokeStyle='rgba(200,240,255,'+(0.35*b.life)+')'; cx.lineWidth=1;
    cx.beginPath(); cx.arc(b.x,b.y,b.r,0,6.2832); cx.stroke();
  }
  for(var i=pops.length-1;i>=0;i--){
    var p=pops[i]; p.y-=0.55; p.life-=0.011;
    if(p.life<=0){ pops.splice(i,1); continue; }
    cx.font='12px Georgia,serif'; cx.textAlign='center';
    cx.fillStyle='rgba('+p.col+','+Math.max(0,p.life)+')';
    cx.fillText(p.txt,p.x,p.y);
  }
  cx.restore();
			cx.drawImage(vgC,0,0,W,H);
			if(T - lastWhisper > 15000){
			  lastWhisper = T; wi = (wi + 1) % whispers.length;
			  whisperText = whispers[wi]; whisperAlpha = 0;
			}
			whisperAlpha += (1 - whisperAlpha) * 0.012;
			cx.globalCompositeOperation = 'source-over';
			cx.textAlign = 'left';
			cx.font = '15px Georgia,serif';
			cx.fillStyle = 'rgba(147,203,236,' + (0.42 * whisperAlpha) + ')';
			cx.fillText(whisperText, 26, H - 30);
			framesW++;
			fCost = fCost * 0.85 + (fnow() - fT0) * 0.15;
			if(ts - qLast > 1200){
			  qLast = ts; fpsShown = Math.round(framesW * 1000 / 1200); framesW = 0;
			}
			minInt = Math.max(26, Math.min(120, fCost * 2));
}



			function onMove(e){
			  var nx = e.clientX - (VIEW === 'mini' ? mini.x : 0), ny = e.clientY - (VIEW === 'mini' ? mini.y : 0);
			  if(lamp.on){
			    lamp.vx = Math.max(-46, Math.min(46, nx - lamp.x));
			    lamp.vy = Math.max(-46, Math.min(46, ny - lamp.y));
			  } else { lamp.vx = 0; lamp.vy = 0; }
			  lamp.x = nx; lamp.y = ny; lamp.on = true;
			}
			function onLeave(){ lamp.on = false; lamp.vx = 0; lamp.vy = 0; }
			window.addEventListener('mousemove', onMove, { passive: true });
			window.addEventListener('mouseleave', onLeave);
			timers.push(setInterval(function(){
			  if(!alive || !S.enabled || document.hidden) return;
			  var mx = whale.x + whale.flip * 58, my = whale.y + 1;
			  for(var i = motes.length - 1; i >= 0; i--){
			    var m = motes[i];
			    var rr = m.w ? 26 : 30;
			    if((m.x-mx)*(m.x-mx) + (m.y-my)*(m.y-my) < rr*rr){
			      motes.splice(i,1); eaten++;
			      if(m.w){ wordsEaten++; if(S.popWord) pop(mx, my-18, '吃掉「' + m.w + '」', '255,190,140'); } else if(S.popToken){ pop(mx, my-15, '-1 token', '255,190,140'); }
			      ripples.push({x:mx,y:my,r:4,max:60,a:0.35}); if(ripples.length>24) ripples.shift();
			      if(motes.length < S.restock){ if(Math.random() < 0.1) spawnWord(); else spawn(); }
			    }
			  }
			}, 120));
			timers.push(setInterval(function(){ if(!alive || !S.enabled || document.hidden) return; spawnWord(); }, 12000));
			HOOKS.respawn = function(n){
			  if(!alive || !S.enabled) return;
			  while(motes.length > n) motes.pop();
			  for(var i = motes.length; i < n; i++) spawn();
			};
			// 控制台总开关（2026-10-17）：停 = 停 rAF、藏画布、两个定时器一起歇着；
			// 恢复 = 重新排一帧，并让面板把光点数量补齐。
			// ---- 看海模式（2026-10-18）：全屏屏保 / 摸鱼小窗 / 回到壁纸 ----
			// VIEW 只在本次会话里有效、不写 localStorage：刷新永远回壁纸，免得一刷新就被锁在屏保里。
			// 层叠：wall(-1) < mini(2147482990) < 齿轮(2147483000) < 面板(2147483001) < full(2147483002) < 提示条(2147483003)
			var VIEW = 'wall';
			var mini = null, gripEl = null, hintEl = null, hintT = 0;
			var drag = null, noClick = false;
			var HINT_FULL = '点击画面或按 Esc 退出';
			var HINT_MINI = '拖动移动 · 右下角缩放 · 点击画面或按 Esc 退出';
			function viewClampX(x, w){ var vw = window.innerWidth || 1200; return Math.max(90 - w, Math.min(vw - 90, x)); }
			function viewClampY(y, h){ var vh = window.innerHeight || 800; return Math.max(4, Math.min(Math.max(4, vh - h - 4), y)); }
			function miniInit(){
			  var vw = window.innerWidth || 1200, vh = window.innerHeight || 800;
			  var w = Math.max(280, Math.min(560, Math.round(vw * 0.36)));
			  var h = Math.max(180, Math.min(Math.round(w * 0.62), Math.max(180, vh - 120)));
			  mini = { x: vw - w - 28, y: vh - h - 28, w: w, h: h };
			  if(mini.y < 56) mini.y = 56;
			  mini.x = viewClampX(mini.x, mini.w);
			  mini.y = viewClampY(mini.y, mini.h);
			}
			function hintEnsure(){
			  if(hintEl || !document.body) return;
			  hintEl = document.createElement('div');
			  hintEl.id = HINT_ID;
			  document.body.appendChild(hintEl);
			}
			function hintPlace(){
			  if(!hintEl) return;
			  if(VIEW === 'mini' && mini){
			    var cx = Math.round(mini.x + mini.w / 2);
			    var vw = window.innerWidth || 1200;
			    hintEl.style.left = Math.max(150, Math.min(vw - 150, cx)) + 'px';
			    var below = Math.round(mini.y + mini.h + 10);
			    // 小窗贴到屏幕底部时，提示条改挂到小窗上方，否则会被视口切掉
			    hintEl.style.top = (below > (window.innerHeight || 800) - 34 ? Math.max(6, Math.round(mini.y) - 36) : below) + 'px';
			    hintEl.style.bottom = 'auto';
			  } else {
			    hintEl.style.left = '50%';
			    hintEl.style.top = 'auto';
			    hintEl.style.bottom = '32px';
			  }
			}
			function showHint(txt){
			  hintEnsure();
			  if(!hintEl) return;
			  hintEl.textContent = txt;
			  hintPlace();
			  hintEl.style.opacity = '1';
			  if(hintT) clearTimeout(hintT);
			  hintT = setTimeout(function(){ if(hintEl) hintEl.style.opacity = '0'; hintT = 0; }, 5200);
			}
			function hideHint(){
			  if(hintT){ clearTimeout(hintT); hintT = 0; }
			  if(hintEl) hintEl.style.opacity = '0';
			}
			function gripEnsure(){
			  if(gripEl || !document.body) return;
			  gripEl = document.createElement('div');
			  gripEl.id = GRIP_ID;
			  gripEl.title = '拖动缩放';
			  gripEl.addEventListener('mousedown', function(e){ e.preventDefault(); e.stopPropagation(); dragStart('size', e); });
			  document.body.appendChild(gripEl);
			}
			function gripPlace(){
			  if(!gripEl) return;
			  if(VIEW !== 'mini' || !mini){ gripEl.style.display = 'none'; return; }
			  gripEl.style.display = 'block';
			  gripEl.style.left = Math.round(mini.x + mini.w - 22) + 'px';
			  gripEl.style.top = Math.round(mini.y + mini.h - 22) + 'px';
			}
			function applyViewStyle(){
			  if(VIEW === 'mini'){
			    if(!mini) miniInit();
			    cv.style.zIndex = '2147482990';
			    cv.style.pointerEvents = 'auto';
			    cv.style.left = Math.round(mini.x) + 'px';
			    cv.style.top = Math.round(mini.y) + 'px';
			    cv.style.width = Math.round(mini.w) + 'px';
			    cv.style.height = Math.round(mini.h) + 'px';
			    cv.style.borderRadius = '13px';
			    cv.style.border = '1px solid rgba(255,168,96,.42)';
			    cv.style.boxShadow = '0 18px 46px rgba(0,0,0,.55)';
			    cv.style.cursor = 'move';
			  } else if(VIEW === 'full'){
			    cv.style.zIndex = '2147483002';
			    cv.style.pointerEvents = 'auto';
			    cv.style.left = '0';
			    cv.style.top = '0';
			    cv.style.width = '100vw';
			    cv.style.height = '100vh';
			    cv.style.borderRadius = '0';
			    cv.style.border = '0';
			    cv.style.boxShadow = 'none';
			    cv.style.cursor = 'pointer';
			  } else {
			    cv.style.zIndex = '-1';
			    cv.style.pointerEvents = 'none';
			    cv.style.left = '0';
			    cv.style.top = '0';
			    cv.style.width = '100vw';
			    cv.style.height = '100vh';
			    cv.style.borderRadius = '0';
			    cv.style.border = '0';
			    cv.style.boxShadow = 'none';
			    cv.style.cursor = '';
			  }
			  gripPlace();
			  hintPlace();
			}
			function rebaseMotes(ow, oh){
			  if(!ow || !oh || !motes.length) return;
			  var sx = W / ow, sy = H / oh;
			  for(var i = 0; i < motes.length; i++){
			    var m = motes[i];
			    m.x = m.x * sx; m.y = m.y * sy;
			    if(m.x < -28) m.x = W + 28; else if(m.x > W + 28) m.x = -28;
			    if(m.y < -28) m.y = H + 28; else if(m.y > H + 28) m.y = -28;
			  }
			}
			function setView(mode){
			  if(!alive) return;
			  if(mode !== 'mini' && mode !== 'full') mode = 'wall';
			  if(mode !== 'wall' && !S.enabled) return;
			  var ow = W || window.innerWidth, oh = H || window.innerHeight;
			  VIEW = mode;
			  if(mode === 'mini' && !mini) miniInit();
			  if(mode !== 'wall'){ gripEnsure(); hintEnsure(); }
			  applyViewStyle();
			  resize();
			  rebaseMotes(ow, oh);
			  lamp.on = false; lamp.vx = 0; lamp.vy = 0;
			  if(VIEW === 'wall'){
			    if(S.enabled && HOOKS.tokens && HOOKS.tokens.apply) HOOKS.tokens.apply();
			    hideHint();
			  } else {
			    if(HOOKS.tokens && HOOKS.tokens.reset) HOOKS.tokens.reset();
			    showHint(VIEW === 'full' ? HINT_FULL : HINT_MINI);
			  }
			  if(HOOKS.refreshView) HOOKS.refreshView();
			}
			function dragStart(kind, e){
			  if(VIEW !== 'mini' || !mini) return;
			  drag = { kind: kind, sx: e.clientX, sy: e.clientY, ox: mini.x, oy: mini.y, ow: mini.w, oh: mini.h, moved: false };
			  window.addEventListener('mousemove', dragMove, true);
			  window.addEventListener('mouseup', dragEnd, true);
			}
			function dragMove(e){
			  if(!drag || !mini) return;
			  var dx = e.clientX - drag.sx, dy = e.clientY - drag.sy;
			  if(!drag.moved){
			    if(dx * dx + dy * dy < 25) return;
			    drag.moved = true;
			  }
			  if(drag.kind === 'move'){
			    mini.x = viewClampX(drag.ox + dx, mini.w);
			    mini.y = viewClampY(drag.oy + dy, mini.h);
			    applyViewStyle();
			  } else {
			    var vw = window.innerWidth || 1200, vh = window.innerHeight || 800;
			    mini.w = Math.max(280, Math.min(vw - 40, Math.round(drag.ow + dx)));
			    mini.h = Math.max(180, Math.min(vh - 40, Math.round(drag.oh + dy)));
			    mini.x = viewClampX(mini.x, mini.w);
			    mini.y = viewClampY(mini.y, mini.h);
			    applyViewStyle();
			    resize();
			  }
			}
			function dragEnd(){
			  if(!drag) return;
			  noClick = drag.moved;
			  drag = null;
			  window.removeEventListener('mousemove', dragMove, true);
			  window.removeEventListener('mouseup', dragEnd, true);
			  if(noClick) setTimeout(function(){ noClick = false; }, 260);
			}
			function onCvDown(e){
			  if(VIEW === 'wall' || VIEW === 'full') return;
			  if(e.button !== 0) return;
			  e.preventDefault();
			  dragStart('move', e);
			}
			function onCvClick(e){
			  if(VIEW === 'wall') return;
			  var skip = noClick;
			  noClick = false;
			  e.preventDefault(); e.stopPropagation();
			  if(skip) return;
			  setView('wall');
			}
			function onCvWheel(e){ if(VIEW !== 'wall'){ e.preventDefault(); } }
			function onWinResize(){
			  if(drag) return;
			  if(VIEW === 'mini' && mini){
			    mini.w = Math.max(280, Math.min(mini.w, Math.max(280, window.innerWidth - 40)));
			    mini.h = Math.max(180, Math.min(mini.h, Math.max(180, window.innerHeight - 40)));
			    mini.x = viewClampX(mini.x, mini.w);
			    mini.y = viewClampY(mini.y, mini.h);
			    applyViewStyle();
			  }
			  resize();
			  gripPlace();
			  hintPlace();
			}
			cv.addEventListener('mousedown', onCvDown);
			cv.addEventListener('click', onCvClick);
			cv.addEventListener('wheel', onCvWheel, { passive: false });
			window.addEventListener('resize', onWinResize);
			HOOKS.getMode = function(){ return VIEW; };
			HOOKS.setMode = setView;
			var running = false;
			function run(){
			  if(!alive || running || !S.enabled) return;
			  running = true;
			  raf = requestAnimationFrame(frame);
			}
			function halt(){
			  running = false;
			  if(raf){ cancelAnimationFrame(raf); raf = 0; }
			}
			HOOKS.setEnabled = function(on){
			  if(!alive) return;
			  var want = on !== false;
			  cv.style.display = want ? '' : 'none';
			  if(want) run(); else { if(VIEW !== 'wall') setView('wall'); halt(); }
			};
			HOOKS.setEnabled(S.enabled);
			return function stop(){
			  alive = false;
			  if(raf) cancelAnimationFrame(raf);
			  for(var i = 0; i < timers.length; i++) clearInterval(timers[i]);
			  window.removeEventListener('resize', resize);
			  window.removeEventListener('mousemove', onMove);
			  window.removeEventListener('mouseleave', onLeave);
			  window.removeEventListener('resize', onWinResize);
			  cv.removeEventListener('mousedown', onCvDown);
			  cv.removeEventListener('click', onCvClick);
			  cv.removeEventListener('wheel', onCvWheel);
			  window.removeEventListener('mousemove', dragMove, true);
			  window.removeEventListener('mouseup', dragEnd, true);
			  if(hintT) clearTimeout(hintT);
			  if(gripEl && gripEl.parentNode) gripEl.parentNode.removeChild(gripEl);
			  if(hintEl && hintEl.parentNode) hintEl.parentNode.removeChild(hintEl);
			  gripEl = null; hintEl = null;
			};
		}

		function apply(ctx){
			sLoad();
			var canvas = document.createElement("canvas");
			canvas.id = CANVAS_ID;
			var style = document.createElement("style");
			style.id = STYLE_ID;
			style.textContent = CSS_TEXT + PANEL_CSS;
			var tokens = makeTokenApplier();
			var pond = null;
			function mount(){
				document.body.insertBefore(canvas, document.body.firstChild);
				document.head.appendChild(style);
				if(S.enabled) tokens.apply();
				HOOKS.tokens = tokens;
				HOOKS.canvas = canvas;
				pond = start(canvas);
				panelMount();
			}
			var timer = 0;
			var observer = new MutationObserver(function(){
				clearTimeout(timer);
				timer = setTimeout(function(){ if(S.enabled) tokens.apply(); }, 180);
			});
			observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class"] });
			function boot(){
				mount();
				if(document.body) observer.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class"] });
			}
			if(document.body) boot();
			else document.addEventListener("DOMContentLoaded", boot);
			return function(){
				observer.disconnect();
				clearTimeout(timer);
				document.removeEventListener("DOMContentLoaded", boot);
				panelUnmount();
				tokens.reset();
				if(pond){ pond(); pond = null; }
				if(canvas.parentNode) canvas.parentNode.removeChild(canvas);
				if(style.parentNode) style.parentNode.removeChild(style);
			};
		}

		exports.isPlugin = true;
		exports.inject = [];
		exports.apply = apply;
		return module.exports;
	}
});
