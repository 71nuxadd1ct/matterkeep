# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for matterkeep.
# Build with: pyinstaller matterkeep.spec
#
# Must be run on the target platform:
#   Linux  → produces  dist/matterkeep
#   macOS  → produces  dist/matterkeep
#   Windows→ produces  dist/matterkeep.exe

from pathlib import Path

src = Path("src/matterkeep")

a = Analysis(
    [str(src / "cli.py")],
    pathex=["src"],
    binaries=[],
    datas=[
        # Bundle the Jinja2 templates and static assets
        (str(src / "templates"), "matterkeep/templates"),
    ],
    hiddenimports=[
        # keyring backends vary by platform — include all so the frozen
        # app can fall back gracefully on any OS
        "keyring.backends.fail",
        "keyring.backends.null",
        # mattermostdriver uses websockets internally
        "websockets",
        "websockets.legacy",
        "websockets.legacy.client",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # keep the binary small — these are never used at runtime
        "tkinter",
        "unittest",
        "xmlrpc",
        "email",
        "http.server",
        "pydoc",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="matterkeep",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,      # CLI tool — keep the terminal
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,  # None = native arch; set "universal2" for macOS fat binary
    codesign_identity=None,
    entitlements_file=None,
)
