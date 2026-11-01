"""Identidade, hidráulica, controles, interface e reversibilidade das trocas."""

import copy
from itertools import permutations

import pytest

from src.hydraulics.models import (CadEntity, Control, Curve, Junction, Pipe, Pump,
                                    Reservoir, Tank, Valve)
from src.hydraulics.project import Project
from src.hydraulics.project_io import load_project, save_project
from src.hydraulics.type_change import (LINK_TYPES, NODE_TYPES, TypeChangeError,
                                        discarded_properties, draft_element,
                                        plan_type_change, selection_types)
from src.hydraulics.validation import validate, valve_connection_issues
from src.integration.input_exporter import network_hash


@pytest.fixture
def project():
    p = Project()
    by = {}
    for e in [Reservoir(name='R', x=-100, head=60, ground_elevation=10),
              Tank(name='T', x=300, elevation=10, init_level=5, max_level=10, diameter=5),
              Junction(name='J1', x=0, elevation=12, base_demand=2),
              Junction(name='J2', x=200, elevation=14)]:
        p.network.put(e)
        by[e.name] = e
    for e in [Pipe(name='P', start=by['J1'].uid, end=by['J2'].uid, diameter=200,
                    minor_loss=3, vertices=[[80, 20], [120, 30]], auto_length=False,
                    length=230, notes='Observação original', fixed_in_optimization=True),
              Pump(name='B', start=by['J2'].uid, end=by['J1'].uid, power=10),
              Valve(name='V', start=by['J1'].uid, end=by['J2'].uid, valve_type='TCV',
                    diameter=150, setting=2)]:
        p.network.put(e)
    return p


def element(project, name):
    return project.network.find_by_name(name)


def parameters(target):
    return {'junction': {}, 'reservoir': {'head': 40},
            'tank': {'init_level': 2, 'max_level': 5, 'diameter': 4},
            'pipe': {'diameter': 160, 'roughness': 130},
            'pump': {'power': 5},
            'valve': {'valve_type': 'TCV', 'setting': 3}}[target]


@pytest.mark.parametrize('source,target', list(permutations(NODE_TYPES, 2)) + list(permutations(LINK_TYPES, 2)))
def test_every_same_category_conversion_keeps_identity_geometry_and_connections(project, source, target):
    src = next(e for e in project.network.elements() if e.KIND == source)
    before = copy.deepcopy(project.network.to_dict())
    adjacency = copy.deepcopy(project.network.adjacency())
    props = parameters(target)
    if source == 'pump' and target == 'valve':
        props['diameter'] = 160  # Bombas não têm diâmetro hidráulico no modelo.
    plan = plan_type_change(project, [src.uid], target, props)
    assert plan.ready and len(plan.changes) == 1
    new = plan.candidates[0]
    assert new.KIND == target
    for key in ('uid', 'name', 'notes'):
        assert getattr(new, key) == getattr(src, key)
    if source in NODE_TYPES:
        assert (new.x, new.y) == (src.x, src.y)
    else:
        assert (new.start, new.end, new.vertices) == (src.start, src.end, src.vertices)
        assert new.vertices is not src.vertices
    assert project.network.to_dict() == before
    assert project.network.adjacency() == adjacency
    assert new.layer == new.DEFAULT_LAYER


@pytest.mark.parametrize('selection,target', [(['J1'], 'pipe'), (['P'], 'tank'),
                                            (['J1', 'P'], 'pipe'), ([], 'pipe')])
def test_incompatible_categories_are_rejected(project, selection, target):
    with pytest.raises(TypeChangeError):
        plan_type_change(project, [element(project, name).uid for name in selection], target)


def test_cad_missing_and_locked_elements_cannot_be_changed(project):
    cad = CadEntity(name='CAD')
    project.put(cad)
    assert selection_types(project, [cad.uid]) == ()
    assert selection_types(project, ['missing']) == ()
    pipe = element(project, 'P')
    project.layer_by_name(pipe.layer).locked = True
    assert selection_types(project, [pipe.uid]) == ()
    with pytest.raises(TypeChangeError):
        plan_type_change(project, [pipe.uid], 'pump', {'power': 1})


def test_custom_layers_are_kept_and_locked_default_destination_is_rejected(project):
    src = element(project, 'P')
    src.layer = 'Setor 2'
    assert plan_type_change(project, [src.uid], 'pump', {'power': 1}).candidates[0].layer == 'Setor 2'
    src.layer = src.DEFAULT_LAYER
    project.layer_by_name('Bombas').locked = True
    with pytest.raises(TypeChangeError, match='destino'):
        plan_type_change(project, [src.uid], 'pump', {'power': 1})


