"""
Dokumentin kirjasinten hallinta ja asennus (Font Manager Dialog).
Tunnistaa dokumentin kirjasimet, ilmoittaa puuttuvista ja osajoukoista (subset),
ja mahdollistaa avointen vastineiden lataamisen käyttäjän luvalla tai omien fonttien tuonnin.
"""

import os
from typing import Optional, List, Dict, Any

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QPushButton, QHeaderView, QMessageBox,
    QFileDialog, QFrame, QAbstractItemView
)

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver, FontDownloader, LOCAL_FONTS_DIR


def format_page_ranges(pages: List[int], total_pages: int = 0) -> str:
    """Muuntaa sivunumerolistan tiiviiksi välimuotoiluksi (esim. '1–5, 10, 12–14')."""
    if not pages:
        return "—"
    if total_pages > 15 and len(pages) >= total_pages * 0.8:
        return f"Koko kirja ({len(pages)} s.)"

    ranges = []
    start = pages[0]
    prev = pages[0]
    for p in pages[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(str(start) if start == prev else f"{start}–{prev}")
            start = p
            prev = p
    ranges.append(str(start) if start == prev else f"{start}–{prev}")

    text = ", ".join(ranges)
    if len(text) > 30:
        return f"{ranges[0]}, {ranges[1]} ... ({len(pages)} s.)"
    return text


class FontManagerDialog(QDialog):
    """
    Dokumentin kirjasintenhallintaikkuna.
    Näyttää kaikki dokumentin käyttämät fontit, niiden tilan ja tarjoaa
    toiminnot puuttuvien kirjasinten ratkaisemiseen.
    """

    fonts_updated = pyqtSignal()

    def __init__(self, doc_model: PDFDocumentModel, parent=None):
        super().__init__(parent)
        self.doc_model = doc_model
        self.fonts_summary: List[Dict[str, Any]] = []

        self.setWindowTitle("Dokumentin kirjasimet ja typografia (Font Manager)")
        self.resize(1100, 620)
        self.setMinimumSize(960, 520)
        self.init_ui()
        self.refresh_fonts()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)

        # 1. Otsikko ja infoalue
        self.header_frame = QFrame()
        self.header_frame.setStyleSheet(
            "background-color: #242b35; border: 1px solid #3d4a5d; border-radius: 8px; padding: 12px;"
        )
        header_layout = QVBoxLayout(self.header_frame)
        header_layout.setSpacing(4)
        header_layout.setContentsMargins(10, 10, 10, 10)

        self.title_label = QLabel("<b>Dokumentin kirjasimet ja saatavuus</b>")
        self.title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #ecf0f1;")
        header_layout.addWidget(self.title_label)

        self.desc_label = QLabel(
            "PDF-dokumenteissa ammattimaiset kirjasimet on usein upotettu vain osittaisina osajoukkoina (subset). "
            "Uusien merkkien lisäämiseksi ja ulkoasun säilyttämiseksi suositellaan täyden fontin asentamista. "
            "Voit tuoda oman .ttf/.otf -fonttisi koneelta tai ladata luvallasi suositellun avoimen vastineen."
        )
        self.desc_label.setStyleSheet("color: #a4b0be; font-size: 11px; line-height: 1.4;")
        self.desc_label.setWordWrap(True)
        header_layout.addWidget(self.desc_label)

        layout.addWidget(self.header_frame)

        # 2. Fonttilistaus-taulukko
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels([
            "Kirjasinperhe", "Tyyli / Leikkaus", "PDF-nimi", "Sivut", "Tila & Saatavuus", "Suositeltu avoin vastine"
        ])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)

        # Sarakkeiden mitoitus ja venytys
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)

        self.table.setColumnWidth(0, 160)  # Kirjasinperhe
        self.table.setColumnWidth(1, 115)  # Tyyli
        self.table.setColumnWidth(2, 210)  # PDF-nimi
        self.table.setColumnWidth(3, 110)  # Sivut
        # Sarake 4 venyy (Tila & Saatavuus)
        self.table.setColumnWidth(5, 240)  # Suositeltu avoin vastine

        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #1e252f;
                alternate-background-color: #252e3a;
                color: #ecf0f1;
                border: 1px solid #34495e;
                border-radius: 6px;
                gridline-color: #2c3e50;
                font-size: 12px;
                selection-background-color: #2980b9;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                padding: 6px 12px;
            }
            QHeaderView::section {
                background-color: #2c3e50;
                color: #ecf0f1;
                font-weight: bold;
                font-size: 12px;
                padding: 9px 12px;
                border: none;
                border-right: 1px solid #34495e;
                border-bottom: 2px solid #3498db;
            }
        """)
        layout.addWidget(self.table)

        # 3. Toimintopainikkeet
        btn_layout = QHBoxLayout()

        self.btn_download_all = QPushButton("⚡ Nouda kaikki vastineet...")
        self.btn_download_all.setStyleSheet(
            "QPushButton { background-color: #0984e3; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #74b9ff; }"
            "QPushButton:disabled { background-color: #3d4a5d; color: #7f8c8d; }"
        )
        self.btn_download_all.clicked.connect(self._on_download_all_clicked)
        btn_layout.addWidget(self.btn_download_all)

        self.btn_download = QPushButton("⬇️ Lataa avoin vastine verkosta...")
        self.btn_download.setStyleSheet(
            "QPushButton { background-color: #27ae60; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #2ecc71; }"
            "QPushButton:disabled { background-color: #3d4a5d; color: #7f8c8d; }"
        )
        self.btn_download.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        btn_layout.addWidget(self.btn_download)

        self.btn_import = QPushButton("📁 Tuo fonttitiedosto koneelta (.ttf / .otf)...")
        self.btn_import.setStyleSheet(
            "QPushButton { background-color: #2980b9; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #3498db; }"
        )
        self.btn_import.clicked.connect(self._on_import_clicked)
        btn_layout.addWidget(self.btn_import)

        btn_layout.addStretch()

        self.btn_refresh = QPushButton("🔄 Päivitä")
        self.btn_refresh.setStyleSheet(
            "QPushButton { background-color: #4a5568; color: white; padding: 8px 14px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #718096; }"
        )
        self.btn_refresh.clicked.connect(self.refresh_fonts)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_close = QPushButton("Sulje")
        self.btn_close.setStyleSheet(
            "QPushButton { background-color: #4a5568; color: white; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
            "QPushButton:hover { background-color: #718096; }"
        )
        self.btn_close.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_close)

        layout.addLayout(btn_layout)

    def refresh_fonts(self):
        """Hakee ja päivittää dokumentin kirjasintiedot taulukkoon."""
        if not self.doc_model or not self.doc_model.is_open:
            self.table.setRowCount(0)
            return

        # Päivitetään paikallinen fonttikatalogi
        FontconfigResolver.scan_local_user_fonts(force_reload=True)
        self.fonts_summary = self.doc_model.get_document_fonts_summary()
        self.table.setRowCount(len(self.fonts_summary))

        for row, f in enumerate(self.fonts_summary):
            # 0. Perhe
            fam_item = QTableWidgetItem(f["clean_family"])
            fam_font = fam_item.font()
            fam_font.setBold(True)
            fam_item.setFont(fam_font)
            self.table.setItem(row, 0, fam_item)

            # 1. Tyyli
            styles = []
            if f["is_bold"]:
                styles.append("Lihavoitu")
            if f["is_italic"]:
                styles.append("Kursiivi")
            style_str = " + ".join(styles) if styles else "Normaali"
            self.table.setItem(row, 1, QTableWidgetItem(style_str))

            # 2. PDF-nimi
            pdf_name_str = f["name"]
            if f["is_subset"]:
                pdf_name_str += " (Subset)"
            self.table.setItem(row, 2, QTableWidgetItem(pdf_name_str))

            # 3. Sivut
            pages_str = format_page_ranges(f["pages"], self.doc_model.page_count if self.doc_model else 0)
            self.table.setItem(row, 3, QTableWidgetItem(pages_str))

            # 4. Tila & Saatavuus
            if f["is_installed"]:
                if "Avoin vastine" in f.get("status_desc", ""):
                    status_text = f"✅ {f['status_desc']}"
                elif not f["is_subset"]:
                    status_text = f"✅ Asennettu ({f['status_desc']})"
                else:
                    status_text = f"✅ Asennettu paikallisesti ({f['status_desc']})"
                color = QColor("#2ecc71")
            elif f["is_subset"]:
                status_text = f"⚠️ Osajoukko PDF:ssä — uudet merkit korvikkeella ({f['status_desc']})"
                color = QColor("#f39c12")
            else:
                status_text = f"❌ Ei asennettu ({f['status_desc']})"
                color = QColor("#e74c3c")

            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(color)
            self.table.setItem(row, 4, status_item)

            # 5. Suositeltu avoin vastine
            rec_text = f.get("recommendation") or "—"
            if f["is_installed"] and "Avoin vastine" in f.get("status_desc", ""):
                rec_text = f"✅ Käytössä: {rec_text.split('(')[0].strip()}"
            rec_item = QTableWidgetItem(rec_text)
            self.table.setItem(row, 5, rec_item)

        # Päivitetään tilaruutu ja "Nouda kaikki" -painikkeen tila
        uninstalled_total = [f for f in self.fonts_summary if not f.get("is_installed", False)]
        missing_with_rec = [f for f in self.fonts_summary if not f.get("is_installed", False) and f.get("rec_id")]

        if not uninstalled_total:
            self.header_frame.setStyleSheet(
                "background-color: #172a1e; border: 1px solid #27ae60; border-radius: 8px; padding: 12px;"
            )
            self.title_label.setText("<b>Dokumentin kirjasimet ja saatavuus — Kaikki asennettu!</b>")
            self.desc_label.setText(
                "🎉 <b>Kaikki tämän dokumentin tarvitsemat kirjasimet tai niiden avoimet vastineet on asennettu ja 100 % käyttövalmiina!</b><br>"
                "Mitään ei tarvitse enää ladata. Voit sulkea tämän ikkunan ja muokata tekstiä vapaasti täydellä typografialla."
            )
            self.desc_label.setStyleSheet("color: #2ecc71; font-size: 11px; line-height: 1.4;")
            self.btn_download_all.setText("✅ Kaikki kirjasimet on jo asennettu ja käyttövalmiina")
            self.btn_download_all.setEnabled(False)
            self.btn_download_all.setStyleSheet(
                "QPushButton { background-color: #1b3823; color: #2ecc71; border: 1px solid #27ae60; font-weight: bold; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
            )
        elif missing_with_rec:
            self.header_frame.setStyleSheet(
                "background-color: #242b35; border: 1px solid #3d4a5d; border-radius: 8px; padding: 12px;"
            )
            self.title_label.setText("<b>Dokumentin kirjasimet ja saatavuus</b>")
            self.desc_label.setText(
                "PDF-dokumenteissa ammattimaiset kirjasimet on usein upotettu vain osittaisina osajoukkoina (subset). "
                "Voit ladata puuttuvat avoimet vastineet suoraan painikkeella 'Nouda kaikki puuttuvat vastineet'."
            )
            self.desc_label.setStyleSheet("color: #a4b0be; font-size: 11px; line-height: 1.4;")
            self.btn_download_all.setText(f"⚡ Nouda kaikki puuttuvat vastineet ({len(missing_with_rec)} kpl)...")
            self.btn_download_all.setEnabled(True)
            self.btn_download_all.setStyleSheet(
                "QPushButton { background-color: #0984e3; color: white; font-weight: bold; padding: 8px 16px; border-radius: 4px; font-size: 12px; }"
                "QPushButton:hover { background-color: #74b9ff; }"
            )
        else:
            self.btn_download_all.setText("⚡ Kaikki suositellut vastineet asennettu")
            self.btn_download_all.setEnabled(False)

        self._on_selection_changed()

    def _on_download_all_clicked(self):
        """Lataa ja ottaa käyttöön kerralla kaikki puuttuvat suositellut vastineet."""
        missing = [f for f in self.fonts_summary if not f.get("is_installed", False) and f.get("rec_id")]
        if not missing:
            QMessageBox.information(
                self,
                "Kaikki kirjasimet kunnossa",
                "Kaikki dokumentin tarvitsemat kirjasimet tai niiden suositellut avoimet vastineet on jo asennettu!"
            )
            return

        to_download_names = list(dict.fromkeys([f.get("recommendation", f["clean_family"]) for f in missing]))
        names_bullets = "\n".join(f"• {n}" for n in to_download_names)

        confirm = QMessageBox.question(
            self,
            "Vahvista kaikkien puuttuvien kirjasinten lataus",
            f"Haluatko noutaa seuraavat suositellut avoimet vastineet (Google Fonts)?\n\n"
            f"{names_bullets}\n\n"
            f"Tiedostot tallennetaan sovelluksen paikalliseen fonts/-kansioon ja "
            f"otetaan välittömästi käyttöön dokumentissa ilman manuaalisia säätöjä.\n\n"
            f"Sallitaanko lataus?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        success_count, total_count, errors = FontDownloader.download_all_recommended(self.doc_model)
        if success_count > 0:
            msg = f"{success_count}/{total_count} avointa kirjasinta ladattiin ja otettiin käyttöön onnistuneesti!"
            if errors:
                msg += "\n\nHuomiot:\n" + "\n".join(errors)
            QMessageBox.information(self, "Kirjasimet asennettu ja päivitetty", msg)
            self.refresh_fonts()
            self.fonts_updated.emit()
        else:
            QMessageBox.warning(
                self,
                "Lataus epäonnistui",
                "Kirjasinten automaattinen nouto epäonnistui:\n" + "\n".join(errors)
            )

    def _get_selected_font(self) -> Optional[Dict[str, Any]]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        idx = rows[0].row()
        if 0 <= idx < len(self.fonts_summary):
            return self.fonts_summary[idx]
        return None

    def _on_selection_changed(self):
        font_info = self._get_selected_font()
        if not font_info:
            self.btn_download.setEnabled(False)
            self.btn_download.setText("⬇️ Lataa avoin vastine verkosta...")
            return

        rec_id = font_info.get("rec_id")
        rec_desc = font_info.get("recommendation")
        is_installed = font_info.get("is_installed", False)
        short_rec = rec_desc.split("(")[0].strip() if rec_desc else ""

        if rec_id and not is_installed:
            self.btn_download.setEnabled(True)
            self.btn_download.setText(f"⬇️ Lataa '{short_rec}' (Google Fonts)...")
        elif rec_id and is_installed:
            self.btn_download.setEnabled(True)
            self.btn_download.setText(f"⬇️ Lataa uudelleen: {short_rec}")
        elif is_installed:
            self.btn_download.setEnabled(False)
            self.btn_download.setText(f"✅ {font_info['clean_family']} on asennettu ja valmis")
        else:
            self.btn_download.setEnabled(False)
            self.btn_download.setText("✅ Standardi PDF-kirjasin (Asennettu)")

    def _on_download_clicked(self):
        font_info = self._get_selected_font()
        if not font_info:
            return

        rec_id = font_info.get("rec_id")
        rec_desc = font_info.get("recommendation", rec_id)
        clean_fam = font_info.get("clean_family", "")

        # Kysytään KÄYTTÄJÄLTÄ NIMENOMAINEN LUPA ennen verkkolatausta!
        confirm = QMessageBox.question(
            self,
            "Vahvista kirjasimen lataus",
            f"Haluatko ladata avoimen kirjasimen '{rec_desc}' (Google Fonts)?\n\n"
            f"Sovellus toimii oletuksena 100 % offline-tilassa ilman verkkoyhteyksiä. "
            f"Tämä toiminto tekee kertaluonteisen HTTPS-pyynnön kirjasintiedoston noutamiseksi "
            f"sovelluksen paikalliseen fonts/-kansioon.\n\n"
            f"Kohdekansio: {LOCAL_FONTS_DIR}\n\n"
            f"Sallitaanko lataus?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )

        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Suoritetaan lataus
        success, msg, out_path = FontDownloader.download_open_font(rec_id or clean_fam)
        if success:
            QMessageBox.information(
                self,
                "Kirjasin asennettu",
                f"{msg}\n\nTiedosto tallennettu: {out_path}\n"
                f"Kirjasin on nyt välittömästi käytettävissä tekstin muokkaamiseen!"
            )
            self.refresh_fonts()
            self.fonts_updated.emit()
        else:
            QMessageBox.warning(
                self,
                "Lataus epäonnistui",
                f"{msg}\n\nVoit tuoda fonttitiedoston omalta koneeltasi painikkeella 'Tuo fonttitiedosto koneelta'."
            )

    def _on_import_clicked(self):
        src_file, _ = QFileDialog.getOpenFileName(
            self,
            "Valitse fonttitiedosto (.ttf tai .otf)",
            "",
            "Fonttitiedostot (*.ttf *.otf)"
        )
        if not src_file:
            return

        success, msg, out_path = FontDownloader.import_font_file(src_file)
        if success:
            QMessageBox.information(
                self,
                "Fonttitiedosto tuotu",
                f"{msg}\n\nTallennettu: {out_path}\n"
                f"Kirjasin on nyt käytettävissä dokumentin muokkaamiseen!"
            )
            self.refresh_fonts()
            self.fonts_updated.emit()
        else:
            QMessageBox.warning(self, "Tuonti epäonnistui", msg)
