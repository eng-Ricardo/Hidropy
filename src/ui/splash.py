"""Tela de abertura do AVANT HIDRO."""
from __future__ import annotations
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QSplashScreen
from .. import __version__
from ..branding import APP_NAME, LOGO_PATH, ORIGINAL_AUTHOR
BACKGROUND = QColor('#000000')
WIDTH, HEIGHT = 820, 420
DURATION_MS = 2000
LOGO = str(LOGO_PATH)
def splash_pixmap(scale: float = 1.0) -> QPixmap:
    w, h = round(WIDTH * scale), round(HEIGHT * scale)
    pm = QPixmap(w, h)
    pm.fill(BACKGROUND)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    s = scale
    logo = QPixmap(LOGO)
    if not logo.isNull():
        logo = logo.scaled(round((WIDTH - 48) * s), round(306 * s), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawPixmap(round((w - logo.width()) / 2), round(22 * s), logo)
    else:
        p.setPen(QColor('#ffffff'))
        font = QFont('Segoe UI'); font.setPixelSize(round(48 * s)); font.setBold(True)
        p.setFont(font)
        p.drawText(QRectF(24 * s, 40 * s, w - 48 * s, 190 * s), Qt.AlignCenter, APP_NAME)
    p.setPen(QColor('#e1e6ed'))
    font = QFont('Segoe UI'); font.setPixelSize(round(17 * s)); p.setFont(font)
    p.drawText(QRectF(20 * s, 320 * s, w - 40 * s, 30 * s), Qt.AlignCenter, f'Versão {__version__} • Licença MIT')
    font.setPixelSize(round(12 * s)); p.setFont(font)
    p.setPen(QColor('#a7b0bf'))
    p.drawText(QRectF(20 * s, 365 * s, w - 40 * s, 30 * s), Qt.AlignCenter, f'Baseado no HidroPy • Autor original: {ORIGINAL_AUTHOR}')
    p.end()
    return pm

def show_splash(app) -> QSplashScreen:
    ratio = app.primaryScreen().devicePixelRatio() if app.primaryScreen() else 1.0
    pm = splash_pixmap(ratio)
    pm.setDevicePixelRatio(ratio)
    splash = QSplashScreen(pm, Qt.WindowStaysOnTopHint)
    splash.show(); app.processEvents()
    return splash
