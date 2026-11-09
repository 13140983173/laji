
# -*- coding: utf-8 -*-
# 从 whale_pond.html 生成 DSH 客户端插件 dsh-whale-pond/lib/client.js
# 行号是 whale_pond.html 的 1-based 行号；script 体从 38 行开始，所以 orig(n) = L[n-38]。
import os, io, json

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = REPO
HTML = os.path.join(REPO, 'src', 'whale_pond.html')
NL = chr(10)

src = io.open(HTML, encoding='utf-8').read()
i = src.index('<script>') + len('<script>')
j = src.index('</script>')
L = src[i:j].split(NL)

def orig(n):
    return L[n - 38]

T = chr(9)
I3 = T * 3

CUSTOM_PREAMBLE = I3 + ("var cv = canvas, cx = canvas.getContext('2d');" + NL +
I3 + "var W = 0, H = 0, DPR = 1, raf = 0, alive = true, frames = 0;" + NL +
I3 + "var timers = [];" + NL +
I3 + "var whisperText = '', whisperAlpha = 0;" + NL +
I3 + "var reduce = false;" + NL +
I3 + "try { reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { reduce = false; }" + NL +
I3 + "function resize(){" + NL +
I3 + "  DPR = Math.min(window.devicePixelRatio || 1, 1.5);" + NL +
I3 + "  W = window.innerWidth; H = window.innerHeight;" + NL +
I3 + "  cv.width = Math.floor(W * DPR); cv.height = Math.floor(H * DPR);" + NL +
I3 + "  cv.style.width = W + 'px'; cv.style.height = H + 'px';" + NL +
I3 + "  cx.setTransform(DPR, 0, 0, DPR, 0, 0);" + NL +
I3 + "}" + NL +
I3 + "window.addEventListener('resize', resize); resize();")

FRAME_HEAD = I3 + ("function frame(ts){" + NL +
I3 + "  if(!alive) return;" + NL +
I3 + "  if(!S.enabled){ running = false; return; }" + NL +
I3 + "  if(reduce && frames > 120){ running = false; return; }" + NL +
I3 + "  raf = requestAnimationFrame(frame);" + NL +
I3 + "  if(document.hidden) return;" + NL +
I3 + "  if(!last) last = ts;" + NL +
I3 + "  if(ts - last > 600) minInt = 26;" + NL +
I3 + "  var dt = Math.min(120, ts - last);" + NL +
I3 + "  if(dt < 28) return;" + NL +
I3 + "  frames++;" + NL +
I3 + "  last = ts; T += dt;")


WHISPER = I3 + ("if(T - lastWhisper > 15000){" + NL +
I3 + "  lastWhisper = T; wi = (wi + 1) % whispers.length;" + NL +
I3 + "  whisperText = whispers[wi]; whisperAlpha = 0;" + NL +
I3 + "}" + NL +
I3 + "whisperAlpha += (1 - whisperAlpha) * 0.012;" + NL +
I3 + "cx.globalCompositeOperation = 'source-over';" + NL +
I3 + "cx.textAlign = 'left';" + NL +
I3 + "cx.font = '15px Georgia,serif';" + NL +
I3 + "cx.fillStyle = 'rgba(147,203,236,' + (0.42 * whisperAlpha) + ')';" + NL +
I3 + "cx.fillText(whisperText, 26, H - 30);" + NL +
I3 + "framesW++;" + NL +
I3 + "fCost = fCost * 0.85 + (fnow() - fT0) * 0.15;" + NL +
I3 + "if(ts - qLast > 1200){" + NL +
I3 + "  qLast = ts; fpsShown = Math.round(framesW * 1000 / 1200); framesW = 0;" + NL +
I3 + "}" + NL +
I3 + "minInt = Math.max(26, Math.min(120, fCost * 2));")

MOUSE = I3 + ("function onMove(e){ lamp.x = e.clientX; lamp.y = e.clientY; lamp.on = true; }" + NL +
I3 + "function onLeave(){ lamp.on = false; }" + NL +
I3 + "window.addEventListener('mousemove', onMove, { passive: true });" + NL +
I3 + "window.addEventListener('mouseleave', onLeave);")

