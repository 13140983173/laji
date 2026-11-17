"""把打好的 onedir 产物封装成插件市场能直接装的 Release 资产。

市场里 `com.nerve.laji-pet` 走 `install.type = "release"`：下载 zip 解压即插件目录，
所以资产内就是插件的最终布局，不需要再经过仓库转换：

    laji.plugin.toml          # 插件清单（与安装后的目录同一份）
    bin/laji-pet/laji-pet.exe # onedir 成品，_internal 必须与 exe 同级
    bin/laji-pet/_internal/**

宿主启动时按 `<plugin>/bin` 探到 `laji-pet.exe` 并填好 `LAJI_PET_EXE`，
清单里的 `${env:LAJI_PET_EXE}` 因此开箱即用。

用法::

    python plugin-registry/plugins/laji-pet/pack_release.py
    python plugin-registry/plugins/laji-pet/pack_release.py --bin <其他 onedir 目录>

产物 `dist/laji-pet-<version>-win-x64.zip`，末尾会打印 sha256 和 index.json 片段。
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent
MANIFEST = PLUGIN_ROOT / "laji.plugin.toml"
DEFAULT_BIN = PLUGIN_ROOT / "bin" / "laji-pet"
DIST = PLUGIN_ROOT / "dist"
EXE_NAME = "laji-pet.exe"
# 素材是上万个 png，deflate 换不来体积只换来等待；dll/exe 还能压一点，取低档。
COMPRESS_LEVEL = 3


def manifest_version(manifest: Path) -> str:
    text = manifest.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"no [plugin] version in {manifest}")
    return match.group(1)


def add_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    # 只跳过调试符号。**不要按 ".zip" 过滤**：PyInstaller 的 `_internal/base_library.zip`
    # 就是 .zip，而它是 bootloader 初始化内嵌解释器的必需品——1.1.0 就是把这个后缀
    # 当垃圾一起滤掉，市场里那个包一启动就弹 "Failed to start embedded python
    # interpreter!"。onedir 产物目录里没有其它 .zip 需要排掉。
    if path.suffix.lower() == ".pdb":
        return
    zf.write(path, arcname, compress_type=zipfile.ZIP_DEFLATED, compresslevel=COMPRESS_LEVEL)


def build(bin_dir: Path, version: str, platform: str, out: Path) -> int:
    exe = bin_dir / EXE_NAME
    if not exe.is_file():
        print(f"onedir product missing: {exe}\n先跑 build_laji_pet.py", file=sys.stderr)
        return 1
    if not (bin_dir / "_internal").is_dir():
        # 单发 exe 会启动即崩，宁可在这里拦下。
        print(f"_internal missing next to {exe}: onedir 整个目录都要带", file=sys.stderr)
        return 1
    # PyInstaller 的 bootloader 靠这两样初始化内嵌解释器。少了任意一样，exe 一启动
    # 就弹 "Failed to start embedded python interpreter!"，而市场、宿主、这个脚本
    # 原先都只看 `_internal` 在不在——1.1.0 就是这样带着一个跑不起来的包发出去的。
    internal = bin_dir / "_internal"
    missing: list[str] = []
    if not (internal / "base_library.zip").is_file():
        missing.append("_internal/base_library.zip")
    if not any(p.is_file() and p.stat().st_size > 0 for p in internal.glob("python3*.dll")):
        missing.append("_internal/python3*.dll")
    if missing:
        print(
            "onedir 产物不完整，拒给往外发：\n  " + "\n  ".join(missing) +
            f"\n先确认 {internal} 没被安全软件清过，再重跑 build_laji_pet.py",
            file=sys.stderr,
        )
        return 1

    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", allowZip64=True) as zf:
        add_file(zf, MANIFEST, "laji.plugin.toml")
        count += 1
        # 桌宠管家面板（lib/ 由 xiaoxiao-pet-manager 并入）：纯 JS，无需重编 exe。
        mgmt_dir = PLUGIN_ROOT / "mgmt-lib"
        if mgmt_dir.is_dir():
            for path in sorted(mgmt_dir.iterdir()):
                if path.is_file():
                    add_file(zf, path, f"lib/{path.name}")
                    count += 1
        for path in sorted(bin_dir.rglob("*")):
            if not path.is_file():
                continue
            add_file(zf, path, f"bin/laji-pet/{path.relative_to(bin_dir).as_posix()}")
            count += 1
        # 角色包（catgirl-gemini / whale-maid-*）：装后落在
        # <pluginsRoot>/<id>/<ver>/characters/，由 pet 的 external_character_dirs
        # 第 4 优先级自动发现，右键菜单即可切换。
        characters_dir = PLUGIN_ROOT / "characters"
        if characters_dir.is_dir():
            for path in sorted(characters_dir.rglob("*")):
                if not path.is_file():
                    continue
                add_file(zf, path, f"characters/{path.relative_to(characters_dir).as_posix()}")
                count += 1
    size = out.stat().st_size
    # 回读真实产物，而不是只信源目录：源目录完整不代表 zip 里也在。
    with zipfile.ZipFile(out) as zf:
        names = set(zf.namelist())
        required = [
            "laji.plugin.toml",
            "lib/client.js",
            "lib/host.mjs",
            f"bin/laji-pet/{EXE_NAME}",
            "bin/laji-pet/_internal/base_library.zip",
        ]
        problems = [n for n in required if n not in names or zf.getinfo(n).file_size == 0]
        if not any(re.fullmatch(r"bin/laji-pet/_internal/python3\d*\.dll", n) for n in names):
            problems.append("bin/laji-pet/_internal/python3*.dll")
    if problems:
        out.unlink(missing_ok=True)
        print(
            "打出来的 zip 缺运行时必需品，已删除，不发：\n  " + "\n  ".join(problems),
            file=sys.stderr,
        )
        return 1
    digest = hashlib.sha256()
    with out.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    hexdigest = digest.hexdigest()
    print(f"packed: {out}")
    print(f"  files   : {count}")
    print(f"  size    : {size / 1024 / 1024:.1f} MB")
    print(f"  sha256  : {hexdigest}")
    print(
        "\nindex.json install 片段：\n"
        "  {\n"
        '    "type": "release",\n'
        '    "owner": "13140983173",\n'
        '    "repo": "laji",\n'
        f'    "tag": "laji-pet-v{version}",\n'
        f'    "asset": "{out.name}",\n'
        f'    "sha256": "{hexdigest}"\n'
        "  }"
    )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="打包 laji-pet 的 Release 资产 zip")
    ap.add_argument("--bin", type=Path, default=DEFAULT_BIN, help="onedir 产物目录（默认 bin/laji-pet）")
    ap.add_argument("--version", default=None, help="默认取 laji.plugin.toml 里的 version")
    ap.add_argument("--platform", default="win-x64", help="资产名里的平台后缀")
    ap.add_argument("--out", type=Path, default=None, help="输出 zip（默认 dist/laji-pet-<ver>-<platform>.zip）")
    args = ap.parse_args()

    version = args.version or manifest_version(MANIFEST)
    out = args.out or DIST / f"laji-pet-{version}-{args.platform}.zip"
    return build(args.bin, version, args.platform, out)


if __name__ == "__main__":
    raise SystemExit(main())
