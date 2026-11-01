"""Compatibilidade QEPANET: leitura editável, metadados e cálculo hidráulico."""

import copy
import hashlib
from pathlib import Path

import pytest

from src.hydraulics.project import Project
from src.hydraulics.project_io import load_project, save_project
from src.hydraulics.validation import has_errors, validate
from src.integration.inp_check import check_inp, prepare
from src.integration.inp_compat import MARKER, split_extensions
from src.integration.inp_importer import import_inp
from src.integration.input_exporter import export_inp, write_inp


STANDARD = '''[TITLE]
Rede de teste
[JUNCTIONS]
J1 10 0 ; Nó de chegada
J2 15 0.5
[RESERVOIRS]
R1 50
[TANKS]
T1 20 1 0 3 5 0
[PIPES]
L1 R1 J1 10 100 130 0 OPEN ; Adutora principal
L2 J2 T1 10 100 130 0 OPEN
[PUMPS]
P1 J1 J2 POWER {power} SPEED 1
[TAGS]
NODE J1 Chegada
LINK L1 Setor-A
[OPTIONS]
UNITS {units}
HEADLOSS H-W
[TIMES]
DURATION 0
[COORDINATES]
R1 0 0
J1 10 0
J2 20 0
T1 30 0
[VERTICES]
L1 2 0
L1 5 0
L2 25 0
[END]
'''
EXTRAS = '''[QEPANET-JUNCTIONS]
; ID DeltaZ
J1 -2
J2 1
[QEPANET-RESERVOIRS]
R1 3 7
[QEPANET-TANKS]
T1 -1
[QEPANET-PIPES]
L1 Plastic
L2 Ductile Iron
[QEPANET-VERTICES]
L1 11
L1 12
L2 18
[QOPTIONS]
'''


def file(tmp_path, text=None, power=2, units='LPS'):
    p = tmp_path / 'qepanet.inp'
    p.write_text(text if text is not None else STANDARD.format(power=power, units=units) + EXTRAS,
                 encoding='utf-8')
    return p


def load(path):
    p = Project();p.network, warnings = import_inp(str(path), p)
    return p, warnings


def element(p, name, collection=None):
    return p.network.find_by_name(name, collection)


def test_extensions_are_comments_without_changing_hydraulic_text(tmp_path):
    p = file(tmp_path)
    check = check_inp(str(p))
    assert not check.issues and any('6 seções' in w for w in check.warnings)
    assert not any('desconhecidas' in w for w in check.warnings)
    assert check.compatible_text.startswith(STANDARD.format(power=2, units='LPS'))
    assert all(not line.startswith('[Q') for line in check.compatible_text.splitlines())
    safe, blocks = split_extensions(check.compatible_text)
    assert safe == check.compatible_text and len(blocks) == 6
    assert MARKER + '[QEPANET-PIPES]' in safe


@pytest.mark.parametrize('prepared', [False, True])
def test_materials_offsets_vertex_order_and_original_are_preserved(tmp_path, prepared):
    path = file(tmp_path);before = path.read_bytes()
    source = prepare(check_inp(str(path)), False) if prepared else str(path)
    p, warnings = load(source)
    assert len(p.network.nodes) == 4 and len(p.network.links) == 3
    assert element(p, 'L1').material == 'Plastic'
    assert element(p, 'L2').material == 'Ductile Iron'
    assert element(p, 'J1').elevation == 10  # Não soma delta Z duas vezes.
    assert element(p, 'J1').ground_elevation == 12
    assert element(p, 'T1').ground_elevation == 21
    assert element(p, 'R1').head == 50 and element(p, 'R1').ground_elevation == 40
    assert element(p, 'L1').source_data['qepanet']['vertex_profile'] == [[2, 0, 11], [5, 0, 12]]
    assert element(p, 'L1').length == 10 and not element(p, 'L1').auto_length
    assert element(p, 'J1').notes == 'Nó de chegada'
    assert element(p, 'L1').notes == 'Adutora principal'
    assert element(p, 'J1').source_data['epanet']['tag'] == 'Chegada'
    assert path.read_bytes() == before
    assert p.meta['inp_imports'][-1]['recovered'] == {
        'materials': 2, 'node_elevations': 4, 'vertex_elevations': 3}


