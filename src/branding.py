"""Identidade pública da aplicação; formatos de arquivo permanecem compatíveis."""

from pathlib import Path

APP_NAME = 'AVANT HIDRO'
APP_SLUG = 'avant-hidro'
EXECUTABLE_NAME = 'AvantHidro'
ORGANIZATION = 'AVANT'
TAGLINE = 'Modelagem e projeto de redes hidráulicas'
APP_USER_MODEL_ID = 'AVANT.AvantHidro'
LOG_DIRECTORY = 'AvantHidro'
ORIGINAL_NAME = 'HidroPy'
ORIGINAL_AUTHOR = 'Caio Henrique de Oliveira Nascimento'
ORIGINAL_COPYRIGHT = 'Copyright (c) 2026 caioews'
RESOURCES = Path(__file__).resolve().parent / 'resources'
LOGO_PATH = RESOURCES / 'avant_hidro_logo.png'
ICON_PATH = RESOURCES / 'avant_hidro.ico'


def legal_file(name):
    """Recurso legal no código-fonte e na pasta interna do PyInstaller."""
    packaged = RESOURCES / 'legal' / name
    return packaged if packaged.is_file() else Path(__file__).resolve().parent.parent / name
