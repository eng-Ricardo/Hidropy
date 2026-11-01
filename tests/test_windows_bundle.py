"""Evita regressão da DLL ICU externa e verifica a GUI real no diagnóstico."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('windows_bundle', ROOT / 'tools/windows_bundle.py')
helpers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helpers)


def test_build_path_cannot_pick_external_icu_or_qt(tmp_path):
    external = str(tmp_path / 'foreign-poppler')
    original = {'SystemRoot': str(tmp_path / 'Windows'), 'PATH': external,
                'QT_PLUGIN_PATH': external, 'QML2_IMPORT_PATH': external, 'LANG': 'pt_BR'}
    env = helpers.build_environment(original)
    assert external not in env['PATH'].split(os.pathsep)
    assert str(Path(sys.executable).parent) in env['PATH'].split(os.pathsep)
    assert str(tmp_path / 'Windows/System32') in env['PATH'].split(os.pathsep)
    assert 'QT_PLUGIN_PATH' not in env and 'QML2_IMPORT_PATH' not in env
    assert env['LANG'] == 'pt_BR' and original['PATH'] == external


def test_only_conflicting_global_icu_is_excluded():
    records = [(name, f'origin/{name}', 'BINARY') for name in
               ['icuuc.dll', 'ICUIN.DLL', 'icu.dll', 'icudt78.dll', 'PySide6/icuuc.dll',
                'icuuc78.dll', 'PySide6/Qt6Core.dll', 'python312.dll', 'VCRUNTIME140.dll']]
    assert [r[0] for r in helpers.exclude_foreign_windows_icu(records)] == [
        'PySide6/icuuc.dll', 'icuuc78.dll', 'PySide6/Qt6Core.dll', 'python312.dll', 'VCRUNTIME140.dll']


def test_diagnostic_constructs_and_renders_main_window():
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONDONTWRITEBYTECODE='1')
    process = subprocess.run([sys.executable, '-B', str(ROOT / 'main.py'), '--diagnostico'],
                             cwd=ROOT, env=env, capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=60)
    assert process.returncode == 0, process.stderr + process.stdout
    result = json.loads(process.stdout)
    assert result['status'] == 'ok' and result['application'] == 'AVANT HIDRO'
    assert not result['frozen'] and result['qt_platform'] == 'offscreen'
    assert 'AVANT HIDRO' in result['title']


def builder_module(monkeypatch):
    monkeypatch.setitem(sys.modules, 'windows_bundle', helpers)
    spec = importlib.util.spec_from_file_location('build_windows', ROOT / 'tools/build_windows.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_os_block_is_reported_and_never_approved(monkeypatch, tmp_path):
    module = builder_module(monkeypatch)
    error = OSError('Uma política de Controle de Aplicativo bloqueou este arquivo')
    error.winerror = 4551
    def blocked(*args, **kwargs):
        raise error
    monkeypatch.setattr(module.subprocess, 'run', blocked)
    with pytest.raises(RuntimeError, match='Não foi possível testar'):
        module.verify(tmp_path, tmp_path / 'build')
    report = json.loads((tmp_path / 'verificacao-executavel.json').read_text(encoding='utf-8'))
    assert report['status'] == 'blocked' and report['winerror'] == 4551
    assert 'Controle de Aplicativo' in (tmp_path / 'build/diagnostico-executavel.log').read_text(encoding='utf-8')


def test_native_failure_after_rendering_is_rejected(monkeypatch, tmp_path):
    module = builder_module(monkeypatch)
    process = SimpleNamespace(returncode=9, stdout=json.dumps({'status': 'ok', 'frozen': True}), stderr='')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: process)
    with pytest.raises(RuntimeError, match='reprovado'):
        module.verify(tmp_path, tmp_path / 'build')
    assert json.loads((tmp_path / 'verificacao-executavel.json').read_text())['status'] == 'error'


def test_native_success_writes_the_verified_version(monkeypatch, tmp_path):
    module = builder_module(monkeypatch)
    result = {'status': 'ok', 'frozen': True, 'application': 'AVANT HIDRO',
              'version': '1.2.0', 'qt': '6.12.0', 'qt_platform': 'windows'}
    process = SimpleNamespace(returncode=0, stdout=json.dumps(result), stderr='')
    monkeypatch.setattr(module.subprocess, 'run', lambda *a, **kw: process)
    module.verify(tmp_path, tmp_path / 'build')
    assert json.loads((tmp_path / 'verificacao-executavel.json').read_text()) == result
