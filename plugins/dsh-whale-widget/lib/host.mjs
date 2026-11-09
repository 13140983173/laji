// dsh-whale-widget 的宿主薄壳（Laji 侧）。
//
// 上游是 DSH 的 cordis bundle：`vendor/lib/index.mjs` 只用到宿主的一小块契约
// —— `webServer.register/tapIndex`、`credentials.resolve/set`、`on`、`effect`、
// `get`、`inject`。Laji 没有 cordis，也没有 `/dsh-whale/*` 路由，所以这里按那
// 一小块把 ctx 实现出来，起一个**只绑回环**的 HTTP 服务，然后原样跑上游的
// 22 条路由（余额、峰谷、角色、音效、设置持久化都在里面）。
//
// 浏览器不直连这个端口：CSP 不放行回环 http，且上游自带的跨站栅栏会拒掉带
// Origin 的浏览器请求。渲染层的 `/dsh-whale/*` 统一走主进程的
// `laji-plugin://<id>/__proxy/...`（见 apps/laji-agent/src/main/plugin-protocol.ts），
// 由主进程代理到这里的端口。端口写在 `<安装目录>/runtime.json`。

import { createServer } from "node:http";
import { cpSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const LIB_DIR = path.dirname(fileURLToPath(import.meta.url));
const PACKAGE_ROOT = path.resolve(LIB_DIR, "..");
// 用户数据（账本、凭据、日志）放在**插件目录之外**。
// 放在安装目录里的代价很实在：创意工坊的“更新/重装”是整目录替换，
// `state/` 会跟着被清空 —— 表现就是“刚填的 key 又 401 了”。
const DATA_ROOT = process.env.DSH_WHALE_DATA?.trim()
  ? path.resolve(process.env.DSH_WHALE_DATA.trim())
  : path.join(process.env.LOCALAPPDATA || os.homedir(), "laji", "plugin-data", "com.nerve.dsh-whale-widget");
const STATE_DIR = path.join(DATA_ROOT, "state");
const LEGACY_STATE_DIR = path.join(PACKAGE_ROOT, "state");
const RUNTIME_FILE = path.join(PACKAGE_ROOT, "runtime.json");
// 单实例锁放在数据目录：runtime.json 在插件目录里，更新/重装会被整目录替换，
// 锁一旦跟着丢，老实例还在跑、新实例照样起，两个进程同时写同一份账本。
const LOCK_FILE = path.join(STATE_DIR, "host.pid");
const CRED_FILE = path.join(STATE_DIR, "credentials.json");
const LOG_FILE = path.join(STATE_DIR, "host.log");

mkdirSync(STATE_DIR, { recursive: true });
// 旧版本的数据在插件目录里：新位置还没有账本时一次性搬过来。
if (!existsSync(path.join(STATE_DIR, "dsh")) && existsSync(path.join(LEGACY_STATE_DIR, "dsh"))) {
  try {
    cpSync(LEGACY_STATE_DIR, STATE_DIR, { recursive: true });
  } catch {
    /* 迁移失败不阻塞服务 */
  }
}
// 把进程的工作目录让出去：Windows 上如果有进程以某目录为 cwd，那个目录就删不掉、
// 也改不了名 —— 表现为在创意工坊卸载/更新插件时报 `EPERM, Permission denied`。
// supervisor 起本进程时 cwd 就是插件安装目录，所以这里主动切到临时目录。
// （本文件所有路径都用绝对路径，切走不影响后续读写。）
if (!process.env.DSH_HOME?.trim()) process.env.DSH_HOME = path.join(STATE_DIR, "dsh");
try {
  process.chdir(os.tmpdir());
} catch {
  /* 切不动就算了，服务优先 */
}

/** supervisor 用 `stdio: "ignore"` 起进程，日志只能自己落盘。 */
function log(line) {
  try {
    writeFileSync(LOG_FILE, `[${new Date().toISOString()}] ${line}\n`, { flag: "a" });
  } catch {
    /* 写不进日志就算了，别把服务本身拖死 */
  }
}

// ---------------------------------------------------------------------------
// 单实例：supervisor 的两条 app 条目（cmd.exe / 自定义 node）可能同时命中，
// 而以 pid 是否活着做判断，比端口占用更早、也更便宜。
// ---------------------------------------------------------------------------

function alivePid(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    // EPERM 表示进程存在但没权限发信号，同样是“有人在跑”；
    // 当成不存在会让第二个 host 也起来，两个实例各写一份账本。
    return Boolean(err && err.code === "EPERM");
  }
}

try {
  let prevPid = null;
  try {
    prevPid = Number.parseInt(readFileSync(LOCK_FILE, "utf8").trim(), 10);
  } catch {
    prevPid = null;
  }
  if (!Number.isInteger(prevPid) || prevPid <= 0) {
    try {
      prevPid = JSON.parse(readFileSync(RUNTIME_FILE, "utf8")).pid;
    } catch {
      prevPid = null;
    }
  }
  if (prevPid !== process.pid && alivePid(prevPid)) {
    log(`another host already running (pid ${prevPid}), exiting`);
    process.exit(0);
  }
} catch {
  /* 读不到就是首次启动 */
}
try {
  writeFileSync(LOCK_FILE, String(process.pid));
} catch {
  /* 锁写不进去也不阻塞服务；只是少了跨重装的互斥 */
}