def test_batch_keeps_individual_diameters_minor_losses_and_geometry(project):
    a = element(project, 'P')
    b = Pipe(name='P2', start=a.start, end=a.end, diameter=350, minor_loss=4, length=220,
             auto_length=False, vertices=[[100, -20]])
    project.network.put(b)
    plan = plan_type_change(project, [a.uid, b.uid], 'valve', parameters('valve'))
    assert plan.ready
    assert [(e.diameter, e.minor_loss, e.vertices) for e in plan.candidates] == [
        (a.diameter, a.minor_loss, a.vertices), (b.diameter, b.minor_loss, b.vertices)]
    assert len(plan.changes) == 2


def test_members_already_of_target_kind_are_kept_even_with_overrides(project):
    p, b = element(project, 'P'), element(project, 'B')
    plan = plan_type_change(project, [p.uid, b.uid, b.uid], 'pipe', parameters('pipe'))
    assert [c.uid for c in plan.candidates] == [b.uid]
    assert project.get(p.uid).diameter == 200


def test_unknown_terrain_is_not_inferred_from_reservoir_head_and_pump_requires_data(project):
    r = element(project, 'R')
    r.ground_elevation = None
    assert draft_element(project, r, 'junction').elevation is None
    with pytest.raises(TypeChangeError, match='cota'):
        plan_type_change(project, [r.uid], 'junction')
    assert plan_type_change(project, [r.uid], 'junction', {'elevation': 12}).ready
    j = element(project, 'J1')
    assert draft_element(project, j, 'reservoir').head is None
    with pytest.raises(TypeChangeError, match='carga'):
        plan_type_change(project, [j.uid], 'reservoir')
    with pytest.raises(TypeChangeError, match='potência'):
        plan_type_change(project, [element(project, 'P').uid], 'pump')
    t = element(project, 'T')
    assert plan_type_change(project, [t.uid], 'reservoir').candidates[0].head == t.elevation + t.init_level


@pytest.mark.parametrize('target,props', [
    ('pump', {'power': float('nan')}), ('pump', {'power': float('inf')}),
    ('pump', {'power': -1}), ('pump', {'power': 0}),
    ('pump', {'power': 1, 'speed': -1}),
    ('pipe', {'roughness': 0}), ('pipe', {'roughness': float('nan')}),
    ('tank', {'init_level': 6, 'max_level': 5, 'diameter': 4}),
    ('tank', {'init_level': 1, 'max_level': 5, 'diameter': 0}),
    ('tank', {'init_level': 1, 'max_level': 5, 'diameter': 4, 'min_volume': -1}),
])
def test_invalid_hydraulic_values_do_not_create_a_plan(project, target, props):
    src = element(project, 'R' if target == 'tank' else 'V' if target == 'pipe' else 'P')
    before = copy.deepcopy(project.network.to_dict())
    with pytest.raises(TypeChangeError):
        plan_type_change(project, [src.uid], target, props)
    assert project.network.to_dict() == before


def test_new_pipes_require_roughness_and_use_geometry_without_inventing_material(project):
    src = element(project, 'V')
    with pytest.raises(TypeChangeError, match='rugosidade'):
        plan_type_change(project, [src.uid], 'pipe')
    new = plan_type_change(project, [src.uid], 'pipe', {'roughness': .0015}).candidates[0]
    assert new.length == pytest.approx(project.network.geometric_length(src))
    assert new.auto_length and new.material == '' and not new.distributes
    assert new.diameter == src.diameter


def test_typed_curves_and_non_circular_tank_geometry(project):
    p = element(project, 'P')
    pump_curve = Curve(name='HB', curve_type='PUMP', points=[[10, 30]])
    volume = Curve(name='VT', curve_type='VOLUME', points=[[0, 0], [10, 100]])
    for c in (pump_curve, volume):
        project.network.put(c)
    assert plan_type_change(project, [p.uid], 'pump', {'curve': pump_curve.uid}).ready
    with pytest.raises(TypeChangeError, match='PUMP'):
        plan_type_change(project, [p.uid], 'pump', {'curve': volume.uid})
    with pytest.raises(TypeChangeError, match='OU'):
        plan_type_change(project, [p.uid], 'pump', {'curve': pump_curve.uid, 'power': 1})
    tank = plan_type_change(project, [element(project, 'J1').uid], 'tank',
                            {'init_level': 1, 'max_level': 5, 'volume_curve': volume.uid}).candidates[0]
    assert tank.diameter == 0 and tank.volume_curve == volume.uid


