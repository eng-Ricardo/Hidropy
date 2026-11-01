"""Gráficos: dados hidráulicos, percursos, distribuição, exportação e integração Qt."""

import csv
import math

import pytest

from src.hydraulics.models import Junction, Pipe, Reservoir, Tank
from src.hydraulics.project import Project
from src.integration.input_exporter import network_hash
from src.results import graphs


@pytest.fixture
def graph_project():
    p = Project()
    r = Reservoir(name='R', x=-10, head=30)
    a = Junction(name='A', x=0, y=0, elevation=2)
    b = Junction(name='B', x=10, y=0, elevation=3)
    c = Junction(name='C', x=10, y=10, elevation=4)
    t = Tank(name='T', x=20, y=10, elevation=20)
    for n in (r, a, b, c, t):
        p.network.put(n)
    for name, start, end, length in (
            ('RA', r, a, 10), ('AB', a, b, 120), ('BC', b, c, 180), ('CT', c, t, 10)):
        p.network.put(Pipe(name=name, start=start.uid, end=end.uid,
                           auto_length=False, length=length))
    nodes = {
        r.uid: {'pressure': [0, 0], 'head': [30, 30], 'demand': [-8, -6]},
        a.uid: {'pressure': [10, 11], 'head': [12, 13], 'demand': [2, 2]},
        b.uid: {'pressure': [20, 22], 'head': [23, 25], 'demand': [2, 2]},
        c.uid: {'pressure': [20, None], 'head': [24, None], 'demand': [2, 2]},
        t.uid: {'pressure': [5, 6], 'head': [25, 26], 'demand': [2, 0],
                'level': [5, 6], 'volume': [100, 120]},
    }
    links = {uid: {'flow': [-3, 4], 'velocity': [0.3, 0.4], 'unit_headloss': [1, 2],
                   'headloss': [0.1, 0.2], 'status': [1, 0]} for uid in p.network.links}
    sim = {'uid': 'graph-sim', 'kind': 'simulation', 'status': 'ok', 'created': '2026-10-31T12:00:00',
           'scenario': p.active_scenario, 'inp_sha256': network_hash(p),
           'times': [0, 3600], 'nodes': nodes, 'links': links}
    p.add_result(sim)
    return p, sim


def uid(p, name):
    return p.network.find_by_name(name).uid


def test_time_series_uses_hours_keeps_flow_direction_and_missing_values(graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, uids=[uid(p, 'A'), uid(p, 'C')])
    assert [s.label for s in data.series] == ['A', 'C']
    assert data.series[0].x == [0, 1]
    assert data.series[1].y == [20, None]
    flow = graphs.build_graph(p, sim, collection='links', variable='flow', uids=[uid(p, 'AB')])
    assert flow.series[0].y == [-3, 4]


def test_profile_expands_connected_route_using_hydraulic_lengths(graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, kind='profile', variable='head', uids=[uid(p, 'A'), uid(p, 'C')])
    assert data.series[0].labels == ['A', 'B', 'C']
    assert data.series[0].x == [0, 120, 300]
    assert data.series[0].y == [12, 23, 24]
    assert data.series[1].y == [2, 3, 4]
    reverse = graphs.build_graph(p, sim, kind='profile', uids=[uid(p, 'C'), uid(p, 'A')])
    assert reverse.series[0].labels == ['C', 'B', 'A']
    assert reverse.series[0].x == [0, 180, 300]


def test_profile_reports_disconnected_nodes(graph_project):
    p, sim = graph_project
    p.network.links = {u: l for u, l in p.network.links.items() if l.name != 'BC'}
    with pytest.raises(graphs.GraphError, match='Não há caminho'):
        graphs.build_graph(p, sim, kind='profile', uids=[uid(p, 'A'), uid(p, 'C')])


def test_frequency_is_empirical_cdf_of_junctions_with_ties(graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, kind='frequency')
    assert data.series[0].x == [10, 20]
    assert data.series[0].y == pytest.approx([100 / 3, 100])
    later = graphs.build_graph(p, sim, kind='frequency', time_index=1)
    assert later.series[0].x == [11, 22]
    assert later.series[0].y == [50, 100]
    assert '1 sem valor' in later.note


def test_system_flows_balance_reservoir_supply_demand_and_tank_storage(graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, kind='system')
    supply, demand, storage = [s.y for s in data.series]
    assert supply == [8, 6] and demand == [6, 6] and storage == [2, 0]
    assert all(math.isclose(s - d - t, 0) for s, d, t in zip(supply, demand, storage))
    sim['nodes'][uid(p, 'A')]['demand'][1] = None
    assert graphs.build_graph(p, sim, kind='system').series[1].y[1] is None


def test_contour_excludes_tank_levels_and_rejects_collinear_geometry(graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, kind='contour')
    assert {point[0] for point in data.points} == {'A', 'B', 'C'}
    p.network.nodes[uid(p, 'C')].x, p.network.nodes[uid(p, 'C')].y = 20, 0
    with pytest.raises(graphs.GraphError, match='alinhados'):
        graphs.build_graph(p, sim, kind='contour')


def test_contour_rejects_coincident_nodes_with_conflicting_results(graph_project):
    p, sim = graph_project
    p.network.nodes[uid(p, 'B')].x = 0
    with pytest.raises(graphs.GraphError, match='coincidentes'):
        graphs.build_graph(p, sim, kind='contour')


