# -*- mode: python ; coding: utf-8 -*-
# Fichier de build PyInstaller — IrwaneTraceForest (ITF)
# Utilisation : pyinstaller itf.spec   (depuis un environnement Windows avec les dépendances installées)

block_cipher = None

a = Analysis(
    ['desktop_launcher.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates', 'templates'),
        ('static', 'static'),
    ],
    hiddenimports=[
        'webview', 'flask',
        'reportlab', 'reportlab.graphics.barcode', 'reportlab.graphics.barcode.code128',
        'reportlab.pdfgen', 'reportlab.lib.pagesizes', 'reportlab.lib.units', 'reportlab.lib.colors',
        'openpyxl', 'openpyxl.styles', 'openpyxl.utils', 'openpyxl.cell._writer',
        'win32gui', 'win32con', 'win32api',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='IrwaneTraceForest',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # False = pas de console visible (application de bureau)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='static/img/itf.ico',   # facultatif — retirez cette ligne si vous n'avez pas d'icône
    onefile=True,
)
