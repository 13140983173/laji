// 校验 pluginhub/index.json 与各插件 laji.plugin.toml 的 id / 版本一致。
// 用法: node tools/verify-index.mjs
import * as fs from "node:fs";
import * as path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const doc = JSON.parse(fs.readFileSync(path.join(root, "pluginhub/index.json"), "utf8"));
const bad = [];
const stray = [];

for (const p of doc.plugins) {
  const dir = path.join(root, p.install.path);
  const mf = path.join(dir, "laji.plugin.toml");
  if (!fs.existsSync(mf)) {
    bad.push(`${p.id}: 缺目录 ${p.install.path}`);
    continue;
  }
  const t = fs.readFileSync(mf, "utf8");
  const id = (t.match(/^id = "(.+)"/m) || [])[1];
  const version = (t.match(/^version = "(.+)"/m) || [])[1];
  if (id !== p.id) bad.push(`${p.id}: toml id = ${id}`);
  if (version !== p.version) bad.push(`${p.id}: 版本不一致 toml=${version} index=${p.version}`);

  for (const f of fs.readdirSync(dir, { recursive: true })) {
    const abs = path.join(dir, String(f));
    if (!fs.statSync(abs).isFile()) continue;
    if (/\.(bak|prev|orig|tmp)$/.test(String(f)) || /\.(bak|prev)-/.test(String(f))) {
      stray.push(path.relative(root, abs));
    }
  }
}

console.log(`index 条目数: ${doc.plugins.length}`);
console.log(bad.length ? `问题:\n${bad.join("\n")}` : "OK: 全部 id / 版本一致");
if (stray.length) console.log(`疑似临时/备份文件:\n${stray.join("\n")}`);
process.exit(bad.length ? 1 : 0);
