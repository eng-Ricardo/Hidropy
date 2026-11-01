"""Identidade, documentos legais e portabilidade dos recursos da nova marca."""

import base64
from pathlib import Path
import re
import subprocess
import sys

from src import __version__
from src.branding import APP_NAME, ICON_PATH, LOGO_PATH, legal_file


def test_version_and_cli_help_expose_new_identity_without_gui():
    root = Path(__file__).resolve().parent.parent
    for flag in ('--version', '--versao'):
        result = subprocess.run([sys.executable, '-B', 'main.py', flag], cwd=root,
                                text=True, encoding='utf-8', capture_output=True, timeout=20)
        assert result.returncode == 0
        assert result.stdout.strip() == f'{APP_NAME} {__version__}'
    result = subprocess.run([sys.executable, '-B', 'main.py', 'cli', '--help'], cwd=root,
                            text=True, encoding='utf-8', capture_output=True, timeout=30)
    assert result.returncode == 0 and 'AVANT HIDRO' in result.stdout
    assert 'HidroPy.exe' not in result.stdout


def test_windows_icon_has_small_and_high_resolution_variants(qapp):
    from PySide6.QtGui import QIcon, QImage
    icon = QIcon(str(ICON_PATH))
    assert {16, 32, 48, 128, 256} <= {s.width() for s in icon.availableSizes()}
    assert not icon.pixmap(32, 32).isNull()
    logo = QImage(str(LOGO_PATH))
    assert not logo.isNull() and logo.width() > logo.height() * 2
    master = QImage(str(LOGO_PATH.parent / 'avant_hidro_icon_master.png'))
    assert master.hasAlphaChannel() and master.pixelColor(0, 0).alpha() == 0


def test_original_mit_license_is_preserved_verbatim():
    root = Path(__file__).resolve().parent.parent
    current = (root / 'LICENSE').read_text(encoding='utf-8')
    original = (root / 'licenses/hidropy-original-LICENSE.txt').read_text(encoding='utf-8')
    assert current.replace('Copyright (c) 2026 AVANT HIDRO contributors\n', '') == original


def test_licenses_dialog_shows_mit_origin_and_third_party_terms(qapp):
    from src.ui.dialogs.help_dialogs import LicensesDialog
    dialog = LicensesDialog()
    assert dialog.tabs.count() == 3
    texts = [dialog.tabs.widget(i).toPlainText() for i in range(3)]
    assert 'Copyright (c) 2026 caioews' in texts[0]
    assert 'SOFTWARE IS PROVIDED "AS IS"' in texts[0]
    assert 'Caio Henrique de Oliveira Nascimento' in texts[1]
    assert 'PySide6' in texts[2] and 'DEAP' in texts[2]
    assert all('Arquivo não encontrado:' not in t for t in texts)
    dialog.reject()


def test_packaged_legal_resources_take_precedence(tmp_path, monkeypatch):
    from src import branding
    resources = tmp_path / 'src/resources'
    (resources / 'legal').mkdir(parents=True)
    (resources / 'legal/LICENSE').write_text('licença empacotada', encoding='utf-8')
    monkeypatch.setattr(branding, 'RESOURCES', resources)
    assert legal_file('LICENSE').read_text(encoding='utf-8') == 'licença empacotada'


def test_report_embeds_logo_for_offline_html_and_pdf(qapp, simple_project):
    from src.results.reports import build_report
    from src.ui.controller import DocumentController
    report = build_report(DocumentController(simple_project), {'cadastro'})
    assert 'Relatório — AVANT HIDRO' in report
    data = re.search(r'src="data:image/png;base64,([^"]+)"', report).group(1)
    assert base64.b64decode(data) == LOGO_PATH.read_bytes()
