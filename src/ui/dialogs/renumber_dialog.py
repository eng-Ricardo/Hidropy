"""Prévia e configuração da renumeração de junções e tubulações."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QGridLayout, QGroupBox,
                               QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ...hydraulics.renumbering import (METHODS, RenumberError, RenumberSettings,
                                      export_mapping, plan_renumber)


class RenumberDialog(QDialog):
    def __init__(self, controller, parent=None, time_index=0):
        super().__init__(parent)
        self.setWindowTitle('Renumerar nós e trechos')
        self.resize(850, 720)
        self.ctrl = controller
        self.plan = None
        self._refreshing = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.preview)
        layout = QVBoxLayout(self)
        intro = QLabel('A renumeração será aplicada apenas ao cenário ativo. '
                       'Reservatórios, tanques, bombas e válvulas mantêm seus nomes. '
                       'Conexões, controles e demais propriedades são preservados.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        group = QGroupBox('Prefixos e formato')
        form = QGridLayout(group)
        for col, text in enumerate(('Renumerar', 'Prefixo', 'Dígitos', 'Número inicial')):
            form.addWidget(QLabel(text), 0, col)
        self.node_enabled = QCheckBox('Junções (nós de consumo)')
        self.pipe_enabled = QCheckBox('Tubulações')
        self.node_enabled.setChecked(True)
        self.pipe_enabled.setChecked(True)
        self.node_prefix, self.pipe_prefix = QLineEdit('J-'), QLineEdit('P-')
        self.node_digits, self.pipe_digits = QSpinBox(), QSpinBox()
        self.node_start, self.pipe_start = QSpinBox(), QSpinBox()
        for widget in (self.node_digits, self.pipe_digits):
            widget.setRange(1, 6)
            widget.setValue(3)
        for widget in (self.node_start, self.pipe_start):
            widget.setRange(1, 999999999)
            widget.setValue(1)
        for row, widgets in enumerate(((self.node_enabled, self.node_prefix, self.node_digits, self.node_start),
                                        (self.pipe_enabled, self.pipe_prefix, self.pipe_digits, self.pipe_start)), 1):
            for col, widget in enumerate(widgets):
                form.addWidget(widget, row, col)
        layout.addWidget(group)
        sort = QGroupBox('Ordenação')
        form = QGridLayout(sort)
        self.method = QComboBox()
        for key, label in METHODS.items():
            self.method.addItem(label, key)
        self.instant = QComboBox()
        form.addWidget(QLabel('Método:'), 0, 0)
        form.addWidget(self.method, 0, 1)
        form.addWidget(QLabel('Instante da simulação:'), 1, 0)
        form.addWidget(self.instant, 1, 1)
        self.description = QLabel()
        self.description.setWordWrap(True)
        form.addWidget(self.description, 2, 0, 1, 2)
        layout.addWidget(sort)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(['Tipo', 'ID atual', 'Novo ID', 'Vazão (L/s)'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        note = QLabel('Aplique após conferir a prévia. A operação pode ser desfeita com Ctrl+Z. '
                      'Execute nova simulação para atualizar os resultados com os novos nomes.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Cancel)
        self.apply_button = self.buttons.button(QDialogButtonBox.Apply)
        self.apply_button.setText('Aplicar renumeração')
        self.apply_button.clicked.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.export_button = QPushButton('Exportar correspondência (CSV)…')
        self.buttons.addButton(self.export_button, QDialogButtonBox.ActionRole)
        self.export_button.clicked.connect(self.export)
        layout.addWidget(self.buttons)
        for widget in (self.node_prefix, self.pipe_prefix):
            widget.textChanged.connect(self.schedule_preview)
        for widget in (self.node_digits, self.pipe_digits, self.node_start, self.pipe_start):
            widget.valueChanged.connect(self.schedule_preview)
        for widget in (self.node_enabled, self.pipe_enabled):
            widget.toggled.connect(self.schedule_preview)
        self.method.currentIndexChanged.connect(self.schedule_preview)
        self.instant.currentIndexChanged.connect(self.schedule_preview)
        self.ctrl.resultsChanged.connect(self.refresh)
        self.ctrl.projectReplaced.connect(self.refresh)
        self.ctrl.elementsChanged.connect(self.refresh)
        self.refresh()
        self.instant.setCurrentIndex(max(0, min(time_index, self.instant.count() - 1)))
        self.preview()

    def settings(self):
        return RenumberSettings(
            method=self.method.currentData(), rename_nodes=self.node_enabled.isChecked(),
            rename_pipes=self.pipe_enabled.isChecked(), node_prefix=self.node_prefix.text(),
            pipe_prefix=self.pipe_prefix.text(), node_digits=self.node_digits.value(),
            pipe_digits=self.pipe_digits.value(), node_start=self.node_start.value(),
            pipe_start=self.pipe_start.value())

    def refresh(self, *_):
        self._refreshing = True
        sim = self.ctrl.project.latest_result('simulation')
        current = self.instant.currentData()
        self.instant.clear()
        for i, second in enumerate(sim.get('times', []) if sim else []):
            self.instant.addItem(f'{second / 3600:g} h', i)
        self.instant.setCurrentIndex(max(0, self.instant.findData(current)))
        index = self.method.findData('hydraulic')
        available = bool(sim and self.ctrl.is_current(sim))
        self.method.model().item(index).setEnabled(available)
        self.method.model().item(index).setToolTip(
            'Usa as vazões da simulação do cenário ativo.' if available else
            'Execute uma simulação (F5) da rede atual para habilitar.')
        self._refreshing = False
        self.preview()

    def schedule_preview(self, *_):
        if self._refreshing:
            return
        self.apply_button.setEnabled(False)
        self.export_button.setEnabled(False)
        self._timer.start(150)

    def _build_plan(self):
        return plan_renumber(self.ctrl.project, self.settings(),
                             self.ctrl.project.latest_result('simulation'),
                             max(0, self.instant.currentIndex()))

    def preview(self):
        self._timer.stop()
        hydraulic = self.method.currentData() == 'hydraulic'
        self.instant.setEnabled(hydraulic and self.instant.count() > 1)
        if hydraulic:
            description = ('Percurso em largura a partir de reservatórios e tanques, seguindo '
                           'a vazão do instante escolhido. Tubulações em ordem de vazão absoluta '
                           'decrescente. Vazão zero segue o sentido de cadastro.')
        elif self.method.currentData() == 'original':
            description = 'Junções e tubulações seguem a ordem de cadastro do cenário atual.'
        else:
            description = ('A ordenação geométrica afeta as junções. Tubulações mantêm a ordem '
                           'de cadastro, como no protocolo da suíte. Empates mantêm a ordem original.')
        self.description.setText(description)
        for checked, widgets in (
                (self.node_enabled.isChecked(), (self.node_prefix, self.node_digits, self.node_start)),
                (self.pipe_enabled.isChecked(), (self.pipe_prefix, self.pipe_digits, self.pipe_start))):
            for widget in widgets:
                widget.setEnabled(checked)
        try:
            plan = self._build_plan()
        except (RenumberError, ValueError) as error:
            self.plan = None
            self.table.setRowCount(0)
            self.status.setText(str(error))
            self.apply_button.setEnabled(False)
            self.export_button.setEnabled(False)
            return
        self.plan = plan
        self.table.setRowCount(len(plan.items))
        for row, item in enumerate(plan.items):
            values = ['Junção' if item.kind == 'junction' else 'Tubulação',
                      item.old_name, item.new_name, '' if item.flow is None else f'{item.flow:.4g}']
            for col, value in enumerate(values):
                cell = QTableWidgetItem(value)
                cell.setData(Qt.UserRole, item.uid)
                self.table.setItem(row, col, cell)
        count = len(plan.changes)
        self.status.setText(f'{plan.node_count} junção(ões), {plan.pipe_count} tubulação(ões). '
                            f'{count} identificador(es) serão alterados.'
                            + (' A rede já está nesta sequência.' if not count else '')
                            + ('\n' + '\n'.join(plan.warnings) if plan.warnings else ''))
        self.apply_button.setEnabled(bool(plan.changes))
        self.export_button.setEnabled(True)

    def accept(self):
        previous = self.plan
        self.preview()
        if self.plan is None or not self.plan.changes:
            return
        if previous is not None and previous.items != self.plan.items:
            self.status.setText('A prévia mudou após uma atualização da rede ou dos resultados. '
                                'Confira os nomes e clique em Aplicar renumeração novamente.')
            return
        super().accept()

    def export(self):
        self.preview()
        if self.plan is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar correspondência de IDs',
                                             'renumeracao.csv', 'CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            export_mapping(self.plan, path)
        except OSError as error:
            QMessageBox.warning(self, 'Exportar correspondência', str(error))
