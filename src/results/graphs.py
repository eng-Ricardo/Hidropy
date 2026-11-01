"""Dados dos gráficos hidráulicos, sem dependência da interface Qt."""

from __future__ import annotations

from collections import Counter
import csv
from dataclasses import dataclass, field
import heapq
import math


GRAPH_TYPES = {
    'time': 'Série temporal',
    'profile': 'Perfil da rede',
    'contour': 'Contorno',
    'frequency': 'Frequência acumulada',
    'system': 'Vazão do sistema',
}
NODE_PARAMETERS = {
    'pressure': 'Pressão (m)', 'head': 'Carga hidráulica (m)',
    'demand': 'Demanda / vazão nodal (L/s)', 'level': 'Nível do tanque (m)',
    'volume': 'Volume do tanque (m³)', 'elevation': 'Cota (m)',
}
LINK_PARAMETERS = {
    'flow': 'Vazão (L/s)', 'velocity': 'Velocidade (m/s)',
    'unit_headloss': 'Perda de carga unitária (m/km)', 'headloss': 'Perda de carga (m)',
    'friction_factor': 'Fator de atrito', 'status': 'Estado operacional',
}


class GraphError(ValueError):
    """Configuração ou dados insuficientes para representar o gráfico."""


@dataclass
class Series:
    label: str
    x: list[float]
    y: list[float | None]
    labels: list[str] = field(default_factory=list)


@dataclass
class GraphData:
    kind: str
    title: str
    x_label: str
    y_label: str
    series: list[Series] = field(default_factory=list)
    points: list[tuple[str, float, float, float]] = field(default_factory=list)
    edges: list[list[tuple[float, float]]] = field(default_factory=list)
    note: str = ''

    def rows(self):
        if self.kind == 'contour':
            return [{'Nó': name, self.x_label: x, 'Y (m)': y, self.y_label: value}
                    for name, x, y, value in self.points]
        rows = []
        has_labels = any(s.labels for s in self.series)
        for s in self.series:
            for i, (x, y) in enumerate(zip(s.x, s.y)):
                row = {'Série': s.label, self.x_label: x, self.y_label: y}
                if has_labels:
                    row['Nó'] = s.labels[i] if s.labels else ''
                rows.append(row)
        return rows


def parameters(collection):
    return NODE_PARAMETERS if collection == 'nodes' else LINK_PARAMETERS