def test_valve_subtype_requires_fresh_setting_and_gpv_requires_headloss_curve(project):
    v = element(project, 'V')
    with pytest.raises(TypeChangeError, match='novo ajuste'):
        plan_type_change(project, [v.uid], 'valve', {'valve_type': 'FCV'})
    assert plan_type_change(project, [v.uid], 'valve', {'valve_type': 'FCV', 'setting': 3}).ready
    curve = Curve(name='HL', curve_type='HEADLOSS', points=[[0, 0], [20, 10]])
    project.network.put(curve)
    plan = plan_type_change(project, [v.uid], 'valve', {'valve_type': 'GPV', 'headloss_curve': curve.uid})
    assert plan.ready and plan.candidates[0].setting == 0
    v2 = plan.candidates[0]
    project.network.put(v2)
    changed = plan_type_change(project, [v.uid], 'valve', {'valve_type': 'FCV', 'setting': 5})
    assert dict(discarded_properties(v2, changed.candidates[0]))['Curva de perda (GPV)'] == curve.uid


@pytest.mark.parametrize('kind', ['PRV', 'PSV', 'FCV'])
@pytest.mark.parametrize('source', ['R', 'T'])
def test_epanet_forbids_regulating_valves_directly_at_sources(project, kind, source):
    p = element(project, 'P')
    p.start = element(project, source).uid
    with pytest.raises(TypeChangeError, match='diretamente'):
        plan_type_change(project, [p.uid], 'valve', {'valve_type': kind, 'setting': 3})
    assert not valve_connection_issues(project.network)


def test_changing_a_junction_into_source_checks_incident_valves(project):
    element(project, 'V').valve_type = 'PRV'
    with pytest.raises(TypeChangeError, match='diretamente'):
        plan_type_change(project, [element(project, 'J1').uid], 'reservoir', {'head': 50})


@pytest.mark.parametrize('kind,a,b', [
    ('PRV', (0, 2), (1, 2)), ('PRV', (0, 1), (1, 2)),
    ('PSV', (0, 1), (0, 2)), ('PSV', (0, 1), (1, 2)),
    ('mixed', (0, 1), (1, 2)),
])
def test_epanet_valve_arrangements_are_checked_in_global_validation(kind, a, b):
    p = Project()
    nodes = [Junction(name=f'J{i}', x=i * 100) for i in range(3)]
    for n in nodes:
        p.network.put(n)
    for name, endpoints, valve_type in [('A', a, 'PRV' if kind == 'mixed' else kind),
                                        ('B', b, 'PSV' if kind == 'mixed' else kind)]:
        p.network.put(Valve(name=name, start=nodes[endpoints[0]].uid,
                            end=nodes[endpoints[1]].uid, valve_type=valve_type))
    assert any(i.code == 'VALVULA_ARRANJO' for i in validate(p))


def test_conversion_cannot_create_parallel_prvs(project):
    element(project, 'V').valve_type = 'PRV'
    with pytest.raises(TypeChangeError, match='compartilhar'):
        plan_type_change(project, [element(project, 'P').uid], 'valve', {'setting': 10})


def test_controls_require_explicit_removal_and_open_closed_controls_are_kept(project):
    p = element(project, 'P')
    status = Control(name='ESTADO', link=p.uid, action='CLOSED')
    numeric = Control(name='AJUSTE', link=p.uid, action='2')
    for c in (status, numeric):
        project.network.put(c)
    before = copy.deepcopy(project.network.to_dict())
    plan = plan_type_change(project, [p.uid], 'pump', {'power': 1})
    assert not plan.ready and plan.changes == []
    assert [c.uid for c in plan.conflicts] == [numeric.uid]
    assert project.network.to_dict() == before
    plan = plan_type_change(project, [p.uid], 'pump', {'power': 1}, remove_controls=True)
    assert plan.ready and len(plan.changes) == 2
    assert plan.changes[-1] == (numeric.uid, numeric.to_dict(), None)
    assert all(uid != status.uid for uid, _, _ in plan.changes)


def test_node_conditions_and_cv_status_controls_are_incompatible(project):
    j, p = element(project, 'J1'), element(project, 'P')
    c = Control(name='PRESSAO', link=p.uid, node=j.uid, action='OPEN', condition='IF NODE BELOW', value='10')
    project.network.put(c)
    plan = plan_type_change(project, [j.uid], 'tank', parameters('tank'))
    assert not plan.ready and plan.conflicts[0].uid == c.uid
    v = element(project, 'V')
    c.link = v.uid
    plan = plan_type_change(project, [v.uid], 'pipe', {'roughness': 130, 'status': 'CV'})
    assert not plan.ready and 'CV' in plan.conflicts[0].reason


