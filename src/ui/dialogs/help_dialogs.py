"""Ajuda: manual do usuário e janela Sobre."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QTextBrowser,
                               QVBoxLayout, QTabWidget, QPushButton)

from ... import __version__
from ...branding import APP_NAME, LOGO_PATH, TAGLINE, legal_file

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), 'resources')
MANUAL = os.path.join(RESOURCES, 'manual.html')
LOGO = str(LOGO_PATH)

AUTHOR = 'Caio Henrique de Oliveira Nascimento'
AUTHOR_INFO = 'Estudante de Engenharia Ambiental e Sanitária<br>IFCE — campus Maracanaú'
LINKEDIN = 'https://www.linkedin.com/in/caio-henrique-6a6650236'


class ManualDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Manual do {APP_NAME}')
        self.resize(900, 760)
        v = QVBoxLayout(self)
        self.browser = QTextBrowser()
        self.browser.document().setBaseUrl(QUrl.fromLocalFile(RESOURCES + os.sep))
        self.browser.setOpenExternalLinks(True)        # LinkedIn abre no navegador
        self.browser.setOpenLinks(True)                # links do sumário rolam o texto
        try:
            with open(MANUAL, encoding='utf-8') as f:
                self.browser.setHtml(f.read())
        except OSError:
            self.browser.setPlainText('Manual não encontrado.')
        v.addWidget(self.browser)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Sobre o {APP_NAME}')
        self.resize(720, 680)
        h = QVBoxLayout()
        logo = QLabel()
        if os.path.exists(LOGO):
            logo.setPixmap(QPixmap(LOGO).scaled(650, 250, Qt.KeepAspectRatio,
                                                Qt.SmoothTransformation))
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet('background: #000000; padding: 12px;')
        h.addWidget(logo)
        text = QLabel(
            f'<h2 style="margin:0">{APP_NAME}</h2>'
            f'<p><b>Versão {__version__}</b></p>'
            f'<p>{TAGLINE}</p>'
            '<p>Desenho, simulação e otimização de redes de distribuição de água, com '
            'simulação hidráulica pelo EPANET e otimização de diâmetros por algoritmo '
            'genético.</p>'
            '<p><b>Identidade e evolução:</b> AVANT HIDRO.<br>'
            '<b>Licença do código:</b> MIT. Copyright (c) 2026 caioews; '
            'Copyright (c) 2026 AVANT HIDRO contributors.</p>'
            f'<p><b>Baseado no HidroPy — autor original:</b><br>{AUTHOR}<br>{AUTHOR_INFO}</p>'
            f'<p>LinkedIn: <a href="{LINKEDIN}">www.linkedin.com/in/caio-henrique-6a6650236</a>'
            '</p><p>Usa Qt/PySide6 e DEAP sob suas licenças LGPL e componentes com '
            'outras licenças próprias. Consulte os textos e atribuições abaixo.</p>')
        text.setTextFormat(Qt.RichText)
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setTextInteractionFlags(Qt.TextBrowserInteraction)
        text.setMinimumWidth(360)
        h.addWidget(text, 1)
        v = QVBoxLayout(self)
        v.addLayout(h)
        self.licenses_button = QPushButton('Licenças e atribuições…')
        self.licenses_button.clicked.connect(self.open_licenses)
        v.addWidget(self.licenses_button)
        bb = QDialogButtonBox(QDialogButtonBox.Ok)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)

    def open_licenses(self):
        dialog = LicensesDialog(self)
        dialog.exec()
        dialog.deleteLater()


class LicensesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f'Licenças e atribuições — {APP_NAME}')
        self.resize(850, 680)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        for title, name in [('MIT — aplicativo', 'LICENSE'), ('Origem e alterações', 'NOTICE.md'),
                            ('Dependências', 'THIRD_PARTY_NOTICES.md')]:
            browser = QTextBrowser()
            browser.setOpenExternalLinks(True)
            path = legal_file(name)
            try:
                text = path.read_text(encoding='utf-8')
                if path.suffix == '.md':
                    browser.document().setBaseUrl(QUrl.fromLocalFile(str(path.parent) + os.sep))
                    browser.setMarkdown(text)
                else:
                    browser.setPlainText(text)
            except OSError:
                browser.setPlainText(f'Arquivo não encontrado: {name}')
            self.tabs.addTab(browser, title)
        layout.addWidget(self.tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
