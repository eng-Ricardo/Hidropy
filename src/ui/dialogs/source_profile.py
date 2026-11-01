"""Consulta e exportação das cotas de vértices recebidas do QEPANET."""

import csv

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog,
                               QDialogButtonBox, QFileDialog, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)


class SourceProfileDialog(QDialog):
    def __init__(self, link, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Cotas dos vértices — QEPANET')
        self.resize(680, 430)
        self.name = link.name
        self.rows = link.source_data.get('qepanet', {}).get('vertex_profile', [])
        layout = QVBoxLayout(self)
        title = QLabel(f'Trecho {link.name} · {len(self.rows)} vértices intermediários')
        title.setTextFormat(Qt.PlainText)
        layout.addWidget(title)
        note = QLabel('Coordenadas originais do mapa e cotas Z em metros. '
                      'Dados informativos da importação, sem alterar o comprimento hidráulico.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QTableWidget(len(self.rows), 4)
        self.table.setHorizontalHeaderLabels(['Vértice', 'X original', 'Y original', 'Cota Z (m)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        for i, row in enumerate(self.rows):
            for j, value in enumerate([i + 1, *row]):
                self.table.setItem(i, j, QTableWidgetItem('' if value is None else format(value, '.12g')))
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = QPushButton('Copiar')
        copy.clicked.connect(self.copy)
        buttons.addButton(copy, QDialogButtonBox.ActionRole)
        export = QPushButton('Exportar CSV...')
        export.clicked.connect(self.export)
        buttons.addButton(export, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        QShortcut(QKeySequence.Copy, self, activated=self.copy)

    def copy(self):
        selected = sorted({item.row() for item in self.table.selectedIndexes()}) or range(len(self.rows))
        QApplication.clipboard().setText('\n'.join('\t'.join(
            self.table.item(i, j).text() for j in range(4)) for i in selected))

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Exportar cotas dos vértices',
                                             f'{self.name}_vertices.csv', 'CSV (*.csv)')
        if not path:
            return
        if not path.lower().endswith('.csv'):
            path += '.csv'
        try:
            with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
                writer = csv.writer(stream, delimiter=';')
                writer.writerow(['Trecho', 'Vértice', 'X original', 'Y original', 'Cota Z (m)'])
                writer.writerows([self.name, i, *row] for i, row in enumerate(self.rows, 1))
        except OSError as error:
            QMessageBox.warning(self, 'Exportar cotas', str(error))
