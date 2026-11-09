// 消息通知 · 本机服务。
//
// 职责三件：存配置（含凭据）、按事件决定发哪些渠道、真正发出去。
// 渲染层只通过 `laji-plugin://com.nerve.dsh-notify/__proxy/...` 打到这里，
// 因为生产 CSP 不放行回环 http，也不该让面板碰 SMTP / 签名密钥。
//
// 单实例：runtime.json 里记 pid，宿主那边的 runtimeAlive() 也按它判断。
// 端口由内核分配（listen 0），再写回 runtime.json —— 与 dsh-whale-widget 同约定。

import { appendFileSync, chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHmac } from "node:crypto";
import { createServer } from "node:http";
import { request as httpsRequest } from "node:https";
import { connect as tlsConnect } from "node:tls";
import { connect as netConnect } from "node:net";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const PLUGIN_DIR = path.resolve(HERE, "..");
const STATE_DIR = path.join(PLUGIN_DIR, "state");
const CONFIG_FILE = path.join(STATE_DIR, "config.json");
const LOG_FILE = path.join(STATE_DIR, "notify-log.jsonl");
const RUNTIME_FILE = path.join(PLUGIN_DIR, "runtime.json");

const CHANNELS = ["sms", "mail", "wecom"];
const EVENT_LABEL = { approval: "审批", questions: "提问", error: "错误", plan: "计划" };

export const DEFAULT_CONFIG = {
  enabled: true,
  channels: {
    sms: {
      on: false,
      provider: "aliyun",
      sign: "",
      templateCode: "",
      phones: [],
      webhook: "",
      accessKeyId: "",
      accessKeySecret: "",
    },
    mail: {
      on: false,
      host: "",
      port: 465,
      secure: true,
      from: "",
      to: [],
      user: "",
      pass: "",
      subject: "[{{事件}}] {{标题}}",
      body: "{{事件}}：{{标题}}\n{{会话}}\n\n{{详情}}",
      html: false,
    },
    wecom: {
      on: false,
      webhook: "",
      mention: "",
      template: "**{{事件}}** {{标题}}\n> {{会话}}\n\n{{详情}}",
    },
  },
  events: {
    approval: { sms: true, mail: true, wecom: true },
    questions: { sms: false, mail: true, wecom: true },
    error: { sms: true, mail: true, wecom: true },
    plan: { sms: false, mail: false, wecom: true },
  },
  policy: { onlyUnfocused: true, quiet: { on: true, start: "22:00", end: "08:00" }, hourlyMax: 10 },
};

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

/** 逐键合并，数组整体替换：面板每次提交整份设置，「恢复默认」也走这条路。 */
export function mergeConfig(base, patch) {
  const out = clone(base);
  if (!patch || typeof patch !== "object") return out;
  for (const key of Object.keys(out)) {
    const next = patch[key];
    if (next === undefined) continue;
    if (Array.isArray(out[key])) {
      if (Array.isArray(next)) out[key] = next.map(String);
    } else if (out[key] && typeof out[key] === "object") {
      out[key] = mergeConfig(out[key], next);
    } else if (typeof next === typeof out[key]) {
      out[key] = next;
    }
  }
  return out;
}

function readJson(file, fallback) {
  try {
    return JSON.parse(readFileSync(file, "utf8"));
  } catch {
    return fallback;
  }
}

export function loadConfig(file = CONFIG_FILE) {
  return mergeConfig(DEFAULT_CONFIG, readJson(file, {}));
}

export function saveConfig(config, file = CONFIG_FILE) {
  if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true });
  writeFileSync(file, JSON.stringify(config, null, 2), "utf8");
  try {
    chmodSync(file, 0o600);
  } catch {
    /* Windows 上 chmod 只是尽力而为 */
  }
}

/** 给渲染层看的版本：密钥不出插件目录，只说「有没有」。 */
export function publicConfig(config) {
  const out = clone(config);
  const secrets = {
    sms: Boolean(out.channels.sms.accessKeySecret) || Boolean(out.channels.sms.webhook),
    mail: Boolean(out.channels.mail.pass),
  };
  out.channels.sms.accessKeySecret = "";
  out.channels.mail.pass = "";
  return { config: out, secrets };
}

/** 提交里的空密钥 = 没改，保留旧值；面板因此不需要回填明文。 */
export function applySecrets(prev, next) {
  if (!next.channels.sms.accessKeySecret) next.channels.sms.accessKeySecret = prev.channels.sms.accessKeySecret;
  if (!next.channels.mail.pass) next.channels.mail.pass = prev.channels.mail.pass;
  return next;
}

