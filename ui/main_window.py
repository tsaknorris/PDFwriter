"""
Pääikkuna ja Käyttöliittymäorkesterointi (Main Window).
Yhdistää sivukankaan, pikkukuvat, in-place -tekstieditorin, syvätarkastelijan,
sivujenhallinnan (Drag & Drop, Insert PDF, kierto, poisto) sekä Gauntlet Loop -laatuvalidoinnin.
"""

import os
from typing import Optional, Dict, Any

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
    QDockWidget, QFileDialog, QMessageBox, QStatusBar, QLabel,
    QToolBar, QDialog, QTextBrowser, QPushButton, QFrame,
    QToolButton, QMenu
)

from pdf_engine.pdf_document import PDFDocumentModel, EditOperation
from pdf_engine.font_resolver import FontMatchResult, FontDownloader
from pdf_engine.layout_engine import FitStrategy
from pdf_engine.validator import GauntletValidator, ValidationReport

from .page_canvas import PDFPageCanvas
from .text_editor_dock import TextEditorDock
from .inspector_panel import InspectorPanel
from .thumbnails_bar import ThumbnailsBar
from .font_manager_dialog import FontManagerDialog
from .margins_dialog import MarginsDialog
from .shape_properties_dock import ShapePropertiesDock
from .layers_panel import LayersPanel


