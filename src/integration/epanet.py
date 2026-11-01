"""Execução hidráulica com validação de convergência e integridade dos resultados."""

from pathlib import Path
import sys

import numpy as np


def execution_metadata(wn):
    """Registra o ambiente e as opções efetivamente enviados ao motor."""
    import wntr

    return {'python': sys.version.split()[0], 'platform': sys.platform,
            'wntr': wntr.__version__, 'numpy': np.__version__, 'epanet': '2.2',
            'hydraulic_options': dict(vars(wn.options.hydraulic)),
            'time_options': dict(vars(wn.options.time))}


def run_epanet(wn, prefix):
    import wntr

    result = wntr.sim.EpanetSimulator(wn).run_sim(
        file_prefix=str(prefix), convergence_error=True)
    report_path = Path(str(prefix) + '.rpt')
    report = report_path.read_text(encoding='utf-8', errors='replace') \
        if report_path.exists() else ''
    # Em regime permanente o binário pode conter uma linha mesmo sem convergir.
    if any(message in report.upper() for message in (
            'SYSTEM UNBALANCED', 'EXECUTION HALTED', 'HYDRAULICALLY UNBALANCED')):
        raise RuntimeError('O EPANET não convergiu; consulte o relatório de cálculo.')
    if getattr(result, 'error_code', None) is not None:
        raise RuntimeError('O EPANET devolveu resultados parciais ou com erro.')

    time = wn.options.time
    expected = list(range(int(time.report_start), int(time.duration) + 1,
                          int(time.report_timestep)))
    if not expected:
        raise RuntimeError('O início do relatório é posterior à duração da simulação.')
    for group, fields, names in (
            (result.node, ('pressure', 'head', 'demand'), wn.node_name_list),
            (result.link, ('flowrate', 'velocity', 'headloss'), wn.link_name_list)):
        for field in fields:
            frame = group.get(field)
            if frame is None or list(frame.index) != expected or \
                    set(frame.columns) != set(names):
                raise RuntimeError(f'Resultado hidráulico incompleto: {field}.')
            if not np.isfinite(frame.to_numpy()).all():
                raise RuntimeError(f'Resultado hidráulico não finito: {field}.')
    return result
