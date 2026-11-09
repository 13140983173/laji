"""把桌宠的一次「对话」请求交给本机的 Laji Agent。

为什么走这条线：桌宠自带的聊天窗要用户自己配 provider/API Key，没配好时点
「AI 对话」只会得到一个发不出消息的空窗（用户口径是"点了没反应"）。Laji Agent
已经装在这台机器上、`laji-agent://` 协议也注册过，把焦点和问题递过去，比在桌宠
里再造一套对话 UI 便宜得多，而且回答用的是用户已经配好的模型。

协议不可用（Laji 没装 / 从没跑过一次注册流程）时 `openUrl` 返回 False，调用方
照旧打开自带聊天窗 —— 入口不会变成死项。
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from urllib.parse import urlencode

log = logging.getLogger("pet.agent_bridge")

#: Laji Agent 注册的协议（见 ``packages/laji-bridge-client/src/schemes.ts``）。
SCHEME = "laji-agent"
ASK_HOST = "ask"
# ``from=pet`` 的来源标记，见 :func:`ask_url`。
ASK_SOURCE = "pet"

#: 当前桌宠的角色 id 的提供者（由 app 启动时挂上；没挂上就当没有）。
#: 不在这里直接读配置：agent_bridge 被托盘/菜单/演出多处调用，那些地方手上没有
#: config，而每次重新构一个 ``Config()`` 读一遍设置只为了拼一个目录名不划算。
_pet_id_provider = None


def set_pet_id_provider(provider) -> None:
    """注册「当前桌宠角色 id」的取法（app 启动时调，可重复调）。"""
    global _pet_id_provider
    _pet_id_provider = provider


def current_pet_id() -> str:
    """当前桌宠的角色 id；没注册或读不出来时返回空串（Laji 会退回共用的 Pet）。"""
    if _pet_id_provider is None:
        return ""
    try:
        return str(_pet_id_provider() or "").strip()
    except Exception:
        log.debug("agent bridge: 读不到当前角色 id", exc_info=True)
        return ""

#: 打包版是 ``Laji.exe "%1"``；开发镜像是 ``LajiAgent.exe "<appDir>" "%1"``。
#: 后者少了中间那个应用目录，Electron 就把 URL 当成 app 路径，弹出
#: “Unable to find Electron app …——拉起它的进程当场报错，连“交给已运行实例”
#: 这一步都走不到（用户看到的就是点了一下、闪一下、报错框）。所以光看进程在
#: 不在跑不够，还得确认注册命令本身是自洽的。
_LAJI_PROCESS_NAMES = {"laji", "lajiagent", "laji-agent"}

#: 只有 ``node_modules\electron\dist`` 里的 electron 需要显式 app 目录。
_DEV_ELECTRON_MARK = os.path.join("node_modules", "electron", "dist").lower()

#: 安装器落盘的可执行文件名；新装的是 ``Laji Agent.exe``，老包可能是另外两个。
_INSTALL_EXE_NAMES = ("Laji Agent.exe", "LajiAgent.exe", "Laji.exe", "laji.exe")


def protocol_command() -> str:
    """注册表里 ``laji-agent://`` 的打开命令；读不到时返回空串（调用方乐观放行）。"""
    if sys.platform != "win32":
        return ""
    try:
        import winreg
    except Exception:  # pragma: no cover - 非 Windows 打包
        return ""
    key = r"Software\Classes\{}\shell\open\command".format(SCHEME)
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(root, key) as handle:
                value, _ = winreg.QueryValueEx(handle, "")
        except OSError:
            continue
        return str(value or "").strip()
    return ""


def registration_ok(command: str) -> bool:
    """注册命令能否真的把 URL 送进 Laji（而不是被 Electron 当成 app 路径）。"""
    if not command or "%1" not in command:
        return False
    quoted = re.findall(r'"([^"]+)"', command.replace('"%1"', ""))
    if not quoted or not os.path.exists(quoted[0]):
        return False
    if _DEV_ELECTRON_MARK not in quoted[0].lower():
        return True
    for token in quoted[1:]:
        try:
            if os.path.isfile(os.path.join(token, "package.json")):
                return True
        except OSError:  # pragma: no cover - 路径非法时按不可用处理
            continue
    return False


