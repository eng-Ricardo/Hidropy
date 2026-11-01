"""Editores de curvas e padrões com tabela, prévia e alterações pendentes."""

from __future__ import annotations

import copy
import math
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from ...hydraulics import editing
from ...hydraulics.models import Curve, Pattern
from ...hydraulics.series_data import (CURVE_AXES, CURVE_LABELS, fit_pump, number,
    parse_curve_text, parse_pattern_text, read_series_file, text_number,
    validate_curve, validate_name, validate_pattern, write_series_file)


class _DataTable(QTableWidget):
    pasteRequested = Signal()
    copyRequested = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Paste):
            self.pasteRequested.emit()
        elif event.matches(QKeySequence.Copy):
            self.copyRequested.emit()
        else:
            super().keyPressEvent(event)


class _SeriesEditor(QDialog):
    KIND = ''
    TITLE = ''

    def __init__(self, ctrl, select_uid='', parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.project = ctrl.project
        self.scenario = self.project.active_scenario
        self._loading = True
        self._uid = ''
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.preview)
        self.setWindowTitle(self.TITLE)
        self.resize(1100, 750)
        self.setMinimumSize(840, 580)
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumWidth(150)
        self.list.setMaximumWidth(230)
        left.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.new_button = QPushButton('Novo')
        self.duplicate_button = QPushButton('Duplicar')
        self.delete_button = QPushButton('Excluir')
        for button, callback in [(self.new_button, self.new), (self.duplicate_button, self.duplicate),
                                  (self.delete_button, self.delete)]:
            button.clicked.connect(callback)
            buttons.addWidget(button)
        left.addLayout(buttons)
        body.addLayout(left, 1)
        self.right = QVBoxLayout()
        form = QFormLayout()
        self.name = QLineEdit()
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(54)
        self.description.setPlaceholderText('Descrição opcional')
        form.addRow('Identificador:', self.name)
        form.addRow('Descrição:', self.description)
        self.right.addLayout(form)
        self.build_editor()
        body.addLayout(self.right, 4)
        layout.addLayout(body, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        footer = QHBoxLayout()
        self.load_button = QPushButton('Carregar…')
        self.export_button = QPushButton('Salvar arquivo…')
        self.load_button.clicked.connect(self.import_file)
        self.export_button.clicked.connect(self.export_file)
        footer.addWidget(self.load_button)
        footer.addWidget(self.export_button)
        help_button = QPushButton('Ajuda')
        help_button.clicked.connect(self.help)
        footer.addWidget(help_button)
        footer.addStretch()
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_button.clicked.connect(self.save_current)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        footer.addWidget(self.buttons)
        layout.addLayout(footer)
        note = QLabel('Aplicar grava as alterações no cenário ativo. Cancelar descarta apenas '
                      'o que ainda não foi aplicado. A edição aplicada pode ser desfeita com Ctrl+Z.')
        note.setWordWrap(True)
        layout.addWidget(note)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
            button.setDefault(False)
        self.name.textChanged.connect(self.changed)
        self.description.textChanged.connect(self.changed)
        self.list.currentItemChanged.connect(self._select)
        self.reset(select_uid)

    def store(self):
        return getattr(self.project.network, self.KIND + 's')

    def reset(self, select=''):
        self._baseline = {uid: e.to_dict() for uid, e in self.store().items()}
        self._models = {uid: e.clone() for uid, e in self.store().items()}
        self._forms = {uid: self.to_form(e) for uid, e in self._models.items()}
        self._initial_forms = copy.deepcopy(self._forms)
        self._uid = ''
        self._refresh_list(select)

    def _refresh_list(self, select=''):
        self.list.blockSignals(True)
        self.list.clear()
        for uid, raw in self._forms.items():
            dirty = uid not in self._initial_forms or raw != self._initial_forms[uid]
            item = QListWidgetItem((raw['name'] or '(sem identificador)') + (' *' if dirty else ''))
            item.setData(Qt.UserRole, uid)
            self.list.addItem(item)
            if uid == select:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and self.list.count():
            self.list.setCurrentRow(0)
        self.list.blockSignals(False)
        self._select(self.list.currentItem(), None)

    def _stash(self):
        if self._uid in self._forms:
            self._forms[self._uid] = self.form_data()

    def _select(self, current, previous):
        self._stash()
        self._uid = current.data(Qt.UserRole) if current else ''
        self._loading = True
        raw = self._forms.get(self._uid)
        self.name.setText(raw['name'] if raw else '')
        self.description.setPlainText(raw['notes'] if raw else '')
        self.load_data(raw)
        self._loading = False
        enabled = raw is not None
        for widget in (self.name, self.description, self.editor, self.duplicate_button,
                       self.delete_button, self.export_button, self.load_button):
            widget.setEnabled(enabled)
        self.preview()

    def changed(self, *args):
        if self._loading:
            return
        self._stash()
        item = self.list.currentItem()
        if item:
            raw = self._forms[self._uid]
            dirty = self._initial_forms.get(self._uid) != raw
            item.setText((raw['name'] or '(sem identificador)') + (' *' if dirty else ''))
        self._timer.start(140)

    def new(self):
        self._stash()
        taken = {raw['name'] for raw in self._forms.values()}
        name = self.project.network.unique_name(self.KIND, taken)
        model = Curve(name=name) if self.KIND == 'curve' else Pattern(name=name, multipliers=[1.0] * 24)
        self._models[model.uid] = model
        self._forms[model.uid] = self.to_form(model)
        self._uid = ''
        self._refresh_list(model.uid)
        self.name.setFocus()
        self.name.selectAll()

    def duplicate(self):
        if not self._uid:
            return
        self._stash()
        raw = copy.deepcopy(self._forms[self._uid])
        taken = {r['name'] for r in self._forms.values()}
        model = self._models[self._uid].clone()
        from ...hydraulics.models import new_uid
        model.uid = new_uid()
        base = raw['name'][:26] or ('C' if self.KIND == 'curve' else 'PAD')
        i = 2
        while f'{base}_{i}' in taken:
            i += 1
        raw['name'] = f'{base}_{i}'
        self._models[model.uid], self._forms[model.uid] = model, raw
        self._uid = ''
        self._refresh_list(model.uid)

    def delete(self):
        if not self._uid:
            return
        if self.KIND == 'pattern' and self._uid == self.project.sim_options.default_pattern:
            QMessageBox.warning(self, 'Padrão global', 'Este é o padrão global da simulação. '
                                'Selecione outro padrão nas opções de simulação antes de excluí-lo.')
            return
        name = self.name.text()
        if QMessageBox.question(self, 'Excluir', f"Excluir '{name}'? Ao aplicar, as referências "
                                'a este objeto serão removidas. Ctrl+Z restaura a operação.') != QMessageBox.Yes:
            return
        del self._forms[self._uid]
        self._uid = ''
        self._refresh_list()

    def _collect(self, raw, uid):
        name = raw['name'].strip()
        validate_name(name)
        props = {'name': name, 'notes': raw['notes']}
        if self.KIND == 'curve':
            rows = raw['rows']
            while rows and not any(v.strip() for v in rows[-1]):
                rows = rows[:-1]
            props.update(curve_type=raw['curve_type'], points=validate_curve(raw['curve_type'], rows))
            expected = {'pump': ('curve', 'PUMP'), 'tank': ('volume_curve', 'VOLUME'),
                        'valve': ('headloss_curve', 'HEADLOSS')}
            for e in self.project.network.elements():
                rule = expected.get(e.KIND)
                if rule and getattr(e, rule[0]) == uid and raw['curve_type'] != rule[1]:
                    raise ValueError(f"A curva é utilizada por '{e.name}' e deve continuar do tipo {rule[1]}. "
                                     'Duplique-a para criar uma curva de outro tipo.')
        else:
            props['multipliers'] = validate_pattern(raw['values'])
        return props

    def save_current(self):
        self._timer.stop()
        self._stash()
        if self.ctrl.project is not self.project or self.project.active_scenario != self.scenario or \
                {uid: e.to_dict() for uid, e in self.store().items()} != self._baseline:
            QMessageBox.warning(self, 'Dados alterados', 'O cenário ou os dados mudaram desde a abertura. '
                                'Feche e abra novamente o editor para atualizar os dados.')
            return False
        try:
            changes = editing.delete(self.project, set(self._baseline) - set(self._forms))
            names = set()
            for uid, raw in self._forms.items():
                name = raw['name'].strip()
                if name in names:
                    raise ValueError(f"Identificador duplicado: '{name}'.")
                names.add(name)
                if raw == self._initial_forms.get(uid):
                    continue
                props = self._collect(raw, uid)
                model = self._models[uid].clone()
                for key, value in props.items():
                    setattr(model, key, value)
                changes.append((uid, self._baseline.get(uid), model.to_dict()))
            # Opção global é externa aos elementos e não pode ficar sem referência.
            if self.project.sim_options.default_pattern in set(self._baseline) - set(self._forms):
                raise ValueError('O padrão global da simulação não pode ser excluído neste editor.')
        except ValueError as error:
            QMessageBox.warning(self, 'Dados inválidos', str(error))
            return False
        selected = self._uid
        self.ctrl.apply(changes, 'Editar curvas' if self.KIND == 'curve' else 'Editar padrões temporais')
        self.reset(selected)
        self.status.setText('Alterações aplicadas. Ctrl+Z para desfazer.')
        return True

    def accept(self):
        if self.save_current():
            super().accept()

    def reject(self):
        self._timer.stop()
        super().reject()

    def help(self):
        if self.KIND == 'curve':
            text = ('Informe os pontos X/Y nas unidades indicadas. Enter confirma a célula e '
                    'atualiza o gráfico. Ctrl+C e Ctrl+V copiam e colam pontos.\n\n'
                    'Bomba: um ponto, ou três começando em vazão zero, geram o ajuste '
                    'H = A − B Q^C (0 < C ≤ 20). Os demais casos usam segmentos lineares. '
                    'A carga deve diminuir com a vazão.\n'
                    'Rendimento: valores entre 0 e 100%. Volume: níveis e volumes crescentes.\n\n'
                    'Carregar/Salvar arquivo usa CRV do EPANET ou CSV, em L/s, m e m³. '
                    'Uma curva já associada deve manter o tipo exigido pelo equipamento.')
        else:
            text = ('Cada coluna representa um período. Edite a linha Multiplicador. '
                    'Ctrl+C e Ctrl+V copiam e colam valores de uma linha ou coluna de planilha.\n\n'
                    'O passo e o início do padrão são globais e ficam nas opções de simulação. '
                    'O ciclo se repete após o último multiplicador. '
                    'A linha tracejada mostra a média.\n\n'
                    'Média = 1 divide todos os valores pela média e altera o padrão. '
                    'Carregar/Salvar arquivo usa PAT do EPANET ou CSV. O arquivo PAT '
                    'guarda multiplicadores e descrição, sem alterar os tempos globais.')
        QMessageBox.information(self, 'Ajuda do editor', text)

    def preview(self):
        self._timer.stop()
        self._stash()
        self.figure.clear()
        axes = self.figure.add_subplot(111)
        pending = self._forms != self._initial_forms
        self.apply_button.setEnabled(pending)
        try:
            if not self._uid:
                raise ValueError('Selecione um item ou clique em Novo.')
            raw = self._forms[self._uid]
            props = self._collect(raw, self._uid)
            self.draw(axes, props)
            axes.set_title(props['name'], fontsize=11, parse_math=False)
            axes.grid(True, alpha=.2)
            self.status.setStyleSheet('')
            self.status.setText('Alterações pendentes: clique em Aplicar ou OK.' if pending else
                                'Edite a tabela para atualizar a prévia.')
        except (ValueError, ArithmeticError) as error:
            axes.set_axis_off()
            axes.text(.5, .5, 'A prévia será exibida quando os dados forem válidos.',
                      ha='center', va='center', transform=axes.transAxes, wrap=True)
            self.info.setText(str(error))
            self.status.setStyleSheet('color: #a33125;')
            self.status.setText(str(error))
        self.canvas.draw_idle()

    def _plot(self, layout):
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.PlainText)
        layout.addWidget(self.info)
        self.figure = Figure(figsize=(5, 3), layout='constrained')
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.canvas.setMinimumHeight(220)
        layout.addWidget(self.canvas, 1)

    def import_file(self):
        kind = 'Curva EPANET (*.crv)' if self.KIND == 'curve' else 'Padrão EPANET (*.pat)'
        path, _ = QFileDialog.getOpenFileName(self, 'Carregar dados', '',
                                             kind + ';;CSV/TXT (*.csv *.txt);;Todos (*.*)')
        if not path:
            return
        try:
            data = read_series_file(path, self.KIND)
            raw = copy.deepcopy(self.form_data())
            if self.KIND == 'curve':
                curve_type = data['curve_type'] or raw['curve_type']
                validate_curve(curve_type, data['values'])
                raw.update(curve_type=curve_type, rows=[[text_number(v) for v in row] for row in data['values']] + [['', '']])
            else:
                raw['values'] = [text_number(v) for v in data['values']]
            if data['notes'] is not None:
                raw['notes'] = data['notes']
        except (ValueError, OSError) as error:
            QMessageBox.warning(self, 'Carregar dados', str(error))
            return
        self._forms[self._uid] = raw
        self._loading = True
        self.description.setPlainText(raw['notes'])
        self.load_data(raw)
        self._loading = False
        self.changed()
        self.preview()

    def export_file(self):
        try:
            props = self._collect(self.form_data(), self._uid)
        except ValueError as error:
            QMessageBox.warning(self, 'Salvar arquivo', str(error))
            return
        extension = '.crv' if self.KIND == 'curve' else '.pat'
        label = 'Curva EPANET (*.crv)' if self.KIND == 'curve' else 'Padrão EPANET (*.pat)'
        path, selected = QFileDialog.getSaveFileName(self, 'Salvar dados', props['name'] + extension,
                                                    label + ';;CSV (*.csv)')
        if not path:
            return
        if not Path(path).suffix:
            path += '.csv' if selected.startswith('CSV') else extension
        try:
            write_series_file(path, self.KIND, props)
        except OSError as error:
            QMessageBox.warning(self, 'Salvar arquivo', str(error))