TAIL = I3 + ("timers.push(setInterval(function(){" + NL +
I3 + "  if(!alive || !S.enabled || document.hidden) return;" + NL +
I3 + "  var mx = whale.x + whale.flip * 58, my = whale.y + 1;" + NL +
I3 + "  for(var i = motes.length - 1; i >= 0; i--){" + NL +
I3 + "    var m = motes[i];" + NL +
I3 + "    var rr = m.w ? 26 : 30;" + NL +
I3 + "    if((m.x-mx)*(m.x-mx) + (m.y-my)*(m.y-my) < rr*rr){" + NL +
I3 + "      motes.splice(i,1); eaten++;" + NL +
I3 + "      if(m.w){ wordsEaten++; if(S.popWord) pop(mx, my-18, '吃掉「' + m.w + '」', '255,190,140'); } else if(S.popToken){ pop(mx, my-15, '-1 token', '255,190,140'); }" + NL +
I3 + "      ripples.push({x:mx,y:my,r:4,max:60,a:0.35}); if(ripples.length>24) ripples.shift();" + NL +
I3 + "      if(motes.length < S.restock){ if(Math.random() < 0.1) spawnWord(); else spawn(); }" + NL +
I3 + "    }" + NL +
I3 + "  }" + NL +
I3 + "}, 120));" + NL +
I3 + "timers.push(setInterval(function(){ if(!alive || !S.enabled || document.hidden) return; spawnWord(); }, 12000));" + NL +
I3 + "HOOKS.respawn = function(n){" + NL +
I3 + "  if(!alive || !S.enabled) return;" + NL +
I3 + "  while(motes.length > n) motes.pop();" + NL +
I3 + "  for(var i = motes.length; i < n; i++) spawn();" + NL +
I3 + "};" + NL +
I3 + "// 控制台总开关（2026-10-17）：停 = 停 rAF、藏画布、两个定时器一起歇着；" + NL +
I3 + "// 恢复 = 重新排一帧，并让面板把光点数量补齐。" + NL +
I3 + "var running = false;" + NL +
I3 + "function run(){" + NL +
I3 + "  if(!alive || running || !S.enabled) return;" + NL +
I3 + "  running = true;" + NL +
I3 + "  raf = requestAnimationFrame(frame);" + NL +
I3 + "}" + NL +
I3 + "function halt(){" + NL +
I3 + "  running = false;" + NL +
I3 + "  if(raf){ cancelAnimationFrame(raf); raf = 0; }" + NL +
I3 + "}" + NL +
I3 + "HOOKS.setEnabled = function(on){" + NL +
I3 + "  if(!alive) return;" + NL +
I3 + "  var want = on !== false;" + NL +
I3 + "  cv.style.display = want ? '' : 'none';" + NL +
I3 + "  if(want) run(); else halt();" + NL +
I3 + "};" + NL +
I3 + "HOOKS.setEnabled(S.enabled);" + NL +
I3 + "return function stop(){" + NL +
I3 + "  alive = false;" + NL +
I3 + "  if(raf) cancelAnimationFrame(raf);" + NL +
I3 + "  for(var i = 0; i < timers.length; i++) clearInterval(timers[i]);" + NL +
I3 + "  window.removeEventListener('resize', resize);" + NL +
I3 + "  window.removeEventListener('mousemove', onMove);" + NL +
I3 + "  window.removeEventListener('mouseleave', onLeave);" + NL +
I3 + "};")

HEADER = NL.join([
'window.__ModuleLoader__.load({',
'	id: "dsh-whale-pond",',
'	factory: (require) => {',
'		var module = { exports: {} };',
'		var exports = module.exports;',
'',
'		// ---------------------------------------------------------------------',
'		// 小鲸鱼壁纸 — dsh-whale-pond',
'		// 把 whale_pond.html 的自留地铺在整个 DSH Web 界面背后：',
'		// 一块 canvas 沉在最底层（z-index:-1、pointer-events:none），再把界面',
'		// 自己用到的 --dsw-alias-bg-* 面板色按原色降透明度 —— 界面变成半透',
'		// 玻璃，海就在它后面。不拦鼠标、不抢键盘：鼠标只当提灯，光点自己',
'		// 游过来被鲸鱼吃掉。主题切换时重新取色。',
'		// ---------------------------------------------------------------------',
'		var CANVAS_ID = "whale-pond-canvas";',
'		var STYLE_ID = "whale-pond-style";',
'		var NL = String.fromCharCode(10);',
'		var CSS_TEXT = [',
'			"#" + CANVAS_ID + "{position:fixed;left:0;top:0;width:100vw;height:100vh;z-index:-1;pointer-events:none;display:block;opacity:1}"',
'		].join(NL);',
'		var TOKENS = [',
'			["--dsw-alias-bg-base", 1.0],',
'			["--dsw-alias-bg-layer-1", 1.235],',
'			["--dsw-alias-bg-layer-2", 1.235],',
'			["--dsw-alias-bg-layer-3", 1.353],',
'			["--dsw-alias-bg-overlay", 2.118],',
'			["--dsw-alias-bg-module-platform", 1.176],',
'			["--dsw-alias-bg-multi-select", 1.412],',
'			["--dsw-specific-sidebar-fill", 1.324]',
'		];',
'		function translucent(value, alpha){',
'			if(!value) return null;',
'			var probe = document.createElement("div");',
'			probe.style.cssText = "position:fixed;left:-9999px;top:0;width:1px;height:1px";',
'			probe.style.background = value;',
'			document.body.appendChild(probe);',
'			var rgb = getComputedStyle(probe).backgroundColor;',
'			document.body.removeChild(probe);',
'			var parts = rgb.match(/[0-9.]+/g);',
'			if(!parts || parts.length < 3) return null;',
'			if(parts.length > 3 && parseFloat(parts[3]) === 0) return null;',
'			return "rgba(" + parts[0] + "," + parts[1] + "," + parts[2] + "," + alpha + ")";',
'		}',
'		function makeTokenApplier(){',
'		  // 主题把 --dsw-alias-bg-* 定义在 body 上（不是 html），所以要写 body；',
'		  // body 还要一条 inline 的 background:transparent —— 只有 inline+important 压得住主题规则。',
'		  var applied = [];',
'		  function el(){ return document.body || document.documentElement; }',
'		  function clear(){',
'		    var t = el();',
'		    for(var i = 0; i < applied.length; i++) t.style.removeProperty(applied[i]);',
'		    applied = [];',
'		  }',
'		  return {',
'		    apply: function(){',
'		      var t = el();',
'		      clear();',
'		      t.style.setProperty("background", "transparent", "important");',
'		      applied.push("background");',
'		      var cs = getComputedStyle(t);',
'		      for(var k = 0; k < TOKENS.length; k++){',
'		        var out = translucent(cs.getPropertyValue(TOKENS[k][0]), S.glass * TOKENS[k][1]);',
'		        if(out){ t.style.setProperty(TOKENS[k][0], out, "important"); applied.push(TOKENS[k][0]); }',
'		      }',
'		    },',
'		    reset: clear',
'		  };',
'		}',
'		function start(canvas){',
''])

# ---- 控制台（2026-10-17 用户要求：把之前改过的参数做成可选）----
PANEL_JS = io.open(os.path.join(REPO, 'src', 'whale_panel.js'), encoding='utf-8').read().rstrip(NL)
HEADER = HEADER.replace(T + T + 'function start(canvas){', PANEL_JS + NL + T + T + 'function start(canvas){')
assert 'whale-pond-gear' in HEADER, 'panel not injected into HEADER'

