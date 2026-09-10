"""
Sivujen hallinta- ja erätoimintodialogi (Batch Page Operations Dialog).
Mahdollistaa useiden sivujen valinnan sivuväleillä (esim. "1-10, 20")
sekä erätoimenpiteet: poisto, kierto, purku uuteen PDF-tiedostoon, monistus ja siirto.
"""

import os
import re
from typing import Optional, List, Tuple
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QGroupBox, QFileDialog, QMessageBox, QSpinBox,
    QComboBox, QFrame, QWidget
)

from pdf_engine.pdf_document import PDFDocumentModel


def parse_page_range_string(range_str: str, max_pages: int) -> List[int]:
    """
    Parsii käyttäjän syöttämän sivuvälikuvauksen (esim. '1-10, 20, 25-30')
    0-pohjaisiksi sivunumeroiksi.
    Tukee:
    - Yksittäiset sivut: '1', '20'
    - Välit: '1-10', '1..10', '1 to 10'
    - Erottimet: pilkku ',', puolipiste ';', välilyönti
    - Avainsanat: 'all'/'kaikki'/'*', 'even'/'parilliset', 'odd'/'parittomat'
    """
    if not range_str or max_pages <= 0:
        return []

    clean = range_str.strip().lower()
    if clean in ("all", "kaikki", "*"):
        return list(range(max_pages))
    if clean in ("even", "parilliset"):
        return [i for i in range(max_pages) if (i + 1) % 2 == 0]
    if clean in ("odd", "parittomat"):
        return [i for i in range(max_pages) if (i + 1) % 2 == 1]

    # Korvataan vaihtoehtoiset erottimet pilkulla
    s = range_str.replace(";", ",").replace("..", "-").replace(" to ", "-")
    parts = s.split(",")
    selected_indices = set()

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Alivalinnat välilyönneillä (esim. "1 2 3")
        sub_tokens = part.split()
        for token in sub_tokens:
            token = token.strip()
            if not token:
                continue

            if "-" in token:
                range_match = re.match(r"^(\d+)\s*-\s*(\d+)$", token)
                if range_match:
                    start_p = int(range_match.group(1))
                    end_p = int(range_match.group(2))
                    p_min = max(1, min(start_p, end_p))
                    p_max = min(max_pages, max(start_p, end_p))
                    for p in range(p_min, p_max + 1):
                        selected_indices.add(p - 1)
            else:
                try:
                    p = int(token)
                    if 1 <= p <= max_pages:
                        selected_indices.add(p - 1)
                except ValueError:
                    pass

    return sorted(selected_indices)


def format_page_range_string(indices: List[int]) -> str:
    """
    Muotoilee 0-pohjaiset sivuindeksit tiiviiksi käyttäjäystävälliseksi
    1-pohjaiseksi merkkijonoksi (esim. [0,1,2,4,6,7] -> '1-3, 5, 7-8').
    """
    if not indices:
        return ""
    sorted_pages = sorted(set(i + 1 for i in indices))
    ranges = []
    start = sorted_pages[0]
    end = start

    for p in sorted_pages[1:]:
        if p == end + 1:
            end = p
        else:
            if start == end:
                ranges.append(str(start))
            else:
                ranges.append(f"{start}-{end}")
            start = p
            end = p

    if start == end:
        ranges.append(str(start))
    else:
        ranges.append(f"{start}-{end}")

    return ", ".join(ranges)