/** `credentials.resolve()` 的返回形状：上游读 `cred.value`。 */
function readCredentials() {
  try {
    // 剥掉 UTF-8 BOM：Windows 记事本 / PowerShell 的 `-Encoding utf8` 都会写 BOM，
    // 而 JSON.parse 不认它 —— 那样凭据会被静默忽略并回退到宿主环境变量，
    // 表现成“明明填了 key 却一直 401”。
    const text = readFileSync(CRED_FILE, "utf8").replace(/^\uFEFF/, "");
    const doc = JSON.parse(text);
    return doc && typeof doc === "object" ? doc : {};
  } catch {
    return {};
  }
}

function writeCredentials(doc) {
  mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(CRED_FILE, JSON.stringify(doc, null, 2), "utf8");
}

const credentials = {
  /** 优先插件自己的账本，其次宿主进程环境（Laji 主进程会把 DEEPSEEK_API_KEY 注进 env）。 */
  async resolve(ref) {
    if (typeof ref !== "string" || ref === "") return null;
    const stored = readCredentials()[ref];
    const value = stored && stored.value ? String(stored.value) : String(process.env[ref] ?? "");
    return value === "" ? null : { ref, value };
  },
  async set(ref, value) {
    if (typeof ref !== "string" || ref === "") return;
    writeCredentials({ ...readCredentials(), [ref]: { value: String(value) } });
  },
  async delete(ref) {
    const doc = readCredentials();
    delete doc[ref];
    writeCredentials(doc);
  },
};

const routes = [];
const disposers = [];
const noop = () => {};

/** 上游用到的那一小块 cordis ctx。宿主服务在这里都已就绪，inject 直接进回调。 */
const ctx = {
  get: () => undefined,
  on: () => noop,
  effect(fn) {
    const disposer = fn();
    if (typeof disposer === "function") disposers.push(disposer);
  },
  inject(_names, cb) {
    cb(ctx);
  },
  credentials: { ...credentials, remove: credentials.delete, unset: credentials.delete },
  webServer: {
    register(route) {
      routes.push(route);
      return () => {
        const i = routes.indexOf(route);
        if (i >= 0) routes.splice(i, 1);
      };
    },
    // 上游靠 index 注入行把 widget.js 塞进页面；Laji 的包装器自己建 script 标签，
    // 这一路留空即可（否则会在页面里插一段指向 `/dsh-whale/widget.js` 的相对路径）。
    tapIndex() {
      return noop;
    },
  },
};

function sendJson(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "content-length": Buffer.byteLength(text) });
  res.end(text);
}

const server = createServer((req, res) => {
  let pathname = "/";
  try {
    pathname = new URL(req.url ?? "/", "http://127.0.0.1").pathname;
  } catch {
    /* 落到 404 */
  }
  if (pathname === "/__health") {
    sendJson(res, 200, { ok: true, routes: routes.length, pid: process.pid });
    return;
  }
  const route = routes.find((r) => r && r.path === pathname);
  if (!route) {
    sendJson(res, 404, { ok: false, error: "no such route", path: pathname });
    return;
  }
  Promise.resolve()
    .then(() => route.handler(req, res))
    .catch((err) => {
      log(`route ${pathname} failed: ${err && err.stack ? err.stack : String(err)}`);
      if (!res.headersSent) sendJson(res, 500, { ok: false, error: String((err && err.message) || err) });
      else if (!res.writableEnded) res.end();
    });
});

try {
  const { default: plugin } = await import(new URL("../vendor/lib/index.mjs", import.meta.url).href);
  plugin.apply(ctx);
} catch (err) {
  log(`upstream plugin failed to load: ${err && err.stack ? err.stack : String(err)}`);
  process.exit(1);
}

server.on("error", (err) => {
  log(`listen failed: ${err && err.stack ? err.stack : String(err)}`);
  process.exit(1);
});

server.listen(0, "127.0.0.1", () => {
  const addr = server.address();
  const port = addr && typeof addr === "object" ? addr.port : 0;
  writeFileSync(RUNTIME_FILE, JSON.stringify({ port, pid: process.pid, updatedAt: new Date().toISOString() }, null, 2), "utf8");
  log(`listening on 127.0.0.1:${port} with ${routes.length} routes`);
});

function shutdown() {
  try {
    for (const d of disposers) {
      try {
        d();
      } catch {
        /* 单个 disposer 失败不影响退出 */
      }
    }
    const prev = JSON.parse(readFileSync(RUNTIME_FILE, "utf8"));
    if (prev && prev.pid === process.pid && existsSync(RUNTIME_FILE)) writeFileSync(RUNTIME_FILE, "{}", "utf8");
  } catch {
    /* ignore */
  }
  process.exit(0);
}

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
process.on("exit", () => {
  try {
    const prev = JSON.parse(readFileSync(RUNTIME_FILE, "utf8"));
    if (prev && prev.pid === process.pid) writeFileSync(RUNTIME_FILE, "{}", "utf8");
  } catch {
    /* ignore */
  }
});