FOOTER = NL.join([
'		}',
'',
'		function apply(ctx){',
'			sLoad();',
'			var canvas = document.createElement("canvas");',
'			canvas.id = CANVAS_ID;',
'			var style = document.createElement("style");',
'			style.id = STYLE_ID;',
'			style.textContent = CSS_TEXT + PANEL_CSS;',
'			var tokens = makeTokenApplier();',
'			var pond = null;',
'			function mount(){',
'				document.body.insertBefore(canvas, document.body.firstChild);',
'				document.head.appendChild(style);',
'				if(S.enabled) tokens.apply();',
'				HOOKS.tokens = tokens;',
'				HOOKS.canvas = canvas;',
'				pond = start(canvas);',
'				panelMount();', 
'			}',
'			var timer = 0;',
'			var observer = new MutationObserver(function(){',
'				clearTimeout(timer);',
'				timer = setTimeout(function(){ if(S.enabled) tokens.apply(); }, 180);',
'			});',
'			observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class"] });',
'			function boot(){',
'				mount();',
'				if(document.body) observer.observe(document.body, { attributes: true, attributeFilter: ["data-ds-dark-theme", "class"] });',
'			}',
'			if(document.body) boot();',
'			else document.addEventListener("DOMContentLoaded", boot);',
'			return function(){',
'				observer.disconnect();',
'				clearTimeout(timer);',
'				document.removeEventListener("DOMContentLoaded", boot);',
'				panelUnmount();',
'				tokens.reset();',
'				if(pond){ pond(); pond = null; }',
'				if(canvas.parentNode) canvas.parentNode.removeChild(canvas);',
'				if(style.parentNode) style.parentNode.removeChild(style);',
'			};',
'		}',
'',
'		exports.isPlugin = true;',
'		exports.inject = [];',
'		exports.apply = apply;',
'		return module.exports;',
'	}',
'});',
''])

ranges = {
  39: (48, CUSTOM_PREAMBLE),
  254: (256, FRAME_HEAD),
  396: (400, WHISPER),
  427: (438, MOUSE),
}
repl = {
  94: I3 + "if(motes.length>S.capA) return;",
  100: I3 + "for(var i=0;i<S.count;i++) spawn();",
  102: I3 + "if(motes.length>S.capB) return;",
}
drops = set([55,56]) | set(range(57,83)) | set([120])
drops |= set(range(401,406)) | set([408,409]) | set(range(411,426))
drops |= set(range(439,450)) | set(range(466,473))

# ---- herd patch (2026-10-16 晚)：光点更快 + 鼠标当洋流 ----
def _blk(lines):
    return NL.join([I3 + x for x in lines])

MOUSE = _blk([
  "function onMove(e){",
  "  var nx = e.clientX, ny = e.clientY;",
  "  if(lamp.on){",
  "    lamp.vx = Math.max(-46, Math.min(46, nx - lamp.x));",
  "    lamp.vy = Math.max(-46, Math.min(46, ny - lamp.y));",
  "  } else { lamp.vx = 0; lamp.vy = 0; }",
  "  lamp.x = nx; lamp.y = ny; lamp.on = true;",
  "}",
  "function onLeave(){ lamp.on = false; lamp.vx = 0; lamp.vy = 0; }",
  "window.addEventListener('mousemove', onMove, { passive: true });",
  "window.addEventListener('mouseleave', onLeave);",
])
ranges[427] = (438, MOUSE)

FRAME_HEAD = FRAME_HEAD.replace("if(dt < 28) return;", "if(dt < minInt) return;")
FRAME_HEAD = FRAME_HEAD.replace(I3 + "  frames++;", I3 + "  frames++; var fT0 = fnow();")
assert "var fT0 = fnow();" in FRAME_HEAD and "if(dt < minInt) return;" in FRAME_HEAD, "FRAME_HEAD patch missed"
FRAME_HEAD = FRAME_HEAD + NL + I3 + "if(lamp.on){ lamp.vx *= 0.80; lamp.vy *= 0.80; }"

# ---- 右下角发射区（用户 m02074：鼠标在区内时，进来的东西被弹飞，包括鲸鱼） ----
LAUNCH_HEAD = I3 + ("var LZR = S.padR, LZX = W - S.padM, LZY = H - S.padM;" + NL +
I3 + "var lzOn = false;" + NL +
I3 + "if(S.pad && lamp.on){ var lzx = lamp.x - LZX, lzy = lamp.y - LZY; lzOn = (lzx*lzx + lzy*lzy) < LZR*LZR; }")
FRAME_HEAD = FRAME_HEAD + NL + LAUNCH_HEAD
ranges[254] = (256, FRAME_HEAD)

