"""Tela de abertura: marca AVANT HIDRO, proporção e sequência de inicialização."""


def test_splash_pixmap(qapp):
    from PySide6.QtGui import QColor
    from src.ui import splash
    pm = splash.splash_pixmap(1.0)
    assert (pm.width(), pm.height()) == (splash.WIDTH, splash.HEIGHT)
    assert pm.width() > pm.height()                                   # retangular
    img = pm.toImage()
    assert img.pixelColor(5, 5) == QColor('#000000')
    # A marca real aparece (azul da gota/letras), inclusive sem fontes de sistema.
    assert any(img.pixelColor(x, y).blue() > img.pixelColor(x, y).red() + 35
               for x in range(30, splash.WIDTH - 30, 5) for y in range(25, 310, 5))
    large = splash.splash_pixmap(2.0)
    assert (large.width(), large.height()) == (splash.WIDTH * 2, splash.HEIGHT * 2)


def test_startup_shows_splash_then_main_window(qapp, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QSplashScreen
    from src import app as app_mod
    from src.ui.main_window import MainWindow
    seen = {}

    def tops(cls):
        return [w for w in QApplication.topLevelWidgets() if isinstance(w, cls) and w.isVisible()]

    def early():                       # 1 s depois: splash visível, janela ainda não
        seen['early'] = (bool(tops(QSplashScreen)), bool(tops(MainWindow)))

    def late():                        # 3 s depois: janela visível, splash fechada
        seen['late'] = (bool(tops(QSplashScreen)), bool(tops(MainWindow)))
        for w in tops(MainWindow):
            w.ctrl.mark_saved()
            w.close()
        QApplication.instance().quit()

    QTimer.singleShot(1000, early)
    QTimer.singleShot(3000, late)
    app_mod.run(['avant-hidro'])
    assert seen['early'] == (True, False)
    assert seen['late'] == (False, True)
    from src import __version__
    assert qapp.applicationName() == 'AVANT HIDRO'
    assert qapp.applicationVersion() == __version__
    assert qapp.organizationName() == 'AVANT'