class GauntletReportDialog(QDialog):
    """Gauntlet Loop -laaturaportin näyttävä dialogi."""

    def __init__(self, report: ValidationReport, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Gauntlet Loop -laadunvarmistusraportti")
        self.resize(750, 500)

        layout = QVBoxLayout(self)
        browser = QTextBrowser()
        browser.setMarkdown(report.summary_markdown())
        layout.addWidget(browser)

        close_btn = QPushButton("Sulje")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


class MainWindow(QMainWindow):
    """Pääikkuna."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Acrobat-tason Offline PDF-Editori (Linux / NixOS Architecture)")
        self.resize(1400, 900)

        self.doc_model = PDFDocumentModel()
        self.current_span: Optional[Dict[str, Any]] = None
        self.current_block: Optional[Dict[str, Any]] = None

        self.init_ui()
        self.init_menus_and_toolbars()
        self.update_action_states()

    def init_ui(self):
        # Keskusalue (Scrollattava Canvas + Fonttihuomautuspalkki)
        central_container = QWidget()
        central_layout = QVBoxLayout(central_container)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # Yläpalkki: Fonttihuomautus (näytetään jos dokumentissa on puuttuvia fontteja tai osajoukkoja)
        self.font_banner = QFrame()
        self.font_banner.setStyleSheet(
            "background-color: #fff3cd; border-bottom: 1px solid #ffeeba; padding: 4px 12px;"
        )
        self.font_banner.setVisible(False)
        banner_layout = QHBoxLayout(self.font_banner)
        banner_layout.setContentsMargins(8, 4, 8, 4)
        banner_layout.setSpacing(10)

        self.banner_label = QLabel("⚠️ Dokumentissa on kirjasimia ilman täyttä asennusta.")
        self.banner_label.setStyleSheet("color: #856404; font-weight: bold; font-size: 11px;")
        banner_layout.addWidget(self.banner_label, 1)

        self.btn_banner_auto_download = QPushButton("⚡ Nouda suositellut vastineet")
        self.btn_banner_auto_download.setStyleSheet(
            "background-color: #27ae60; color: white; font-weight: bold; padding: 3px 10px; border-radius: 3px; font-size: 11px;"
        )
        self.btn_banner_auto_download.clicked.connect(self._auto_download_missing_fonts)
        banner_layout.addWidget(self.btn_banner_auto_download)

        self.btn_banner_manage = QPushButton("🔤 Hallitse fontteja...")
        self.btn_banner_manage.setStyleSheet(
            "background-color: #ffc107; color: #212529; font-weight: bold; padding: 3px 10px; border-radius: 3px; font-size: 11px;"
        )
        self.btn_banner_manage.clicked.connect(self.show_font_manager_dialog)
        banner_layout.addWidget(self.btn_banner_manage)

        self.btn_banner_dismiss = QPushButton("✕")
        self.btn_banner_dismiss.setStyleSheet(
            "background: transparent; border: none; font-size: 13px; font-weight: bold; color: #856404;"
        )
        self.btn_banner_dismiss.clicked.connect(lambda: self.font_banner.setVisible(False))
        banner_layout.addWidget(self.btn_banner_dismiss)

        central_layout.addWidget(self.font_banner)

        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll_area.setStyleSheet("background-color: #34495e;")

        self.canvas = PDFPageCanvas()
        self.canvas.block_selected.connect(self._on_block_selected)
        self.canvas.span_selected.connect(self._on_span_selected)
        self.canvas.mode_changed.connect(lambda mode: self._sync_mode_ui(mode))
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.text_selected.connect(self._on_text_selected)
        self.canvas.request_edit.connect(self._focus_editor)
        self.canvas.request_font_manager.connect(self.show_font_manager_dialog)
        self.canvas.request_bold.connect(self._toggle_bold)
        self.canvas.request_italic.connect(self._toggle_italic)
        self.canvas.request_fontsize.connect(self._set_editor_fontsize)
        self.canvas.request_paste.connect(self._paste_into_editor)
        self.canvas.request_delete_text.connect(self._delete_selected_text)
        self.canvas.request_delete_block.connect(self._delete_selected_block)
        self.canvas.request_undo.connect(self.undo)
        self.canvas.request_redo.connect(self.redo)
        self.scroll_area.setWidget(self.canvas)
        central_layout.addWidget(self.scroll_area)
        self.setCentralWidget(central_container)

        # Vasen sivupalkki: Sivujen pikkukuvat ja hallinta
        self.thumb_dock = QDockWidget("Sivunavigaatio & Hallinta", self)
        self.thumb_dock.setObjectName("dock_thumbnails")
        self.thumb_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.thumbnails_bar = ThumbnailsBar()
        self.thumbnails_bar.page_selected.connect(self._on_page_navigated)
        self.thumbnails_bar.page_structure_changed.connect(self._on_page_structure_changed)
        self.thumbnails_bar.undo_requested.connect(self.undo)
        self.thumbnails_bar.redo_requested.connect(self.redo)
        self.thumb_dock.setWidget(self.thumbnails_bar)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumb_dock)

        # Oikea yläpalkki: Tekstieditori (tukee kappaleita ja rivejä)
        self.editor_dock = QDockWidget("In-Place Tekstieditori", self)
        self.editor_dock.setObjectName("dock_editor")
        self.editor_widget = TextEditorDock()
        self.editor_widget.edit_committed.connect(self._on_edit_committed)
        self.editor_widget.block_edit_committed.connect(self._on_block_edit_committed)
        self.editor_widget.mode_switch_requested.connect(self._set_selection_mode)
        self.editor_widget.font_manager_requested.connect(self.show_font_manager_dialog)
        self.editor_widget.undo_requested.connect(self.undo)
        self.editor_widget.redo_requested.connect(self.redo)
        self.canvas.block_geometry_changed.connect(self.editor_widget.on_block_geometry_changed)
        self.editor_dock.setWidget(self.editor_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.editor_dock)

        # Oikea alapalkki: Kirjasin & Geometria Tarkastelija
        self.inspector_dock = QDockWidget("Kirjasin- && Dokumenttitarkastelija", self)
        self.inspector_dock.setObjectName("dock_inspector")
        self.inspector_widget = InspectorPanel()
        self.inspector_dock.setWidget(self.inspector_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)

        # Oikea alapalkki (välilehti): Muodot & Palikat (Acrobat-työkalut)
        self.shape_dock = QDockWidget("Muodot && Palikat (Acrobat-työkalut)", self)
        self.shape_dock.setObjectName("dock_shapes")
        self.shape_widget = ShapePropertiesDock()
        self.shape_widget.tool_changed.connect(self.canvas.set_active_tool)
        self.shape_widget.properties_changed.connect(self.canvas.set_shape_properties)
        self.shape_widget.add_background_to_selection_requested.connect(self.canvas.add_background_card_to_selected_block)
        self.shape_widget.delete_shape_requested.connect(self.canvas.delete_selected_shape)
        self.shape_widget.font_manager_requested.connect(self.show_font_manager_dialog)
        self.shape_widget.select_all_text_requested.connect(self.canvas.select_all_shape_text)
        self.canvas.shape_selected.connect(self._on_shape_selected)
        self.canvas.tool_switched.connect(self.shape_widget.set_tool)
        self.canvas.request_focus_shape_text.connect(self._on_request_focus_shape_text)
        self.canvas.shape_text_cursor_changed.connect(self.shape_widget.update_from_cursor_format)
        self.shape_dock.setWidget(self.shape_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.shape_dock)
        self.tabifyDockWidget(self.editor_dock, self.shape_dock)
        self.tabifyDockWidget(self.shape_dock, self.inspector_dock)

        # Oikea alapalkki (välilehti): Tasot & Objektit (Z-Order, Layers, Groups)
        self.layers_dock = QDockWidget("Tasot && Objektit (Layers)", self)
        self.layers_dock.setObjectName("dock_layers")
        self.layers_widget = LayersPanel()
        self.layers_widget.element_selected.connect(self.canvas.select_element)
        self.layers_widget.request_canvas_refresh.connect(self.canvas.refresh_page)
        self.canvas.shape_selected.connect(lambda s: self.layers_widget.select_item_by_id(s.get("id") if s else None))
        self.canvas.block_selected.connect(lambda b: self.layers_widget.select_item_by_id(b.get("block_id") if b else None))
        self.layers_dock.setWidget(self.layers_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.layers_dock)
        self.tabifyDockWidget(self.inspector_dock, self.layers_dock)

        self.canvas.shape_drawn.connect(self._on_shape_drawn)
        self.canvas.shape_properties_committed.connect(self._on_shape_properties_committed)
        self.canvas.request_margins_dialog.connect(self.show_margins_dialog)

        # Tilapalkki
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.status_file_label = QLabel("Ei tiedostoa avattuna")
        self.status_page_label = QLabel("Sivu: - / -")
        self.status_zoom_label = QLabel("Zoom: 150 %")
        self.status_offline_badge = QLabel("🔒 100 % OFFLINE")
        self.status_offline_badge.setStyleSheet("color: #4ade80; font-weight: bold; padding: 0 8px;")

        self.btn_status_restore = QPushButton("🗂️ Palauta paneelit (F4)")
        self.btn_status_restore.setToolTip("Palauta kaikki 5 sivupaneelia oletusasetteluun (F4)")
        self.btn_status_restore.setStyleSheet("background-color: #2a2a34; color: #38bdf8; font-weight: bold; padding: 2px 8px; border: 1px solid #4a4a58; border-radius: 3px; font-size: 11px;")
        self.btn_status_restore.clicked.connect(self.reset_dock_layout)

        self.status_bar.addWidget(self.status_file_label, 2)
        self.status_bar.addWidget(self.status_page_label, 1)
        self.status_bar.addWidget(self.status_zoom_label, 1)
        self.status_bar.addPermanentWidget(self.btn_status_restore)
        self.status_bar.addPermanentWidget(self.status_offline_badge)

    def init_menus_and_toolbars(self):
        menu_bar = self.menuBar()

        # --- Tiedosto-valikko ---
        file_menu = menu_bar.addMenu("&Tiedosto")
        self.act_open = QAction("&Avaa PDF...", self)
        self.act_open.setShortcut(QKeySequence.StandardKey.Open)
        self.act_open.triggered.connect(self.open_file_dialog)
        file_menu.addAction(self.act_open)

        self.act_save = QAction("&Tallenna", self)
        self.act_save.setShortcut(QKeySequence.StandardKey.Save)
        self.act_save.triggered.connect(self.save_file)
        file_menu.addAction(self.act_save)

        self.act_save_as = QAction("Tallenna &nimellä...", self)
        self.act_save_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.act_save_as.triggered.connect(self.save_file_as)
        file_menu.addAction(self.act_save_as)

        file_menu.addSeparator()
        self.act_close = QAction("&Sulje dokumentti", self)
        self.act_close.triggered.connect(self.close_file)
        file_menu.addAction(self.act_close)

        self.act_quit = QAction("&Lopeta", self)
        self.act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        self.act_quit.triggered.connect(self.close)
        file_menu.addAction(self.act_quit)

        # --- Muokkaa-valikko ---
        edit_menu = menu_bar.addMenu("&Muokkaa")
        self.act_undo = QAction("&Kumoa (Undo)", self)
        self.act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.act_undo.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_undo.triggered.connect(self.undo)
        edit_menu.addAction(self.act_undo)

        self.act_redo = QAction("&Tee uudelleen (Redo)", self)
        self.act_redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        self.act_redo.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        self.act_redo.triggered.connect(self.redo)
        edit_menu.addAction(self.act_redo)

        edit_menu.addSeparator()
        self.act_mode_paragraph = QAction("📄 Kappaletila (Koko lohko)", self)
        self.act_mode_paragraph.setCheckable(True)
        self.act_mode_paragraph.setChecked(True)
        self.act_mode_paragraph.triggered.connect(lambda: self._set_selection_mode("paragraph"))
        edit_menu.addAction(self.act_mode_paragraph)

        self.act_mode_span = QAction("📏 Rivitila (Yksittäinen rivi)", self)
        self.act_mode_span.setCheckable(True)
        self.act_mode_span.setChecked(False)
        self.act_mode_span.triggered.connect(lambda: self._set_selection_mode("span"))
        edit_menu.addAction(self.act_mode_span)

        edit_menu.addSeparator()
        self.act_group = QAction("🔗 &Ryhmittele muodot", self)
        self.act_group.setShortcut("Ctrl+G")
        self.act_group.triggered.connect(self.layers_widget._group_selected)
        edit_menu.addAction(self.act_group)

        self.act_ungroup = QAction("🔓 &Pura ryhmä", self)
        self.act_ungroup.setShortcut("Ctrl+Shift+G")
        self.act_ungroup.triggered.connect(self.layers_widget._ungroup_selected)
        edit_menu.addAction(self.act_ungroup)

        # --- Sivu-valikko ---
        page_menu = menu_bar.addMenu("&Sivu")
        self.act_batch_pages = QAction("📑 &Sivujen hallinta ja erätoiminnot...", self)
        self.act_batch_pages.setShortcut("Ctrl+Shift+P")
        self.act_batch_pages.triggered.connect(self.menu_batch_pages)
        page_menu.addAction(self.act_batch_pages)
        page_menu.addSeparator()

        self.act_insert_pdf = QAction("Lisää sivuja &tiedostosta tähän...", self)
        self.act_insert_pdf.setShortcut("Ctrl+Shift+I")
        self.act_insert_pdf.triggered.connect(self.menu_insert_pdf)
        page_menu.addAction(self.act_insert_pdf)

        self.act_insert_blank = QAction("Lisää &tyhjä sivu tähän", self)
        self.act_insert_blank.setShortcut("Ctrl+Shift+N")
        self.act_insert_blank.triggered.connect(self.menu_insert_blank_page)
        page_menu.addAction(self.act_insert_blank)

        self.act_duplicate_page = QAction("&Monista tämä sivu", self)
        self.act_duplicate_page.setShortcut("Ctrl+Shift+D")
        self.act_duplicate_page.triggered.connect(self.menu_duplicate_page)
        page_menu.addAction(self.act_duplicate_page)

        self.act_rotate_page = QAction("&Kierrä 90° myötäpäivään", self)
        self.act_rotate_page.setShortcut("Ctrl+R")
        self.act_rotate_page.triggered.connect(self.menu_rotate_page)
        page_menu.addAction(self.act_rotate_page)

        page_menu.addSeparator()
        self.act_delete_page = QAction("&Poista nykyinen sivu", self)
        self.act_delete_page.setShortcut("Ctrl+Delete")
        self.act_delete_page.triggered.connect(self.menu_delete_page)
        page_menu.addAction(self.act_delete_page)

        page_menu.addSeparator()
        self.act_page_margins = QAction("📐 &Sivun marginaalit ja arkkikoko...", self)
        self.act_page_margins.setShortcut("Ctrl+Shift+M")
        self.act_page_margins.triggered.connect(self.show_margins_dialog)
        page_menu.addAction(self.act_page_margins)

        self.act_margin_guides = QAction("👁️ Apulinjat: Näytä marginaalit", self)
        self.act_margin_guides.setCheckable(True)
        self.act_margin_guides.setChecked(True)
        self.act_margin_guides.toggled.connect(self.canvas.set_show_margin_guides)
        page_menu.addAction(self.act_margin_guides)

        # --- Lisää-valikko (Muodot & Palikat) ---
        insert_menu = menu_bar.addMenu("&Lisää")
        self.act_tool_select = QAction("🖐️ MOVE-työkalu (Siirrä & Muokkaa)", self)
        self.act_tool_select.setShortcut(QKeySequence("V"))
        self.act_tool_select.setToolTip("Siirtotyökalu (MOVE) - Siirrä, valitse ja muokkaa objekteja kankaalla (V)")
        self.act_tool_select.triggered.connect(lambda: self.shape_widget.set_tool("move"))
        insert_menu.addAction(self.act_tool_select)

        self.act_tool_textbox = QAction("🔤 Tekstilaatikko (Textbox)", self)
        self.act_tool_textbox.setShortcut(QKeySequence("T"))
        self.act_tool_textbox.setToolTip("Tekstilaatikko - Luo tai sijoita tekstiä dokumenttiin (T)")
        self.act_tool_textbox.triggered.connect(lambda: self.shape_widget.set_tool("textbox"))
        insert_menu.addAction(self.act_tool_textbox)

        insert_menu.addSeparator()
        self.act_tool_rect = QAction("🔲 Suorakulmio (Laatikko)", self)
        self.act_tool_rect.triggered.connect(lambda: self.shape_widget.set_tool("rect"))
        insert_menu.addAction(self.act_tool_rect)

        self.act_tool_round = QAction("🔲 Pyöristetty laatikko", self)
        self.act_tool_round.triggered.connect(lambda: self.shape_widget.set_tool("rounded_rect"))
        insert_menu.addAction(self.act_tool_round)

        self.act_tool_circle = QAction("🔘 Ympyrä / Ellipsi", self)
        self.act_tool_circle.triggered.connect(lambda: self.shape_widget.set_tool("circle"))
        insert_menu.addAction(self.act_tool_circle)

        self.act_tool_arrow = QAction("➔ Nuoli (Vapaa suunta)", self)
        self.act_tool_arrow.triggered.connect(lambda: self.shape_widget.set_tool("arrow"))
        insert_menu.addAction(self.act_tool_arrow)

        self.act_tool_line = QAction("━ Viiva", self)
        self.act_tool_line.triggered.connect(lambda: self.shape_widget.set_tool("line"))
        insert_menu.addAction(self.act_tool_line)

        insert_menu.addSeparator()
        self.act_add_bg_card = QAction("🎨 Lisää taustalaatikko valitulle tekstille", self)
        self.act_add_bg_card.triggered.connect(self.canvas.add_background_card_to_selected_block)
        insert_menu.addAction(self.act_add_bg_card)

        # --- Näytä-valikko ---
        view_menu = menu_bar.addMenu("&Näytä")
        self.act_zoom_in = QAction("&Lähennä", self)
        self.act_zoom_in.setShortcut(QKeySequence.StandardKey.ZoomIn)
        self.act_zoom_in.triggered.connect(lambda: self.canvas.set_zoom(self.canvas.zoom_factor * 1.25))
        view_menu.addAction(self.act_zoom_in)

        self.act_zoom_out = QAction("&Loitonna", self)
        self.act_zoom_out.setShortcut(QKeySequence.StandardKey.ZoomOut)
        self.act_zoom_out.triggered.connect(lambda: self.canvas.set_zoom(self.canvas.zoom_factor / 1.25))
        view_menu.addAction(self.act_zoom_out)

        self.act_zoom_reset = QAction("&Normaalikoko (100 %)", self)
        self.act_zoom_reset.setShortcut("Ctrl+0")
        self.act_zoom_reset.triggered.connect(lambda: self.canvas.set_zoom(1.0))
        view_menu.addAction(self.act_zoom_reset)

        view_menu.addSeparator()

        # Paneelit ja ikkunat -alivalikko
        self.panels_menu = view_menu.addMenu("🗂️ &Sivupaneelit ja Ikkunat")

        self.act_dock_thumb = self.thumb_dock.toggleViewAction()
        self.act_dock_thumb.setText("📑 Sivunavigaatio & Hallinta (Vasen)")
        self.act_dock_thumb.setShortcut("Ctrl+Alt+1")
        self.panels_menu.addAction(self.act_dock_thumb)

        self.act_dock_editor = self.editor_dock.toggleViewAction()
        self.act_dock_editor.setText("✍️ In-Place Tekstieditori (Oikea ylä)")
        self.act_dock_editor.setShortcut("Ctrl+Alt+2")
        self.panels_menu.addAction(self.act_dock_editor)

        self.act_dock_inspector = self.inspector_dock.toggleViewAction()
        self.act_dock_inspector.setText("🔍 Kirjasin- & Dokumenttitarkastelija (Oikea ala)")
        self.act_dock_inspector.setShortcut("Ctrl+Alt+3")
        self.panels_menu.addAction(self.act_dock_inspector)

        self.act_dock_shape = self.shape_dock.toggleViewAction()
        self.act_dock_shape.setText("🎨 Muodot & Palikat (Oikea ala)")
        self.act_dock_shape.setShortcut("Ctrl+Alt+4")
        self.panels_menu.addAction(self.act_dock_shape)

        self.act_dock_layers = self.layers_dock.toggleViewAction()
        self.act_dock_layers.setText("📚 Tasot & Objektit (Oikea ala)")
        self.act_dock_layers.setShortcut("Ctrl+Alt+5")
        self.panels_menu.addAction(self.act_dock_layers)

        self.panels_menu.addSeparator()
        self.act_reset_panels = QAction("🔄 Palauta oletuspaneelit (Näytä kaikki)", self)
        self.act_reset_panels.setShortcut("F4")
        self.act_reset_panels.triggered.connect(self.reset_dock_layout)
        self.panels_menu.addAction(self.act_reset_panels)
        view_menu.addAction(self.act_reset_panels)

        # --- Työkalut-valikko ---
        tools_menu = menu_bar.addMenu("&Työkalut")
        self.act_font_manager = QAction("🔤 Dokumentin &kirjasimet (Font Manager)...", self)
        self.act_font_manager.setShortcut("Ctrl+Shift+F")
        self.act_font_manager.triggered.connect(self.show_font_manager_dialog)
        tools_menu.addAction(self.act_font_manager)

        self.act_gauntlet = QAction("⚡ Suorita &Gauntlet-laadunvarmistus", self)
        self.act_gauntlet.setShortcut("F5")
        self.act_gauntlet.triggered.connect(self.run_gauntlet_audit)
        tools_menu.addAction(self.act_gauntlet)

        # --- Työkalupalkki ---
        toolbar = QToolBar("Päätyökalut", self)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        toolbar.addAction(self.act_open)
        toolbar.addAction(self.act_save)
        toolbar.addSeparator()
        toolbar.addAction(self.act_undo)
        toolbar.addAction(self.act_redo)
        toolbar.addSeparator()
        toolbar.addAction(self.act_mode_paragraph)
        toolbar.addAction(self.act_mode_span)
        toolbar.addSeparator()

        self.act_prev_page = QAction("◀ Edellinen", self)
        self.act_prev_page.triggered.connect(self.prev_page)
        toolbar.addAction(self.act_prev_page)

        self.act_next_page = QAction("Seuraava ▶", self)
        self.act_next_page.triggered.connect(self.next_page)
        toolbar.addAction(self.act_next_page)

        toolbar.addSeparator()
        toolbar.addAction(self.act_insert_pdf)
        toolbar.addAction(self.act_rotate_page)
        toolbar.addSeparator()
        toolbar.addAction(self.act_tool_select)
        toolbar.addAction(self.act_tool_textbox)
        toolbar.addAction(self.act_tool_rect)
        toolbar.addAction(self.act_tool_round)
        toolbar.addAction(self.act_tool_circle)
        toolbar.addAction(self.act_tool_arrow)
        toolbar.addAction(self.act_page_margins)
        toolbar.addSeparator()
        toolbar.addAction(self.act_zoom_in)
        toolbar.addAction(self.act_zoom_out)
        toolbar.addSeparator()
        toolbar.addAction(self.act_font_manager)
        toolbar.addAction(self.act_gauntlet)
        toolbar.addSeparator()

        self.btn_panels_tool = QToolButton(self)
        self.btn_panels_tool.setText("🗂️ Paneelit")
        self.btn_panels_tool.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.btn_panels_tool.setMenu(self.panels_menu)
        self.btn_panels_tool.setToolTip("Hallitse sivupaneeleita tai palauta oletusasettelu (F4)")
        self.btn_panels_tool.setStyleSheet("font-weight: bold; padding: 3px 6px;")
        toolbar.addWidget(self.btn_panels_tool)

    def createPopupMenu(self) -> QMenu:
        """Ylikirjoitetaan Qt:n vakio kontekstivalikko telakoille ja työkaluille."""
        menu = QMenu("Sivupaneelit", self)
        menu.addAction(self.act_reset_panels)
        menu.addSeparator()
        menu.addAction(self.act_dock_thumb)
        menu.addAction(self.act_dock_editor)
        menu.addAction(self.act_dock_inspector)
        menu.addAction(self.act_dock_shape)
        menu.addAction(self.act_dock_layers)
        return menu

    def reset_dock_layout(self):
        """Palauttaa kaikki 5 telakointipaneelia oletusasetteluun ja tekee niistä näkyviä."""
        self.thumb_dock.show()
        self.editor_dock.show()
        self.inspector_dock.show()
        self.shape_dock.show()
        self.layers_dock.show()

        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.thumb_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.editor_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.inspector_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.shape_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.layers_dock)

        self.tabifyDockWidget(self.inspector_dock, self.shape_dock)
        self.tabifyDockWidget(self.shape_dock, self.layers_dock)

        self.layers_dock.raise_()
        self.status_bar.showMessage("Kaikki sivupaneelit palautettu oletusasetteluun.", 4000)

    def update_action_states(self):
        is_open = self.doc_model.is_open
        page_count = self.doc_model.page_count
        cur_page = self.canvas.current_page_idx

        self.act_save.setEnabled(is_open)
        self.act_save_as.setEnabled(is_open)
        self.act_close.setEnabled(is_open)
        self.act_undo.setEnabled(self.doc_model.can_undo())
        self.act_redo.setEnabled(self.doc_model.can_redo())
        self.act_font_manager.setEnabled(is_open)
        self.act_gauntlet.setEnabled(is_open)
        self.act_prev_page.setEnabled(is_open and cur_page > 0)
        self.act_next_page.setEnabled(is_open and cur_page < page_count - 1)

        # Sivuvalikon ja muotojen tilat
        self.act_batch_pages.setEnabled(is_open)
        self.act_insert_pdf.setEnabled(is_open)
        self.act_insert_blank.setEnabled(is_open)
        self.act_duplicate_page.setEnabled(is_open and page_count > 0)
        self.act_rotate_page.setEnabled(is_open and page_count > 0)
        self.act_delete_page.setEnabled(is_open and page_count > 1)
        self.act_page_margins.setEnabled(is_open)
        self.act_margin_guides.setEnabled(is_open)

        self.act_tool_select.setEnabled(is_open)
        self.act_tool_rect.setEnabled(is_open)
        self.act_tool_round.setEnabled(is_open)
        self.act_tool_circle.setEnabled(is_open)
        self.act_tool_arrow.setEnabled(is_open)
        self.act_tool_line.setEnabled(is_open)
        self.act_add_bg_card.setEnabled(is_open)

        if is_open:
            self.status_file_label.setText(f"Dokumentti: {os.path.basename(self.doc_model.file_path)}")
            self.status_page_label.setText(f"Sivu: {cur_page + 1} / {page_count}")
        else:
            self.status_file_label.setText("Ei tiedostoa avattuna")
            self.status_page_label.setText("Sivu: - / -")

    def open_file(self, file_path: str):
        try:
            self.doc_model.open(file_path)
            self.canvas.set_document(self.doc_model)
            self.thumbnails_bar.set_document(self.doc_model)
            self.layers_widget.set_document(self.doc_model, self.canvas.current_page_idx)
            self.inspector_widget.update_document_details(self.doc_model)
            self.update_action_states()
            self._check_document_fonts()
            if hasattr(self, "shape_widget") and self.shape_widget:
                self.shape_widget.update_available_fonts(self.doc_model.get_document_font_families())
            self.status_bar.showMessage(f"Avattu onnistuneesti: {file_path}", 4000)
        except Exception as e:
            QMessageBox.critical(self, "Virhe tiedoston avauksessa", f"Ei voitu avata PDF-tiedostoa:\n{str(e)}")

    def _check_document_fonts(self):
        """Tarkistaa dokumentin kirjasimet ja näyttää huomautuspalkin tarvittaessa."""
        if not self.doc_model.is_open:
            self.font_banner.setVisible(False)
            return

        fonts = self.doc_model.get_document_fonts_summary()
        uninstalled = [f for f in fonts if not f.get("is_installed", False)]
        if uninstalled:
            unique_names = []
            for f in uninstalled:
                if f["clean_family"] not in unique_names:
                    unique_names.append(f["clean_family"])
            names_str = ", ".join(unique_names[:3])
            if len(unique_names) > 3:
                names_str += f" (+{len(unique_names)-3} muuta)"
            self.banner_label.setText(
                f"⚠️ Dokumentissa on kirjasimia, joita ei ole asennettu koneelle ({names_str}). "
                f"Uusien merkkien muokkaus voi vaatia fonttitiedoston."
            )
            self.font_banner.setVisible(True)
        else:
            self.font_banner.setVisible(False)

    def show_margins_dialog(self):
        """Avaa sivun marginaalien ja arkkikoon hallintadialogin."""
        if not self.doc_model.is_open:
            QMessageBox.information(self, "Marginaalit", "Avaa ensin PDF-dokumentti.")
            return

        dlg = MarginsDialog(self.doc_model, self.canvas.current_page_idx, self)
        dlg.margins_changed.connect(self._on_margins_changed)
        dlg.exec()

    def _on_margins_changed(self):
        """Kutsutaan kun sivun marginaaleja on muutettu."""
        self.canvas.refresh_page()
        self.thumbnails_bar.refresh_thumbnails(keep_selected_page=self.canvas.current_page_idx)
        self.inspector_widget.update_document_details(self.doc_model)
        self.layers_widget.refresh_elements()
        self.update_action_states()
        self.status_bar.showMessage("Sivun marginaalit ja mitat päivitetty.", 3000)

    def _on_shape_drawn(self, data: dict):
        """Kutsutaan kun kankaalle on piirretty muoto tai lisätty taustalaatikko."""
        cur_page = self.canvas.current_page_idx
        self.thumbnails_bar.update_single_thumbnail(cur_page)
        self.inspector_widget.update_document_details(self.doc_model)
        self.layers_widget.refresh_elements()
        self.update_action_states()
        self.status_bar.showMessage(f"Muoto lisätty onnistuneesti sivulle {cur_page + 1}.", 3000)

    def _on_shape_properties_committed(self):
        """Kutsutaan kun muodon ominaisuuksia muokataan reaaliajassa sivupalkista."""
        if not self.doc_model or not self.doc_model.is_open:
            return
        cur_page = self.canvas.current_page_idx
        self.thumbnails_bar.update_single_thumbnail(cur_page)
        self.layers_widget.refresh_elements()
        self.update_action_states()

    def _on_request_focus_shape_text(self, shape_id: str):
        """Aktivoi Muodot & Palikat -paneelin säilyttäen fokuksen kankaan tekstilaatikossa."""
        self.shape_dock.show()
        self.shape_dock.raise_()
        if hasattr(self.canvas, "inline_shape_editor") and self.canvas.inline_shape_editor.isVisible():
            self.canvas.inline_shape_editor.setFocus()

    def _on_shape_selected(self, shape_data: Dict[str, Any]):
        """Kutsutaan kun muoto valitaan kankaalla."""
        self.shape_widget.load_shape_properties(shape_data)
        if shape_data and shape_data.get("id"):
            self.shape_dock.raise_()

    def show_font_manager_dialog(self):
        """Avaa dokumentin kirjasinten hallintaikkunan."""
        if not self.doc_model.is_open:
            QMessageBox.information(self, "Kirjasinhallinta", "Avaa ensin PDF-dokumentti.")
            return

        dlg = FontManagerDialog(self.doc_model, self)
        dlg.fonts_updated.connect(self._on_fonts_updated)
        dlg.exec()

    def _auto_download_missing_fonts(self):
        """Lataa ja ottaa automaattisesti käyttöön dokumentin puuttuvat suositellut kirjasimet."""
        if not self.doc_model.is_open:
            return

        fonts_summary = self.doc_model.get_document_fonts_summary()
        missing = [f for f in fonts_summary if not f.get("is_installed", False) and f.get("rec_id")]
        if not missing:
            QMessageBox.information(
                self,
                "Kaikki kirjasimet kunnossa",
                "Kaikki dokumentin käyttämät kirjasimet tai niiden suositellut avoimet vastineet on jo asennettu!"
            )
            self.font_banner.setVisible(False)
            return

        to_download_names = list(dict.fromkeys([f.get("recommendation", f["clean_family"]) for f in missing]))
        names_bullets = "\n".join(f"• {n}" for n in to_download_names)

        confirm = QMessageBox.question(
            self,
            "Vahvista suositeltujen kirjasinten lataus",
            f"Haluatko noutaa ja ottaa käyttöön seuraavat avoimet vastineet (Google Fonts)?\n\n"
            f"{names_bullets}\n\n"
            f"Tiedostot tallennetaan sovelluksen fonts/-kansioon ja otetaan "
            f"välittömästi käyttöön ilman manuaalisia säätöjä.\n\n"
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
            QMessageBox.information(self, "Kirjasimet päivitetty", msg)
            self._on_fonts_updated()
        else:
            QMessageBox.warning(
                self,
                "Lataus epäonnistui",
                "Kirjasinten automaattinen nouto epäonnistui:\n" + "\n".join(errors)
            )

    def _on_fonts_updated(self):
        """Kutsutaan kun fontti on asennettu tai tuotu dialogista."""
        self._check_document_fonts()
        self.canvas.refresh_page()
        self.inspector_widget.update_document_details(self.doc_model)
        if self.current_block:
            self.editor_widget.set_target_block(self.current_block, self.doc_model)
        elif self.current_span:
            self.editor_widget.set_target_span(self.current_span, self.doc_model)
        if hasattr(self, "shape_widget") and self.shape_widget:
            doc_fonts = self.doc_model.get_document_font_families() if self.doc_model.is_open else []
            self.shape_widget.update_available_fonts(doc_fonts)

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Valitse PDF-tiedosto", "", "PDF-tiedostot (*.pdf)")
        if path:
            self.open_file(path)

    def save_file(self):
        if not self.doc_model.is_open:
            return
        self.save_file_as()

    def save_file_as(self):
        if not self.doc_model.is_open:
            return

        default_path = self.doc_model.file_path.replace(".pdf", "_edited.pdf")
        path, _ = QFileDialog.getSaveFileName(self, "Tallenna PDF", default_path, "PDF-tiedostot (*.pdf)")
        if not path:
            return

        try:
            self.doc_model.save(path)
            self.status_bar.showMessage(f"Tallennettu virheettömästi: {path}", 5000)
            QMessageBox.information(
                self, "Tallennus onnistui",
                f"PDF tallennettu optimoituna puhtaalla XRef-rakenteella:\n{path}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Tallennusvirhe", f"PDF-tallennus epäonnistui:\n{str(e)}")

    def close_file(self):
        self.doc_model.close()
        self.font_banner.setVisible(False)
        self.canvas.set_document(self.doc_model)
        self.thumbnails_bar.set_document(self.doc_model)
        self.layers_widget.set_document(None)
        self.inspector_widget.update_document_details(self.doc_model)
        self.update_action_states()

    def prev_page(self):
        if self.doc_model.is_open and self.canvas.current_page_idx > 0:
            new_idx = self.canvas.current_page_idx - 1
            self.canvas.set_page(new_idx)
            self.thumbnails_bar.select_page(new_idx)
            self.layers_widget.set_page(new_idx)
            self.update_action_states()

    def next_page(self):
        if self.doc_model.is_open and self.canvas.current_page_idx < self.doc_model.page_count - 1:
            new_idx = self.canvas.current_page_idx + 1
            self.canvas.set_page(new_idx)
            self.thumbnails_bar.select_page(new_idx)
            self.layers_widget.set_page(new_idx)
            self.update_action_states()

    def undo(self):
        if self.doc_model.undo():
            self.current_block = None
            self.current_span = None
            self.editor_widget.clear_target()
            self.canvas.clear_selection()
            active_p = min(self.canvas.current_page_idx, max(0, self.doc_model.page_count - 1))
            self.canvas.set_page(active_p)
            self.thumbnails_bar.refresh_thumbnails(keep_selected_page=active_p)
            self.inspector_widget.update_document_details(self.doc_model)
            self.layers_widget.refresh_elements()
            self.update_action_states()
            self.status_bar.showMessage("Muutos kumottu.", 3000)

    def redo(self):
        if self.doc_model.redo():
            self.current_block = None
            self.current_span = None
            self.editor_widget.clear_target()
            self.canvas.clear_selection()
            active_p = min(self.canvas.current_page_idx, max(0, self.doc_model.page_count - 1))
            self.canvas.set_page(active_p)
            self.thumbnails_bar.refresh_thumbnails(keep_selected_page=active_p)
            self.inspector_widget.update_document_details(self.doc_model)
            self.layers_widget.refresh_elements()
            self.update_action_states()
            self.status_bar.showMessage("Muutos tehty uudelleen.", 3000)

    def _set_selection_mode(self, mode: str):
        """Vaihtaa valintatilan (paragraph / span) ja päivittää valikot ja kankaan."""
        self.canvas.set_selection_mode(mode)
        self.editor_widget.set_active_mode(mode)
        self._sync_mode_ui(mode)
        mode_desc = "Kappaletila (Koko lohko)" if mode == "paragraph" else "Rivitila (Yksittäinen rivi)"
        self.status_bar.showMessage(f"Aktiivinen tila: {mode_desc}", 2500)

    def _sync_mode_ui(self, mode: str):
        """Synkronoi valikoiden ja painikkeiden tilan."""
        self.act_mode_paragraph.blockSignals(True)
        self.act_mode_span.blockSignals(True)
        self.act_mode_paragraph.setChecked(mode == "paragraph")
        self.act_mode_span.setChecked(mode == "span")
        self.act_mode_paragraph.blockSignals(False)
    def _on_text_selected(self, selected_text: str):
        """Kutsutaan kun tekstiä valitaan kankaalta hiirellä mustamaalaamalla tai tuplaklikkaamalla."""
        clean = " ".join(selected_text.split())
        if len(clean) > 40:
            clean = clean[:37] + "..."
        self.status_bar.showMessage(f"Valittu teksti: '{clean}' ({len(selected_text)} merkkiä)", 3500)

    def _focus_editor(self):
        """Kohdistaa kursorin tekstieditorin syöttökenttään ja korostaa valitun sanan."""
        self.editor_dock.raise_()
        self.editor_widget.input_edit.setFocus()
        if self.canvas.selected_text:
            doc = self.editor_widget.input_edit.document()
            target_word = self.canvas.selected_text.strip().split()[0] if self.canvas.selected_text.strip() else ""
            if target_word:
                cursor = doc.find(target_word)
                if not cursor.isNull():
                    self.editor_widget.input_edit.setTextCursor(cursor)

    def _toggle_bold(self):
        self.editor_widget.toggle_bold()

    def _toggle_italic(self):
        self.editor_widget.toggle_italic()

    def _set_editor_fontsize(self, size: float):
        self.editor_widget.set_fontsize(size)

    def _paste_into_editor(self, text: str):
        self.editor_dock.raise_()
        self.editor_widget.input_edit.setFocus()
        self.editor_widget.input_edit.insertPlainText(text)

    def _delete_selected_text(self):
        if not self.canvas.selected_text:
            return
        cur_txt = self.editor_widget.input_edit.toPlainText()
        if self.canvas.selected_text in cur_txt:
            new_txt = cur_txt.replace(self.canvas.selected_text, "", 1)
            self.editor_widget.input_edit.setPlainText(new_txt)
            self.canvas.clear_selection()
            self.status_bar.showMessage("Valittu teksti poistettu.", 2500)

    def _delete_selected_block(self, block: Dict[str, Any]):
        self.editor_widget.input_edit.setPlainText("")
        self.canvas.clear_selection()
        self.status_bar.showMessage("Kappaleen teksti tyhjennetty.", 2500)

    def _on_block_selected(self, block: Dict[str, Any]):
        """Kutsutaan kun kokonainen kappale/lohko on valittu kankaalta."""
        self.current_block = block
        self.current_span = None
        self.editor_widget.set_target_block(block, self.doc_model)
        font_match = self.editor_widget.active_font_match
        self.inspector_widget.update_block_details(block, font_match)

    def _on_span_selected(self, span: Dict[str, Any]):
        self.current_span = span
        self.current_block = None
        self.editor_widget.set_target_span(span, self.doc_model)
        font_match = self.editor_widget.active_font_match
        self.inspector_widget.update_span_details(span, font_match)

    def _on_block_edit_committed(
        self,
        block: Dict[str, Any],
        new_text: str,
        font_match: FontMatchResult,
        strategy: FitStrategy,
        custom_size: Optional[float],
        custom_color: Optional[tuple]
    ):
        """
        Korvaa kokonaisen kappaleen ja PYSYY nykyisellä sivulla ilman hyppyjä alkuun!
        """
        try:
            target_page_idx = self.canvas.current_page_idx
            custom_w = block.get("max_width")
            op = self.doc_model.replace_block_inplace(
                page_idx=target_page_idx,
                block=block,
                new_text=new_text,
                font_match=font_match,
                custom_fontsize=custom_size,
                custom_color=custom_color,
                custom_max_width=custom_w
            )

            # Päivitetään kankaan nykyinen sivu
            self.canvas.refresh_page()

            # Päivitetään VAIN kyseisen sivun pikkukuva, eikä nollata pikkukuvapalkkia!
            self.thumbnails_bar.update_single_thumbnail(target_page_idx)
            self.thumbnails_bar.select_page(target_page_idx)
            self.layers_widget.refresh_elements()

            self.update_action_states()
            self.status_bar.showMessage(
                f"Kappale korvattu onnistuneesti sivulla {target_page_idx + 1}.", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "Muokkausvirhe", f"Kappaleen korvaus epäonnistui:\n{str(e)}")

    def _on_edit_committed(
        self,
        span: Dict[str, Any],
        new_text: str,
        font_match: FontMatchResult,
        strategy: FitStrategy,
        custom_size: Optional[float],
        custom_color: Optional[tuple]
    ):
        """
        Korvaa tekstin ja PYSYY nykyisellä sivulla ilman hyppyjä alkuun!
        """
        try:
            target_page_idx = self.canvas.current_page_idx
            op = self.doc_model.replace_text_inplace(
                page_idx=target_page_idx,
                span=span,
                new_text=new_text,
                font_match=font_match,
                strategy=strategy,
                custom_fontsize=custom_size,
                custom_color=custom_color
            )

            # Päivitetään kankaan nykyinen sivu
            self.canvas.refresh_page()

            # Päivitetään VAIN kyseisen sivun pikkukuva, eikä nollata pikkukuvapalkkia!
            self.thumbnails_bar.update_single_thumbnail(target_page_idx)
            self.thumbnails_bar.select_page(target_page_idx)
            self.layers_widget.refresh_elements()

            self.update_action_states()
            self.status_bar.showMessage(
                f"Teksti korvattu onnistuneesti kohdassa ({op.origin[0]:.1f}, {op.origin[1]:.1f}) pt.", 4000
            )
        except Exception as e:
            QMessageBox.critical(self, "Muokkausvirhe", f"Tekstin korvaus epäonnistui:\n{str(e)}")

    def _on_page_navigated(self, page_idx: int):
        self.canvas.set_page(page_idx)
        self.layers_widget.set_page(page_idx)
        self.update_action_states()

    def _on_page_structure_changed(self, new_active_page: int):
        """Kutsutaan kun sivuja on lisätty, poistettu, siirretty tai kierretty."""
        if self.doc_model.is_open:
            valid_page = max(0, min(new_active_page, self.doc_model.page_count - 1))
            self.canvas.set_page(valid_page)
            self.thumbnails_bar.select_page(valid_page)
            self.layers_widget.set_page(valid_page)
            self.inspector_widget.update_document_details(self.doc_model)
            self.update_action_states()
            self.status_bar.showMessage("Sivurakenne päivitetty onnistuneesti.", 3000)

    def menu_batch_pages(self):
        """Avaa sivujen hallinta- ja erätoimintodialogin."""
        if not self.doc_model.is_open:
            return
        self.thumbnails_bar.open_batch_dialog()

    def menu_insert_pdf(self):
        if not self.doc_model.is_open:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Valitse liitettävä PDF-tiedosto", "", "PDF-tiedostot (*.pdf)"
        )
        if path:
            target_idx = self.canvas.current_page_idx + 1
            try:
                count = self.doc_model.insert_pdf_pages(path, at_idx=target_idx)
                self.thumbnails_bar.refresh_thumbnails(keep_selected_page=target_idx)
                self._on_page_structure_changed(target_idx)
                QMessageBox.information(self, "PDF Liitetty", f"Liitettiin {count} sivua tiedostosta:\n{os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Virhe", f"Liittäminen epäonnistui: {str(e)}")

    def menu_insert_blank_page(self):
        if not self.doc_model.is_open:
            return
        target_idx = self.canvas.current_page_idx + 1
        self.doc_model.insert_blank_page(target_idx)
        self.thumbnails_bar.refresh_thumbnails(keep_selected_page=target_idx)
        self._on_page_structure_changed(target_idx)

    def menu_duplicate_page(self):
        if not self.doc_model.is_open:
            return
        target_idx = self.canvas.current_page_idx
        self.doc_model.duplicate_page(target_idx)
        self.thumbnails_bar.refresh_thumbnails(keep_selected_page=target_idx + 1)
        self._on_page_structure_changed(target_idx + 1)

    def menu_rotate_page(self):
        if not self.doc_model.is_open:
            return
        cur_page = self.canvas.current_page_idx
        self.doc_model.rotate_page(cur_page, 90)
        self.canvas.refresh_page()
        self.thumbnails_bar.update_single_thumbnail(cur_page)
        self.inspector_widget.update_document_details(self.doc_model)
        self.update_action_states()
        self.status_bar.showMessage(f"Sivu {cur_page + 1} kierretty 90°.", 2500)

    def menu_delete_page(self):
        if not self.doc_model.is_open or self.doc_model.page_count <= 1:
            return
        cur_page = self.canvas.current_page_idx
        ret = QMessageBox.question(
            self, "Vahvista sivun poisto",
            f"Haluatko varmasti poistaa sivun {cur_page + 1}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if ret == QMessageBox.StandardButton.Yes:
            if self.doc_model.delete_page(cur_page):
                new_idx = min(cur_page, self.doc_model.page_count - 1)
                self.thumbnails_bar.refresh_thumbnails(keep_selected_page=new_idx)
                self._on_page_structure_changed(new_idx)

    def _on_zoom_changed(self, zoom: float):
        self.status_zoom_label.setText(f"Zoom: {int(zoom * 100)} %")

    def run_gauntlet_audit(self):
        """Suorittaa täyden Gauntlet Loop -laadunvarmistuksen nykyiselle dokumentille."""
        if not self.doc_model.is_open:
            return

        temp_audit_path = "/tmp/gauntlet_audit_temp.pdf"
        try:
            self.doc_model.save(temp_audit_path)
            report = GauntletValidator.audit_document(
                temp_audit_path,
                operations=self.doc_model.operations_history
            )
            dlg = GauntletReportDialog(report, self)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Audit-virhe", f"Gauntlet-auditointi epäonnistui:\n{str(e)}")
        finally:
            if os.path.exists(temp_audit_path):
                try:
                    os.remove(temp_audit_path)
                except Exception:
                    pass