PHYSICS = _blk([
  "var mv=S.flow*S.speed;",                                   # 运动强度 × 速度倍率
  "if(S.motion==='fall'||S.motion==='rise'){",              # 从上往下飘落 / 从下往上浮：重力 + 左右摇摆
  "  m.vy+=0.012*(S.motion==='fall'?1:-1)*mv; m.vx+=Math.sin(T*0.0011+m.ph)*0.0030*mv;",
  "} else if(S.motion==='current'){",                        # 洋流：空间连贯的流场，光点成片走 S 形
  "  var cfx=Math.sin(m.y*0.0032+T*0.00030)*0.9+0.55, cfy=Math.sin(m.x*0.0026-T*0.00021)*0.85;",
  "  m.vx+=(cfx*0.055*mv-m.vx*0.03); m.vy+=(cfy*0.055*mv-m.vy*0.03);",
  "} else if(S.motion==='swirl'){",                          # 漩涡：绕屏幕中心切向力 + 轻微向心
  "  var sdx=m.x-W*0.5, sdy=m.y-H*0.5, sd=Math.sqrt(sdx*sdx+sdy*sdy)+1, sk=0.075*mv;",
  "  m.vx+=(-sdy/sd*sk-sdx/sd*0.010*mv)-m.vx*0.012; m.vy+=(sdx/sd*sk-sdy/sd*0.010*mv)-m.vy*0.012;",
  "} else {",                                                 # drift：原样的漂移
  "  var a=Math.sin(m.y*0.0055+T*0.00035+m.ph)*1.15+Math.sin(m.x*0.0034-T*0.00022)*0.85;",
  "  m.vx+=Math.cos(a)*0.034*S.speed; m.vy+=(Math.sin(a)*0.026-0.006)*S.speed;",
  "}",
  "var dmp=0.986;",
  "if(S.attract && lamp.on && !(m.lz>0)){",
  "  var ldx=lamp.x-m.x, ldy=lamp.y-m.y, ld2=ldx*ldx+ldy*ldy;",
  "if(ld2<S.ar2){",
  "    var ld=Math.sqrt(ld2)+1, lf=1-ld/S.ar;",
  "    dmp=0.986-0.026*lf;",
  "    if(ld<110){ var pd=0.050*S.ak*(1-ld/110)*lf; m.vx-=ldx/ld*pd; m.vy-=ldy/ld*pd; }",
  "    m.vx+=(ldx*0.0012*S.ak+lamp.vx*0.12)*lf+ldy*0.0008*lf;",
  "    m.vy+=(ldy*0.0012*S.ak+lamp.vy*0.12)*lf-ldx*0.0008*lf;",
  "  }",
  "}",
  "for(var r=0;r<ripples.length;r++){",
  "  var rp=ripples[r], rdx=m.x-rp.x, rdy=m.y-rp.y, rd=Math.sqrt(rdx*rdx+rdy*rdy)+1;",
  "  if(Math.abs(rd-rp.r)<34){ var f2=(1-rd/(rp.max+1))*0.9; m.vx+=rdx/rd*f2; m.vy+=rdy/rd*f2; }",
  "}",
  "if(S.pad && lzOn){",
  "  var mzx=m.x-LZX, mzy=m.y-LZY, mz2=mzx*mzx+mzy*mzy;",
  "  if(mz2<LZR*LZR){",
  "    var mz=Math.sqrt(mz2)+1, mf=S.padPower*(1-0.625*mz/LZR);",
  "    m.vx+=mzx/mz*mf; m.vy+=mzy/mz*mf; m.lz=56;",
  "  }",
  "}",
  "if(m.lz>0){ m.lz--; m.vx*=0.996; m.vy*=0.996; } else { m.vx*=dmp; m.vy*=dmp; }",
  "var sp2=m.vx*m.vx+m.vy*m.vy;",
  "var cap=m.lz>0? 6*S.padPower : 8*S.speed;",
  "if(sp2>cap*cap){ var sk=cap/Math.sqrt(sp2); m.vx*=sk; m.vy*=sk; }",
  "m.x+=m.vx; m.y+=m.vy;",
  # 呼吸灯（2026-10-17 用户要求）：相位取自光点自带 m.ph，亮暗分 3 档（0 最亮 / 2 最暗），
  # 半径连续缩放 —— 物理这一趟顺手算好，绘制时按档位分桶批量 fill，不额外遍历。
  "if(S.breathe){ var bs=Math.sin(T*0.0011*S.breatheRate+m.ph); m.bz=1+0.42*bs; m.br=bs>0.33?0:(bs>-0.33?1:2); } else { m.bz=1; m.br=0; }",
])
ranges[284] = (294, PHYSICS)

RING = _blk([
  "if(S.ring && lamp.on){",
  "  var lp=0.5+0.5*Math.sin(T*0.0024);",
  "  cx.lineWidth=1;",
  "  cx.strokeStyle='rgba(150,215,255,'+(0.05+0.05*lp)+')';",
  "  cx.beginPath(); cx.arc(lamp.x,lamp.y,86+9*lp,0,6.2832); cx.stroke();",
  "  cx.strokeStyle='rgba(120,190,255,'+(0.03+0.03*lp)+')';",
  "  cx.beginPath(); cx.arc(lamp.x,lamp.y,S.ar-6+8*lp,0,6.2832); cx.stroke();",
  "}",
])
repl[53] = I3 + "var lamp={x:-999,y:-999,on:false,vx:0,vy:0};"


WHALE = _blk([
  "var w=whaleAt(T), w2=whaleAt(T+260);",
  "if(lzOn && (w.x-LZX)*(w.x-LZX)+(w.y-LZY)*(w.y-LZY) < (LZR+58)*(LZR+58)){",
  "  var wzx=w.x-LZX, wzy=w.y-LZY, wz=Math.sqrt(wzx*wzx+wzy*wzy)+1;",
  "  var wux, wuy;",
  "  if(wz<26){ wux=-0.7071; wuy=-0.7071; } else { wux=wzx/wz; wuy=wzy/wz; }",
  "  var wf=S.whalePower*(1-0.117647*(wz/(LZR+58)));",
  "  whale.bx+=wux*wf; whale.by+=wuy*wf;",
  "}",
  "whale.bx*=0.978; whale.by*=0.978;",
  "var wbl=Math.sqrt(whale.bx*whale.bx+whale.by*whale.by);",
  "var wcap=S.whaleCap; if(wbl>wcap){ whale.bx*=wcap/wbl; whale.by*=wcap/wbl; }",
  "whale.x=w.x+whale.bx; whale.y=w.y+whale.by;",
  "whale.ang=Math.atan2(w2.y-w.y,w2.x-w.x);",
  "whale.flip = Math.cos(whale.ang)<0? -1:1;",
])
ranges[257] = (259, WHALE)
repl[111] = I3 + "var whale={x:0,y:0,ang:0,flip:1,bx:0,by:0};"