export function appendLog(row, file = LOG_FILE) {
  if (!existsSync(STATE_DIR)) mkdirSync(STATE_DIR, { recursive: true });
  appendFileSync(file, `${JSON.stringify(row)}\n`, "utf8");
}

export function readLog(limit = 60, file = LOG_FILE) {
  try {
    return readFileSync(file, "utf8")
      .split("\n")
      .filter(Boolean)
      .slice(-limit)
      .reverse()
      .map((line) => {
        try {
          return JSON.parse(line);
        } catch {
          return null;
        }
      })
      .filter(Boolean);
  } catch {
    return [];
  }
}

/** "22:00" → 分钟数。非法值返回 null（静默时段失效，不阻断发送）。 */
export function parseClock(text) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(text ?? ""));
  if (!m) return null;
  const h = Number(m[1]);
  const min = Number(m[2]);
  if (h > 23 || min > 59) return null;
  return h * 60 + min;
}

/** 支持跨零点的静默时段：22:00–08:00 命中，08:00–22:00 不命中。 */
export function inQuietHours(date, quiet) {
  if (!quiet?.on) return false;
  const start = parseClock(quiet.start);
  const end = parseClock(quiet.end);
  if (start === null || end === null || start === end) return false;
  const now = date.getHours() * 60 + date.getMinutes();
  return start < end ? now >= start && now < end : now >= start || now < end;
}

/**
 * 决定这条事件发哪些渠道。
 *
 * `sentInLastHour` 与 `focused` 由调用方给：前者是服务端窗口（单实例，计得准），
 * 后者来自面板上报的窗口焦点 —— 服务端不知道 Laji 是不是在前台。
 */
export function planDeliveries(config, event, ctx = {}) {
  if (!config.enabled) return [];
  if (config.policy.onlyUnfocused && ctx.focused === true) return [];
  if (inQuietHours(ctx.now ?? new Date(), config.policy.quiet)) return [];
  const max = Number(config.policy.hourlyMax);
  if (Number.isFinite(max) && max > 0 && (ctx.sentInLastHour ?? 0) >= max) return [];
  const rows = config.events?.[event.kind] ?? {};
  return CHANNELS.filter((ch) => config.channels?.[ch]?.on && rows[ch]);
}

function firstLine(text, cap = 160) {
  const flat = String(text ?? "").replace(/\s+/g, " ").trim();
  return flat.length > cap ? `${flat.slice(0, cap)}…` : flat;
}

/** 四类事件的中文文案。短信短、企微/邮件带上下文。 */
export function renderMessage(event) {
  const kind = EVENT_LABEL[event.kind] ?? "通知";
  const where = event.sessionTitle ? `会话「${event.sessionTitle}」` : "当前会话";
  const detail = firstLine(event.detail, 200);
  const title = firstLine(event.title, 60);
  return {
    kind,
    title,
    detail,
    where,
    short: `[${kind}] ${firstLine(event.title, 40)} ${where}`,
    lines: [`[${kind}] ${title}`, where, detail].filter(Boolean),
    markdown: [`**[${kind}]** ${title}`, `> ${where}`, detail ? `\`${detail}\`` : ""].filter(Boolean).join("\n"),
  };
}

/** 模板占位符：{{事件}} {{标题}} {{会话}} {{详情}}；认不出的占位原样留着。 */
export function renderTemplate(template, message) {
  const values = {
    "事件": message.kind,
    "标题": message.title,
    "会话": message.where,
    "详情": message.detail,
  };
  return String(template || "")
    .replace(/\{\{\s*([^{}]+?)\s*\}\}/g, (all, key) => (key in values ? String(values[key] ?? "") : all))
    .trim();
}