def laji_running() -> bool:
    """Laji Agent 主进程是否在跑；探测本身不可用时乐观放行（宁可不拦）。"""
    try:
        import psutil
    except Exception:  # pragma: no cover - psutil 是打包依赖，缺失就跳过检测
        return True
    try:
        for proc in psutil.process_iter(["name"]):
            name = (proc.info.get("name") or "").lower()
            if name.removesuffix(".exe") in _LAJI_PROCESS_NAMES:
                return True
    except Exception:
        return True
    return False


def ask_url(text: str = "", run_id: str = "", workspace: str = "", pet: str | None = None) -> str:
    """``laji-agent://ask?text=...&from=pet&pet=<角色>``。

    ``text`` 为空表示只唤起 + 聚焦输入框、不预填（用户想自己开口问）；
    非空则整段落进输入框，**不自动发送**，由用户在 Laji 里确认。

    ``from=pet`` 告诉 Laji 这条请求来自桌宠：它没有自己的工程，会话要落在内置
    Pet 工作区下属于这只桌宠的那一格（侧栏分组名就是她的名字），而不是掉进用户
    当前打开的项目。``pet`` 是那只桌宠的角色 id，Laji 用它拼目录 ``Pet/<id>``；
    不带就只能退回共用的 ``Pet``。

    ``workspace`` 只在指明「打开别人那条会话」时才给：那条 run 属于某个项目工作区，
    落在 Pet 目录下就打不开了。
    """
    params = {"text": text} if text else {}
    params["from"] = ASK_SOURCE
    pet_id = current_pet_id() if pet is None else str(pet or "").strip()
    if pet_id:
        # 目录归属：Laji 侧据此把工作区落在 Pet/<角色>，侧栏显示这只桌宠的名字。
        params["pet"] = pet_id
    if run_id:
        # 带上会话：Laji 收到后直接打开那一轮所在的聊天框，而不是一个空白新会话。
        params["run"] = run_id
    if workspace:
        params["workspace"] = workspace
    return f"{SCHEME}://{ASK_HOST}?" + urlencode(params)


def open_laji_ask(
    text: str = "", run_id: str = "", workspace: str = "", pet: str | None = None
) -> bool:
    """把 ``text`` 交给 Laji Agent；返回是否真的交给了系统（False → 调用方回退）。"""
    return open_laji(text, run_id=run_id, workspace=workspace, pet=pet)


def _is_laji_code(command: str) -> bool:
    """注册命令指向的是 Laji Code（VS Code 壳）还是真正的 Laji Agent。"""
    return "laji code.exe" in command.lower()


def _is_dev_command(command: str) -> bool:
    """命令用的是 dev 镜像里的裸 electron（要靠 ``NERVE_DEV_ROOT`` 那套 env）。"""
    return _DEV_ELECTRON_MARK in command.lower()


def _registration_usable(command: str) -> bool:
    """系统协议处理器能不能把 URL 送进 Laji Agent 本体。"""
    if not command:
        return False
    return registration_ok(command) and not _is_laji_code(command)


def _command_exe(command: str) -> str:
    """命令模板里的可执行文件路径（第一段）；拆不动返回空串。"""
    try:
        import shlex

        parts = [part.strip('"') for part in shlex.split(command, posix=False)]
    except Exception:
        return ""
    return parts[0] if parts else ""


def _open_url_is_safe(command: str) -> bool:
    """交给系统协议处理器是否会真的打开一个程序。

    注册项空、或它的可执行文件根本不存在时，``ShellExecute`` 会弹“找不到应用”类
    对话框，比“点了没反应”更难看——那两种情形留给调用方回退。
    """
    if not command:
        return False
    exe = _command_exe(command)
    if not exe or not os.path.isfile(exe):
        return False
    return _is_laji_code(command) or registration_ok(command)


DEV_SERVER_PORT = 5174

# socket 探测在 Windows 上是**等超时**（关闭的端口不回 RST），实测单次 ~276ms；
# 「打工」每次点击都会问一次 dev server 在不在，缓存 5 秒够用且不必每次都等。
DEV_SERVER_CACHE_SECONDS = 5.0
_DEV_SERVER_CACHE: dict = {"key": None, "at": 0.0, "ok": False}


