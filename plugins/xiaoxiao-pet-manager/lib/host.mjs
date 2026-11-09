// 桌宠管家 —— 本机服务（浏览器半的唯一后端）。
//
// 与 dsh-notify / dsh-whale-widget 同约定：
//   • 只绑回环，端口由内核分配（listen 0），写进插件安装目录的 runtime.json
//     （{ port, pid }），主进程的插件协议据此把 laji-plugin://<id>/__proxy/*
//     转到这里；
//   • 装了才起（contributions.apps），禁用/卸载即停，单实例按 runtime.json 的
//     pid 判断（残留且 pid 已死就接管重写）。
//
// 全部状态读写都走 lib/core.mjs；本文件只做 HTTP 包装与请求卫生。

import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createServer, get } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import {
  applyConfigOp,
  buildCatalogState,
  findPetHome,
  insideRoot,
  LAJI_PET_HOME,
  mergeDeep,
  packCharacterRoots,
  planSettingsPatch,
  readPetConfig,
  readSlot0,
  SLOT_KEYS,
  splitPerPetState,
  writeJsonAtomic,
  writeMainSlotCharacter,
} from "./core.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
/** 插件安装根（runtime.json 必须落在这里，协议代理按它找端口）。 */
const PLUGIN_DIR = dirname(HERE);
const RUNTIME_FILE = join(PLUGIN_DIR, "runtime.json");
/** 打开配置目录用；Windows 专属一条，其它平台给 file:// 提示也不做。 */
const IS_WINDOWS = process.platform === "win32";

const MIME = {
  ".webp": "image/webp",
  ".png": "image/png",
  ".webm": "video/webm",
  ".json": "application/json; charset=utf-8",
};

function log(...args) {
  console.log("[xiaoxiao-pet-manager]", ...args);
}

// ---------------------------------------------------------------- 单实例

/**
 * runtime.json 里记的实例还在不在。
 *
 * 只判 pid 活不活会误判：Windows 会很快复用 pid，重启宿主后那个号很可能
 * 已经属于一个无关进程，新实例就会以为「已有实例在跑」直接退出，于是
 * runtime.json 永远指着死端口、面板整块连不上（2026-11-08 真踩过）。
 * 所以 pid 活着还要再敲一下它记的端口，确实是我们这套接口才算数。
 */
function probeRunning(port) {
  if (!Number.isInteger(port) || port <= 0) return Promise.resolve(false);
  return new Promise((resolve) => {
    const req = get({ host: "127.0.0.1", port, path: "/api/state", timeout: 600 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200);
    });
    req.on("timeout", () => { req.destroy(); resolve(false); });
    req.on("error", () => resolve(false));
  });
}

async function anotherInstance() {
  let parsed;
  try {
    parsed = JSON.parse(readFileSync(RUNTIME_FILE, "utf8"));
  } catch {
    return { alive: false }; // 没有 / 坏了
  }
  const pid = Number(parsed.pid);
  const port = Number(parsed.port);
  if (!Number.isInteger(pid) || pid <= 0 || pid === process.pid) return { alive: false };
  try {
    process.kill(pid, 0);
  } catch {
    return { alive: false }; // 残留文件，接管
  }
  return (await probeRunning(port)) ? { alive: true, port } : { alive: false };
}

const previous = await anotherInstance();
if (previous.alive) {
  log("已有实例在跑（port", previous.port, "），退出");
  process.exit(0);
}

// ---------------------------------------------------------------- 桌宠家

/** 每次请求时重定位（用户可能中途删/换变体目录），带 3s 缓存挡抖。 */
let homeCache = { home: null, at: 0 };
function petHome() {
  const now = Date.now();
  if (homeCache.home !== null && now - homeCache.at < 3000) return homeCache.home;
  const appData = process.env.APPDATA || null;
  const home = findPetHome(appData);
  homeCache = { home, at: now };
  return home;
}

