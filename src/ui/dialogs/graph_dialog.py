"""Seleção e visualização de gráficos dos resultados da simulação."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
                               QSplitter, QVBoxLayout, QWidget)

from ...hydraulics.models import KIND_LABELS
from ...results import graphs
from ...results.graph_rendering import draw_graph, draw_message

log = logging.getLogger(__name__)

DESCRIPTIONS = {
    'time': 'Compare um ou mais elementos ao longo dos instantes calculados. '
            'Em regime permanente, cada série tem um único ponto.',
    'profile': 'Adicione pelo menos dois nós e organize a lista. O perfil segue o menor '
               'percurso cadastrado entre eles, incluindo os nós intermediários.',
    'contour': 'Usa todos os nós compatíveis com o parâmetro, no instante escolhido. '
               'Exige pelo menos três posições distintas que não estejam alinhadas.',
    'frequency': 'Distribuição acumulada de todos os nós ou trechos compatíveis, '
                 'no instante escolhido. A lista individual não é usada.',
    'system': 'Compara o fornecimento dos reservatórios, a demanda nas junções e o '
              'armazenamento nos tanques ao longo do período calculado.',
}


class GraphDialog(QDialog):
    def __init__(self, controller, parent=None, time_index=0):
        super().__init__(parent)
        self.setWindowTitle('Gráficos de resultados — AVANT HIDRO')
        self.resize(1120, 720)
        self.setMinimumSize(850, 560)
        self.ctrl = controller
        self.graph_data = None
        self._uids = {'nodes': [], 'links': []}
        self._collection = 'nodes'
        self._updating = True
        self._last_scenario = controller.project.active_scenario
        self._build()
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.nodes_radio.toggled.connect(lambda checked: self._collection_changed() if checked else None)
        self.links_radio.toggled.connect(lambda checked: self._collection_changed() if checked else None)
        self.parameter.currentIndexChanged.connect(self._parameter_changed)
        self.instant.currentIndexChanged.connect(self.generate)
        self.generate_button.clicked.connect(self.generate)
        self.ctrl.resultsChanged.connect(self.refresh)
        self.ctrl.projectReplaced.connect(self.refresh)
        self.ctrl.elementsChanged.connect(self.refresh)
        self._updating = False
        self.refresh()
        self.set_time_index(time_index)

    def _build(self):
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
        from matplotlib.figure import Figure

        layout = QVBoxLayout(self)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        split = QSplitter(Qt.Horizontal)
        controls = QWidget()
        controls.setMaximumWidth(350)
        controls.setMinimumWidth(270)
        left = QVBoxLayout(controls)
        left.setContentsMargins(0, 0, 8, 0)
        config = QGroupBox('Configuração do gráfico')
        form = QFormLayout(config)
        self.kind = QComboBox()
        self.kind.setObjectName('graph_kind')
        for key, label in graphs.GRAPH_TYPES.items():
            self.kind.addItem(label, key)
        self.parameter = QComboBox()
        self.parameter.setObjectName('graph_parameter')
        self.instant = QComboBox()
        self.instant.setObjectName('graph_time')
        form.addRow('Tipo:', self.kind)
        form.addRow('Parâmetro:', self.parameter)
        form.addRow('Instante:', self.instant)
        left.addWidget(config)
        self.objects = QGroupBox('Elementos a representar')
        box = QVBoxLayout(self.objects)
        types = QHBoxLayout()
        self.nodes_radio = QRadioButton('Nós')
        self.links_radio = QRadioButton('Trechos')
        self.nodes_radio.setChecked(True)
        types.addWidget(self.nodes_radio)
        types.addWidget(self.links_radio)
        box.addLayout(types)
        self.individual = QWidget()
        selection = QVBoxLayout(self.individual)
        selection.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.available = QComboBox()
        self.available.setObjectName('graph_available')
        self.available.setEditable(True)
        self.available.setInsertPolicy(QComboBox.NoInsert)
        self.available.setMinimumContentsLength(10)
        self.add_button = QPushButton('Adicionar')
        self.add_button.clicked.connect(self.add_current)
        row.addWidget(self.available, 1)
        row.addWidget(self.add_button)
        selection.addLayout(row)
        self.selected = QListWidget()
        self.selected.setObjectName('graph_selected')
        self.selected.setSelectionMode(QAbstractItemView.ExtendedSelection)
        selection.addWidget(self.selected)
        row = QHBoxLayout()
        for text, slot in (('Remover', self.remove_selected), ('Subir', lambda: self.move(-1)),
                           ('Descer', lambda: self.move(1))):
            button = QPushButton(text)
            button.clicked.connect(slot)
            row.addWidget(button)
        selection.addLayout(row)
        self.from_canvas = QPushButton('Adicionar seleção do desenho')
        self.from_canvas.clicked.connect(self.add_selection)
        selection.addWidget(self.from_canvas)
        box.addWidget(self.individual)
        left.addWidget(self.objects)
        self.description = QLabel()
        self.description.setWordWrap(True)
        left.addWidget(self.description)
        left.addStretch()
        self.generate_button = QPushButton('Gerar / atualizar gráfico')
        left.addWidget(self.generate_button)
        split.addWidget(controls)
        preview = QWidget()
        right = QVBoxLayout(preview)
        right.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(figsize=(8, 5), facecolor='white')
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.navigation = NavigationToolbar2QT(self.canvas, self)
        right.addWidget(self.navigation)
        right.addWidget(self.canvas, 1)
        split.addWidget(preview)
        split.setSizes([300, 800])
        layout.addWidget(split, 1)
        footer = QHBoxLayout()
        self.save_image = QPushButton('Exportar imagem…')
        self.save_image.clicked.connect(self.export_image)
        self.save_csv = QPushButton('Exportar dados (CSV)…')
        self.save_csv.clicked.connect(self.export_data)
        footer.addWidget(self.save_image)
        footer.addWidget(self.save_csv)
        footer.addStretch()
        close = QPushButton('Fechar')
        close.clicked.connect(self.close)
        footer.addWidget(close)
        layout.addLayout(footer)

    def collection(self):
        return 'nodes' if self.nodes_radio.isChecked() else 'links'

    def simulation(self):
        return self.ctrl.project.latest_result('simulation')

    def set_time_index(self, index):
        self.instant.setCurrentIndex(max(0, min(index, self.instant.count() - 1)))

    def refresh(self, *_):
        if self._updating:
            return
        self._updating = True
        try:
            if self._last_scenario != self.ctrl.project.active_scenario:
                self._uids = {'nodes': [], 'links': []}
                self._last_scenario = self.ctrl.project.active_scenario
            sim = self.simulation()
            old_time = self.instant.currentData()
            self.instant.clear()
            for i, second in enumerate(sim.get('times', []) if sim else []):
                self.instant.addItem(f'{second / 3600:g} h', i)
            self.instant.setCurrentIndex(max(0, self.instant.findData(old_time)))
            self._sync_parameters()
        finally:
            self._updating = False
        self._kind_changed()

    def _sync_parameters(self):
        current = self.parameter.currentData()
        self.parameter.clear()
        for key, text in graphs.parameters(self.collection()).items():
            self.parameter.addItem(text, key)
        self.parameter.setCurrentIndex(max(0, self.parameter.findData(current)))

    def _kind_changed(self, *_):
        if self._updating:
            return
        kind = self.kind.currentData()
        if kind in ('profile', 'contour', 'system'):
            self.nodes_radio.setChecked(True)
        if kind == 'system':
            self.parameter.setCurrentIndex(self.parameter.findData('demand'))
        self.links_radio.setEnabled(kind not in ('profile', 'contour', 'system'))
        self.nodes_radio.setEnabled(kind != 'system')
        self.objects.setEnabled(kind != 'system')
        self.individual.setVisible(kind in ('time', 'profile'))
        self.parameter.setEnabled(kind != 'system')
        self.instant.setEnabled(kind in ('profile', 'contour', 'frequency') and self.instant.count() > 1)
        self.description.setText(DESCRIPTIONS[kind])
        self._fill_objects()
        self.generate()

    def _collection_changed(self):
        if self._updating:
            return
        self._collection = self.collection()
        self._updating = True
        self._sync_parameters()
        self._updating = False
        self._fill_objects()
        self.generate()

    def _parameter_changed(self, *_):
        if not self._updating:
            self._fill_objects()
            self.generate()

    def _fill_objects(self):
        elements = graphs.eligible_elements(self.ctrl.project, self.collection(),
                                             self.parameter.currentData())
        allowed = {e.uid: e for e in elements}
        current = self.available.currentData()
        self.available.clear()
        for e in elements:
            self.available.addItem(f'{e.name} — {KIND_LABELS[e.KIND]}', e.uid)
        self.available.setCurrentIndex(max(0, self.available.findData(current)))
        chosen = [uid for uid in self._uids[self.collection()] if uid in allowed]
        if not chosen:
            chosen = [uid for uid in self.ctrl.selection if uid in allowed]
        if not chosen and elements:
            chosen = [elements[0].uid]
        self._uids[self.collection()] = chosen
        self._show_selected()
        self.add_button.setEnabled(bool(elements))

    def _show_selected(self):
        self.selected.clear()
        for uid in self._uids[self.collection()]:
            element = self.ctrl.project.network.get(uid)
            if element:
                item = QListWidgetItem(element.name)
                item.setData(Qt.UserRole, uid)
                self.selected.addItem(item)

    def add_current(self):
        index = self.available.findText(self.available.currentText())
        uid = self.available.itemData(index) if index >= 0 else None
        if uid is None:
            for i in range(self.available.count()):
                element = self.ctrl.project.network.get(self.available.itemData(i))
                if element and element.name == self.available.currentText().strip():
                    uid = element.uid
                    break
        if uid is None:
            self.status.setText('Escolha um elemento disponível ou digite seu identificador exato.')
            return
        if uid and uid not in self._uids[self.collection()]:
            self._uids[self.collection()].append(uid)
            self._show_selected()
            self.selected.setCurrentRow(self.selected.count() - 1)
            self.generate()

    def add_selection(self):
        allowed = {self.available.itemData(i) for i in range(self.available.count())}
        chosen = self._uids[self.collection()]
        for uid in self.ctrl.selection:
            if uid in allowed and uid not in chosen:
                chosen.append(uid)
        self._show_selected()
        self.generate()

    def remove_selected(self):
        remove = {item.data(Qt.UserRole) for item in self.selected.selectedItems()}
        self._uids[self.collection()] = [uid for uid in self._uids[self.collection()] if uid not in remove]
        self._show_selected()
        self.generate()

    def move(self, direction):
        index = self.selected.currentRow()
        chosen = self._uids[self.collection()]
        target = index + direction
        if index >= 0 and 0 <= target < len(chosen):
            chosen[index], chosen[target] = chosen[target], chosen[index]
            self._show_selected()
            self.selected.setCurrentRow(target)
            self.generate()

    def generate(self, *_):
        if self._updating:
            return
        sim = self.simulation()
        self.graph_data = None
        try:
            if sim and not self.ctrl.is_current(sim):
                raise graphs.GraphError('A rede foi alterada após este cálculo. '
                                        'Execute novamente a simulação (F5) para gerar gráficos.')
            data = graphs.build_graph(self.ctrl.project, sim, self.kind.currentData(),
                                      self.collection(), self.parameter.currentData(),
                                      self._uids[self.collection()], max(0, self.instant.currentIndex()))
            draw_graph(self.figure, data)
            self.graph_data = data
            scenario = self.ctrl.project.scenario().name
            self.status.setText(f'Cenário: {scenario} · {len(sim["times"])} instante(s) calculado(s)')
        except graphs.GraphError as error:
            self.status.setText(str(error))
            draw_message(self.figure, str(error))
        except Exception as error:
            log.exception('Falha ao desenhar gráfico')
            self.status.setText(f'Não foi possível gerar o gráfico: {error}')
            draw_message(self.figure, self.status.text())
        self.save_image.setEnabled(self.graph_data is not None)
        self.save_csv.setEnabled(self.graph_data is not None)
        self.canvas.draw_idle()

    def export_image(self):
        if self.graph_data is None:
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, 'Exportar gráfico', f'grafico_{self.graph_data.kind}.png',
            'PNG (*.png);;SVG (*.svg);;PDF (*.pdf)')
        if path:
            suffix = '.svg' if selected_filter.startswith('SVG') else \
                '.pdf' if selected_filter.startswith('PDF') else '.png'
            if Path(path).suffix.lower() not in ('.png', '.svg', '.pdf'):
                path += suffix
            try:
                self.figure.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
            except Exception as error:
                QMessageBox.warning(self, 'Exportar gráfico', str(error))

    def export_data(self):
        if self.graph_data is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar dados do gráfico',
                                             f'grafico_{self.graph_data.kind}.csv', 'CSV (*.csv)')
        if path:
            if not path.lower().endswith('.csv'):
                path += '.csv'
            try:
                graphs.export_csv(self.graph_data, path)
            except (OSError, graphs.GraphError) as error:
                QMessageBox.warning(self, 'Exportar dados', str(error))