def _number(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _elevation(node):
    ground = getattr(node, 'ground_elevation', None)
    return _number(ground if ground is not None else getattr(node, 'elevation', None))


def eligible_elements(project, collection, variable):
    net = project.network
    elements = net.nodes.values() if collection == 'nodes' else net.links.values()
    out = []
    for e in elements:
        if collection == 'nodes':
            if variable == 'pressure' and e.KIND != 'junction':
                continue  # pressão de tanque é nível, não pressão de atendimento
            if variable in ('level', 'volume') and e.KIND != 'tank':
                continue
            if variable == 'elevation' and _elevation(e) is None:
                continue
        elif variable in ('unit_headloss', 'friction_factor') and e.KIND != 'pipe':
            continue
        out.append(e)
    return sorted(out, key=lambda e: (e.name.casefold(), e.uid))


def _values(project, sim, collection, variable, uid):
    if collection == 'nodes' and variable == 'elevation':
        return [_elevation(project.network.nodes[uid])] * len(sim['times'])
    values = sim.get(collection, {}).get(uid, {}).get(variable)
    if values is None or len(values) != len(sim['times']):
        e = project.network.get(uid)
        raise GraphError(f'Série de {e.name if e else uid} ausente ou incompleta para o parâmetro.')
    return [_number(v) for v in values]


def _snapshot(project, sim, collection, variable, time_index):
    elements = eligible_elements(project, collection, variable)
    samples = []
    for e in elements:
        try:
            value = _values(project, sim, collection, variable, e.uid)[time_index]
        except GraphError:
            continue
        if value is not None:
            samples.append((e, value))
    if not samples:
        raise GraphError('Não há valores calculados para este parâmetro no instante escolhido.')
    return samples, len(elements) - len(samples)


def _profile_route(net, waypoints):
    adj = {uid: [] for uid in net.nodes}
    for link in net.links.values():
        if link.start not in adj or link.end not in adj:
            continue
        length = net.hydraulic_length(link) if link.KIND == 'pipe' else net.geometric_length(link)
        if not math.isfinite(length) or length < 0:
            continue
        adj[link.start].append((link.end, length))
        adj[link.end].append((link.start, length))
    route, distances = [waypoints[0]], [0.0]
    for start, end in zip(waypoints, waypoints[1:]):
        heap, costs, previous = [(0.0, start)], {start: 0.0}, {}
        while heap:
            cost, uid = heapq.heappop(heap)
            if cost != costs[uid]:
                continue
            if uid == end:
                break
            for other, length in adj[uid]:
                candidate = cost + length
                if other not in costs or candidate < costs[other]:
                    costs[other], previous[other] = candidate, uid
                    heapq.heappush(heap, (candidate, other))
        if end not in costs:
            raise GraphError(f"Não há caminho cadastrado entre '{net.nodes[start].name}' "
                             f"e '{net.nodes[end].name}'.")
        segment, uid = [end], end
        while uid != start:
            uid = previous[uid]
            segment.append(uid)
        offset = distances[-1]
        for uid in reversed(segment[:-1]):
            route.append(uid)
            distances.append(offset + costs[uid])
    return route, distances


def build_graph(project, sim, kind='time', collection='nodes', variable='pressure',
                uids=(), time_index=0):
    if not sim or sim.get('status') != 'ok' or not sim.get('times'):
        raise GraphError('Execute uma simulação (F5) antes de gerar gráficos.')
    times = [_number(t) for t in sim['times']]
    if any(t is None for t in times) or any(a >= b for a, b in zip(times, times[1:])):
        raise GraphError('Os instantes de simulação estão incompletos ou fora de ordem.')
    if kind not in GRAPH_TYPES or collection not in ('nodes', 'links'):
        raise GraphError('Tipo de gráfico ou de objeto inválido.')
    if not 0 <= time_index < len(times):
        raise GraphError('Instante fora do período calculado.')
    hrs = [t / 3600 for t in times]
    if kind == 'system':
        data = GraphData(kind, 'Vazão do sistema', 'Tempo (h)', 'Vazão (L/s)')
        for node_kind, label, sign in (
                ('reservoir', 'Fornecimento dos reservatórios', -1),
                ('junction', 'Demanda nas junções', 1),
                ('tank', 'Armazenamento nos tanques', 1)):
            values = [_values(project, sim, 'nodes', 'demand', e.uid)
                      for e in project.network.nodes.values() if e.KIND == node_kind]
            totals = [None if any(row[i] is None for row in values)
                      else sign * sum(row[i] for row in values) for i in range(len(times))]
            data.series.append(Series(label, hrs, totals))
        data.note = ('Vazões líquidas. Armazenamento positivo = enchimento; '
                     'negativo = esvaziamento. Dados de regime permanente têm um único instante.')
        return data

    if kind in ('profile', 'contour') and collection != 'nodes':
        raise GraphError('Perfis e contornos representam somente nós.')
    if variable not in parameters(collection):
        raise GraphError('Parâmetro inválido para este tipo de objeto.')
    label = parameters(collection)[variable]
    at = f'{hrs[time_index]:g} h'
    if kind in ('frequency', 'contour'):
        samples, missing = _snapshot(project, sim, collection, variable, time_index)
        if kind == 'frequency':
            counts = Counter(value for _, value in samples)
            values = sorted(counts)
            total, percents = 0, []
            for value in values:
                total += counts[value]
                percents.append(100.0 * total / len(samples))
            return GraphData(kind, f'Frequência acumulada — {at}', label,
                             'Percentual acumulado (%)', [Series(label, values, percents)],
                             note=f'{len(samples)} elementos com dados; {missing} sem valor. '
                                  'Cada ponto indica a fração com valor menor ou igual ao indicado.')
        unique = {}
        for node, value in samples:
            if _number(node.x) is None or _number(node.y) is None:
                continue
            key = (node.x, node.y)
            if key in unique and not math.isclose(unique[key][1], value, abs_tol=1e-8):
                raise GraphError('Há nós coincidentes com valores diferentes. Revise a geometria.')
            unique[key] = (node, value)
        points = [(n.name, n.x, n.y, v) for n, v in unique.values()]
        if len(points) < 3:
            raise GraphError('O contorno exige pelo menos três nós com posições distintas.')
        x0, y0 = points[0][1:3]
        vectors = [(x - x0, y - y0) for _, x, y, _ in points[1:]]
        scale = max(max(abs(x), abs(y)) for x, y in vectors)
        ax, ay = max(vectors, key=lambda p: p[0] ** 2 + p[1] ** 2)
        if not any(abs(ax * by - ay * bx) > 1e-10 * max(scale ** 2, 1)
                   for bx, by in vectors):
            raise GraphError('Não é possível gerar contorno com todos os nós alinhados.')
        return GraphData(kind, f'Contorno — {label} — {at}', 'X (m)', label, points=points,
                         edges=[project.network.link_points(l) for l in project.network.links.values()],
                         note='Interpolação linear entre nós, limitada à área dos pontos. '
                              'As faixas interpoladas não são novos resultados do motor hidráulico.')

    eligible = {e.uid: e for e in eligible_elements(project, collection, variable)}
    uids = list(dict.fromkeys(uids))
    if not uids:
        raise GraphError('Adicione os nós ou trechos que deseja representar.')
    if any(uid not in eligible for uid in uids):
        raise GraphError('Há elementos incompatíveis com o parâmetro escolhido. Revise a seleção.')
    if kind == 'time':
        data = GraphData(kind, f'Série temporal — {label}', 'Tempo (h)', label)
        for uid in uids:
            values = _values(project, sim, collection, variable, uid)
            if not any(v is not None for v in values):
                raise GraphError(f'{eligible[uid].name} não possui valores válidos para este parâmetro.')
            data.series.append(Series(eligible[uid].name, hrs, values))
        data.note = 'Vazão negativa indica sentido oposto ao cadastro.' if variable == 'flow' else ''
        if len(times) == 1:
            data.note += ' Regime permanente: há apenas um instante calculado.'
        return data
    if len(uids) < 2:
        raise GraphError('Adicione pelo menos dois nós, na ordem desejada, para gerar o perfil.')
    route, distances = _profile_route(project.network, uids)
    values, labels = [], []
    for uid in route:
        if uid not in eligible:
            raise GraphError('O percurso contém nós incompatíveis com este parâmetro. '
                             'Escolha carga hidráulica para incluir reservatórios e tanques.')
        values.append(_values(project, sim, 'nodes', variable, uid)[time_index])
        labels.append(project.network.nodes[uid].name)
    if not any(v is not None for v in values):
        raise GraphError('Não há valores válidos no percurso escolhido.')
    data = GraphData(kind, f'Perfil da rede — {at}', 'Distância acumulada (m)', label,
                     [Series(label, distances, values, labels)],
                     note='Menor percurso cadastrado entre os nós escolhidos, na ordem da lista. '
                          'Tubos usam comprimento hidráulico; bombas e válvulas usam o geométrico.')
    if variable == 'head':
        data.y_label = 'Carga / cota (m)'
        data.series.append(Series('Cota do terreno / fundo', distances,
                                  [_elevation(project.network.nodes[uid]) for uid in route], labels))
    return data


def export_csv(data, path):
    rows = data.rows()
    if not rows:
        raise GraphError('O gráfico não possui dados para exportar.')
    with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), delimiter=';')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: '' if value is None else
                             format(value, '.12g').replace('.', ',') if isinstance(value, float)
                             else value for key, value in row.items()})
