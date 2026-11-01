"""Gera o executável e acompanha-o de licenças e fontes da aplicação."""

from pathlib import Path
import argparse
import json
import shutil
import subprocess
import sys
import zipfile

from windows_bundle import build_environment

ROOT = Path(__file__).resolve().parent.parent


def verify(folder, workpath):
    """Uma compilação só é aprovada se o executável carregar e renderizar a GUI."""
    folder, workpath = Path(folder).resolve(), Path(workpath).resolve()
    workpath.mkdir(parents=True, exist_ok=True)
    env = build_environment()
    env.pop('QT_QPA_PLATFORM', None)
    log = workpath / 'diagnostico-executavel.log'
    try:
        process = subprocess.run([str(folder / 'AvantHidro.exe'), '--diagnostico'],
                                 cwd=folder, env=env, capture_output=True, text=True,
                                 encoding='utf-8', errors='replace', timeout=90)
    except (OSError, subprocess.TimeoutExpired) as error:
        status = 'blocked' if getattr(error, 'winerror', None) == 4551 else 'error'
        report = {'status': status, 'error': str(error), 'winerror': getattr(error, 'winerror', None)}
        log.write_text(str(error), encoding='utf-8')
        (folder / 'verificacao-executavel.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RuntimeError(f'Não foi possível testar o executável: {error}') from error
    log.write_text(process.stdout + '\nSTDERR:\n' + process.stderr, encoding='utf-8')
    try:
        result = json.loads(process.stdout)
    except json.JSONDecodeError as error:
        (folder / 'verificacao-executavel.json').write_text(json.dumps({'status': 'error', 'error': 'Diagnóstico inválido'}), encoding='utf-8')
        raise RuntimeError(f'Diagnóstico inválido do executável. Consulte {log}.') from error
    if process.returncode != 0 or result.get('status') != 'ok' or not result.get('frozen'):
        report = {'status': 'error', 'exit_code': process.returncode,
                  'error': result.get('error', 'Falha nativa ou execução fora do pacote compilado.')}
        (folder / 'verificacao-executavel.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RuntimeError(f'Executável reprovado: {result.get("error", "falha nativa")}. Consulte {log}.')
    summary = {key: result[key] for key in ('application', 'version', 'status', 'qt', 'qt_platform', 'frozen')}
    (folder / 'verificacao-executavel.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Interface do executável verificada:', result['qt'], result['qt_platform'])


def finalize(folder):
    folder = Path(folder)
    for name in ('LICENSE', 'NOTICE.md', 'THIRD_PARTY_NOTICES.md'):
        shutil.copy2(ROOT / name, folder / name)
    shutil.copytree(ROOT / 'licenses', folder / 'licenses', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'docs/IDENTIDADE_E_LICENCAS.md', folder / 'LEIA-ME.md')
    with zipfile.ZipFile(folder / 'AvantHidro-fontes.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for directory in ('src', 'tests', 'tools', 'licenses', 'skill', 'docs'):
            for path in (ROOT / directory).rglob('*'):
                if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc':
                    archive.write(path, path.relative_to(ROOT))
        for name in ('main.py', 'main4.py', 'AvantHidro.spec', 'HidroPy.spec', 'requirements.txt',
                     'requirements-build.txt', 'requirements-windows-py312.lock', 'README.md',
                     'LICENSE', 'NOTICE.md', 'THIRD_PARTY_NOTICES.md', 'examples/gerar_exemplos.py'):
            archive.write(ROOT / name, name)
    print('Arquivos da distribuição preparados:', folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distpath', type=Path, default=ROOT / 'dist')
    parser.add_argument('--workpath', type=Path, default=ROOT / 'build')
    parser.add_argument('--finalize-only', action='store_true')
    args = parser.parse_args()
    if not args.finalize_only:
        subprocess.run([sys.executable, '-B', str(ROOT / 'tools/collect_licenses.py')], cwd=ROOT, check=True)
        subprocess.run([sys.executable, '-B', '-m', 'PyInstaller', '--noconfirm', '--clean',
                        '--distpath', str(args.distpath), '--workpath', str(args.workpath),
                        str(ROOT / 'AvantHidro.spec')], cwd=ROOT, env=build_environment(), check=True)
    finalize(args.distpath / 'AvantHidro')
    verify(args.distpath / 'AvantHidro', args.workpath)


if __name__ == '__main__':
    main()
