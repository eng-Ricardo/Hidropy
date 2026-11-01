"""Editores EPANET: ajustes, arquivos, transações e cálculos nativos."""

import copy
import math

import pytest

from src.hydraulics.models import Curve, Junction, Pattern, Pipe, Pump, Reservoir
from src.hydraulics.project import Project
from src.hydraulics.series_data import (fit_pump, parse_curve_text, parse_pattern_text,
    read_series_file, validate_curve, validate_pattern, write_series_file)
from src.hydraulics.validation import has_errors, validate


@pytest.mark.parametrize('kind,points', [
    ('PUMP', [[10, 40]]), ('PUMP', [[0, 60], [20, 0]]),
    ('PUMP', [[0, 125], [40, 110], [70, 0]]),
    ('PUMP', [[5, 97.5], [10, 90], [20, 60]]),
    ('PUMP', [[0, 60], [10, 55], [20, 45], [30, 0]]),
    ('EFFICIENCY', [[0, 0], [10, 85], [20, 0]]),
    ('VOLUME', [[0, 0], [5, 100]]), ('HEADLOSS', [[0, 0], [10, 5]])])
def test_all_supported_curve_shapes(kind, points):
    assert validate_curve(kind, points) == points


@pytest.mark.parametrize('kind,points', [
    ('PUMP', []), ('PUMP', [[0, 50]]), ('PUMP', [[10, 0]]),
    ('PUMP', [[0, 50], [10, 55]]), ('PUMP', [[0, 50], [0, 40]]),
    ('PUMP', [[0, 50], [10, float('nan')]]),
    ('PUMP', [[0, 100], [10, 99.99999], [20, 0]]),
    ('EFFICIENCY', [[0, 105]]), ('VOLUME', [[0, 0]]),
    ('VOLUME', [[0, 10], [1, 10]]), ('HEADLOSS', [[1, 1]]),
    ('HEADLOSS', [[0, -1], [10, 10]]), ('OTHER', [[0, 1]])])
def test_invalid_curve_values_are_rejected(kind, points):
    with pytest.raises(ValueError):
        validate_curve(kind, points)


def test_power_curve_matches_native_shutoff_and_single_point_assumptions():
    fit = fit_pump([[0, 100], [10, 90], [20, 60]])
    assert (fit.a, fit.b, fit.c) == pytest.approx((100, .1, 2), rel=1e-8)
    fit = fit_pump([[10, 40]])
    assert fit.head(0) == pytest.approx(40 * 1.33334)
    assert fit.head(10) == pytest.approx(40)
    assert fit.head(20) == pytest.approx(0, abs=1e-10)
    assert fit_pump([[0, 60], [20, 0]]) is None
    assert fit_pump([[5, 97.5], [10, 90], [20, 60]]) is None


@pytest.mark.parametrize('text,expected', [
    ('0,6 0,5;1,2\n1', [.6, .5, 1.2, 1]),
    ('1\t0,5\n2\t1,5', [.5, 1.5]),
    ('Período;Multiplicador\n1;0.5\n2;1.5', [.5, 1.5]),
    ('period,multiplier\n1,0.5\n2,1.5', [.5, 1.5]),
    ('Multiplicador\n0,5\n1,5', [.5, 1.5]),
    ('-1 0 1', [-1, 0, 1])])
def test_pattern_formats_and_decimal_comma(text, expected):
    assert parse_pattern_text(text) == expected


@pytest.mark.parametrize('text', ['0.5 texto 1.2', '1 NaN', '', 'Período;Multiplicador\n2;1'])
def test_bad_pattern_data_is_not_silently_skipped(text):
    with pytest.raises(ValueError):
        parse_pattern_text(text)


@pytest.mark.parametrize('text', ['0 125\n40 110\n70 0', 'Vazão (L/s);Carga (m)\n0;125\n40;110\n70;0',
                                 'Flow (L/s),Head (m)\n0,125\n40,110\n70,0'])
def test_curve_text_formats(text):
    assert parse_curve_text(text) == [[0, 125], [40, 110], [70, 0]]


def test_curve_import_reports_bad_row_instead_of_discarding_it():
    with pytest.raises(ValueError, match='Linha 2'):
        parse_curve_text('0 125\n40 erro\n70 0')
    with pytest.raises(ValueError):
        validate_pattern([float('inf')])


@pytest.mark.parametrize('kind,extension', [('curve', '.crv'), ('curve', '.csv'),
                                          ('pattern', '.pat'), ('pattern', '.csv')])
