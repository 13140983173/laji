window.__ModuleLoader__.load({
	id: "dsh-skin-whale-fantasy",
	factory: function () {
		var module = { exports: {} };
		var exports = module.exports;

		// ---------------------------------------------------------------------
		// 鲸落 · 未至之境 — 动态层
		//
		// 皮肤包本身只换色与网格（纯 CSS，静态）。这里补一层「深海在动」：
		// 极光呼吸、星尘上浮、全息扫描线、以及跟随指针的极轻视差。
		// 全部是 pointer-events:none 的装饰层，不接管鼠标键盘；星尘被上下遮罩
		// 挡在内容区之外，只从页眉和页脚透出来，正文上不落点。
		//
		// 颜色一律取皮肤变量（--wf-h / --wf-h2），四个配色变体、日后改色板都能
		// 直接跟随，不用在这里写死色值。`prefers-reduced-motion` 下只留静态层。
		// ---------------------------------------------------------------------
		var ROOT_ID = "wf-motion";
		var STYLE_ID = "wf-motion-style";
		var NL = String.fromCharCode(10);
		var CSS_TEXT = [
			"#" + ROOT_ID + "{position:fixed;inset:0;z-index:0;pointer-events:none;overflow:hidden;contain:strict;mix-blend-mode:screen}",
			"#" + ROOT_ID + ">div{position:absolute;pointer-events:none}",
			// 底部极光：两层径向渐变，18s 呼吸一次，指针带一点点位移。
			"#" + ROOT_ID + " .wf-aurora{left:-10%;right:-10%;top:52%;bottom:-28%;",
			"background:radial-gradient(46% 42% at 22% 76%,hsl(var(--wf-h,222) 100% 62% / .17),transparent 70%),",
			"radial-gradient(42% 36% at 78% 86%,hsl(var(--wf-h2,168) 100% 62% / .12),transparent 74%);",
			"transform:translate3d(calc(var(--wf-px,0) * 12px),calc(var(--wf-py,0) * 9px),0);",
			"animation:wf-aurora 18s ease-in-out infinite alternate}",
			// 扫描光带：11s 自上而下走一遍，像全息投影在刷新。
			"#" + ROOT_ID + " .wf-scan{left:0;right:0;height:22vh;top:-22vh;",
			"background:linear-gradient(180deg,transparent,hsl(var(--wf-h,222) 100% 66% / .05) 42%,",
			"hsl(var(--wf-h2,168) 100% 64% / .075) 58%,transparent);",
			"animation:wf-scan 11s linear infinite}",
			// 星尘：四组错开的点阵向上漂；上下各 24% 做遮罩，中间正文区不落点。
			"#" + ROOT_ID + " .wf-dust{inset:0;opacity:.5;",
			"background-image:radial-gradient(1.4px 1.4px at 22% 28%,#fff9,transparent 60%),",
			"radial-gradient(1.2px 1.2px at 68% 62%,hsl(var(--wf-h2,168) 100% 74% / .85),transparent 60%),",
			"radial-gradient(1.6px 1.6px at 44% 82%,hsl(var(--wf-h,222) 100% 76% / .7),transparent 60%),",
			"radial-gradient(1px 1px at 84% 18%,#fff7,transparent 60%);",
			"background-size:340px 260px,420px 320px,300px 220px,520px 380px;",
			"animation:wf-dust 26s linear infinite;",
			"mask-image:linear-gradient(180deg,#000 0%,transparent 24%,transparent 76%,#000 100%);",
			"-webkit-mask-image:linear-gradient(180deg,#000 0%,transparent 24%,transparent 76%,#000 100%)}",
			// 四边一圈内发光，把画面收进「舱内」。
			"#" + ROOT_ID + " .wf-frame{inset:0;box-shadow:inset 0 0 140px hsl(var(--wf-h,222) 100% 50% / .12)}",
			"@keyframes wf-aurora{0%{opacity:.55;transform:translate3d(0,0,0) scale(1)}",
			"100%{opacity:1;transform:translate3d(0,-2.5%,0) scale(1.06)}}",
			"@keyframes wf-scan{0%{top:-22vh}100%{top:104vh}}",
			"@keyframes wf-dust{0%{background-position:0 0,0 0,0 0,0 0}",
			"100%{background-position:0 -260px,0 -320px,0 -220px,0 -380px}}",
			"@media (prefers-reduced-motion:reduce){#" + ROOT_ID + ">div{animation:none!important}",
			"#" + ROOT_ID + " .wf-scan{display:none}}",
		].join(NL);

		function build() {
			var el = document.createElement("div");
			el.id = ROOT_ID;
			el.setAttribute("aria-hidden", "true");
			el.innerHTML =
				'<div class="wf-aurora"></div><div class="wf-dust"></div>' +
				'<div class="wf-scan"></div><div class="wf-frame"></div>';
			return el;
		}

		function apply() {
			var existing = document.getElementById(ROOT_ID);
			if (existing) existing.parentNode.removeChild(existing);

			var style = document.createElement("style");
			style.id = STYLE_ID;
			style.textContent = CSS_TEXT;
			document.head.appendChild(style);

			var el = build();
			var root = document.documentElement;
			var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
			var raf = 0;
			var last = null;

			function syncSkin() {
				var on = root.dataset ? root.dataset.workbenchSkin === "whale-fantasy" : true;
				el.style.display = on ? "" : "none";
				if (!on) clearParallax();
			}

			function clearParallax() {
				if (raf) {
					cancelAnimationFrame(raf);
					raf = 0;
				}
				root.style.removeProperty("--wf-px");
				root.style.removeProperty("--wf-py");
			}

			// 视差：一次 rAF 内只算一帧，百分比取两位小数，避免每次 mousemove 都改样式。
			function onMove(e) {
				if (raf) return;
				last = e;
				raf = requestAnimationFrame(function () {
					raf = 0;
					var ev = last;
					last = null;
					if (!ev || !el.isConnected || el.style.display === "none") return;
					var w = window.innerWidth || 1;
					var h = window.innerHeight || 1;
					var px = Math.round(((ev.clientX / w) - 0.5) * 200) / 100;
					var py = Math.round(((ev.clientY / h) - 0.5) * 200) / 100;
					root.style.setProperty("--wf-px", String(Math.max(-1, Math.min(1, px))));
					root.style.setProperty("--wf-py", String(Math.max(-1, Math.min(1, py))));
				});
			}

			var observer =
				typeof MutationObserver === "function"
					? new MutationObserver(function () {
							syncSkin();
					  })
					: null;
			if (observer) observer.observe(root, { attributes: true, attributeFilter: ["data-workbench-skin"] });

			var timer = 0;
			function mount() {
				if (!document.body) return;
				document.body.appendChild(el);
				syncSkin();
				if (!reduce) window.addEventListener("mousemove", onMove, { passive: true });
			}
			if (document.body) mount();
			else timer = window.setTimeout(mount, 60);

			return function dispose() {
				if (timer) clearTimeout(timer);
				clearParallax();
				window.removeEventListener("mousemove", onMove);
				if (observer) observer.disconnect();
				if (el.parentNode) el.parentNode.removeChild(el);
				if (style.parentNode) style.parentNode.removeChild(style);
			};
		}

		exports.isPlugin = true;
		exports.inject = [];
		exports.apply = apply;
		return module.exports;
	},
});
