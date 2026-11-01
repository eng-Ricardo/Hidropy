"""Teste real da interface para validar o pacote Windows antes de distribuí-lo."""

from __future__ import annotations

import gc
import json
import os
import platform
import sys
import traceback


def windows_modules():
    if sys.platform != 'win32':
        return []
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    process = kernel.GetCurrentProcess()
    modules = (wintypes.HMODULE * 4096)()
    required = wintypes.DWORD()
    psapi.EnumProcessModules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE),
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE,
                                         wintypes.LPWSTR, wintypes.DWORD]
    if not psapi.EnumProcessModules(process, modules, ctypes.sizeof(modules), ctypes.byref(required)):
        return []
    result = []
    for module in modules[:required.value // ctypes.sizeof(wintypes.HMODULE)]:
        path = ctypes.create_unicode_buffer(32768)
        if psapi.GetModuleFileNameExW(process, module, path, len(path)):
            result.append(path.value)
    return sorted(result)


def run():
    from . import __version__
    from .branding import APP_NAME, ICON_PATH, LOGO_PATH
    result = {'application': APP_NAME, 'version': __version__,
              'frozen': bool(getattr(sys, 'frozen', False)),
              'python': platform.python_version(), 'executable': sys.executable,
              'windows': platform.platform(), 'status': 'error'}
    app = window = None
    try:
        # Mesma primeira importação do programa: não pré-carrega QtCore/QtGui.
        from PySide6.QtWidgets import QApplication
        from PySide6.QtCore import QCoreApplication, QEvent, qVersion
        from PySide6.QtGui import QIcon, QPixmap
        from .ui.main_window import MainWindow
        app = QApplication.instance() or QApplication([APP_NAME])
        app.setApplicationName(APP_NAME)
        app.setApplicationVersion(__version__)
        app.setWindowIcon(QIcon(str(ICON_PATH)))
        if app.windowIcon().isNull() or QPixmap(str(LOGO_PATH)).isNull():
            raise RuntimeError('Ícone ou logo ausente no pacote.')
        window = MainWindow()
        window.resize(1000, 700)
        app.processEvents()
        if window.grab().isNull():
            raise RuntimeError('A janela não pôde ser renderizada.')
        result.update(status='ok', qt=qVersion(), qt_platform=app.platformName(),
                      title=window.windowTitle())
    except Exception as error:
        result.update(error=str(error), traceback=traceback.format_exc(),
                      qt_environment={k: v for k, v in os.environ.items() if k.startswith(('QT_', 'QML'))})
    finally:
        result['loaded_modules'] = windows_modules()
        if app is not None:
            for widget in app.topLevelWidgets():
                if hasattr(widget, 'ctrl'):
                    widget.ctrl.mark_saved()
                widget.hide()
                widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
            window = None
            gc.collect()
    print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
    return 0 if result['status'] == 'ok' else 1