def test_native_and_csv_round_trip(kind, extension, tmp_path):
    props = {'name': 'C1', 'notes': 'Descrição com acentuação', 'curve_type': 'PUMP',
             'points': [[0, 125], [40, 110], [70, 0]], 'multipliers': [.5, 1.5]}
    path = tmp_path / ('dados' + extension)
    write_series_file(path, kind, props)
    data = read_series_file(path, kind)
    assert data['values'] == props['points' if kind == 'curve' else 'multipliers']
    if extension in ('.crv', '.pat'):
        assert data['notes'] == props['notes']
    if extension == '.crv':
        assert data['curve_type'] == 'PUMP'


@pytest.fixture
def project():
    p = Project()
    a, b = Reservoir(name='R', head=100), Junction(name='J', x=100, elevation=10, base_demand=2)
    p.network.put(a); p.network.put(b)
    p.network.put(Pipe(name='P', start=a.uid, end=b.uid, auto_length=False, length=100, diameter=200))
    p.network.put(Pattern(name='PAD1', notes='Consumo diário', multipliers=[.5, 1.5]))
    p.network.put(Pattern(name='PAD2', multipliers=[1, 2, 3]))
    p.network.put(Curve(name='C1', notes='Bomba principal', points=[[0, 125], [40, 110], [70, 0]]))
    p.network.put(Curve(name='C2', points=[[10, 40]]))
    return p


def by(project, name):
    return project.network.find_by_name(name)


def test_pattern_live_preview_keeps_project_unchanged_and_undo_restores(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import PatternsDialog
    from PySide6.QtWidgets import QTableWidgetItem
    ctrl = DocumentController(project)
    before = copy.deepcopy(project.network.to_dict())
    uid = by(project, 'PAD1').uid
    dialog = PatternsDialog(ctrl, uid)
    dialog.table.setItem(1, 0, QTableWidgetItem('0,75'))
    dialog.description.setPlainText('Nova descrição')
    dialog.preview()
    assert '1.125' in dialog.info.text()
    assert project.network.to_dict() == before
    assert dialog.save_current()
    assert project.get(uid).multipliers == [.75, 1.5]
    assert project.get(uid).notes == 'Nova descrição'
    assert ctrl.undo_stack.count() == 1
    ctrl.undo_stack.undo()
    assert project.network.to_dict() == before
    dialog.reject()


def test_switching_items_retains_invalid_drafts_cancel_discards_them(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import PatternsDialog
    from PySide6.QtWidgets import QTableWidgetItem
    before = copy.deepcopy(project.network.to_dict())
    dialog = PatternsDialog(DocumentController(project), by(project, 'PAD1').uid)
    dialog.table.setItem(1, 0, QTableWidgetItem('incompleto'))
    dialog.list.setCurrentRow(1)
    dialog.list.setCurrentRow(0)
    assert dialog.table.item(1, 0).text() == 'incompleto'
    dialog.reject()
    assert project.network.to_dict() == before


def test_duplicate_is_pending_and_normalization_is_explicit(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import PatternsDialog
    ctrl = DocumentController(project)
    dialog = PatternsDialog(ctrl, by(project, 'PAD2').uid)
    assert project.get(by(project, 'PAD2').uid).multipliers == [1, 2, 3]
    dialog.duplicate()
    assert len(project.network.patterns) == 2
    dialog.normalize()
    assert dialog.form_data()['values'] == ['0.5', '1', '1.5']
    assert dialog.save_current()
    assert len(project.network.patterns) == 3
    assert by(project, 'PAD2').multipliers == [1, 2, 3]
    ctrl.undo_stack.undo()
    assert len(project.network.patterns) == 2
    dialog.reject()


def test_curve_equation_and_pending_description(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import CurvesDialog
    dialog = CurvesDialog(DocumentController(project), by(project, 'C1').uid)
    assert 'H = 125' in dialog.info.text()
    assert len(dialog.figure.axes[0].lines[0].get_xdata()) == 161
    dialog.description.setPlainText('Teste da curva')
    assert dialog.save_current()
    assert by(project, 'C1').notes == 'Teste da curva'
    dialog.reject()


def test_invalid_import_does_not_replace_valid_draft(qapp, project, tmp_path, monkeypatch):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import CurvesDialog
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    dialog = CurvesDialog(DocumentController(project), by(project, 'C1').uid)
    before = copy.deepcopy(dialog.form_data())
    path = tmp_path / 'bad.csv';path.write_text('0;125\n40;erro\n70;0')
    monkeypatch.setattr(QFileDialog, 'getOpenFileName', lambda *a, **k: (str(path), 'CSV'))
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: errors.append(a[-1]))
    dialog.import_file()
    assert errors and dialog.form_data() == before
    dialog.reject()


def test_global_pattern_cannot_be_deleted_with_dangling_reference(qapp, project, monkeypatch):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import PatternsDialog
    from PySide6.QtWidgets import QMessageBox
    pattern = by(project, 'PAD1');project.sim_options.default_pattern = pattern.uid
    dialog = PatternsDialog(DocumentController(project), pattern.uid)
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: errors.append(a[-1]))
    dialog.delete()
    assert errors and pattern.uid in dialog._forms
    dialog.reject()


def test_delete_and_undo_restore_pattern_references(qapp, project, monkeypatch):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import PatternsDialog
    from PySide6.QtWidgets import QMessageBox
    pattern = by(project, 'PAD1');by(project, 'J').demand_pattern = pattern.uid
    ctrl = DocumentController(project)
    dialog = PatternsDialog(ctrl, pattern.uid)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a: QMessageBox.Yes)
    dialog.delete()
    assert project.get(pattern.uid) is not None
    assert dialog.save_current()
    assert project.get(pattern.uid) is None and by(project, 'J').demand_pattern == ''
    ctrl.undo_stack.undo()
    assert project.get(pattern.uid) is not None and by(project, 'J').demand_pattern == pattern.uid
    dialog.reject()


def test_curve_type_change_cannot_break_pump_reference(qapp, project, monkeypatch):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import CurvesDialog
    from PySide6.QtWidgets import QMessageBox, QTableWidgetItem
    curve = by(project, 'C1');pipe = by(project, 'P')
    project.network.put(Pump(name='B', start=pipe.start, end=pipe.end, curve=curve.uid))
    ctrl = DocumentController(project)
    dialog = CurvesDialog(ctrl, curve.uid)
    dialog.ctype.setCurrentIndex(dialog.ctype.findData('VOLUME'))
    dialog._loading = True
    dialog.pts.setRowCount(2)
    for r, values in enumerate([['0', '0'], ['5', '100']]):
        for c, value in enumerate(values):dialog.pts.setItem(r, c, QTableWidgetItem(value))
    dialog._loading = False
    errors = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda *a: errors.append(a[-1]))
    assert not dialog.save_current()
    assert errors and 'utilizada' in errors[-1] and project.get(curve.uid).curve_type == 'PUMP'
    assert ctrl.undo_stack.count() == 0
    dialog.reject()


