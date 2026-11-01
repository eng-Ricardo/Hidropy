# Entrada de compatibilidade: gera AvantHidro.exe com a nova identidade.
from pathlib import Path
path = Path(SPECPATH) / "AvantHidro.spec"
exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"))