def _dev_root() -> str:
    """dev 镜像根目录（``NERVE_DEV_ROOT`` 优先，否则 ``%%LOCALAPPDATA%%\\laji-dev``）。"""
    if sys.platform != "win32":
        return ""
    root = os.environ.get("NERVE_DEV_ROOT")
    if root:
        return root
    local = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(local, "laji-dev") if local else ""


def dev_desktop_command() -> str:
    """dev 镜像里 Laji Agent 的直接入口（``LajiAgent.exe <appDir> "%1"``）。

    为什么要这一份：dev 的协议处理器被改指给了 Laji Code，靠 ``laji-agent://``
    只会打开那个 VS Code 壳；而 Electron 的单实例转交只需要「可执行文件 + 应用
    目录 + URL」三件东西，自己拼就能交给已运行的主进程。
    """
    root = _dev_root()
    if not root:
        return ""
    exe = os.path.join(root, "node_modules", "electron", "dist", "LajiAgent.exe")
    app_dir = os.path.join(root, "apps", "laji-agent")
    if not os.path.isfile(exe):
        return ""
    if not os.path.isfile(os.path.join(app_dir, "package.json")):
        return ""
    return f'"{exe}" "{app_dir}" "%1"'


def _install_roots() -> list[str]:
    """安装器可能的落盘根目录（新→老、用户级→机器级）。"""
    local = os.environ.get("LOCALAPPDATA", "")
    roaming = os.environ.get("APPDATA", "")
    roots: list[str] = []
    for base in (os.path.join(local, "Programs") if local else "",
                 os.path.join(roaming, "Programs") if roaming else "",
                 local,
                 os.environ.get("ProgramFiles", ""),
                 os.environ.get("ProgramFiles(x86)", "")):
        if not base:
            continue
        # "LajiAgent" 是 electron-builder 安装器（apps/laji-agent/build/installer.nsh
        # 的 customInit）写死的默认落点，没有空格——装完的包就在这一层。少了它，
        # 默认安装/静默安装之后「打工」会判定成没装，白白又装一份到旧路径。
        for name in ("LajiAgent", "Laji Agent", "laji-agent", "Laji", "laji"):
            roots.append(os.path.join(base, name))
    return roots


def installed_desktop_command() -> str:
    """正式安装版的直接入口（``"<exe>" "%1"``）；找不到返回空串。

    为什么要一份不依赖注册表的入口：用户只拷了桌宠包、或用 dev 脚本把那项注册改
    成了不自洽的形状时，``laji-agent://`` 就再也拉不起 Laji——而「打工」要的是
    「没开就打开它」。按安装器默认落点直接投递比修注册表稳。

    先问 ``agent_locator``：它读开始菜单快捷方式，因此**自定义安装路径**（不在
    任何默认根目录下，比如本机的 ``D:\\tmp\\LajiAgent``）也能命中；读不到再退回
    穷举默认落点。
    """
    from . import agent_locator

    target = agent_locator.find()
    if target is not None and not target.dev:
        return target.command()
    for root in _install_roots():
        for name in _INSTALL_EXE_NAMES:
            exe = os.path.join(root, name)
            if os.path.isfile(exe):
                return f'"{exe}" "%1"'
        try:
            children = sorted(os.listdir(root))
        except OSError:
            continue
        for child in children:
            # 有些安装包把 exe 塞进版本子目录（``Laji Agent\app-1.2.3\``）。
            nested = os.path.join(root, child)
            if not os.path.isdir(nested):
                continue
            for name in _INSTALL_EXE_NAMES:
                exe = os.path.join(nested, name)
                if os.path.isfile(exe):
                    return f'"{exe}" "%1"'
    return ""


def direct_commands() -> list[tuple[str, bool]]:
    """可直投的入口，按可信度排序：``(命令模板, 是否 dev 形态)``。

    dev 形态要额外补 ``dev_desktop_env()`` 那套 env，否则冷启动出来的不是「同一个
    Laji」；正式安装的包自己知道去哪找 app。
    """
    found: list[tuple[str, bool]] = []
    command = protocol_command()
    if command and registration_ok(command) and not _is_laji_code(command):
        found.append((command, _is_dev_command(command)))
    dev = dev_desktop_command()
    if dev:
        found.append((dev, True))
    installed = installed_desktop_command()
    if installed:
        found.append((installed, False))
    return found


