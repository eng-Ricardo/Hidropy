"""Dados de curvas/padrões e formatos dos editores EPANET 2.2 (LPS e metros)."""

from __future__ import annotations

import csv
from dataclasses import dataclass
import io
import math
from pathlib import Path
import re

CURVE_LABELS = {'PUMP': 'Bomba — carga × vazão', 'EFFICIENCY': 'Rendimento da bomba',
                'VOLUME': 'Volume do tanque', 'HEADLOSS': 'Perda de carga — GPV'}
CURVE_AXES = {'PUMP': ('Vazão (L/s)', 'Carga (m)'), 'EFFICIENCY': ('Vazão (L/s)', 'Rendimento (%)'),
              'VOLUME': ('Nível (m)', 'Volume (m³)'), 'HEADLOSS': ('Vazão (L/s)', 'Perda de carga (m)')}


def number(value):
    try:
        result = float(str(value).strip().replace(',', '.'))
    except (ValueError, TypeError):
        raise ValueError(f'Valor numérico inválido: {value!r}.') from None
    if not math.isfinite(result):
        raise ValueError('Os valores devem ser finitos (sem NaN ou infinito).')
    return result


def text_number(value):
    text = repr(float(value))
    return text[:-2] if text.endswith('.0') else text


def validate_name(name):
    if not name or len(name) > 31 or any(c.isspace() or ord(c) < 32 or c in ';"' for c in name):
        raise ValueError('Identificador: use de 1 a 31 caracteres, sem espaços, ponto e vírgula ou aspas.')


def validate_pattern(values):
    if not values:
        raise ValueError('Informe ao menos um multiplicador.')
    return [number(v) for v in values]


@dataclass(frozen=True)
class PumpFit:
    a: float
    b: float
    c: float

    def head(self, flow):
        return self.a - self.b * flow ** self.c

    @property
    def zero_flow(self):
        return math.exp((math.log(self.a) - math.log(self.b)) / self.c)

    @property
    def equation(self):
        return f'H = {self.a:.6g} − {self.b:.6g} × Q^{self.c:.6g}  (H em m; Q em L/s)'


def fit_pump(points):
    """Ajuste do motor EPANET: um ponto ou três começando em vazão zero."""
    if len(points) != 1 and not (len(points) == 3 and points[0][0] == 0):
        return None
    if len(points) == 1:
        q, h = points[0]
        if q <= 0 or h <= 0:
            raise ValueError('Bomba com um ponto exige vazão e carga > 0.')
        points = [[0.0, 1.33334 * h], [q, h], [2 * q, 0.0]]
    (_, h0), (q1, h1), (q2, h2) = points
    try:
        c = math.log((h0 - h2) / (h0 - h1)) / math.log(q2 / q1)
        if not 0 < c <= 20:
            raise ValueError('O expoente do ajuste da bomba deve satisfazer 0 < C ≤ 20, como no EPANET.')
        a, b = h0, (h0 - h1) / q1 ** c
        if not all(math.isfinite(v) and v > 0 for v in (a, b, c)):
            raise ValueError('Escala inadequada para o ajuste da bomba.')
    except (OverflowError, ZeroDivisionError):
        raise ValueError('Escala inadequada para o ajuste da bomba.') from None
    return PumpFit(a, b, c)


def validate_curve(kind, rows):
    if kind not in CURVE_LABELS:
        raise ValueError('Tipo de curva inválido.')
    if not rows:
        raise ValueError('Informe ao menos um ponto da curva.')
    points = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            raise ValueError(f'Ponto {index}: informe X e Y.')
        x, y = (number(v) for v in row)
        if x < 0 or y < 0:
            raise ValueError(f'Ponto {index}: X e Y devem ser não negativos.')
        points.append([x, y])
    if any(b[0] <= a[0] for a, b in zip(points, points[1:])):
        raise ValueError('Os valores de X devem ser estritamente crescentes, sem duplicação.')
    if kind == 'PUMP':
        if any(b[1] >= a[1] for a, b in zip(points, points[1:])):
            raise ValueError('A carga da bomba deve diminuir com o aumento da vazão.')
        fit_pump(points)
    elif kind == 'EFFICIENCY':
        if any(y > 100 for _, y in points):
            raise ValueError('O rendimento deve estar entre 0 e 100%.')
    elif kind == 'VOLUME':
        if len(points) < 2 or any(b[1] <= a[1] for a, b in zip(points, points[1:])):
            raise ValueError('Volume: informe ao menos dois pontos, com níveis e volumes crescentes.')
    elif len(points) < 2:
        raise ValueError('Perda de carga: informe ao menos dois pontos.')
    return points