class BatchPageOperationsDialog(QDialog):
    """Sivujen erävalinta ja -toimintodialogi."""

    pages_modified = pyqtSignal(int)  # Lähettää aktiiviseksi tulevan sivun indeksin
    selection_applied = pyqtSignal(list)  # Lähettää valitut sivut pikkukuvalistalle

    def __init__(
        self,
        doc_model: PDFDocumentModel,
        initial_pages: Optional[List[int]] = None,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.doc_model = doc_model
        self.max_pages = self.doc_model.page_count if self.doc_model and self.doc_model.is_open else 0
        self.selected_indices: List[int] = []

        self.setWindowTitle("📑 Sivujen hallinta ja erätoiminnot")
        self.resize(620, 520)
        self.init_ui()

        # Alustetaan valinta
        if initial_pages:
            init_str = format_page_range_string(initial_pages)
            self.txt_range.setText(init_str)
        else:
            self.txt_range.setText("1")

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(16, 16, 16, 16)

        # 0. Yläotsikko ja dokumentin perustiedot
        header_box = QHBoxLayout()
        lbl_title = QLabel("📑 Sivujen valinta ja erätoimenpiteet")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: bold; color: #38bdf8;")
        header_box.addWidget(lbl_title)
        header_box.addStretch()

        self.lbl_total_pages = QLabel(f"Dokumentissa sivuja: <b>{self.max_pages}</b>")
        self.lbl_total_pages.setStyleSheet("color: #cbd5e1; font-size: 12px;")
        header_box.addWidget(self.lbl_total_pages)
        layout.addLayout(header_box)

        # 1. Sivuvälien valinta
        sel_group = QGroupBox("1. Valitse sivut (Syötä sivuvälit tai käytä pikavalintoja)")
        sel_layout = QVBoxLayout(sel_group)
        sel_layout.setSpacing(8)

        input_row = QHBoxLayout()
        input_row.addWidget(QLabel("Sivut:"))
        self.txt_range = QLineEdit()
        self.txt_range.setPlaceholderText("esim. 1-10, 20 tai 25-30")
        self.txt_range.setStyleSheet(
            "background-color: #16161a; color: #f8fafc; border: 1px solid #4a4a58; border-radius: 4px; padding: 6px; font-size: 13px;"
        )
        self.txt_range.textChanged.connect(self._on_range_text_changed)
        input_row.addWidget(self.txt_range)
        sel_layout.addLayout(input_row)

        # Pikavalintapainikkeet
        quick_row = QHBoxLayout()
        self.btn_sel_all = QPushButton("📑 Kaikki (1-N)")
        self.btn_sel_all.clicked.connect(self._select_all)

        self.btn_sel_even = QPushButton("🔢 Parilliset")
        self.btn_sel_even.clicked.connect(self._select_even)

        self.btn_sel_odd = QPushButton("🔣 Parittomat")
        self.btn_sel_odd.clicked.connect(self._select_odd)

        self.btn_sel_invert = QPushButton("🔄 Käännä valinta")
        self.btn_sel_invert.clicked.connect(self._select_invert)

        self.btn_sel_clear = QPushButton("❌ Tyhjennä")
        self.btn_sel_clear.clicked.connect(self._select_clear)

        for btn in (self.btn_sel_all, self.btn_sel_even, self.btn_sel_odd, self.btn_sel_invert, self.btn_sel_clear):
            btn.setStyleSheet(
                "background-color: #2a2a34; color: #f8fafc; border: 1px solid #4a4a58; border-radius: 3px; padding: 4px 8px; font-size: 11px;"
            )
            quick_row.addWidget(btn)
        sel_layout.addLayout(quick_row)

        # Valintayhteenveto
        self.lbl_summary = QLabel("Valittu: 0 sivua")
        self.lbl_summary.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 12px; padding: 2px;")
        self.lbl_summary.setWordWrap(True)
        sel_layout.addWidget(self.lbl_summary)

        layout.addWidget(sel_group)

        # 2. Toiminnot valituille sivuille
        actions_group = QGroupBox("2. Mitä tehdään valituille sivuille?")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.setSpacing(10)

        # Rivi A: Poisto ja Kierto
        row_a = QHBoxLayout()
        self.btn_delete = QPushButton("🗑️ Poista valitut sivut")
        self.btn_delete.setStyleSheet(
            "background-color: #991b1b; color: #ffffff; font-weight: bold; padding: 8px; border-radius: 4px;"
        )
        self.btn_delete.setToolTip("Poistaa kaikki valitut sivut kerralla dokumentista.")
        self.btn_delete.clicked.connect(self._action_delete_pages)
        row_a.addWidget(self.btn_delete, 2)

        self.btn_rot_cw = QPushButton("🔄 Kierrä +90°")
        self.btn_rot_cw.setStyleSheet("padding: 8px; background-color: #334155; color: white; border-radius: 4px;")
        self.btn_rot_cw.clicked.connect(lambda: self._action_rotate_pages(90))
        row_a.addWidget(self.btn_rot_cw, 1)

        self.btn_rot_ccw = QPushButton("↺ Kierrä -90°")
        self.btn_rot_ccw.setStyleSheet("padding: 8px; background-color: #334155; color: white; border-radius: 4px;")
        self.btn_rot_ccw.clicked.connect(lambda: self._action_rotate_pages(-90))
        row_a.addWidget(self.btn_rot_ccw, 1)

        self.btn_rot_180 = QPushButton("🔃 Kierrä 180°")
        self.btn_rot_180.setStyleSheet("padding: 8px; background-color: #334155; color: white; border-radius: 4px;")
        self.btn_rot_180.clicked.connect(lambda: self._action_rotate_pages(180))
        row_a.addWidget(self.btn_rot_180, 1)
        actions_layout.addLayout(row_a)

        # Rivi B: Pura ja Monista
        row_b = QHBoxLayout()
        self.btn_extract = QPushButton("💾 Pura valitut sivut uuteen PDF-tiedostoon...")
        self.btn_extract.setStyleSheet(
            "background-color: #047857; color: #ffffff; font-weight: bold; padding: 8px; border-radius: 4px;"
        )
        self.btn_extract.setToolTip("Tallentaa valitut sivut uutena erillisenä PDF-tiedostona levylle.")
        self.btn_extract.clicked.connect(self._action_extract_pages)
        row_b.addWidget(self.btn_extract, 2)

        self.btn_duplicate = QPushButton("📋 Monista valitut sivut")
        self.btn_duplicate.setStyleSheet("padding: 8px; background-color: #334155; color: white; border-radius: 4px;")
        self.btn_duplicate.setToolTip("Kahdentaa valitut sivut dokumenttiin kunkin sivun perään.")
        self.btn_duplicate.clicked.connect(self._action_duplicate_pages)
        row_b.addWidget(self.btn_duplicate, 1)
        actions_layout.addLayout(row_b)

        # Rivi C: Sivujen siirto (Move)
        move_box = QGroupBox("Sivujen siirtäminen (Järjestele uudelleen)")
        move_layout = QHBoxLayout(move_box)
        move_layout.setContentsMargins(8, 8, 8, 8)

        self.btn_move_start = QPushButton("⇤ Siirrä alkuun")
        self.btn_move_start.setStyleSheet("padding: 6px; background-color: #1e293b; color: white; border: 1px solid #475569; border-radius: 3px;")
        self.btn_move_start.clicked.connect(lambda: self._action_move_pages("start"))
        move_layout.addWidget(self.btn_move_start)

        self.btn_move_end = QPushButton("⇥ Siirrä loppuun")
        self.btn_move_end.setStyleSheet("padding: 6px; background-color: #1e293b; color: white; border: 1px solid #475569; border-radius: 3px;")
        self.btn_move_end.clicked.connect(lambda: self._action_move_pages("end"))
        move_layout.addWidget(self.btn_move_end)

        move_layout.addSpacing(10)
        move_layout.addWidget(QLabel("tai sivun jälkeen:"))
        self.spin_move_target = QSpinBox()
        self.spin_move_target.setRange(1, max(1, self.max_pages))
        self.spin_move_target.setValue(1)
        self.spin_move_target.setStyleSheet("padding: 4px;")
        move_layout.addWidget(self.spin_move_target)

        self.btn_move_after = QPushButton("→ Siirrä")
        self.btn_move_after.setStyleSheet("padding: 6px 12px; background-color: #0284c7; color: white; border-radius: 3px; font-weight: bold;")
        self.btn_move_after.clicked.connect(lambda: self._action_move_pages("after", self.spin_move_target.value() - 1))
        move_layout.addWidget(self.btn_move_after)

        actions_layout.addWidget(move_box)
        layout.addWidget(actions_group)

        # 3. Alapalkin painikkeet
        bottom_box = QHBoxLayout()
        self.btn_select_in_sidebar = QPushButton("👁️ Korosta valitut sivut sivupalkissa ja sulje")
        self.btn_select_in_sidebar.setStyleSheet("padding: 8px 14px; background-color: #0284c7; color: white; font-weight: bold; border-radius: 4px;")
        self.btn_select_in_sidebar.clicked.connect(self._apply_selection_and_close)
        bottom_box.addWidget(self.btn_select_in_sidebar)

        bottom_box.addStretch()

        self.btn_close = QPushButton("Sulje")
        self.btn_close.setStyleSheet("padding: 8px 16px; background-color: #475569; color: white; border-radius: 4px;")
        self.btn_close.clicked.connect(self.reject)
        bottom_box.addWidget(self.btn_close)

        layout.addLayout(bottom_box)

    def _on_range_text_changed(self, text: str):
        self.selected_indices = parse_page_range_string(text, self.max_pages)
        n = len(self.selected_indices)
        has_sel = n > 0

        self.btn_delete.setEnabled(has_sel)
        self.btn_rot_cw.setEnabled(has_sel)
        self.btn_rot_ccw.setEnabled(has_sel)
        self.btn_rot_180.setEnabled(has_sel)
        self.btn_extract.setEnabled(has_sel)
        self.btn_duplicate.setEnabled(has_sel)
        self.btn_move_start.setEnabled(has_sel)
        self.btn_move_end.setEnabled(has_sel)
        self.btn_move_after.setEnabled(has_sel)
        self.btn_select_in_sidebar.setEnabled(has_sel)

        if not has_sel:
            self.lbl_summary.setText("⚠️ Ei sivuja valittuna.")
            self.lbl_summary.setStyleSheet("color: #f87171; font-size: 12px; padding: 2px;")
            return

        formatted = format_page_range_string(self.selected_indices)
        display_pages = [str(i + 1) for i in self.selected_indices]
        if len(display_pages) <= 15:
            detail_str = ", ".join(display_pages)
        else:
            detail_str = ", ".join(display_pages[:12]) + f" ... (+{len(display_pages)-12} muuta)"

        self.lbl_summary.setText(
            f"✅ Valittu <b>{n} / {self.max_pages}</b> sivua: [{formatted}]<br>"
            f"<span style='font-size: 11px; color: #94a3b8;'>Sivut: {detail_str}</span>"
        )
        self.lbl_summary.setStyleSheet("color: #4ade80; font-size: 12px; padding: 2px;")

    def _select_all(self):
        if self.max_pages > 0:
            self.txt_range.setText(f"1-{self.max_pages}")

    def _select_even(self):
        self.txt_range.setText("even")

    def _select_odd(self):
        self.txt_range.setText("odd")

    def _select_invert(self):
        cur_set = set(self.selected_indices)
        all_indices = set(range(self.max_pages))
        inverted = sorted(all_indices - cur_set)
        self.txt_range.setText(format_page_range_string(inverted))

    def _select_clear(self):
        self.txt_range.setText("")

    def _action_delete_pages(self):
        if not self.selected_indices or not self.doc_model:
            return

        n = len(self.selected_indices)
        if n >= self.max_pages:
            ret = QMessageBox.question(
                self, "Tyhjennä ja luo uusi sivu",
                "PDF-dokumentissa on oltava vähintään yksi sivu.<br><br>"
                "Haluatko tyhjentää dokumentin korvaamalla kaikki sivut uudella puhtaalla sivulla?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if ret == QMessageBox.StandardButton.Yes:
                self.doc_model.insert_blank_page(self.max_pages)
                self.doc_model.delete_pages(list(range(self.max_pages)))
                self.max_pages = self.doc_model.page_count
                self.lbl_total_pages.setText(f"Dokumentissa sivuja: <b>{self.max_pages}</b>")
                self.spin_move_target.setRange(1, max(1, self.max_pages))
                self.pages_modified.emit(0)
                self.txt_range.setText("1")
                self._on_range_text_changed("1")
            return

        formatted = format_page_range_string(self.selected_indices)
        ret = QMessageBox.question(
            self, "Vahvista sivujen poisto",
            f"Haluatko varmasti poistaa <b>{n} valittua sivua</b>?<br><br>"
            f"<b>Poistettavat sivut:</b> {formatted}<br><br>"
            "<i>(Voit peruuttaa poiston painamalla Ctrl + Z.)</i>",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret != QMessageBox.StandardButton.Yes:
            return

        deleted_count = self.doc_model.delete_pages(self.selected_indices)
        if deleted_count > 0:
            self.max_pages = self.doc_model.page_count
            self.lbl_total_pages.setText(f"Dokumentissa sivuja: <b>{self.max_pages}</b>")
            self.spin_move_target.setRange(1, max(1, self.max_pages))
            first_idx = min(self.selected_indices[0], self.max_pages - 1)
            self.pages_modified.emit(first_idx)
            self.txt_range.setText(str(first_idx + 1))
            QMessageBox.information(
                self, "Sivut poistettu",
                f"{deleted_count} sivua poistettiin onnistuneesti."
            )

    def _action_rotate_pages(self, angle: int):
        if not self.selected_indices or not self.doc_model:
            return

        n = self.doc_model.rotate_pages(self.selected_indices, angle)
        if n > 0:
            first_idx = self.selected_indices[0]
            self.pages_modified.emit(first_idx)
            QMessageBox.information(
                self, "Sivut kierretty",
                f"{n} sivua kierrettiin onnistuneesti {angle}°."
            )

    def _action_extract_pages(self):
        if not self.selected_indices or not self.doc_model:
            return

        default_name = f"puretut_sivut_{format_page_range_string(self.selected_indices).replace(' ', '_')}.pdf"
        out_path, _ = QFileDialog.getSaveFileName(
            self, "Tallenna valitut sivut uuteen PDF-tiedostoon",
            default_name, "PDF-tiedostot (*.pdf)"
        )
        if not out_path:
            return

        success = self.doc_model.extract_pages_to_file(self.selected_indices, out_path)
        if success:
            QMessageBox.information(
                self, "Purkaminen valmis",
                f"{len(self.selected_indices)} sivua purettiin ja tallennettiin onnistuneesti tiedostoon:<br>"
                f"<b>{os.path.basename(out_path)}</b>"
            )

    def _action_duplicate_pages(self):
        if not self.selected_indices or not self.doc_model:
            return

        dup_count = self.doc_model.duplicate_pages(self.selected_indices)
        if dup_count > 0:
            self.max_pages = self.doc_model.page_count
            self.lbl_total_pages.setText(f"Dokumentissa sivuja: <b>{self.max_pages}</b>")
            self.spin_move_target.setRange(1, max(1, self.max_pages))
            first_idx = self.selected_indices[0]
            self.pages_modified.emit(first_idx)
            QMessageBox.information(
                self, "Sivut monistettu",
                f"{dup_count} sivua monistettiin onnistuneesti."
            )

    def _action_move_pages(self, target_pos: str, target_idx: Optional[int] = None):
        if not self.selected_indices or not self.doc_model:
            return

        ok = self.doc_model.move_pages(self.selected_indices, target_pos, target_idx)
        if ok:
            first_idx = 0 if target_pos == "start" else (self.max_pages - len(self.selected_indices) if target_pos == "end" else (target_idx or 0))
            self.pages_modified.emit(first_idx)
            self._apply_selection_and_close()

    def _apply_selection_and_close(self):
        if self.selected_indices:
            self.selection_applied.emit(self.selected_indices)
        self.accept()
