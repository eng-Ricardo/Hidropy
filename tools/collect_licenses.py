"""Registra licenças das dependências instaladas, sem substituir seus textos."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import sys

from packaging.requirements import Requirement

ROOTS = ('wntr', 'deap', 'numpy', 'PySide6', 'ezdxf', 'pandas', 'matplotlib', 'openpyxl')


def distributions():
    pending, found = list(ROOTS), {}
    while pending:
        name = pending.pop()
        key = re.sub(r'[-_.]+', '-', name).lower()
        if key in found:
            continue
        dist = metadata.distribution(name)
        found[key] = dist
        for entry in dist.requires or ():
            req = Requirement(entry)
            if req.marker is None or req.marker.evaluate({'extra': ''}):
                pending.append(req.name)
    # O bootloader também faz parte do executável; preserve sua licença/exceção.
    try:
        found['pyinstaller'] = metadata.distribution('PyInstaller')
    except metadata.PackageNotFoundError:
        pass
    return sorted(found.values(), key=lambda d: d.metadata['Name'].lower())


def collect(root):
    root = Path(root).resolve()
    records = []
    for dist in distributions():
        name = dist.metadata['Name']
        slug = re.sub(r'[^a-z0-9.-]+', '-', name.lower())
        record = {'name': name, 'version': dist.version, 'files': [],
                  'urls': dist.metadata.get_all('Project-URL') or []}
        expression = dist.metadata.get('License-Expression')
        license_text = dist.metadata.get('License', '').strip()
        classifiers = [v.rsplit(' :: ', 1)[-1] for v in dist.metadata.get_all('Classifier') or []
                       if v.startswith('License ::')]
        record['license'] = expression or ('; '.join(classifiers) if classifiers else '') or (
            license_text if '\n' not in license_text and len(license_text) < 160 else
            'Consulte os textos originais')
        for file in dist.files or ():
            if not any(token in file.name.lower() for token in ('license', 'licence', 'copying', 'notice', 'copyright')):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file():
                continue
            token = hashlib.sha256(str(file).encode()).hexdigest()[:8]
            target = root / 'licenses' / 'dependencies' / slug / (token + '-' + file.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            record['files'].append({'source': str(file), 'path': target.relative_to(root).as_posix(),
                                     'sha256': hashlib.sha256(source.read_bytes()).hexdigest()})
        if not record['files']:
            raise RuntimeError(f'Nenhum texto de licença encontrado para {name}; conferir antes de distribuir.')
        records.append(record)
    python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if python_license.is_file():
        target = root / 'licenses' / 'Python-LICENSE.txt'
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(python_license, target)
    (root / 'licenses' / 'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Licenças e atribuições de terceiros', '',
             'A licença MIT de AVANT HIDRO não altera as licenças das dependências.',
             'Este inventário registra o ambiente de execução usado para preparar a distribuição,',
             'incluindo dependências transitivas e arquivos originais com seus avisos de autoria.', '',
             '## Qt/PySide6 e DEAP', '',
             'Qt/PySide6 e DEAP são utilizados sob suas opções LGPL. Os textos',
             '[LGPLv3](licenses/standard/LGPL-3.0.txt) e [GPLv3](licenses/standard/GPL-3.0.txt)',
             'acompanham os avisos originais. As bibliotecas Qt são carregadas dinamicamente.',
             'Esta distribuição não restringe a substituição das bibliotecas nem a engenharia',
             'reversa necessária à depuração dessas modificações. Os arquivos da aplicação',
             'e instruções de reconstrução são fornecidos junto com a distribuição.', '',
             'Fontes e informações das bibliotecas: [Qt/PySide](https://code.qt.io/pyside/pyside-setup.git/),',
             '[Qt](https://code.qt.io/qt/), [DEAP](https://github.com/DEAP/deap).',
             'As versões efetivamente instaladas constam abaixo; licenças e direitos de',
             'componentes de terceiros incorporados nessas bibliotecas também permanecem válidos.', '',
             '## Python', '', '[Licença do Python e avisos incorporados](licenses/Python-LICENSE.txt).', '',
             '## Bibliotecas instaladas', '']
    for record in records:
        lines += [f"### {record['name']} {record['version']}", '', f"Licença declarada: {record['license']}", '']
        lines += [f"- [{Path(f['path']).name}]({f['path']})" for f in record['files']]
        lines += ['']
        lines += ['- ' + url for url in record['urls'] if 'https://' in url]
        lines += ['']
    (root / 'THIRD_PARTY_NOTICES.md').write_text('\n'.join(lines), encoding='utf-8')
    print(f'{len(records)} dependências; {sum(len(r["files"]) for r in records)} textos originais preservados.')
    return records


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    collect(parser.parse_args().root)