def test_discarded_data_and_no_source_warning_are_visible(project):
    p = element(project, 'P')
    plan = plan_type_change(project, [p.uid], 'pump', {'power': 1})
    discarded = dict(discarded_properties(p, plan.candidates[0]))
    assert discarded['Trecho existente (executado)'] is True
    assert discarded['Diâmetro'] == 200
    project.network.remove(element(project, 'T').uid)
    plan = plan_type_change(project, [element(project, 'R').uid], 'junction')
    assert plan.ready and any('sem fonte' in w for w in plan.warnings)


@pytest.mark.parametrize('key,value', [('uid', 'X'), ('start', 'X'), ('vertices', []), ('unknown', 5)])
def test_identity_and_geometry_cannot_be_overridden(project, key, value):
    with pytest.raises(TypeChangeError, match='identidade'):
        plan_type_change(project, [element(project, 'P').uid], 'pump', {'power': 1, key: value})


def test_one_undo_redo_restores_elements_controls_selection_and_saved_types(qapp, project, tmp_path):
    from src.ui.controller import DocumentController
    src = element(project, 'J1')
    control = Control(name='C', link=element(project, 'P').uid, node=src.uid,
                      condition='IF NODE BELOW', value='10')
    project.network.put(control)
    before = copy.deepcopy(project.network.to_dict())
    before_hash = network_hash(project)
    ctrl = DocumentController(project)
    ctrl.set_selection([src.uid], 'canvas')
    plan = plan_type_change(project, [src.uid], 'tank', parameters('tank'), remove_controls=True)
    ctrl.apply(plan.changes, 'Trocar elemento')
    after = copy.deepcopy(project.network.to_dict())
    assert network_hash(project) != before_hash
    assert ctrl.undo_stack.count() == 1 and set(ctrl.selection) == {src.uid}
    assert isinstance(project.get(src.uid), Tank) and project.get(control.uid) is None
    path = tmp_path / 'trocado.shcad'
    save_project(project, str(path))
    assert isinstance(load_project(str(path)).get(src.uid), Tank)
    ctrl.undo_stack.undo()
    assert project.network.to_dict() == before and network_hash(project) == before_hash
    ctrl.undo_stack.redo()
    assert project.network.to_dict() == after