def _dev_server_running(host: str = "127.0.0.1", port: int = DEV_SERVER_PORT,
                        timeout: float = 0.03, *, fresh: bool = False) -> bool:
    """Vite dev server 是否在监听（决定冷启动能不能挂上实时 renderer）。

    结果缓存 ``DEV_SERVER_CACHE_SECONDS``：这只是一道「走不走实时 renderer」的
    分叉，毫秒级新鲜度没有意义，而每次点击都等一次超时会把界面拖住。
    """
    import socket

    key = (host, port)
    now = time.monotonic()
    if (not fresh and _DEV_SERVER_CACHE["key"] == key
            and now - float(_DEV_SERVER_CACHE["at"]) < DEV_SERVER_CACHE_SECONDS):
        return bool(_DEV_SERVER_CACHE["ok"])
    try:
        with socket.create_connection((host, port), timeout=timeout):
            ok = True
    except OSError:
        ok = False
    _DEV_SERVER_CACHE.update(key=key, at=now, ok=ok)
    return ok


def dev_desktop_env() -> dict:
    """补齐 ``npm run dev`` 给 Electron 的那几项 env；已设置的一律不动。

    只 Popen ``LajiAgent.exe`` 而不带这几项时，``isDevShell()`` 为假，进程按生产
    形态加载 ``dist/renderer`` 并且另算一份引擎数据目录——窗口能开，但看不到正在
    dev 的会话，也就谈不上两边互通。
    """
    root = _dev_root()
    if not root:
        return {}
    wanted = {
        "NERVE_DEV_ROOT": root,
        # dev 默认走 ``laji serve`` 子进程，与 dev-windows.ps1 保持一致。
        "LAJI_IN_PROCESS": "0",
        "LAJI_SKIP_STARTUP_GATE": "1",
    }
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        shared = os.path.join(local, "laji")
        wanted["LAJI_DATA_DIR"] = shared
        wanted["LAJI_CONFIG_DIR"] = shared
    if _dev_server_running():
        wanted["VITE_DEV_SERVER_URL"] = f"http://127.0.0.1:{DEV_SERVER_PORT}/"
        wanted["LAJI_DEV_SHELL"] = "1"
    else:
        # 桌宠自己可能是从曾经的 dev 环境里启的，继承来的 dev server 地址会过期（
        # 白屏）。这两项是「必须对」的：死了就得清掉，不能只补不删。
        wanted["VITE_DEV_SERVER_URL"] = None
        wanted["LAJI_DEV_SHELL"] = None
    merged = {}
    for key, value in wanted.items():
        if value is not None and os.environ.get(key):
            continue
        merged[key] = value
    return merged


def _apply_env(base: dict, extra: dict) -> dict:
    """把覆写表合进 env；``None`` 表示显式删除。"""
    merged = dict(base)
    for key, value in extra.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def _launch(command: str, url: str, extra_env: dict | None = None) -> bool:
    """按命令模板拉起（``%1`` 换成 URL），绕开系统协议处理器。"""
    try:
        import shlex
        import subprocess

        filled = command.replace('"%1"', url).replace("%1", url)
        args = [part.strip('"') for part in shlex.split(filled, posix=False)]
        env = None
        if extra_env:
            env = _apply_env(os.environ, extra_env)
        subprocess.Popen(args, close_fds=True, env=env)
    except Exception:
        log.debug("agent bridge: 自投递失败（%s）", command, exc_info=True)
        return False
    return True