@pytest.mark.parametrize('case', ['no_result', 'incomplete', 'wrong_parameter', 'one_profile_node'])
def test_invalid_graph_requests_have_clear_errors(graph_project, case):
    p, sim = graph_project
    args = {'uids': [uid(p, 'A')]}
    if case == 'no_result':
        sim = None
    elif case == 'incomplete':
        sim['nodes'][uid(p, 'A')]['pressure'] = [10]
    elif case == 'wrong_parameter':
        args['variable'] = 'flow'
    else:
        args['kind'] = 'profile'
    with pytest.raises(graphs.GraphError):
        graphs.build_graph(p, sim, **args)


def test_export_csv_contains_graphed_values_and_blank_gaps(tmp_path, graph_project):
    p, sim = graph_project
    data = graphs.build_graph(p, sim, uids=[uid(p, 'C')])
    path = tmp_path / 'serie.csv'
    graphs.export_csv(data, str(path))
    with path.open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream, delimiter=';'))
    assert rows[0] == {'Série': 'C', 'Tempo (h)': '0', 'Pressão (m)': '20'}
    assert rows[1]['Pressão (m)'] == '' and rows[1]['Tempo (h)'] == '1'


@pytest.mark.parametrize('kind', list(graphs.GRAPH_TYPES))
def test_all_graph_types_render_and_export_with_matplotlib(tmp_path, graph_project, kind):
    from matplotlib.figure import Figure
    from src.results.graph_rendering import draw_graph
    p, sim = graph_project
    data = graphs.build_graph(p, sim, kind=kind, variable='head' if kind == 'profile' else 'pressure',
                              uids=[uid(p, 'A'), uid(p, 'C')])
    figure = Figure(figsize=(8, 5))
    axes = draw_graph(figure, data)
    assert axes.get_title() == data.title
    path = tmp_path / f'{kind}.png'
    figure.savefig(path)
    assert path.stat().st_size > 1000


def test_constant_contour_has_single_value_legend(graph_project):
    from matplotlib.figure import Figure
    from src.results.graph_rendering import draw_graph
    p, sim = graph_project
    for name in ('A', 'B', 'C'):
        sim['nodes'][uid(p, name)]['pressure'][0] = 10
    data = graphs.build_graph(p, sim, kind='contour')
    axes = draw_graph(Figure(), data)
    assert '10' in axes.get_legend().get_texts()[0].get_text()


def test_graph_dialog_selection_reordering_exports_and_changed_network(qapp, graph_project, tmp_path, monkeypatch):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.graph_dialog import GraphDialog
    from PySide6.QtWidgets import QFileDialog
    p, _ = graph_project
    ctrl = DocumentController(p)
    ctrl.set_selection([uid(p, 'A'), uid(p, 'C')])
    dialog = GraphDialog(ctrl)
    assert len(dialog.graph_data.series) == 2
    dialog.kind.setCurrentIndex(dialog.kind.findData('profile'))
    dialog.parameter.setCurrentIndex(dialog.parameter.findData('head'))
    assert dialog.graph_data.series[0].labels == ['A', 'B', 'C']
    dialog.selected.setCurrentRow(1)
    dialog.move(-1)
    assert dialog.graph_data.series[0].labels == ['C', 'B', 'A']
    image = tmp_path / 'profile.png'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(image), 'PNG (*.png)'))
    dialog.export_image()
    assert image.stat().st_size > 1000
    csv_path = tmp_path / 'profile.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(csv_path), 'CSV (*.csv)'))
    dialog.export_data()
    assert csv_path.exists()
    ctrl.update_element(uid(p, 'A'), base_demand=10)
    assert dialog.graph_data is None and not dialog.save_csv.isEnabled()
    assert 'Execute novamente' in dialog.status.text()
    dialog.close()


def test_graph_dialog_handles_empty_results_without_blocking(qapp):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.graph_dialog import GraphDialog
    dialog = GraphDialog(DocumentController(Project()))
    assert dialog.graph_data is None
    assert not dialog.save_image.isEnabled()
    assert 'F5' in dialog.status.text()
    dialog.close()


def test_menu_toolbar_and_results_tab_open_the_same_graph_window(qapp, graph_project):
    from src.ui.main_window import MainWindow
    from PySide6.QtWidgets import QToolBar
    p, _ = graph_project
    window = MainWindow(p)
    toolbar = window.findChild(QToolBar, 'tb_calc')
    actions = toolbar.actions()
    assert actions.index(window.a['graphs']) == actions.index(window.a['results']) + 1
    menu = next(action.menu() for action in window.menuBar().actions()
                if action.text().replace('&', '') == 'Resultados')
    assert window.a['graphs'] in menu.actions()
    window.a['graphs'].trigger()
    dialog = window.graphs_dialog
    assert dialog.isVisible() and dialog.graph_data is not None
    dialog.close()
    window.results.tabs.setCurrentWidget(window.results.plot_host)
    assert window.results.tabs.tabText(window.results.tabs.currentIndex()) == 'Gráficos'
    window.results.graphs_button.click()
    assert window.graphs_dialog is dialog and dialog.isVisible()
    dialog.close()
    window.ctrl.mark_saved()
    window.close()


def test_system_chart_matches_real_epanet_extended_simulation(eps_project):
    from src.integration import simulation_adapter
    result = simulation_adapter.run_blocking(eps_project)
    assert result['status'] == 'ok'
    data = graphs.build_graph(eps_project, result, kind='system')
    assert len(data.series[0].x) == 25
    supply, demand, storage = [s.y for s in data.series]
    assert max(abs(s - d - t) for s, d, t in zip(supply, demand, storage)) < 0.001