def test_dialog_requires_new_data_accepts_decimal_comma_and_cancel_does_not_edit(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.type_change_dialog import TypeChangeDialog
    ctrl = DocumentController(project)
    src = element(project, 'J1')
    before = copy.deepcopy(project.network.to_dict())
    dialog = TypeChangeDialog(ctrl, [src.uid], 'reservoir')
    assert not dialog.apply_button.isEnabled() and dialog.plan is None
    dialog.fields['head'][1].setText('40,5')
    dialog.preview()
    assert dialog.apply_button.isEnabled() and dialog.plan.candidates[0].head == 40.5
    assert dialog.table.rowCount() == 1 and 'Demanda-base' in dialog.table.item(0, 2).text()
    dialog.reject()
    assert project.network.to_dict() == before and ctrl.undo_stack.count() == 0


def test_dialog_valve_change_clears_setting_and_requires_control_consent(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.type_change_dialog import TypeChangeDialog
    v = element(project, 'V')
    project.network.put(Control(name='NUMERICO', link=v.uid, action='5'))
    dialog = TypeChangeDialog(DocumentController(project), [v.uid], 'valve')
    combo = dialog.fields['valve_type'][1]
    combo.setCurrentIndex(combo.findData('FCV'))
    assert not dialog.fields['setting'][1].text()
    dialog.preview()
    assert not dialog.apply_button.isEnabled()
    dialog.fields['setting'][1].setText('3')
    dialog.preview()
    assert dialog.plan and not dialog.plan.ready
    assert 'NUMERICO' in dialog.control_details.toPlainText()
    assert 'L/s' in dialog.labels['setting'].text()
    dialog.remove_controls.setChecked(True)
    dialog.preview()
    assert dialog.apply_button.isEnabled() and len(dialog.plan.changes) == 2
    dialog.reject()


def test_dialog_batch_leaves_different_values_individual_and_refuses_changed_source(qapp, project):
    from src.hydraulics import editing
    from src.ui.controller import DocumentController
    from src.ui.dialogs.type_change_dialog import TypeChangeDialog
    src = element(project, 'P')
    other = Pipe(name='P2', start=src.start, end=src.end, diameter=350)
    project.network.put(other)
    ctrl = DocumentController(project)
    dialog = TypeChangeDialog(ctrl, [src.uid, other.uid], 'valve')
    assert dialog.fields['diameter'][1].text() == ''
    kind = dialog.fields['valve_type'][1]
    kind.setCurrentIndex(kind.findData('TCV'))
    dialog.fields['setting'][1].setText('3')
    dialog.preview()
    assert [e.diameter for e in dialog.plan.candidates] == [200, 350]
    ctrl.apply(editing.update(project, src.uid, diameter=250), 'Editar')
    dialog.accept()
    assert not dialog.apply_button.isEnabled() and 'mudou' in dialog.status.text()
    assert dialog.result() == 0
    dialog.reject()


def test_context_submenus_limit_categories_and_main_action_updates_symbol_and_undo(qapp, project):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMenu
    from src.ui.dialogs.type_change_dialog import TypeChangeDialog
    from src.ui.main_window import MainWindow
    window = MainWindow(project)
    pipe = element(project, 'P')
    pipe.auto_length = True
    pipe.length = 0  # Exibição deve usar o comprimento real, não o cache não preenchido.
    check = TypeChangeDialog(window.ctrl, [pipe.uid], 'pump')
    assert f'Comprimento hidráulico: {project.network.hydraulic_length(pipe):.12g}' in check.table.item(0, 2).text()
    check.reject()
    pipe.auto_length = False
    pipe.length = 230
    menu = QMenu(window)
    window.add_type_change_menu(menu, {pipe.uid})
    sub = menu.actions()[0].menu()
    assert [a.data() for a in sub.actions()] == list(LINK_TYPES)
    assert not sub.actions()[0].isEnabled()
    mixed = QMenu(window)
    window.add_type_change_menu(mixed, {pipe.uid, element(project, 'J1').uid})
    assert not mixed.actions()[0].isEnabled()
    errors = []

    def apply_visible():
        dialog = next(w for w in QApplication.topLevelWidgets()
                      if isinstance(w, TypeChangeDialog) and w.isVisible())
        try:
            dialog.fields['power'][1].setText('5')
            dialog.accept()
        except BaseException as error:
            errors.append(error)
            dialog.reject()

    QTimer.singleShot(0, apply_visible)
    sub.actions()[1].trigger()
    assert not errors
    assert isinstance(project.get(pipe.uid), Pump)
    assert window.canvas.items_by_uid[pipe.uid].symbol.kind == 'pump'
    assert window.ctrl.undo_stack.count() == 1
    window.ctrl.undo_stack.undo()
    assert isinstance(project.get(pipe.uid), Pipe)
    assert window.canvas.items_by_uid[pipe.uid].symbol.kind == ''
    window.hide()
    window.deleteLater()


def test_right_click_selects_hit_keeps_existing_multiselection_and_keyboard_does_not_pick(qapp, project):
    from PySide6.QtGui import QContextMenuEvent
    from src.ui.main_window import MainWindow
    window = MainWindow(project)
    canvas = window.canvas
    canvas.contextMenuRequested.disconnect(window.canvas_context_menu)
    seen = []
    canvas.contextMenuRequested.connect(lambda pos: seen.append(set(window.ctrl.selection)))
    window.show()
    canvas.fit_all()
    qapp.processEvents()
    a, b = element(project, 'J1'), element(project, 'J2')
    pos = canvas.mapFromScene(canvas.m2s(a.x, a.y))
    global_pos = canvas.viewport().mapToGlobal(pos)
    window.ctrl.set_selection([b.uid], 'canvas')
    canvas.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, pos, global_pos))
    assert seen[-1] == {a.uid}
    window.ctrl.set_selection([a.uid, b.uid], 'canvas')
    canvas.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Mouse, pos, global_pos))
    assert seen[-1] == {a.uid, b.uid}
    window.ctrl.set_selection([b.uid], 'canvas')
    canvas.contextMenuEvent(QContextMenuEvent(QContextMenuEvent.Keyboard, pos, global_pos))
    assert seen[-1] == {b.uid}
    window.hide()
    window.deleteLater()


@pytest.mark.parametrize('target', ['pump', 'valve', 'tank'])
def test_real_epanet_simulates_converted_elements(qapp, simple_project, target):
    from src.integration.simulation_adapter import run_blocking
    from src.ui.controller import DocumentController
    p = simple_project
    src = next(e for e in p.network.elements() if e.KIND == ('reservoir' if target == 'tank' else 'pipe'))
    props = parameters(target)
    if target == 'tank':
        props.update(elevation=src.head - 2)
    ctrl = DocumentController(p)
    plan = plan_type_change(p, [src.uid], target, props)
    assert plan.ready
    ctrl.apply(plan.changes, 'Trocar')
    result = run_blocking(p)
    assert result['status'] == 'ok', result
    assert src.uid in result['nodes' if target == 'tank' else 'links']
