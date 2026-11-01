"""Regressões de engenharia verificadas com o EPANET real e processos limitados."""

import sys
import time

import pytest
import wntr

from src.hydraulics.models import Junction, Pipe, Reservoir
from src.hydraulics.project import Project
from src.hydraulics.project_io import load_project, save_project
from src.integration import optimization_adapter, runner, simulation_adapter
from src.integration.inp_importer import import_inp
from src.integration.input_exporter import write_inp
from src.results.tables import optimization_df


def small_network(head=11, demand=1.2):
    p = Project()
    r = Reservoir(name='R', head=head)
    j = Junction(name='J', x=100, base_demand=demand)
    for n in (r, j):
        p.network.put(n)
    p.network.put(Pipe(name='P', start=r.uid, end=j.uid, diameter=150))
    p.opt_settings.catalogo_completo = [[50, 0.05, 25], [150, 0.15, 125]]
    p.opt_settings.num_geracoes = 2
    p.opt_settings.tam_populacao = 8
    return p


def optimize(p):
    result = optimization_adapter.run_blocking(p, timeout=60)
    assert result['status'] == 'ok', result.get('error', '') + result.get('log', '')
    return result


@pytest.mark.parametrize('minimum', [10.0, 2.0])
def test_low_pressure_never_relaxes_requested_minimum_or_absolute_floor(minimum):
    p = small_network(head=5, demand=1)
    p.opt_settings.pressao_min = minimum
    result = optimize(p)
    assert result['summary']['viavel'] is False
    assert result['summary']['n_p_baixa'] == 1
    junction = next(iter(result['junctions'].values()))
    assert junction['alvo'] == max(minimum, p.opt_settings.pressao_min_absoluta)
    assert junction['ok_pressure'] is False


def test_viable_solution_beats_cheaper_infeasible_solution_already_evaluated():
    result = optimize(small_network())
    assert result['summary']['viavel'] is True
    assert result['summary']['avaliacoes_unicas'] == 2
    assert result['summary']['custo'] == pytest.approx(12500)
    assert next(iter(result['pipes'].values()))['opt_diam_mm'] == 150
    assert result['execution']['optimization_settings']['SEMENTE'] == 42
    assert result['execution']['selection_policy'] == 'violation_then_cost'
    assert result['execution']['epanet'] == '2.2'


def test_no_viable_solution_selects_smallest_violation_before_cost():
    result = optimize(small_network(head=5))
    assert result['summary']['viavel'] is False
    # DN150 tem menor déficit; o custo não deve fazê-lo perder para DN50.
    assert next(iter(result['pipes'].values()))['opt_diam_mm'] == 150


@pytest.mark.parametrize('constraint', ['velocity', 'headloss'])
def test_fixed_pipes_remain_fixed_and_participate_in_constraints(constraint):
    p = small_network(head=40, demand=10)
    p.network.find_by_name('J').x = 2
    a = Junction(name='A', x=1)
    p.network.put(a)
    pipe = p.network.find_by_name('P')
    fixed = Pipe(name='FIXED', start=pipe.start, end=a.uid,
                 diameter=50, fixed_in_optimization=True)
    pipe.start = a.uid
    p.network.put(fixed)
    if constraint == 'headloss':
        p.opt_settings.velocidade_max = 10
        p.opt_settings.aplicar_limite_perda_unitaria = True
    result = optimize(p)
    assert result['summary']['viavel'] is False
    data = result['pipes'][fixed.uid]
    assert data['fixed'] and data['opt_diam_mm'] == data['orig_diam_mm'] == 50
    assert data['v_max'] == pytest.approx(5.09293, rel=1e-4)
    assert result['summary']['v_max'] == pytest.approx(data['v_max'])
    if constraint == 'velocity':
        assert result['summary']['n_v_alta'] >= 1
        assert result['summary']['n_v_alta_fixos'] == 1
        row = optimization_df(p, result).set_index('ID').loc['FIXED']
        assert row['Restrição de velocidade'] == 'NÃO atende'
    else:
        assert data['j_max'] > p.opt_settings.perda_carga_max
        assert result['summary']['n_j_alta'] >= 1


