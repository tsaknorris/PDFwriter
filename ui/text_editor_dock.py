"""
In-Place Tekstieditori ja Sovitusohjain (Text Editor Dock).
Mahdollistaa tekstin muokkaamisen monirivisessä kappaletilassa tai tarkassa rivitilassa.
Tukee automaattista sanarivitystä (word-wrap), reaaliaikaista metriikkaa,
fonttikoon säätöä (0.1 pt), värivalintaa ja sovitusstrategioita.
"""

from typing import Optional, Dict, Any, Tuple
import re
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QTextOption
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QComboBox, QDoubleSpinBox, QColorDialog,
    QGroupBox, QFrame, QSizePolicy, QScrollArea
)

from pdf_engine.font_resolver import FontMatchResult, FontconfigResolver
from pdf_engine.layout_engine import LayoutEngine, FitStrategy, OverflowReport
from pdf_engine.pdf_document import PDFDocumentModel


class MultilineTextEdit(QPlainTextEdit):
    """Monirivinen tekstikenttä, joka tukee Ctrl+Enter -pikanäppäintä tallennukseen ja kumoamisen delegointia."""
    commit_requested = pyqtSignal()
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit_requested.emit()
            event.accept()
            return
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_Z and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                if not self.document().isUndoAvailable():
                    self.undo_requested.emit()
                    event.accept()
                    return
            elif event.key() == Qt.Key.Key_Y or (event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                if not self.document().isRedoAvailable():
                    self.redo_requested.emit()
                    event.accept()
                    return
        super().keyPressEvent(event)


class TextEditorDock(QWidget):
    """Interaktiivinen tekstinmuokkauspaneeli (kappaleet ja rivit)."""

    edit_committed = pyqtSignal(dict, str, object, object, object, object)  # (span, text, font_match, strategy, size, color)
    block_edit_committed = pyqtSignal(dict, str, object, object, object, object)  # (block, text, font_match, strategy, size, color)
    mode_switch_requested = pyqtSignal(str)  # "paragraph" tai "span"
    font_manager_requested = pyqtSignal()  # Pyyntö avata Font Manager -ikkuna
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.active_mode: str = "paragraph"  # "paragraph" tai "span"
        self.active_span: Optional[Dict[str, Any]] = None
        self.active_block: Optional[Dict[str, Any]] = None
        self.active_font_match: Optional[FontMatchResult] = None
        self.doc_model: Optional[PDFDocumentModel] = None
        self.selected_color_rgb: Optional[Tuple[float, float, float]] = None
        self.orig_size: float = 12.0
        self.orig_color_rgb: Optional[Tuple[float, float, float]] = None

        self.init_ui()

    def init_ui(self):
        # Root-tason asettelu ja vieritysalue (QScrollArea), jotta kaikki asetukset näkyvät ilman telakan irrottamista
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 0. Muokkaustilan valitsin
        mode_box = QHBoxLayout()
        mode_box.addWidget(QLabel("Valintatila:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("📄 Kappaletila (Koko lohko - Oletus)", "paragraph")
        self.mode_combo.addItem("📏 Rivitila (Yksittäinen rivi / jakso)", "span")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_combo_changed)
        mode_box.addWidget(self.mode_combo)
        layout.addLayout(mode_box)

        # 1. Tekstin syöttö ja kirjasimen tunnistus
        input_group = QGroupBox("Tekstin In-Place -muokkaus")
        input_layout = QVBoxLayout(input_group)

        font_header = QHBoxLayout()
        self.font_info_label = QLabel("Kirjasin: Ei valintaa")
        self.font_info_label.setStyleSheet("font-weight: bold; color: #38bdf8; padding: 2px 0;")
        self.font_info_label.setWordWrap(True)
        font_header.addWidget(self.font_info_label, 1)

        self.btn_manage_fonts = QPushButton("🔤 Fontit...")
        self.btn_manage_fonts.setStyleSheet(
            "background-color: #363642; color: #f8fafc; border: 1px solid #4f4f60; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
        )
        self.btn_manage_fonts.setToolTip("Avaa dokumentin kirjasinten hallinta")
        self.btn_manage_fonts.clicked.connect(self.font_manager_requested.emit)
        font_header.addWidget(self.btn_manage_fonts)
        input_layout.addLayout(font_header)

        self.input_edit = MultilineTextEdit()
        self.input_edit.setPlaceholderText("Valitse teksti sivulta hiirellä muokataksesi sitä...")
        self.input_edit.setMinimumHeight(120)
        self.input_edit.textChanged.connect(self._on_text_changed)
        self.input_edit.commit_requested.connect(self._on_commit)
        self.input_edit.undo_requested.connect(self.undo_requested.emit)
        self.input_edit.redo_requested.connect(self.redo_requested.emit)
        input_layout.addWidget(self.input_edit)

        self.hint_label = QLabel("Vinkki: Ctrl + Enter hyväksyy muutoksen välittömästi.")
        self.hint_label.setStyleSheet("font-size: 11px; color: #cbd5e1; font-style: italic;")
        input_layout.addWidget(self.hint_label)

        # 2. Metriikat & Asettelun tila
        self.status_badge = QLabel("Ei valittua elementtiä")
        self.status_badge.setStyleSheet(
            "padding: 6px; border-radius: 4px; background-color: #282834; color: #cbd5e1; font-weight: bold;"
        )
        self.status_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        input_layout.addWidget(self.status_badge)

        self.metrics_label = QLabel("Rivejä: -  |  Pituus: -")
        self.metrics_label.setStyleSheet("font-size: 11px; color: #e2e8f0; font-weight: bold;")
        input_layout.addWidget(self.metrics_label)

        layout.addWidget(input_group)

        # 3. Typografia & Sovitusstrategia
        typo_group = QGroupBox("Typografia && Sovitus")
        typo_layout = QVBoxLayout(typo_group)

        # Sovitustapa
        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel("Sovitustapa:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItem("Luonnollinen (Natural / Sanarivitys)", FitStrategy.NATURAL)
        self.strategy_combo.addItem("Automaattinen sovitus (Auto-Fit)", FitStrategy.AUTO_FIT)
        self.strategy_combo.addItem("Rivin juoksutus (Reflow)", FitStrategy.REFLOW)
        self.strategy_combo.currentIndexChanged.connect(self._on_text_changed)
        strategy_row.addWidget(self.strategy_combo)
        typo_layout.addLayout(strategy_row)

        # Fonttikoko & Väri
        # Fonttikoko, Lihavointi/Kursivointi & Väri
        tools_row = QHBoxLayout()
        tools_row.addWidget(QLabel("Koko (pt):"))
        self.size_spin = QDoubleSpinBox()
        self.size_spin.setRange(2.0, 200.0)
        self.size_spin.setSingleStep(0.5)
        self.size_spin.setDecimals(1)
        self.size_spin.valueChanged.connect(self._on_text_changed)
        tools_row.addWidget(self.size_spin)

        self.btn_bold = QPushButton("𝐁")
        self.btn_bold.setCheckable(True)
        self.btn_bold.setFixedWidth(30)
        self.btn_bold.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.btn_bold.setToolTip("Lihavointi (Bold / Ctrl+B)")
        self.btn_bold.toggled.connect(self._on_style_toggled)
        tools_row.addWidget(self.btn_bold)

        self.btn_italic = QPushButton("𝐼")
        self.btn_italic.setCheckable(True)
        self.btn_italic.setFixedWidth(30)
        self.btn_italic.setStyleSheet("font-style: italic; font-size: 13px;")
        self.btn_italic.setToolTip("Kursivointi (Italic / Ctrl+I)")
        self.btn_italic.toggled.connect(self._on_style_toggled)
        tools_row.addWidget(self.btn_italic)

        self.color_btn = QPushButton("Väri...")
        self.color_btn.clicked.connect(self._pick_color)
        tools_row.addWidget(self.color_btn)
        typo_layout.addLayout(tools_row)

        # Lohkon leveys & Palstaan sovitus
        width_row = QHBoxLayout()
        width_row.addWidget(QLabel("Leveys (pt):"))
        self.width_spin = QDoubleSpinBox()
        self.width_spin.setRange(20.0, 2000.0)
        self.width_spin.setSingleStep(5.0)
        self.width_spin.setDecimals(1)
        self.width_spin.setEnabled(False)
        self.width_spin.valueChanged.connect(self._on_width_spin_changed)
        width_row.addWidget(self.width_spin)

        self.btn_fit_column = QPushButton("↔ Sovita palstaan")
        self.btn_fit_column.setStyleSheet(
            "background-color: #363642; color: #f8fafc; border: 1px solid #4f4f60; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
        )
        self.btn_fit_column.setToolTip("Laajenna lohkon leveys koko palstan tai sivun vapaaseen tilaan")
        self.btn_fit_column.setEnabled(False)
        self.btn_fit_column.clicked.connect(self._on_fit_column_clicked)
        width_row.addWidget(self.btn_fit_column)
        typo_layout.addLayout(width_row)

        layout.addWidget(typo_group)

        # 4. Toimintopainike
        self.commit_btn = QPushButton("Korvaa kappale (In-Place)")
        self.commit_btn.setStyleSheet("background-color: #0284c7; color: #ffffff; font-weight: bold; padding: 9px; font-size: 13px; border-radius: 4px;")
        self.commit_btn.setEnabled(False)
        self.commit_btn.clicked.connect(self._on_commit)
        layout.addWidget(self.commit_btn)

        layout.addStretch()

        self.scroll_area.setWidget(content_widget)
        root_layout.addWidget(self.scroll_area)

    def set_active_mode(self, mode: str):
        """Synkronoi tila ulkopuolelta (esim. kankaan tilamuutoksesta)."""
        self.active_mode = mode
        idx = self.mode_combo.findData(mode)
        if idx >= 0 and self.mode_combo.currentIndex() != idx:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
        
        if mode == "paragraph":
            self.commit_btn.setText("Korvaa kappale (In-Place)")
        else:
            self.commit_btn.setText("Korvaa teksti (In-Place)")

    def _on_mode_combo_changed(self):
        new_mode = self.mode_combo.currentData()
        self.active_mode = new_mode
        if new_mode == "paragraph":
            self.commit_btn.setText("Korvaa kappale (In-Place)")
        else:
            self.commit_btn.setText("Korvaa teksti (In-Place)")
        self.mode_switch_requested.emit(new_mode)

    def set_target_block(self, block: Dict[str, Any], doc_model: PDFDocumentModel):
        """Asettaa valitun tekstikappaleen muokattavaksi."""
        self.active_block = block
        self.active_span = None
        self.set_active_mode("paragraph")
        self.doc_model = doc_model

        orig_text = block.get("text", "")
        orig_lines = block.get("original_lines", [])
        if len(orig_lines) > 1 and "\n" not in orig_text:
            orig_text = "\n".join(orig_lines)
        self.orig_size = float(block.get("size", 12.0))
        self.input_edit.setPlainText(orig_text)
        self.size_spin.setValue(self.orig_size)

        # Lohkon leveys
        cur_w = float(block.get("max_width", 0.0))
        if cur_w <= 0:
            bbox = block.get("bbox", [0, 0, 100, 50])
            cur_w = bbox[2] - bbox[0]
        self.width_spin.blockSignals(True)
        self.width_spin.setValue(cur_w)
        self.width_spin.blockSignals(False)
        self.width_spin.setEnabled(True)
        self.btn_fit_column.setEnabled(True)

        # Väri
        color_int = block.get("color", 0)
        r = ((color_int >> 16) & 255) / 255.0
        g = ((color_int >> 8) & 255) / 255.0
        b = (color_int & 255) / 255.0
        self.selected_color_rgb = (r, g, b)
        self.orig_color_rgb = (r, g, b)
        self._update_color_button_preview()

        # Kirjasimen tarkka tunnistus
        flags = block.get("flags", 0)
        is_b = bool(flags & 16) or "bold" in block.get("font", "").lower()
        is_it = bool(flags & 2) or ("italic" in block.get("font", "").lower() or "oblique" in block.get("font", "").lower())
        self.btn_bold.blockSignals(True)
        self.btn_bold.setChecked(is_b)
        self.btn_bold.blockSignals(False)
        self.btn_italic.blockSignals(True)
        self.btn_italic.setChecked(is_it)
        self.btn_italic.blockSignals(False)

        if doc_model and doc_model.doc:
            self.active_font_match = FontconfigResolver.inspect_and_resolve(
                doc_model.doc,
                block,
                orig_text,
                override_bold=is_b,
                override_italic=is_it
            )
            font_display = f"Kirjasin: {block.get('font', '')} ({block.get('size', 0):.1f} pt) — {self.active_font_match.status_summary}"
            self.font_info_label.setText(font_display)
            self._update_font_badge()
            print(f"[DEBUG-INSPECT] Valittu kappale: {len(orig_text)} merkkiä, {block.get('line_count')} riviä | Kirjasin: {block.get('font')} | Koko: {block.get('size')} pt")

        self.commit_btn.setEnabled(True)
        self.input_edit.setFocus()
        self._update_metrics_and_warnings()

    def set_target_span(self, span: Dict[str, Any], doc_model: PDFDocumentModel):
        """Asettaa valitun yksittäisen tekstijakson muokattavaksi."""
        self.active_span = span
        self.active_block = None
        self.set_active_mode("span")
        self.doc_model = doc_model

        self.width_spin.setEnabled(False)
        self.btn_fit_column.setEnabled(False)

        orig_text = span.get("text", "")
        self.orig_size = float(span.get("size", 10.0))
        self.input_edit.setPlainText(orig_text)
        self.size_spin.setValue(self.orig_size)

        # Väri
        color_int = span.get("color", 0)
        r = ((color_int >> 16) & 255) / 255.0
        g = ((color_int >> 8) & 255) / 255.0
        b = (color_int & 255) / 255.0
        self.selected_color_rgb = (r, g, b)
        self.orig_color_rgb = (r, g, b)
        self._update_color_button_preview()

        # Tyylin tunnistus
        flags = span.get("flags", 0)
        is_b = bool(flags & 16) or "bold" in span.get("font", "").lower()
        is_it = bool(flags & 2) or ("italic" in span.get("font", "").lower() or "oblique" in span.get("font", "").lower())
        self.btn_bold.blockSignals(True)
        self.btn_bold.setChecked(is_b)
        self.btn_bold.blockSignals(False)
        self.btn_italic.blockSignals(True)
        self.btn_italic.setChecked(is_it)
        self.btn_italic.blockSignals(False)

        # Resoluutio
        if doc_model and doc_model.doc:
            self.active_font_match = FontconfigResolver.inspect_and_resolve(
                doc_model.doc,
                span,
                orig_text,
                override_bold=is_b,
                override_italic=is_it
            )
            font_display = f"Kirjasin: {span.get('font', '')} ({span.get('size', 0):.1f} pt) — {self.active_font_match.status_summary}"
            self.font_info_label.setText(font_display)
            self._update_font_badge()
            print(f"[DEBUG-INSPECT] Valittu rivi/jakso: '{orig_text}' | Kirjasin: {span.get('font')} | Koko: {span.get('size')} pt")

        self.commit_btn.setEnabled(True)
        self.input_edit.setFocus()
        self._update_metrics_and_warnings()

    def toggle_bold(self):
        """Kääntää lihavointitilan (Bold)."""
        self.btn_bold.toggle()

    def toggle_italic(self):
        """Kääntää kursivointitilan (Italic)."""
        self.btn_italic.toggle()

    def set_fontsize(self, size: float):
        """Asettaa valitun fonttikoon."""
        self.size_spin.setValue(size)

    def _on_style_toggled(self):
        """Kutsutaan kun lihavointi- tai kursivointipainiketta painetaan."""
        self._on_text_changed()

    def _on_text_changed(self):
        new_text = self.input_edit.toPlainText()
        b_val = self.btn_bold.isChecked()
        it_val = self.btn_italic.isChecked()

        if self.active_mode == "paragraph" and self.active_block and self.doc_model:
            self.active_font_match = FontconfigResolver.inspect_and_resolve(
                self.doc_model.doc,
                self.active_block,
                new_text,
                override_bold=b_val,
                override_italic=it_val
            )
            if self.active_font_match:
                font_display = f"Kirjasin: {self.active_block.get('font', '')} ({self.size_spin.value():.1f} pt) — {self.active_font_match.status_summary}"
                self.font_info_label.setText(font_display)
                self._update_font_badge()
        elif self.active_mode == "span" and self.active_span and self.doc_model:
            self.active_font_match = FontconfigResolver.inspect_and_resolve(
                self.doc_model.doc,
                self.active_span,
                new_text,
                override_bold=b_val,
                override_italic=it_val
            )
            if self.active_font_match:
                font_display = f"Kirjasin: {self.active_span.get('font', '')} ({self.size_spin.value():.1f} pt) — {self.active_font_match.status_summary}"
                self.font_info_label.setText(font_display)
                self._update_font_badge()

    def _update_font_badge(self):
        if not self.active_font_match:
            self.btn_manage_fonts.setStyleSheet(
                "background-color: #363642; color: #f8fafc; border: 1px solid #4f4f60; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
            )
            self.btn_manage_fonts.setText("🔤 Fontit...")
            return

        if not self.active_font_match.can_use_local and not self.active_font_match.can_use_embedded:
            self.btn_manage_fonts.setStyleSheet(
                "background-color: #78350f; color: #fde047; font-weight: bold; border: 1px solid #d97706; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
            )
            self.btn_manage_fonts.setText("⚠️ Asenna fontti...")
            self.btn_manage_fonts.setToolTip("Tämän tekstin kirjasin puuttuu koneelta. Klikkaa tästä asentaaksesi tai ladataksesi sen.")
        elif self.active_font_match.is_subset and not self.active_font_match.can_use_local:
            self.btn_manage_fonts.setStyleSheet(
                "background-color: #713f12; color: #fef08a; font-weight: bold; border: 1px solid #ca8a04; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
            )
            self.btn_manage_fonts.setText("⚠️ Subset-kirjasin...")
            self.btn_manage_fonts.setToolTip("Dokumentin fontti on osajoukko. Täyden fontin asentaminen takaa kaikkien uusien merkkien toimivuuden.")
        else:
            self.btn_manage_fonts.setStyleSheet(
                "background-color: #14532d; color: #86efac; font-weight: bold; border: 1px solid #16a34a; border-radius: 3px; padding: 2px 6px; font-size: 11px;"
            )
            self.btn_manage_fonts.setText("✅ Fontti asennettu (valmis)")
            self.btn_manage_fonts.setToolTip("Kirjasin on asennettu ja 100 % käyttövalmis! Mitään ei tarvitse enää ladata. Voit muokata tekstiä vapaasti.")

        self._update_metrics_and_warnings()

    def _update_metrics_and_warnings(self):
        new_text = self.input_edit.toPlainText()

        if self.active_mode == "paragraph" and self.active_block:
            bbox = self.active_block.get("bbox", [0, 0, 0, 0])
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            leading = self.active_block.get("leading", 0.0)
            line_count = len([l for l in new_text.split("\n") if l.strip()]) or 1
            char_count = len(new_text)

            self.metrics_label.setText(
                f"Kappale: {w:.1f} × {h:.1f} pt  |  Riviväli: {leading:.1f} pt  |  {char_count} merkkiä  |  {line_count} riviä"
            )
            self.status_badge.setText("✅ Asettelu lukittu — Riviväli ja perusviivat säilytetään identtisinä")
            self.status_badge.setStyleSheet(
                "padding: 6px; border-radius: 4px; background-color: #14532d; color: #86efac; font-weight: bold;"
            )

        elif self.active_mode == "span" and self.active_span and self.doc_model:
            p_idx = self.active_span.get("page_idx", 0)
            page = self.doc_model.doc[p_idx] if (self.doc_model.is_open and 0 <= p_idx < len(self.doc_model.doc)) else None
            fontfile = self.active_font_match.effective_font_path if self.active_font_match else None
            fontname = (self.active_font_match.effective_font_name if self.active_font_match else "helv") or "helv"

            report: OverflowReport = LayoutEngine.analyze_overflow(
                self.active_span,
                new_text,
                page=page,
                fontfile=fontfile,
                fontname=fontname
            )

            orig_w = report.original_width
            new_w = report.new_width
            delta = report.delta_width

            self.metrics_label.setText(
                f"Alkuperäinen pituus: {orig_w:.1f} pt  |  Uusi: {new_w:.1f} pt  ({'+' if delta >= 0 else ''}{delta:.1f} pt)"
            )

            if not report.is_overflow:
                self.status_badge.setText("✅ Alkuperäinen asettelu säilyy")
                self.status_badge.setStyleSheet(
                    "padding: 6px; border-radius: 4px; background-color: #14532d; color: #86efac; font-weight: bold;"
                )
            elif report.overflow_severity == "minor":
                self.status_badge.setText(f"ℹ️ Teksti hieman pidempi (+{delta:.1f} pt)")
                self.status_badge.setStyleSheet(
                    "padding: 6px; border-radius: 4px; background-color: #1e3a8a; color: #93c5fd; font-weight: bold;"
                )
            else:
                self.status_badge.setText(f"ℹ️ Pidempi teksti (+{delta:.1f} pt). Käytä halutessasi Auto-Fit -sovitusta.")
                self.status_badge.setStyleSheet(
                    "padding: 6px; border-radius: 4px; background-color: #713f12; color: #fef08a; font-weight: bold;"
                )

    def _pick_color(self):
        init_color = QColor(0, 0, 0)
        if self.selected_color_rgb:
            r, g, b = self.selected_color_rgb
            init_color = QColor(int(r * 255), int(g * 255), int(b * 255))
        
        color = QColorDialog.getColor(init_color, self, "Valitse tekstin väri")
        if color.isValid():
            self.selected_color_rgb = (color.redF(), color.greenF(), color.blueF())
            self._update_color_button_preview()
            self.commit_btn.setEnabled(True)
            if self.active_font_match:
                self._on_commit()

    def _update_color_button_preview(self):
        if self.selected_color_rgb:
            r, g, b = self.selected_color_rgb
            hex_c = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            text_c = "#fff" if (r+g+b) < 1.5 else "#000"
            self.color_btn.setStyleSheet(f"background-color: {hex_c}; color: {text_c}; font-weight: bold;")

    def _on_width_spin_changed(self, val: float):
        if self.active_mode == "paragraph" and self.active_block:
            self.active_block["max_width"] = val
            bbox = list(self.active_block.get("bbox", [0, 0, 0, 0]))
            bbox[2] = bbox[0] + val
            self.active_block["bbox"] = bbox
            self._update_metrics_and_warnings()

    def _on_fit_column_clicked(self):
        if self.active_mode == "paragraph" and self.active_block:
            avail = self.active_block.get("available_width")
            if not avail or avail <= 0:
                avail = self.active_block.get("max_width", 300.0)
            self.width_spin.setValue(avail)

    def on_block_geometry_changed(self, block: Dict[str, Any]):
        """Kutsutaan kun kankaan tekstilaatikon kahvoja raahataan hiirellä."""
        if self.active_mode == "paragraph" and self.active_block:
            new_w = block.get("max_width", 0.0)
            if new_w <= 0:
                bbox = block.get("bbox", [0, 0, 100, 50])
                new_w = bbox[2] - bbox[0]
            self.active_block["max_width"] = new_w
            self.active_block["bbox"] = block.get("bbox", self.active_block.get("bbox"))
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(new_w)
            self.width_spin.blockSignals(False)
            self._update_metrics_and_warnings()

    def _on_reset(self):
        if self.active_mode == "paragraph" and self.active_block:
            orig_lines = self.active_block.get("original_lines", [])
            reset_text = self.active_block.get("text", "")
            if len(orig_lines) > 1 and "\n" not in reset_text:
                reset_text = "\n".join(orig_lines)
            self.input_edit.setPlainText(reset_text)
            self.size_spin.setValue(self.orig_size)
            self.selected_color_rgb = self.orig_color_rgb
            self._update_color_button_preview()
            orig_bbox = self.active_block.get("original_bbox", self.active_block.get("bbox"))
            orig_w = orig_bbox[2] - orig_bbox[0]
            self.active_block["bbox"] = list(orig_bbox)
            self.active_block["max_width"] = orig_w
            self.width_spin.blockSignals(True)
            self.width_spin.setValue(orig_w)
            self.width_spin.blockSignals(False)
            self._update_metrics_and_warnings()
        elif self.active_mode == "span" and self.active_span:
            self.input_edit.setPlainText(self.active_span.get("text", ""))
            self.size_spin.setValue(self.orig_size)
            self.selected_color_rgb = self.orig_color_rgb
            self._update_color_button_preview()

    def _on_commit(self):
        new_text = self.input_edit.toPlainText()
        strategy = self.strategy_combo.currentData()
        
        spin_val = self.size_spin.value()
        custom_size = spin_val if abs(spin_val - self.orig_size) > 0.05 else None
        custom_color = self.selected_color_rgb if self.selected_color_rgb != self.orig_color_rgb else None

        if self.active_mode == "paragraph" and self.active_block and self.active_font_match:
            self.block_edit_committed.emit(
                self.active_block,
                new_text,
                self.active_font_match,
                strategy,
                custom_size,
                custom_color
            )
        elif self.active_mode == "span" and self.active_span and self.active_font_match:
            self.edit_committed.emit(
                self.active_span,
                new_text,
                self.active_font_match,
                strategy,
                custom_size,
                custom_color
            )

    def clear_target(self):
        """Tyhjentää aktiivisen valinnan ja palauttaa editorin neutraaliin tilaan."""
        self.active_block = None
        self.active_span = None
        self.active_font_match = None
        self.input_edit.blockSignals(True)
        self.input_edit.clear()
        self.input_edit.blockSignals(False)
        self.font_info_label.setText("Kirjasin: Ei valintaa")
        self.status_badge.setText("Ei valittua elementtiä")
        self.status_badge.setStyleSheet(
            "padding: 6px; border-radius: 4px; background-color: #ecf0f1; color: #7f8c8d; font-weight: bold;"
        )
        self.metrics_label.setText("Rivejä: -  |  Pituus: -")
        self.commit_btn.setEnabled(False)
        self.width_spin.setEnabled(False)
        self.btn_fit_column.setEnabled(False)

