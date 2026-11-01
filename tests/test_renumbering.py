"""Protocolo da Suite EPANET 4.9: ordem, identidade, referências e edição reversível."""

import copy
import csv

import pytest

from src.hydraulics.models import CadEntity, Control, Junction, Pipe, Pump, Reservoir, Tank, Valve
from src.hydraulics.project import Project
from src.hydraulics.project_io import load_project, save_project
from src.hydraulics.renumbering import (RenumberError, RenumberSettings, export_mapping,
                                       plan_renumber)
from src.integration.input_exporter import export_inp, network_hash


@pytest.fixture
def project():
    p = Project()
    nodes = [Reservoir(name='R'), Tank(name='T', x=40),
             Junction(name='B', x=20, y=-10), Junction(name='A', x=10, y=20),
             Junction(name='C', x=10, y=20), Junction(name='D', x=30, y=30)]
    for node in nodes:
        p.network.put(node)
    by = {n.name: n for n in nodes}
    for name, a, b in [('PB', 'R', 'B'), ('PA', 'B', 'A'), ('PC', 'A', 'C'), ('PD', 'C', 'D')]:
        p.network.put(Pipe(name=name, start=by[a].uid, end=by[b].uid,
                           auto_length=False, length=100, notes='Comentário: A e PA intactos.'))
    p.network.put(Pump(name='BOMBA', start=by['B'].uid, end=by['T'].uid, power=10))
    p.network.put(Valve(name='VALVULA', start=by['A'].uid, end=by['D'].uid, valve_type='TCV'))
    pipe = p.network.find_by_name('PC')
    p.network.put(Control(name='CTRL', link=pipe.uid, node=by['A'].uid,
                          condition='IF NODE ABOVE', value='20', action='CLOSED'))
    p.put(CadEntity(name='TEXTO', geom='text', text='A e PA', points=[[0, 0]]))
    return p


def original_order(plan, kind):
    return [item.old_name for item in plan.items if item.kind == kind]


@pytest.mark.parametrize('method,expected', [
    ('original', ['B', 'A', 'C', 'D']), ('coord-x', ['A', 'C', 'B', 'D']),
    ('coord-y', ['D', 'A', 'C', 'B'])])
def test_geometry_and_original_order_match_suite_and_keep_pipe_order(project, method, expected):
    before = copy.deepcopy(project.network.to_dict())
    plan = plan_renumber(project, RenumberSettings(method=method))
    assert original_order(plan, 'junction') == expected
    assert original_order(plan, 'pipe') == ['PB', 'PA', 'PC', 'PD']
    assert [item.new_name for item in plan.items[:4]] == ['J-001', 'J-002', 'J-003', 'J-004']
    assert plan.node_count == plan.pipe_count == 4
    assert project.network.to_dict() == before


def test_prefix_padding_and_custom_start_do_not_truncate_numbers(project):
    settings = RenumberSettings(node_prefix='N_', node_digits=1, node_start=9,
                                pipe_prefix='T-', pipe_digits=3, pipe_start=20)
    plan = plan_renumber(project, settings)
    assert [item.new_name for item in plan.items[:4]] == ['N_9', 'N_10', 'N_11', 'N_12']
    assert [item.new_name for item in plan.items[4:]] == ['T-020', 'T-021', 'T-022', 'T-023']


@pytest.mark.parametrize('field,value', [
    ('node_prefix', 'J '), ('pipe_prefix', 'P;'), ('node_prefix', 'J"'),
    ('node_prefix', 'J\x00'), ('node_prefix', 'x' * 31), ('node_digits', 0),
    ('pipe_digits', 7), ('node_start', 0), ('pipe_start', 1.5), ('method', 'unknown')])
def test_invalid_settings_are_rejected_without_modifying_network(project, field, value):
    before = copy.deepcopy(project.network.to_dict())
    settings = RenumberSettings()
    setattr(settings, field, value)
    with pytest.raises(RenumberError):
        plan_renumber(project, settings)
    assert project.network.to_dict() == before


@pytest.mark.parametrize('kind,name', [('reservoir', 'J-001'), ('pump', 'P-001')])
def test_collisions_with_preserved_elements_are_blocked(project, kind, name):
    element = next(e for e in project.network.elements() if e.KIND == kind)
    element.name = name
    before = copy.deepcopy(project.network.to_dict())
    with pytest.raises(RenumberError, match='duplicado'):
        plan_renumber(project)
    assert project.network.to_dict() == before


def test_single_category_and_empty_prefix_are_allowed(project):
    settings = RenumberSettings(rename_nodes=False, pipe_prefix='', pipe_digits=2,
                                node_prefix='IGNORADO;')
    plan = plan_renumber(project, settings)
    assert plan.node_count == 0 and plan.pipe_count == 4
    assert [item.new_name for item in plan.items] == ['01', '02', '03', '04']


