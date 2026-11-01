import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'examples'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

EXAMPLES = os.path.join(ROOT, 'examples')
MAIN4 = os.path.join(ROOT, 'main4.py')


@pytest.fixture(scope='session')
def qapp():
    import gc
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
    # Destrói widgets e seus ciclos Python enquanto QApplication ainda está viva.
    # Deixar essa ordem para o encerramento do interpretador pode abortar no Windows.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
    gc.collect()


@pytest.fixture
def simple_project():
    import gerar_exemplos
    return gerar_exemplos.rede_exemplo()


@pytest.fixture
def eps_project():
    import gerar_exemplos
    return gerar_exemplos.rede_periodo_estendido()


@pytest.fixture(scope='session')
def base_dxf(tmp_path_factory):
    import gerar_exemplos
    path = str(tmp_path_factory.mktemp('dxf') / 'base.dxf')
    gerar_exemplos.base_dxf(path)
    return path
