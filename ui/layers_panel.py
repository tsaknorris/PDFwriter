"""
Tasot & Objektit -hallintapaneeli (Layers & Objects Panel).
Tarjoaa visuaalisen pinojärjestyksen (Z-Order) ja elementtiluettelon aktiiviselle sivulle:
- Tekstin päällä olevat muodot (Over Text)
- Sivun tekstilohkot ja kappaleet (Text elements)
- Tekstin alla olevat muodot ja taustakortit (Behind Text)
- Objektien ryhmittely (Group/Ungroup), tasonvaihto, näkyvyys (👁️) ja poisto (🗑️).
"""

from typing import Optional, List, Dict, Any
from PyQt6.QtCore import Qt, pyqtSignal, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QToolBar, QPushButton, QLabel, QInputDialog, QMenu, QHeaderView,
    QAbstractItemView
)
from PyQt6.QtGui import QIcon, QFont, QColor, QBrush, QAction, QKeySequence

from pdf_engine.pdf_document import PDFDocumentModel


class LayersPanel(QWidget):
    """
    Telakoituva paneeli, joka näyttää sivun kaikki elementit selkeänä hierarkiana.
    Mahdollistaa minkä tahansa objektin valinnan, vaikka se sijaitsisi 100 % tekstin takana.
    """

    # Signaalit
    element_selected = pyqtSignal(str, str)  # (elem_id, elem_type: "shape"|"text")
    elements_grouped = pyqtSignal(list)      # list of shape_ids
    group_ungrouped = pyqtSignal(str)        # group_id
    element_reordered = pyqtSignal(str, str) # (elem_id, action)
    element_deleted = pyqtSignal(str, str)   # (elem_id, elem_type)
    visibility_toggled = pyqtSignal(str, bool) # (elem_id, is_visible)
    request_canvas_refresh = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.doc_model: Optional[PDFDocumentModel] = None
        self.current_page_idx: int = 0
        self._is_updating: bool = False

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # 1. Otsikko ja toimintorivi
        header_layout = QHBoxLayout()
        self.lbl_title = QLabel("📚 Tasot & Objektit (Z-Order)")
        self.lbl_title.setStyleSheet("font-weight: bold; color: #f8fafc; font-size: 12px;")
        header_layout.addWidget(self.lbl_title)
        header_layout.addStretch()

        self.btn_refresh = QPushButton("🔄")
        self.btn_refresh.setToolTip("Päivitä tasoluettelo")
        self.btn_refresh.setFixedSize(26, 24)
        self.btn_refresh.clicked.connect(self.refresh_elements)
        header_layout.addWidget(self.btn_refresh)
        layout.addLayout(header_layout)

        # 2. Työkalupainikkeet (Move up/down, Behind/Over text, Group/Ungroup, Delete)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)

        self.btn_vis = QPushButton("👁️")
        self.btn_vis.setToolTip("Näytä / Piilota valittu muoto")
        self.btn_vis.setFixedSize(28, 26)
        self.btn_vis.clicked.connect(self._toggle_selected_visibility)
        toolbar.addWidget(self.btn_vis)

        self.btn_up = QPushButton("🔼")
        self.btn_up.setToolTip("Siirrä ylemmäs pinossa (Move Up)")
        self.btn_up.setFixedSize(28, 26)
        self.btn_up.clicked.connect(lambda: self._reorder_selected("move_up"))
        toolbar.addWidget(self.btn_up)

        self.btn_down = QPushButton("🔽")
        self.btn_down.setToolTip("Siirrä alemmas pinossa (Move Down)")
        self.btn_down.setFixedSize(28, 26)
        self.btn_down.clicked.connect(lambda: self._reorder_selected("move_down"))
        toolbar.addWidget(self.btn_down)

        self.btn_toggle_layer = QPushButton("🔄 Taso")
        self.btn_toggle_layer.setToolTip("Vaihda tilaa: Tekstin alle ⇄ Tekstin päälle")
        self.btn_toggle_layer.setFixedHeight(26)
        self.btn_toggle_layer.clicked.connect(self._toggle_layer_placement)
        toolbar.addWidget(self.btn_toggle_layer)

        self.btn_group = QPushButton("🔗")
        self.btn_group.setToolTip("Ryhmittele valitut muodot (Group - Ctrl+G)")
        self.btn_group.setFixedSize(28, 26)
        self.btn_group.clicked.connect(self._group_selected)
        toolbar.addWidget(self.btn_group)

        self.btn_ungroup = QPushButton("🔓")
        self.btn_ungroup.setToolTip("Pura ryhmä (Ungroup - Ctrl+Shift+G)")
        self.btn_ungroup.setFixedSize(28, 26)
        self.btn_ungroup.clicked.connect(self._ungroup_selected)
        toolbar.addWidget(self.btn_ungroup)

        self.btn_delete = QPushButton("🗑️")
        self.btn_delete.setToolTip("Poista valittu muoto (Delete)")
        self.btn_delete.setFixedSize(28, 26)
        self.btn_delete.setStyleSheet("color: #f87171; font-weight: bold;")
        self.btn_delete.clicked.connect(self._delete_selected)
        toolbar.addWidget(self.btn_delete)

        layout.addLayout(toolbar)

        # 3. Puurakenne tasoille ja elementeille
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Elementti", "Tila"])
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._show_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_item_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)
        
        # Sarakkeiden leveydet
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)

        self.tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid #4a4a58;
                border-radius: 4px;
                background-color: #16161a;
                alternate-background-color: #202026;
                color: #f8fafc;
                font-size: 11px;
            }
            QTreeWidget::item {
                padding: 4px;
                color: #f8fafc;
                border-bottom: 1px solid #282834;
            }
            QTreeWidget::item:hover {
                background-color: #2e3848;
                color: #ffffff;
            }
            QTreeWidget::item:selected {
                background-color: #0284c7;
                color: #ffffff;
                font-weight: bold;
            }
        """)

        layout.addWidget(self.tree)

        # 4. Alapalkin tila / opastus
        self.lbl_info = QLabel("Vihje: Klikkaa objektia listalta valitaksesi sen tekstin takaa.")
        self.lbl_info.setStyleSheet("color: #cbd5e1; font-size: 10px; font-style: italic;")
        self.lbl_info.setWordWrap(True)
        layout.addWidget(self.lbl_info)

    def set_document(self, doc_model: Optional[PDFDocumentModel], page_idx: int = 0):
        """Asettaa aktiivisen dokumentin ja sivun."""
        self.doc_model = doc_model
        self.current_page_idx = page_idx
        self.refresh_elements()

    def set_page(self, page_idx: int):
        """Päivittää aktiivisen sivun indeksin."""
        self.current_page_idx = page_idx
        self.refresh_elements()

    def refresh_elements(self):
        """Lukee sivun elementit dokumenttimallista ja päivittää puunäkymän."""
        if not self.doc_model or not self.doc_model.is_open:
            self.tree.clear()
            self.lbl_title.setText("📚 Tasot & Objektit (Ei dokumenttia)")
            return

        self._is_updating = True
        self.tree.clear()

        elements = self.doc_model.get_page_elements(self.current_page_idx)
        self.lbl_title.setText(f"📚 Tasot & Objektit (Sivu {self.current_page_idx + 1})")

        # 1. Pääkategoriat (Section headers)
        item_over = QTreeWidgetItem(["🔼 Tekstin päällä (Over Text)", ""])
        item_over.setFont(0, QFont("Sans", 9, QFont.Weight.Bold))
        item_over.setForeground(0, QBrush(QColor("#38bdf8")))
        item_over.setFlags(item_over.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        item_text = QTreeWidgetItem(["📄 Tekstilohkot & Kappaleet", ""])
        item_text.setFont(0, QFont("Sans", 9, QFont.Weight.Bold))
        item_text.setForeground(0, QBrush(QColor("#4ade80")))
        item_text.setFlags(item_text.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        item_behind = QTreeWidgetItem(["🔽 Tekstin alla (Behind Text / Tausta)", ""])
        item_behind.setFont(0, QFont("Sans", 9, QFont.Weight.Bold))
        item_behind.setForeground(0, QBrush(QColor("#c084fc")))
        item_behind.setFlags(item_behind.flags() & ~Qt.ItemFlag.ItemIsSelectable)

        self.tree.addTopLevelItem(item_over)
        self.tree.addTopLevelItem(item_text)
        self.tree.addTopLevelItem(item_behind)

        # Apurakenne ryhmille
        group_items: Dict[str, QTreeWidgetItem] = {}

        type_icons = {
            "rect": "🔲",
            "rounded_rect": "◽",
            "circle": "🔵",
            "oval": "🥚",
            "arrow": "➡️",
            "line": "➖",
            "text": "📄"
        }

        for elem in elements:
            layer = elem.get("layer", "over_text")
            el_type = elem.get("type", "rect")
            el_id = elem.get("id", "")
            el_name = elem.get("name", "Nimetön")
            visible = elem.get("visible", True)
            group_id = elem.get("group_id")

            icon_char = type_icons.get(el_type, "🔹")
            vis_str = "👁️" if visible else "🚫"
            label = f"{icon_char}  {el_name}"

            item = QTreeWidgetItem([label, vis_str])
            item.setData(0, Qt.ItemDataRole.UserRole, elem)

            # Sijoitus kategoriaan
            parent_category = item_over
            if layer == "behind_text":
                parent_category = item_behind
            elif layer == "text":
                parent_category = item_text

            # Jos elementti kuuluu ryhmään
            if group_id and el_type != "text":
                if group_id not in group_items:
                    g_item = QTreeWidgetItem([f"📁 Ryhmä ({group_id})", "🔗"])
                    g_item.setFont(0, QFont("Sans", 9, QFont.Weight.DemiBold))
                    g_item.setData(0, Qt.ItemDataRole.UserRole, {"id": group_id, "type": "group"})
                    parent_category.addChild(g_item)
                    group_items[group_id] = g_item
                group_items[group_id].addChild(item)
            else:
                parent_category.addChild(item)

        # Avataan kaikki kategoriat oletuksena
        self.tree.expandAll()
        self._is_updating = False

    def select_item_by_id(self, elem_id: Optional[str]):
        """Valitsee vastaavan puunäkymän elementin kankaalta tulleen valinnan mukaan."""
        if not elem_id or self._is_updating:
            return

        self._is_updating = True
        self.tree.clearSelection()

        def search_item(parent_item):
            for i in range(parent_item.childCount()):
                child = parent_item.child(i)
                data = child.data(0, Qt.ItemDataRole.UserRole)
                if data and data.get("id") == elem_id:
                    child.setSelected(True)
                    self.tree.scrollToItem(child)
                    return True
                if search_item(child):
                    return True
            return False

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if search_item(top):
                break

        self._is_updating = False

    def _on_item_selection_changed(self):
        """Käyttäjä valitsi elementin puusta -> ilmoitetaan kankaalle."""
        if self._is_updating:
            return

        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        item = selected_items[0]
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        elem_id = data.get("id")
        elem_type = data.get("type")
        if elem_id and elem_type:
            self.element_selected.emit(elem_id, elem_type)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Tuplaklikkaus nimeää muodon uudelleen."""
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data or data.get("type") == "text":
            return

        elem_id = data.get("id")
        current_name = data.get("name", "")
        new_name, ok = QInputDialog.getText(self, "Nimeä objekti", "Anna objektille uusi nimi:", text=current_name)
        if ok and new_name.strip() and self.doc_model:
            self.doc_model.update_shape(self.current_page_idx, elem_id, name=new_name.strip())
            self.refresh_elements()
            self.request_canvas_refresh.emit()

    def _get_selected_shape_ids(self) -> List[str]:
        """Palauttaa kaikkien puussa valittujen muotojen ID:t."""
        ids = []
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") not in ("text", "group"):
                ids.append(data.get("id"))
            elif data and data.get("type") == "group":
                # Jos koko ryhmä on valittuna, lisätään kaikki sen lapset
                for j in range(item.childCount()):
                    c_data = item.child(j).data(0, Qt.ItemDataRole.UserRole)
                    if c_data and c_data.get("id"):
                        ids.append(c_data.get("id"))
        return list(set(ids))

    def _toggle_selected_visibility(self):
        """Kytkee valitun muodon näkyvyyden päälle/pois (👁️)."""
        shape_ids = self._get_selected_shape_ids()
        if not shape_ids or not self.doc_model:
            return
        for s_id in shape_ids:
            shape = self.doc_model.get_shape(self.current_page_idx, s_id)
            if shape:
                new_vis = not shape.get("visible", True)
                self.doc_model.update_shape(self.current_page_idx, s_id, visible=new_vis)
        self.refresh_elements()
        self.request_canvas_refresh.emit()

    def _reorder_selected(self, action: str):
        """Siirtää valittua muotoa ylemmäs tai alemmas pinossa."""
        shape_ids = self._get_selected_shape_ids()
        if not shape_ids or not self.doc_model:
            return
        for s_id in shape_ids:
            self.doc_model.reorder_shape(self.current_page_idx, s_id, action)
        self.refresh_elements()
        self.request_canvas_refresh.emit()

    def _toggle_layer_placement(self):
        """Siirtää valitun muodon tekstin alle (Behind) tai tekstin päälle (Over)."""
        shape_ids = self._get_selected_shape_ids()
        if not shape_ids or not self.doc_model:
            return
        for s_id in shape_ids:
            shape = self.doc_model.get_shape(self.current_page_idx, s_id)
            if shape:
                cur_overlay = shape.get("overlay", True)
                action = "behind_text" if cur_overlay else "over_text"
                self.doc_model.reorder_shape(self.current_page_idx, s_id, action)
        self.refresh_elements()
        self.request_canvas_refresh.emit()

    def _group_selected(self):
        """Ryhmittelee valitut vähintään kaksi muotoa (Ctrl+G)."""
        shape_ids = self._get_selected_shape_ids()
        if len(shape_ids) < 2 or not self.doc_model:
            return
        group_id = self.doc_model.group_shapes(self.current_page_idx, shape_ids)
        if group_id:
            self.refresh_elements()
            self.request_canvas_refresh.emit()
            self.elements_grouped.emit(shape_ids)

    def _ungroup_selected(self):
        """Purkaa valitun ryhmän tai valitun muodon ryhmän (Ctrl+Shift+G)."""
        if not self.doc_model:
            return
        # Tarkistetaan onko suoraan ryhmäkansio valittuna
        for item in self.tree.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if data and data.get("type") == "group":
                g_id = data.get("id")
                self.doc_model.ungroup_shapes(self.current_page_idx, g_id)
                self.refresh_elements()
                self.request_canvas_refresh.emit()
                self.group_ungrouped.emit(g_id)
                return

        # Muussa tapauksessa katsotaan valitun muodon group_id
        shape_ids = self._get_selected_shape_ids()
        for s_id in shape_ids:
            shape = self.doc_model.get_shape(self.current_page_idx, s_id)
            if shape and shape.get("group_id"):
                g_id = shape["group_id"]
                self.doc_model.ungroup_shapes(self.current_page_idx, g_id)
                self.refresh_elements()
                self.request_canvas_refresh.emit()
                self.group_ungrouped.emit(g_id)
                return

    def _delete_selected(self):
        """Poistaa valitut muodot sivulta."""
        shape_ids = self._get_selected_shape_ids()
        if not shape_ids or not self.doc_model:
            return
        self.doc_model.delete_shapes(self.current_page_idx, shape_ids)
        self.refresh_elements()
        self.request_canvas_refresh.emit()

    def _show_context_menu(self, pos):
        """Hiiren oikean painikkeen pikavalikko listakohteelle."""
        item = self.tree.itemAt(pos)
        if not item:
            return

        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return

        el_type = data.get("type")
        el_id = data.get("id")

        menu = QMenu(self)

        if el_type != "text" and el_type != "group":
            act_rename = menu.addAction("✏️  Nimeä uudelleen...")
            act_rename.triggered.connect(lambda: self._on_item_double_clicked(item, 0))

            menu.addSeparator()

            act_vis = menu.addAction("👁️  Näytä / Piilota")
            act_vis.triggered.connect(self._toggle_selected_visibility)

            act_up = menu.addAction("🔼  Siirrä ylemmäs")
            act_up.triggered.connect(lambda: self._reorder_selected("move_up"))

            act_down = menu.addAction("🔽  Siirrä alemmas")
            act_down.triggered.connect(lambda: self._reorder_selected("move_down"))

            act_layer = menu.addAction("🔄  Vaihda tekstin alle / päälle")
            act_layer.triggered.connect(self._toggle_layer_placement)

            menu.addSeparator()

            if len(self._get_selected_shape_ids()) >= 2:
                act_grp = menu.addAction("🔗  Ryhmittele (Ctrl+G)")
                act_grp.triggered.connect(self._group_selected)

            shape = self.doc_model.get_shape(self.current_page_idx, el_id) if self.doc_model else None
            if shape and shape.get("group_id"):
                act_ungrp = menu.addAction("🔓  Pura ryhmä (Ctrl+Shift+G)")
                act_ungrp.triggered.connect(self._ungroup_selected)

            act_del = menu.addAction("🗑️  Poista objekti")
            act_del.triggered.connect(self._delete_selected)

        elif el_type == "group":
            act_ungrp = menu.addAction("🔓  Pura ryhmä (Ctrl+Shift+G)")
            act_ungrp.triggered.connect(self._ungroup_selected)

            act_del = menu.addAction("🗑️  Poista koko ryhmä")
            act_del.triggered.connect(self._delete_selected)

        menu.exec(self.tree.mapToGlobal(pos))
