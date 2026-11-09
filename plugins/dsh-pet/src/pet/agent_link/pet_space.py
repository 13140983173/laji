"""桌宠自己的工作区。

气泡里说的话就是 Laji daemon 的一条 run，``workspace_root`` 决定它在 Laji Agent 侧栏
归到哪个目录。留空会跟着「最近活跃项目」走，桌宠的闲聊就混进用户的代码会话列表里；
所以这里给每只桌宠一个固定目录 ``<userData>/Pet/<角色 id>``，侧栏据此分出一个以
桌宠名字命名的组。

为什么在 ``Pet`` 下再分一层而不是直接叫 ``Pet``：用户同时养好几只时它们的人格、
附件、临时文件不该挤在同一格；侧栏标题取目录末段，分完之后每组就是对应桌宠的名字。

路径与 Laji Agent 主进程一致（``app.getPath("userData")/Pet/<id>``，productName 是
``Laji Agent``）。Laji 自己拉起桌宠时会用 ``LAJI_PET_WORKSPACE`` 直接告知，免去猜；
用户双击 exe 起的裸进程没有这个 env，就按默认位置算。
"""

from __future__ import annotations

import os
import shutil

PET_SPACE_DIR_NAME = "Pet"
PET_WORKSPACE_ENV = "LAJI_PET_WORKSPACE"
# electron-builder 的 productName；userData 目录名由它决定。
_DEFAULT_PRODUCT_NAME = "Laji Agent"
# 目录名只收这些字符：角色 id 是 ASCII，但用户可能自己起名叫「大肥鱼」。
_SAFE_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def _appdata_roaming() -> str:
    base = (os.environ.get("APPDATA") or "").strip()
    if base:
        return base
    return os.path.join(os.path.expanduser("~"), "AppData", "Roaming")


def _safe_dir_name(name: str) -> str:
    """角色名 → 能当目录名的一段：剔掉路径分隔符与保留名，宁缺不猜。"""
    raw = "".join(ch for ch in str(name or "").strip() if ch in _SAFE_NAME_CHARS)
    raw = raw.strip(". ")
    if not raw or raw in {".", ".."} or raw.lower() in {"con", "prn", "aux", "nul"}:
        return ""
    return raw[:64]


def _keep_mkdir(path: str) -> bool:
    """建目录，返回「这次是新建的」。"""
    if os.path.isdir(path):
        return False
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        return False
    return True


def _seed_from_legacy(base: str, root: str) -> None:
    """新目录第一次出现时，把旧的 ``Pet/.laji`` 复制一份过来。

    旧版本把每只桌宠都塞在 ``Pet`` 本身，人设文件、附件、临时文件都在那里。旧的
    原样留着（用户可能还想打开那个组），新目录只是拿到一份副本开张。只有新目录
    **刚建出来**、且它自己还没有 ``.laji`` 时才复制，不会拿旧文件盖掉新内容。
    """
    source = os.path.join(base, ".laji")
    target = os.path.join(root, ".laji")
    if not os.path.isdir(source) or os.path.exists(target):
        return
    try:
        shutil.copytree(source, target, dirs_exist_ok=True)
    except OSError:
        # 复制失败就当没有旧存档：她自己会重建人设文件，不值得挡住启动。
        pass


def pet_workspace_root(character: str = "") -> str:
    """桌宠会话的 workspace 根（``<userData>/Pet/<角色 id>``）。

    建不出来时返回空串（调用方退回跟随最近项目）。``character`` 留空则用默认角色。
    """
    explicit = (os.environ.get(PET_WORKSPACE_ENV) or "").strip()
    if explicit:
        _keep_mkdir(explicit)
        return explicit if os.path.isdir(explicit) else ""
    base = os.path.join(_appdata_roaming(), _DEFAULT_PRODUCT_NAME, PET_SPACE_DIR_NAME)
    name = _safe_dir_name(character)
    if not name:
        from .. import catalog

        name = _safe_dir_name(catalog.DEFAULT_CHARACTER) or "pet"
    root = os.path.join(base, name)
    if _keep_mkdir(root):
        _seed_from_legacy(base, root)
    if not os.path.isdir(root):
        return ""
    return root


def same_workspace(left: str, right: str) -> bool:
    """Windows 路径比较：大小写、分隔符、结尾斜杠都不该让同一目录判成两个。"""
    if not left or not right:
        return False
    norm = lambda p: os.path.normcase(os.path.normpath(p))  # noqa: E731
    return norm(left) == norm(right)