def test_nonconverged_steady_state_is_failure_even_when_binary_contains_values(simple_project):
    simple_project.sim_options.trials = 1
    simple_project.sim_options.accuracy = 0.00001
    result = simulation_adapter.run_blocking(simple_project, timeout=30)
    assert result['status'] == 'failed'
    assert 'UNBALANCED' in result['report'].upper()
    assert result['error']


@pytest.mark.parametrize('message', ['', 'iniciou'])
def test_timeout_covers_reading_stdout_and_reaps_worker(tmp_path, message):
    job = runner.RunJob(kind='simulate', workdir=str(tmp_path), inp_path='',
                        job_path='', result_path='', export=None)
    job.command = [sys.executable, '-u', '-c',
                   f'import time; print({message!r}, flush=True); time.sleep(5)']
    job.env = runner.worker_env()
    start = time.monotonic()
    code, log = runner.run_blocking(job, timeout=0.2)
    assert code == -1
    assert time.monotonic() - start < 3
    assert 'Tempo limite excedido' in log
    if message:
        assert message in log


def test_output_callback_failure_terminates_worker(tmp_path):
    job = runner.RunJob(kind='simulate', workdir=str(tmp_path), inp_path='',
                        job_path='', result_path='', export=None)
    job.command = [sys.executable, '-u', '-c', 'print("ready"); import time; time.sleep(5)']
    job.env = runner.worker_env()

    def fail(line):
        raise ValueError('callback')

    with pytest.raises(ValueError, match='callback'):
        runner.run_blocking(job, timeout=2, on_output=fail)


@pytest.mark.parametrize('units', ['LPS', 'GPM', 'CMH'])
def test_hydraulic_options_and_time_offsets_survive_inp_and_project_roundtrip(tmp_path, units):
    wn = wntr.network.WaterNetworkModel()
    wn.add_reservoir('R', base_head=20)
    wn.add_junction('J', base_demand=0.001)
    wn.add_pipe('P', 'R', 'J', length=100, diameter=0.15, roughness=130)
    h = wn.options.hydraulic
    h.demand_model = 'PDA'
    h.minimum_pressure = 2
    h.required_pressure = 20
    h.pressure_exponent = 0.7
    h.viscosity = 1.3
    h.specific_gravity = 1.1
    h.emitter_exponent = 0.6
    h.unbalanced = 'CONTINUE'
    h.unbalanced_value = 7
    h.checkfreq = 3
    h.maxcheck = 8
    h.damplimit = 0.02
    wn.options.time.duration = 7200
    wn.options.time.pattern_start = 3723
    wn.options.time.report_start = 3600
    wn.options.time.hydraulic_timestep = 33
    source = str(tmp_path / 'source.inp')
    wntr.network.write_inpfile(wn, source, units=units)
    reference = wntr.network.WaterNetworkModel(source)
    p = Project()
    p.network, warnings = import_inp(source, p)
    project_file = str(tmp_path / 'rede.shcad')
    save_project(p, project_file)
    p = load_project(project_file)
    target = str(tmp_path / 'target.inp')
    write_inp(p, target)
    actual = wntr.network.WaterNetworkModel(target)
    for name in ('demand_model', 'minimum_pressure', 'required_pressure', 'pressure_exponent',
                 'viscosity', 'specific_gravity', 'emitter_exponent', 'unbalanced',
                 'unbalanced_value', 'checkfreq', 'maxcheck', 'damplimit'):
        before = getattr(reference.options.hydraulic, name)
        after = getattr(actual.options.hydraulic, name)
        assert after == (pytest.approx(before) if isinstance(before, (int, float)) else before)
    for name in ('duration', 'pattern_start', 'report_start', 'hydraulic_timestep'):
        assert getattr(actual.options.time, name) == getattr(reference.options.time, name)
    assert p.sim_options.demand_model == 'PDA'


