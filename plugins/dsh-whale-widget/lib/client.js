// dsh-whale-widget 的 Laji 客户端包装器。
//
// 上游 `vendor/assets/whale-widget.js` 是一段普通 IIFE（不是模块加载器的模块），
// 而且所有数据/资源都写成相对路径 `/dsh-whale/...`。这里做两件事把它们接上：
//
//   1. 把 `/dsh-whale/*` 改写成 `laji-plugin://<id>/__proxy/dsh-whale/*` —— 主进程
//      的插件协议会把 `__proxy/` 转给本插件的本地 host（见 lib/host.mjs）。
//      renderer 直连回环 http 会被 CSP 与上游的跨站栅栏同时挡掉。
//   2. 建 script 标签加载上游 bundle，并在卸载时把改写的全局全部还原。
//
// 为什么要等一会儿再注入：宿主冷启动时插件服务要晚几百毫秒到几秒才监听端口，
// 而上游 bundle 在注入那一刻就会 fetch `/dsh-whale/size.json`，失败一次就弹
// 「设置读取失败，已暂停保存」并永久停掉保存；角色图同样只在启动时加载一次，
// 失败就一直是空框（刷新才能恢复）。这里先等到服务可达再注入，把冷启动竞态消掉。
//
// 改写面只有三处：`fetch`、媒体/图片的 `src`（含 `setAttribute("src")`）。
// 上游拿音频走 WebAudio 的 `fetch`，拿图片走 `img.src`，都在这里覆盖到。