class CurvesDialog(_SeriesEditor):
    KIND = 'curve'
    TITLE = 'Editor de curvas — AVANT HIDRO'

    def build_editor(self):
        self.editor = QWidget()
        layout = QVBoxLayout(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)
        self.ctype = QComboBox()
        for key, label in CURVE_LABELS.items():
            self.ctype.addItem(label, key)
        layout.addWidget(self.ctype)
        split = QSplitter(Qt.Horizontal)
        table_widget = QWidget()
        table_layout = QVBoxLayout(table_widget)
        table_layout.setContentsMargins(0, 0, 0, 0)
        self.pts = _DataTable(0, 2)
        self.pts.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.pts.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table_layout.addWidget(self.pts, 1)
        buttons = QHBoxLayout()
        for label, callback in [('+ Ponto', self.add_point), ('− Ponto', self.del_point),
                                ('Colar', self.paste), ('Copiar', self.copy)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        table_layout.addLayout(buttons)
        split.addWidget(table_widget)
        chart = QWidget()
        chart_layout = QVBoxLayout(chart)
        self._plot(chart_layout)
        split.addWidget(chart)
        split.setSizes([340, 520])
        layout.addWidget(split, 1)
        self.right.addWidget(self.editor, 1)
        self.ctype.currentIndexChanged.connect(self._type_changed)
        self.pts.cellChanged.connect(self._cell_changed)
        self.pts.pasteRequested.connect(self.paste)
        self.pts.copyRequested.connect(self.copy)

    def to_form(self, e):
        return {'name': e.name, 'notes': e.notes, 'curve_type': e.curve_type,
                'rows': [[text_number(x), text_number(y)] for x, y in e.points] + [['', '']]}

    def form_data(self):
        return {'name': self.name.text(), 'notes': self.description.toPlainText(),
                'curve_type': self.ctype.currentData(),
                'rows': [[self.pts.item(r, c).text() if self.pts.item(r, c) else '' for c in range(2)]
                         for r in range(self.pts.rowCount())]}

    def load_data(self, raw):
        self.pts.setRowCount(0)
        if raw:
            self.ctype.setCurrentIndex(self.ctype.findData(raw['curve_type']))
            self.pts.setRowCount(len(raw['rows']))
            for r, row in enumerate(raw['rows']):
                for c, value in enumerate(row):
                    self.pts.setItem(r, c, QTableWidgetItem(value))
        self._axes()

    def _axes(self):
        self.pts.setHorizontalHeaderLabels(CURVE_AXES.get(self.ctype.currentData(), ('X', 'Y')))

    def _type_changed(self):
        self._axes()
        self.changed()

    def _cell_changed(self):
        if not self._loading and self.pts.rowCount() and any(
                self.pts.item(self.pts.rowCount() - 1, c) and
                self.pts.item(self.pts.rowCount() - 1, c).text().strip() for c in (0, 1)):
            self.pts.insertRow(self.pts.rowCount())
        self.changed()

    def add_point(self):
        row = self.pts.rowCount() - 1
        if row < 0 or any(self.pts.item(row, c) and self.pts.item(row, c).text() for c in (0, 1)):
            row = self.pts.rowCount()
            self.pts.insertRow(row)
        self._loading = True
        for c in (0, 1):
            if self.pts.item(row, c) is None:
                self.pts.setItem(row, c, QTableWidgetItem(''))
        self._loading = False
        self.pts.setCurrentCell(row, 0)
        self.pts.editItem(self.pts.item(row, 0))
        self.changed()

    def del_point(self):
        for row in sorted({i.row() for i in self.pts.selectedIndexes()}, reverse=True):
            self.pts.removeRow(row)
        self.changed()

    def paste(self):
        try:
            rows = parse_curve_text(QApplication.clipboard().text())
        except ValueError as error:
            QMessageBox.warning(self, 'Colar pontos', str(error))
            return
        start = max(0, self.pts.currentRow())
        self._loading = True
        self.pts.setRowCount(max(self.pts.rowCount(), start + len(rows) + 1))
        for r, row in enumerate(rows, start):
            for c, value in enumerate(row):
                self.pts.setItem(r, c, QTableWidgetItem(text_number(value)))
        self._loading = False
        self.changed()
        self.preview()

    def copy(self):
        rows = sorted({i.row() for i in self.pts.selectedIndexes()}) or list(range(self.pts.rowCount()))
        data = self.form_data()['rows']
        QApplication.clipboard().setText('\n'.join('\t'.join(data[r]) for r in rows if any(data[r])))

    def draw(self, axes, props):
        points = props['points']
        xs, ys = zip(*points)
        fit = fit_pump(points) if props['curve_type'] == 'PUMP' else None
        if fit:
            maximum = max(xs[-1], fit.zero_flow)
            sample = [maximum * i / 160 for i in range(161)]
            axes.plot(sample, [max(0, fit.head(x)) for x in sample], color='#e87924', label='Ajuste EPANET')
            axes.scatter(xs, ys, color='#0068b4', zorder=3, label='Pontos informados')
            axes.legend(fontsize=8)
            self.info.setText(fit.equation)
        else:
            axes.plot(xs, ys, 'o-', color='#0068b4')
            self.info.setText(f'{len(points)} ponto(s)' + (
                ' · interpolação linear por trechos.' if len(points) > 1 else ' informado.'))
        axes.set_xlabel(CURVE_AXES[props['curve_type']][0])
        axes.set_ylabel(CURVE_AXES[props['curve_type']][1])
        axes.set_xlim(left=0)
        axes.set_ylim(bottom=0)


class PatternsDialog(_SeriesEditor):
    KIND = 'pattern'
    TITLE = 'Editor de padrões temporais — AVANT HIDRO'

    def build_editor(self):
        self.editor = QWidget()
        layout = QVBoxLayout(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel('Número de períodos:'))
        self.count = QSpinBox()
        self.count.setRange(0, 100000)
        row.addWidget(self.count)
        for label, callback in [('+ Período', self.add_period), ('− Período', self.del_period),
                                ('Colar', self.paste), ('Copiar', self.copy), ('Média = 1', self.normalize)]:
            button = QPushButton(label)
            button.clicked.connect(callback)
            if label == 'Média = 1':
                button.setToolTip('Divide os multiplicadores pela média; altera os valores do padrão.')
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.table = _DataTable(2, 0)
        self.table.setVerticalHeaderLabels(['Intervalo (h)', 'Multiplicador'])
        self.table.horizontalHeader().setDefaultSectionSize(80)
        self.table.setMinimumHeight(110)
        self.table.setMaximumHeight(145)
        layout.addWidget(self.table)
        self.timing = QLabel()
        self.timing.setWordWrap(True)
        layout.addWidget(self.timing)
        self._plot(layout)
        self.right.addWidget(self.editor, 1)
        self.count.valueChanged.connect(self._resize)
        self.table.cellChanged.connect(self.changed)
        self.table.pasteRequested.connect(self.paste)
        self.table.copyRequested.connect(self.copy)

    def to_form(self, e):
        return {'name': e.name, 'notes': e.notes, 'values': [text_number(v) for v in e.multipliers]}

    def form_data(self):
        return {'name': self.name.text(), 'notes': self.description.toPlainText(),
                'values': [self.table.item(1, c).text() if self.table.item(1, c) else ''
                           for c in range(self.table.columnCount())]}

    def load_data(self, raw):
        values = raw['values'] if raw else []
        self.table.setColumnCount(len(values))
        self.count.blockSignals(True)
        self.count.setValue(len(values))
        self.count.blockSignals(False)
        step = self.project.sim_options.pattern_step_h
        for c, value in enumerate(values):
            interval = QTableWidgetItem(f'{c * step:g}–{(c + 1) * step:g}')
            interval.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.table.setItem(0, c, interval)
            self.table.setItem(1, c, QTableWidgetItem(value))
        self.table.setHorizontalHeaderLabels([str(i + 1) for i in range(len(values))])
        self.timing.setText(f'Passo global: {step:g} h · início do padrão: '
                            f'{self.project.sim_options.pattern_start_h:g} h. '
                            'Tempos configurados nas opções de simulação.')

    def _resize(self, count):
        if self._loading:
            return
        raw = self.form_data()
        raw['values'] = raw['values'][:count] + ['1'] * max(0, count - len(raw['values']))
        self._loading = True
        self.load_data(raw)
        self._loading = False
        self.changed()

    def add_period(self):
        self.count.setValue(self.count.value() + 1)

    def del_period(self):
        selected = {i.column() for i in self.table.selectedIndexes()}
        if not selected and self.table.columnCount():
            selected = {self.table.columnCount() - 1}
        raw = self.form_data()
        raw['values'] = [v for c, v in enumerate(raw['values']) if c not in selected]
        self._loading = True
        self.load_data(raw)
        self._loading = False
        self.changed()

    def paste(self):
        try:
            values = parse_pattern_text(QApplication.clipboard().text())
        except ValueError as error:
            QMessageBox.warning(self, 'Colar multiplicadores', str(error))
            return
        raw = self.form_data()
        start = max(0, self.table.currentColumn())
        required = start + len(values)
        raw['values'] += ['1'] * max(0, required - len(raw['values']))
        raw['values'][start:required] = [text_number(v) for v in values]
        self._loading = True
        self.load_data(raw)
        self._loading = False
        self.changed()
        self.preview()

    def copy(self):
        cols = sorted({i.column() for i in self.table.selectedIndexes()}) or list(range(self.table.columnCount()))
        values = self.form_data()['values']
        QApplication.clipboard().setText('\t'.join(values[c] for c in cols))

    def normalize(self):
        try:
            raw = self.form_data()
            values = validate_pattern(raw['values'])
            mean = math.fsum(values) / len(values)
            if mean <= 0:
                raise ValueError('A normalização exige média positiva.')
            raw['values'] = [text_number(v / mean) for v in values]
        except (ValueError, ArithmeticError) as error:
            QMessageBox.warning(self, 'Normalizar', str(error))
            return
        self._loading = True
        self.load_data(raw)
        self._loading = False
        self.changed()
        self.preview()

    def draw(self, axes, props):
        values = props['multipliers']
        step = self.project.sim_options.pattern_step_h
        if not math.isfinite(step) or step <= 0:
            raise ValueError('Configure um passo de padrão positivo nas opções de simulação.')
        duration = len(values) * step
        mean = math.fsum(values) / len(values)
        if len(values) <= 256:
            axes.bar([i * step for i in range(len(values))], values, width=step * .93,
                     align='edge', color=['#0068b4' if v >= 0 else '#b74b36' for v in values])
        else:
            axes.stairs(values, [i * step for i in range(len(values) + 1)], fill=True, color='#0068b4')
        axes.axhline(mean, color='#e87924', linestyle='--', label=f'Média {mean:.4g}')
        offset = self.project.sim_options.pattern_start_h % duration
        if offset:
            axes.axvline(offset, color='#555555', linestyle=':', label='Posição no ciclo em t=0')
        axes.legend(fontsize=8)
        axes.set_xlabel('Tempo no ciclo (h)')
        axes.set_ylabel('Multiplicador')
        axes.set_xlim(0, duration)
        self.info.setText(f'{len(values)} períodos · ciclo {duration:g} h · média {mean:.4g} · '
                          f'mínimo {min(values):g} · máximo {max(values):g}' +
                          (' · Atenção: multiplicadores negativos invertem o sinal da grandeza.' if min(values) < 0 else ''))
