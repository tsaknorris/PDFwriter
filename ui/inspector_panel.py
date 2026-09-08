"""
Tarkastelupaneeli (Inspector Panel).
Näyttää valitun elementin fontin sisärakenteen (subset, CMap, lokaali mäppäys),
geometriset metriikat (perusviiva, bbox, väri) sekä PDF-dokumentin metatiedot.
"""

from typing import Optional, Dict, Any
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QGroupBox, QFormLayout,
    QScrollArea, QFrame, QTextEdit
)

from pdf_engine.font_resolver import FontMatchResult
from pdf_engine.pdf_document import PDFDocumentModel


class InspectorPanel(QWidget):
    """Dokumentin ja kirjasimien syvätarkastelupaneeli."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.init_ui()

    def init_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        content_widget = QWidget()
        main_layout = QVBoxLayout(content_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(10)

        def make_row_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 11px;")
            return lbl

        # 1. Kirjasintiedot ja Subset-analyysi
        self.font_group = QGroupBox("Kirjasin && Enkoodaus (Font Inspector)")
        font_layout = QFormLayout(self.font_group)
        font_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lbl_orig_font = QLabel("-")
        self.lbl_orig_font.setStyleSheet("color: #f8fafc; font-weight: bold;")
        self.lbl_orig_font.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_clean_font = QLabel("-")
        self.lbl_clean_font.setStyleSheet("color: #f8fafc;")
        self.lbl_subset = QLabel("-")
        self.lbl_subset.setStyleSheet("color: #f8fafc;")
        self.lbl_embedded_status = QLabel("-")
        self.lbl_embedded_status.setStyleSheet("color: #f8fafc;")
        self.lbl_local_font = QLabel("-")
        self.lbl_local_font.setStyleSheet("color: #f8fafc;")
        self.lbl_local_font.setWordWrap(True)
        self.lbl_cmap_status = QLabel("-")
        self.lbl_cmap_status.setStyleSheet("color: #f8fafc;")

        font_layout.addRow(make_row_label("PDF-fontti:"), self.lbl_orig_font)
        font_layout.addRow(make_row_label("Puhdistettu perhe:"), self.lbl_clean_font)
        font_layout.addRow(make_row_label("Subset-tila:"), self.lbl_subset)
        font_layout.addRow(make_row_label("Upotettu fontti:"), self.lbl_embedded_status)
        font_layout.addRow(make_row_label("Fontconfig-osuma:"), self.lbl_local_font)
        font_layout.addRow(make_row_label("CMap / Glyyfit:"), self.lbl_cmap_status)
        main_layout.addWidget(self.font_group)

        # 2. Geometria & Metriikat
        self.geom_group = QGroupBox("Geometria && Perusviiva (Layout)")
        geom_layout = QFormLayout(self.geom_group)
        geom_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lbl_origin = QLabel("-")
        self.lbl_origin.setStyleSheet("color: #f8fafc; font-family: monospace;")
        self.lbl_bbox = QLabel("-")
        self.lbl_bbox.setStyleSheet("color: #f8fafc; font-family: monospace;")
        self.lbl_size = QLabel("-")
        self.lbl_size.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.lbl_color = QLabel("-")
        self.lbl_color.setStyleSheet("color: #f8fafc;")

        geom_layout.addRow(make_row_label("Perusviiva (Origin):"), self.lbl_origin)
        geom_layout.addRow(make_row_label("Bounding Box:"), self.lbl_bbox)
        geom_layout.addRow(make_row_label("Koko (pt):"), self.lbl_size)
        geom_layout.addRow(make_row_label("Väri (RGB):"), self.lbl_color)
        main_layout.addWidget(self.geom_group)

        # 3. Dokumentin tiedot
        self.doc_group = QGroupBox("PDF-Dokumentti && Eristys")
        doc_layout = QFormLayout(self.doc_group)
        doc_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.lbl_pdf_version = QLabel("-")
        self.lbl_pdf_version.setStyleSheet("color: #f8fafc; font-weight: bold;")
        self.lbl_page_count = QLabel("-")
        self.lbl_page_count.setStyleSheet("color: #f8fafc; font-weight: bold;")
        self.lbl_offline_status = QLabel("100 % Paikallinen (QT_NO_NETWORK=1)")
        self.lbl_offline_status.setStyleSheet("color: #4ade80; font-weight: bold;")

        doc_layout.addRow(make_row_label("PDF-versio:"), self.lbl_pdf_version)
        doc_layout.addRow(make_row_label("Sivuja:"), self.lbl_page_count)
        doc_layout.addRow(make_row_label("Eristystila:"), self.lbl_offline_status)
        main_layout.addWidget(self.doc_group)

        main_layout.addStretch()

        self.scroll_area.setWidget(content_widget)
        root_layout.addWidget(self.scroll_area)

    def update_span_details(self, span: Dict[str, Any], font_match: Optional[FontMatchResult] = None):
        """Päivittää valitun tekstialkion tiedot."""
        raw_font = span.get("font", "-")
        size = span.get("size", 0.0)
        origin = span.get("origin", (0, 0))
        bbox = span.get("bbox", (0, 0, 0, 0))
        color_int = span.get("color", 0)

        # Väri
        r = (color_int >> 16) & 255
        g = (color_int >> 8) & 255
        b = color_int & 255
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.lbl_color.setText(f"{hex_color} ({r}, {g}, {b})")
        self.lbl_color.setStyleSheet(f"background-color: {hex_color}; color: {'#fff' if (r+g+b)<380 else '#000'}; padding: 2px 6px; border-radius: 3px;")

        self.lbl_orig_font.setText(raw_font)
        self.lbl_size.setText(f"{size:.2f} pt")
        self.lbl_origin.setText(f"X: {origin[0]:.2f} pt, Y: {origin[1]:.2f} pt (Baseline)")
        self.lbl_bbox.setText(f"[{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}] pt")

        if font_match:
            self.lbl_clean_font.setText(f"{font_match.clean_family} {'(Bold)' if font_match.is_bold else ''} {'(Italic)' if font_match.is_italic else ''}".strip())
            if font_match.is_subset:
                self.lbl_subset.setText("Upotettu osajoukko (Subset)")
                self.lbl_subset.setStyleSheet("color: #fbbf24; font-weight: bold;")
            else:
                self.lbl_subset.setText("Täysi tai vakiofontti")
                self.lbl_subset.setStyleSheet("color: #38bdf8; font-weight: bold;")

            if font_match.embedded_extracted:
                self.lbl_embedded_status.setText(f"Purettu ({font_match.embedded_ext})")
            else:
                self.lbl_embedded_status.setText("Ei purettavissa")

            if font_match.local_font_path:
                style_tag = ""
                if font_match.effective_is_bold and font_match.effective_is_italic:
                    style_tag = " (Lihavoitu & Kursiivi)"
                elif font_match.effective_is_bold:
                    style_tag = " (Lihavoitu / Bold)"
                elif font_match.effective_is_italic:
                    style_tag = " (Kursivoitu / Italic)"
                elif font_match.needs_faux_bold:
                    style_tag = " (Keinotekoinen lihavointi)"
                self.lbl_local_font.setText(f"{font_match.local_font_family}{style_tag}\n({font_match.local_font_path})")
                self.lbl_local_font.setStyleSheet("color: #4ade80; font-size: 11px; font-weight: bold;")
            else:
                self.lbl_local_font.setText("Ei suoraa osumaa (käytetään vakiota)")
                self.lbl_local_font.setStyleSheet("color: #f87171; font-weight: bold;")

            if font_match.can_use_embedded:
                self.lbl_cmap_status.setText("Täydellinen (kaikki merkit upotetussa)")
                self.lbl_cmap_status.setStyleSheet("color: #4ade80; font-weight: bold;")
            elif font_match.can_use_local:
                self.lbl_cmap_status.setText("Korvattu täydellä lokaalilla fontilla")
                self.lbl_cmap_status.setStyleSheet("color: #4ade80;")
            else:
                self.lbl_cmap_status.setText(f"Puuttuvia: {font_match.local_missing_glyphs}")
                self.lbl_cmap_status.setStyleSheet("color: #f87171; font-weight: bold;")

    def update_block_details(self, block: Dict[str, Any], font_match: Optional[FontMatchResult] = None):
        """Päivittää valitun tekstikappaleen tiedot."""
        raw_font = block.get("font", "-")
        size = block.get("size", 0.0)
        bbox = block.get("bbox", (0, 0, 0, 0))
        color_int = block.get("color", 0)
        line_count = block.get("line_count", 1)

        r = (color_int >> 16) & 255
        g = (color_int >> 8) & 255
        b = color_int & 255
        hex_color = f"#{r:02x}{g:02x}{b:02x}"
        self.lbl_color.setText(f"{hex_color} ({r}, {g}, {b})")
        self.lbl_color.setStyleSheet(f"background-color: {hex_color}; color: {'#fff' if (r+g+b)<380 else '#000'}; padding: 2px 6px; border-radius: 3px;")

        self.lbl_orig_font.setText(raw_font)
        self.lbl_size.setText(f"{size:.2f} pt")
        first_orig = block.get("first_origin", (0, 0))
        leading = block.get("leading", 0.0)
        self.lbl_origin.setText(f"Perusviiva: Y={first_orig[1]:.1f} pt | Riviväli: {leading:.1f} pt ({line_count} riviä)")
        self.lbl_bbox.setText(f"[{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}] pt")

        if font_match:
            self.lbl_clean_font.setText(f"{font_match.clean_family} {'(Bold)' if font_match.is_bold else ''} {'(Italic)' if font_match.is_italic else ''}".strip())
            if font_match.is_subset:
                self.lbl_subset.setText("Upotettu osajoukko (Subset)")
                self.lbl_subset.setStyleSheet("color: #fbbf24; font-weight: bold;")
            else:
                self.lbl_subset.setText("Täysi tai vakiofontti")
                self.lbl_subset.setStyleSheet("color: #38bdf8; font-weight: bold;")

            if font_match.embedded_extracted:
                self.lbl_embedded_status.setText(f"Purettu ({font_match.embedded_ext})")
            else:
                self.lbl_embedded_status.setText("Ei purettavissa")

            if font_match.local_font_path:
                style_tag = ""
                if font_match.effective_is_bold and font_match.effective_is_italic:
                    style_tag = " (Lihavoitu & Kursiivi)"
                elif font_match.effective_is_bold:
                    style_tag = " (Lihavoitu / Bold)"
                elif font_match.effective_is_italic:
                    style_tag = " (Kursivoitu / Italic)"
                elif font_match.needs_faux_bold:
                    style_tag = " (Keinotekoinen lihavointi)"
                self.lbl_local_font.setText(f"{font_match.local_font_family}{style_tag}\n({font_match.local_font_path})")
                self.lbl_local_font.setStyleSheet("color: #4ade80; font-size: 11px; font-weight: bold;")
            else:
                self.lbl_local_font.setText("Ei suoraa osumaa (käytetään vakiota)")
                self.lbl_local_font.setStyleSheet("color: #f87171; font-weight: bold;")

            if font_match.can_use_embedded:
                self.lbl_cmap_status.setText("Täydellinen (kaikki merkit upotetussa)")
                self.lbl_cmap_status.setStyleSheet("color: #4ade80; font-weight: bold;")
            elif font_match.can_use_local:
                self.lbl_cmap_status.setText("Korvattu täydellä lokaalilla fontilla")
                self.lbl_cmap_status.setStyleSheet("color: #4ade80;")
            else:
                self.lbl_cmap_status.setText(f"Puuttuvia: {font_match.local_missing_glyphs}")
                self.lbl_cmap_status.setStyleSheet("color: #f87171; font-weight: bold;")

    def update_document_details(self, doc_model: PDFDocumentModel):
        """Päivittää dokumenttitason tiedot."""
        if not doc_model or not doc_model.is_open:
            self.lbl_pdf_version.setText("-")
            self.lbl_page_count.setText("-")
            return

        doc = doc_model.doc
        meta = doc.metadata or {}
        pdf_ver = f"PDF {doc.metadata.get('format', '1.7')}" if meta else "PDF 1.7"
        self.lbl_pdf_version.setText(pdf_ver)
        self.lbl_page_count.setText(f"{doc_model.page_count} sivua")