def hydraulic_project():
    p = Project()
    by = {}
    for node in [Reservoir(name='R'), Tank(name='T')] + [Junction(name=n) for n in 'ABCDFE']:
        p.network.put(node)
        by[node.name] = node
    flows = {}
    for name, a, b, flow in [('RA', 'R', 'A', 10), ('BA', 'B', 'A', -7),
                              ('AC', 'A', 'C', 3), ('CD', 'C', 'D', -2), ('TD', 'T', 'D', 4)]:
        link = Pipe(name=name, start=by[a].uid, end=by[b].uid, auto_length=False, length=100)
        p.network.put(link)
        flows[link.uid] = {'flow': [flow, flow]}
    pump = Pump(name='BOMBA', start=by['B'].uid, end=by['F'].uid, power=10)
    p.network.put(pump)
    flows[pump.uid] = {'flow': [5, 5]}
    sim = {'uid': 'simulation', 'kind': 'simulation', 'status': 'ok',
           'inp_sha256': network_hash(p), 'times': [0, 3600], 'links': flows}
    return p, sim


def test_hydraulic_bfs_respects_sources_negative_flows_pumps_and_unreached_nodes():
    p, sim = hydraulic_project()
    plan = plan_renumber(p, RenumberSettings(method='hydraulic'), sim)
    assert original_order(plan, 'junction') == ['A', 'D', 'B', 'C', 'F', 'E']
    assert original_order(plan, 'pipe') == ['RA', 'BA', 'TD', 'AC', 'CD']
    assert len(plan.warnings) == 1 and 'E' in plan.warnings[0]
    assert {item.old_name for item in plan.items}.isdisjoint({'R', 'T', 'BOMBA'})


def test_hydraulic_order_uses_selected_instant_and_stable_ties():
    p, sim = hydraulic_project()
    for uid, item in sim['links'].items():
        item['flow'][1] = 1
    sim['links'][p.network.find_by_name('RA').uid]['flow'][1] = -1
    plan = plan_renumber(p, RenumberSettings(method='hydraulic'), sim, 1)
    assert original_order(plan, 'pipe') == ['RA', 'BA', 'AC', 'CD', 'TD']
    assert original_order(plan, 'junction') == ['D', 'A', 'B', 'C', 'F', 'E']


@pytest.mark.parametrize('problem', ['missing', 'old_hash', 'missing_flow', 'nan', 'wrong_time'])
def test_hydraulic_order_requires_complete_current_results(problem):
    p, sim = hydraulic_project()
    time_index = 0
    if problem == 'missing':
        sim = None
    elif problem == 'old_hash':
        sim['inp_sha256'] = 'old'
    elif problem == 'missing_flow':
        sim['links'].pop(next(iter(sim['links'])))
    elif problem == 'nan':
        next(iter(sim['links'].values()))['flow'][0] = float('nan')
    else:
        time_index = 2
    with pytest.raises(RenumberError):
        plan_renumber(p, RenumberSettings(method='hydraulic'), sim, time_index)


def test_name_permutation_uid_references_properties_undo_and_redo(qapp, project):
    from src.ui.controller import DocumentController
    # Os novos IDs já pertencem a outros elementos renumerados: não pode haver cascata.
    project.network.find_by_name('B').name = 'J-001'
    project.network.find_by_name('A').name = 'J-002'
    original = copy.deepcopy(project.network.to_dict())
    cad = copy.deepcopy(project.cad)
    ctrl = DocumentController(project)
    plan = plan_renumber(project)
    ctrl.apply(plan.changes, 'Renumerar nós e trechos')
    assert ctrl.undo_stack.count() == 1
    expected = copy.deepcopy(original)
    names = {item.uid: item.new_name for item in plan.items}
    for collection in expected.values():
        for element in collection:
            element['name'] = names.get(element['uid'], element['name'])
    assert project.network.to_dict() == expected
    assert project.cad == cad
    ctrl.undo_stack.undo()
    assert project.network.to_dict() == original
    ctrl.undo_stack.redo()
    assert project.network.to_dict() == expected


def test_saved_project_and_inp_keep_renamed_nodes_and_control_references(qapp, project, tmp_path):
    from src.ui.controller import DocumentController
    ctrl = DocumentController(project)
    plan = plan_renumber(project)
    ctrl.apply(plan.changes, 'Renumerar')
    path = str(tmp_path / 'renumerado.shcad')
    save_project(project, path)
    loaded = load_project(path)
    assert loaded.network.to_dict() == project.network.to_dict()
    control = next(iter(project.network.controls.values()))
    exported = export_inp(project)
    assert f'LINK {project.network.links[control.link].name} CLOSED IF NODE ' \
           f'{project.network.nodes[control.node].name} ABOVE 20' in exported.text
    assert 'Comentário: A e PA intactos.' in project.network.find_by_name('P-001').notes
    assert project.network.find_by_name('BOMBA').KIND == 'pump'
    assert project.network.find_by_name('VALVULA').KIND == 'valve'


