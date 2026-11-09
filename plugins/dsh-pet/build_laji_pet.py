"""把 packs/plugins/dsh-pet/src（上游 MIT 快照）打成 Laji 自己的桌宠：bin/laji-pet/laji-pet.exe

构建参数（收哪些包、哪些数据、排除什么）**只有一处真相**：``src/laji-pet.spec``。
这个脚本只负责外部动作——停旧实例、写变体标识、调 PyInstaller、报产物摘要。

为什么不再在这里拼 ``--collect-all`` / ``--add-data``：那样会有两份清单，而桌宠直连
laji daemon 需要的 ``grpc`` / ``google.protobuf`` / ``pet/agent_link/_proto`` 正是最容易
只在其中一份里出现的条目。漏了不会报错，只会让冻结包里的 agent_link 变 unavailable，
气泡成一个发不出消息的空窗——实测过：``--collect-all google.protobuf`` 会把
``_internal/google/_upb`` 建成空目录，upb 的 C 扩展收不进来。

与上游 scripts/build_onedir.ps1 的区别（有意为之，不是遗漏）：

* 产物名 ``laji-pet``、变体标识 ``laji`` → 配置目录
  ``%APPDATA%\\dsh-pet-standalone-laji``，不与上游发行版的 ``-webm-chat``
  抢同一份 config.json。
* 不跑上游那些发布前硬门（frameseq 完整性、presentmon、rapidocr 模型、TTS 环境）。
  那些门要求构建机装齐 rapidocr/onnxruntime/cv2/edge-tts/winrt 与派生的帧序列；
  本仓只交付「桌宠本体 + Laji 联动」，OCR/在线 TTS 缺失时上游自身会降级并置灰。
* 因此 spec 不收集 rapidocr / cv2 / numpy / edge_tts / aiofiles。**QtMultimedia 是例外**：
  语音报时/「立即试听」的播放出口只有 QMediaPlayer+QAudioOutput 一条路，缺它合成成功
  也一声不响（2026-10-31 实机定位），故 spec 显式收集它和多媒体插件；构建机须装
  PySide6-Addons（见 requirements.txt）。点击音效另有 winmm 直放后端可兑底。

用法::

    <venv>\\Scripts\\python.exe packs\\plugins\\dsh-pet\\build_laji_pet.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
SRC = PLUGIN_ROOT / "src"
DIST = PLUGIN_ROOT / "bin"
WORK = PLUGIN_ROOT / ".build"
NAME = "laji-pet"
VARIANT = "laji"
# 新装默认启用集合：'baseline' = 全部功能模块开（否则 chat 模块关着时
# 右键菜单里「AI 对话」「和她说话」整项消失）；'pure' = 纯核心；也可给
# 模块 id 元组只开指定几项。由 pet/feature_activation.py 读取。
NEW_INSTALL_ENABLED = "baseline"
SPEC = SRC / "laji-pet.spec"


def stop_stale_instances() -> None:
    """旧实例会锁住 _internal 里的 DLL；只停本变体与上游变体，不碰别的进程。"""
    for image in ("laji-pet.exe", "dsh-pet-standalone-webm-chat.exe"):
        subprocess.run(
            ["taskkill", "/IM", image, "/F"],
            capture_output=True,
            check=False,
        )


def main() -> int:
    if not (SRC / "packaging/pet_entry.py").is_file():
        print(f"src tree incomplete: {SRC}", file=sys.stderr)
        return 1
    if not SPEC.is_file():
        print(f"spec missing: {SPEC}", file=sys.stderr)
        return 1

    stop_stale_instances()
    (SRC / "packaging/build_variant.py").write_text(
        f"VARIANT = {VARIANT!r}\nNEW_INSTALL_ENABLED = {NEW_INSTALL_ENABLED!r}\n",
        encoding="utf-8",
    )

    # spec 里的 datas / Analysis 路径都是相对 SRC 的，所以 cwd 必须是 SRC。
    args: list[str] = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        SPEC.name,
    ]
    print("pyinstaller:", " ".join(args), flush=True)
    proc = subprocess.run(args, cwd=str(SRC), check=False)
    if proc.returncode != 0:
        print(f"PyInstaller failed: {proc.returncode}", file=sys.stderr)
        return proc.returncode

    exe = DIST / NAME / f"{NAME}.exe"
    if not exe.is_file():
        print(f"build output missing: {exe}", file=sys.stderr)
        return 1
    total = sum(f.stat().st_size for f in (DIST / NAME).rglob("*") if f.is_file())
    print(f"built: {exe} ({total / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
