# -*- coding: utf-8 -*-
"""aboutme-pets 精灵图并行下载器（ghfast.top 加速，12 线程，断点续传式跳过已存在）"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(r"C:\Users\EDY\AppData\Local\Temp\aboutme-pets")
BASE = "https://ghfast.top/https://raw.githubusercontent.com/hunmer/aboutme-pets/main/"
PACKS = ["dsh1", "gpt", "claude", "gemini"]
WORKERS = 12


def jobs():
    out = []
    for pack in PACKS:
        # actions.json 优先，gemini 没有 actions.json 用 manifest.json
        meta_path = ROOT / f"{pack}-actions.json"
        if not meta_path.exists():
            meta_path = ROOT / f"{pack}-manifest.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for a in meta["animations"]:
            rel = a["sources"]["webp"]          # 形如 spritesheet/<名>.webp
            out.append((pack, a["id"], rel))
    return out


def fetch(pack, name, rel):
    dest = ROOT / "spritesheets" / pack / rel.split("/", 1)[1]
    if dest.exists() and dest.stat().st_size > 10000:
        return (pack, name, "skip", 0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = BASE + "pets/" + pack + "/" + urllib.parse.quote(rel)
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "laji-pet-assets"})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
            if len(data) < 10000:
                raise ValueError(f"too small: {len(data)}")
            tmp = dest.with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(dest)
            return (pack, name, "ok", len(data))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(1.5 * (attempt + 1))
    return (pack, name, f"FAIL: {last_err}", 0)


def main():
    all_jobs = jobs()
    print(f"total {len(all_jobs)} files", flush=True)
    ok = skip = fail = 0
    bytes_total = 0
    t0 = time.time()
    with ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(fetch, *j): j for j in all_jobs}
        for i, f in enumerate(as_completed(futs), 1):
            pack, name, status, size = f.result()
            if status == "ok":
                ok += 1
                bytes_total += size
            elif status == "skip":
                skip += 1
            else:
                fail += 1
                print(f"  {status} | {pack}/{name}", flush=True)
            if i % 25 == 0 or i == len(all_jobs):
                dt = time.time() - t0
                print(f"[{i}/{len(all_jobs)}] ok={ok} skip={skip} fail={fail} "
                      f"{bytes_total/1e6:.0f}MB {dt:.0f}s {bytes_total/max(dt,1)/1e3:.0f}KB/s",
                      flush=True)
    print(f"DONE ok={ok} skip={skip} fail={fail}", flush=True)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