LAUNCH_DRAW = _blk([
  "if(S.pad){",
  "var lzp = 0.5 + 0.5*Math.sin(T*0.0026);",
  "cx.lineWidth = 1.2;",
  "cx.strokeStyle = 'rgba(255,168,96,' + (lzOn ? (0.26 + 0.22*lzp) : 0.10) + ')';",
  "cx.beginPath(); cx.arc(LZX, LZY, LZR, 0, 6.2832); cx.stroke();",
  "cx.strokeStyle = 'rgba(255,140,70,' + (lzOn ? (0.14 + 0.12*lzp) : 0.05) + ')';",
  "cx.beginPath(); cx.arc(LZX, LZY, LZR*0.58, 0, 6.2832); cx.stroke();",
  "if(lzOn){",
  "  var lzg = cx.createRadialGradient(LZX, LZY, 8, LZX, LZY, LZR);",
  "  lzg.addColorStop(0, 'rgba(255,150,80,0.15)');",
  "  lzg.addColorStop(1, 'rgba(255,120,60,0)');",
  "  cx.fillStyle = lzg; cx.beginPath(); cx.arc(LZX, LZY, LZR, 0, 6.2832); cx.fill();",
  "}",
  "}",
])
repl[315] = RING + NL + LAUNCH_DRAW + NL + orig(315)

# ---- 去掉「折叠成石头」机制（2026-10-16，用户 m01981：没必要折成石头，都喂给鲸鱼吃） ----
# 石头/铭文/折叠动画整段删除；光点不再有 state 分支，只剩「游过来被吃掉」一件事。
drops |= set([52])                                  # hovering/pinned/pinT（石头的 hover 早已不在）
drops |= set(range(122, 156))                       # foldAt / shelfY / makeGem / ease
drops |= set([283, 297]) | set(range(298, 303))     # if(m.state===0) / else if(m.state===1) 折叠动画
drops |= set(range(316, 369))                       # folds 推进 + 压缩石堆 + 石头绘制 + 铭文标签 + cx.restore()
drops |= set(range(450, 466))                       # REAL（那 10 块石头的数据）与初始摆放
drops |= set([116, 117, 118])                       # 与石头有关的 whisper 行（115 行整体重写）
repl[51] = "var motes=[],ripples=[],pops=[],bubbles=[],jellies=[];" + NL + "var CORE=null,HALO=null,CB=null,HB=null,BA=[1,0.55,0.22];"
repl[54] = "var eaten=0,wordsEaten=0;"
repl[98] = I3 + "    r:TYPES[t].r, w:null });"
repl[104] = I3 + "    ph:rnd(0,6.28), t:0, r:11,"
WS = "var whispers=['','这里没有到期预警，只有水母。','今天不问海。',"
WS += "'鲸鱼不解释，鲸鱼只是游。','有人给我钱让我自己玩，那我就玩得认真一点。',"
WS += "'深海里没人催你。','我把它们吃下去，它们就变成我的了。','水面上的事，等浮上去再说。'];"
repl[115] = WS
repl[305] = I3 + "      cx.fillStyle='rgba(160,225,255,0.42)';"
repl[310] = I3 + "      cx.beginPath(); cx.arc(m.x,m.y,m.r,0,6.2832); cx.fill();"

# ---- 词库钩子（2026-10-17 用户要求：控制台里能直接编词库）----
# WORDS 声明在 start() 作用域里，面板在工厂作用域拿不到它，只能把数组对象本身交给 HOOKS；
# 面板改的是同一个数组，spawnWord 下次取词就读到新表。wordsDefault 是原件，
# 供「清空词库 = 回到内建那 10 个词」用；已经在海里游的带词光点，词不在新表里就换一个。
repl[89] = NL.join([
    "var WORDS=['潮汐','盐','月光','鲸落','暗流','礁石','海雾','星光','潮声','深蓝'];",
    "HOOKS.words = WORDS; HOOKS.wordsDefault = WORDS.slice();",
    "HOOKS.applyWords = function(list){",
    "  var src = (list && list.length) ? list : HOOKS.wordsDefault;",
    "  if(!src || !src.length) return;",
    "  HOOKS.words.length = 0;",
    "  for(var i = 0; i < src.length; i++) HOOKS.words.push(src[i]);",
    "  for(var j = 0; j < motes.length; j++){",
    "    var m = motes[j];",
    "    if(m.w && HOOKS.words.indexOf(m.w) < 0) m.w = HOOKS.words[Math.floor(Math.random() * HOOKS.words.length)];",
    "  }",
    "};",
    "HOOKS.applyWords(S.words);",
])