function pluginsRoot() {
  // 兄弟插件包扫描根，两种安装形态：
  //   bundled 源码 packs/plugins/<dir>            → 上一级是 packs/plugins（有 dsh-pet）
  //   安装快照 <lajiRoot>/plugins/<pluginId>/<ver> → 上两级才是 plugins（有 com.nerve.dsh-pet）
  // 都不匹配就放弃（面板只剩本机角色）。
  const up1 = dirname(PLUGIN_DIR);
  const up2 = dirname(up1);
  if (existsSync(join(up1, "dsh-pet")) || existsSync(join(up1, "com.nerve.dsh-pet"))) return up1;
  if (existsSync(join(up2, "dsh-pet")) || existsSync(join(up2, "com.nerve.dsh-pet"))) return up2;
  return PLUGIN_DIR;
}

function sendJson(res, code, value) {
  const body = JSON.stringify(value);
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
  });
  res.end(body);
}

function sendError(res, code, message) {
  sendJson(res, code, { ok: false, error: message });
}

/** 相邻的 dsh-pet 安装快照自带 imageio-ffmpeg；找不到再退回 PATH。 */
function ffmpegBin() {
  const root = pluginsRoot();
  const found = [];
  for (const pack of ["com.nerve.dsh-pet", "dsh-pet"]) {
    const base = join(root, pack);
    let versions = [];
    try {
      versions = readdirSync(base, { withFileTypes: true })
        .filter((e) => e.isDirectory())
        .map((e) => e.name)
        .sort()
        .reverse();
    } catch {
      continue;
    }
    for (const ver of versions) {
      for (const variant of ["bin/laji-pet", "bin-next/laji-pet"]) {
        const dir = join(base, ver, variant, "_internal", "imageio_ffmpeg", "binaries");
        try {
          for (const name of readdirSync(dir)) {
            if (/^ffmpeg.*\.exe$/i.test(name)) found.push(join(dir, name));
          }
        } catch {
          /* 变体目录不存在 */
        }
      }
    }
  }
  return found[0] ?? (IS_WINDOWS ? "ffmpeg.exe" : "ffmpeg");
}

/**
 * 只有 videos/*.webm 的角色没有静态帧：抽一帧抠成透明 PNG，按文件指纹缓存在
 * 桌宠家，避免每次开面板都起一次 ffmpeg。
 *
 * 两个坑（都实测过）：
 * 1. 解码必须显式点名 libvpx-vp9 —— ffmpeg 原生 vp9 解码器会**静默丢弃** VP9
 *    的 alpha 位流（webm 里的 BlockAdditions），透明素材抽出来是黑底方块。
 * 2. 不能直接把 chromakey 串在 -vf 上：chromakey 只认颜色，会把输入自带的
 *    alpha 重置成「非绿即不透明」。所以拆两路 —— 原 alpha 走 alphaextract，
 *    绿幕走 chromakey，最后 alphamerge 相乘：绿幕包（aboutme）靠 key 出透明，
 *    已经是透明 webm 的包靠原 alpha 出透明，一套命令通吃。
 */
function thumbFor(file, home) {
  const st = statSync(file);
  const key = createHash("sha1")
    .update(file + "|" + st.size + "|" + Math.round(st.mtimeMs))
    .digest("hex")
    .slice(0, 16);
  const cacheDir = join(home, ".xxpm-thumbs");
  const out = join(cacheDir, key + ".png");
  if (existsSync(out)) return out;
  mkdirSync(cacheDir, { recursive: true });
  const env = { ...process.env };
  delete env.NODE_OPTIONS; // 宿主注入的 shim 会干扰子进程
  const r = spawnSync(
    ffmpegBin(),
    [
      "-hide_banner", "-loglevel", "error", "-ss", "0.6",
      "-c:v", "libvpx-vp9", "-i", file,
      "-frames:v", "1",
      "-filter_complex",
      "[0:v]split[a][b];[a]alphaextract[al];" +
        "[b]chromakey=0x3AB93A:0.12:0.02,format=yuv420p[ck];[ck][al]alphamerge",
      "-pix_fmt", "rgba",
      "-y", out,
    ],
    { windowsHide: true, timeout: 20000, env },
  );
  if (r.status !== 0 || !existsSync(out)) {
    log("抽帧失败", file, r.error?.message ?? r.status, String(r.stderr ?? "").slice(0, 200));
    return null;
  }
  return out;
}

