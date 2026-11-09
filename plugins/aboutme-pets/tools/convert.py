# -*- coding: utf-8 -*-
"""aboutme-pets 精灵图 → 透明 WebM 批量转换器（v2：直落 Laji 插件包）

输入：C:\\Users\\EDY\\AppData\\Local\\Temp\\aboutme-pets\\spritesheets\\<pack>\\*.webp
     各包 actions.json / manifest.json 的 spritesheet 元数据（640×360、8列、12fps）
输出：D:\\workspace\\waf\\Nerve-agent\\Laji\\packs\\plugins\\aboutme-pets\\
     characters\\<角色ID>\\videos\\<pet分类>\\<动作名>.webm
     每个角色包附 manifest.json（显示名）。

分类映射（pet 播放器六分类 ← aboutme 九分类）：
  待机类名称/分类 → idle；点击回应 → click；拖拽 → drag；移动 → move；其余 → random
用法：python convert.py [--packs dsh1,gpt,claude,gemini] [--jobs 4]
"""
import argparse
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import imageio_ffmpeg

SRC = Path(r"C:\Users\EDY\AppData\Local\Temp\aboutme-pets")
OUT = Path(r"D:\workspace\waf\Nerve-agent\Laji\packs\plugins\aboutme-pets\characters")
FF = imageio_ffmpeg.get_ffmpeg_exe()

CHARS = {
    "dsh1":   ("whale-maid-extra",  "蓝毛小女仆·新动作包"),
    "gpt":    ("whale-maid-gpt",    "蓝毛小女仆·GPT批次"),
    "claude": ("whale-maid-claude", "蓝毛小女仆·Claude批次"),
    "gemini": ("catgirl-gemini",    "猫耳娘·Gemini批次"),
}
IDLE_KEYS = ("待机", "呼吸", "发呆", "打瞌睡", "晃神", "小憩", "沉眠", "假寐")


def load_meta(pack: str) -> list[dict]:
    for cand in (SRC / f"{pack}-actions.json", SRC / f"{pack}-manifest.json"):
        if cand.exists():
            return json.loads(cand.read_text(encoding="utf-8"))["animations"]
    raise FileNotFoundError(pack)


def pet_category(cat: str, name: str) -> str:
    if cat == "待机" or any(k in name for k in IDLE_KEYS):
        return "idle"
    if cat == "点击回应" or "回应" in name:
        return "click"
    if cat == "拖拽":
        return "drag"
    if cat == "移动":
        return "move"
    return "random"


def convert_one(pack: str, char_id: str, anim: dict) -> tuple[str, str]:
    name = anim["id"]
    src = SRC / "spritesheets" / pack / f"{name}.webp"
    cat = pet_category(anim.get("category", ""), name)
    dest = OUT / char_id / "videos" / cat / f"{name}.webm"
    if dest.exists() and dest.stat().st_size > 5000:
        return (name, "skip")
    if not src.exists():
        return (name, "MISSING-SRC")

    sp = anim["spritesheet"]
    fw, fh = sp["frameWidth"], sp["frameHeight"]
    cols, count, fps = sp["columns"], sp["frameCount"], sp["fps"]

    from PIL import Image
    img = Image.open(src).convert("RGBA")
    frames = []
    for i in range(count):
        x = (i % cols) * fw
        y = (i // cols) * fh
        frames.append(img.crop((x, y, x + fw, y + fh)))

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        FF, "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", "rgba",
        "-s", f"{fw}x{fh}", "-r", str(fps), "-i", "-",
        "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
        "-deadline", "realtime", "-cpu-used", "8", "-row-mt", "1",
        "-b:v", "0", "-crf", "20",
        str(dest),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        for fr in frames:
            proc.stdin.write(fr.tobytes())
    finally:
        proc.stdin.close()
        rc = proc.wait()
    if rc != 0 or not dest.exists() or dest.stat().st_size < 5000:
        dest.unlink(missing_ok=True)
        return (name, f"FAIL rc={rc}")
    return (name, "ok")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--packs", default="dsh1,gpt,claude,gemini")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    fails = []
    t0 = time.time()
    for pack in args.packs.split(","):
        char_id, disp = CHARS[pack]
        anims = load_meta(pack)
        # manifest.json（显示名；body_box 缺省回退整画布行为）
        mdir = OUT / char_id
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "manifest.json").write_text(
            json.dumps({"name": disp, "source": f"hunmer/aboutme-pets {pack}"},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{pack}] {len(anims)} clips → {char_id}", flush=True)
        done = 0
        with ThreadPoolExecutor(args.jobs) as ex:
            futs = {ex.submit(convert_one, pack, char_id, a): a for a in anims}
            for f in as_completed(futs):
                name, status = f.result()
                done += 1
                if status not in ("ok", "skip"):
                    fails.append((pack, name, status))
                    print(f"  {status} | {pack}/{name}", flush=True)
                if done % 20 == 0 or done == len(anims):
                    print(f"[{pack}] {done}/{len(anims)} fails={len(fails)} "
                          f"{time.time()-t0:.0f}s", flush=True)
    print(f"CONVERT-DONE fails={len(fails)}", flush=True)
    for pack, name, status in fails:
        print(f"  FAIL {pack}/{name}: {status}", flush=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
