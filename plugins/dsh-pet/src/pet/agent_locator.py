"""Laji 到底装在哪：先问系统，别让桌宠满桌面乱找。

为什么单独一个模块：``agent_bridge`` 管的是"怎么把 URL 递进去"（协议注册、dev 环境、
deep link），而"它在哪个盘哪个目录"是另一件事。两者混在一起之后，``_install_roots()``
只能穷举安装器默认落点，遇到自定义路径（比如本机的 ``D:\\tmp\\LajiAgent``）就判成没装。

定位顺序（每级都是毫秒级、纯读，不弹窗、不起进程）：

1. **开始菜单快捷方式** —— 安装器一定会建，指向真实的 exe；自定义路径也能覆盖。
2. **安装根目录** —— 老版本/绿色版没建快捷方式时的兜底。
3. **运行中的进程** —— 收在托盘时进程还在，直接读它的 exe。

拿不到才算"没装"。搜 Windows 搜索框是最后手段，且要驱动 XAML 输入，不稳，默认不做。
"""

from __future__ import annotations

import glob
import logging
import os
import re
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: 安装版的 exe 名（electron-builder 默认带空格）。
_EXE_NAMES = ("Laji Agent.exe", "LajiAgent.exe", "Laji.exe", "laji.exe")

#: 这些进程名不是"用户要打开的那个 Laji"：dev 镜像的裸 electron、桌宠自己。
_NOT_TARGET = ("electron.exe", "laji-pet.exe", "dsh-pet.exe")

#: lnk 是二进制，但 target 在 LinkInfo 里是明文（ASCII 或 UTF-16）。
_EXE_IN_LNK = re.compile(r"[A-Za-z]:\\[^\x00\"<>|\r\n]{2,160}?\.exe", re.IGNORECASE)


@dataclass(frozen=True)
class Target:
    """一条能拉起 Laji 的实证路径。"""

    exe: str
    args: str = ""
    source: str = ""          # start_menu / install_root / running_process
    dev: bool = False         # True = dev 镜像的裸 electron，要补 app 目录与环境

    def command(self, placeholder: str = "%1") -> str:
        parts = [f'"{self.exe}"']
        if self.args:
            parts.append(self.args)
        if placeholder:
            parts.append(f'"{placeholder}"')
        return " ".join(parts)


def start_menu_links() -> list[str]:
    """开始菜单里所有含 ``laji`` 的快捷方式（用户级优先）。"""
    roots = [
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("ProgramData", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
    ]
    found: list[str] = []
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for path in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            if "laji" in os.path.basename(path).lower():
                found.append(path)
    return found


def exe_from_link(lnk_path: str) -> str:
    """从 .lnk 里读出它指向的 exe（读不到返回空串）。

    不走 COM：``WScript.Shell`` 会被安全软件判成脚本宿主，``Shell.Application`` 取
    target 的属性名各版本不一致（实测 IShellLinkDual2 上没有 ``GetPath``）。lnk 的
    LinkInfo 段本身就是明文路径，扫一遍再校验文件存在，比调 COM 快两个数量级。
    """
    try:
        with open(lnk_path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return ""
    for encoding in ("mbcs", "utf-16-le"):
        try:
            text = raw.decode(encoding, "ignore")
        except LookupError:
            continue
        for hit in _EXE_IN_LNK.findall(text):
            candidate = hit.split("\x1e")[0].strip()
            if os.path.isfile(candidate):
                return candidate
    return ""


def _from_start_menu() -> Target | None:
    for lnk in start_menu_links():
        exe = exe_from_link(lnk)
        if not exe:
            continue
        log.debug("agent_locator: 开始菜单命中 %s → %s", lnk, exe)
        return Target(exe=exe, source="start_menu", dev=_looks_dev(exe))
    return None


def _install_roots() -> list[str]:
    """安装器可能的落盘根目录（用户级 → 机器级）。"""
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    bases = [
        os.path.join(local, "Programs") if local else "",
        os.path.join(roaming, "Programs") if roaming else "",
        local,
        os.environ.get("ProgramFiles", ""),
        os.environ.get("ProgramFiles(x86)", ""),
    ]
    roots: list[str] = []
    for base in bases:
        if not base:
            continue
        for name in ("LajiAgent", "Laji Agent", "laji-agent", "Laji", "laji"):
            roots.append(os.path.join(base, name))
    return roots


def _from_install_roots() -> Target | None:
    for root in _install_roots():
        for name in _EXE_NAMES:
            exe = os.path.join(root, name)
            if os.path.isfile(exe):
                log.debug("agent_locator: 安装目录命中 %s", exe)
                return Target(exe=exe, source="install_root", dev=_looks_dev(exe))
    return None


def _from_running() -> Target | None:
    """进程还在（收在托盘也一样）就能读出它的 exe。"""
    try:
        import psutil
    except Exception:
        return None
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = proc.info
            name = (info.get("name") or "").lower()
            if info.get("pid") == me or name in _NOT_TARGET:
                continue
            if "laji" not in name:
                continue
            exe = info.get("exe") or ""
            if exe and os.path.isfile(exe):
                return Target(exe=exe, args=_running_args(info.get("pid")),
                              source="running_process", dev=_looks_dev(exe))
        except Exception:
            continue
    return None


def _running_args(pid: int | None) -> str:
    """dev 镜像的裸 electron 必须带 app 目录，否则弹 "Unable to find Electron app"。"""
    if not pid:
        return ""
    try:
        import psutil

        cmdline = psutil.Process(pid).cmdline()
    except Exception:
        return ""
    if len(cmdline) < 2:
        return ""
    app_dir = cmdline[1]
    if os.path.isdir(app_dir) and os.path.isfile(os.path.join(app_dir, "package.json")):
        return f'"{app_dir}"'
    return ""


def _looks_dev(exe: str) -> bool:
    return os.path.join("node_modules", "electron", "dist") in exe.lower()


def find(use_cache: bool = True) -> Target | None:
    """按可信度找一条启动路径；找不到返回 None。"""
    global _cache
    now = time.monotonic()
    if use_cache and _cache and now - _cache[0] < 8.0:
        return _cache[1]

    target = _from_start_menu() or _from_install_roots()
    if target is None:
        target = _from_running()
    _cache = (now, target)
    return target


_cache: tuple[float, "Target | None"] | None = None


def invalidate() -> None:
    global _cache
    _cache = None