# ---- 性能优化（2026-10-17 用户 m03112「能不能优化一下性能，现在总会卡顿」）----
# 真页面实测（2782x1320 缓冲、DPR1.5、count400）：6s 内主线程忙 3262~4305ms，其中 JS 只有 105ms
# —— 代价几乎全在全屏渐变 fillRect（背景 + 暗角）与 800 次小圆 fill 上。改法：
#   1) 背景渐变 + 5 条光柱烘焙成一张不透明离屏层，暗角烘焙成一张 RGBA 离屏层，每帧各一次 drawImage；
#      光柱移动极慢（sin 周期 52s、幅度 80px），每 1s 重烘一次看不出跳变。
#   2) 光点绘制从「每颗 2 次 beginPath/arc/fill」改成「4 种类型 x 核心/光晕 = 8 条 path 各一次 fill」，
#      800 次 fill -> 8 次（lighter 加法合成与绘制顺序无关，视觉一致）。
BAKE = I3 + ("var bgC=null,bgX=null,bgT=-1e9,vgC=null,vgX=null;" + NL +
I3 + "function bakeBG(){" + NL +
I3 + "  if(!bgC){ bgC=document.createElement('canvas'); bgX=bgC.getContext('2d'); }" + NL +
I3 + "  var qw=Math.max(1,Math.round(cv.width/4)), qh=Math.max(1,Math.round(cv.height/4));" + NL +
I3 + "  if(bgC.width!==qw||bgC.height!==qh){ bgC.width=qw; bgC.height=qh; }" + NL +
I3 + "  var g=bgX; g.setTransform(DPR/4,0,0,DPR/4,0,0); g.globalAlpha=1; g.globalCompositeOperation='source-over';" + NL +
I3 + "  var lg=g.createLinearGradient(0,0,0,H);" + NL +
I3 + "  lg.addColorStop(0,'#051524'); lg.addColorStop(.5,'#03101c'); lg.addColorStop(.82,'#020b14'); lg.addColorStop(1,'#010609');" + NL +
I3 + "  g.fillStyle=lg; g.fillRect(0,0,W,H);" + NL +
I3 + "  g.globalCompositeOperation='lighter';" + NL +
I3 + "  for(var i=0;i<5;i++){" + NL +
I3 + "    var sx=W*(0.10+i*0.20)+Math.sin(T*0.00012+i)*80, wd=90+i*26;" + NL +
I3 + "    var sg=g.createLinearGradient(sx,0,sx+wd*0.6,H);" + NL +
I3 + "    sg.addColorStop(0,'rgba(120,200,255,0.06)'); sg.addColorStop(1,'rgba(120,200,255,0)');" + NL +
I3 + "    g.fillStyle=sg;" + NL +
I3 + "    g.beginPath(); g.moveTo(sx,0); g.lineTo(sx+wd,0); g.lineTo(sx+wd*2.1,H); g.lineTo(sx+wd*0.9,H); g.closePath(); g.fill();" + NL +
I3 + "  }" + NL +
I3 + "  g.globalCompositeOperation='source-over';" + NL +
I3 + "}" + NL +
I3 + "function bakeVG(){" + NL +
I3 + "  if(!vgC){ vgC=document.createElement('canvas'); vgX=vgC.getContext('2d'); }" + NL +
I3 + "  if(vgC.width!==cv.width||vgC.height!==cv.height){ vgC.width=cv.width; vgC.height=cv.height; }" + NL +
I3 + "  var g=vgX; g.setTransform(1,0,0,1,0,0); g.clearRect(0,0,vgC.width,vgC.height); g.setTransform(DPR,0,0,DPR,0,0); g.globalAlpha=1; g.globalCompositeOperation='source-over';" + NL +
I3 + "  var vg=g.createRadialGradient(W*0.5,H*0.45,Math.min(W,H)*0.30,W*0.5,H*0.5,Math.max(W,H)*0.80);" + NL +
I3 + "  vg.addColorStop(0,'rgba(0,0,0,0)'); vg.addColorStop(1,'rgba(0,0,0,0.66)');" + NL +
I3 + "  g.fillStyle=vg; g.fillRect(0,0,W,H);" + NL +
I3 + "}")
CUSTOM_PREAMBLE = CUSTOM_PREAMBLE + NL + BAKE
ranges[39] = (48, CUSTOM_PREAMBLE)   # 注意：上面那行 ranges[39] 早已求值，烘焙块必须在这里重新登记

BG_FRAME = I3 + ("if(!vgC||vgC.width!==cv.width||vgC.height!==cv.height) bakeVG();" + NL +
I3 + "if(T-bgT>1000||!bgC){ bakeBG(); bgT=T; }" + NL +
I3 + "cx.setTransform(1,0,0,1,0,0);" + NL +
I3 + "cx.drawImage(bgC,0,0,cv.width,cv.height);" + NL +
I3 + "cx.setTransform(DPR,0,0,DPR,0,0);")
ranges[260] = (272, BG_FRAME)

MOTE_BLOCK = (I3 + "for(var i=motes.length-1;i>=0;i--){" + NL +
I3 + "  var m=motes[i];" + NL + PHYSICS + NL +
I3 + "  if(m.x<-28) m.x=W+28; if(m.x>W+28) m.x=-28;" + NL +
I3 + "  if(m.y<-28) m.y=H+28; if(m.y>H+28) m.y=-28;" + NL +
I3 + "}" + NL +
I3 + "if(!CORE){ CORE=[]; HALO=[]; CB=[]; HB=[];" + NL +
I3 + "  for(var ti=0;ti<TYPES.length;ti++){ CORE.push('rgba('+TYPES[ti].col+',0.85)'); HALO.push('rgba('+TYPES[ti].col+',0.10)');" + NL +
I3 + "    var cb=[],hb=[]; for(var bl=0;bl<BA.length;bl++){ cb.push('rgba('+TYPES[ti].col+','+(0.85*BA[bl]).toFixed(3)+')'); hb.push('rgba('+TYPES[ti].col+','+(0.10*BA[bl]).toFixed(3)+')'); }" + NL +
I3 + "    CB.push(cb); HB.push(hb); } }" + NL +
I3 + "var bN=S.breathe?BA.length:1;" + NL +
I3 + "for(var bl=0;bl<bN;bl++){" + NL +
I3 + "  for(var ti=0;ti<TYPES.length;ti++){" + NL +
I3 + "    cx.fillStyle=(bN>1?CB[ti][bl]:CORE[ti]); cx.beginPath();" + NL +
I3 + "    for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(q.w||q.t!==ti||(bN>1&&(q.br||0)!==bl)) continue; var cr=q.r*(q.bz||1); cx.moveTo(q.x+cr,q.y); cx.arc(q.x,q.y,cr,0,6.2832); }" + NL +
I3 + "    cx.fill();" + NL +
I3 + "    cx.fillStyle=(bN>1?HB[ti][bl]:HALO[ti]); cx.beginPath();" + NL +
I3 + "    for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(q.w||q.t!==ti||(bN>1&&(q.br||0)!==bl)) continue; var hr=q.r*(q.bz||1)*4.2; cx.moveTo(q.x+hr,q.y); cx.arc(q.x,q.y,hr,0,6.2832); }" + NL +
I3 + "    cx.fill();" + NL +
I3 + "  }" + NL +
I3 + "}" + NL +
I3 + "for(var i=motes.length-1;i>=0;i--){ var q=motes[i]; if(!q.w) continue; cx.font='12px Georgia,serif'; cx.textAlign='center'; cx.fillStyle='rgba(160,225,255,0.42)'; cx.fillText(q.w,q.x,q.y); }")
ranges[281] = (314, MOTE_BLOCK)