def test_other_scenarios_are_not_renumbered(qapp, project):
    from src.ui.controller import DocumentController
    other = project.create_scenario('Alternativa')
    old = copy.deepcopy(other.network)
    ctrl = DocumentController(project)
    ctrl.apply(plan_renumber(project).changes, 'Renumerar')
    assert other.network == old


def test_csv_mapping_contains_exact_old_new_ids_and_uids(project, tmp_path):
    plan = plan_renumber(project)
    path = tmp_path / 'ids.csv'
    export_mapping(plan, path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter=';'))
    assert len(rows) == 8
    assert rows[0] == {'Tipo': 'Junção', 'ID anterior': 'A', 'Novo ID': 'J-001', 'UID': plan.items[0].uid}


def test_renumbering_preserves_real_epanet_pressures_and_flows(qapp, simple_project):
    from src.integration import simulation_adapter
    from src.ui.controller import DocumentController
    before = simulation_adapter.run_blocking(simple_project)
    assert before['status'] == 'ok'
    ctrl = DocumentController(simple_project)
    plan = plan_renumber(simple_project, RenumberSettings(method='hydraulic'), before)
    ctrl.apply(plan.changes, 'Renumerar')
    after = simulation_adapter.run_blocking(simple_project)
    assert after['status'] == 'ok'
    assert set(before['nodes']) == set(after['nodes'])
    assert set(before['links']) == set(after['links'])
    for uid in before['nodes']:
        assert after['nodes'][uid]['pressure'] == pytest.approx(before['nodes'][uid]['pressure'], abs=1e-5)
    for uid in before['links']:
        assert after['links'][uid]['flow'] == pytest.approx(before['links'][uid]['flow'], abs=1e-5)


def test_dialog_preview_invalid_prefix_and_cancel_do_not_edit_model(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.renumber_dialog import RenumberDialog
    before = copy.deepcopy(project.network.to_dict())
    ctrl = DocumentController(project)
    dialog = RenumberDialog(ctrl)
    assert dialog.plan and dialog.table.rowCount() == 8
    assert dialog.apply_button.isEnabled()
    index = dialog.method.findData('hydraulic')
    assert not dialog.method.model().item(index).isEnabled()
    dialog.node_prefix.setText('J ')
    dialog.preview()
    assert dialog.plan is None and not dialog.apply_button.isEnabled()
    dialog.reject()
    assert project.network.to_dict() == before and ctrl.undo_stack.count() == 0


def test_dialog_hydraulic_time_selection_and_mapping_export(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from src.ui.controller import DocumentController
    from src.ui.dialogs.renumber_dialog import RenumberDialog
    p, sim = hydraulic_project()
    p.add_result(sim)
    dialog = RenumberDialog(DocumentController(p), time_index=1)
    dialog.method.setCurrentIndex(dialog.method.findData('hydraulic'))
    dialog.preview()
    assert dialog.instant.isEnabled() and dialog.instant.currentIndex() == 1
    assert original_order(dialog.plan, 'pipe')[0] == 'RA'
    path = tmp_path / 'correspondencia.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'CSV (*.csv)'))
    dialog.export()
    assert path.exists()
    dialog.reject()


def test_menu_toolbar_next_to_split_and_apply_one_undo_command(qapp, project):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QToolBar
    from src.ui.dialogs.renumber_dialog import RenumberDialog
    from src.ui.main_window import MainWindow
    window = MainWindow(project)
    toolbar = window.findChild(QToolBar, 'tb_net')
    actions = toolbar.actions()
    assert actions.index(window.a['renumber']) == actions.index(window.a['tool_split']) + 1
    menu = next(a.menu() for a in window.menuBar().actions()
                if a.text().replace('&', '') == 'Rede hidráulica')
    actions = menu.actions()
    assert actions.index(window.a['renumber']) == actions.index(window.a['tool_split']) + 1
    errors = []

    def apply_visible():
        dialog = next(w for w in QApplication.topLevelWidgets() if isinstance(w, RenumberDialog)
                      and w.isVisible())
        try:
            dialog.node_prefix.setText('N-')
            dialog.preview()
            dialog.accept()
        except BaseException as error:
            errors.append(error)
            dialog.reject()

    QTimer.singleShot(0, apply_visible)
    window.a['renumber'].trigger()
    assert not errors
    assert window.ctrl.undo_stack.count() == 1
    assert all(n.name.startswith('N-') for n in project.network.nodes.values() if n.KIND == 'junction')
    window.ctrl.undo_stack.undo()
    assert project.network.find_by_name('A') is not None
    window.ctrl.mark_saved()
    window.close()
