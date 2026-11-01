"""Configuração e prévia de trocas de elementos da mesma categoria."""

from __future__ import annotations

import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHeaderView, QLabel,
                               QLineEdit, QPlainTextEdit, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...hydraulics.models import KIND_LABELS, VALVE_TYPES
from ...hydraulics.schema import SCHEMA
from ...hydraulics.type_change import (PROTECTED, TypeChangeError, discarded_properties,
                                       draft_element, plan_type_change)


class TypeChangeDialog(QDialog):
    def __init__(self, controller, uids, target, parent=None):
        super().__init__(parent)
        self.ctrl, self.target = controller, target
        self.project = controller.project
        self.scenario = self.project.active_scenario
        self.uids = list(dict.fromkeys(uids))
        self.sources = [self.project.get(uid) for uid in self.uids]
        self.baseline = {e.uid: e.to_dict() for e in self.sources}
        self.drafts = [draft_element(self.project, e, target) for e in self.sources
                       if e.KIND != target or target == 'valve']
        self.plan = None
        self.fields = {}
        self._conflicts = ()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.preview)
        self.setWindowTitle('Trocar elemento — ' + KIND_LABELS[target])
        self.resize(930, 780)
        layout = QVBoxLayout(self)
        intro = QLabel(f'{len(self.uids)} elemento(s) selecionado(s). Nome, identidade, '
                       'posição, extremidades e vértices são preservados. '
                       'Confira os dados do novo tipo e os dados removidos/substituídos. '
                       'Elementos que já são do tipo escolhido são mantidos; válvulas '
                       'também permitem trocar o subtipo.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        split = QSplitter(Qt.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        form_widget = QWidget()
        self.form = QFormLayout(form_widget)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.labels = {}
        if target == 'pump':
            self.pump_mode = QComboBox()
            self.pump_mode.addItem('Potência constante (kW)', 'power')
            self.pump_mode.addItem('Curva característica', 'curve')
            self.form.addRow('Modelo da bomba:', self.pump_mode)
        for prop in SCHEMA[target]:
            if prop.key in PROTECTED or prop.type in ('computed', 'demand_cats'):
                continue
            values = [getattr(e, prop.key) for e in self.drafts]
            mixed = bool(values) and any(v != values[0] for v in values[1:])
            value = None if mixed or not values else values[0]
            if prop.type == 'bool':
                widget = QCheckBox()
                widget.setTristate(mixed)
                widget.setCheckState(Qt.PartiallyChecked if mixed else
                                     Qt.Checked if value else Qt.Unchecked)
                widget.checkStateChanged.connect(self.schedule_preview)
            elif prop.type in ('choice', 'ref_pattern', 'ref_curve'):
                widget = QComboBox()
                if mixed:
                    widget.addItem('Manter valores individuais', None)
                if prop.type == 'choice':
                    for choice in prop.choices:
                        label = VALVE_TYPES.get(choice, choice) if prop.key == 'valve_type' else {
                            'None': 'Automático / regulando', 'Open': 'Aberto',
                            'Closed': 'Fechado', 'CV': 'Retenção (CV)'}.get(choice, choice)
                        widget.addItem(label, choice)
                else:
                    widget.addItem('(nenhum)', '')
                    if prop.type == 'ref_pattern':
                        refs = self.project.network.patterns.values()
                    else:
                        kind = {'curve': 'PUMP', 'volume_curve': 'VOLUME',
                                'headloss_curve': 'HEADLOSS'}[prop.key]
                        refs = [c for c in self.project.network.curves.values() if c.curve_type == kind]
                    for ref in refs:
                        widget.addItem(ref.name, ref.uid)
                index = widget.findData(value)
                widget.setCurrentIndex(max(0, index))
                widget.currentIndexChanged.connect(self.schedule_preview)
            else:
                widget = QLineEdit()
                if value is not None:
                    widget.setText(format(value, '.15g') if isinstance(value, (int, float)) else str(value))
                widget.setPlaceholderText('Manter valores individuais' if mixed else
                                          'Preencher se necessário ao novo tipo')
                widget.textChanged.connect(self.schedule_preview)
            widget.setObjectName('type_change_' + prop.key)
            widget.setProperty('keepIndividual', mixed)
            widget.setToolTip(prop.note)
            label = QLabel(prop.label + (f' ({prop.unit})' if prop.unit else '') + ':')
            self.form.addRow(label, widget)
            self.labels[prop.key] = label
            self.fields[prop.key] = (prop, widget)
        if target == 'pump':
            self.pump_mode.currentIndexChanged.connect(self._dependent_fields)
        if target == 'valve':
            self.fields['valve_type'][1].currentIndexChanged.connect(self._valve_type_changed)
        if target == 'pipe':
            self.fields['auto_length'][1].checkStateChanged.connect(self._dependent_fields)
        scroll.setWidget(form_widget)
        split.addWidget(scroll)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Identificador', 'Troca de tipo',
                                              'Dados removidos / substituídos', 'Camada de destino'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in enumerate((110, 185, 420, 150)):
            self.table.setColumnWidth(column, width)
        split.addWidget(self.table)
        split.setSizes([370, 180])
        layout.addWidget(split, 1)
        self.remove_controls = QCheckBox('Remover os controles incompatíveis listados abaixo')
        self.remove_controls.setVisible(False)
        self.remove_controls.toggled.connect(self.schedule_preview)
        layout.addWidget(self.remove_controls)
        self.control_details = QPlainTextEdit()
        self.control_details.setReadOnly(True)
        self.control_details.setMaximumHeight(90)
        self.control_details.setVisible(False)
        layout.addWidget(self.control_details)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note = QLabel('As propriedades exclusivas do tipo anterior não são transferidas. '
                      'A camada padrão acompanha o novo tipo; camadas personalizadas são mantidas. '
                      'Ctrl+Z restaura elementos e controles. Execute nova simulação após a troca.')
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText('Aplicar troca')
        self.apply_button.clicked.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._dependent_fields()
        self.preview()

    def schedule_preview(self, *args):
        self._timer.start(120)

    def _dependent_fields(self, *args):
        if self.target == 'pump':
            by_curve = self.pump_mode.currentData() == 'curve'
            self.fields['curve'][1].setEnabled(by_curve)
            self.fields['power'][1].setEnabled(not by_curve)
        elif self.target == 'pipe':
            self.fields['length'][1].setEnabled(self.fields['auto_length'][1].checkState() != Qt.Checked)
        elif self.target == 'valve':
            kind = self.fields['valve_type'][1].currentData()
            self.fields['setting'][1].setEnabled(kind != 'GPV')
            self.fields['headloss_curve'][1].setEnabled(kind == 'GPV' or kind is None)
            self.labels['setting'].setText({'FCV': 'Vazão de ajuste (L/s):',
                                            'TCV': 'Coeficiente de perda (K):',
                                            'GPV': 'Ajuste numérico (não usado em GPV):'}.get(
                                                kind, 'Pressão de ajuste (m):'))
        self.schedule_preview()

    def _valve_type_changed(self, *args):
        # Um valor em m não pode virar L/s ou coeficiente K apenas mudando o tipo.
        self.fields['setting'][1].clear()
        curve = self.fields['headloss_curve'][1]
        curve.setCurrentIndex(curve.findData(''))
        self.remove_controls.setChecked(False)
        self._dependent_fields()

    def properties(self):
        result = {}
        for key, (prop, widget) in self.fields.items():
            if not widget.isEnabled():
                continue
            if isinstance(widget, QCheckBox):
                if widget.checkState() != Qt.PartiallyChecked:
                    result[key] = widget.isChecked()
            elif isinstance(widget, QComboBox):
                if widget.currentData() is not None:
                    result[key] = widget.currentData()
            elif prop.type in ('float', 'float_opt'):
                if widget.text().strip():
                    try:
                        result[key] = float(widget.text().strip().replace(',', '.'))
                    except ValueError:
                        raise TypeChangeError(f'{prop.label}: informe um número válido.') from None
                elif not widget.property('keepIndividual'):
                    result[key] = None
            elif widget.text() or len(self.drafts) == 1:
                result[key] = widget.text()
        if self.target == 'pump':
            if self.pump_mode.currentData() == 'power':
                result['curve'] = ''
            else:
                result['power'] = None
        return result

    def _value(self, value):
        if value is None:
            return 'não informado'
        if isinstance(value, str):
            element = self.project.get(value)
            return element.name if element else value or '(vazio)'
        if isinstance(value, bool):
            return 'sim' if value else 'não'
        if isinstance(value, (int, float)):
            return format(value, '.12g')
        return json.dumps(value, ensure_ascii=False)

    def _show_candidates(self, candidates):
        by = {e.uid: e for e in candidates}
        self.table.setRowCount(len(self.sources))
        for row, source in enumerate(self.sources):
            candidate = by.get(source.uid, draft_element(self.project, source, self.target))
            dropped = discarded_properties(source, candidate)
            if source.KIND == 'pipe' and source.auto_length:
                dropped = [(label, self.project.network.hydraulic_length(source)
                            if label == 'Comprimento hidráulico' else value)
                           for label, value in dropped]
            text = '; '.join(f'{label}: {self._value(value)}' for label, value in dropped) or '—'
            values = [source.name, KIND_LABELS[source.KIND] + ' → ' + KIND_LABELS[self.target],
                      text, candidate.layer]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.table.setItem(row, col, item)
        self.table.resizeRowsToContents()

    def preview(self):
        self._timer.stop()
        self.plan = None
        self.apply_button.setEnabled(False)
        self.remove_controls.setVisible(False)
        self.control_details.clear()
        self.control_details.setVisible(False)
        if self.ctrl.project is not self.project or self.project.active_scenario != self.scenario or any(
                self.project.get_dict(uid) != data for uid, data in self.baseline.items()):
            self.status.setText('A seleção ou o cenário mudou. Feche a janela e inicie novamente.')
            return
        try:
            plan = plan_type_change(self.project, self.uids, self.target, self.properties(),
                                    self.remove_controls.isChecked())
            signature = tuple((c.uid, c.reason) for c in plan.conflicts)
            if signature != self._conflicts and self.remove_controls.isChecked():
                self.remove_controls.setChecked(False)
                plan = plan_type_change(self.project, self.uids, self.target, self.properties())
            self._conflicts = signature
        except TypeChangeError as error:
            self._show_candidates([])
            self.status.setText(str(error))
            return
        self.plan = plan
        self._show_candidates(plan.candidates)
        self.remove_controls.setVisible(bool(plan.conflicts))
        self.control_details.setVisible(bool(plan.conflicts))
        self.control_details.setPlainText('\n'.join(f'{c.name}: {c.reason}.' for c in plan.conflicts))
        message = f'{len(plan.candidates)} elemento(s) a alterar.'
        if plan.conflicts:
            message += f' {len(plan.conflicts)} controle(s) incompatível(is) ' + (
                'serão removidos na mesma operação.' if plan.ready else
                'impedem a troca; revise a lista e marque a remoção para continuar.')
        if plan.warnings:
            message += '\n' + '\n'.join(plan.warnings)
        self.status.setText(message)
        self.apply_button.setEnabled(plan.ready)

    def accept(self):
        self.preview()
        if self.plan is not None and self.plan.ready:
            super().accept()