def _rows(text):
    lines = [(i, line.strip()) for i, line in enumerate(text.lstrip('\ufeff').splitlines(), 1)
             if line.strip() and not line.lstrip().startswith(('#', ';'))]
    if not lines:
        raise ValueError('O arquivo ou a área de transferência está vazio.')
    first = lines[0][1]
    delimiter = ';' if ';' in first else '\t' if '\t' in first else ',' if ',' in first and (
        not re.search(r'\s', first) or first[0].isalpha()) else None
    result = []
    for i, line in lines:
        if delimiter:
            bits = next(csv.reader([line], delimiter=delimiter))
        else:
            bits = re.split(r'[\s;]+', line)
        result.append((i, [v.strip() for v in bits]))
    return result


def parse_curve_text(text):
    rows = _rows(text)
    if rows and rows[0][1][0].casefold().split('(')[0].strip() in ('x', 'vazão', 'vazao', 'flow', 'nível', 'nivel', 'altura'):
        rows = rows[1:]
    points = []
    for line, row in rows:
        if len(row) != 2:
            raise ValueError(f'Linha {line}: esperadas duas colunas X e Y.')
        try:
            points.append([number(v) for v in row])
        except ValueError as error:
            raise ValueError(f'Linha {line}: {error}') from None
    if not points:
        raise ValueError('Nenhum ponto encontrado.')
    return points


def parse_pattern_text(text):
    # Vírgula entre dígitos é decimal no formato livre de multiplicadores.
    clean = text.lstrip('\ufeff').strip()
    header = clean.splitlines()[0].casefold() if clean else ''
    indexed = any(word in header for word in ('período', 'periodo', 'period,'))
    single_header = header.strip() in ('multiplicador', 'multiplier', 'multipliers')
    if indexed:
        rows = _rows(clean)[1:]
    else:
        rows = [(i, re.split(r'[\s;]+', line.strip())) for i, line in enumerate(clean.splitlines(), 1)
                if line.strip() and not line.lstrip().startswith(('#', ';'))]
        if single_header:
            rows = rows[1:]
        indexed = len(rows) > 1 and all(len(row) == 2 and row[0] == str(i + 1)
                                      for i, (_, row) in enumerate(rows))
    values = []
    for line, row in rows:
        if indexed:
            if len(row) != 2 or number(row[0]) != len(values) + 1:
                raise ValueError(f'Linha {line}: os períodos devem ser consecutivos, a partir de 1.')
            row = row[1:]
        try:
            values.extend(number(v) for v in row)
        except ValueError as error:
            raise ValueError(f'Linha {line}: {error}') from None
    return validate_pattern(values)


def read_series_file(path, kind):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    lines = text.splitlines()
    signature = lines[0].strip() if lines else ''
    notes, curve_type = None, None
    if signature == 'EPANET Curve Data':
        if kind != 'curve' or len(lines) < 3:
            raise ValueError('Arquivo CRV incompatível com este editor.')
        curve_type, notes = lines[1].strip().upper(), lines[2]
        text = '\n'.join(lines[3:])
    elif signature == 'EPANET Pattern Data':
        if kind != 'pattern' or len(lines) < 2:
            raise ValueError('Arquivo PAT incompatível com este editor.')
        notes, text = lines[1], '\n'.join(lines[2:])
    values = parse_curve_text(text) if kind == 'curve' else parse_pattern_text(text)
    return {'values': values, 'notes': notes, 'curve_type': curve_type}


def write_series_file(path, kind, props):
    path = Path(path)
    notes = ' '.join(props.get('notes', '').splitlines())
    if path.suffix.lower() == ('.crv' if kind == 'curve' else '.pat'):
        if kind == 'curve':
            lines = ['EPANET Curve Data', props['curve_type'], notes]
            lines += ['  '.join(text_number(v) for v in row) for row in props['points']]
        else:
            lines = ['EPANET Pattern Data', notes] + [text_number(v) for v in props['multipliers']]
        path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    else:
        output = io.StringIO(newline='')
        writer = csv.writer(output, delimiter=';', lineterminator='\n')
        if kind == 'curve':
            writer.writerow(CURVE_AXES[props['curve_type']])
            writer.writerows([[text_number(v) for v in row] for row in props['points']])
        else:
            writer.writerow(['Período', 'Multiplicador'])
            writer.writerows([[i, text_number(v)] for i, v in enumerate(props['multipliers'], 1)])
        path.write_text(output.getvalue(), encoding='utf-8-sig')
