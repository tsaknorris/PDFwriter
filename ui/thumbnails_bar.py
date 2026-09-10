"""
Sivujen esikatselu- ja hallintapalkki (Thumbnails Bar).
Toteuttaa turvallisen InternalMove Drag & Drop -siirron ilman elementtien katoamista,
ulkoisten PDF-tiedostojen pudotuksen (insert) sekä kattavan vianmäärityslokituksen.
"""

import os
from typing import Optional, List
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QPoint, QItemSelectionModel
from PyQt6.QtGui import QIcon, QPixmap, QDragEnterEvent, QDragMoveEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QListWidget, QListWidgetItem,
    QLabel, QMenu, QFileDialog, QMessageBox, QAbstractItemView
)

from pdf_engine.pdf_document import PDFDocumentModel
from ui.batch_pages_dialog import BatchPageOperationsDialog, format_page_range_string


class ThumbnailsListWidget(QListWidget):
    """
    Räätälöity QListWidget:
    - Käyttää Qt:n luotettavaa InternalMove -tilaa sivujen siirtämiseen.
    - Tukee monivalintaa (ExtendedSelection: Shift+klik, Ctrl+klik, Ctrl+A).
    - Tukee pikanäppäimiä: Ctrl+A (valitse kaikki), Delete/Backspace (poista valitut), Ctrl+Z / Ctrl+Y.
    - Hyväksyy ulkoisten .pdf-tiedostojen pudotuksen tiedostonhallinnasta.
    """

    pdf_files_dropped = pyqtSignal(list, int)  # ([file_paths], target_index)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()
    delete_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setIconSize(QSize(100, 140))
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_A:
                self.selectAll()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Z and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.undo_requested.emit()
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Y or (event.key() == Qt.Key.Key_Z and (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
                self.redo_requested.emit()
                event.accept()
                return
        if event.key() == Qt.Key.Key_Delete:
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            if any(u.toLocalFile().lower().endswith(".pdf") for u in urls):
                print(f"[DEBUG-PAGE] Ulkoinen PDF raahattu sivupalkkiin: {len(urls)} tiedostoa.")
                event.acceptProposedAction()
                return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent):
        # 1. Ulkoiset PDF-tiedostot
        if event.mimeData().hasUrls():
            pdf_paths = [
                u.toLocalFile() for u in event.mimeData().urls()
                if u.toLocalFile().lower().endswith(".pdf") and os.path.isfile(u.toLocalFile())
            ]
            if pdf_paths:
                drop_item = self.itemAt(event.position().toPoint())
                target_idx = self.row(drop_item) if drop_item else self.count()
                print(f"[DEBUG-PAGE] Pudotettiin {len(pdf_paths)} ulkoista PDF-tiedostoa kohtaan {target_idx}.")
                event.acceptProposedAction()
                self.pdf_files_dropped.emit(pdf_paths, target_idx)
                return

        # 2. Sisäinen siirto: annetaan Qt:n sisäänrakennetun InternalMoven hoitaa siirto turvallisesti
        print(f"[DEBUG-PAGE] Suoritetaan sisäinen sivun siirto (InternalMove)...")
        super().dropEvent(event)


class ThumbnailsBar(QWidget):
    """Sivujen pikkukuvat ja sivumuokkausten ohjauspaneeli."""

    page_selected = pyqtSignal(int)
    page_structure_changed = pyqtSignal(int)
    undo_requested = pyqtSignal()
    redo_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.doc_model: Optional[PDFDocumentModel] = None
        self._is_reordering: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)
        self.header_label = QLabel("Sivut")
        self.header_label.setStyleSheet("font-weight: bold; padding: 2px;")
        header_layout.addWidget(self.header_label, stretch=1)

        self.btn_batch_pages = QPushButton("⚙️ Erätoiminnot...")
        self.btn_batch_pages.setToolTip("Avaa sivujen hallinta- ja erätoimintovalikko (Ctrl+Shift+P)")
        self.btn_batch_pages.setStyleSheet("font-size: 11px; padding: 2px 6px;")
        self.btn_batch_pages.clicked.connect(self.open_batch_dialog)
        header_layout.addWidget(self.btn_batch_pages)

        layout.addLayout(header_layout)

        self.list_widget = ThumbnailsListWidget()
        self.list_widget.currentRowChanged.connect(self._on_row_changed)
        self.list_widget.model().rowsMoved.connect(self._on_rows_moved)
        self.list_widget.pdf_files_dropped.connect(self._on_pdf_files_dropped)
        self.list_widget.undo_requested.connect(self.undo_requested.emit)
        self.list_widget.redo_requested.connect(self.redo_requested.emit)
        self.list_widget.delete_requested.connect(self._on_delete_requested)

        # Oikean napin kontekstivalikko
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)

        layout.addWidget(self.list_widget)

    def set_document(self, doc_model: PDFDocumentModel):
        self.doc_model = doc_model
        self.refresh_thumbnails(keep_selected_page=0)

    def refresh_thumbnails(self, keep_selected_page: Optional[int] = None):
        """Päivittää pikkukuvat dokumentin nykytilasta."""
        if keep_selected_page is None:
            current_row = self.list_widget.currentRow()
            target_row = current_row if current_row >= 0 else 0
        else:
            target_row = keep_selected_page

        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        if not self.doc_model or not self.doc_model.is_open:
            self.header_label.setText("Sivut (0)")
            self.list_widget.blockSignals(False)
            print("[DEBUG-PAGE] refresh_thumbnails: Ei avointa dokumenttia.")
            return

        page_count = self.doc_model.page_count
        self.header_label.setText(f"Sivut ({page_count})")
        print(f"[DEBUG-PAGE] refresh_thumbnails: Luodaan {page_count} sivun esikatselukuvat.")

        for idx in range(page_count):
            try:
                qimg, _, _ = self.doc_model.render_page(idx, scale=0.25)
                pix = QPixmap.fromImage(qimg)
                item = QListWidgetItem(QIcon(pix), f"Sivu {idx + 1}")
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self.list_widget.addItem(item)
            except Exception as e:
                print(f"[DEBUG-PAGE] Virhe sivun {idx} renderöinnissä: {e}")
                item = QListWidgetItem(f"Sivu {idx + 1}")
                item.setData(Qt.ItemDataRole.UserRole, idx)
                self.list_widget.addItem(item)

        if page_count > 0:
            target_row = max(0, min(target_row, page_count - 1))
            self.list_widget.setCurrentRow(target_row)

        self.list_widget.blockSignals(False)
        print(f"[DEBUG-PAGE] refresh_thumbnails valmis: {self.list_widget.count()} kuvaa listassa, valittu sivu={target_row}.")

    def update_single_thumbnail(self, page_idx: int):
        """Päivittää ainoastaan yhden muuttuneen sivun pikkukuvan."""
        if not self.doc_model or not self.doc_model.is_open:
            return
        if 0 <= page_idx < self.list_widget.count():
            try:
                qimg, _, _ = self.doc_model.render_page(page_idx, scale=0.25)
                pix = QPixmap.fromImage(qimg)
                item = self.list_widget.item(page_idx)
                if item:
                    item.setIcon(QIcon(pix))
                print(f"[DEBUG-PAGE] Yksittäinen pikkukuva päivitetty sivulle {page_idx + 1}.")
            except Exception as e:
                print(f"[DEBUG-PAGE] Virhe sivun {page_idx} pikkukuvan päivityksessä: {e}")

    def select_page(self, page_idx: int):
        if 0 <= page_idx < self.list_widget.count():
            self.list_widget.blockSignals(True)
            self.list_widget.setCurrentRow(page_idx)
            self.list_widget.blockSignals(False)

    def _on_row_changed(self, row: int):
        if row >= 0 and not self._is_reordering:
            print(f"[DEBUG-PAGE] Käyttäjä valitsi rivin {row} (Sivu {row + 1}).")
            self.page_selected.emit(row)

    def _on_rows_moved(self, parent, start, end, destination, row):
        """
        Qt:n sisäinen malli ilmoittaa kun rivi on siirretty hiirellä.
        Päivittää dokumenttimallin vastaamaan uutta järjestystä.
        """
        if not self.doc_model or not self.doc_model.is_open:
            return

        self._is_reordering = True

        # Lasketaan uusi kohdeindeksi
        from_idx = start
        if start < row:
            to_idx = row - 1
        else:
            to_idx = row

        print(f"[DEBUG-PAGE] rowsMoved havaittu: siirretään sivu {from_idx} -> {to_idx}. Sivuja yhteensä: {self.list_widget.count()}.")

        # 1. Siirretään sivu PDF-dokumentissa
        self.doc_model.move_page(from_idx, to_idx)

        # 2. Päivitetään pikkukuvien tekstietiketit (Sivu 1, Sivu 2, ...)
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setText(f"Sivu {i + 1}")
            item.setData(Qt.ItemDataRole.UserRole, i)
        self.list_widget.setCurrentRow(to_idx)
        self.list_widget.blockSignals(False)

        self._is_reordering = False
        print(f"[DEBUG-PAGE] Sivut järjestetty uudelleen: sivu {to_idx} on nyt aktiivinen.")
        self.page_structure_changed.emit(to_idx)

    def _on_pdf_files_dropped(self, pdf_paths: List[str], target_idx: int):
        if not self.doc_model or not self.doc_model.is_open:
            return

        total_inserted = 0
        current_target = target_idx
        for p in pdf_paths:
            try:
                count = self.doc_model.insert_pdf_pages(p, at_idx=current_target)
                print(f"[DEBUG-PAGE] Liitettiin {count} sivua tiedostosta {p} kohtaan {current_target}.")
                current_target += count
                total_inserted += count
            except Exception as e:
                print(f"[DEBUG-PAGE] Virhe liitettäessä {p}: {e}")
                QMessageBox.critical(self, "Virhe PDF:n liitossa", f"Tiedoston {p} liittäminen epäonnistui:\n{str(e)}")

        if total_inserted > 0:
            self.refresh_thumbnails(keep_selected_page=target_idx)
            self.page_structure_changed.emit(target_idx)

    def get_selected_pages(self) -> List[int]:
        """Palauttaa tällä hetkellä valittujen sivujen 0-pohjaiset indeksit lajiteltuna."""
        items = self.list_widget.selectedItems()
        if not items:
            curr = self.list_widget.currentRow()
            return [curr] if curr >= 0 else []
        rows = []
        for item in items:
            r = self.list_widget.row(item)
            if r >= 0:
                rows.append(r)
        return sorted(list(set(rows)))

    def set_selected_pages(self, pages: List[int]):
        """Asettaa annetut sivut valituiksi pikkukuvalistassa ja siirtää katselun ensimmäiseen."""
        self.list_widget.blockSignals(True)
        self.list_widget.clearSelection()
        for idx in pages:
            if 0 <= idx < self.list_widget.count():
                item = self.list_widget.item(idx)
                if item:
                    item.setSelected(True)
        if pages:
            first = min(pages)
            if 0 <= first < self.list_widget.count():
                m_idx = self.list_widget.model().index(first, 0)
                if self.list_widget.selectionModel():
                    self.list_widget.selectionModel().setCurrentIndex(
                        m_idx, QItemSelectionModel.SelectionFlag.NoUpdate
                    )
                item = self.list_widget.item(first)
                if item:
                    self.list_widget.scrollToItem(item)
        self.list_widget.blockSignals(False)
        if pages:
            self.page_selected.emit(min(pages))

    def open_batch_dialog(self):
        """Avaa sivujen hallinta- ja erätoimintodialogin."""
        if not self.doc_model or not self.doc_model.is_open:
            return
        selected = self.get_selected_pages()
        dlg = BatchPageOperationsDialog(
            self.doc_model,
            initial_pages=selected,
            parent=self.window() or self
        )
        dlg.pages_modified.connect(self._on_dialog_pages_modified)
        dlg.selection_applied.connect(self.set_selected_pages)
        dlg.exec()

    def _on_dialog_pages_modified(self, new_active_page: int):
        self.refresh_thumbnails(keep_selected_page=new_active_page)
        self.page_structure_changed.emit(new_active_page)

    def _confirm_and_delete_pages(self, pages: List[int]):
        """Vahvistaa ja poistaa useita tai yhden sivun turvallisesti."""
        if not self.doc_model or not self.doc_model.is_open or not pages:
            return
        total = self.doc_model.page_count
        if total <= 1 or len(pages) >= total:
            # Dokumentissa täytyy olla vähintään 1 sivu (PDF-standardi). Ei avata häiritseviä ponnahdusikkunoita.
            return

        formatted = format_page_range_string(pages)
        n = len(pages)
        if n == 1:
            msg = f"Haluatko varmasti poistaa sivun {pages[0] + 1}?"
        else:
            msg = f"Haluatko varmasti poistaa {n} valittua sivua ({formatted})?"

        ret = QMessageBox.question(
            self, "Vahvista sivujen poisto", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            print(f"[DEBUG-PAGE] Poistetaan sivut {pages} ({formatted}).")
            if self.doc_model.delete_pages(pages):
                new_idx = min(pages[0], self.doc_model.page_count - 1)
                self.refresh_thumbnails(keep_selected_page=new_idx)
                self.page_structure_changed.emit(new_idx)

    def _on_delete_requested(self):
        selected = self.get_selected_pages()
        if selected:
            self._confirm_and_delete_pages(selected)

    def _show_context_menu(self, pos: QPoint):
        if not self.doc_model or not self.doc_model.is_open:
            return

        item = self.list_widget.itemAt(pos)
        selected_pages = self.get_selected_pages()

        if item:
            clicked_row = self.list_widget.row(item)
            if clicked_row not in selected_pages:
                self.list_widget.setCurrentRow(clicked_row)
                selected_pages = [clicked_row]
        elif not selected_pages:
            curr = self.list_widget.currentRow()
            selected_pages = [curr] if curr >= 0 else [0]

        menu = QMenu(self)

        # Undo / Redo
        act_undo = menu.addAction("↩️ Kumoa (Undo / Ctrl+Z)")
        act_redo = menu.addAction("↪️ Tee uudelleen (Redo / Ctrl+Y)")
        act_undo.setEnabled(self.doc_model.can_undo() if self.doc_model else False)
        act_redo.setEnabled(self.doc_model.can_redo() if self.doc_model else False)
        menu.addSeparator()

        if len(selected_pages) > 1:
            # Monivalinnan toiminnot
            formatted_range = format_page_range_string(selected_pages)
            info_act = menu.addAction(f"📑 Valitut sivut ({len(selected_pages)} kpl: {formatted_range})")
            info_act.setEnabled(False)
            menu.addSeparator()

            act_batch_dialog = menu.addAction("⚙️ Sivujen erätoiminnot... (Ctrl+Shift+P)")
            act_rotate_cw = menu.addAction(f"🔄 Kierrä valitut sivut ({len(selected_pages)} kpl) 90°")
            act_duplicate = menu.addAction(f"📋 Monista valitut sivut ({len(selected_pages)} kpl)")
            act_extract = menu.addAction("💾 Pura valitut sivut uuteen PDF:ään...")
            menu.addSeparator()
            act_delete = menu.addAction(f"🗑️ Poista valitut sivut ({len(selected_pages)} kpl)")

            if len(selected_pages) >= self.doc_model.page_count:
                act_delete.setEnabled(False)

            action = menu.exec(self.list_widget.mapToGlobal(pos))
            if not action:
                return

            if action == act_undo:
                self.undo_requested.emit()
            elif action == act_redo:
                self.redo_requested.emit()
            elif action == act_batch_dialog:
                self.open_batch_dialog()
            elif action == act_rotate_cw:
                self.doc_model.rotate_pages(selected_pages, 90)
                self.refresh_thumbnails(keep_selected_page=selected_pages[0])
                self.page_structure_changed.emit(selected_pages[0])
            elif action == act_duplicate:
                self.doc_model.duplicate_pages(selected_pages)
                self.refresh_thumbnails(keep_selected_page=selected_pages[0])
                self.page_structure_changed.emit(selected_pages[0])
            elif action == act_extract:
                default_name = f"valitut_sivut_{formatted_range.replace(' ', '_')}.pdf"
                path, _ = QFileDialog.getSaveFileName(
                    self, "Tallenna valitut sivut uuteen PDF-tiedostoon", default_name, "PDF-tiedostot (*.pdf)"
                )
                if path:
                    if self.doc_model.extract_pages_to_file(selected_pages, path):
                        QMessageBox.information(
                            self, "Purkaminen valmis",
                            f"{len(selected_pages)} sivua purettiin ja tallennettiin onnistuneesti tiedostoon:\n{os.path.basename(path)}"
                        )
            elif action == act_delete:
                self._confirm_and_delete_pages(selected_pages)
        else:
            # Yksittäisen sivun toiminnot
            page_idx = selected_pages[0] if selected_pages else 0

            act_batch_dialog = menu.addAction("⚙️ Sivujen erätoiminnot... (Ctrl+Shift+P)")
            menu.addSeparator()
            act_insert_pdf = menu.addAction("📄 Lisää sivuja toisesta PDF-tiedostosta tähän väliin...")
            act_insert_blank = menu.addAction("➕ Lisää tyhjä sivu tähän")
            act_duplicate = menu.addAction("📋 Monista tämä sivu")
            act_rotate_cw = menu.addAction("🔄 Kierrä 90° myötäpäivään")
            menu.addSeparator()
            act_delete = menu.addAction("🗑️ Poista tämä sivu")

            if self.doc_model.page_count <= 1:
                act_delete.setEnabled(False)

            action = menu.exec(self.list_widget.mapToGlobal(pos))
            if not action:
                return

            if action == act_undo:
                self.undo_requested.emit()
            elif action == act_redo:
                self.redo_requested.emit()
            elif action == act_batch_dialog:
                self.open_batch_dialog()
            elif action == act_insert_pdf:
                path, _ = QFileDialog.getOpenFileName(
                    self, "Valitse liitettävä PDF-tiedosto", "", "PDF-tiedostot (*.pdf)"
                )
                if path:
                    self._on_pdf_files_dropped([path], page_idx + 1)
            elif action == act_insert_blank:
                print(f"[DEBUG-PAGE] Lisätään tyhjä sivu kohtaan {page_idx + 1}.")
                self.doc_model.insert_blank_page(page_idx + 1)
                self.refresh_thumbnails(keep_selected_page=page_idx + 1)
                self.page_structure_changed.emit(page_idx + 1)
            elif action == act_duplicate:
                print(f"[DEBUG-PAGE] Monistetaan sivu {page_idx + 1}.")
                self.doc_model.duplicate_page(page_idx)
                self.refresh_thumbnails(keep_selected_page=page_idx + 1)
                self.page_structure_changed.emit(page_idx + 1)
            elif action == act_rotate_cw:
                print(f"[DEBUG-PAGE] Kierretään sivua {page_idx + 1} 90 astetta.")
                self.doc_model.rotate_page(page_idx, 90)
                self.refresh_thumbnails(keep_selected_page=page_idx)
                self.page_structure_changed.emit(page_idx)
            elif action == act_delete:
                self._confirm_and_delete_pages([page_idx])
