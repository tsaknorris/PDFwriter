"""
Interaktiivinen sivun renderöintialusta (PDF Page Canvas).
Tukee HiDPI-skaalausta, kursorin hover-tunnistusta, tekstialkioiden valintaa,
perusviivan (baseline) visualisointia ja sulavaa zoomausta.
"""

from typing import Optional, Dict, Any, List, Tuple
import fitz
import math
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal
from PyQt6.QtGui import (
    QImage, QPixmap, QPainter, QColor, QPen, QBrush, QWheelEvent, QMouseEvent,
    QKeyEvent, QContextMenuEvent, QKeySequence, QGuiApplication, QPolygonF
)
from PyQt6.QtWidgets import QWidget, QMenu, QPlainTextEdit

from pdf_engine.pdf_document import PDFDocumentModel


class InlineShapeEditor(QPlainTextEdit):
    """Kankaalla kelluva suora tekstinsyöttöeditori muodoille ja tekstilaatikoille."""
    escape_pressed = pyqtSignal()
    commit_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setPlaceholderText("Kirjoita teksti tähän...")
        self.setStyleSheet(
            "background-color: #1e1e24; color: #f8fafc; border: 2px solid #38bdf8; border-radius: 4px; padding: 4px; font-size: 13px;"
        )

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            self.commit_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class PDFPageCanvas(QWidget):
    """
    Sivun interaktiivinen piirtoalusta.
    Tukee sekä kokonaisten kappaleiden (Paragraph Mode) että tarkkojen tekstijaksojen (Span Mode)
    valintaa, visualisointia ja muokkausta.
    Tukee Word- ja Acrobat-tasoista tekstin mustamaalausta (drag-selection),
    tuplaklikkausta ja monipuolista hiiren oikean napin kontekstivalikkoa.
    Tukee graafisten muotojen (suorakulmio, pyöristetty, ympyrä, nuoli, viiva, tekstilaatikko) piirtoa tekstin päälle tai alle.
    """

    block_selected = pyqtSignal(dict)
    span_selected = pyqtSignal(dict)
    block_geometry_changed = pyqtSignal(dict)
    zoom_changed = pyqtSignal(float)
    mode_changed = pyqtSignal(str)
    text_selected = pyqtSignal(str)
    request_edit = pyqtSignal()
    request_font_manager = pyqtSignal()
    request_bold = pyqtSignal()
    request_italic = pyqtSignal()
    request_fontsize = pyqtSignal(float)
    request_delete_text = pyqtSignal()
    request_delete_block = pyqtSignal(dict)
    request_paste = pyqtSignal(str)
    request_undo = pyqtSignal()
    request_redo = pyqtSignal()
    shape_drawn = pyqtSignal(dict)
    request_margins_dialog = pyqtSignal()
    shape_selected = pyqtSignal(dict)
    element_selected = pyqtSignal(dict)
    tool_switched = pyqtSignal(str)
    request_focus_shape_text = pyqtSignal(str)
    shape_properties_committed = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.doc_model: Optional[PDFDocumentModel] = None
        self.current_page_idx: int = 0
        self.zoom_factor: float = 1.5  # Perusskaalaus (HiDPI)
        self.selection_mode: str = "paragraph"  # "paragraph" (oletus) tai "span"
        
        self.page_pixmap: Optional[QPixmap] = None
        self.spans: List[Dict[str, Any]] = []
        self.blocks: List[Dict[str, Any]] = []
        
        self.selected_span: Optional[Dict[str, Any]] = None
        self.hover_span: Optional[Dict[str, Any]] = None
        self.selected_block: Optional[Dict[str, Any]] = None
        self.hover_block: Optional[Dict[str, Any]] = None

        # Sanat ja tekstitason valinta (Word-like text selection / mustamaalaus)
        self.page_words: List[Tuple] = []
        self.is_selecting_text: bool = False
        self.select_start_pos: QPointF = QPointF()
        self.current_mouse_pos: QPointF = QPointF()
        self.selected_text: str = ""
        self.selected_text_rects: List[QRectF] = []
        self.selected_words: List[Tuple] = []
        self.mouse_pressed: bool = False

        # Interaktiivinen koonmuutostila (kulmista ja reunoista raahaaminen)
        self.is_resizing: bool = False
        self.active_handle: Optional[str] = None
        self.resize_start_pos = QPointF()
        self.resize_start_bbox: List[float] = []

        # Panikointitila (raahaaminen)
        self.is_panning: bool = False
        self.pan_start_pos = QPointF()

        # Muototyökalut & Piirto
        self.active_tool: str = "move"  # "move" (oletus), "select", "rect", "rounded_rect", "circle", "arrow", "line"
        self.show_margin_guides: bool = True
        self.shape_has_fill: bool = True
        self.shape_fill_color: Optional[Tuple[float, float, float]] = (0.93, 0.95, 0.98)
        self.shape_fill_opacity: float = 0.85
        self.shape_stroke_color: Optional[Tuple[float, float, float]] = (0.2, 0.4, 0.7)
        self.shape_stroke_opacity: float = 1.0
        self.shape_stroke_width: float = 1.5
        self.shape_radius: float = 8.0
        self.shape_overlay: bool = False  # Oletuksena tekstin alle (Behind Text)!
        self.is_drawing_shape: bool = False
        self.shape_start_pos: QPointF = QPointF()
        self.shape_current_pos: QPointF = QPointF()

        # Valittu muoto (Shape selection & manipulation)
        self.selected_shape_id: Optional[str] = None
        self.is_dragging_shape: bool = False
        self.drag_shape_start_pos: QPointF = QPointF()
        self.drag_shape_delta: Tuple[float, float] = (0.0, 0.0)
        self.is_resizing_shape: bool = False
        self.resize_shape_handle: Optional[str] = None
        self.resize_shape_start_geom: Any = None

        # Vapaa kierto (Free Rotation)
        self.shape_rotation: float = 0.0
        self.is_rotating_shape: bool = False
        self.rotate_start_angle: float = 0.0
        self.rotate_start_pos: QPointF = QPointF()
        self.rotate_center: QPointF = QPointF()

        # Tekstiominaisuudet (Muotojen sisäinen teksti & Textbox)
        self.shape_text: str = ""
        self.shape_font_family: str = "Helvetica"
        self.shape_font_size: float = 14.0
        self.shape_font_bold: bool = False
        self.shape_font_italic: bool = False
        self.shape_text_color: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.shape_text_align: str = "center"
        self.shape_vertical_align: str = "middle"

        # Kelluva in-canvas tekstieditori
        self.inline_shape_editor = InlineShapeEditor(self)
        self.inline_shape_editor.hide()
        self.inline_shape_editor.escape_pressed.connect(lambda: self.finish_inline_shape_editor(commit=False))
        self.inline_shape_editor.commit_requested.connect(lambda: self.finish_inline_shape_editor(commit=True))
        self.inline_shape_editor.textChanged.connect(self._on_inline_shape_text_changed)
        self._active_inline_shape_id: Optional[str] = None
        self._syncing_inline_editor: bool = False

    def start_inline_shape_editor(self, shape_id: str):
        """Käynnistää kankaalla kelluvan tekstieditorin suoraan muodon päällä."""
        if not self.doc_model or not shape_id:
            return
        shape = self.doc_model.get_shape(self.current_page_idx, shape_id)
        if not shape:
            return
        self._active_inline_shape_id = shape_id
        bbox = self.doc_model._compute_shape_bbox(shape)
        x = bbox[0] * self.zoom_factor
        y = bbox[1] * self.zoom_factor
        w = max(70.0, (bbox[2] - bbox[0]) * self.zoom_factor)
        h = max(36.0, (bbox[3] - bbox[1]) * self.zoom_factor)

        self._syncing_inline_editor = True
        try:
            self.inline_shape_editor.setGeometry(int(x), int(y), int(w), int(h))
            self.inline_shape_editor.setPlainText(shape.get("text", ""))
        finally:
            self._syncing_inline_editor = False

        self.inline_shape_editor.show()
        self.inline_shape_editor.setFocus()
        self.inline_shape_editor.selectAll()

    def finish_inline_shape_editor(self, commit: bool = True):
        """Sulkee kankaan kelluvan tekstieditorin ja tallentaa muutoksen."""
        if not self.inline_shape_editor.isVisible() or not self._active_inline_shape_id:
            return
        target_id = self._active_inline_shape_id
        new_text = self.inline_shape_editor.toPlainText()
        self.inline_shape_editor.hide()
        self._active_inline_shape_id = None
        if commit and self.doc_model:
            self.doc_model.update_shape(self.current_page_idx, target_id, text=new_text, push_undo=True)
            self.refresh_page()
            shape_data = self.doc_model.get_shape(self.current_page_idx, target_id)
            if shape_data:
                self.shape_selected.emit(shape_data)
            self.shape_properties_committed.emit()
        self.setFocus()
        self.update()

    def _on_inline_shape_text_changed(self):
        if self._syncing_inline_editor or not self._active_inline_shape_id or not self.doc_model:
            return
        new_text = self.inline_shape_editor.toPlainText()
        self.doc_model.update_shape(self.current_page_idx, self._active_inline_shape_id, text=new_text, push_undo=False)
        shape_data = self.doc_model.get_shape(self.current_page_idx, self._active_inline_shape_id)
        if shape_data:
            self.shape_selected.emit(shape_data)

    def _constrain_shape_point(self, p_start: QPointF, p_cur: QPointF, shape_type: str) -> QPointF:
        """
        Pakottaa muodon kuvasuhteen kiinteäksi (Ctrl / Shift pohjassa):
        - circle, rect, rounded_rect: 1:1 suhde (neliö / täydellinen ympyrä)
        - arrow, line: 45 asteen kulmalukitus (0, 45, 90, 135, 180 astetta)
        """
        dx = p_cur.x() - p_start.x()
        dy = p_cur.y() - p_start.y()

        if shape_type in ("circle", "oval", "rect", "rounded_rect"):
            s = max(abs(dx), abs(dy))
            sx = 1.0 if dx >= 0 else -1.0
            sy = 1.0 if dy >= 0 else -1.0
            return QPointF(p_start.x() + sx * s, p_start.y() + sy * s)

        elif shape_type in ("arrow", "line"):
            length = math.hypot(dx, dy)
            if length < 1.0:
                return p_cur
            angle = math.atan2(dy, dx)
            step = math.pi / 4.0  # 45 astetta
            snapped_angle = round(angle / step) * step
            return QPointF(
                p_start.x() + length * math.cos(snapped_angle),
                p_start.y() + length * math.sin(snapped_angle)
            )

        return p_cur

    def _get_shape_handles(self, shape: Dict[str, Any]) -> Dict[str, QPointF]:
        """Palauttaa valitun muodon raahauskahvojen pikselikoordinaatit kankaalla huomioiden kierron."""
        geom = shape.get("geometry")
        stype = shape.get("type", "rect")
        if not geom:
            return {}

        rot = float(shape.get("rotation", 0.0))

        def rotate_pt(pt_x: float, pt_y: float, cx: float, cy: float, deg: float) -> QPointF:
            if abs(deg) <= 0.001:
                return QPointF(pt_x, pt_y)
            rad = math.radians(deg)
            dx = pt_x - cx
            dy = pt_y - cy
            rx = cx + dx * math.cos(rad) - dy * math.sin(rad)
            ry = cy + dx * math.sin(rad) + dy * math.cos(rad)
            return QPointF(rx, ry)

        if stype in ("arrow", "line"):
            p1, p2 = geom
            x1 = p1[0] * self.zoom_factor
            y1 = p1[1] * self.zoom_factor
            x2 = p2[0] * self.zoom_factor
            y2 = p2[1] * self.zoom_factor
            cx = (x1 + x2) / 2.0
            cy = (y1 + y2) / 2.0
            return {
                "p1": rotate_pt(x1, y1, cx, cy, rot),
                "p2": rotate_pt(x2, y2, cx, cy, rot),
                "rot": rotate_pt(cx, min(y1, y2) - 25.0, cx, cy, rot)
            }
        else:
            x0 = geom[0] * self.zoom_factor
            y0 = geom[1] * self.zoom_factor
            x1 = geom[2] * self.zoom_factor
            y1 = geom[3] * self.zoom_factor
            cx = (x0 + x1) / 2.0
            cy = (y0 + y1) / 2.0
            w = x1 - x0
            h = y1 - y0
            return {
                "tl": rotate_pt(x0, y0, cx, cy, rot),
                "tr": rotate_pt(x1, y0, cx, cy, rot),
                "bl": rotate_pt(x0, y1, cx, cy, rot),
                "br": rotate_pt(x1, y1, cx, cy, rot),
                "r": rotate_pt(x1, y0 + h / 2.0, cx, cy, rot),
                "l": rotate_pt(x0, y0 + h / 2.0, cx, cy, rot),
                "t": rotate_pt(cx, y0, cx, cy, rot),
                "b": rotate_pt(cx, y1, cx, cy, rot),
                "rot": rotate_pt(cx, y0 - 25.0, cx, cy, rot),
            }

    def _shape_contains_point(self, shape: Dict[str, Any], pt: fitz.Point) -> bool:
        """Tarkistaa osuuko piste muodon alueelle (kääntää pisteen käänteisesti jos muoto on kierretty)."""
        stype = shape.get("type", "rect")
        geom = shape.get("geometry")
        if not geom:
            return False

        rot = float(shape.get("rotation", 0.0))
        test_pt = pt
        if abs(rot) > 0.001:
            if stype in ("arrow", "line"):
                cx = (geom[0][0] + geom[1][0]) / 2.0
                cy = (geom[0][1] + geom[1][1]) / 2.0
            else:
                cx = (geom[0] + geom[2]) / 2.0
                cy = (geom[1] + geom[3]) / 2.0
            rad = math.radians(-rot)
            dx = pt.x - cx
            dy = pt.y - cy
            nx = cx + dx * math.cos(rad) - dy * math.sin(rad)
            ny = cy + dx * math.sin(rad) + dy * math.cos(rad)
            test_pt = fitz.Point(nx, ny)

        if stype in ("arrow", "line"):
            p1, p2 = geom
            px, py = test_pt.x, test_pt.y
            x1, y1 = p1[0], p1[1]
            x2, y2 = p2[0], p2[1]
            dx = x2 - x1
            dy = y2 - y1
            l2 = dx * dx + dy * dy
            if l2 == 0:
                return math.hypot(px - x1, py - y1) <= 6.0
            t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / l2))
            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            return math.hypot(px - proj_x, py - proj_y) <= 8.0
        else:
            r = fitz.Rect(geom)
            return fitz.Rect(r.x0 - 4, r.y0 - 4, r.x1 + 4, r.y1 + 4).contains(test_pt)

    def _hit_test_shape(self, pt: fitz.Point) -> Optional[Dict[str, Any]]:
        """Etsii kursorin alla olevan muodon (ensin etualalla olevat, sitten taustalla olevat)."""
        if not self.doc_model or not self.doc_model.is_open:
            return None
        shapes = self.doc_model.page_shapes.get(self.current_page_idx, [])
        for s in reversed([x for x in shapes if x.get("overlay", True) and x.get("visible", True)]):
            if self._shape_contains_point(s, pt):
                return s
        for s in reversed([x for x in shapes if not x.get("overlay", True) and x.get("visible", True)]):
            if self._shape_contains_point(s, pt):
                return s
        return None

    def select_shape(self, shape_id: Optional[str]):
        """Valitsee muodon kankaalla ja lähettää tiedon Tasot-paneelille ja ominaisuuksille."""
        if self.selected_shape_id != shape_id:
            self.selected_shape_id = shape_id
            if shape_id:
                self.selected_block = None
                self.selected_span = None
                self.clear_selection()
            shape_data = self.doc_model.get_shape(self.current_page_idx, shape_id) if (self.doc_model and shape_id) else {}
            self.shape_selected.emit(shape_data or {})
            self.update()

    def select_element(self, elem_id: str, elem_type: str):
        """Valitsee elementin Tasot-paneelista tulleen pyynnön perusteella."""
        if elem_type == "text":
            self.select_shape(None)
            for b in self.blocks:
                b_id = b.get("block_id", f"text_b{b.get('number', 0)}")
                if b_id == elem_id or str(b.get("number", 0)) == elem_id:
                    self.selected_block = b
                    self.block_selected.emit(b)
                    self.update()
                    break
        else:
            self.select_shape(elem_id)

    def _reorder_selected_shape(self, action: str):
        """Järjestelee valitun muodon tason ja päivittää näkymän."""
        if self.selected_shape_id and self.doc_model:
            self.doc_model.reorder_shape(self.current_page_idx, self.selected_shape_id, action)
            self.refresh_page()
            shape_data = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            self.shape_selected.emit(shape_data or {})

    def _delete_selected_shape(self):
        """Poistaa valitun muodon."""
        if self.selected_shape_id and self.doc_model:
            s_id = self.selected_shape_id
            self.selected_shape_id = None
            self.doc_model.delete_shape(self.current_page_idx, s_id)
            self.refresh_page()
            self.shape_selected.emit({})

    def _ungroup_selected_shape(self):
        """Purkaa valitun muodon ryhmän."""
        if self.selected_shape_id and self.doc_model:
            cur = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur and cur.get("group_id"):
                self.doc_model.ungroup_shapes(self.current_page_idx, cur["group_id"])
                self.refresh_page()
                self.shape_selected.emit(cur)

    def set_shape_properties(self, props: Dict[str, Any]):
        """Päivittää muotojen piirtoasetukset shape_properties_dock -paneelista."""
        if "tool" in props:
            self.set_active_tool(props["tool"])
        if "has_fill" in props:
            self.shape_has_fill = props["has_fill"]
        if "fill_color" in props:
            self.shape_fill_color = props["fill_color"]
        if "fill_opacity" in props:
            self.shape_fill_opacity = props["fill_opacity"]
        if "stroke_color" in props:
            self.shape_stroke_color = props["stroke_color"]
        if "stroke_opacity" in props:
            self.shape_stroke_opacity = props["stroke_opacity"]
        if "stroke_width" in props:
            self.shape_stroke_width = props["stroke_width"]
        if "radius" in props:
            self.shape_radius = props["radius"]
        if "overlay" in props:
            self.shape_overlay = props["overlay"]
        if "rotation" in props:
            self.shape_rotation = props["rotation"]

        # Tekstiominaisuuksien oletukset tuleville muodoille
        if "text" in props:
            self.shape_text = props["text"]
        if "font_family" in props:
            self.shape_font_family = props["font_family"]
        if "font_size" in props:
            self.shape_font_size = props["font_size"]
        if "font_bold" in props:
            self.shape_font_bold = props["font_bold"]
        if "font_italic" in props:
            self.shape_font_italic = props["font_italic"]
        if "text_color" in props:
            self.shape_text_color = props["text_color"]
        if "text_align" in props:
            self.shape_text_align = props["text_align"]
        if "vertical_align" in props:
            self.shape_vertical_align = props["vertical_align"]

        # Jos jokin muoto on valittuna, päivitetään sen ominaisuudet reaaliajassa!
        target_id = props.get("target_shape_id") or self.selected_shape_id
        if target_id and self.doc_model and self.doc_model.is_open:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, target_id)
            if cur_shape:
                commit_undo = props.get("commit_undo", True)
                update_kwargs = {}
                if "fill_opacity" in props:
                    update_kwargs["fill_opacity"] = props["fill_opacity"]
                    if cur_shape.get("type") in ("arrow", "line") and cur_shape.get("fill_color") is None:
                        update_kwargs["stroke_opacity"] = props["fill_opacity"]
                if "has_fill" in props:
                    if props["has_fill"]:
                        if "fill_color" in props and props["fill_color"]:
                            update_kwargs["fill_color"] = props["fill_color"]
                    else:
                        update_kwargs["fill_color"] = None
                elif "fill_color" in props:
                    update_kwargs["fill_color"] = props["fill_color"]

                if "stroke_color" in props:
                    update_kwargs["stroke_color"] = props["stroke_color"]
                if "stroke_opacity" in props:
                    update_kwargs["stroke_opacity"] = props["stroke_opacity"]
                if "stroke_width" in props:
                    update_kwargs["stroke_width"] = props["stroke_width"]
                if "radius" in props:
                    update_kwargs["radius"] = props["radius"]
                if "overlay" in props:
                    update_kwargs["overlay"] = props["overlay"]
                if "rotation" in props:
                    update_kwargs["rotation"] = props["rotation"]

                if "text" in props:
                    update_kwargs["text"] = props["text"]
                if "font_family" in props:
                    update_kwargs["font_family"] = props["font_family"]
                if "font_size" in props:
                    update_kwargs["font_size"] = props["font_size"]
                if "font_bold" in props:
                    update_kwargs["font_bold"] = props["font_bold"]
                if "font_italic" in props:
                    update_kwargs["font_italic"] = props["font_italic"]
                if "text_color" in props:
                    update_kwargs["text_color"] = props["text_color"]
                if "text_align" in props:
                    update_kwargs["text_align"] = props["text_align"]
                if "vertical_align" in props:
                    update_kwargs["vertical_align"] = props["vertical_align"]

                if update_kwargs:
                    self.doc_model.update_shape(
                        self.current_page_idx,
                        target_id,
                        push_undo=commit_undo,
                        **update_kwargs
                    )
                    self.refresh_page()
                    self.shape_properties_committed.emit()

                    # Jos kelluva in-canvas editori on auki tälle muodolle, synkronoidaan sen teksti säilyttäen kursori
                    if self.inline_shape_editor.isVisible() and self._active_inline_shape_id == target_id:
                        if "text" in props and not self._syncing_inline_editor:
                            new_t = props["text"]
                            if self.inline_shape_editor.toPlainText() != new_t:
                                cursor = self.inline_shape_editor.textCursor()
                                old_pos = cursor.position()
                                self._syncing_inline_editor = True
                                try:
                                    self.inline_shape_editor.setPlainText(new_t)
                                    cursor.setPosition(min(old_pos, len(new_t)))
                                    self.inline_shape_editor.setTextCursor(cursor)
                                finally:
                                    self._syncing_inline_editor = False

        self.update()

    def set_active_tool(self, tool_id: str):
        """Asettaa aktiivisen piirto- tai siirtotyökalun."""
        self.active_tool = "move" if tool_id in ("move", "select") else tool_id
        if self.active_tool != "move":
            self.setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        self.update()

    def delete_selected_shape(self):
        """Poistaa kankaalla valitun muodon."""
        if self.selected_shape_id and self.doc_model and self.doc_model.is_open:
            s_id = self.selected_shape_id
            self.select_shape(None)
            self.doc_model.delete_shape(self.current_page_idx, s_id)
            self.refresh_page()
            self.update()

    def set_show_margin_guides(self, show: bool):
        """Kytkee sivun marginaaliohjaimet päälle/pois."""
        self.show_margin_guides = show
        self.update()

    def add_background_card_to_selected_block(self):
        """Lisää taustakortin valitun tekstikappaleen alle."""
        if not self.selected_block or not self.doc_model or not self.doc_model.is_open:
            return
        fill = self.shape_fill_color if self.shape_fill_color else (0.94, 0.96, 0.98)
        stroke = self.shape_stroke_color if self.shape_stroke_color else (0.7, 0.8, 0.9)
        self.doc_model.add_background_card_for_block(
            page_idx=self.current_page_idx,
            block=self.selected_block,
            padding=6.0,
            fill_color=fill,
            stroke_color=stroke,
            stroke_width=self.shape_stroke_width,
            radius=self.shape_radius
        )
        self.refresh_page()
        self.shape_drawn.emit({"action": "background_card", "page": self.current_page_idx})

    def _quick_add_shape(self, shape_type: str, overlay: bool = True):
        """Lisää muodon nopeasti sivulle."""
        if not self.doc_model or not self.doc_model.is_open:
            return
        boxes = self.doc_model.get_page_boxes(self.current_page_idx)
        w = boxes.get("width_pt", 595.0)
        h = boxes.get("height_pt", 842.0)
        cx, cy = w / 2.0, h / 2.0
        if shape_type in ("rect", "rounded_rect", "circle"):
            geom = (cx - 100, cy - 50, cx + 100, cy + 50)
        elif shape_type == "arrow":
            geom = ((cx - 80, cy), (cx + 80, cy))
        else:
            geom = ((cx - 80, cy), (cx + 80, cy))

        fill = self.shape_fill_color if getattr(self, "shape_has_fill", True) and self.shape_fill_color else None
        stroke = self.shape_stroke_color if self.shape_stroke_color else (0.2, 0.4, 0.7)
        new_id = self.doc_model.draw_shape(
            page_idx=self.current_page_idx,
            shape_type=shape_type,
            geometry=geom,
            fill_color=fill,
            stroke_color=stroke,
            fill_opacity=self.shape_fill_opacity,
            stroke_opacity=self.shape_stroke_opacity,
            stroke_width=self.shape_stroke_width,
            radius=self.shape_radius,
            overlay=overlay,
            rotation=getattr(self, "shape_rotation", 0.0),
        )
        self.select_shape(new_id)
        self.refresh_page()
        self.shape_drawn.emit({"tool": shape_type, "geom": geom, "id": new_id})

    def clear_selection(self):
        """Tyhjentää nykyisen sanakohtaisen tekstivalinnan (mustamaalauksen)."""
        self.selected_words.clear()
        self.selected_text = ""
        self.selected_text_rects.clear()
        self.update()

    def set_selection_mode(self, mode: str):
        """Asettaa valintatilan: 'paragraph' (kappale) tai 'span' (rivi/jakso)."""
        if mode in ("paragraph", "span") and self.selection_mode != mode:
            self.selection_mode = mode
            self.selected_span = None
            self.hover_span = None
            self.selected_block = None
            self.hover_block = None
            self.clear_selection()
            self.mode_changed.emit(mode)
            self.update()

    def set_document(self, doc_model: PDFDocumentModel):
        self.doc_model = doc_model
        self.current_page_idx = 0
        self.selected_span = None
        self.hover_span = None
        self.selected_block = None
        self.hover_block = None
        self.clear_selection()
        self.refresh_page()

    def set_page(self, page_idx: int):
        if not self.doc_model or not self.doc_model.is_open:
            return
        if 0 <= page_idx < self.doc_model.page_count:
            self.current_page_idx = page_idx
            self.selected_span = None
            self.hover_span = None
            self.selected_block = None
            self.hover_block = None
            self.clear_selection()
            self.refresh_page()

    def set_zoom(self, zoom: float):
        zoom = max(0.5, min(5.0, zoom))
        if abs(self.zoom_factor - zoom) > 0.01:
            self.zoom_factor = zoom
            self.zoom_changed.emit(self.zoom_factor)
            self.refresh_page()

    def refresh_page(self):
        if not self.doc_model or not self.doc_model.is_open:
            self.page_pixmap = None
            self.spans.clear()
            self.blocks.clear()
            self.page_words.clear()
            self.clear_selection()
            self.update()
            return

        # Renderöidään kuva korkealla tarkkuudella
        qimg, w, h = self.doc_model.render_page(self.current_page_idx, scale=self.zoom_factor)
        self.page_pixmap = QPixmap.fromImage(qimg)
        self.setFixedSize(w, h)

        # Haetaan sivun rakenne (kappaleet, jaksot ja sanat)
        self.blocks = self.doc_model.get_blocks_for_page(self.current_page_idx)
        self.spans = self.doc_model.get_spans_for_page(self.current_page_idx)
        try:
            page = self.doc_model.doc[self.current_page_idx]
            self.page_words = page.get_text("words")
        except Exception:
            self.page_words = []
        self.update()

    def _get_block_handles(self, block: Dict[str, Any]) -> Dict[str, QPointF]:
        """Palauttaa valitun lohkon 8 raahauskahvan pikselikoordinaatit kankaalla."""
        r = block["bbox"]
        x = r[0] * self.zoom_factor
        y = r[1] * self.zoom_factor
        w = (r[2] - r[0]) * self.zoom_factor
        h = (r[3] - r[1]) * self.zoom_factor
        return {
            "tl": QPointF(x, y),
            "tr": QPointF(x + w, y),
            "bl": QPointF(x, y + h),
            "br": QPointF(x + w, y + h),
            "r": QPointF(x + w, y + h / 2.0),
            "l": QPointF(x, y + h / 2.0),
            "t": QPointF(x + w / 2.0, y),
            "b": QPointF(x + w / 2.0, y + h),
        }

    def _hit_test_handle(self, pt_screen: QPointF, handles: Dict[str, QPointF], radius: float = 8.0) -> Optional[str]:
        """Tarkistaa osuuko hiiren kursori johonkin kahvoista."""
        for name, h_pt in handles.items():
            dx = pt_screen.x() - h_pt.x()
            dy = pt_screen.y() - h_pt.y()
            if (dx * dx + dy * dy) <= (radius * radius):
                return name
        return None

    def _update_cursor_for_handle(self, handle_name: Optional[str]):
        """Päivittää hiirikursorin muodon kahvan suunnan mukaan."""
        if not handle_name:
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif handle_name in ("r", "l"):
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        elif handle_name in ("t", "b"):
            self.setCursor(Qt.CursorShape.SizeVerCursor)
        elif handle_name in ("tl", "br"):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif handle_name in ("tr", "bl"):
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        elif handle_name == "rot":
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _find_nearest_word_index(self, pt: fitz.Point, max_dist: float = 30.0) -> Optional[int]:
        """Etsii ja palauttaa annettua pistettä lähimmän sanan indeksin sivulla."""
        if not self.page_words:
            return None
        # Ensisijainen: suora tai pehmustettu osuma sanalaatikkoon
        for i, w in enumerate(self.page_words):
            if fitz.Rect(w[0] - 2.0, w[1] - 2.0, w[2] + 2.0, w[3] + 2.0).contains(pt):
                return i
        # Toissijainen: lähin etäisyys (painottaen pystyetäisyyttä jotta pysyy samalla rivillä)
        best_idx = None
        best_dist = float("inf")
        for i, w in enumerate(self.page_words):
            r = fitz.Rect(w[:4])
            dx = max(r.x0 - pt.x, 0.0, pt.x - r.x1)
            dy = max(r.y0 - pt.y, 0.0, pt.y - r.y1)
            dist = (dx * dx + (dy * dy * 4.0)) ** 0.5
            if dist < best_dist and dist <= max_dist:
                best_dist = dist
                best_idx = i
        return best_idx

    def copy_selection_to_clipboard(self):
        """Kopioi valitun tekstin (mustamaalatut sanat tai koko kappale) leikepöydälle (Ctrl+C)."""
        text = ""
        if self.selected_text:
            text = self.selected_text
        elif self.selected_block:
            text = self.selected_block.get("text", "")
        elif self.selected_span:
            text = self.selected_span.get("text", "")
        if text:
            cb = QGuiApplication.clipboard()
            if cb:
                cb.setText(text)

    def cut_selection(self):
        """Leikkaa valitun tekstin leikepöydälle ja poistaa sen (Ctrl+X)."""
        self.copy_selection_to_clipboard()
        self.delete_selection()

    def paste_from_clipboard(self):
        """Liittää leikepöydän sisällön editoriin (Ctrl+V)."""
        cb = QGuiApplication.clipboard()
        if cb:
            txt = cb.text()
            if txt:
                self.request_paste.emit(txt)

    def delete_selection(self):
        """Poistaa valitun tekstin, kappaleen tai muodon (Del / Backspace)."""
        if self.selected_shape_id and self.doc_model:
            self.delete_selected_shape()
        elif self.selected_text:
            self.request_delete_text.emit()
        elif self.selected_block:
            self.request_delete_block.emit(self.selected_block)

    def toggle_bold(self):
        """Kääntää lihavointitilan (Bold / Ctrl+B)."""
        self.request_bold.emit()

    def toggle_italic(self):
        """Kääntää kursivointitilan (Italic / Ctrl+I)."""
        self.request_italic.emit()

    def mouseMoveEvent(self, event: QMouseEvent):
        if not self.doc_model or not self.doc_model.is_open:
            return

        pos = event.position()
        self.current_mouse_pos = pos

        # 0. Käsitellään käynnissä oleva muodon piirtäminen
        if self.is_drawing_shape:
            # Kuvasuhteen lukitus Ctrl tai Shift pohjassa
            if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                pos = self._constrain_shape_point(self.shape_start_pos, pos, self.active_tool)
            self.shape_current_pos = pos
            self.update()
            return

        # Jos muototyökalu on valittuna, näytetään ristikursori
        if self.active_tool not in ("move", "select"):
            self.setCursor(Qt.CursorShape.CrossCursor)
            return

        # 1.0 Käsitellään käynnissä oleva muodon raahaaminen (Shape dragging)
        if self.is_dragging_shape and self.selected_shape_id:
            dx = (pos.x() - self.drag_shape_start_pos.x()) / self.zoom_factor
            dy = (pos.y() - self.drag_shape_start_pos.y()) / self.zoom_factor
            self.drag_shape_delta = (dx, dy)
            self.update()
            return

        # 1.05 Käsitellään käynnissä oleva muodon vapaa kierto (Shape rotation dragging)
        if getattr(self, "is_rotating_shape", False) and self.selected_shape_id:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur_shape:
                dx = pos.x() - self.rotate_center.x()
                dy = pos.y() - self.rotate_center.y()
                angle = math.degrees(math.atan2(dy, dx)) + 90.0
                while angle > 180.0:
                    angle -= 360.0
                while angle < -180.0:
                    angle += 360.0
                if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                    angle = round(angle / 15.0) * 15.0
                self.doc_model.update_shape(self.current_page_idx, self.selected_shape_id, push_undo=False, rotation=round(angle, 1))
                self.refresh_page()
                self.update()
                return

        # 1.1 Käsitellään käynnissä oleva muodon koonmuutos (Shape handle dragging)
        if self.is_resizing_shape and self.selected_shape_id and self.resize_shape_start_geom:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur_shape:
                stype = cur_shape.get("type", "rect")
                orig = self.resize_shape_start_geom
                dx = (pos.x() - self.resize_start_pos.x()) / self.zoom_factor
                dy = (pos.y() - self.resize_start_pos.y()) / self.zoom_factor
                h_name = self.resize_shape_handle

                if stype in ("arrow", "line"):
                    p1, p2 = orig
                    if h_name == "p1":
                        np1 = QPointF(p1[0] + dx, p1[1] + dy)
                        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                            np1 = self._constrain_shape_point(QPointF(p2[0], p2[1]), np1, stype)
                        new_geom = ((np1.x(), np1.y()), p2)
                    else:
                        np2 = QPointF(p2[0] + dx, p2[1] + dy)
                        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                            np2 = self._constrain_shape_point(QPointF(p1[0], p1[1]), np2, stype)
                        new_geom = (p1, (np2.x(), np2.y()))
                else:
                    x0, y0, x1, y1 = orig
                    w0 = max(1.0, x1 - x0)
                    h0 = max(1.0, y1 - y0)
                    nx0, ny0, nx1, ny1 = x0, y0, x1, y1

                    if "r" in h_name:
                        nx1 = max(nx0 + 10.0, x1 + dx)
                    if "l" in h_name:
                        nx0 = min(nx1 - 10.0, x0 + dx)
                    if "b" in h_name:
                        ny1 = max(ny0 + 10.0, y1 + dy)
                    if "t" in h_name:
                        ny0 = min(ny1 - 10.0, y0 + dy)

                    # Kuvasuhdelukitus Ctrl tai Shift pohjassa ("silleen fixatusti")
                    if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                        nw = nx1 - nx0
                        nh = ny1 - ny0
                        ratio = w0 / h0
                        s = max(nw / w0, nh / h0)
                        target_w = w0 * s
                        target_h = h0 * s
                        if h_name == "br":
                            nx1 = nx0 + target_w
                            ny1 = ny0 + target_h
                        elif h_name == "tl":
                            nx0 = nx1 - target_w
                            ny0 = ny1 - target_h
                        elif h_name == "tr":
                            nx1 = nx0 + target_w
                            ny0 = ny1 - target_h
                        elif h_name == "bl":
                            nx0 = nx1 - target_w
                            ny1 = ny0 + target_h
                        elif "r" in h_name or "l" in h_name:
                            target_h = nw / ratio
                            mid_y = (ny0 + ny1) / 2.0
                            ny0 = mid_y - target_h / 2.0
                            ny1 = mid_y + target_h / 2.0
                        elif "b" in h_name or "t" in h_name:
                            target_w = nh * ratio
                            mid_x = (nx0 + nx1) / 2.0
                            nx0 = mid_x - target_w / 2.0
                            nx1 = mid_x + target_w / 2.0

                    new_geom = (min(nx0, nx1), min(ny0, ny1), max(nx0, nx1), max(ny0, ny1))

                self.doc_model.update_shape(self.current_page_idx, self.selected_shape_id, push_undo=False, geometry=new_geom)
                self.refresh_page()
                return

        # 1.2 Käsitellään käynnissä oleva lohkon koonmuutos (Handle dragging)
        if self.is_resizing and self.selected_block:
            dx = (pos.x() - self.resize_start_pos.x()) / self.zoom_factor
            dy = (pos.y() - self.resize_start_pos.y()) / self.zoom_factor
            orig_b = self.resize_start_bbox
            new_b = list(orig_b)

            # Oikea reuna ja oikeat kulmat
            if self.active_handle in ("r", "tr", "br"):
                new_b[2] = max(orig_b[0] + 20.0, orig_b[2] + dx)
            # Vasen reuna ja vasemmat kulmat
            elif self.active_handle in ("l", "tl", "bl"):
                new_b[0] = min(orig_b[2] - 20.0, orig_b[0] + dx)

            # Alareuna ja alakulmat
            if self.active_handle in ("b", "bl", "br"):
                new_b[3] = max(orig_b[1] + 10.0, orig_b[3] + dy)
            # Yläreuna ja yläkulmat
            elif self.active_handle in ("t", "tl", "tr"):
                new_b[1] = min(orig_b[3] - 10.0, orig_b[1] + dy)

            self.selected_block["bbox"] = new_b
            self.selected_block["max_width"] = max(20.0, new_b[2] - new_b[0])
            self.block_geometry_changed.emit(self.selected_block)
            self.update()
            return

        # 2. Käsitellään Word-tason mustamaalaus / tekstivalinnan raahaus
        if self.mouse_pressed and (event.buttons() & Qt.MouseButton.LeftButton):
            dist = (pos - self.select_start_pos).manhattanLength()
            if dist > 5:
                self.is_selecting_text = True
                p_start = fitz.Point(self.select_start_pos.x() / self.zoom_factor, self.select_start_pos.y() / self.zoom_factor)
                p_cur = fitz.Point(pos.x() / self.zoom_factor, pos.y() / self.zoom_factor)

                idx_start = self._find_nearest_word_index(p_start, max_dist=25.0)
                idx_cur = self._find_nearest_word_index(p_cur, max_dist=25.0)

                if idx_start is not None and idx_cur is not None:
                    i0, i1 = min(idx_start, idx_cur), max(idx_start, idx_cur)
                    sel_words = self.page_words[i0 : i1 + 1]
                else:
                    x0, y0 = min(p_start.x, p_cur.x), min(p_start.y, p_cur.y)
                    x1, y1 = max(p_start.x, p_cur.x), max(p_start.y, p_cur.y)
                    drag_rect = fitz.Rect(x0, y0, x1, y1)
                    sel_words = [w for w in self.page_words if fitz.Rect(w[:4]).intersects(drag_rect)]

                self.selected_words = sel_words
                self.selected_text = " ".join(w[4] for w in sel_words)
                self.selected_text_rects = [
                    QRectF(w[0] * self.zoom_factor, w[1] * self.zoom_factor,
                           (w[2] - w[0]) * self.zoom_factor, (w[3] - w[1]) * self.zoom_factor)
                    for w in sel_words
                ]
                self.update()
                return

        # 3. Tarkistetaan osoittaako hiiri valitun muodon kahvaan tai muotoon
        pdf_x = pos.x() / self.zoom_factor
        pdf_y = pos.y() / self.zoom_factor
        pt = fitz.Point(pdf_x, pdf_y)

        if self.selected_shape_id and self.doc_model:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur_shape:
                handles = self._get_shape_handles(cur_shape)
                hit = self._hit_test_handle(pos, handles)
                if hit:
                    self._update_cursor_for_handle(hit)
                    return
                elif self._shape_contains_point(cur_shape, pt):
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                    return

        # Jos ollaan siirtotilassa (move) ja osoitetaan mitä tahansa muotoa kankaalla:
        if self.active_tool in ("move", "select"):
            hover_s = self._hit_test_shape(pt)
            if hover_s:
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return

        # 4. Tarkistetaan osoittaako hiiri valitun kappaleen kahvaan
        if self.selection_mode == "paragraph" and self.selected_block:
            handles = self._get_block_handles(self.selected_block)
            hit = self._hit_test_handle(pos, handles)
            self._update_cursor_for_handle(hit)
            if hit:
                return

        # 5. Normaali hover-tunnistus ja kursorin muoto (I-Beam tekstille)
        is_over_word = any(fitz.Rect(w[:4]).contains(pt) for w in self.page_words)
        if is_over_word:
            self.setCursor(Qt.CursorShape.IBeamCursor)
        else:
            self.setCursor(Qt.CursorShape.ArrowCursor)

        if self.selection_mode == "paragraph":
            found_block = None
            for b in self.blocks:
                r = fitz.Rect(b["bbox"])
                if r.contains(pt):
                    found_block = b
                    break
            if self.hover_block != found_block:
                self.hover_block = found_block
                self.update()
        else:
            found_span = None
            for s in self.spans:
                r = fitz.Rect(s["bbox"])
                if r.contains(pt):
                    found_span = s
                    break
            if self.hover_span != found_span:
                self.hover_span = found_span
                self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if not self.doc_model or not self.doc_model.is_open:
            return

        if self.inline_shape_editor.isVisible():
            self.finish_inline_shape_editor(commit=True)

        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            self.mouse_pressed = True
            self.select_start_pos = pos
            self.current_mouse_pos = pos
            self.is_selecting_text = False

            # Muototyökalun piirtämisen aloitus
            if self.active_tool not in ("move", "select"):
                self.is_drawing_shape = True
                self.shape_start_pos = pos
                self.shape_current_pos = pos
                self.update()
                event.accept()
                return

            pdf_x = pos.x() / self.zoom_factor
            pdf_y = pos.y() / self.zoom_factor
            pt = fitz.Point(pdf_x, pdf_y)

            # 1. Tarkistetaan osuuko klikkaus valitun muodon kahvaan tai sen sisään
            if self.selected_shape_id and self.doc_model:
                cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
                if cur_shape:
                    handles = self._get_shape_handles(cur_shape)
                    hit_handle = self._hit_test_handle(pos, handles)
                    if hit_handle:
                        if hit_handle == "rot":
                            self.is_rotating_shape = True
                            self.rotate_start_angle = float(cur_shape.get("rotation", 0.0))
                            self.rotate_start_pos = pos
                            bbox = self.doc_model._compute_shape_bbox(cur_shape)
                            self.rotate_center = QPointF(
                                (bbox[0] + bbox[2]) / 2.0 * self.zoom_factor,
                                (bbox[1] + bbox[3]) / 2.0 * self.zoom_factor
                            )
                            event.accept()
                            return
                        else:
                            self.is_resizing_shape = True
                            self.resize_shape_handle = hit_handle
                            self.resize_start_pos = pos
                            self.resize_shape_start_geom = cur_shape.get("geometry")
                            event.accept()
                            return
                    if self._shape_contains_point(cur_shape, pt):
                        self.is_dragging_shape = True
                        self.drag_shape_start_pos = pos
                        self.drag_shape_delta = (0.0, 0.0)
                        self.setCursor(Qt.CursorShape.SizeAllCursor)
                        event.accept()
                        return

            # 2. Tarkistetaan osuuko klikkaus muuhun muotoon kankaalla
            hit_shape = self._hit_test_shape(pt)
            if hit_shape:
                self.select_shape(hit_shape["id"])
                self.is_dragging_shape = True
                self.drag_shape_start_pos = pos
                self.drag_shape_delta = (0.0, 0.0)
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                event.accept()
                return

            # Ei osuttu muotoon -> nollataan muotovalinta
            if self.selected_shape_id:
                self.select_shape(None)

            # 3. Tarkistetaan osuuko klikkaus valitun lohkon kahvaan
            if self.selection_mode == "paragraph" and self.selected_block:
                handles = self._get_block_handles(self.selected_block)
                hit_handle = self._hit_test_handle(pos, handles)
                if hit_handle:
                    self.is_resizing = True
                    self.active_handle = hit_handle
                    self.resize_start_pos = pos
                    self.resize_start_bbox = list(self.selected_block["bbox"])
                    event.accept()
                    return

            if self.selection_mode == "paragraph":
                target_block = None
                for b in self.blocks:
                    r = fitz.Rect(b["bbox"])
                    if r.contains(pt):
                        target_block = b
                        break
                self.selected_block = target_block
                self.selected_span = None
                if target_block:
                    self.block_selected.emit(target_block)
                self.update()
            else:
                target_span = None
                for s in self.spans:
                    r = fitz.Rect(s["bbox"])
                    if r.contains(pt):
                        target_span = s
                        break
                self.selected_span = target_span
                self.selected_block = None
                if target_span:
                    self.span_selected.emit(target_span)
                self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.mouse_pressed = False
        if event.button() == Qt.MouseButton.LeftButton:
            # Muodon piirtämisen päättäminen ja tallennus
            if self.is_drawing_shape:
                self.is_drawing_shape = False
                p1 = (self.shape_start_pos.x() / self.zoom_factor, self.shape_start_pos.y() / self.zoom_factor)
                pos = event.position()
                if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
                    pos = self._constrain_shape_point(self.shape_start_pos, pos, self.active_tool)
                p2 = (pos.x() / self.zoom_factor, pos.y() / self.zoom_factor)
                dx = abs(p2[0] - p1[0])
                dy = abs(p2[1] - p1[1])
                if (dx > 3 or dy > 3) and self.doc_model and self.doc_model.is_open:
                    drawn_tool = self.active_tool
                    if drawn_tool in ("rect", "rounded_rect", "circle", "textbox"):
                        geom = (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
                    else:
                        geom = (p1, p2)
                    actual_fill = self.shape_fill_color if getattr(self, "shape_has_fill", True) and self.shape_fill_color else None
                    new_id = self.doc_model.draw_shape(
                        page_idx=self.current_page_idx,
                        shape_type=drawn_tool,
                        geometry=geom,
                        fill_color=actual_fill,
                        stroke_color=self.shape_stroke_color,
                        fill_opacity=self.shape_fill_opacity,
                        stroke_opacity=self.shape_stroke_opacity,
                        stroke_width=self.shape_stroke_width,
                        radius=self.shape_radius,
                        overlay=self.shape_overlay,
                        rotation=getattr(self, 'shape_rotation', 0.0),
                        text=getattr(self, 'shape_text', ""),
                        font_family=getattr(self, 'shape_font_family', "Helvetica"),
                        font_size=getattr(self, 'shape_font_size', 14.0),
                        font_bold=getattr(self, 'shape_font_bold', False),
                        font_italic=getattr(self, 'shape_font_italic', False),
                        text_color=getattr(self, 'shape_text_color', (0.0, 0.0, 0.0)),
                        text_align=getattr(self, 'shape_text_align', "center"),
                        vertical_align=getattr(self, 'shape_vertical_align', "middle"),
                    )
                    self.select_shape(new_id)
                    self.refresh_page()
                    self.shape_drawn.emit({"tool": drawn_tool, "geom": geom, "id": new_id})
                    self.set_active_tool("move")
                    self.tool_switched.emit("move")
                    if drawn_tool == "textbox":
                        self.start_inline_shape_editor(new_id)
                        self.request_focus_shape_text.emit(new_id)
                self.update()
                event.accept()
                return

            if self.is_dragging_shape:
                self.is_dragging_shape = False
                dx, dy = self.drag_shape_delta
                self.drag_shape_delta = (0.0, 0.0)
                if (abs(dx) > 0.5 or abs(dy) > 0.5) and self.selected_shape_id and self.doc_model:
                    self.doc_model.move_shape(self.current_page_idx, self.selected_shape_id, dx, dy, push_undo=True)
                    self.refresh_page()
                self.setCursor(Qt.CursorShape.ArrowCursor)
                self.update()
                event.accept()
                return

            if getattr(self, "is_rotating_shape", False):
                self.is_rotating_shape = False
                if self.selected_shape_id and self.doc_model:
                    cur_s = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
                    if cur_s:
                        rot = float(cur_s.get("rotation", 0.0))
                        self.doc_model.update_shape(self.current_page_idx, self.selected_shape_id, push_undo=True, rotation=rot)
                        self.shape_selected.emit(cur_s)
                self.update()
                event.accept()
                return

            if self.is_resizing_shape:
                self.is_resizing_shape = False
                self.resize_shape_handle = None
                self.resize_shape_start_geom = None
                if self.doc_model:
                    self.doc_model._push_undo_state()
                    self.doc_model.redo_stack.clear()
                self.update()
                event.accept()
                return

            if self.is_resizing:
                self.is_resizing = False
                self.active_handle = None
                if self.selected_block:
                    self.block_geometry_changed.emit(self.selected_block)
                self.update()
                event.accept()
                return

            if self.is_selecting_text:
                self.is_selecting_text = False
                if self.selected_words:
                    self.selected_text = " ".join(w[4] for w in self.selected_words)
                    self.text_selected.emit(self.selected_text)
                    # Synkronoidaan editori valitun tekstin lohkoon
                    first_w = self.selected_words[0]
                    for b in self.blocks:
                        if fitz.Rect(b["bbox"]).intersects(fitz.Rect(first_w[:4])):
                            self.selected_block = b
                            self.block_selected.emit(b)
                            break
                self.update()
                event.accept()
                return
            else:
                # Tavallinen klikkaus ilman raahausta: jos klikattiin tekstin ulkopuolelle, tyhjennetään sanavalinta
                pdf_x = event.position().x() / self.zoom_factor
                pdf_y = event.position().y() / self.zoom_factor
                pt = fitz.Point(pdf_x, pdf_y)
                hit_word = any(fitz.Rect(w[:4]).contains(pt) for w in self.page_words)
                if not hit_word:
                    self.selected_words.clear()
                    self.selected_text = ""
                    self.selected_text_rects.clear()
                    self.update()
        super().mouseReleaseEvent(event)


    def keyReleaseEvent(self, event: QKeyEvent):
        """Päivittää kuminauhan kun Ctrl / Shift vapautetaan."""
        if self.is_drawing_shape:
            if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Shift):
                self.shape_current_pos = self.current_mouse_pos
                self.update()
        super().keyReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if not self.doc_model or not self.doc_model.is_open:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position()
            pdf_x = pos.x() / self.zoom_factor
            pdf_y = pos.y() / self.zoom_factor
            pt = fitz.Point(pdf_x, pdf_y)

            # 1. Tarkistetaan osuuko kaksoisnapsautus muotoon tai tekstilaatikkoon
            hit_shape = self._hit_test_shape(pt)
            if hit_shape:
                s_id = hit_shape.get("id")
                self.select_shape(s_id)
                self.start_inline_shape_editor(s_id)
                self.request_focus_shape_text.emit(s_id)
                event.accept()
                return

            hit_w = None
            for w in self.page_words:
                if fitz.Rect(w[0] - 2.0, w[1] - 2.0, w[2] + 2.0, w[3] + 2.0).contains(pt):
                    hit_w = w
                    break

            if hit_w:
                self.selected_words = [hit_w]
                self.selected_text = hit_w[4]
                r = fitz.Rect(hit_w[:4])
                self.selected_text_rects = [
                    QRectF(r.x0 * self.zoom_factor, r.y0 * self.zoom_factor,
                           (r.x1 - r.x0) * self.zoom_factor, (r.y1 - r.y0) * self.zoom_factor)
                ]
                self.text_selected.emit(self.selected_text)

                for b in self.blocks:
                    if fitz.Rect(b["bbox"]).intersects(fitz.Rect(hit_w[:4])):
                        self.selected_block = b
                        self.block_selected.emit(b)
                        break
                self.update()
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent):
        if not self.doc_model or not self.doc_model.is_open:
            return

        pos = event.pos()
        pdf_x = pos.x() / self.zoom_factor
        pdf_y = pos.y() / self.zoom_factor
        pt = fitz.Point(pdf_x, pdf_y)

        # 0. Jos muoto on valittuna tai klikataan muotoa: näytetään muotovalikko
        if not self.selected_shape_id:
            hit_shape = self._hit_test_shape(pt)
            if hit_shape:
                self.select_shape(hit_shape["id"])

        if self.selected_shape_id and self.doc_model:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur_shape and self._shape_contains_point(cur_shape, pt):
                menu = QMenu(self)
                menu.setStyleSheet("""
                    QMenu {
                        background-color: #2c3e50;
                        color: #ecf0f1;
                        border: 1px solid #1a252f;
                        border-radius: 6px;
                        padding: 4px;
                        font-size: 12px;
                    }
                    QMenu::item {
                        padding: 5px 22px 5px 20px;
                        border-radius: 3px;
                    }
                    QMenu::item:selected {
                        background-color: #2980b9;
                        color: #ffffff;
                    }
                    QMenu::separator {
                        height: 1px;
                        background-color: #3e5871;
                        margin: 4px 6px;
                    }
                """)
                act_undo = menu.addAction("↩️  Kumoa (Undo)")
                act_undo.setShortcut(QKeySequence.StandardKey.Undo)
                act_undo.setEnabled(self.doc_model.can_undo())
                act_undo.triggered.connect(self.request_undo.emit)

                act_redo = menu.addAction("↪️  Tee uudelleen (Redo)")
                act_redo.setShortcut(QKeySequence.StandardKey.Redo)
                act_redo.setEnabled(self.doc_model.can_redo())
                act_redo.triggered.connect(self.request_redo.emit)

                menu.addSeparator()

                act_front = menu.addAction("🔼  Tuo etualalle (Bring to Front)")
                act_front.triggered.connect(lambda: self._reorder_selected_shape("bring_to_front"))

                act_back = menu.addAction("🔽  Vie taustalle (Send to Back)")
                act_back.triggered.connect(lambda: self._reorder_selected_shape("send_to_back"))

                act_behind = menu.addAction("📄  Siirrä tekstin alle (Behind Text)")
                act_behind.triggered.connect(lambda: self._reorder_selected_shape("behind_text"))

                act_over = menu.addAction("📄  Siirrä tekstin päälle (Over Text)")
                act_over.triggered.connect(lambda: self._reorder_selected_shape("over_text"))

                menu.addSeparator()

                if cur_shape.get("group_id"):
                    act_ungroup = menu.addAction("🔓  Pura ryhmä (Ungroup)")
                    act_ungroup.triggered.connect(self._ungroup_selected_shape)

                act_del = menu.addAction("🗑️  Poista muoto (Delete)")
                act_del.setShortcut(QKeySequence.StandardKey.Delete)
                act_del.triggered.connect(self._delete_selected_shape)

                menu.exec(event.globalPos())
                return

        # Jos klikataan nykyisen valinnan ulkopuolelle, valitaan kohdistimen alla oleva sana tai lohko
        is_inside_selection = any(r.contains(pos) for r in self.selected_text_rects)
        if not is_inside_selection:
            hit_w = None
            for w in self.page_words:
                if fitz.Rect(w[0] - 2.0, w[1] - 2.0, w[2] + 2.0, w[3] + 2.0).contains(pt):
                    hit_w = w
                    break
            if hit_w:
                self.selected_words = [hit_w]
                self.selected_text = hit_w[4]
                r = fitz.Rect(hit_w[:4])
                self.selected_text_rects = [
                    QRectF(r.x0 * self.zoom_factor, r.y0 * self.zoom_factor,
                           (r.x1 - r.x0) * self.zoom_factor, (r.y1 - r.y0) * self.zoom_factor)
                ]
                self.text_selected.emit(self.selected_text)
                for b in self.blocks:
                    if fitz.Rect(b["bbox"]).intersects(fitz.Rect(hit_w[:4])):
                        self.selected_block = b
                        self.block_selected.emit(b)
                        break
            else:
                for b in self.blocks:
                    if fitz.Rect(b["bbox"]).contains(pt):
                        self.selected_block = b
                        self.block_selected.emit(b)
                        break
            self.update()

        # Luodaan Acrobat-tyylinen tyylikäs valikko
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #2c3e50;
                color: #ecf0f1;
                border: 1px solid #1a252f;
                border-radius: 6px;
                padding: 4px;
                font-size: 12px;
            }
            QMenu::item {
                padding: 5px 22px 5px 20px;
                border-radius: 3px;
            }
            QMenu::item:selected {
                background-color: #2980b9;
                color: #ffffff;
            }
            QMenu::item:disabled {
                color: #7f8c8d;
            }
            QMenu::separator {
                height: 1px;
                background-color: #3e5871;
                margin: 4px 6px;
            }
        """)

        has_selection = bool(self.selected_text or self.selected_block or self.selected_span)

        act_undo = menu.addAction("↩️  Kumoa (Undo)")
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.setEnabled(self.doc_model.can_undo() if self.doc_model else False)
        act_undo.triggered.connect(self.request_undo.emit)

        act_redo = menu.addAction("↪️  Tee uudelleen (Redo)")
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.setEnabled(self.doc_model.can_redo() if self.doc_model else False)
        act_redo.triggered.connect(self.request_redo.emit)

        menu.addSeparator()

        act_edit = menu.addAction("✍️  Muokkaa tekstiä (In-Place Editor)")
        act_edit.setEnabled(has_selection)
        act_edit.triggered.connect(self.request_edit.emit)

        menu.addSeparator()

        act_copy = menu.addAction("📋  Kopioi (Copy)")
        act_copy.setShortcut(QKeySequence.StandardKey.Copy)
        act_copy.setEnabled(has_selection)
        act_copy.triggered.connect(self.copy_selection_to_clipboard)

        act_cut = menu.addAction("✂️  Leikkaa (Cut)")
        act_cut.setShortcut(QKeySequence.StandardKey.Cut)
        act_cut.setEnabled(has_selection)
        act_cut.triggered.connect(self.cut_selection)

        act_paste = menu.addAction("📥  Liitä (Paste)")
        act_paste.setShortcut(QKeySequence.StandardKey.Paste)
        cb = QGuiApplication.clipboard()
        can_paste = bool(cb and cb.text())
        act_paste.setEnabled(can_paste)
        act_paste.triggered.connect(self.paste_from_clipboard)

        act_delete = menu.addAction("🗑️  Poista teksti (Delete)")
        act_delete.setEnabled(has_selection)
        act_delete.triggered.connect(self.delete_selection)

        menu.addSeparator()

        act_bold = menu.addAction("𝐁  Lihavoi (Bold)")
        act_bold.setShortcut("Ctrl+B")
        act_bold.setEnabled(has_selection)
        act_bold.triggered.connect(self.toggle_bold)

        act_italic = menu.addAction("𝐼  Kursivoi (Italic)")
        act_italic.setShortcut("Ctrl+I")
        act_italic.setEnabled(has_selection)
        act_italic.triggered.connect(self.toggle_italic)

        size_menu = menu.addMenu("🔠  Fonttikoko...")
        for sz in (8, 9, 10, 11, 12, 14, 16, 18, 24, 36):
            sz_act = size_menu.addAction(f"{sz} pt")
            sz_act.triggered.connect(lambda checked, s=sz: self.request_fontsize.emit(float(s)))

        menu.addSeparator()

        act_p_mode = menu.addAction("📄  Kappaletila (Koko lohko)")
        act_p_mode.setCheckable(True)
        act_p_mode.setChecked(self.selection_mode == "paragraph")
        act_p_mode.triggered.connect(lambda: self.set_selection_mode("paragraph"))

        act_s_mode = menu.addAction("📏  Rivitila (Yksittäinen rivi)")
        act_s_mode.setCheckable(True)
        act_s_mode.setChecked(self.selection_mode == "span")
        act_s_mode.triggered.connect(lambda: self.set_selection_mode("span"))

        menu.addSeparator()

        act_zoom_in = menu.addAction("🔍  Lähennä (+)")
        act_zoom_in.triggered.connect(lambda: self.set_zoom(self.zoom_factor * 1.25))

        act_zoom_out = menu.addAction("🔍  Loitonna (-)")
        act_zoom_out.triggered.connect(lambda: self.set_zoom(self.zoom_factor / 1.25))

        act_fonts = menu.addAction("🔤  Dokumentin kirjasimet...")
        act_fonts.triggered.connect(self.request_font_manager.emit)

        menu.addSeparator()

        # Sivun marginaalit ja mitat
        act_margins = menu.addAction("📐  Sivun marginaalit ja arkkikoko...")
        act_margins.triggered.connect(self.request_margins_dialog.emit)

        # Taustakortti valitulle tekstille
        if self.selected_block:
            act_bg_card = menu.addAction("🔲  Lisää taustalaatikko tälle tekstille (Tekstin alle)")
            act_bg_card.triggered.connect(self.add_background_card_to_selected_block)

        # Lisää muoto -alivalikko
        shape_menu = menu.addMenu("➕  Lisää muoto...")
        act_add_rect_bg = shape_menu.addAction("🔲  Suorakulmio (Tekstin alle / Tausta)")
        act_add_rect_bg.triggered.connect(lambda: self._quick_add_shape("rect", overlay=False))
        act_add_rect_fg = shape_menu.addAction("🔲  Suorakulmio (Tekstin päälle)")
        act_add_rect_fg.triggered.connect(lambda: self._quick_add_shape("rect", overlay=True))
        act_add_round_bg = shape_menu.addAction("🔲  Pyöristetty laatikko (Tekstin alle)")
        act_add_round_bg.triggered.connect(lambda: self._quick_add_shape("rounded_rect", overlay=False))
        act_add_circle = shape_menu.addAction("🔘  Ympyrä / Ellipsi (Tekstin päälle)")
        act_add_circle.triggered.connect(lambda: self._quick_add_shape("circle", overlay=True))
        act_add_circle_bg = shape_menu.addAction("🔘  Ympyrä / Ellipsi (Tekstin alle)")
        act_add_circle_bg.triggered.connect(lambda: self._quick_add_shape("circle", overlay=False))
        act_add_arrow = shape_menu.addAction("➔  Nuoli")
        act_add_arrow.triggered.connect(lambda: self._quick_add_shape("arrow", overlay=True))
        act_add_line = shape_menu.addAction("━  Viiva")
        act_add_line.triggered.connect(lambda: self._quick_add_shape("line", overlay=True))

        menu.exec(event.globalPos())

    def keyPressEvent(self, event: QKeyEvent):
        if self.is_drawing_shape:
            if event.key() in (Qt.Key.Key_Control, Qt.Key.Key_Shift):
                pos = self._constrain_shape_point(self.shape_start_pos, self.current_mouse_pos, self.active_tool)
                self.shape_current_pos = pos
                self.update()

        # Nuolinäppäinsiirto valitulle muodolle
        if self.selected_shape_id and self.doc_model and event.key() in (
            Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Up, Qt.Key.Key_Down
        ):
            step = 10.0 if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else 1.0
            dx, dy = 0.0, 0.0
            if event.key() == Qt.Key.Key_Left:
                dx = -step
            elif event.key() == Qt.Key.Key_Right:
                dx = step
            elif event.key() == Qt.Key.Key_Up:
                dy = -step
            elif event.key() == Qt.Key.Key_Down:
                dy = step
            self.doc_model.move_shape(self.current_page_idx, self.selected_shape_id, dx, dy, push_undo=True)
            self.refresh_page()
            self.update()
            event.accept()
            return

        if event.key() == Qt.Key.Key_V and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.set_active_tool("move")
            self.tool_switched.emit("move")
            event.accept()
            return

        if event.key() == Qt.Key.Key_T and not (event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            self.set_active_tool("textbox")
            self.tool_switched.emit("textbox")
            event.accept()
            return

        if event.matches(QKeySequence.StandardKey.Undo) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Z
        ):
            self.request_undo.emit()
            event.accept()
            return
        elif event.matches(QKeySequence.StandardKey.Redo) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and (
                event.key() == Qt.Key.Key_Y or (event.modifiers() & Qt.KeyboardModifier.ShiftModifier and event.key() == Qt.Key.Key_Z)
            )
        ):
            self.request_redo.emit()
            event.accept()
            return
        elif event.matches(QKeySequence.StandardKey.Copy) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C
        ):
            self.copy_selection_to_clipboard()
            event.accept()
            return
        elif event.matches(QKeySequence.StandardKey.Cut) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_X
        ):
            self.cut_selection()
            event.accept()
            return
        elif event.matches(QKeySequence.StandardKey.Paste) or (
            event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_V
        ):
            self.paste_from_clipboard()
            event.accept()
            return
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.delete_selection()
            event.accept()
            return
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_B:
            self.toggle_bold()
            event.accept()
            return
        elif event.modifiers() & Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_I:
            self.toggle_italic()
            event.accept()
            return
        elif event.key() == Qt.Key.Key_Escape:
            if self.selected_shape_id:
                self.select_shape(None)
            self.clear_selection()
            self.set_active_tool("move")
            self.tool_switched.emit("move")
            event.accept()
            return
        super().keyPressEvent(event)

    def leaveEvent(self, event):
        self.setCursor(Qt.CursorShape.ArrowCursor)
        super().leaveEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.set_zoom(self.zoom_factor * 1.15)
            elif delta < 0:
                self.set_zoom(self.zoom_factor / 1.15)
            event.accept()
        else:
            super().wheelEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # 1. Piirretään taustasivu
        if self.page_pixmap:
            painter.drawPixmap(0, 0, self.page_pixmap)
        else:
            painter.fillRect(self.rect(), QColor(245, 245, 245))
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Ei dokumenttia avattuna")
            painter.end()
            return

        # 1.1 Marginaaliohjaimet (Margin Guides - katkoviivat)
        if self.show_margin_guides and self.doc_model and self.doc_model.is_open:
            boxes = self.doc_model.get_page_boxes(self.current_page_idx)
            if boxes:
                cbox = boxes.get("cropbox")
                if cbox:
                    guide_pen = QPen(QColor(52, 152, 219, 130), 1.0, Qt.PenStyle.DashLine)
                    painter.save()
                    painter.setPen(guide_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    guide_r = QRectF(
                        cbox[0] * self.zoom_factor,
                        cbox[1] * self.zoom_factor,
                        (cbox[2] - cbox[0]) * self.zoom_factor,
                        (cbox[3] - cbox[1]) * self.zoom_factor
                    )
                    painter.drawRect(guide_r)
                    painter.restore()

        # 1.2 Parhaillaan piirrettävän muodon kuminauhaesikatselu (Rubber-Band Shape Preview)
        if self.is_drawing_shape and self.shape_start_pos and self.shape_current_pos:
            painter.save()
            s_color = QColor(
                int(self.shape_stroke_color[0] * 255),
                int(self.shape_stroke_color[1] * 255),
                int(self.shape_stroke_color[2] * 255),
                int(self.shape_stroke_opacity * 255)
            ) if self.shape_stroke_color else QColor(0, 0, 0, 0)
            pen = QPen(s_color, max(1.0, self.shape_stroke_width * self.zoom_factor * 0.7), Qt.PenStyle.SolidLine)
            painter.setPen(pen)

            if getattr(self, "shape_has_fill", True) and self.shape_fill_color:
                f_color = QColor(
                    int(self.shape_fill_color[0] * 255),
                    int(self.shape_fill_color[1] * 255),
                    int(self.shape_fill_color[2] * 255),
                    int(self.shape_fill_opacity * 255)
                )
                painter.setBrush(QBrush(f_color))
            else:
                painter.setBrush(Qt.BrushStyle.NoBrush)

            p1 = self.shape_start_pos
            p2 = self.shape_current_pos
            r_box = QRectF(p1, p2).normalized()

            if self.active_tool in ("rect", "textbox"):
                painter.drawRect(r_box)
                if self.active_tool == "textbox":
                    painter.save()
                    painter.setPen(QColor(56, 189, 248, 220))
                    painter.drawText(r_box, Qt.AlignmentFlag.AlignCenter, "🔤 Tekstilaatikko")
                    painter.restore()
            elif self.active_tool == "rounded_rect":
                scaled_rad = self.shape_radius * self.zoom_factor * 0.5
                painter.drawRoundedRect(r_box, scaled_rad, scaled_rad)
            elif self.active_tool == "circle":
                painter.drawEllipse(r_box)
            elif self.active_tool == "arrow":
                painter.drawLine(p1, p2)
                dx = p2.x() - p1.x()
                dy = p2.y() - p1.y()
                length = math.hypot(dx, dy)
                if length >= 5:
                    angle = math.atan2(dy, dx)
                    head_len = min(30.0, max(10.0, self.shape_stroke_width * self.zoom_factor * 3.0))
                    head_angle = 0.45
                    w1 = QPointF(p2.x() - head_len * math.cos(angle - head_angle), p2.y() - head_len * math.sin(angle - head_angle))
                    w2 = QPointF(p2.x() - head_len * math.cos(angle + head_angle), p2.y() - head_len * math.sin(angle + head_angle))
                    arrow_poly = QPolygonF([w1, p2, w2])
                    painter.setBrush(QBrush(s_color))
                    painter.drawPolygon(arrow_poly)
            elif self.active_tool == "line":
                painter.drawLine(p1, p2)

            painter.restore()

        # 2. Word-tason sininen tekstivalinta ("mustamaalaus")
        if self.selected_text_rects:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 120, 215, 105))  # Word / Acrobat valintasininen
            for r in self.selected_text_rects:
                painter.drawRoundedRect(r, 2.0, 2.0)
            painter.restore()

        # Raahauksen suorakaide jos vedetään valintaa kankaalla
        if self.is_selecting_text and self.select_start_pos and self.current_mouse_pos:
            drag_rect = QRectF(self.select_start_pos, self.current_mouse_pos).normalized()
            if drag_rect.width() > 3 or drag_rect.height() > 3:
                painter.save()
                painter.setPen(QPen(QColor(0, 120, 215, 170), 1.0, Qt.PenStyle.DashLine))
                painter.setBrush(QColor(52, 152, 219, 22))
                painter.drawRect(drag_rect)
                painter.restore()

        # 2. Kappaletilan piirto (Oletus)
        if self.selection_mode == "paragraph":
            # Hover-kehys kappaleelle (sininen katkoviiva)
            if self.hover_block and self.hover_block != self.selected_block and not self.is_resizing:
                pen = QPen(QColor(41, 128, 185, 190), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(QColor(52, 152, 219, 20))
                r = self.hover_block["bbox"]
                rect_q = QRectF(
                    r[0] * self.zoom_factor,
                    r[1] * self.zoom_factor,
                    (r[2] - r[0]) * self.zoom_factor,
                    (r[3] - r[1]) * self.zoom_factor
                )
                painter.drawRect(rect_q)

            # Valittu kappale (Acrobat-tyylinen selkeä valintakehys ja 8 kahvaa)
            if self.selected_block:
                pen = QPen(QColor(31, 110, 165, 240), 2.0, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.setBrush(QColor(52, 152, 219, 15))
                r = self.selected_block["bbox"]
                x = r[0] * self.zoom_factor
                y = r[1] * self.zoom_factor
                w = (r[2] - r[0]) * self.zoom_factor
                h = (r[3] - r[1]) * self.zoom_factor
                rect_q = QRectF(x, y, w, h)
                painter.drawRect(rect_q)

                # Piirretään Acrobat-tyyliset 8 raahauskahvaa (4 kulmaa + 4 sivua)
                handle_pen = QPen(QColor(31, 110, 165, 255), 1.2)
                handle_brush = QColor(255, 255, 255)
                painter.setPen(handle_pen)
                painter.setBrush(handle_brush)
                hs = 7.0  # Kahvan koko pikseleinä
                handles = self._get_block_handles(self.selected_block)
                for h_pt in handles.values():
                    painter.drawRect(QRectF(h_pt.x() - hs / 2.0, h_pt.y() - hs / 2.0, hs, hs))

        # 3. Rivitilan piirto (Span mode)
        else:
            # Hover-kehys (sininen katkoviiva)
            if self.hover_span and self.hover_span != self.selected_span:
                pen = QPen(QColor(30, 144, 255, 180), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r = self.hover_span["bbox"]
                painter.drawRect(QRectF(
                    r[0] * self.zoom_factor,
                    r[1] * self.zoom_factor,
                    (r[2] - r[0]) * self.zoom_factor,
                    (r[3] - r[1]) * self.zoom_factor
                ))

            # Valittu jakso ja perusviiva (baseline)
            if self.selected_span:
                pen = QPen(QColor(230, 60, 30, 230), 2.0, Qt.PenStyle.SolidLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                r = self.selected_span["bbox"]
                painter.drawRect(QRectF(
                    r[0] * self.zoom_factor,
                    r[1] * self.zoom_factor,
                    (r[2] - r[0]) * self.zoom_factor,
                    (r[3] - r[1]) * self.zoom_factor
                ))

                # Perusviiva (Baseline Indicator) - vihreä tarkkuusviiva
                origin = self.selected_span.get("origin")
                if origin:
                    base_pen = QPen(QColor(46, 204, 113, 240), 1.5, Qt.PenStyle.SolidLine)
                    painter.setPen(base_pen)
                    base_y = origin[1] * self.zoom_factor
                    x_start = (r[0] - 4.0) * self.zoom_factor
                    x_end = (r[2] + 4.0) * self.zoom_factor
                    painter.drawLine(QPointF(x_start, base_y), QPointF(x_end, base_y))

        # 4. Valitun muodon valintakehys ja kahvat (Shape selection bounding box & handles)
        if self.selected_shape_id and self.doc_model:
            cur_shape = self.doc_model.get_shape(self.current_page_idx, self.selected_shape_id)
            if cur_shape:
                painter.save()
                sel_pen = QPen(QColor(16, 110, 230, 240), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(sel_pen)
                painter.setBrush(QColor(52, 152, 219, 25))
                bbox = self.doc_model._compute_shape_bbox(cur_shape)
                dx_px = 0.0
                dy_px = 0.0
                if self.is_dragging_shape and (self.drag_shape_delta[0] != 0.0 or self.drag_shape_delta[1] != 0.0):
                    dx_px = self.drag_shape_delta[0] * self.zoom_factor
                    dy_px = self.drag_shape_delta[1] * self.zoom_factor

                rot = float(cur_shape.get("rotation", 0.0))
                cx = (bbox[0] + bbox[2]) / 2.0 * self.zoom_factor + dx_px
                cy = (bbox[1] + bbox[3]) / 2.0 * self.zoom_factor + dy_px

                if abs(rot) > 0.001:
                    painter.translate(cx, cy)
                    painter.rotate(rot)
                    painter.translate(-cx, -cy)

                sel_pen = QPen(QColor(16, 110, 230, 240), 1.5, Qt.PenStyle.DashLine)
                painter.setPen(sel_pen)
                painter.setBrush(QColor(52, 152, 219, 25))

                rect_q = QRectF(
                    bbox[0] * self.zoom_factor - 3.0 + dx_px,
                    bbox[1] * self.zoom_factor - 3.0 + dy_px,
                    (bbox[2] - bbox[0]) * self.zoom_factor + 6.0,
                    (bbox[3] - bbox[1]) * self.zoom_factor + 6.0
                )
                painter.drawRect(rect_q)

                if self.is_dragging_shape and (dx_px != 0 or dy_px != 0):
                    painter.setPen(QColor(16, 185, 129, 220))
                    painter.setBrush(QColor(16, 185, 129, 35))
                    painter.drawRoundedRect(rect_q, 4.0, 4.0)
                    if cur_shape.get("text"):
                        painter.setPen(QColor(248, 250, 252, 230))
                        painter.drawText(rect_q, Qt.AlignmentFlag.AlignCenter, cur_shape.get("text"))

                # Kiertovarsi ja pyöreä kiertokahva (Stem line & round rotation handle)
                stem_pen = QPen(QColor(16, 185, 129, 220), 1.5, Qt.PenStyle.SolidLine)
                painter.setPen(stem_pen)
                top_mid = QPointF(cx, rect_q.top())
                rot_pos = QPointF(cx, rect_q.top() - 25.0)
                painter.drawLine(top_mid, rot_pos)

                painter.setPen(QPen(QColor(5, 150, 105, 255), 1.5))
                painter.setBrush(QColor(209, 250, 229, 255))
                painter.drawEllipse(rot_pos, 7.0, 7.0)
                painter.setBrush(QColor(16, 185, 129, 255))
                painter.drawEllipse(rot_pos, 3.0, 3.0)

                # Raahauskahvat
                h_pen = QPen(QColor(16, 110, 230, 255), 1.2)
                h_brush = QColor(255, 255, 255)
                painter.setPen(h_pen)
                painter.setBrush(h_brush)
                hs = 8.0

                stype = cur_shape.get("type", "rect")
                if stype in ("arrow", "line"):
                    geom = cur_shape.get("geometry")
                    p1_px = QPointF(geom[0][0] * self.zoom_factor + dx_px, geom[0][1] * self.zoom_factor + dy_px)
                    p2_px = QPointF(geom[1][0] * self.zoom_factor + dx_px, geom[1][1] * self.zoom_factor + dy_px)
                    painter.drawRect(QRectF(p1_px.x() - hs / 2.0, p1_px.y() - hs / 2.0, hs, hs))
                    painter.drawRect(QRectF(p2_px.x() - hs / 2.0, p2_px.y() - hs / 2.0, hs, hs))
                else:
                    local_handles = [
                        QPointF(rect_q.left(), rect_q.top()),
                        QPointF(rect_q.right(), rect_q.top()),
                        QPointF(rect_q.left(), rect_q.bottom()),
                        QPointF(rect_q.right(), rect_q.bottom()),
                        QPointF(rect_q.right(), cy),
                        QPointF(rect_q.left(), cy),
                        QPointF(cx, rect_q.top()),
                        QPointF(cx, rect_q.bottom()),
                    ]
                    for h_pt in local_handles:
                        painter.drawRect(QRectF(h_pt.x() - hs / 2.0, h_pt.y() - hs / 2.0, hs, hs))

                painter.restore()

                # Jos kierto on käynnissä, näytetään kursorin vieressä selkeä kulmalukema
                if getattr(self, "is_rotating_shape", False):
                    badge_rect = QRectF(cx - 35, rect_q.top() - 55, 70, 22)
                    painter.setPen(QColor(16, 185, 129, 240))
                    painter.setBrush(QColor(15, 23, 42, 230))
                    painter.drawRoundedRect(badge_rect, 4.0, 4.0)
                    painter.setPen(QColor(248, 250, 252))
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, f"{rot:.1f}°")

        painter.end()