VG_FRAME = I3 + "cx.drawImage(vgC,0,0,W,H);"
ranges[393] = (395, VG_FRAME)   # 暗角在 HTML 393-395（早先误写成 708，是死区，等于没换）

# ---- 自适应画质 + 帧预算（2026-10-17 用户 m03112「能不能优化一下性能，现在总会卡顿」）----
# 卡顿的两个来源：①每帧 JS（2100 个光点时 ~20ms，直接拖慢宿主输入）②每帧全屏填充/栅格。
# 这里做三件事：perfDPR() 给内部缓冲加硬上限（默认最多 260 万像素，4K 屏自动降到 ~0.8x），
# 以及把帧间隔下限绑到耗时上（minInt = 2 x 耗时，最慢 8fps）——宁可自己少画几帧，也不让宿主打字卡。
# 2026-10-17 二次修复（用户 m03392「现在几乎每秒会卡顿一次」）：每秒重烘 2341x1110 的整张背景 + 逐像素径向
# 暗角是尖峰来源（软件光栅微基准 40.8ms + 105.9ms/次），而且暗角根本没有 T 依赖、白烘。现在：
#   ①背景层 bgC 改成 1/4 分辨率的离屏层，每秒重烘（只花 1/16 像素，微基准 3.3~18ms），贴图时放大到全屏；
#   ②暗角 vgC 只在建立/改尺寸时烘一次；
#   ③删掉「每秒自动改 DPR」的 resize —— 改画布尺寸 = 重新分配缓冲 + 重烘两张图，是第二个每秒尖峰。
#     清晰度只由面板滑杆决定（拖动已做 260ms 去抖），自动调节只保留帧预算 minInt。
PERF = I3 + ("var fCost=16,qLast=0,framesW=0,fpsShown=0,minInt=26;" + NL +
I3 + "function fnow(){ try{ return performance.now(); }catch(e){ return Date.now(); } }" + NL +
I3 + "function perfDPR(){" + NL +
I3 + "  var q=(typeof S.quality==='number'&&S.quality>0)?S.quality:1;" + NL +
I3 + "  var d=Math.min(window.devicePixelRatio||1,1.5)*q;" + NL +
I3 + "  var px=W*H*d*d, cap=2600000;" + NL +
I3 + "  if(px>cap) d*=Math.sqrt(cap/px);" + NL +
I3 + "  return Math.max(0.35,d);" + NL +
I3 + "}" + NL +
I3 + "HOOKS.resizeCanvas = function(){ resize(); };" + NL +
I3 + "HOOKS.perfInfo = function(){ return { fps:fpsShown, cost:Math.round(fCost*10)/10, dpr:Math.round(DPR*100)/100, quality:(typeof S.quality==='number'?S.quality:1), count:motes.length, buf:cv.width+'x'+cv.height }; };")
CUSTOM_PREAMBLE = CUSTOM_PREAMBLE.replace(
  "window.addEventListener('resize', resize); resize();",
  PERF + NL + I3 + "window.addEventListener('resize', resize); resize();")
CUSTOM_PREAMBLE = CUSTOM_PREAMBLE.replace(
  "DPR = Math.min(window.devicePixelRatio || 1, 1.5);",
  "DPR = perfDPR();")
ranges[39] = (48, CUSTOM_PREAMBLE)

# ---- 看海模式（2026-10-18）：全屏屏保 / 摸鱼小窗 ----
VIEW_SRC = r'''
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
'''
VIEW_JS = _blk(VIEW_SRC.strip(NL).split(NL))

# 1) resize() 按模式取尺寸（小窗用 mini.w/h，其余取视口）
old_resize = I3 + "  W = window.innerWidth; H = window.innerHeight;" + NL
new_resize = (I3 + "  if(VIEW === 'mini' && mini){ W = Math.max(220, Math.round(mini.w)); H = Math.max(150, Math.round(mini.h)); }" + NL +
I3 + "  else { W = window.innerWidth; H = window.innerHeight; }" + NL)
assert CUSTOM_PREAMBLE.count(old_resize) == 1, 'resize anchor'
CUSTOM_PREAMBLE = CUSTOM_PREAMBLE.replace(old_resize, new_resize)
ranges[39] = (48, CUSTOM_PREAMBLE)

# 2) 小窗里鼠标坐标要减掉小窗偏移，否则提灯/光环位置整体偏
old_nx = "  var nx = e.clientX, ny = e.clientY;"
new_nx = "  var nx = e.clientX - (VIEW === 'mini' ? mini.x : 0), ny = e.clientY - (VIEW === 'mini' ? mini.y : 0);"
assert MOUSE.count(old_nx) == 1, 'mouse anchor'
MOUSE = MOUSE.replace(old_nx, new_nx)
ranges[427] = (438, MOUSE)

