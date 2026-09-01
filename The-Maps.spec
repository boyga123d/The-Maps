# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('maps', 'maps'), ('assets', 'assets')]
binaries = []
# scapy/psutil: used by localtelemetry.py for the Npcap capture + game
# process/port lookup. pywebview is collected in full (datas/binaries/
# hiddenimports) since its PyInstaller hook doesn't pick up everything on
# its own; see the excludes below for why only edgechromium is needed.
hiddenimports = ['scapy', 'scapy.all', 'psutil', 'requests', 'pystray._win32']
tmp_ret = collect_all('pywebview')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pywebview probes for whichever GUI toolkit is installed; we only ever
    # use its Windows/WebView2 backend (see islepilot.py: gui="edgechromium"),
    # so drop the other backends its PyInstaller hook otherwise bundles.
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'gtk', 'cef'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='The-Maps',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets\\the_maps.ico'],
)