async function readBody(req, limit = 64 * 1024) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > limit) throw new Error("body too large");
    chunks.push(chunk);
  }
  const text = Buffer.concat(chunks).toString("utf8").trim();
  return text ? JSON.parse(text) : {};
}

/** 桌宠进程在跑吗：主进程 exe 叫 laji-pet（PyInstaller onedir / 源码 pythonw -m pet）。 */
const petRunningCache = { value: false, at: 0 };
function petRunning() {
  const now = Date.now();
  if (now - petRunningCache.at < 10_000) return petRunningCache.value;
  petRunningCache.at = now;
  petRunningCache.value = false;
  if (!IS_WINDOWS) return petRunningCache.value;
  try {
    // windowsHide 铁律：绝不让黑框闪出来。spawnSync 才拿得到同步 stdout。
    const out = spawnSync("tasklist", ["/FI", "IMAGENAME eq laji-pet.exe", "/FO", "CSV", "/NH"], {
      windowsHide: true,
      timeout: 8000,
      encoding: "utf8",
    });
    petRunningCache.value = /laji-pet\.exe/i.test(String(out.stdout ?? ""));
  } catch {
    petRunningCache.value = false;
  }
  return petRunningCache.value;
}

// ---------------------------------------------------------------- 路由

const server = createServer((req, res) => {
  void handle(req, res).catch((err) => {
    log("请求处理失败:", err?.message ?? err);
    if (!res.headersSent) sendError(res, 500, String(err?.message ?? err));
    else res.end();
  });
});

