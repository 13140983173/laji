// 面板回归截图：起 host → 离屏打开 harness → 走一遍真实 fetch 链路 → 截四张图。
//
//   node_modules\electron\dist\electron.exe packs\plugins\dsh-notify\test\capture-panel.cjs
//
// 输出到 docs/prototypes/assets/notify-plugin-settings/；跑完会删掉 runtime.json 与 state/，
// 免得把测试配置留在插件目录里。
const { app, BrowserWindow } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const PLUGIN_DIR = path.resolve(__dirname, "..");
// 仓库根：packs/plugins/<id> → 上三级。
const REPO = path.resolve(PLUGIN_DIR, "../../..");
const OUT = path.join(REPO, "docs/prototypes/assets/notify-plugin-settings");
const HARNESS = path.join(__dirname, "panel-harness.html");

app.disableHardwareAcceleration();
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const say = (msg) => process.stdout.write("[panel] " + msg + "\n");

process.on("unhandledRejection", (err) => say("unhandled: " + (err && err.stack ? err.stack : err)));

app.whenReady().then(async () => {
  let host = null;
  try {
    host = spawn(process.execPath, ["lib/host.mjs"], { cwd: PLUGIN_DIR, stdio: ["ignore", "pipe", "pipe"] });
    host.stderr.on("data", (d) => process.stdout.write("[host] " + d));
    await wait(1400);
    const runtime = JSON.parse(fs.readFileSync(path.join(PLUGIN_DIR, "runtime.json"), "utf8"));

    const win = new BrowserWindow({ width: 1000, height: 760, show: false, backgroundColor: "#1e1e1e" });
    await win.loadFile(HARNESS, { query: { port: String(runtime.port) } });
    await wait(600);
    await win.webContents.executeJavaScript("window.__setup()");

    fs.mkdirSync(OUT, { recursive: true });
    const shoot = async (name) => {
      fs.writeFileSync(path.join(OUT, name), (await win.webContents.capturePage()).toPNG());
      say("saved " + name);
    };

    await shoot("plugin-panel-channels.png");
    await win.webContents.executeJavaScript(
      'document.querySelectorAll("#dsh-notify-panel .np-chan-head")[2].click(); true;',
    );
    await wait(350);
    await shoot("plugin-panel-sms.png");
    await win.webContents.executeJavaScript('window.__tab("ev")');
    await wait(400);
    await shoot("plugin-panel-events.png");
    await win.webContents.executeJavaScript('window.__tab("log")');
    await wait(700);
    await shoot("plugin-panel-log.png");
    await win.webContents.executeJavaScript('document.querySelector("#dsh-notify-panel .np-x").click(); true;');
    await wait(350);
    // 入口不再由插件自己钉在右上角：关掉面板后页面右上角应该什么也不多。
    await shoot("plugin-panel-closed.png");
  } catch (err) {
    say("failed: " + (err && err.stack ? err.stack : err));
  }
  if (host) host.kill();
  await wait(300);
  for (const p of [path.join(PLUGIN_DIR, "state"), path.join(PLUGIN_DIR, "runtime.json")]) {
    if (fs.existsSync(p)) fs.rmSync(p, { recursive: true, force: true });
  }
  app.quit();
});
