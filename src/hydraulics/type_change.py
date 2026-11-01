"""Troca reversível de tipos, sem alterar a identidade nem a conectividade."""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field

from .models import Junction, Reservoir, Tank, Pipe, Pump, Valve, KIND_LABELS
from .schema import SCHEMA
from .validation import valve_connection_issues

TYPES = {c.KIND: c for c in (Junction, Reservoir, Tank, Pipe, Pump, Valve)}
NODE_TYPES = ('junction', 'reservoir', 'tank')
LINK_TYPES = ('pipe', 'pump', 'valve')
PROTECTED = {'uid', 'name', 'layer', 'notes', 'source_data', 'x', 'y', 'start', 'end', 'vertices', 'kind'}


class TypeChangeError(ValueError):
    pass


@dataclass
class ControlConflict:
    uid: str
    name: str
    reason: str


@dataclass
class TypeChangePlan:
    candidates: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    conflicts: list[ControlConflict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ready: bool = False


def selection_types(project, uids):
    elements = [project.get(uid) for uid in dict.fromkeys(uids)]
    if not elements or any(e is None or e.KIND not in TYPES for e in elements):
        return ()
    if any(project.layer_locked(e.layer) for e in elements):
        return ()
    kinds = {e.KIND for e in elements}
    if kinds <= set(NODE_TYPES):
        return NODE_TYPES
    if kinds <= set(LINK_TYPES):
        return LINK_TYPES
    return ()


def draft_element(project, source, target):
    """Rascunho: None exige preenchimento; nunca confunde carga com cota."""
    if target not in TYPES or source.KIND not in TYPES or \
            TYPES[target].COLLECTION != source.COLLECTION:
        raise TypeChangeError('A troca exige tipos da mesma categoria hidráulica.')
    if source.KIND == target:
        return source.clone()
    common = {'uid': source.uid, 'name': source.name, 'notes': source.notes,
              'source_data': copy.deepcopy(source.source_data),
              'layer': TYPES[target].DEFAULT_LAYER if source.layer == source.DEFAULT_LAYER
              else source.layer}
    if source.COLLECTION == 'node':
        common.update(x=source.x, y=source.y)
        elevation = getattr(source, 'elevation', getattr(source, 'ground_elevation', None))
        if target == 'junction':
            return Junction(**common, elevation=elevation, ground_elevation=source.ground_elevation)
        if target == 'reservoir':
            head = source.elevation + source.init_level if source.KIND == 'tank' and \
                all(isinstance(v, (int, float)) and math.isfinite(v)
                    for v in (source.elevation, source.init_level)) else None
            return Reservoir(**common, head=head, ground_elevation=(source.ground_elevation
                             if source.ground_elevation is not None else elevation))
        level = source.head - elevation if source.KIND == 'reservoir' and \
            all(isinstance(v, (int, float)) and math.isfinite(v)
                for v in (source.head, elevation)) else None
        return Tank(**common, elevation=elevation, ground_elevation=source.ground_elevation,
                    init_level=level, max_level=None, diameter=None)
    common.update(start=source.start, end=source.end, vertices=copy.deepcopy(source.vertices))
    closed = source.status == 'Closed'
    if target == 'pump':
        return Pump(**common, status='Closed' if closed else 'Open')
    diameter = getattr(source, 'diameter', None)
    minor = getattr(source, 'minor_loss', 0.0)
    if target == 'valve':
        return Valve(**common, diameter=diameter, minor_loss=minor, setting=None,
                     status='Closed' if closed else 'None')
    length = project.network.geometric_length(source)
    return Pipe(**common, diameter=diameter, minor_loss=minor, roughness=None,
                length=length, auto_length=length > 0, material='', distributes=False,
                status='Closed' if closed else 'Open')


def discarded_properties(source, candidate):
    """Inclui dados exclusivos e ajustes antigos com significado incompatível."""
    target = candidate.to_dict()
    labels = {p.key: p.label for p in SCHEMA[source.KIND]}
    changed_settings = {'status', 'valve_type', 'setting', 'headloss_curve'}
    return [(labels.get(k, k), v) for k, v in source.to_dict().items()
            if k != 'kind' and (k not in target or
                               (k in changed_settings and v != target[k]))]


def _check(candidate, project):
    e, net = candidate, project.network
    prefix = f"{KIND_LABELS[e.KIND]} '{e.name}': "

    def fail(message):
        raise TypeChangeError(prefix + message)

    for prop in SCHEMA[e.KIND]:
        value = getattr(e, prop.key, None)
        if prop.type in ('float', 'float_opt'):
            if value is None and prop.type == 'float_opt':
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                fail(f'informe {prop.label.lower()} com um número finito.')
            if prop.min is not None and value < prop.min:
                fail(f'{prop.label} deve ser ≥ {prop.min:g}.')
        if prop.type == 'ref_pattern' and value and value not in net.patterns:
            fail(f'{prop.label}: padrão inexistente.')
    curve_fields = {'pump': ('curve', 'PUMP'), 'tank': ('volume_curve', 'VOLUME'),
                    'valve': ('headloss_curve', 'HEADLOSS')}
    if e.KIND in curve_fields:
        key, kind = curve_fields[e.KIND]
        uid = getattr(e, key)
        if uid:
            curve = net.curves.get(uid)
            if curve is None or curve.curve_type != kind:
                fail(f'a curva escolhida deve existir e ser do tipo {kind}.')
            pts = curve.points
            if not pts or any(not isinstance(p, (list, tuple)) or len(p) != 2 or any(not isinstance(v, (int, float)) or
                    not math.isfinite(v) for v in p) for p in pts):
                fail('a curva escolhida contém pontos inválidos.')
            if any(b[0] <= a[0] for a, b in zip(pts, pts[1:])):
                fail('a curva deve ter abscissas estritamente crescentes.')
            if kind != 'PUMP' and len(pts) < 2:
                fail('a curva exige pelo menos dois pontos.')
    if e.KIND == 'junction':
        if e.emitter_coeff < 0:
            fail('o coeficiente do emissor deve ser ≥ 0.')
    elif e.KIND == 'tank':
        if not 0 <= e.min_level <= e.init_level <= e.max_level or e.max_level <= e.min_level:
            fail('exige 0 ≤ mínimo ≤ inicial ≤ máximo, com máximo > mínimo.')
        if e.min_volume < 0 or (not e.volume_curve and e.diameter <= 0):
            fail('informe volume mínimo ≥ 0 e diâmetro > 0 ou curva de volume.')
    elif e.KIND in LINK_TYPES:
        if e.start not in net.nodes or e.end not in net.nodes or e.start == e.end:
            fail('as extremidades devem ser dois nós distintos existentes.')
        if e.KIND == 'pipe':
            if e.diameter <= 0 or e.roughness <= 0 or net.hydraulic_length(e) <= 0 or e.minor_loss < 0:
                fail('informe diâmetro, comprimento e rugosidade > 0; perda localizada ≥ 0.')
            if e.status not in ('Open', 'Closed', 'CV'):
                fail('estado da tubulação inválido.')
        elif e.KIND == 'pump':
            if (bool(e.curve) and e.power is not None) or (not e.curve and (e.power is None or e.power <= 0)):
                fail('escolha uma curva de bomba OU informe potência > 0 (kW).')
            if e.speed < 0 or e.status not in ('Open', 'Closed'):
                fail('velocidade relativa ou estado da bomba inválido.')
        else:
            if e.valve_type not in ('PRV', 'PSV', 'PBV', 'FCV', 'TCV', 'GPV'):
                fail('tipo de válvula inválido.')
            if e.diameter <= 0 or e.minor_loss < 0 or e.status not in ('None', 'Open', 'Closed'):
                fail('diâmetro, perda localizada ou estado da válvula inválido.')
            if e.valve_type == 'GPV':
                if not e.headloss_curve:
                    fail('GPV exige curva de perda de carga.')
            elif e.setting < 0:
                fail('o ajuste da válvula deve ser ≥ 0.')


def plan_type_change(project, uids, target, properties=None, remove_controls=False):
    """Não modifica o projeto. Controles incompatíveis bloqueiam changes até consentimento."""
    uids = list(dict.fromkeys(uids))
    if target not in selection_types(project, uids):
        raise TypeChangeError('Selecione apenas nós ou apenas ligações, em camadas desbloqueadas.')
    properties = copy.deepcopy(properties or {})
    allowed = {p.key for p in SCHEMA[target] if p.key not in PROTECTED and p.type != 'computed'}
    if set(properties) - allowed:
        raise TypeChangeError('A troca não pode alterar identidade, geometria ou conexões.')
    plan = TypeChangePlan()
    before_after = {}
    for uid in uids:
        source = project.get(uid)
        if source.KIND == target and target != 'valve':
            continue
        candidate = draft_element(project, source, target)
        for key, value in properties.items():
            setattr(candidate, key, copy.deepcopy(value))
        if target == 'valve':
            changed_type = source.KIND != 'valve' or source.valve_type != candidate.valve_type
            if changed_type and candidate.valve_type != 'GPV' and 'setting' not in properties:
                raise TypeChangeError(f"'{source.name}': informe o novo ajuste e confira a unidade da válvula.")
            if changed_type and candidate.valve_type == 'GPV' and 'headloss_curve' not in properties:
                raise TypeChangeError(f"'{source.name}': escolha a curva de perda para a nova GPV.")
            if candidate.valve_type == 'GPV':
                candidate.setting = 0.0  # GPV usa a curva, não um ajuste numérico.
            else:
                candidate.headloss_curve = ''
        if target == 'tank' and candidate.volume_curve and candidate.diameter is None:
            candidate.diameter = 0.0  # Geometria não circular definida pela curva de volume.
        if project.layer_locked(candidate.layer):
            raise TypeChangeError(f"A camada de destino '{candidate.layer}' está bloqueada.")
        _check(candidate, project)
        if source.to_dict() == candidate.to_dict():
            continue
        before_after[uid] = (source, candidate)
        plan.candidates.append(candidate)
        if not project.layer_visible(candidate.layer):
            plan.warnings.append(f"'{source.name}': camada de destino '{candidate.layer}' oculta.")
    net = copy.copy(project.network)
    net.nodes, net.links = project.network.nodes.copy(), project.network.links.copy()
    for candidate in plan.candidates:
        net.put(candidate)
    old_issues = {(i.code, i.uid, i.message) for i in valve_connection_issues(project.network)}
    introduced = [i for i in valve_connection_issues(net) if (i.code, i.uid, i.message) not in old_issues]
    if introduced:
        raise TypeChangeError(introduced[0].message)
    for c in net.controls.values():
        reasons = []
        if c.node in before_after and c.condition.startswith('IF NODE'):
            old, new = before_after[c.node]
            if old.KIND != new.KIND:
                reasons.append('a condição por pressão/nível não se aplica ao novo tipo de nó')
        if c.link in before_after:
            old, new = before_after[c.link]
            if new.KIND == 'pipe' and new.status == 'CV':
                reasons.append('tubulação com retenção (CV) não admite controles')
            elif c.action.upper() not in ('OPEN', 'CLOSED') and (
                    old.KIND != new.KIND or (new.KIND == 'valve' and old.valve_type != new.valve_type)):
                reasons.append('o ajuste numérico tem significado/unidade incompatível')
        if reasons:
            plan.conflicts.append(ControlConflict(c.uid, c.name, '; '.join(reasons)))
    if any(n.KIND in ('tank', 'reservoir') for n in project.network.nodes.values()) and \
            not any(n.KIND in ('tank', 'reservoir') for n in net.nodes.values()):
        plan.warnings.append('A rede ficará sem fonte de carga. Adicione reservatório ou tanque antes de simular.')
    plan.ready = bool(plan.candidates) and (not plan.conflicts or remove_controls)
    if plan.ready:
        plan.changes = [(uid, old.to_dict(), new.to_dict()) for uid, (old, new) in before_after.items()]
        plan.changes += [(c.uid, net.controls[c.uid].to_dict(), None) for c in plan.conflicts]
    return plan
