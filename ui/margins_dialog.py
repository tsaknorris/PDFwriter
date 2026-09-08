"""
Sivun marginaalien ja mittojen hallintadialogi (Page Margins & Boxes Dialog).
Mahdollistaa arkin marginaalien (vasen, oikea, ylä, ala) säätämisen millimetreinä ja pisteinä,
sekä CropBox-rajauksen että MediaBox-arkkikoon laajennuksen/pienennyksen.
"""

from typing import Optional
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QDoubleSpinBox,
    QPushButton, QGroupBox, QComboBox, QCheckBox, QFormLayout, QFrame
)
from pdf_engine.pdf_document import PDFDocumentModel


class MarginsDialog(QDialog):
    """Sivun marginaalien ja laatikoiden säätöikkuna."""

    margins_changed = pyqtSignal()

    def __init__(self, doc_model: PDFDocumentModel, current_page: int = 0, parent: Optional[QDialog] = None):
        super().__init__(parent)
        self.doc_model = doc_model
        self.current_page = current_page
        self.setWindowTitle("Sivun marginaalit ja arkkikoko")
        self.setMinimumWidth(440)

        self.pt_to_mm = 25.4 / 72.0
        self.mm_to_pt = 72.0 / 25.4

        self.init_ui()
        self.load_current_values()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 1. Sivun nykytilan yhteenveto
        info_group = QGroupBox("Sivun mitat")
        info_layout = QFormLayout(info_group)
        self.lbl_page_idx = QLabel(f"Sivu {self.current_page + 1} / {self.doc_model.page_count}")
        self.lbl_page_idx.setStyleSheet("font-weight: bold; color: #2980b9;")
        self.lbl_page_size = QLabel("-")
        info_layout.addRow("Aktiivinen sivu:", self.lbl_page_idx)
        info_layout.addRow("Nykyinen koko:", self.lbl_page_size)
        layout.addWidget(info_group)

        # 2. Marginaalisäätimet
        margins_group = QGroupBox("Marginaalit (mm)")
        margins_layout = QFormLayout(margins_group)

        self.spin_left = QDoubleSpinBox()
        self.spin_left.setRange(-200.0, 200.0)
        self.spin_left.setSingleStep(1.0)
        self.spin_left.setDecimals(1)
        self.spin_left.setSuffix(" mm")

        self.spin_right = QDoubleSpinBox()
        self.spin_right.setRange(-200.0, 200.0)
        self.spin_right.setSingleStep(1.0)
        self.spin_right.setDecimals(1)
        self.spin_right.setSuffix(" mm")

        self.spin_top = QDoubleSpinBox()
        self.spin_top.setRange(-200.0, 200.0)
        self.spin_top.setSingleStep(1.0)
        self.spin_top.setDecimals(1)
        self.spin_top.setSuffix(" mm")

        self.spin_bottom = QDoubleSpinBox()
        self.spin_bottom.setRange(-200.0, 200.0)
        self.spin_bottom.setSingleStep(1.0)
        self.spin_bottom.setDecimals(1)
        self.spin_bottom.setSuffix(" mm")

        margins_layout.addRow("Vasen marginaali:", self.spin_left)
        margins_layout.addRow("Oikea marginaali:", self.spin_right)
        margins_layout.addRow("Ylämarginaali:", self.spin_top)
        margins_layout.addRow("Alamarginaali:", self.spin_bottom)
        layout.addWidget(margins_group)

        # 3. Toimintatapa ja laajuus
        opts_group = QGroupBox("Asetukset")
        opts_layout = QVBoxLayout(opts_group)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Toimintatapa:"))
        self.combo_mode = QComboBox()
        self.combo_mode.addItem("✂️ Rajaa sivu (CropBox - leikkaa reunoja)", "cropbox")
        self.combo_mode.addItem("📐 Muuta arkkikokoa (MediaBox - laajenna/pienennä)", "mediabox")
        mode_row.addWidget(self.combo_mode)
        opts_layout.addLayout(mode_row)

        self.chk_all_pages = QCheckBox("Käytä samoja marginaaleja dokumentin kaikille sivuille")
        opts_layout.addWidget(self.chk_all_pages)

        layout.addWidget(opts_group)

        # 4. Painikkeet
        btn_box = QHBoxLayout()
        self.btn_apply = QPushButton("Käytä marginaaleja")
        self.btn_apply.setStyleSheet("background-color: #2980b9; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self.btn_apply.clicked.connect(self._on_apply)

        self.btn_close = QPushButton("Sulje")
        self.btn_close.clicked.connect(self.accept)

        btn_box.addStretch()
        btn_box.addWidget(self.btn_apply)
        btn_box.addWidget(self.btn_close)
        layout.addLayout(btn_box)

    def load_current_values(self):
        """Lataa sivun nykyiset mitat käyttöliittymään."""
        boxes = self.doc_model.get_page_boxes(self.current_page)
        if not boxes:
            return

        w_mm = boxes.get("width_mm", 0.0)
        h_mm = boxes.get("height_mm", 0.0)
        w_pt = boxes.get("width_pt", 0.0)
        h_pt = boxes.get("height_pt", 0.0)
        self.lbl_page_size.setText(f"{w_mm:.1f} × {h_mm:.1f} mm ({w_pt:.1f} × {h_pt:.1f} pt)")

        self.spin_left.setValue(boxes.get("left_mm", 0.0))
        self.spin_right.setValue(boxes.get("right_mm", 0.0))
        self.spin_top.setValue(boxes.get("top_mm", 0.0))
        self.spin_bottom.setValue(boxes.get("bottom_mm", 0.0))

    def _on_apply(self):
        left_mm = self.spin_left.value()
        right_mm = self.spin_right.value()
        top_mm = self.spin_top.value()
        bottom_mm = self.spin_bottom.value()

        left_pt = left_mm * self.mm_to_pt
        right_pt = right_mm * self.mm_to_pt
        top_pt = top_mm * self.mm_to_pt
        bottom_pt = bottom_mm * self.mm_to_pt

        mode = self.combo_mode.currentData()
        apply_all = self.chk_all_pages.isChecked()

        self.doc_model.set_page_margins(
            page_idx=self.current_page,
            left_pt=left_pt,
            top_pt=top_pt,
            right_pt=right_pt,
            bottom_pt=bottom_pt,
            mode=mode,
            apply_to_all=apply_all
        )
        self.margins_changed.emit()
        self.load_current_values()
