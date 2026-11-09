# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('assets/characters', 'assets/characters'), ('assets/big_blue_fat_fish', 'assets/big_blue_fat_fish'), ('pet/persona_presets', 'pet/persona_presets'), ('pet/menu_templates', 'pet/menu_templates'), ('pet/chat/legacy_styles.qss', 'pet/chat'), ('pet/chat/modern_styles.qss', 'pet/chat'), ('assets/sounds', 'assets/sounds'), ('assets/chat', 'assets/chat'), ('assets/icon.ico', 'assets'), ('LICENSE', '.'), ('THIRD_PARTY_NOTICES.md', '.'), ('integrations', 'integrations'), ('resources/presentmon', 'resources/presentmon'), ('pet/agent_link/_proto/laji', 'pet/agent_link/_proto/laji')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('imageio_ffmpeg')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('certifi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('tzdata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('psutil')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('keyring')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('win32ctypes')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('grpc')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('google.protobuf')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# protobuf 7.x 的 upb C 扩展住在 `google/_upb/`，是 `google.protobuf` 的**兄弟目录**：
# 上面那句只进 `google/protobuf`，遍历不到它，冻结包里就留下一个空的 `google/_upb`，
# `session_pb2` import 时直接炸——桌宠整个 agent_link 变 unavailable。
from PyInstaller.utils.hooks import collect_dynamic_libs
binaries += collect_dynamic_libs('google._upb')
# QtMultimedia：语音报时/「立即试听」的播放出口只有 QMediaPlayer+QAudioOutput 一条路
# （chime_service._ensure_player），缺它则合成成功却一声不响——只在气泡里留一句
# 「播放器不可用」。Essentials 不含该模块，构建机须装 PySide6-Addons 才有东西可收；
# 解码后端在 PySide6/plugins/multimedia 下（ffmpegmediaplugin.dll 等），只收 .pyd 而漏
# 插件目录同样是静音，故两者一起带。
from pathlib import Path as _Path
import PySide6 as _PySide6
tmp_ret = collect_all('PySide6.QtMultimedia')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
datas += [(str(_Path(_PySide6.__file__).resolve().parent / 'plugins' / 'multimedia'), 'PySide6/plugins/multimedia')]


a = Analysis(
    ['packaging/pet_entry.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['OpenGL', 'PyQt5', 'PyQt6', 'PySide2', 'matplotlib', 'matplotlib_inline', 'seaborn', 'IPython', 'ipykernel', 'jupyter_client', 'jupyter_core', 'nbformat', 'zmq', 'torch', 'transformers', 'datasets', 'langchain', 'pandas', 'numba', 'llvmlite', 'spacy', 'playwright', 'django', 'hypothesis'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='laji-pet',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/icon.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='laji-pet',
)