def test_us_metadata_units_are_converted_once(tmp_path):
    p, _ = load(file(tmp_path, units='GPM'))
    assert element(p, 'J1').elevation == pytest.approx(10 * .3048)
    assert element(p, 'J1').ground_elevation == pytest.approx(12 * .3048)
    assert element(p, 'R1').ground_elevation == pytest.approx(40 * .3048)
    assert element(p, 'L1').source_data['qepanet']['vertex_profile'][0] == pytest.approx([2, 0, 11 * .3048])


def test_zero_pump_and_empty_tank_are_editable_without_fabricating_design(tmp_path):
    text = (STANDARD.format(power=0, units='LPS') + EXTRAS).replace('T1 20 1 0 3 5 0', 'T1 20 0 0 0 0 0')
    path = file(tmp_path, text)
    p, warnings = load(path)
    assert element(p, 'P1').power == 0
    assert element(p, 'T1').diameter == 0 and element(p, 'T1').max_level == 0
    assert has_errors(validate(p))
    assert any('potência original de 0' in w for w in warnings)
    target = tmp_path / 'zero-preservado.inp'
    write_inp(p, str(target))
    other, _ = load(target)
    assert element(other, 'P1').power == 0
    assert p.meta['inp_imports'][-1]['review']


def test_bad_metadata_does_not_shift_subsequent_vertex_heights(tmp_path):
    text = (STANDARD.format(power=2, units='LPS') + EXTRAS).replace('L1 11\nL1 12', 'L1 inválido\nL1 12')
    p, warnings = load(file(tmp_path, text))
    assert element(p, 'L1').source_data['qepanet']['vertex_profile'] == [[2, 0, None], [5, 0, 12]]
    assert any('posição do vértice' in w for w in warnings)


def test_vertex_count_mismatch_is_not_guessed(tmp_path):
    text = (STANDARD.format(power=2, units='LPS') + EXTRAS).replace('L1 11\nL1 12', 'L1 11')
    p, warnings = load(file(tmp_path, text))
    data = element(p, 'L1').source_data['qepanet']
    assert 'vertex_profile' not in data and data['unmatched_vertex_z'] == [11]
    assert any('associação ambígua' in w for w in warnings)


def test_unknown_ids_duplicates_and_options_are_audited(tmp_path):
    extras = EXTRAS.replace('J1 -2', 'J1 -2\nJ1 100\nAusente 4').replace('[QOPTIONS]', '[QOPTIONS]\nCRS EPSG:1234')
    p, warnings = load(file(tmp_path, STANDARD.format(power=2, units='LPS') + extras))
    assert element(p, 'J1').ground_elevation == 12
    assert any('duplicado' in w for w in warnings) and any('referência ausente' in w for w in warnings)
    assert any('sem interpretar' in w for w in warnings)
    assert 'CRS EPSG:1234' in str(p.meta['inp_imports'][-1]['qepanet_sections'])


def test_inp_round_trip_with_renamed_ids_and_no_active_extension_sections(tmp_path):
    p, _ = load(file(tmp_path))
    element(p, 'L1').name = 'ADT-1';element(p, 'J1').name = 'NO-1'
    target = tmp_path / 'export.inp';write_inp(p, str(target))
    assert not any(row.startswith('[Q') for row in target.read_text(encoding='utf-8').splitlines())
    other, _ = load(target)
    assert element(other, 'ADT-1').material == 'Plastic'
    assert element(other, 'NO-1').ground_elevation == 12
    assert element(other, 'ADT-1').source_data['qepanet']['vertex_profile'] == [[2, 0, 11], [5, 0, 12]]


