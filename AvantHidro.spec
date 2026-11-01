# -*- mode: python ; coding: utf-8 -*-
# python -m PyInstaller --noconfirm AvantHidro.spec
# Saída: dist/AvantHidro/AvantHidro.exe (bibliotecas dinâmicas em _internal).
from pathlib import Path
import runpy
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

root = Path(SPECPATH)
legal_names = ('LICENSE', 'NOTICE.md', 'THIRD_PARTY_NOTICES.md')
for name in legal_names:
    if not (root / name).is_file():
        raise SystemExit('Prepare as licenças antes de empacotar: python tools/collect_licenses.py')
datas = [(str(root / 'main4.py'), '.'),
         (str(root / 'src/cad/resources/conexoes.dxf'), 'src/cad/resources'),
         (str(root / 'src/resources/avant_hidro.ico'), 'src/resources'),
         (str(root / 'src/resources/avant_hidro_logo.png'), 'src/resources'),
         (str(root / 'src/resources/manual.html'), 'src/resources'),
         (str(root / 'licenses'), 'src/resources/legal/licenses')]
datas += [(str(root / name), 'src/resources/legal') for name in legal_names]
binaries, hiddenimports = [], ['openpyxl']
for package in ('wntr', 'deap'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules('ezdxf')
hiddenimports += ['atexit', 'random', 'shutil', 'tempfile', 'warnings']
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries, datas=datas,
             hiddenimports=hiddenimports, hookspath=[], hooksconfig={}, runtime_hooks=[],
             excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets',
                       'PySide6.QtQuick', 'PySide6.QtQml', 'PySide6.Qt3DCore',
                       'tkinter', 'pytest', 'IPython'], noarchive=False)
if sys.platform == 'win32':
    helpers = runpy.run_path(str(root / 'tools/windows_bundle.py'))
    a.binaries = helpers['exclude_foreign_windows_icu'](a.binaries)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='AvantHidro',
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(root / 'src/resources/avant_hidro.ico'),
          version=str(root / 'src/resources/version_info.txt'))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='AvantHidro')
