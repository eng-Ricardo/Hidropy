"""Planejamento reversível da renumeração, conforme a Suite EPANET 4.9.

Somente nomes de junções e tubulações mudam. Referências continuam usando UIDs.
"""

from __future__ import annotations

from collections import deque
import csv
from dataclasses import dataclass, field
import math
import re

from . import editing


METHODS = {
    'coord-x': 'Geométrico: Oeste → Leste (X)',
    'coord-y': 'Geométrico: Norte → Sul (Y)',
    'original': 'Manter ordem original',
    'hydraulic': 'Topológico hidráulico',
}


class RenumberError(ValueError):
    pass


@dataclass
class RenumberSettings:
    method: str = 'coord-x'
    rename_nodes: bool = True
    rename_pipes: bool = True
    node_prefix: str = 'J-'
    pipe_prefix: str = 'P-'
    node_digits: int = 3
    pipe_digits: int = 3
    node_start: int = 1
    pipe_start: int = 1


@dataclass
class RenumberItem:
    uid: str
    kind: str
    old_name: str
    new_name: str
    flow: float | None = None


@dataclass
class RenumberPlan:
    items: list[RenumberItem] = field(default_factory=list)
    changes: list = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def node_count(self):
        return sum(item.kind == 'junction' for item in self.items)

    @property
    def pipe_count(self):
        return sum(item.kind == 'pipe' for item in self.items)


def _names(elements, prefix, digits, start, label):
    if not isinstance(prefix, str) or re.search(r'[\s;"\x00-\x1f\x7f]', prefix):
        raise RenumberError(f'Prefixo de {label}: não use espaços, ponto e vírgula, '
                            'aspas ou caracteres de controle.')
    if type(digits) is not int or not 1 <= digits <= 6:
        raise RenumberError(f'{label}: use entre 1 e 6 dígitos.')
    if type(start) is not int or start < 1:
        raise RenumberError(f'{label}: o número inicial deve ser um inteiro maior que zero.')
    names = {e.uid: f'{prefix}{str(start + i).zfill(digits)}' for i, e in enumerate(elements)}
    if any(len(name) > 31 for name in names.values()):
        raise RenumberError(f'Os novos identificadores de {label} ultrapassam 31 caracteres.')
    return names


def _check_names(elements, names, label):
    seen = {}
    for element in elements:
        name = names.get(element.uid, element.name)
        if name in seen:
            raise RenumberError(f"O identificador '{name}' fica duplicado em {label}. "
                                'Altere o prefixo ou o número inicial. Nomes de reservatórios, '
                                'tanques, bombas e válvulas são preservados.')
        seen[name] = element.uid


def hydraulic_flows(project, simulation, time_index):
    from ..integration.input_exporter import network_hash

    if not simulation or simulation.get('status') != 'ok':
        raise RenumberError('Execute uma simulação (F5) para usar a ordem hidráulica.')
    if simulation.get('inp_sha256') != network_hash(project):
        raise RenumberError('A rede mudou após o cálculo. Execute novamente a simulação (F5) '
                            'para usar a ordem hidráulica.')
    times = simulation.get('times') or []
    if not 0 <= time_index < len(times):
        raise RenumberError('Escolha um instante calculado para a ordem hidráulica.')
    flows = {}
    for uid, link in project.network.links.items():
        series = simulation.get('links', {}).get(uid, {}).get('flow')
        try:
            if series is None or len(series) != len(times) or series[time_index] is None:
                raise ValueError()
            value = float(series[time_index])
            if not math.isfinite(value):
                raise ValueError()
        except (TypeError, ValueError, IndexError):
            raise RenumberError(f"Vazão de '{link.name}' ausente ou inválida no instante escolhido. "
                                'Execute novamente a simulação.') from None
        flows[uid] = value
    return flows