def open_laji(text: str = "", *, force: bool = False, run_id: str = "",
              workspace: str = "", pet: str | None = None) -> bool:
    """把 ``text`` 交给 Laji Agent；返回是否真的交给了系统（False → 调用方回退）。

    ``force=True`` 跳过「主进程是否在跑」这道预检：``laji-agent://`` 的协议处理器
    本身就是冷启动入口，「打工」按钮要的是「没开就打开它」，预检会把这条路堵死。
    ``run_id`` 非空 = 请 Laji 直接打开这一轮所在的聊天框（气泡的「去聊天窗」）；
    ``workspace`` 只在打开别人那条会话时给（审批提醒落在项目工作区）。
    ``pet`` = 当前桌宠的角色 id，定它在 Laji 那边的目录 ``Pet/<id>``。
    """
    if not force and not laji_running():
        log.debug("agent bridge: Laji 没在跑，回退自带聊天窗")
        return False
    url = ask_url(text, run_id, workspace, pet)
    command = protocol_command()
    # 优先系统协议：Windows 会把它转交给已运行的主进程并置前台，比自己起进程
    # 更省事。前提是这项注册真的指向 Laji Agent（不能是 Laji Code 壳，也不能是
    # 缺 app 目录的裸 electron——那会弹 “Unable to find Electron app”）。
    if _registration_usable(command) and _open_url(url):
        return True
    if command and not _registration_usable(command):
        log.info("agent bridge: %s:// 注册命令不可用（%s），改投直接入口", SCHEME, command)
    # 直接入口：dev 镜像 / 正式安装目录。用户单独跑桌宠、或注册被改坏时全靠这条。
    for candidate, is_dev in direct_commands():
        extra_env = dev_desktop_env() if is_dev else None
        if _launch(candidate, url, extra_env=extra_env):
            log.info("agent bridge: 已投递 %s → %s", url, candidate)
            return True
    # 还有注册项但没自洽入口：只在它真能打开一个程序时交给系统（例如用户自己
    # 把关联改对了）。否则留给调用方提示，不弹系统错误框。
    if _open_url_is_safe(command) and _open_url(url):
        return True
    log.warning("agent bridge: 找不到可用的 Laji Agent 入口（注册=%r），回退自带聊天窗",
                command)
    return False


def has_launch_entry() -> bool:
    """有没有一条能拉起 Laji 的路（只查文件/注册表，不联网、不起进程）。

    点击瞬间用它定气泡：有入口先说「这就叫起来」，没入口立刻说没找到——两者都
    不该让用户对着一片空白等结果。
    """
    command = protocol_command()
    if _registration_usable(command):
        return True
    if dev_desktop_command():
        return True
    return bool(installed_desktop_command())


def open_laji_in_background(text: str = "", *, force: bool = True, run_id: str = "",
                            workspace: str = "", pet: str | None = None, on_done=None) -> bool:
    """在后台线程里跑 ``open_laji``；返回 ``open_laji`` 的成功与否（线程已起时恒 True）。

    Electron 冷启动要几秒，而点「打工」走的是 Qt 主线程：同步等这几秒，桌宠动画
    会整个冻住，用户看到的就是「点了没反应」。这里先把调用扔出去，气泡在那之前
    已经上屏。入口在不在由调用方先问 ``has_launch_entry()``。

    ``on_done(ok)`` 在**工作线程**里执行，调用方自己排回主线程（只在失败时用）。
    """
    def _run() -> None:
        try:
            ok = open_laji(text, force=force, run_id=run_id, workspace=workspace, pet=pet)
        except Exception:
            log.debug("agent bridge: 后台拉起失败", exc_info=True)
            ok = False
        if on_done is not None:
            try:
                on_done(ok)
            except Exception:
                log.debug("agent bridge: 后台拉起回调失败", exc_info=True)

    try:
        import threading

        threading.Thread(target=_run, name="laji-open", daemon=True).start()
    except Exception:
        log.debug("agent bridge: 线程起不来，退回同步拉起", exc_info=True)
        return open_laji(text, force=force, run_id=run_id, workspace=workspace)
    return True


def _open_url(url: str) -> bool:
    """交给系统协议处理器；Qt 不可用/抛错时按「没交出去」处理。"""
    try:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
    except Exception:  # pragma: no cover - 打包缺 QtGui 时退回自带聊天窗
        log.debug("agent bridge: Qt 不可用，回退自带聊天窗", exc_info=True)
        return False
    try:
        return bool(QDesktopServices.openUrl(QUrl(url)))
    except Exception:
        log.debug("agent bridge: 唤起 Laji 失败（%s）", url, exc_info=True)
        return False