def test_descriptions_round_trip_through_inp(project, tmp_path):
    from src.integration.input_exporter import write_inp
    from src.integration.inp_importer import import_inp
    by(project, 'PAD1').notes = 'Padrão de verão\nSegunda linha'
    by(project, 'C1').notes = 'Bomba principal'
    path = tmp_path / 'dados.inp';write_inp(project, str(path))
    net, warnings = import_inp(str(path), Project())
    assert net.find_by_name('PAD1').notes == 'Padrão de verão\nSegunda linha'
    assert net.find_by_name('C1').notes == 'Bomba principal'


@pytest.mark.parametrize('points,demand,linear_head', [
    ([[10, 40]], 5, None), ([[0, 60], [20, 0]], 5, 45),
    ([[0, 125], [40, 110], [70, 0]], 5, None),
    ([[5, 97.5], [10, 90], [20, 60]], 12.5, 82.5)])
def test_real_epanet_pump_matches_editor_curve(points, demand, linear_head):
    from src.integration.simulation_adapter import run_blocking
    p = Project();r = Reservoir(name='R', head=100);j = Junction(name='J', elevation=10, base_demand=demand)
    c = Curve(name='C', points=points)
    for e in [r, j, c, Pump(name='B', start=r.uid, end=j.uid, curve=c.uid)]:p.network.put(e)
    assert not has_errors(validate(p))
    result = run_blocking(p)
    assert result['status'] == 'ok', result
    fit = fit_pump(points)
    expected = fit.head(demand) if fit else linear_head
    assert result['nodes'][j.uid]['head'][0] - 100 == pytest.approx(expected, abs=.015)


def test_three_points_without_shutoff_have_linear_graph(qapp, project):
    from src.ui.controller import DocumentController
    from src.ui.dialogs.data_dialogs import CurvesDialog
    curve = by(project, 'C1');curve.points = [[5, 97.5], [10, 90], [20, 60]]
    dialog = CurvesDialog(DocumentController(project), curve.uid)
    assert list(dialog.figure.axes[0].lines[0].get_xdata()) == [5, 10, 20]
    assert 'interpolação linear' in dialog.info.text()
    dialog.reject()


def test_real_epanet_pattern_order_cycle_and_negative_multiplier(project):
    from src.integration.simulation_adapter import run_blocking
    p = project
    pattern = by(p, 'PAD1');pattern.multipliers = [-.5, 1.5]
    node = by(p, 'J');node.demand_pattern = pattern.uid
    p.sim_options.duration_h = 2
    p.sim_options.report_step_h = p.sim_options.hydraulic_step_h = p.sim_options.pattern_step_h = 1
    assert not has_errors(validate(p))
    result = run_blocking(p)
    assert result['status'] == 'ok', result
    assert result['nodes'][node.uid]['demand'] == pytest.approx([-1, 3, -1])