window.__ModuleLoader__.load({
	id: "dsh-whale-widget",
	factory: function () {
		var BASE = new URL("../", import.meta.url).href; // laji-plugin://<id>/
		var PROXY_BASE = new URL("__proxy/", BASE).href; // laji-plugin://<id>/__proxy/
		var WIDGET_SRC = new URL("vendor/assets/whale-widget.js", BASE).href;
		var ROUTE_PREFIX = "/dsh-whale/";
		/** 探活路由：服务端返回固定小 JSON，是 host 监听成功的最早信号。 */
		var READY_URL = new URL("__proxy/dsh-whale/size.json", BASE).href;
		var READY_TIMEOUT_MS = 25000;
		var READY_INTERVAL_MS = 250;

		/** `/dsh-whale/x` → `laji-plugin://<id>/__proxy/dsh-whale/x`；别的 URL 原样返回。 */
		function rewrite(url) {
			if (typeof url !== "string") return url;
			if (url.indexOf(ROUTE_PREFIX) !== 0) return url;
			return PROXY_BASE + url.slice(1);
		}

		var restores = [];
		var scriptEl = null;
		/**
		 * 当前“代”号。每次 apply 自增；旧一代的异步回调看到自己不是最新一代就直接放弃。
		 * 没有它，热重载时上一代的 `whenHostReady().then` 仍会在清场之后把 script 再插一次。
		 */
		var generation = 0;

		function runRestores() {
			for (var i = restores.length - 1; i >= 0; i--) {
				try {
					restores[i]();
				} catch (err) {
					/* 单个还原失败不影响其它 */
				}
			}
			restores.length = 0;
		}

		/**
		 * 摘掉上游建立的 DOM、样式与一次性闸门。apply 与 dispose 共用：
		 * 上游只认 `window.__dshWhaleWidget`，而这里必须删它才能重新启用 ——
		 * 所以“先删闸门再注入”之前，必须先把上一份实例的节点真删掉，
		 * 否则页面上会同时存在两个角色（上游 bundle 被注入两次 = 两套 DOM）。
		 */
		function clearDom() {
			if (scriptEl && scriptEl.parentNode) scriptEl.parentNode.removeChild(scriptEl);
			scriptEl = null;
			var roots = document.querySelectorAll(".dshwv-root");
			for (var j = 0; j < roots.length; j++) {
				if (roots[j].parentNode) roots[j].parentNode.removeChild(roots[j]);
			}
			var styles = document.querySelectorAll("style");
			for (var k = 0; k < styles.length; k++) {
				if ((styles[k].textContent || "").indexOf("dshwv-root") >= 0 && styles[k].parentNode) {
					styles[k].parentNode.removeChild(styles[k]);
				}
			}
			delete window.__dshWhaleWidget;
			delete window.__dshWhaleInit;
		}

		function patchFetch() {
			var original = window.fetch;
			if (typeof original !== "function") return;
			window.fetch = function (input, init) {
				if (typeof input === "string") {
					input = rewrite(input);
				} else if (input && typeof input === "object" && typeof input.url === "string") {
					var next = rewrite(input.url);
					if (next !== input.url) input = new Request(next, input);
				}
				return original.call(this, input, init);
			};
			restores.push(function () {
				window.fetch = original;
			});
		}

		/** 覆盖某个原型的 `src` 访问器，写入时改写。 */
		function patchSrc(proto) {
			if (!proto) return;
			var desc = Object.getOwnPropertyDescriptor(proto, "src");
			if (!desc || typeof desc.set !== "function") return;
			var next = Object.assign({}, desc, {
				set: function (value) {
					return desc.set.call(this, rewrite(value));
				},
			});
			Object.defineProperty(proto, "src", next);
			restores.push(function () {
				Object.defineProperty(proto, "src", desc);
			});
		}

		function patchSetAttribute() {
			var proto = window.Element && Element.prototype;
			if (!proto || typeof proto.setAttribute !== "function") return;
			var original = proto.setAttribute;
			proto.setAttribute = function (name, value) {
				if (
					typeof name === "string" &&
					name.toLowerCase() === "src" &&
					(window.HTMLImageElement && this instanceof HTMLImageElement ||
						window.HTMLMediaElement && this instanceof HTMLMediaElement)
				) {
					value = rewrite(value);
				}
				return original.call(this, name, value);
			};
			restores.push(function () {
				proto.setAttribute = original;
			});
		}

		/** 等插件服务可达（含超时），返回是否就绪。 */
		function whenHostReady(isCancelled) {
			var deadline = Date.now() + READY_TIMEOUT_MS;
			return new Promise(function (resolve) {
				function tick() {
					if (isCancelled()) return resolve(false);
					window
						.fetch(READY_URL, { cache: "no-store" })
						.then(function (r) {
							return r.ok;
						})
						.catch(function () {
							return false;
						})
						.then(function (ok) {
							if (ok || isCancelled()) return resolve(ok);
							if (Date.now() > deadline) return resolve(false);
							setTimeout(tick, READY_INTERVAL_MS);
						});
				}
				tick();
			});
		}

		function apply() {
			// 整个页面存活期只注入一次上游 bundle。
			// 标记放在 window 上而不是模块变量：宿主会重新求值 client.js（热重载），
			// 模块内变量跟着丢，window 上的不会。
			// 也不能用 `.dshwv-root` / `__dshWhaleWidget` 当判据 —— 上游是 1.1 MB 普通
			// script，append 之后要下载解析才执行，这期间两者都不存在；宿主连续挂载时
			// 每次都会判成“还没有”而各插一份，页面上叠出两个、三个角色。
			// ⚠️ 这段必须在 generation 推进**之前**：被跳过的调用一旦推进 generation，
			// 第一代的异步注入回调就会判自己过期，结果一个实例都起不来。
			if (window.__dshWhaleWidgetMounted) {
				console.info("[dsh-whale-widget] 已有挂件实例，跳过重复注入");
				return function dispose() {
					// 复用态不拥有清理权；上游的 dshwRootGuard 会把被摘掉的 DOM 挂回，
					// 重建只会在下次 apply 里叠出第二份，所以这里什么都不做。
				};
			}
			window.__dshWhaleWidgetMounted = true;

			generation += 1;
			var mine = generation;

			// 首次注入：清掉可能残留的 DOM，再删一次性闸门（否则上游会直接 return）。
			runRestores();
			clearDom();

			patchFetch();
			patchSrc(window.HTMLImageElement && HTMLImageElement.prototype);
			patchSrc(window.HTMLMediaElement && HTMLMediaElement.prototype);
			patchSetAttribute();

			var cancelled = false;
			var injected = false;
			whenHostReady(function () {
				return cancelled || mine !== generation;
			}).then(function (ready) {
				if (cancelled || mine !== generation) return;
				console.info(
					"[dsh-whale-widget] 本机服务" + (ready ? "已就绪" : "超时未响应") + "，注入上游 bundle",
				);
				injected = true;
				scriptEl = document.createElement("script");
				scriptEl.src = WIDGET_SRC;
				scriptEl.dataset.dshWhaleWidget = "1";
				scriptEl.onerror = function () {
					console.error("[dsh-whale-widget] 上游 bundle 加载失败:", WIDGET_SRC);
				};
				document.head.appendChild(scriptEl);
			});

			return function dispose() {
				if (mine !== generation) return; // 已被更新的一代接管，别替它收场
				generation += 1;
				cancelled = true;
				if (injected) return; // 已注入：保持单实例，不动 DOM（摘了也会被上游守护挂回）
				// 还没注入就被取消：释放单例标记，下次挂载还能正常起
				window.__dshWhaleWidgetMounted = false;
				runRestores();
				clearDom();
			};
		}

		return { apply: apply };
	},
});