def _hydraulic_order(net, junctions, flows):
    adj = {uid: [] for uid in net.nodes}
    for link in net.links.values():
        if link.start not in adj or link.end not in adj:
            raise RenumberError(f"A ligação '{link.name}' possui extremidade inexistente.")
        start, end = (link.start, link.end) if flows[link.uid] >= 0 else (link.end, link.start)
        adj[start].append(end)
    sources = [n.uid for kind in ('reservoir', 'tank') for n in net.nodes.values() if n.KIND == kind]
    queue, visited, ordered = deque(sources), set(sources), []
    wanted = {n.uid: n for n in junctions}
    while queue:
        uid = queue.popleft()
        if uid in wanted:
            ordered.append(wanted[uid])
        for other in adj[uid]:
            if other not in visited:
                visited.add(other)
                queue.append(other)
    remaining = [n for n in junctions if n.uid not in visited]
    return ordered + remaining, remaining


def plan_renumber(project, settings=None, simulation=None, time_index=0):
    """Devolve correspondência e alterações; não modifica o projeto.

    A ordem geométrica afeta somente junções, como na suíte. No modo hidráulico,
    junções seguem BFS a partir das fontes e tubos seguem |Q| decrescente.
    Empates e elementos não alcançados preservam a ordem de cadastro.
    """
    settings = settings or RenumberSettings()
    if settings.method not in METHODS:
        raise RenumberError('Método de renumeração inválido.')
    if not settings.rename_nodes and not settings.rename_pipes:
        raise RenumberError('Marque junções e/ou tubulações para renumerar.')
    net = project.network
    junctions = [n for n in net.nodes.values() if n.KIND == 'junction']
    pipes = [link for link in net.links.values() if link.KIND == 'pipe']
    warnings, flows = [], {}
    if settings.method in ('coord-x', 'coord-y') and settings.rename_nodes:
        axis = 'x' if settings.method == 'coord-x' else 'y'
        for node in junctions:
            value = getattr(node, axis)
            if not isinstance(value, (int, float)) or not math.isfinite(value):
                raise RenumberError(f"Coordenada {axis.upper()} de '{node.name}' inválida.")
        junctions = sorted(junctions, key=lambda n: n.x if axis == 'x' else -n.y)
    elif settings.method == 'hydraulic':
        flows = hydraulic_flows(project, simulation, time_index)
        junctions, remaining = _hydraulic_order(net, junctions, flows)
        pipes = sorted(pipes, key=lambda p: -abs(flows[p.uid]))
        if remaining and settings.rename_nodes:
            names = ', '.join(n.name for n in remaining[:10])
            suffix = '…' if len(remaining) > 10 else ''
            warnings.append(f'{len(remaining)} junção(ões) não alcançada(s) a partir das fontes '
                            f'pelos sentidos de vazão; adicionadas ao final: {names}{suffix}.')
    node_names = _names(junctions, settings.node_prefix, settings.node_digits,
                        settings.node_start, 'junções') if settings.rename_nodes else {}
    pipe_names = _names(pipes, settings.pipe_prefix, settings.pipe_digits,
                        settings.pipe_start, 'tubulações') if settings.rename_pipes else {}
    _check_names(net.nodes.values(), node_names, 'nós')
    _check_names(net.links.values(), pipe_names, 'ligações')
    items = [RenumberItem(e.uid, e.KIND, e.name, names[e.uid], flows.get(e.uid))
             for elements, names in ((junctions, node_names), (pipes, pipe_names))
             for e in elements if e.uid in names]
    if not items:
        raise RenumberError('Não há junções ou tubulações para renumerar neste cenário.')
    changes = editing.update_many(project, [(item.uid, {'name': item.new_name}) for item in items])
    return RenumberPlan(items, changes, warnings)


def export_mapping(plan, path):
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream, delimiter=';', quoting=csv.QUOTE_ALL)
        writer.writerow(['Tipo', 'ID anterior', 'Novo ID', 'UID'])
        for item in plan.items:
            writer.writerow(['Junção' if item.kind == 'junction' else 'Tubulação',
                             item.old_name, item.new_name, item.uid])