@pytest.mark.parametrize('units', ['LPS', 'GPM', 'CMH'])
@pytest.mark.parametrize('valve_type', ['PRV', 'PSV', 'PBV', 'FCV', 'TCV'])
def test_control_pressure_level_and_valve_setting_keep_physical_units(tmp_path, units, valve_type):
    source = tmp_path / 'controls.inp'
    source.write_text(f'''[JUNCTIONS]
J 0 1
K 0 0
[RESERVOIRS]
R 100
[TANKS]
T 10 5 0 10 20 0
[PIPES]
P R J 100 4 130 0
PT J T 100 4 130 0
[VALVES]
V J K 4 {valve_type} 1 0
[CONTROLS]
LINK P CLOSED IF NODE J ABOVE 20
LINK P OPEN IF NODE T BELOW 4
LINK V 23 AT TIME 2
[OPTIONS]
UNITS {units}
[END]
''', encoding='utf-8')
    reference = wntr.network.WaterNetworkModel(str(source))
    p = Project()
    p.network, _ = import_inp(str(source), p)
    target = str(tmp_path / 'roundtrip.inp')
    write_inp(p, target)
    actual = wntr.network.WaterNetworkModel(target)
    # Os objetos WNTR expressam limiares e ações em SI, independentemente do INP.
    expected_controls = [c.to_dict() for _, c in reference.controls()]
    actual_controls = [c.to_dict() for _, c in actual.controls()]
    for expected, got in zip(expected_controls, actual_controls):
        assert got['condition'] == expected['condition']
        assert got['then_actions'] == expected['then_actions']
    assert len(actual_controls) == len(expected_controls) == 3


def test_pda_roundtrip_preserves_delivered_demand_not_only_option_names(tmp_path):
    p = small_network(head=5, demand=10)
    p.sim_options.demand_model = 'PDA'
    p.sim_options.required_pressure = 20
    source = str(tmp_path / 'pda.inp')
    write_inp(p, source)
    before = simulation_adapter.run_blocking(p)
    q = Project()
    q.network, _ = import_inp(source, q)
    after = simulation_adapter.run_blocking(q)
    assert before['status'] == after['status'] == 'ok'
    before_j = before['nodes'][p.network.find_by_name('J').uid]
    after_j = after['nodes'][q.network.find_by_name('J').uid]
    assert before_j['demand'][0] < 10
    assert after_j['demand'] == pytest.approx(before_j['demand'])
    assert after_j['pressure'] == pytest.approx(before_j['pressure'])
    assert after['execution']['hydraulic_options']['demand_model'] == 'PDA'


@pytest.mark.parametrize('field,value', [
    ('velocidade_max', 0), ('pressao_max', 5), ('prob_mutacao', float('nan')),
    ('dn_min_permitido', 2000), ('catalogo_completo', [[50, 0.05, float('inf')]])])
def test_invalid_optimization_configuration_is_rejected_before_starting_worker(field, value):
    p = small_network()
    setattr(p.opt_settings, field, value)
    with pytest.raises(ValueError):
        optimization_adapter.prepare(p)


def test_subsecond_step_is_rejected_instead_of_exporting_zero(tmp_path):
    p = small_network()
    p.sim_options.hydraulic_step_h = 0.00001
    with pytest.raises(ValueError, match='segundo'):
        write_inp(p, str(tmp_path / 'invalid.inp'))


def test_pda_invalid_pressures_are_rejected_before_export(tmp_path):
    p = small_network()
    p.sim_options.demand_model = 'PDA'
    p.sim_options.minimum_pressure = p.sim_options.required_pressure
    with pytest.raises(ValueError, match='PDA'):
        write_inp(p, str(tmp_path / 'invalid.inp'))
