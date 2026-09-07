# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（onedir，前端 dist 外置）。

构建（仓库根目录执行；日常请直接跑 scripts/build_release.ps1）:
    uv run pyinstaller packaging/app.spec --noconfirm --clean \
        --distpath release/pyinstaller --workpath release/_build
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()  # packaging/
ROOT = SPEC_DIR.parent  # 仓库根，server 包搜索基准

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn 通过 importlib 动态加载以下实现模块，静态分析不可见，需显式声明。
        # websockets_impl / httptools_impl 随 uvicorn[standard] 安装；wsproto 未安装故不列。
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="app",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="app",
)