/** 阿里云短信 RPC 签名（SignatureVersion 1.0）。 */
export function aliyunSignature(params, secret) {
  const enc = (s) =>
    encodeURIComponent(String(s))
      .replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`)
      .replace(/\+/g, "%20")
      .replace(/\*/g, "%2A")
      .replace(/%7E/g, "~");
  const canonical = Object.keys(params)
    .sort()
    .map((k) => `${enc(k)}=${enc(params[k])}`)
    .join("&");
  const stringToSign = `GET&${enc("/")}&${enc(canonical)}`;
  return createHmac("sha1", `${secret}&`).update(stringToSign).digest("base64");
}

function httpsJson(url, { method = "POST", headers = {}, body } = {}) {
  return new Promise((resolve, reject) => {
    const target = url instanceof URL ? url : new URL(url);
    if (target.protocol !== "https:") {
      reject(new Error(`只支持 https：${target.protocol}`));
      return;
    }
    const req = httpsRequest(
      target,
      { method, headers: { "content-type": "application/json", ...headers } },
      (res) => {
        let text = "";
        res.setEncoding("utf8");
        res.on("data", (chunk) => {
          text += chunk;
        });
        res.on("end", () => {
          let json = null;
          try {
            json = JSON.parse(text || "{}");
          } catch {
            /* 非 JSON 响应交给调用方看 text */
          }
          resolve({ status: res.statusCode ?? 0, json, text });
        });
      },
    );
    req.on("error", reject);
    if (body !== undefined) req.write(body);
    req.end();
  });
}

export async function sendWecom(cfg, message) {
  if (!/^https:\/\//.test(cfg.webhook || "")) throw new Error("企业微信 webhook 必须以 https:// 开头");
  const mention = String(cfg.mention || "").trim();
  const body = cfg.template ? renderTemplate(cfg.template, message) : message.markdown;
  const content = mention ? `${body}\n<@${mention}>` : body;
  const res = await httpsJson(cfg.webhook, {
    body: JSON.stringify({ msgtype: "markdown", markdown: { content } }),
  });
  const errcode = res.json?.errcode;
  if (res.status !== 200 || (errcode !== undefined && errcode !== 0)) {
    throw new Error(`企业微信失败 ${errcode ?? res.status}：${res.json?.errmsg ?? res.text.slice(0, 120)}`);
  }
}

export async function sendSms(cfg, message) {
  if (cfg.provider === "webhook") {
    if (!cfg.webhook) throw new Error("短信网关地址为空");
    const res = await httpsJson(cfg.webhook, {
      body: JSON.stringify({ phones: cfg.phones, text: message.short, kind: message.kind }),
    });
    if (res.status !== 200) throw new Error(`短信网关失败 ${res.status}`);
    return;
  }
  const phones = (cfg.phones ?? []).filter(Boolean);
  if (!phones.length) throw new Error("短信接收号码为空");
  if (!cfg.accessKeyId || !cfg.accessKeySecret) throw new Error("短信 AccessKey 未配置");
  if (!cfg.sign || !cfg.templateCode) throw new Error("短信签名或模板未配置");
  const params = {
    AccessKeyId: cfg.accessKeyId,
    Action: "SendSms",
    Format: "JSON",
    PhoneNumbers: phones.join(","),
    RegionId: "cn-hangzhou",
    SignName: cfg.sign,
    SignatureMethod: "HMAC-SHA1",
    SignatureNonce: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    SignatureVersion: "1.0",
    TemplateCode: cfg.templateCode,
    // 模板里用 ${kind} / ${title} 两个变量；短信模板必须先在控制台过审。
    TemplateParam: JSON.stringify({ kind: message.kind, title: message.title }),
    Timestamp: new Date().toISOString().replace(/\.\d{3}Z$/, "Z"),
    Version: "2017-05-25",
  };
  const signature = aliyunSignature(params, cfg.accessKeySecret);
  const url = new URL("https://dysmsapi.aliyuncs.com/");
  for (const [k, v] of Object.entries({ ...params, Signature: signature })) url.searchParams.set(k, String(v));
  const res = await httpsJson(url.toString(), { method: "GET" });
  if (res.json?.Code !== "OK") throw new Error(`阿里云短信失败：${res.json?.Message ?? res.status}`);
}

/** 最小 SMTP 客户端：EHLO → AUTH LOGIN → MAIL/RCPT → DATA。够发纯文本通知。 */
export function smtpSend(cfg, mail, timeoutMs = 20_000) {
  return new Promise((resolve, reject) => {
    const secure = cfg.secure !== false;
    const socket = secure
      ? tlsConnect({ host: cfg.host, port: Number(cfg.port) || 465, servername: cfg.host })
      : netConnect({ host: cfg.host, port: Number(cfg.port) || 25 });
    let buffer = "";
    let settled = false;
    const queue = [];
    let waiter = null;
    const timer = setTimeout(() => finish(new Error("SMTP 超时")), timeoutMs);

    function finish(err) {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      socket.destroy();
      if (err) reject(err);
      else resolve(true);
    }

    function deliverResponse(res) {
      if (waiter) {
        const w = waiter;
        waiter = null;
        w(res);
      } else {
        queue.push(res);
      }
    }

    // 一条响应可能是多行；最后一行的第 4 个字符是空格（`250-` = 未完）。
    function drain() {
      for (;;) {
        const lines = buffer.split("\r\n");
        let consumed = 0;
        let last = -1;
        for (let i = 0; i < lines.length; i++) {
          if (lines[i] === "") break;
          consumed += lines[i].length + 2;
          if (/^\d{3} /.test(lines[i])) {
            last = i;
            break;
          }
        }
        if (last < 0) return;
        const chunk = lines.slice(0, last + 1);
        buffer = buffer.slice(consumed);
        deliverResponse({
          code: Number(chunk[chunk.length - 1].slice(0, 3)),
          text: chunk.join("\n"),
        });
      }
    }

    socket.setEncoding("utf8");
    socket.on("data", (chunk) => {
      buffer += chunk;
      drain();
    });
    socket.on("error", (err) => finish(err));
    socket.on("close", () => {
      if (!settled) finish(new Error("SMTP 连接被关闭"));
    });

    const read = () => (queue.length ? Promise.resolve(queue.shift()) : new Promise((res) => (waiter = res)));
    const expect = async (want, label) => {
      const r = await read();
      if (Math.floor(r.code / 100) !== want) throw new Error(`${label} 失败：${r.text}`);
      return r;
    };
    const write = (line) => socket.write(`${line}\r\n`);

    (async () => {
      await expect(2, "连接");
      write("EHLO laji-notify");
      await expect(2, "EHLO");
      if (cfg.user) {
        write("AUTH LOGIN");
        await expect(3, "AUTH");
        write(Buffer.from(String(cfg.user), "utf8").toString("base64"));
        await expect(3, "AUTH 用户");
        write(Buffer.from(String(cfg.pass ?? ""), "utf8").toString("base64"));
        await expect(2, "AUTH 密码");
      }
      write(`MAIL FROM:<${cfg.from}>`);
      await expect(2, "MAIL FROM");
      const tos = (cfg.to ?? []).filter(Boolean);
      for (const addr of tos) {
        write(`RCPT TO:<${addr}>`);
        await expect(2, `RCPT ${addr}`);
      }
      write("DATA");
      await expect(3, "DATA");
      const subject = `=?UTF-8?B?${Buffer.from(mail.subject, "utf8").toString("base64")}?=`;
      const isHtml = Boolean(mail.html);
      const body = Buffer.from(mail.text, "utf8").toString("base64").replace(/(.{76})/g, "$1\r\n");
      const raw = [
        `From: <${cfg.from}>`,
        `To: ${tos.join(", ")}`,
        `Subject: ${subject}`,
        "MIME-Version: 1.0",
        `Content-Type: ${isHtml ? "text/html" : "text/plain"}; charset=UTF-8`,
        "Content-Transfer-Encoding: base64",
        "",
        body,
        ".",
      ].join("\r\n");
      write(raw);
      await expect(2, "DATA 提交");
      write("QUIT");
      finish(null);
    })().catch((err) => finish(err));
  });
}

export async function sendMail(cfg, message) {
  const tos = (cfg.to ?? []).filter(Boolean);
  if (!cfg.host || !cfg.from || !tos.length) throw new Error("邮件服务器 / 发件人 / 收件人为空");
  const body = renderTemplate(cfg.body || "{{事件}}：{{标题}}\n{{会话}}\n\n{{详情}}", message);
  const html = cfg.html === true;
  await smtpSend(cfg, {
    subject: renderTemplate(cfg.subject || "[{{事件}}] {{标题}}", message),
    // 勾了 HTML 但正文还是纯文本时，至少别把换行吃掉
    text: html && !body.includes("<") ? body.replace(/\n/g, "<br>") : body,
    html,
  });
}

const SENDERS = { sms: sendSms, mail: sendMail, wecom: sendWecom };

/** 发一条事件到指定渠道；一个渠道失败不影响其它渠道，逐条回报。 */
export async function deliver(config, event, channels) {
  const message = renderMessage(event);
  const results = [];
  for (const channel of channels) {
    const started = Date.now();
    try {
      await SENDERS[channel](config.channels[channel], message);
      results.push({ channel, ok: true, ms: Date.now() - started });
    } catch (err) {
      results.push({ channel, ok: false, ms: Date.now() - started, error: err?.message ?? String(err) });
    }
  }
  return { message, results };
}

// ── HTTP 面：只绑回环，路径面尽量窄 ────────────────────────────────

const sentAt = [];
function countLastHour(now = Date.now()) {
  const cut = now - 3_600_000;
  while (sentAt.length && sentAt[0] < cut) sentAt.shift();
  return sentAt.length;
}

function json(res, status, payload) {
  const text = JSON.stringify(payload);
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(text);
}

function readBody(req, limit = 1_000_000) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on("data", (chunk) => {
      size += chunk.length;
      if (size > limit) {
        reject(new Error("请求体过大"));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on("end", () => {
      const text = Buffer.concat(chunks).toString("utf8");
      if (!text) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(text));
      } catch {
        reject(new Error("请求体不是 JSON"));
      }
    });
    req.on("error", reject);
  });
}

const SAMPLE_EVENT = {
  kind: "approval",
  at: Date.now(),
  runId: "test-run",
  callId: "test-call",
  title: "测试消息",
  detail: "这条来自面板的「发送测试」",
  sessionTitle: "消息通知",
};

async function handle(req, res) {
  const url = new URL(req.url ?? "/", "http://127.0.0.1");
  const route = `${req.method} ${url.pathname}`;

  if (route === "GET /health") {
    json(res, 200, { ok: true, pid: process.pid });
    return;
  }
  if (route === "GET /config") {
    json(res, 200, publicConfig(loadConfig()));
    return;
  }
  if (route === "POST /config") {
    const prev = loadConfig();
    const patch = await readBody(req);
    const next = applySecrets(prev, mergeConfig(prev, patch));
    saveConfig(next);
    json(res, 200, { ok: true, ...publicConfig(next) });
    return;
  }
  if (route === "GET /log") {
    const limit = Number(url.searchParams.get("limit") ?? 60);
    json(res, 200, { rows: readLog(Number.isFinite(limit) ? Math.min(Math.max(limit, 1), 300) : 60) });
    return;
  }
  if (route === "POST /test") {
    const body = await readBody(req);
    const channel = String(body.channel ?? "");
    if (!SENDERS[channel]) {
      json(res, 400, { ok: false, error: "未知渠道" });
      return;
    }
    const config = loadConfig();
    try {
      await SENDERS[channel](config.channels[channel], renderMessage(SAMPLE_EVENT));
      json(res, 200, { ok: true });
    } catch (err) {
      json(res, 200, { ok: false, error: err?.message ?? String(err) });
    }
    return;
  }
  if (route === "POST /notify") {
    const body = await readBody(req);
    const event = body.event;
    if (!event || typeof event.kind !== "string") {
      json(res, 400, { ok: false, error: "缺少 event" });
      return;
    }
    if (!EVENT_LABEL[event.kind]) {
      json(res, 400, { ok: false, error: `未知事件类型 ${event.kind}` });
      return;
    }
    const config = loadConfig();
    const channels = planDeliveries(config, event, {
      focused: body.focused === true,
      sentInLastHour: countLastHour(),
    });
    const at = new Date().toISOString();
    if (!channels.length) {
      appendLog({ at, kind: event.kind, title: event.title, skipped: true });
      json(res, 200, { ok: true, delivered: [], skipped: true });
      return;
    }
    const { results } = await deliver(config, event, channels);
    const now = Date.now();
    for (const r of results) if (r.ok) sentAt.push(now);
    appendLog({ at, kind: event.kind, title: event.title, sessionTitle: event.sessionTitle ?? null, results });
    json(res, 200, { ok: true, delivered: results });
    return;
  }
  json(res, 404, { ok: false, error: "not found" });
}

function log(message) {
  process.stderr.write(`[notify] ${message}\n`);
}

function isMain() {
  try {
    return process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href;
  } catch {
    return false;
  }
}

if (isMain()) {
  const server = createServer((req, res) => {
    handle(req, res).catch((err) => {
      log(`request failed: ${err?.stack ?? err}`);
      json(res, 500, { ok: false, error: err?.message ?? "internal error" });
    });
  });

  server.on("error", (err) => {
    log(`listen failed: ${err?.stack ?? err}`);
    process.exit(1);
  });

  server.listen(0, "127.0.0.1", () => {
    const addr = server.address();
    const port = addr && typeof addr === "object" ? addr.port : 0;
    writeFileSync(
      RUNTIME_FILE,
      JSON.stringify({ port, pid: process.pid, updatedAt: new Date().toISOString() }, null, 2),
      "utf8",
    );
    log(`listening on 127.0.0.1:${port}`);
  });

  const shutdown = () => {
    try {
      const prev = readJson(RUNTIME_FILE, {});
      if (prev && prev.pid === process.pid) writeFileSync(RUNTIME_FILE, "{}", "utf8");
    } catch {
      /* 退出时删不到也没关系 */
    }
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
  process.on("exit", () => {
    try {
      const prev = readJson(RUNTIME_FILE, {});
      if (prev && prev.pid === process.pid) writeFileSync(RUNTIME_FILE, "{}", "utf8");
    } catch {
      /* ignore */
    }
  });
}