async function handle(req, res) {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const route = `${req.method} ${url.pathname}`;

  // 请求卫生：只收本机 Host（协议代理本来就在本机，这里是第二道闸）。
  const host = String(req.headers.host ?? "");
  if (!/^127\.0\.0\.1(:|$)/.test(host) && !/^localhost(:|$)/.test(host)) {
    return sendError(res, 403, "forbidden host");
  }

  if (route === "GET /api/state") {
    const home = petHome();
    if (home === null) {
      return sendJson(res, 200, { ok: true, missing: true, characters: [] });
    }
    const state = buildCatalogState({ petHome: home, pluginsRoot: pluginsRoot() });
    state.petRunning = petRunning();
    state.ok = true;
    return sendJson(res, 200, state);
  }

  if (route === "GET /api/preview") {
    const home = petHome();
    if (home === null) return sendError(res, 404, "桌宠家不存在");
    const file = String(url.searchParams.get("file") ?? "");
    // 预览图只可能来自桌宠家（本机角色）或插件包自带的 characters 目录。
    const roots = [home, ...packCharacterRoots(pluginsRoot()).map((r) => r.dir)];
    const checked = roots.map((root) => insideRoot(root, normalize(file))).find((p) => p !== null) ?? null;
    if (checked === null) return sendError(res, 403, "forbidden path");
    let stat;
    try {
      stat = statSync(checked);
    } catch {
      return sendError(res, 404, "preview not found");
    }
    if (!stat.isFile()) return sendError(res, 404, "preview not found");
    const mime = MIME[extname(checked).toLowerCase()] ?? "application/octet-stream";
    res.writeHead(200, { "content-type": mime, "cache-control": "max-age=86400" });
    res.end(readFileSync(checked));
    return;
  }

  // 只有 webm 的角色包：把首帧抠成透明 PNG 再给 <img>。自定义协议下 <video>
  // 拿不到画面，静态图是唯一在 laji-plugin:// 下稳定显示的预览形态。
  if (route === "GET /api/thumb") {
    const home = petHome();
    if (home === null) return sendError(res, 404, "桌宠家不存在");
    const file = String(url.searchParams.get("file") ?? "");
    if (!/\.webm$/i.test(file)) return sendError(res, 400, "只支持 webm");
    const roots = [home, ...packCharacterRoots(pluginsRoot()).map((r) => r.dir)];
    const checked = roots.map((root) => insideRoot(root, normalize(file))).find((p) => p !== null) ?? null;
    if (checked === null) return sendError(res, 403, "forbidden path");
    try {
      if (!statSync(checked).isFile()) return sendError(res, 404, "preview not found");
    } catch {
      return sendError(res, 404, "preview not found");
    }
    let thumb;
    try {
      thumb = thumbFor(checked, home);
    } catch (err) {
      return sendError(res, 500, `抽帧失败: ${err?.message ?? err}`);
    }
    if (thumb === null) return sendError(res, 503, "抽帧失败");
    res.writeHead(200, { "content-type": "image/png", "cache-control": "max-age=86400" });
    res.end(readFileSync(thumb));
    return;
  }

  // open-config 必须排在通用 POST /api/ 块之前，否则会被当成配置写操作
  // 塞进 applyConfigOp 白名单外报"不支持的操作"。
  if (route === "POST /api/open-config") {
    const home = petHome();
    if (home === null) return sendError(res, 503, "桌宠家不存在");
    if (!IS_WINDOWS) return sendError(res, 501, "仅支持 Windows");
    const target = join(home, "config.json");
    try {
      // windowsHide 铁律；explorer /select 选中文件，退出码 1 属正常。
      spawn("explorer.exe", [`/select,${target}`], { windowsHide: true, detached: true, stdio: "ignore" }).unref();
    } catch (err) {
      return sendError(res, 500, String(err?.message ?? err));
    }
    return sendJson(res, 200, { ok: true });
  }

  // 连接测试：与桌宠 test_connection 同口径 —— 发一条 max_tokens=1 的 ping。
  if (route === "POST /api/test-provider") {
    let payload;
    try {
      payload = await readBody(req);
    } catch {
      return sendError(res, 400, "请求体不是合法 JSON");
    }
    const base = String(payload.base_url ?? "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(base)) return sendError(res, 400, "API 地址必须是 http(s)");
    let key = String(payload.api_key ?? "").trim();
    const id = String(payload.id ?? "");
    if (!key && id) {
      const home = petHome();
      const entry = home ? readPetConfig(home)?.chat?.providers?.[id] : null;
      if (entry && typeof entry === "object") key = String(entry.api_key ?? "").trim();
    }
    const chatPath = String(payload.chat_path ?? "/v1/chat/completions") || "/v1/chat/completions";
    const endpoint = base.endsWith("/chat/completions")
      ? base
      : (/\/v\d+$/.test(base) && chatPath === "/v1/chat/completions" ? `${base}/chat/completions` : base + chatPath);
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15_000);
    try {
      const r = await fetch(endpoint, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          ...(key ? { authorization: `Bearer ${key}` } : {}),
        },
        body: JSON.stringify({
          model: String(payload.model ?? ""),
          messages: [{ role: "user", content: "ping" }],
          max_tokens: 1,
          stream: false,
        }),
        signal: ctrl.signal,
      });
      const text = await r.text().catch(() => "");
      clearTimeout(timer);
      if (r.ok) return sendJson(res, 200, { ok: true, status: r.status, message: `连接成功（HTTP ${r.status}）` });
      const detail = text.replace(/\s+/g, " ").slice(0, 200);
      const hint = r.status === 401 || r.status === 403 ? "认证失败" : "请求失败";
      return sendJson(res, 200, {
        ok: false,
        status: r.status,
        message: `${hint}（HTTP ${r.status}）${detail ? "：" + detail : ""}`,
      });
    } catch (err) {
      clearTimeout(timer);
      const msg = err?.name === "AbortError" ? "请求超时" : String(err?.message ?? err);
      return sendJson(res, 200, { ok: false, message: `网络连接失败：${msg}` });
    }
  }

  // 模型列表：GET {端点}/models（OpenAI 兼容），给「添加模型」的 Model ID 下拉用。
  if (route === "POST /api/list-models") {
    let payload;
    try {
      payload = await readBody(req);
    } catch {
      return sendError(res, 400, "请求体不是合法 JSON");
    }
    const base = String(payload.base_url ?? "").trim().replace(/\/+$/, "");
    if (!/^https?:\/\//i.test(base)) return sendError(res, 400, "API 地址必须是 http(s)");
    let key = String(payload.api_key ?? "").trim();
    const id = String(payload.id ?? "");
    if (!key && id) {
      const home = petHome();
      const entry = home ? readPetConfig(home)?.chat?.providers?.[id] : null;
      if (entry && typeof entry === "object") key = String(entry.api_key ?? "").trim();
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 15_000);
    try {
      const r = await fetch(`${base}/models`, {
        headers: key ? { authorization: `Bearer ${key}` } : {},
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (!r.ok) {
        const detail = (await r.text().catch(() => "")).replace(/\s+/g, " ").slice(0, 200);
        return sendJson(res, 200, {
          ok: false,
          status: r.status,
          message: `拉取失败（HTTP ${r.status}）${detail ? "：" + detail : ""}`,
        });
      }
      const data = await r.json().catch(() => null);
      const list = Array.isArray(data?.data) ? data.data : Array.isArray(data) ? data : [];
      const models = [...new Set(list.map((m) => String(m?.id ?? "")).filter(Boolean))].slice(0, 200);
      return sendJson(res, 200, { ok: true, models });
    } catch (err) {
      clearTimeout(timer);
      const msg = err?.name === "AbortError" ? "请求超时" : String(err?.message ?? err);
      return sendJson(res, 200, { ok: false, message: `网络连接失败：${msg}` });
    }
  }

  // 全量设置：按 catalog 目录校验 + 全局/每宠分流，必须排在通用 POST 之前。
  if (route === "POST /api/settings") {
    const home = petHome();
    if (home === null) return sendError(res, 503, "桌宠家不存在（桌宠还没跑过？）");
    let patch;
    try {
      patch = await readBody(req, 256 * 1024);
    } catch (err) {
      return sendError(res, 400, `请求体不是合法 JSON: ${err?.message ?? err}`);
    }
    const config = readPetConfig(home);
    const slot = readSlot0(home);
    const plan = planSettingsPatch(patch, {
      global: config,
      slot: slot ?? {},
      effective: mergeDeep(config, slot ?? {}),
      current: slot?.character ?? config.character ?? "",
    });
    try {
      // 深合并会把「模型清单里删掉的 id」合并回来：这类路径按整替换落盘。
      let nextConfig = mergeDeep(config, { ...plan.globalPatch, ...plan.slotPatch });
      for (const path of plan.replacePaths ?? []) {
        const parts = String(path).split(".");
        let src = plan.globalPatch;
        let dst = nextConfig;
        for (let i = 0; i < parts.length - 1; i += 1) {
          src = src?.[parts[i]];
          dst = dst?.[parts[i]];
        }
        const leaf = parts[parts.length - 1];
        if (src && dst && Object.prototype.hasOwnProperty.call(src, leaf)) dst[leaf] = src[leaf];
      }
      // slot 档案不存在（未迁移）时全局键就是真值：两边都写，兼容两种安装状态。
      // 已迁移时每宠键只落 slot 档案——写回全局 config.json 会让下次启动的 slot0
      // 迁移备份校验失败（backup-invalid → 桌宠起不来，2026-11-08 实测）。
      let slotWrite = null;
      if (slot !== null) {
        const split = splitPerPetState(nextConfig, mergeDeep(slot, plan.slotPatch));
        nextConfig = split.global;
        if (Object.keys(plan.slotPatch).length > 0 || split.carried > 0) slotWrite = split.slot;
      }
      writeJsonAtomic(join(home, "config.json"), nextConfig);
      if (slotWrite !== null) {
        writeJsonAtomic(join(home, "config-slot-0.json"), slotWrite);
      }
    } catch (err) {
      return sendError(res, 500, `写配置失败: ${err?.message ?? err}`);
    }
    log("全量设置:", plan.written.length, "项, 跳过", plan.skipped.length, "拒绝", plan.rejected.length);
    return sendJson(res, 200, {
      ok: true,
      written: plan.written.length,
      global: Object.keys(plan.globalPatch).length,
      slot: Object.keys(plan.slotPatch).length,
      skipped: plan.skipped,
      rejected: plan.rejected,
    });
  }

  if (route.startsWith("POST /api/")) {
    const home = petHome();
    if (home === null) return sendError(res, 503, "桌宠家不存在（桌宠还没跑过？）");
    let payload;
    try {
      payload = await readBody(req);
    } catch (err) {
      return sendError(res, 400, `请求体不是合法 JSON: ${err?.message ?? err}`);
    }
    const op = url.pathname.slice("/api/".length);
    let next;
    let before;
    try {
      before = JSON.parse(readFileSync(join(home, "config.json"), "utf8"));
      next = applyConfigOp(before, op, payload);
    } catch (err) {
      return sendError(res, 400, String(err?.message ?? err));
    }
    try {
      // 已迁移时每宠键只落 slot 档案（backup-invalid 防护，同 /api/settings）：
      // op 改过的每宠键值先进 slot（那边才是真值），全局侧一律摘除。
      let slotWrite = null;
      const slot = readSlot0(home);
      if (slot !== null) {
        const slotNext = { ...slot };
        let slotTouched = false;
        for (const key of SLOT_KEYS) {
          if (key in next && next[key] !== before[key]) {
            slotNext[key] = next[key];
            slotTouched = true;
          }
        }
        const split = splitPerPetState(next, slotNext);
        next = split.global;
        if (slotTouched || split.carried > 0) slotWrite = split.slot;
      }
      writeJsonAtomic(join(home, "config.json"), next);
      if (slotWrite !== null) {
        writeJsonAtomic(join(home, "config-slot-0.json"), slotWrite);
      }
    } catch (err) {
      return sendError(res, 500, `写配置失败: ${err?.message ?? err}`);
    }
    // 切换角色是每宠键：全局键之外还要同步进主宠 slot 档案，下次启动才真登场。
    if (op === "switch" && typeof next.character === "string") {
      try {
        writeMainSlotCharacter(home, next.character);
      } catch (err) {
        log("写 slot 档案失败（全局键已更新）:", err?.message ?? err);
      }
    }
    log("配置更新:", op, JSON.stringify(payload).slice(0, 200));
    return sendJson(res, 200, { ok: true });
  }

  if (route === "GET /api/health") {
    return sendJson(res, 200, { ok: true, petHome: LAJI_PET_HOME });
  }

  return sendError(res, 404, "not found");
}

server.listen(0, "127.0.0.1", () => {
  const { port } = server.address();
  writeFileSync(RUNTIME_FILE, JSON.stringify({ port, pid: process.pid }), "utf8");
  log("listening on 127.0.0.1:" + port, "runtime.json ->", RUNTIME_FILE);
});

function shutdown() {
  try {
    server.close();
  } catch {
    /* 尽力 */
  }
  try {
    // 只清自己写的端口文件：pid 不是自己就别动（防误删后继者的登记）。
    const parsed = JSON.parse(readFileSync(RUNTIME_FILE, "utf8"));
    if (Number(parsed.pid) === process.pid) {
      import("node:fs").then((fs) => fs.rmSync(RUNTIME_FILE, { force: true }));
    }
  } catch {
    /* 没有 / 坏了就算了 */
  }
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