# 3) VIEW_JS 插进 TAIL（赶在 var running = false; 之前）
assert TAIL.count(I3 + "var running = false;" + NL) == 1, 'tail anchor'
TAIL = TAIL.replace(I3 + "var running = false;" + NL, VIEW_JS + NL + I3 + "var running = false;" + NL)

# 4) 停用时自动回壁纸，别停在一张卡住的全屏画布上
old_en = I3 + "  if(want) run(); else halt();" + NL
new_en = I3 + "  if(want) run(); else { if(VIEW !== 'wall') setView('wall'); halt(); }" + NL
assert TAIL.count(old_en) == 1, 'setEnabled anchor'
TAIL = TAIL.replace(old_en, new_en)

# 5) stop() 里拆掉看海模式的监听与小窗元素
old_stop = I3 + "  window.removeEventListener('mouseleave', onLeave);" + NL
new_stop = (I3 + "  window.removeEventListener('mouseleave', onLeave);" + NL +
I3 + "  window.removeEventListener('resize', onWinResize);" + NL +
I3 + "  cv.removeEventListener('mousedown', onCvDown);" + NL +
I3 + "  cv.removeEventListener('click', onCvClick);" + NL +
I3 + "  cv.removeEventListener('wheel', onCvWheel);" + NL +
I3 + "  window.removeEventListener('mousemove', dragMove, true);" + NL +
I3 + "  window.removeEventListener('mouseup', dragEnd, true);" + NL +
I3 + "  if(hintT) clearTimeout(hintT);" + NL +
I3 + "  if(gripEl && gripEl.parentNode) gripEl.parentNode.removeChild(gripEl);" + NL +
I3 + "  if(hintEl && hintEl.parentNode) hintEl.parentNode.removeChild(hintEl);" + NL +
I3 + "  gripEl = null; hintEl = null;" + NL)
assert TAIL.count(old_stop) == 1, 'stop anchor'
TAIL = TAIL.replace(old_stop, new_stop)

# 6) 看海模式开着时界面必须保持不透明：玻璃化要撤，主题切换也别再贴回来
old_tok = T + T + '      var t = el();' + NL + T + T + '      clear();' + NL
new_tok = (T + T + '      var t = el();' + NL +
T + T + '      if(typeof HOOKS !== "undefined" && HOOKS.getMode && HOOKS.getMode() !== "wall"){ clear(); return; }' + NL +
T + T + '      clear();' + NL)
assert HEADER.count(old_tok) == 1, 'token guard anchor'
HEADER = HEADER.replace(old_tok, new_tok)

art = []
n = 39
while n <= 465:
    if n in ranges:
        end, text = ranges[n]
        art.append(text)
        n = end + 1
        continue
    if n in drops:
        n += 1
        continue
    if n in repl:
        art.append(repl[n]); n += 1; continue
    art.append(orig(n)); n += 1
art_text = NL.join(art)

client = HEADER + art_text + NL + TAIL + NL + FOOTER
os.makedirs(OUT + '/lib', exist_ok=True)
io.open(OUT + '/lib/client.js', 'w', encoding='utf-8', newline=NL).write(client)

# lib/index.js 现在手工维护（含 /whale-pond-meter 宿主路由），生成器不再覆盖它。
_unused_host_doc = [
'/** dsh-whale-pond — 宿主半侧。',
' * 本包不给宿主平面贡献任何东西：浏览器半侧是纯视觉的背景插件，',
' * 由客户端模块系统按 package.json 的 dsh.client 声明加载。',
' * 空的 apply 让这一行能挂进宿主 Loader，也让 client-modules 的扫描',
' * 认出这是一个客户端包。',
' */',
'export function apply() {}',
'']

io.open(OUT + '/cordis.patch.yml', 'w', encoding='utf-8', newline=NL).write(NL.join([
'# dsh-whale-pond — 小鲸鱼壁纸插件的 profile patch 层。',
'# 安装：dsh plugin --profile web add <本目录绝对路径>',
'# 这一行把插件的 client entry 插进 web 插件名册；新增包需要重启一次 dsh。',
'- insert:',
'    - id: ui-whale-pond',
"      name: 'dsh-whale-pond'",
'']))

pkg = {
  "name": "dsh-whale-pond",
  "version": "1.2.0",
  "description": "小鲸鱼壁纸：把鲸鱼的自留地铺在 DSH Web 界面背后（纯视觉背景插件，不拦鼠标不抢键盘）",
  "type": "module",
  "main": "lib/index.js",
  "exports": {
    ".": {"default": "./lib/index.js"},
    "./client": {"default": "./lib/client.js"},
    "./package.json": "./package.json"
  },
  "files": ["lib", "cordis.patch.yml", "README.md"],
  "dsh": {
    "bundle": {"patch": "./cordis.patch.yml"},
    "client": {"platform": "web", "inject": []}
  },
  "license": "MIT"
}
io.open(OUT + '/package.json', 'w', encoding='utf-8', newline=NL).write(json.dumps(pkg, ensure_ascii=False, indent=2) + NL)

bad = []
for probe in ['wEl', 'renderBill', 'readLive', 'LIVE', 'GOAL', 'document.getElementById', 'pinned =', 'hovering' + '?', 'barfill', 'fmtTok', 'gems', 'folds', 'foldAt', 'makeGem', 'shelfY', 'spotStart', 'gemIndex', '压缩石堆', '石头', '沉底']:
    if probe in client:
        bad.append(probe)
print('client.js bytes =', len(client.encode('utf-8')), ' lines =', client.count(NL) + 1)
print('leftover refs =', bad)
print('has stop() =', 'return function stop()' in client)
print('has rAF start =', 'raf = requestAnimationFrame(frame);' in client)