def test_project_round_trip_preserves_metadata_audit_and_hash(tmp_path):
    path = file(tmp_path);p, _ = load(path)
    before = copy.deepcopy(p.network.to_dict())
    save_project(p, str(tmp_path / 'network.shcad'))
    other = load_project(str(tmp_path / 'network.shcad'))
    assert other.network.to_dict() == before
    assert other.meta['inp_imports'][-1]['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert other.meta['inp_imports'] == p.meta['inp_imports']


def test_metadata_does_not_change_hydraulic_hash(tmp_path):
    p, _ = load(file(tmp_path))
    before = export_inp(p).sha256
    element(p, 'L1').material = 'Outro material'
    element(p, 'L1').source_data['qepanet']['vertex_profile'][0][2] = 100
    assert export_inp(p).sha256 == before


def test_failed_import_does_not_modify_project(tmp_path):
    p = Project();before = copy.deepcopy(p.meta), p.sim_options.to_dict(), p.network.to_dict()
    path = file(tmp_path, STANDARD.format(power='invalido', units='LPS') + EXTRAS)
    with pytest.raises(Exception):import_inp(str(path), p)
    assert (p.meta, p.sim_options.to_dict(), p.network.to_dict()) == before


def test_disconnected_components_are_kept_and_reported(tmp_path):
    text = (STANDARD.format(power=2, units='LPS') + EXTRAS).replace('P1 J1 J2 POWER 2 SPEED 1\n', '')
    p, warnings = load(file(tmp_path, text))
    assert len(p.network.links) == 2
    assert p.meta['inp_imports'][-1]['topology']['components'] == [['J1', 'R1'], ['J2', 'T1']]
    assert any('2 grupos sem conexão' in w for w in warnings)


def test_real_epanet_hydraulics_are_unchanged_by_metadata(tmp_path):
    from src.integration.simulation_adapter import run_blocking
    p, _ = load(file(tmp_path))
    plain, _ = load(file(tmp_path, STANDARD.format(power=2, units='LPS')))
    a, b = run_blocking(p), run_blocking(plain)
    assert a['status'] == b['status'] == 'ok', (a, b)
    for name in ('J1', 'J2', 'R1', 'T1'):
        assert a['nodes'][element(p, name).uid]['head'] == pytest.approx(b['nodes'][element(plain, name).uid]['head'])


def test_profile_view_copy_and_csv(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QFileDialog
    from src.ui.dialogs.source_profile import SourceProfileDialog
    p, _ = load(file(tmp_path))
    dialog = SourceProfileDialog(element(p, 'L1'))
    assert dialog.table.rowCount() == 2 and dialog.table.item(1, 3).text() == '12'
    dialog.copy();assert QApplication.clipboard().text().splitlines()[0] == '1\t2\t0\t11'
    path = tmp_path / 'perfil.csv'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **k: (str(path), 'CSV'))
    dialog.export();assert 'L1;2;5.0;0.0;12.0' in path.read_text(encoding='utf-8-sig')
    dialog.reject()


def test_gui_import_preserves_metadata_with_undo(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QGroupBox
    from src.ui.properties_panel import PropertiesPanel
    from src.ui.main_window import MainWindow
    errors = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *a, **k: errors.append(a[-1]))
    w = MainWindow()
    w.ctrl.project.sim_options.duration_h = 12
    before_options, before_meta = w.ctrl.project.sim_options.to_dict(), copy.deepcopy(w.ctrl.project.meta)
    w.import_inp(str(file(tmp_path, power=0)))
    assert not errors and len(w.ctrl.project.network.nodes) == 4
    uid = element(w.ctrl.project, 'L1').uid
    assert w.ctrl.project.get(uid).material == 'Plastic'
    w.ctrl.set_selection([uid])
    panel = w.findChild(PropertiesPanel)
    assert any('QGIS' in box.title() for box in panel.findChildren(QGroupBox))
    assert w.ctrl.project.sim_options.duration_h == 0
    assert w.ctrl.project.meta['inp_imports'][-1]['scenario'] == w.ctrl.project.active_scenario
    w.ctrl.undo_stack.undo();assert not w.ctrl.project.network.nodes
    assert w.ctrl.project.sim_options.to_dict() == before_options and w.ctrl.project.meta == before_meta
    w.ctrl.undo_stack.redo();assert w.ctrl.project.get(uid).source_data['qepanet']['vertex_profile']
    assert w.ctrl.project.sim_options.duration_h == 0 and w.ctrl.project.meta['inp_imports']
    w.ctrl.mark_saved();w.close()
