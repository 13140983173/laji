// 渠道弹框回归：起 host → 离屏加载 harness → 逐个打开渠道弹框 → 检查 EasyMDE/预览并截图。
//
//   node_modules\electron\dist\electron.exe packs\plugins\dsh-notify\test\capture-modal.cjs
//
// 插件前端从仓库读（`../lib/client.js`），但 vendor 走真实的 `laji-plugin://` 方案，
// 指向已安装的插件目录 —— 顺带验证 EasyMDE 静态资源确实随包发出去、路径规则放行。
// 安装目录默认 %LOCALAPPDATA%\laji\plugins\com.nerve.dsh-notify\0.1.0，可用 LAJI_PLUGIN_DIR 覆盖。
const { app, BrowserWindow, protocol } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const PLUGIN_DIR = path.resolve(__dirname, "..");
const REPO = path.resolve(PLUGIN_DIR, "../../..");
const OUT = path.join(REPO, "docs/prototypes/assets/notify-plugin-settings");
const HARNESS = path.join(__dirname, "panel-harness.html");
const INSTALLED =
  process.env.LAJI_PLUGIN_DIR ||
  path.join(process.env.LOCALAPPDATA || "", "laji", "plugins", "com.nerve.dsh-notify", "0.1.0");

app.disableHardwareAcceleration();
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const say = (msg) => process.stdout.write("[modal] " + msg + "\n");

protocol.registerSchemesAsPrivileged([
  { scheme: "laji-plugin", privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true } },
]);

app.whenReady().then(async () => {
  let host = null;
  let failures = 0;
  try {
    protocol.registerFileProtocol("laji-plugin", (req, cb) => {
      const url = new URL(req.url);
      const rel = decodeURIComponent(url.pathname).replace(/^\//, "");
      if (url.hostname !== "com.nerve.dsh-notify") return cb({ error: -6 });
      const target = path.join(INSTALLED, rel);
      const ok = fs.existsSync(target);
      if (!ok) failures++;
      say("asset " + rel + " -> " + (ok ? "ok" : "MISSING"));
      cb({ path: target });
    });

    host = spawn(process.execPath, ["lib/host.mjs"], { cwd: PLUGIN_DIR, stdio: ["ignore", "pipe", "pipe"] });
    host.stderr.on("data", (d) => process.stdout.write("[host] " + d));
    await wait(1400);
    const runtime = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, "runtime.json"), "utf8"));

    const win = new BrowserWindow({ width: 1000, height: 820, show: false, backgroundColor: "#1e1e1e" });
    win.webContents.on("console-message", (event) => {
      const text = event && event.message;
      if (text && String(text).indexOf("[fetch]") === 0) return;
      if (text) say("page: " + text);
    });
    await win.loadFile(HARNESS, { query: { port: String(runtime.port) } });
    await wait(700);
    win.webContents.executeJavaScript("window.__setup()").then(
      (v) => say("setup: " + v),
      (e) => say("setup rejected: " + (e && e.message ? e.message : e)),
    );
    for (let i = 0; i < 24; i++) {
      await wait(500);
      if (await win.webContents.executeJavaScript('!!document.querySelector("#dsh-notify-panel .np-chan-head")')) break;
    }
    await wait(300);

    fs.mkdirSync(OUT, { recursive: true });
    // 渠道顺序：wecom → mail → sms（见 CHANNEL_META）
    for (const [idx, label] of [
      [0, "wecom"],
      [1, "mail"],
      [2, "sms"],
    ]) {
      await win.webContents.executeJavaScript(
        'document.querySelectorAll("#dsh-notify-panel .np-chan-head")[' + idx + "].click(); true;",
      );
      await wait(900);
      const probe = await win.webContents.executeJavaScript(`(() => {
        const m = document.getElementById("dsh-notify-modal");
        if (!m) return { modal: false };
        const btns = Array.from(m.querySelectorAll(".editor-toolbar button")).map((b) => b.textContent.trim());
        return {
          modal: true,
          editors: m.querySelectorAll(".EasyMDEContainer").length,
          textareas: m.querySelectorAll("textarea").length,
          btns,
          preview: !!m.querySelector(".npm-preview"),
          frame: !!m.querySelector(".npm-frame"),
        };
      })()`);
      say(label + " probe: " + JSON.stringify(probe));

      // 滚到底：EasyMDE 是异步升级的，内容高度会变，所以要滚两次。
      const scroll = async () =>
        win.webContents.executeJavaScript(
          'var b=document.querySelector("#dsh-notify-modal .npm-body"); b.scrollTop=b.scrollHeight; true;',
        );
      await scroll();
      await wait(300);
      await scroll();
      await wait(300);
      const png = path.join(OUT, "plugin-modal-" + label + ".png");
      fs.writeFileSync(png, (await win.webContents.capturePage()).toPNG());
      say("saved " + path.basename(png));

      if (probe.editors) {
        const toggle = await win.webContents.executeJavaScript(`(() => {
          const pick = () => document.querySelector("#dsh-notify-modal .CodeMirror").CodeMirror;
          const btn = () => document.querySelector("#dsh-notify-modal .editor-toolbar button");
          pick().setValue("测试一行");
          pick().setSelection({ line: 0, ch: 0 }, { line: 0, ch: 4 });
          btn().click();
          const once = pick().getValue();
          pick().setSelection({ line: 0, ch: 0 }, { line: 0, ch: pick().getValue().length });
          btn().click();
          return { once, twice: pick().getValue() };
        })()`);
        const pass = toggle.once === "**测试一行**" && toggle.twice === "测试一行";
        if (!pass) failures++;
        say(label + " toggle " + (pass ? "PASS" : "FAIL") + ": " + JSON.stringify(toggle));
      }

      await win.webContents.executeJavaScript('document.querySelector("#dsh-notify-modal .npm-x").click(); true;');
      await wait(400);
    }
  } catch (err) {
    failures++;
    say("failed: " + (err && err.stack ? err.stack : err));
  }
  if (host) host.kill();
  await wait(300);
  for (const p of [path.join(PLUGIN_DIR, "state"), path.join(PLUGIN_DIR, "runtime.json")]) {
    if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true });
  }
  say(failures === 0 ? "RESULT ok" : "RESULT " + failures + " problem(s)");
  app.quit();
});
