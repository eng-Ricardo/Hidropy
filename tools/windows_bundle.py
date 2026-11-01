"""Isolamento das dependências nativas do pacote Windows 10/11."""

import os
from pathlib import Path
import re
import sys


def build_environment(environ=None):
    """PATH temporário do compilador, sem ferramentas externas como Poppler/Qt."""
    env = dict(os.environ if environ is None else environ)
    windows = Path(env.get('SystemRoot', r'C:\Windows'))
    directories = [Path(sys.executable).parent, Path(sys.base_prefix),
                   windows / 'System32', windows]
    env['PATH'] = os.pathsep.join(dict.fromkeys(str(p) for p in directories))
    for key in ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'QML2_IMPORT_PATH',
                'QML_IMPORT_PATH', 'QTDIR'):
        env.pop(key, None)
    return env


def exclude_foreign_windows_icu(binaries):
    """Qt usa a ICU nativa do Windows; uma icuuc.dll externa pode ter ABI diferente.

    Não remove DLLs versionadas/vendorizadas dentro de pacotes. Somente cópias
    globais no diretório raiz que poderiam ocultar a biblioteca do Windows.
    """
    result = []
    for entry in binaries:
        target = Path(entry[0])
        name = target.name.lower()
        foreign = name in {'icu.dll', 'icuuc.dll', 'icuin.dll'} or re.fullmatch(r'icudt\d+\.dll', name)
        if target.parent == Path('.') and foreign:
            continue
        result.append(entry)
    return result
