"""
PDF-dokumenttimalli ja elinkaarenhallinta (PDF Document Model).
Vastaa tiedostojen avaamisesta, sivujen renderöinnistä, tekstin in-place -redaktiosta,
vektorigrafiikan säilytyksestä ja kumoa/tee uudelleen (Undo/Redo) -toiminnallisuudesta.
"""

import os
import re
import math
import copy
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
import fitz
from PyQt6.QtGui import QImage

from .font_resolver import FontconfigResolver, FontMatchResult, FontDownloader, LOCAL_FONTS_DIR
from .layout_engine import LayoutEngine, FitStrategy, OverflowReport


@dataclass
class EditOperation:
    """Yksittäinen suoritettu tekstinmuokkausoperaatio."""
    page_idx: int
    span_id: str
    original_text: str
    new_text: str
    bbox: Tuple[float, float, float, float]
    origin: Tuple[float, float]
    font_name: str
    fontsize: float
    color_rgb: Tuple[float, float, float]
    font_path: Optional[str]
    fit_strategy: str


class PDFDocumentModel:
    """
    Korkeatasoinen PDF-dokumentin hallintaluokka.
    Toteuttaa 'PDF-Rakenne- & Eristysrakentajan' vaatimukset:
    - 100 % offline
    - Vektorigrafiikan ja taustakuvien suojaus (images=0, graphics=0)
    - Puhdas XRef-tallennus
    - In-memory Undo/Redo -tuki
    - Tasojen ja objektien (shapes & layers) hallinta
    """

    MAX_HISTORY_STATES = 25

    def __init__(self):
        self.doc: Optional[fitz.Document] = None
        self.base_doc: Optional[fitz.Document] = None
        self.file_path: str = ""
        self.undo_stack: List[Any] = []
        self.redo_stack: List[Any] = []
        self.operations_history: List[EditOperation] = []
        self.page_shapes: Dict[int, List[Dict[str, Any]]] = {}
        self.active_editing_shape_id: Optional[str] = None
        self._next_shape_id: int = 1
        self._next_group_id: int = 1

    @property
    def is_open(self) -> bool:
        return self.doc is not None and not self.doc.is_closed

    @property
    def page_count(self) -> int:
        return len(self.doc) if self.is_open else 0

    def open(self, file_path: str):
        """Avaa PDF-tiedoston paikalliselta levyltä."""
        if not os.path.isfile(file_path):
            raise FileNotFoundError(f"Tiedostoa ei löydy: {file_path}")

        # Suljetaan mahdollinen aiempi dokumentti
        self.close()

        doc = fitz.open(file_path)
        if doc.is_encrypted:
            doc.close()
            raise PermissionError("Dokumentti on salattu. Avaaminen vaatii salasanan.")

        self.doc = doc
        self.base_doc = fitz.open(stream=self.doc.tobytes(garbage=0, deflate=False), filetype="pdf")
        self.file_path = file_path
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.operations_history.clear()
        self.page_shapes.clear()
        self._next_shape_id = 1
        self._push_undo_state()
        try:
            self.extract_document_fonts()
        except Exception:
            pass

    def close(self):
        """Sulkee avoimen dokumentin ja vapauttaa resurssit."""
        if self.doc and not self.doc.is_closed:
            self.doc.close()
        self.doc = None
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.close()
        self.base_doc = None
        self.file_path = ""
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.operations_history.clear()
        self.page_shapes.clear()

    def _ensure_base_doc(self):
        """Varmistaa että base_doc on alustettu ja synkronoitu."""
        if not self.is_open:
            return
        if self.base_doc is None or self.base_doc.is_closed:
            self.base_doc = fitz.open(stream=self.doc.tobytes(garbage=0, deflate=False), filetype="pdf")

    def _sync_base_doc_from_doc(self, page_idx: int):
        """Synkronoi sivun teksti base_doc-pohjaan, jotta myöhemmät muoto-operaatiot eivät hävitä tekstiä."""
        self._ensure_base_doc()
        if self.base_doc and not self.base_doc.is_closed and page_idx < len(self.base_doc):
            # Jos sivulla ei ole dynaamisia muotoja, synkronoidaan sivu suoraan base_doc:iin
            if not self.page_shapes.get(page_idx):
                self.base_doc.delete_page(page_idx)
                self.base_doc.insert_pdf(self.doc, from_page=page_idx, to_page=page_idx, start_at=page_idx)

    def _push_undo_state(self):
        """Tallentaa dokumentin nykytilan muistiin peruutusta varten."""
        if not self.is_open:
            return
        self._ensure_base_doc()
        state_bytes = self.doc.tobytes(garbage=0, deflate=False)
        base_bytes = self.base_doc.tobytes(garbage=0, deflate=False) if (self.base_doc and not self.base_doc.is_closed) else state_bytes
        shapes_copy = copy.deepcopy(self.page_shapes)
        self.undo_stack.append((state_bytes, base_bytes, shapes_copy, self._next_shape_id, self._next_group_id))
        if len(self.undo_stack) > self.MAX_HISTORY_STATES:
            self.undo_stack.pop(0)

    def can_undo(self) -> bool:
        return len(self.undo_stack) > 1

    def can_redo(self) -> bool:
        return len(self.redo_stack) > 0

    def _restore_state(self, state: Any):
        """Palauttaa tallennetun tilan muistista."""
        if isinstance(state, tuple):
            doc_bytes, base_bytes, shapes_copy, next_s_id, next_g_id = state
            if self.doc and not self.doc.is_closed:
                self.doc.close()
            if self.base_doc and not self.base_doc.is_closed:
                self.base_doc.close()
            self.doc = fitz.open(stream=doc_bytes, filetype="pdf")
            self.base_doc = fitz.open(stream=base_bytes, filetype="pdf")
            self.page_shapes = copy.deepcopy(shapes_copy)
            self._next_shape_id = next_s_id
            self._next_group_id = next_g_id
        elif isinstance(state, bytes):
            if self.doc and not self.doc.is_closed:
                self.doc.close()
            self.doc = fitz.open(stream=state, filetype="pdf")
            if self.base_doc and not self.base_doc.is_closed:
                self.base_doc.close()
            self.base_doc = fitz.open(stream=state, filetype="pdf")

    def undo(self) -> bool:
        """Palauttaa dokumentin edelliseen tallennettuun tilaan."""
        if not self.can_undo():
            return False

        current_state = self.undo_stack.pop()
        self.redo_stack.append(current_state)

        target_state = self.undo_stack[-1]
        self._restore_state(target_state)
        if self.operations_history:
            self.operations_history.pop()
        return True

    def redo(self) -> bool:
        """Tekee peruutuksen uudelleen."""
        if not self.can_redo():
            return False

        target_state = self.redo_stack.pop()
        self.undo_stack.append(target_state)
        self._restore_state(target_state)
        return True

    def move_page(self, from_idx: int, to_idx: int):
        """Siirtää sivun indeksistä from_idx indeksiin to_idx."""
        if not self.is_open:
            return
        if from_idx == to_idx:
            return
        if 0 <= from_idx < self.page_count and 0 <= to_idx < self.page_count:
            self._ensure_base_doc()
            layout = list(range(self.page_count))
            p = layout.pop(from_idx)
            layout.insert(to_idx, p)
            self.doc.select(layout)
            if self.base_doc and not self.base_doc.is_closed:
                self.base_doc.select(layout)

            new_page_shapes = {}
            for new_idx, old_idx in enumerate(layout):
                if old_idx in self.page_shapes:
                    new_page_shapes[new_idx] = self.page_shapes[old_idx]
            self.page_shapes = new_page_shapes

            self._push_undo_state()
            self.redo_stack.clear()

    def insert_pdf_pages(self, file_path: str, at_idx: int, from_page: int = 0, to_page: int = -1) -> int:
        """Liittää toisen PDF-dokumentin sivut haluttuun kohtaan (at_idx). Palauttaa lisättyjen sivujen määrän."""
        if not self.is_open or not os.path.isfile(file_path):
            return 0
        src_doc = fitz.open(file_path)
        if src_doc.is_encrypted:
            src_doc.close()
            raise PermissionError("Liitettävä PDF on salattu.")
        
        src_count = len(src_doc)
        if src_count == 0:
            src_doc.close()
            return 0

        self._ensure_base_doc()
        start_at = at_idx if 0 <= at_idx <= self.page_count else -1
        self.doc.insert_pdf(src_doc, from_page=from_page, to_page=to_page, start_at=start_at)
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.insert_pdf(src_doc, from_page=from_page, to_page=to_page, start_at=start_at)
        src_doc.close()

        actual_insert_idx = start_at if start_at >= 0 else (self.page_count - src_count)
        new_page_shapes = {}
        for p_idx, shapes in self.page_shapes.items():
            if p_idx >= actual_insert_idx:
                new_page_shapes[p_idx + src_count] = shapes
            else:
                new_page_shapes[p_idx] = shapes
        self.page_shapes = new_page_shapes

        self._push_undo_state()
        self.redo_stack.clear()
        return src_count

    def insert_blank_page(self, at_idx: int, width: float = 595.0, height: float = 842.0):
        """Lisää uuden tyhjän sivun kohtaan at_idx."""
        if not self.is_open:
            return
        self._ensure_base_doc()
        pno = at_idx if 0 <= at_idx <= self.page_count else -1
        self.doc.new_page(pno=pno, width=width, height=height)
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.new_page(pno=pno, width=width, height=height)

        target_pno = pno if pno >= 0 else (self.page_count - 1)
        new_page_shapes = {}
        for p_idx, shapes in self.page_shapes.items():
            if p_idx >= target_pno:
                new_page_shapes[p_idx + 1] = shapes
            else:
                new_page_shapes[p_idx] = shapes
        self.page_shapes = new_page_shapes

        self._push_undo_state()
        self.redo_stack.clear()

    def delete_page(self, page_idx: int) -> bool:
        """Poistaa sivun. Dokumenttiin täytyy jäädä vähintään 1 sivu."""
        return self.delete_pages([page_idx]) == 1

    def delete_pages(self, page_indices: List[int]) -> int:
        """
        Poistaa useita sivuja kerralla atomisesti.
        Dokumenttiin täytyy jäädä vähintään 1 sivu.
        Palauttaa poistettujen sivujen lukumäärän.
        """
        if not self.is_open or not page_indices:
            return 0
        to_delete = set(i for i in page_indices if 0 <= i < self.page_count)
        if not to_delete:
            return 0
        if len(to_delete) >= self.page_count:
            # Kaikkia sivuja ei voi poistaa
            return 0

        self._ensure_base_doc()
        layout = [i for i in range(self.page_count) if i not in to_delete]
        self.doc.select(layout)
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.select(layout)

        new_page_shapes = {}
        for new_idx, old_idx in enumerate(layout):
            if old_idx in self.page_shapes:
                new_page_shapes[new_idx] = self.page_shapes[old_idx]
        self.page_shapes = new_page_shapes

        self._push_undo_state()
        self.redo_stack.clear()
        return len(to_delete)

    def rotate_page(self, page_idx: int, angle: int = 90):
        """Kiertää sivua (oletus 90 astetta myötäpäivään)."""
        self.rotate_pages([page_idx], angle)

    def rotate_pages(self, page_indices: List[int], angle: int = 90) -> int:
        """
        Kiertää useita sivuja kerralla (oletus 90 astetta myötäpäivään).
        Palauttaa kierrettyjen sivujen lukumäärän.
        """
        if not self.is_open or not page_indices:
            return 0
        target_indices = sorted(set(i for i in page_indices if 0 <= i < self.page_count))
        if not target_indices:
            return 0

        self._ensure_base_doc()
        for idx in target_indices:
            page = self.doc[idx]
            page.set_rotation((page.rotation + angle) % 360)
            if self.base_doc and not self.base_doc.is_closed and idx < len(self.base_doc):
                bpage = self.base_doc[idx]
                bpage.set_rotation((bpage.rotation + angle) % 360)

        self._push_undo_state()
        self.redo_stack.clear()
        return len(target_indices)

    def duplicate_page(self, page_idx: int):
        """Monistaa valitun sivun ja sijoittaa sen heti valitun sivun perään."""
        self.duplicate_pages([page_idx])

    def duplicate_pages(self, page_indices: List[int]) -> int:
        """
        Monistaa valitut sivut kunkin sivun perään.
        Palauttaa monistettujen sivujen lukumäärän.
        """
        if not self.is_open or not page_indices:
            return 0
        selected_set = set(i for i in page_indices if 0 <= i < self.page_count)
        if not selected_set:
            return 0

        self._ensure_base_doc()
        layout = []
        for i in range(self.page_count):
            layout.append(i)
            if i in selected_set:
                layout.append(i)

        self.doc.select(layout)
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.select(layout)

        new_page_shapes = {}
        for new_idx, old_idx in enumerate(layout):
            if old_idx in self.page_shapes:
                new_page_shapes[new_idx] = copy.deepcopy(self.page_shapes[old_idx])
        self.page_shapes = new_page_shapes

        self._push_undo_state()
        self.redo_stack.clear()
        return len(selected_set)

    def move_pages(self, page_indices: List[int], target_position: str, target_idx: Optional[int] = None) -> bool:
        """
        Siirtää valitut sivut uuteen paikkaan:
        - target_position: 'start' (alkuun), 'end' (loppuun), 'after' (kohdan jälkeen), 'before' (ennen kohtaa)
        """
        if not self.is_open or not page_indices:
            return False
        selected_set = set(i for i in page_indices if 0 <= i < self.page_count)
        if not selected_set:
            return False

        self._ensure_base_doc()
        selected_ordered = [i for i in range(self.page_count) if i in selected_set]
        remaining = [i for i in range(self.page_count) if i not in selected_set]

        if not remaining:
            # Kaikki sivut valittuna, järjestys ei muutu
            return False

        if target_position == "start":
            layout = selected_ordered + remaining
        elif target_position == "end":
            layout = remaining + selected_ordered
        elif target_position in ("before", "after") and target_idx is not None:
            clamped_target = max(0, min(target_idx, self.page_count - 1))
            new_layout = []
            placed = False
            for p in remaining:
                if p == clamped_target:
                    if target_position == "before":
                        new_layout.extend(selected_ordered)
                        new_layout.append(p)
                    else:
                        new_layout.append(p)
                        new_layout.extend(selected_ordered)
                    placed = True
                else:
                    new_layout.append(p)
            if not placed:
                new_layout.extend(selected_ordered)
            layout = new_layout
        else:
            return False

        if layout == list(range(self.page_count)):
            return False

        self.doc.select(layout)
        if self.base_doc and not self.base_doc.is_closed:
            self.base_doc.select(layout)

        new_page_shapes = {}
        for new_idx, old_idx in enumerate(layout):
            if old_idx in self.page_shapes:
                new_page_shapes[new_idx] = self.page_shapes[old_idx]
        self.page_shapes = new_page_shapes

        self._push_undo_state()
        self.redo_stack.clear()
        return True

    def extract_pages_to_file(self, page_indices: List[int], output_path: str) -> bool:
        """
        Purkaa valitut sivut uuteen erilliseen PDF-tiedostoon tallentaen sen output_path-polkuun.
        """
        if not self.is_open or not page_indices:
            return False
        selected_ordered = sorted(set(i for i in page_indices if 0 <= i < self.page_count))
        if not selected_ordered:
            return False

        new_doc = fitz.open()
        for idx in selected_ordered:
            new_doc.insert_pdf(self.doc, from_page=idx, to_page=idx)
        new_doc.save(output_path)
        new_doc.close()
        return True

    def get_page_boxes(self, page_idx: int) -> Dict[str, Any]:
        """Palauttaa sivun laatikoiden ja marginaalien mitat pisteinä ja millimetreinä."""
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return {}
        page = self.doc[page_idx]
        mbox = tuple(page.mediabox)
        cbox = tuple(page.cropbox)
        pt_to_mm = 25.4 / 72.0

        w_pt = cbox[2] - cbox[0]
        h_pt = cbox[3] - cbox[1]
        w_mm = w_pt * pt_to_mm
        h_mm = h_pt * pt_to_mm

        left_pt = cbox[0] - mbox[0]
        top_pt = cbox[1] - mbox[1]
        right_pt = mbox[2] - cbox[2]
        bottom_pt = mbox[3] - cbox[3]

        return {
            "mediabox": mbox,
            "cropbox": cbox,
            "rect": tuple(page.rect),
            "width_pt": w_pt,
            "height_pt": h_pt,
            "width_mm": w_mm,
            "height_mm": h_mm,
            "left_pt": left_pt,
            "top_pt": top_pt,
            "right_pt": right_pt,
            "bottom_pt": bottom_pt,
            "left_mm": left_pt * pt_to_mm,
            "top_mm": top_pt * pt_to_mm,
            "right_mm": right_pt * pt_to_mm,
            "bottom_mm": bottom_pt * pt_to_mm,
        }

    def set_page_margins(
        self,
        page_idx: int,
        left_pt: float,
        top_pt: float,
        right_pt: float,
        bottom_pt: float,
        mode: str = "cropbox",
        apply_to_all: bool = False
    ):
        """
        Asettaa sivun marginaalit ja leikkausrajat.
        mode='cropbox': säätää CropBox-laatikkoa MediaBoxin sisällä (rajaa näkyvää arkkia).
        mode='mediabox': muuttaa MediaBoxia (laajentaa tai pienentää arkin fyysistä kokoa).
        """
        if not self.is_open:
            return

        targets = range(self.page_count) if apply_to_all else [page_idx]
        for idx in targets:
            if idx < 0 or idx >= self.page_count:
                continue
            page = self.doc[idx]
            mbox = page.mediabox
            if mode == "cropbox":
                new_crop = fitz.Rect(
                    mbox[0] + left_pt,
                    mbox[1] + top_pt,
                    mbox[2] - right_pt,
                    mbox[3] - bottom_pt
                )
                if new_crop.width > 20 and new_crop.height > 20:
                    page.set_cropbox(new_crop)
                    if self.base_doc and not self.base_doc.is_closed and idx < len(self.base_doc):
                        self.base_doc[idx].set_cropbox(new_crop)
            elif mode == "mediabox":
                new_media = fitz.Rect(
                    mbox[0] - left_pt,
                    mbox[1] - top_pt,
                    mbox[2] + right_pt,
                    mbox[3] + bottom_pt
                )
                if new_media.width > 20 and new_media.height > 20:
                    page.set_mediabox(new_media)
                    if self.base_doc and not self.base_doc.is_closed and idx < len(self.base_doc):
                        self.base_doc[idx].set_mediabox(new_media)
            self.reconstruct_page_shapes(idx)

        self._push_undo_state()
        self.redo_stack.clear()

    def _render_shape_to_page(self, page: fitz.Page, shape: Dict[str, Any]):
        """Piirtää yksittäisen muodon PyMuPDF-sivulle."""
        shape_type = shape.get("type", "rect")
        geometry = shape.get("geometry")
        fill_color = shape.get("fill_color")
        stroke_color = shape.get("stroke_color", (0.0, 0.0, 0.0))
        fill_opacity = shape.get("fill_opacity", 1.0)
        stroke_opacity = shape.get("stroke_opacity", 1.0)
        stroke_width = shape.get("stroke_width", 1.5)
        radius = shape.get("radius")
        overlay = shape.get("overlay", True)
        rotation = float(shape.get("rotation", 0.0))
        is_rotated = abs(rotation) > 0.001

        if shape_type in ("rect", "rounded_rect", "textbox"):
            rect = fitz.Rect(geometry)
            r_val = None
            if shape_type == "rounded_rect" or (radius is not None and radius > 0):
                min_dim = min(rect.width, rect.height)
                if radius is not None and 0 < radius <= 0.5:
                    r_val = radius
                elif radius is not None and min_dim > 0:
                    r_val = min(0.5, max(0.02, radius / min_dim))
                else:
                    r_val = 0.1

            # Tekstilaatikolla piirretään tausta/reuna vain jos ne on määritelty
            should_draw_box = True
            if shape_type == "textbox" and fill_color is None and (stroke_color is None or stroke_width <= 0):
                should_draw_box = False

            center = fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
            morph = (center, fitz.Matrix(-rotation)) if is_rotated else None

            s = page.new_shape()
            if should_draw_box:
                s.draw_rect(rect, radius=r_val)
                s.finish(
                    color=stroke_color if (stroke_color and stroke_width > 0) else None,
                    fill=fill_color,
                    fill_opacity=fill_opacity,
                    stroke_opacity=stroke_opacity,
                    width=stroke_width,
                    morph=morph
                )

            has_html = bool(shape.get("html") and str(shape.get("html")).strip())
            if not has_html and shape.get("text"):
                self._render_shape_text(page, shape, rect, overlay, morph=morph, shape_obj=s)

            s.commit(overlay=overlay)

            if has_html:
                self._render_shape_text(page, shape, rect, overlay=True if should_draw_box else overlay, morph=morph)

        elif shape_type in ("circle", "oval"):
            rect = fitz.Rect(geometry)
            center = fitz.Point((rect.x0 + rect.x1) / 2.0, (rect.y0 + rect.y1) / 2.0)
            morph = (center, fitz.Matrix(-rotation)) if is_rotated else None

            s = page.new_shape()
            s.draw_oval(rect)
            s.finish(
                color=stroke_color if (stroke_color and stroke_width > 0) else None,
                fill=fill_color,
                fill_opacity=fill_opacity,
                stroke_opacity=stroke_opacity,
                width=stroke_width,
                morph=morph
            )

            has_html = bool(shape.get("html") and str(shape.get("html")).strip())
            if not has_html and shape.get("text"):
                self._render_shape_text(page, shape, rect, overlay, morph=morph, shape_obj=s)

            s.commit(overlay=overlay)

            if has_html:
                self._render_shape_text(page, shape, rect, overlay=True, morph=morph)

        elif shape_type == "arrow":
            p1, p2 = geometry
            center = fitz.Point((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
            morph = (center, fitz.Matrix(-rotation)) if is_rotated else None

            dx = p2[0] - p1[0]
            dy = p2[1] - p1[1]
            length = math.hypot(dx, dy)
            if length >= 1:
                angle = math.atan2(dy, dx)
                head_len = min(25.0, max(8.0, stroke_width * 4.5))
                head_angle = 0.45
                w1 = (p2[0] - head_len * math.cos(angle - head_angle), p2[1] - head_len * math.sin(angle - head_angle))
                w2 = (p2[0] - head_len * math.cos(angle + head_angle), p2[1] - head_len * math.sin(angle + head_angle))
                s = page.new_shape()
                s.draw_line(p1, p2)
                s.finish(color=stroke_color, width=stroke_width, stroke_opacity=stroke_opacity, morph=morph)
                s.draw_polyline([w1, p2, w2, w1])
                s.finish(
                    color=stroke_color,
                    fill=stroke_color,
                    width=max(0.5, stroke_width * 0.5),
                    fill_opacity=fill_opacity if fill_color else stroke_opacity,
                    stroke_opacity=stroke_opacity,
                    morph=morph
                )
                s.commit(overlay=overlay)

        elif shape_type == "line":
            p1, p2 = geometry
            center = fitz.Point((p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0)
            morph = (center, fitz.Matrix(-rotation)) if is_rotated else None
            s = page.new_shape()
            s.draw_line(p1, p2)
            s.finish(color=stroke_color, width=stroke_width, stroke_opacity=stroke_opacity, morph=morph)
            s.commit(overlay=overlay)

    def _render_shape_text(
        self,
        page: fitz.Page,
        shape: Dict[str, Any],
        rect: fitz.Rect,
        overlay: bool = True,
        morph: Optional[Tuple[fitz.Point, fitz.Matrix]] = None,
        shape_obj: Optional[fitz.Shape] = None
    ):
        """Renderöi muodon tai tekstilaatikon sisäisen tekstin PyMuPDF-sivulle."""
        text = str(shape.get("text", "")).strip()
        if not text:
            return

        font_family = shape.get("font_family", "Helvetica")
        font_size = float(shape.get("font_size", 14.0))
        font_bold = bool(shape.get("font_bold", False))
        font_italic = bool(shape.get("font_italic", False))
        text_color = shape.get("text_color", (0.0, 0.0, 0.0))
        text_align = shape.get("text_align", "center")
        vertical_align = shape.get("vertical_align", "middle")
        pad = float(shape.get("text_padding", 4.0))

        align_map = {
            "left": fitz.TEXT_ALIGN_LEFT,
            "center": fitz.TEXT_ALIGN_CENTER,
            "right": fitz.TEXT_ALIGN_RIGHT,
            "justify": fitz.TEXT_ALIGN_JUSTIFY,
        }
        align_code = align_map.get(str(text_align).lower(), fitz.TEXT_ALIGN_CENTER)

        fam_lower = font_family.lower()
        fontname = "helv"
        fontfile = None

        # 1. Ensisijaisesti etsitään todellinen fonttitiedosto (paikallinen, purettu dokumenttifontti tai avoin vastine)
        f_path = None
        f_fam = None
        try:
            f_path, f_fam = FontconfigResolver.resolve_local_font(font_family, font_bold, font_italic)
        except Exception:
            pass

        if f_path and os.path.exists(f_path):
            fontfile = f_path
            clean_name = re.sub(r'[^a-zA-Z0-9_-]', '', f_fam or font_family)
            fontname = clean_name if clean_name else "customfont"
        else:
            # 2. Toissijaisesti käytetään standardeja Base-14 PDF-fontteja
            if "time" in fam_lower or "roman" in fam_lower or "serif" in fam_lower:
                if font_bold and font_italic:
                    fontname = "tibi"
                elif font_bold:
                    fontname = "tibo"
                elif font_italic:
                    fontname = "tiit"
                else:
                    fontname = "times"
            elif "courier" in fam_lower or "mono" in fam_lower:
                if font_bold and font_italic:
                    fontname = "cobi"
                elif font_bold:
                    fontname = "cobo"
                elif font_italic:
                    fontname = "coit"
                else:
                    fontname = "cour"
            elif "helv" in fam_lower or "arial" in fam_lower or "sans" in fam_lower:
                if font_bold and font_italic:
                    fontname = "hebi"
                elif font_bold:
                    fontname = "hebo"
                elif font_italic:
                    fontname = "heit"
                else:
                    fontname = "helv"
            else:
                fontname = "hebo" if font_bold else "helv"

        inner_rect = fitz.Rect(rect.x0 + pad, rect.y0 + pad, rect.x1 - pad, rect.y1 - pad)
        if inner_rect.width <= 5 or inner_rect.height <= 5:
            inner_rect = fitz.Rect(rect)

        # Jos tämä muoto on parhaillaan aktiivisesti muokattavana kankaalla (InlineShapeEditor),
        # ei piirretä sen tekstiä sivupixmapille haamukuvan/tuplatekstin välttämiseksi.
        if getattr(self, "active_editing_shape_id", None) and shape.get("id") == self.active_editing_shape_id:
            return

        # Rikkaan tekstin (HTML / mixed fonts) renderöinti insert_htmlbox-moottorilla
        html = shape.get("html")
        if html and str(html).strip():
            arch = None
            try:
                arch = fitz.Archive()
                has_entries = False
                if hasattr(self, "extracted_fonts_dir") and self.extracted_fonts_dir and os.path.exists(self.extracted_fonts_dir):
                    arch.add(self.extracted_fonts_dir)
                    has_entries = True
                if LOCAL_FONTS_DIR and os.path.exists(LOCAL_FONTS_DIR):
                    arch.add(LOCAL_FONTS_DIR)
                    has_entries = True
                if not has_entries:
                    arch = None
            except Exception:
                arch = None

            rotation = float(shape.get("rotation", 0.0))
            is_rotated = abs(rotation) > 0.001
            try:
                if is_rotated:
                    doc_temp = fitz.open()
                    p_temp = doc_temp.new_page(width=max(10.0, inner_rect.width), height=max(10.0, inner_rect.height))
                    spare, _ = p_temp.insert_htmlbox(
                        fitz.Rect(0, 0, max(10.0, inner_rect.width), max(10.0, inner_rect.height)),
                        html,
                        archive=arch
                    )
                    y_off = 0.0
                    if vertical_align == "middle" and spare > 0:
                        y_off = spare / 2.0
                    elif vertical_align == "bottom" and spare > 0:
                        y_off = spare

                    if y_off > 0:
                        doc_temp.close()
                        doc_temp = fitz.open()
                        p_temp = doc_temp.new_page(width=max(10.0, inner_rect.width), height=max(10.0, inner_rect.height))
                        p_temp.insert_htmlbox(
                            fitz.Rect(0, y_off, max(10.0, inner_rect.width), max(10.0, inner_rect.height)),
                            html,
                            archive=arch
                        )

                    rad = math.radians(rotation)
                    cos_a = abs(math.cos(rad))
                    sin_a = abs(math.sin(rad))
                    w = max(10.0, inner_rect.width)
                    h = max(10.0, inner_rect.height)
                    cx = (inner_rect.x0 + inner_rect.x1) / 2.0
                    cy = (inner_rect.y0 + inner_rect.y1) / 2.0
                    bbox_w = w * cos_a + h * sin_a
                    bbox_h = w * sin_a + h * cos_a
                    target_bbox = fitz.Rect(cx - bbox_w / 2.0, cy - bbox_h / 2.0, cx + bbox_w / 2.0, cy + bbox_h / 2.0)

                    page.show_pdf_page(target_bbox, doc_temp, 0, rotate=-rotation, overlay=overlay)
                    doc_temp.close()
                    return
                else:
                    if vertical_align in ("middle", "bottom"):
                        try:
                            doc_temp = fitz.open()
                            p_temp = doc_temp.new_page(width=max(10.0, inner_rect.width), height=max(10.0, inner_rect.height))
                            spare, _ = p_temp.insert_htmlbox(
                                fitz.Rect(0, 0, max(10.0, inner_rect.width), max(10.0, inner_rect.height)),
                                html,
                                archive=arch
                            )
                            doc_temp.close()
                            if spare > 0:
                                if vertical_align == "middle":
                                    inner_rect.y0 += spare / 2.0
                                elif vertical_align == "bottom":
                                    inner_rect.y0 += spare
                        except Exception:
                            pass

                    page.insert_htmlbox(inner_rect, html, archive=arch, overlay=overlay)
                    return
            except Exception:
                # Jos HTML-renderöinti epäonnistuu, jatketaan puhtaan tekstin insert_textbox-polkuun
                pass

        if vertical_align in ("middle", "bottom"):
            try:
                doc_temp = fitz.open()
                p_temp = doc_temp.new_page(width=max(10.0, inner_rect.width), height=max(10.0, inner_rect.height))
                unused = p_temp.insert_textbox(
                    fitz.Rect(0, 0, max(10.0, inner_rect.width), max(10.0, inner_rect.height)),
                    text,
                    fontsize=font_size,
                    fontname=fontname,
                    fontfile=fontfile,
                    align=align_code
                )
                doc_temp.close()
                if unused > 0:
                    if vertical_align == "middle":
                        inner_rect.y0 += unused / 2.0
                    elif vertical_align == "bottom":
                        inner_rect.y0 += unused
            except Exception:
                pass

        if shape_obj is not None:
            try:
                shape_obj.insert_textbox(
                    inner_rect,
                    text,
                    fontsize=font_size,
                    fontname=fontname,
                    fontfile=fontfile,
                    color=text_color,
                    align=align_code,
                    morph=morph
                )
            except Exception:
                try:
                    shape_obj.insert_textbox(
                        inner_rect,
                        text,
                        fontsize=font_size,
                        fontname="helv",
                        color=text_color,
                        align=align_code,
                        morph=morph
                    )
                except Exception:
                    pass
        else:
            try:
                page.insert_textbox(
                    inner_rect,
                    text,
                    fontsize=font_size,
                    fontname=fontname,
                    fontfile=fontfile,
                    color=text_color,
                    align=align_code,
                    overlay=overlay,
                    morph=morph
                )
            except Exception:
                try:
                    page.insert_textbox(
                        inner_rect,
                        text,
                        fontsize=font_size,
                        fontname="helv",
                        color=text_color,
                        align=align_code,
                        overlay=overlay,
                        morph=morph
                    )
                except Exception:
                    pass

    def reconstruct_page_shapes(self, page_idx: int):
        """
        Palauttaa puhtaan sivupohjan base_doc:sta ja piirtää kaikki sivun näkyvät muodot
        järjestyksessä (Behind Text ja Over Text).
        Tämä mahdollistaa minkä tahansa muodon poistamisen, siirtämisen tai tasonvaihdon
        ilman mitään grafiikkajäämiä tai tekstin heikkenemistä.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return

        self._ensure_base_doc()

        # Palautetaan sivu puhtaasta pohjasta ilman että koko dokumenttia ladataan uudelleen
        self.doc.delete_page(page_idx)
        self.doc.insert_pdf(self.base_doc, from_page=page_idx, to_page=page_idx, start_at=page_idx)

        page = self.doc[page_idx]
        shapes = self.page_shapes.get(page_idx, [])

        # Piirretään ensin tekstin alla olevat muodot (Behind Text)
        for s in shapes:
            if not s.get("overlay", True) and s.get("visible", True):
                self._render_shape_to_page(page, s)

        # Piirretään sitten tekstin päällä olevat muodot (Over Text)
        for s in shapes:
            if s.get("overlay", True) and s.get("visible", True):
                self._render_shape_to_page(page, s)

    def draw_shape(
        self,
        page_idx: int,
        shape_type: str,
        geometry: Any,
        fill_color: Optional[Tuple[float, float, float]] = None,
        stroke_color: Optional[Tuple[float, float, float]] = (0.0, 0.0, 0.0),
        fill_opacity: float = 1.0,
        stroke_opacity: float = 1.0,
        stroke_width: float = 1.5,
        radius: Optional[float] = None,
        overlay: bool = True,
        name: Optional[str] = None,
        text: str = "",
        font_family: str = "Helvetica",
        font_size: float = 14.0,
        font_bold: bool = False,
        font_italic: bool = False,
        text_color: Optional[Tuple[float, float, float]] = (0.0, 0.0, 0.0),
        text_align: str = "center",
        vertical_align: str = "middle",
        text_padding: float = 4.0,
        rotation: float = 0.0,
        html: Optional[str] = None
    ) -> str:
        """
        Piirtää sivulle graafisen muodon (suorakulmio, pyöristetty laatikko, ympyrä, nuoli, viiva tai tekstilaatikko)
        ja rekisteröi sen objektiksi.
        Palauttaa luodun muodon ID:n (str).
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return ""

        self._ensure_base_doc()

        shape_id = f"shape_{self._next_shape_id}"
        self._next_shape_id += 1

        if not name:
            type_labels = {
                "rect": "Suorakulmio",
                "rounded_rect": "Pyöristetty laatikko",
                "circle": "Ympyrä",
                "oval": "Ovaali",
                "arrow": "Nuoli",
                "line": "Viiva",
                "textbox": "Tekstilaatikko"
            }
            lbl = type_labels.get(shape_type, "Objekti")
            existing_count = sum(1 for s in self.page_shapes.get(page_idx, []) if s.get("type") == shape_type) + 1
            name = f"{lbl} {existing_count}"

        shape = {
            "id": shape_id,
            "name": name,
            "type": shape_type,
            "geometry": geometry,
            "fill_color": fill_color,
            "stroke_color": stroke_color,
            "fill_opacity": fill_opacity,
            "stroke_opacity": stroke_opacity,
            "stroke_width": stroke_width,
            "radius": radius,
            "overlay": overlay,
            "visible": True,
            "group_id": None,
            "text": text,
            "font_family": font_family,
            "font_size": font_size,
            "font_bold": font_bold,
            "font_italic": font_italic,
            "text_color": text_color or (0.0, 0.0, 0.0),
            "text_align": text_align,
            "vertical_align": vertical_align,
            "text_padding": text_padding,
            "rotation": float(rotation),
            "html": html
        }

        if page_idx not in self.page_shapes:
            self.page_shapes[page_idx] = []
        self.page_shapes[page_idx].append(shape)

        self.reconstruct_page_shapes(page_idx)
        self._push_undo_state()
        self.redo_stack.clear()
        return shape_id

    def add_background_card_for_block(
        self,
        page_idx: int,
        block: Dict[str, Any],
        padding: float = 6.0,
        fill_color: Tuple[float, float, float] = (0.94, 0.96, 0.98),
        stroke_color: Optional[Tuple[float, float, float]] = (0.7, 0.8, 0.9),
        stroke_width: float = 1.0,
        radius: float = 0.08
    ) -> str:
        """
        Lisää tyylikkään taustalaatikon (kortin) tekstikappaleen alle (overlay=False).
        Teksti säilyy 100 % ehjänä ja valittavana laatikon päällä.
        """
        bbox = block.get("bbox", [0, 0, 100, 50])
        card_rect = (
            bbox[0] - padding,
            bbox[1] - padding,
            bbox[2] + padding,
            bbox[3] + padding
        )
        b_num = block.get("number", 0)
        return self.draw_shape(
            page_idx=page_idx,
            shape_type="rounded_rect",
            geometry=card_rect,
            fill_color=fill_color,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            radius=radius,
            overlay=False,
            name=f"Taustakortti (Kappale {b_num + 1})"
        )

    def get_page_elements(self, page_idx: int) -> List[Dict[str, Any]]:
        """
        Palauttaa sivun kaikki elementit (taustamuodot, tekstilohkot, etualamuodot)
        pinojärjestyksessä (Z-order) Tasot & Objektit -paneelia varten.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return []

        elements: List[Dict[str, Any]] = []
        shapes = self.page_shapes.get(page_idx, [])

        # 1. Tekstin alla olevat muodot (Behind text)
        for s in shapes:
            if not s.get("overlay", True):
                bbox = self._compute_shape_bbox(s)
                elements.append({
                    "id": s["id"],
                    "name": s.get("name", "Taustamuoto"),
                    "type": s.get("type", "rect"),
                    "layer": "behind_text",
                    "bbox": bbox,
                    "visible": s.get("visible", True),
                    "group_id": s.get("group_id"),
                    "shape_data": s,
                    "block_data": None
                })

        # 2. Tekstilohkot
        blocks = self.get_blocks_for_page(page_idx)
        for b in blocks:
            b_text = b.get("text", "").strip().replace("\n", " ")
            preview = b_text[:35] + "..." if len(b_text) > 35 else b_text
            b_id = b.get("block_id", f"text_b{b.get('number', 0)}")
            elements.append({
                "id": b_id,
                "name": f"Teksti: {preview}" if preview else f"Tekstilohko {b.get('number', 0)}",
                "type": "text",
                "layer": "text",
                "bbox": b.get("bbox", [0, 0, 0, 0]),
                "visible": True,
                "group_id": None,
                "shape_data": None,
                "block_data": b
            })

        # 3. Tekstin päällä olevat muodot (Over text)
        for s in shapes:
            if s.get("overlay", True):
                bbox = self._compute_shape_bbox(s)
                elements.append({
                    "id": s["id"],
                    "name": s.get("name", "Muoto"),
                    "type": s.get("type", "rect"),
                    "layer": "over_text",
                    "bbox": bbox,
                    "visible": s.get("visible", True),
                    "group_id": s.get("group_id"),
                    "shape_data": s,
                    "block_data": None
                })

        return elements

    @staticmethod
    def _compute_shape_bbox(shape: Dict[str, Any]) -> Tuple[float, float, float, float]:
        """Laskee muodon suorakaiderajauksen [x0, y0, x1, y1]."""
        geom = shape.get("geometry")
        stype = shape.get("type")
        if stype in ("arrow", "line"):
            p1, p2 = geom
            return (min(p1[0], p2[0]), min(p1[1], p2[1]), max(p1[0], p2[0]), max(p1[1], p2[1]))
        elif geom:
            return (float(geom[0]), float(geom[1]), float(geom[2]), float(geom[3]))
        return (0.0, 0.0, 0.0, 0.0)

    def get_shape(self, page_idx: int, shape_id: str) -> Optional[Dict[str, Any]]:
        """Hakee muodon ID:n perusteella sivulta."""
        for s in self.page_shapes.get(page_idx, []):
            if s.get("id") == shape_id:
                return s
        return None

    def update_shape(self, page_idx: int, shape_id: str, push_undo: bool = True, **kwargs) -> bool:
        """Päivittää muodon kenttiä (väri, geometria, näkyvyys, overlay jne.)."""
        shape = self.get_shape(page_idx, shape_id)
        if not shape:
            return False
        for k, v in kwargs.items():
            shape[k] = v
        self.reconstruct_page_shapes(page_idx)
        if push_undo:
            self._push_undo_state()
            self.redo_stack.clear()
        return True

    def delete_shape(self, page_idx: int, shape_id: str) -> bool:
        """Poistaa muodon sivulta ja päivittää näkymän puhtaasti."""
        shapes = self.page_shapes.get(page_idx, [])
        idx = next((i for i, s in enumerate(shapes) if s.get("id") == shape_id), None)
        if idx is None:
            return False
        shapes.pop(idx)
        self.reconstruct_page_shapes(page_idx)
        self._push_undo_state()
        self.redo_stack.clear()
        return True

    def delete_shapes(self, page_idx: int, shape_ids: List[str]) -> bool:
        """Poistaa useita muotoja kerralla."""
        shapes = self.page_shapes.get(page_idx, [])
        self.page_shapes[page_idx] = [s for s in shapes if s.get("id") not in shape_ids]
        self.reconstruct_page_shapes(page_idx)
        self._push_undo_state()
        self.redo_stack.clear()
        return True

    def reorder_shape(self, page_idx: int, shape_id: str, action: str) -> bool:
        """
        Muuttaa muodon tasojärjestystä.
        action: 'move_up', 'move_down', 'bring_to_front', 'send_to_back', 'behind_text', 'over_text'
        """
        shapes = self.page_shapes.get(page_idx, [])
        idx = next((i for i, s in enumerate(shapes) if s.get("id") == shape_id), None)
        if idx is None:
            return False
        shape = shapes[idx]

        if action == "move_up":
            if idx < len(shapes) - 1:
                shapes[idx], shapes[idx + 1] = shapes[idx + 1], shapes[idx]
        elif action == "move_down":
            if idx > 0:
                shapes[idx], shapes[idx - 1] = shapes[idx - 1], shapes[idx]
        elif action == "bring_to_front":
            shape["overlay"] = True
            shapes.pop(idx)
            shapes.append(shape)
        elif action == "send_to_back":
            shape["overlay"] = False
            shapes.pop(idx)
            shapes.insert(0, shape)
        elif action == "behind_text":
            shape["overlay"] = False
        elif action == "over_text":
            shape["overlay"] = True
        else:
            return False

        self.reconstruct_page_shapes(page_idx)
        self._push_undo_state()
        self.redo_stack.clear()
        return True

    def group_shapes(self, page_idx: int, shape_ids: List[str]) -> Optional[str]:
        """Ryhmittelee valitut muodot yhteen ryhmään."""
        shapes = [s for s in self.page_shapes.get(page_idx, []) if s.get("id") in shape_ids]
        if len(shapes) < 2:
            return None
        group_id = f"group_{self._next_group_id}"
        self._next_group_id += 1
        for s in shapes:
            s["group_id"] = group_id
        self._push_undo_state()
        self.redo_stack.clear()
        return group_id

    def ungroup_shapes(self, page_idx: int, group_id: str) -> bool:
        """Purkaa ryhmittelyn kyseiseltä ryhmältä."""
        shapes = self.page_shapes.get(page_idx, [])
        changed = False
        for s in shapes:
            if s.get("group_id") == group_id:
                s["group_id"] = None
                changed = True
        if changed:
            self._push_undo_state()
            self.redo_stack.clear()
        return changed

    def move_shape(self, page_idx: int, shape_id: str, dx: float, dy: float, push_undo: bool = True) -> bool:
        """
        Siirtää muotoa (dx, dy) verran. Jos muoto kuuluu ryhmään,
        siirtää automaattisesti koko ryhmän kaikkia muotoja samalla siirtymällä!
        """
        target = self.get_shape(page_idx, shape_id)
        if not target:
            return False
        group_id = target.get("group_id")
        if group_id:
            targets = [s for s in self.page_shapes.get(page_idx, []) if s.get("group_id") == group_id]
        else:
            targets = [target]

        for s in targets:
            stype = s.get("type")
            geom = s.get("geometry")
            if stype in ("arrow", "line"):
                p1, p2 = geom
                s["geometry"] = ((p1[0] + dx, p1[1] + dy), (p2[0] + dx, p2[1] + dy))
            else:
                s["geometry"] = (geom[0] + dx, geom[1] + dy, geom[2] + dx, geom[3] + dy)

        self.reconstruct_page_shapes(page_idx)
        if push_undo:
            self._push_undo_state()
            self.redo_stack.clear()
        return True

    def render_page(self, page_idx: int, scale: float = 2.0) -> Tuple[QImage, int, int]:
        """
        Renderöi sivun korkearesoluutioiseksi QImage-olioksi.
        Käyttää matriisia (scale, scale) tarkan tekstikohdistuksen takaamiseksi.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            raise IndexError("Virheellinen sivunumero")

        page = self.doc[page_idx]
        mat = fitz.Matrix(scale, scale)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        
        # Luodaan QImage suoraan bittikartasta
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888)
        # Tehdään kopio, jotta data säilyy vaikka pixmap vapautetaan
        return img.copy(), pix.width, pix.height

    def get_spans_for_page(self, page_idx: int) -> List[Dict[str, Any]]:
        """
        Kerää sivun kaikki tekstialkiot (spans) rikastettuna tunnistetiedoilla ja perusviivoilla.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return []

        page = self.doc[page_idx]
        text_dict = page.get_text("dict")
        spans = []
        span_counter = 0

        for b_idx, block in enumerate(text_dict.get("blocks", [])):
            if block.get("type") == 0:  # Tekstiblokki
                for l_idx, line in enumerate(block.get("lines", [])):
                    for s_idx, span in enumerate(line.get("spans", [])):
                        span_data = dict(span)
                        span_id = f"p{page_idx}_b{b_idx}_l{l_idx}_s{s_idx}_{span_counter}"
                        span_data["span_id"] = span_id
                        span_data["page_idx"] = page_idx
                        span_counter += 1
                        spans.append(span_data)

        return spans

    def get_blocks_for_page(self, page_idx: int) -> List[Dict[str, Any]]:
        """
        Kerää sivun kaikki tekstikappaleet (blocks) älykkäällä typografisella kappale-
        yhdistimellä. Yhdistää InDesign/LaTeX-kirjojen hajautetut yksittäiset rivit
        kokonaisiksi, luonnollisiksi tekstikappaleiksi.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            return []

        import re

        page = self.doc[page_idx]
        text_dict = page.get_text("dict")
        raw_blocks = [b for b in text_dict.get("blocks", []) if b.get("type") == 0]
        if not raw_blocks:
            return []

        # 1. Kerätään kaikki sivun ei-tyhjät tekstirivit
        lines = []
        for b in raw_blocks:
            for l in b.get("lines", []):
                spans = [s for s in l.get("spans", []) if s.get("text", "").strip()]
                if spans:
                    lines.append(l)

        if not lines:
            return []

        # Lajitellaan rivit vertikaalisesti y:n ja x:n mukaan
        lines.sort(key=lambda l: (round(l["bbox"][1], 1), round(l["bbox"][0], 1)))

        # 2. Yhdistetään samalla perusviivalla/korkeudella olevat rivinjaksot (esim. ylätunniste ja sivunumero)
        merged_lines = []
        for l in lines:
            if merged_lines and abs(merged_lines[-1]["bbox"][1] - l["bbox"][1]) < 3.0:
                prev_l = merged_lines[-1]
                prev_l["spans"].extend(l.get("spans", []))
                b1 = prev_l["bbox"]
                b2 = l["bbox"]
                prev_l["bbox"] = (min(b1[0], b2[0]), min(b1[1], b2[1]), max(b1[2], b2[2]), max(b1[3], b2[3]))
            else:
                merged_lines.append(dict(l))

        def get_line_text(line):
            return "".join(s.get("text", "") for s in line.get("spans", []))

        def get_line_font_info(line):
            spans = line.get("spans", [])
            if not spans:
                return "Helvetica", 10.0, False, 0
            s = spans[0]
            fname = s.get("font", "Helvetica")
            fsize = s.get("size", 10.0)
            fcolor = s.get("color", 0)
            is_bold = bool(re.search(r"bold|semibold|heavy|black", fname, re.I))
            clean_fam = re.sub(r"^[A-Z]{6}\+", "", fname)
            clean_fam = re.sub(r"-(Regular|Medium|Bold|Italic|MediumItal|Semibold|Oblique).*", "", clean_fam)
            return clean_fam, fsize, is_bold, fcolor

        # Sivun palstan mittasuhteet (maksimileveys leipätekstiriveille)
        page_max_x1 = max(l["bbox"][2] for l in merged_lines)
        typical_line_w = max(l["bbox"][2] - l["bbox"][0] for l in merged_lines)

        # 3. Älykäs kappaleiden ryhmittely (Leading, linjaus, fontti ja virkerajat)
        paragraphs = []
        cur_para = []

        for l in merged_lines:
            if not cur_para:
                cur_para.append(l)
                continue

            prev = cur_para[-1]
            dy = l["bbox"][1] - prev["bbox"][1]

            fam_prev, size_prev, bold_prev, color_prev = get_line_font_info(prev)
            fam_cur, size_cur, bold_cur, color_cur = get_line_font_info(l)

            prev_text = get_line_text(prev).strip()
            dx_left = abs(l["bbox"][0] - prev["bbox"][0])

            same_family = (fam_prev == fam_cur) or (not fam_prev or not fam_cur)
            same_size = abs(size_prev - size_cur) < 0.8
            same_weight = (bold_prev == bold_cur)

            def are_colors_close(c1: int, c2: int) -> bool:
                if c1 == c2:
                    return True
                r1, g1, b1 = (c1 >> 16) & 255, (c1 >> 8) & 255, c1 & 255
                r2, g2, b2 = (c2 >> 16) & 255, (c2 >> 8) & 255, c2 & 255
                if max(r1, g1, b1) < 55 and max(r2, g2, b2) < 55:
                    return True
                return ((r1 - r2)**2 + (g1 - g2)**2 + (b1 - b2)**2)**0.5 < 30.0

            same_color = are_colors_close(color_prev, color_cur)

            # Riviväli (leading) toleranssi: tyypillisesti 0.75 - 2.2 kertaa fonttikoko
            leading_ok = (size_prev * 0.75 <= dy <= size_prev * 2.2)

            # Linjaus vasempaan reunaan tai kappaleen aloitussisennys (5 - 30 pt)
            left_ok = (dx_left < 4.0) or (5.0 <= dx_left <= 30.0 and len(cur_para) == 1)

            # Jos edellinen rivi loppui selvästi ennen palstan reunaa ja virkkeen lopetusmerkkiin, kappale päättyi
            prev_w = prev["bbox"][2] - prev["bbox"][0]
            ends_sentence = prev_text.endswith((".", "!", "?", ":", "”", "\""))
            is_short_end = (prev_w < typical_line_w * 0.82) and ends_sentence

            is_same_para = leading_ok and same_size and same_family and same_weight and same_color and left_ok and not is_short_end

            if is_same_para:
                cur_para.append(l)
            else:
                paragraphs.append(cur_para)
                cur_para = [l]

        if cur_para:
            paragraphs.append(cur_para)

        # 4. Muodostetaan rikastetut lohkot
        blocks = []
        for p_idx, lines_in_p in enumerate(paragraphs):
            primary_font = "Helvetica"
            primary_size = 12.0
            primary_color_int = 0
            primary_flags = 0

            for line in lines_in_p:
                for s in line.get("spans", []):
                    if s.get("text", "").strip():
                        primary_font = s.get("font", "Helvetica")
                        primary_size = s.get("size", 12.0)
                        primary_color_int = s.get("color", 0)
                        primary_flags = s.get("flags", 0)
                        break
                if primary_font != "Helvetica":
                    break

            min_x = min(l["bbox"][0] for l in lines_in_p)
            min_y = min(l["bbox"][1] for l in lines_in_p)
            max_x = max(l["bbox"][2] for l in lines_in_p)
            max_y = max(l["bbox"][3] for l in lines_in_p)
            bbox = (min_x, min_y, max_x, max_y)

            line_origins = []
            line_bboxes = []
            line_spans = []
            for line in lines_in_p:
                line_bboxes.append(line.get("bbox", [0, 0, 0, 0]))
                line_spans.append([dict(s) for s in line.get("spans", [])])
                l_orig = None
                for s in line.get("spans", []):
                    if s.get("origin"):
                        l_orig = (float(s["origin"][0]), float(s["origin"][1]))
                        break
                if not l_orig:
                    l_box = line.get("bbox", [0, 0, 0, 0])
                    l_orig = (float(l_box[0]), float(l_box[1] + primary_size * 0.85))
                line_origins.append(l_orig)

            first_origin = fitz.Point(line_origins[0][0], line_origins[0][1])

            line_leadings = []
            if len(line_origins) > 1:
                for idx in range(len(line_origins) - 1):
                    dy = line_origins[idx + 1][1] - line_origins[idx][1]
                    line_leadings.append(dy)
                leading = sum(line_leadings) / len(line_leadings)
            else:
                line_h = lines_in_p[0].get("bbox", [0, 0, 0, 0])[3] - lines_in_p[0].get("bbox", [0, 0, 0, 0])[1]
                leading = line_h if line_h > 5.0 else primary_size * 1.35

            text_parts = []
            for l_idx, line in enumerate(lines_in_p):
                line_str = "".join(s.get("text", "") for s in line.get("spans", []))
                if l_idx == len(lines_in_p) - 1:
                    text_parts.append(line_str)
                    break
                line_stripped = line_str.rstrip(" ")
                if line_stripped.endswith(("\xad", "-", "‐", "‑")):
                    text_parts.append(line_stripped[:-1])
                elif line_str.endswith(" "):
                    text_parts.append(line_str)
                else:
                    text_parts.append(line_str + " ")

            full_text = "".join(text_parts).replace("\xad", "").strip()
            # Normalisoidaan InDesignin erikoisvälilyönnit (thin space \u2006, em-space jne.)
            full_text = re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0]", " ", full_text)
            max_w = max_x - first_origin.x
            line_max_w = max(l["bbox"][2] - l["bbox"][0] for l in lines_in_p)
            max_w = max(max_w, line_max_w)
            if max_w < 20.0:
                max_w = max(50.0, max_x - min_x)

            avail_w = max(max_w, page_max_x1 - first_origin.x)

            block_data = {
                "block_id": f"p{page_idx}_para{p_idx}",
                "page_idx": page_idx,
                "type": 0,
                "bbox": bbox,
                "original_bbox": bbox,
                "text": full_text,
                "font": primary_font,
                "size": primary_size,
                "color": primary_color_int,
                "flags": primary_flags,
                "line_count": len(lines_in_p),
                "first_origin": (first_origin.x, first_origin.y),
                "line_origins": line_origins,
                "line_leadings": line_leadings,
                "line_bboxes": line_bboxes,
                "line_spans": line_spans,
                "leading": leading,
                "max_width": max_w,
                "available_width": avail_w,
                "original_lines": [
                    "".join(s.get("text", "") for s in l.get("spans", [])).replace("\xad", "")
                    for l in lines_in_p
                ]
            }
            blocks.append(block_data)

        return blocks

    def replace_block_inplace(
        self,
        page_idx: int,
        block: Dict[str, Any],
        new_text: str,
        font_match: FontMatchResult,
        custom_fontsize: Optional[float] = None,
        custom_color: Optional[Tuple[float, float, float]] = None,
        custom_max_width: Optional[float] = None
    ) -> EditOperation:
        """
        Korvaa kokonaisen tekstikappaleen in-place säilyttäen alkuperäisen
        rivivälikorkeuden (leading), tarkan perusviivan (baseline) ja kirjasinmetriikat.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            raise IndexError("Virheellinen sivunumero")

        page = self.doc[page_idx]
        orig_bbox = fitz.Rect(block.get("original_bbox", block["bbox"]))
        bbox = fitz.Rect(block["bbox"])
        orig_size = block.get("size", 12.0)
        orig_color_int = block.get("color", 0)

        # 1. Alkuperäisten mittojen ja rivivälin (leading) nouto
        first_origin = fitz.Point(block.get("first_origin", (bbox.x0, bbox.y0 + orig_size * 0.85)))
        orig_leading = block.get("leading", orig_size * 1.35)

        if custom_max_width is not None and custom_max_width > 0:
            max_width = custom_max_width
        else:
            max_width = block.get("max_width", max(50.0, bbox.x1 - first_origin.x))
            line_bboxes = block.get("line_bboxes", [])
            if line_bboxes:
                max_width = max(max_width, max(b[2] - b[0] for b in line_bboxes))
            avail_width = block.get("available_width", max_width)

            # Jos kyseessä on yksirivinen otsikko ilman eksplisiittistä rivinvaihtoa (\n),
            # sallitaan leveyden joustaa palstan vapaaseen tilaan asti, jotta otsikko ei rivity turhaan
            if "\n" not in new_text.strip() and block.get("line_count", 1) == 1:
                max_width = max(max_width, avail_width)

        line_origins = block.get("line_origins", [(first_origin.x, first_origin.y)])

        if custom_fontsize is not None and abs(custom_fontsize - orig_size) > 0.05 and orig_size > 0:
            effective_fontsize = custom_fontsize
            effective_leading = orig_leading * (effective_fontsize / orig_size)
            use_exact_origins = False
        else:
            effective_fontsize = orig_size
            effective_leading = orig_leading
            use_exact_origins = True

        # 2. RGB-väri
        if custom_color is not None:
            color_tuple = custom_color
        else:
            r = ((orig_color_int >> 16) & 255) / 255.0
            g = ((orig_color_int >> 8) & 255) / 255.0
            b = (orig_color_int & 255) / 255.0
            color_tuple = (r, g, b)

        # 3. Kirjasimen valmistelu ja mittausfontti sanarivitystä varten
        base14_fonts = ("helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "tibi", "couri", "cobo", "coit", "cobi", "symb", "zadb")
        measuring_font = None

        if font_match.can_use_embedded and font_match.embedded_buffer:
            try:
                measuring_font = fitz.Font(fontbuffer=font_match.embedded_buffer)
            except Exception:
                measuring_font = None
        elif font_match.effective_font_name in base14_fonts:
            try:
                measuring_font = fitz.Font(font_match.effective_font_name)
            except Exception:
                measuring_font = None
        elif font_match.effective_font_path and os.path.isfile(font_match.effective_font_path):
            try:
                measuring_font = fitz.Font(fontfile=font_match.effective_font_path)
            except Exception:
                measuring_font = None

        if measuring_font is None:
            fallback_path, _ = FontconfigResolver.resolve_local_font("sans-serif")
            if fallback_path and os.path.isfile(fallback_path):
                try:
                    measuring_font = fitz.Font(fontfile=fallback_path)
                except Exception:
                    measuring_font = fitz.Font("helv")
            else:
                measuring_font = fitz.Font("helv")

        # 4. Deterministinen ja tarkka sanarivitys lohkon leveyden mukaan (toleranssi estää pyöristysvirheet)
        tolerance = max(2.0, effective_fontsize * 0.25)
        clean_text = new_text.replace("\xad", "")
        clean_text = re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0]", " ", clean_text)
        paragraphs = clean_text.split("\n")
        wrapped_lines = []
        for para in paragraphs:
            if not para.strip():
                wrapped_lines.append("")
                continue
            words = para.split(" ")
            cur_line = []
            for word in words:
                cand = " ".join(cur_line + [word])
                try:
                    w = measuring_font.text_length(cand, fontsize=effective_fontsize)
                except Exception:
                    w = len(cand) * effective_fontsize * 0.52
                if w <= (max_width + tolerance) or not cur_line:
                    cur_line.append(word)
                else:
                    wrapped_lines.append(" ".join(cur_line))
                    cur_line = [word]
            if cur_line:
                wrapped_lines.append(" ".join(cur_line))

        # 5. Tarkistetaan voidaanko suorittaa rivikohtainen kirurginen korvaus:
        # Jos käyttäjä muokkasi tekstiä säilyttäen alkuperäisen rivijaon (esim. korjasi sanan yhdeltä riviltä),
        # ei redaktoida eikä ylikirjoiteta muuttumattomia rivejä!
        # Tämä suojaa muiden rivien monimutkaiset tyylit (kursiivit, erikoismerkit, välistykset) 100% koskemattomina.
        orig_lines = block.get("original_lines", [])
        line_bboxes = block.get("line_bboxes", [])

        can_do_surgical = (
            use_exact_origins and
            len(paragraphs) == len(orig_lines) and
            len(orig_lines) == len(line_bboxes) and
            len(orig_lines) == len(line_origins) and
            len(orig_lines) > 0
        )

        changed_line_indices = []
        if can_do_surgical:
            for i in range(len(orig_lines)):
                p_clean = re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0\s]+", " ", paragraphs[i].strip())
                o_clean = re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0\s]+", " ", orig_lines[i].strip())
                if p_clean != o_clean:
                    changed_line_indices.append(i)

            if not changed_line_indices:
                return EditOperation(
                    page_idx=page_idx,
                    span_id=block.get("block_id", "block"),
                    original_text=block.get("text", ""),
                    new_text=new_text,
                    bbox=tuple(orig_bbox),
                    origin=(first_origin.x, first_origin.y),
                    font_name=font_match.effective_font_name or "helv",
                    fontsize=effective_fontsize,
                    color_rgb=color_tuple,
                    font_path=font_match.effective_font_path,
                    fit_strategy=FitStrategy.NATURAL.value
                )

            # Varmistetaan mahtuvatko kaikki muuttuneet rivit ilman uudelleenrivitystä
            for i in changed_line_indices:
                cand = paragraphs[i]
                try:
                    w = measuring_font.text_length(cand, fontsize=effective_fontsize)
                except Exception:
                    w = len(cand) * effective_fontsize * 0.52
                if w > (max_width + tolerance):
                    can_do_surgical = False
                    break

        if can_do_surgical and changed_line_indices:
            # Tarkistetaan voidaanko jokin muuttuneista riveistä korvata vieläkin tarkemmin sanatasolla (Word-level precision):
            # Jos rivillä vaihtui vain yksi sana ja sen pituus on identtinen vanhan sanan kanssa (kuten vuosiluku 2023 -> 2024),
            # redaktoidaan ja piirretään vain kyseinen sana, jolloin rivin muiden sanojen (kuten "Technology")
            # alkuperäiset InDesign-parivälistykset säilyvät 100% koskemattomina ilman edes 0.1 mm siirtymää!
            word_level_lines = {}
            for i in changed_line_indices:
                p_words = paragraphs[i].strip().split(" ")
                o_words = orig_lines[i].strip().split(" ")
                if len(p_words) == len(o_words) and len(p_words) > 1:
                    diff_w_idxs = [w_i for w_i, (pw, ow) in enumerate(zip(p_words, o_words)) if pw != ow]
                    if len(diff_w_idxs) == 1:
                        w_idx = diff_w_idxs[0]
                        r_line = fitz.Rect(line_bboxes[i])
                        w_list = [w for w in page.get_text("words") if fitz.Rect(w[:4]).intersects(r_line) and abs(w[1] - r_line.y0) < 6.0]
                        w_list.sort(key=lambda w: w[0])
                        if len(w_list) == len(o_words) and w_list[w_idx][4].strip(" ,.:;()[]") == o_words[w_idx].strip(" ,.:;()[]"):
                            old_w_len = w_list[w_idx][2] - w_list[w_idx][0]
                            try:
                                new_w_len = measuring_font.text_length(p_words[w_idx], fontsize=effective_fontsize)
                            except Exception:
                                new_w_len = len(p_words[w_idx]) * effective_fontsize * 0.52
                            # Jos sanan pituusero on alle 0.8 pt (tasalevyiset luvut tai sama merkkileveys)
                            if abs(new_w_len - old_w_len) < 0.8:
                                word_level_lines[i] = {
                                    "word_box": w_list[w_idx][:4],
                                    "new_word": p_words[w_idx]
                                }

            # Kirurginen vektoriredaktio: jos riville on sanakohtainen täsmäkorvaus, redaktoidaan vain kyseinen sana!
            for i in changed_line_indices:
                if i in word_level_lines:
                    wb = word_level_lines[i]["word_box"]
                    redact_rect = fitz.Rect(wb[0] + 0.05, wb[1] - 0.5, wb[2] - 0.05, wb[3] + 0.5)
                    page.add_redact_annot(redact_rect)
                else:
                    l_box = line_bboxes[i]
                    redact_rect = fitz.Rect(l_box[0] - 0.5, l_box[1] - 0.5, l_box[2] + 0.5, l_box[3] + 0.5)
                    page.add_redact_annot(redact_rect)
            page.apply_redactions(images=0, graphics=0)

            # Fontin rekisteröinti sivulle REDAKTION JÄLKEEN
            insert_font_name = "helv"
            insert_font_file = None

            if font_match.can_use_embedded and font_match.embedded_buffer:
                reused_font_name = f"F_emb_{abs(hash(font_match.original_font_name)) % 100000}"
                try:
                    page.insert_font(fontname=reused_font_name, fontbuffer=font_match.embedded_buffer)
                    insert_font_name = reused_font_name
                except Exception:
                    insert_font_name = font_match.effective_font_name if font_match.effective_font_name in base14_fonts else "helv"
            elif font_match.effective_font_path and os.path.isfile(font_match.effective_font_path):
                file_stem = re.sub(r"[^a-zA-Z0-9]", "", os.path.splitext(os.path.basename(font_match.effective_font_path))[0])
                unique_name = f"F_{file_stem}_{abs(hash(font_match.effective_font_path)) % 1000}"
                try:
                    page.insert_font(fontname=unique_name, fontfile=font_match.effective_font_path)
                    insert_font_name = unique_name
                    insert_font_file = font_match.effective_font_path
                except Exception:
                    insert_font_file = font_match.effective_font_path
                    insert_font_name = unique_name
            elif font_match.effective_font_name in base14_fonts:
                insert_font_name = font_match.effective_font_name
            else:
                fallback_path, _ = FontconfigResolver.resolve_local_font("sans-serif")
                if fallback_path and os.path.isfile(fallback_path):
                    try:
                        page.insert_font(fontname="fallback_block_font", fontfile=fallback_path)
                        insert_font_name = "fallback_block_font"
                        insert_font_file = fallback_path
                    except Exception:
                        insert_font_name = "helv"
                        insert_font_file = None
                else:
                    insert_font_name = "helv"
                    insert_font_file = None

            # Sijoitetaan vain muuttuneet rivit tai sanat
            for i in changed_line_indices:
                if i in word_level_lines:
                    wb = word_level_lines[i]["word_box"]
                    line_text = word_level_lines[i]["new_word"]
                    line_pt = fitz.Point(wb[0], line_origins[i][1])
                else:
                    line_text = paragraphs[i]
                    line_pt = fitz.Point(line_origins[i][0], line_origins[i][1])

                if insert_font_file and os.path.isfile(insert_font_file):
                    insert_kwargs = {
                        "point": line_pt,
                        "text": line_text,
                        "fontsize": effective_fontsize,
                        "fontfile": insert_font_file,
                        "fontname": insert_font_name,
                        "color": color_tuple
                    }
                    if getattr(font_match, "needs_faux_bold", False):
                        insert_kwargs["render_mode"] = 2
                        insert_kwargs["fill"] = color_tuple
                        insert_kwargs["border_width"] = max(0.1, effective_fontsize * 0.025)
                    page.insert_text(**insert_kwargs)
                else:
                    page.insert_text(
                        point=line_pt,
                        text=line_text,
                        fontsize=effective_fontsize,
                        fontname=insert_font_name,
                        color=color_tuple
                    )

            op = EditOperation(
                page_idx=page_idx,
                span_id=block.get("block_id", "block"),
                original_text=block.get("text", ""),
                new_text=new_text,
                bbox=tuple(orig_bbox),
                origin=(first_origin.x, first_origin.y),
                font_name=font_match.effective_font_name or insert_font_name,
                fontsize=effective_fontsize,
                color_rgb=color_tuple,
                font_path=font_match.effective_font_path,
                fit_strategy=FitStrategy.NATURAL.value
            )
            self.operations_history.append(op)
            self._sync_base_doc_from_doc(page_idx)
            self._push_undo_state()
            self.redo_stack.clear()
            return op

        # 5. Vektoriredaktio vanhalle lohkoalueelle (graphics=0, images=0 säilyttää taustat)
        # TÄRKEÄÄ: Suoritetaan ENNEN uuden fontin rekisteröintiä sivulle, jotta apply_redactions ei pyyhi fonttiresursseja!
        # Käytetään nimenomaan alkuperäistä tekstilaatikkoa (orig_bbox), jotta laajennetun laatikon ulkopuoliset grafiikat eivät pyyhiydy
        redact_rect = fitz.Rect(orig_bbox.x0 - 0.5, orig_bbox.y0 - 0.5, orig_bbox.x1 + 0.5, orig_bbox.y1 + 0.5)
        page.add_redact_annot(redact_rect)
        page.apply_redactions(images=0, graphics=0)

        # 6. Kirjasimen rekisteröinti sivulle REDAKTION JÄLKEEN
        insert_font_name = "helv"
        insert_font_file = None

        if font_match.can_use_embedded and font_match.embedded_buffer:
            reused_font_name = f"F_emb_{abs(hash(font_match.original_font_name)) % 100000}"
            try:
                page.insert_font(fontname=reused_font_name, fontbuffer=font_match.embedded_buffer)
                insert_font_name = reused_font_name
            except Exception:
                insert_font_name = font_match.effective_font_name if font_match.effective_font_name in base14_fonts else "helv"
        elif font_match.effective_font_path and os.path.isfile(font_match.effective_font_path):
            file_stem = re.sub(r"[^a-zA-Z0-9]", "", os.path.splitext(os.path.basename(font_match.effective_font_path))[0])
            unique_name = f"F_{file_stem}_{abs(hash(font_match.effective_font_path)) % 1000}"
            try:
                page.insert_font(fontname=unique_name, fontfile=font_match.effective_font_path)
                insert_font_name = unique_name
                insert_font_file = font_match.effective_font_path
            except Exception:
                insert_font_file = font_match.effective_font_path
                insert_font_name = unique_name
        elif font_match.effective_font_name in base14_fonts:
            insert_font_name = font_match.effective_font_name
        else:
            fallback_path, _ = FontconfigResolver.resolve_local_font("sans-serif")
            if fallback_path and os.path.isfile(fallback_path):
                try:
                    page.insert_font(fontname="fallback_block_font", fontfile=fallback_path)
                    insert_font_name = "fallback_block_font"
                    insert_font_file = fallback_path
                except Exception:
                    insert_font_name = "helv"
                    insert_font_file = None
            else:
                insert_font_name = "helv"
                insert_font_file = None

        # 7. Rivien sijoitus täsmällisille alkuperäisille perusviivoille identtisellä rivivälillä
        safe_fallback_font = "hebo" if font_match.is_bold else "helv"

        for i, line_text in enumerate(wrapped_lines):
            if not line_text.strip():
                continue
            if use_exact_origins and i < len(line_origins):
                line_pt = fitz.Point(line_origins[i][0], line_origins[i][1])
            else:
                if line_origins:
                    base_x = line_origins[0][0]
                    base_y = line_origins[-1][1]
                    extra_lines = i - (len(line_origins) - 1)
                    line_pt = fitz.Point(base_x, base_y + extra_lines * effective_leading)
                else:
                    line_pt = fitz.Point(first_origin.x, first_origin.y + i * effective_leading)

            try:
                if insert_font_file and os.path.isfile(insert_font_file):
                    insert_kwargs = {
                        "point": line_pt,
                        "text": line_text,
                        "fontsize": effective_fontsize,
                        "fontfile": insert_font_file,
                        "fontname": insert_font_name,
                        "color": color_tuple
                    }
                    if getattr(font_match, "needs_faux_bold", False):
                        insert_kwargs["render_mode"] = 2
                        insert_kwargs["fill"] = color_tuple
                        insert_kwargs["border_width"] = max(0.1, effective_fontsize * 0.025)
                    page.insert_text(**insert_kwargs)
                else:
                    page.insert_text(
                        point=line_pt,
                        text=line_text,
                        fontsize=effective_fontsize,
                        fontname=insert_font_name,
                        color=color_tuple
                    )
            except Exception:
                page.insert_text(
                    point=line_pt,
                    text=line_text,
                    fontsize=effective_fontsize,
                    fontname=safe_fallback_font,
                    color=color_tuple
                )

        op = EditOperation(
            page_idx=page_idx,
            span_id=block.get("block_id", ""),
            original_text=block.get("text", ""),
            new_text=new_text,
            bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            origin=(first_origin.x, first_origin.y),
            font_name=font_match.clean_family,
            fontsize=effective_fontsize,
            color_rgb=color_tuple,
            font_path=font_match.effective_font_path,
            fit_strategy="paragraph_flow"
        )
        self.operations_history.append(op)
        self._sync_base_doc_from_doc(page_idx)
        self._push_undo_state()
        self.redo_stack.clear()
        return op

    def replace_text_inplace(
        self,
        page_idx: int,
        span: Dict[str, Any],
        new_text: str,
        font_match: FontMatchResult,
        strategy: FitStrategy = FitStrategy.NATURAL,
        custom_fontsize: Optional[float] = None,
        custom_color: Optional[Tuple[float, float, float]] = None
    ) -> EditOperation:
        """
        Suorittaa kirurgisen in-place -korvauksen:
        1. Lisää tarkan vektoriredaktioalueen vanhalle tekstille.
        2. Poistaa tekstin sisältövirrasta säilyttäen taustakuvat ja vektorit (images=0, graphics=0).
        3. Asettaa uuden tekstin täsmälleen samalle perusviivalle ja värille.
        """
        if not self.is_open or page_idx < 0 or page_idx >= self.page_count:
            raise IndexError("Virheellinen sivunumero")

        page = self.doc[page_idx]
        bbox = fitz.Rect(span["bbox"])
        orig_origin = fitz.Point(span["origin"])
        orig_size = span["size"]
        orig_color_int = span.get("color", 0)

        # Lasketaan RGB-väri
        if custom_color is not None:
            color_tuple = custom_color
        else:
            r = ((orig_color_int >> 16) & 255) / 255.0
            g = ((orig_color_int >> 8) & 255) / 255.0
            b = (orig_color_int & 255) / 255.0
            color_tuple = (r, g, b)

        # Lasketaan fonttikoko ja asetteluparametrit
        if custom_fontsize is not None:
            effective_fontsize = custom_fontsize
            target_origin = orig_origin
        else:
            effective_fontsize, _, target_origin = LayoutEngine.compute_fit_parameters(
                span,
                new_text,
                strategy,
                fontfile=font_match.effective_font_path,
                fontname=font_match.effective_font_name or "helv"
            )

        # 1. Vektoriredaktio: poistaa ainoastaan tekstin kyseiseltä alueelta
        page.add_redact_annot(bbox)
        # images=0: ei poisteta taustakuvia
        # graphics=0: ei poisteta taustavektoreita, viivoja tai täyttöjä
        page.apply_redactions(images=0, graphics=0)

        # 2. Uuden tekstin sijoitus tarkan perusviivan mukaan
        base14_fonts = ("helv", "hebo", "heit", "hebi", "tiro", "tibo", "tiit", "tibi", "couri", "cobo", "coit", "cobi", "symb", "zadb")
        safe_fallback_font = "hebo" if font_match.is_bold else "helv"

        try:
            if font_match.can_use_embedded and font_match.embedded_buffer:
                reused_font_name = f"F_emb_{abs(hash(font_match.original_font_name)) % 100000}"
                try:
                    page.insert_font(fontname=reused_font_name, fontbuffer=font_match.embedded_buffer)
                except Exception:
                    reused_font_name = safe_fallback_font
                page.insert_text(
                    point=target_origin,
                    text=new_text,
                    fontsize=effective_fontsize,
                    fontname=reused_font_name,
                    color=color_tuple
                )
            elif font_match.effective_font_path and os.path.isfile(font_match.effective_font_path):
                file_stem = re.sub(r"[^a-zA-Z0-9]", "", os.path.splitext(os.path.basename(font_match.effective_font_path))[0])
                unique_name = f"F_{file_stem}_{abs(hash(font_match.effective_font_path)) % 1000}"
                try:
                    page.insert_font(fontname=unique_name, fontfile=font_match.effective_font_path)
                except Exception:
                    pass
                insert_kwargs = {
                    "point": target_origin,
                    "text": new_text,
                    "fontsize": effective_fontsize,
                    "fontfile": font_match.effective_font_path,
                    "fontname": unique_name,
                    "color": color_tuple
                }
                if getattr(font_match, "needs_faux_bold", False):
                    insert_kwargs["render_mode"] = 2
                    insert_kwargs["fill"] = color_tuple
                    insert_kwargs["border_width"] = max(0.1, effective_fontsize * 0.025)
                page.insert_text(**insert_kwargs)
            elif font_match.effective_font_name in base14_fonts:
                page.insert_text(
                    point=target_origin,
                    text=new_text,
                    fontsize=effective_fontsize,
                    fontname=font_match.effective_font_name,
                    color=color_tuple
                )
            else:
                fallback_path, _ = FontconfigResolver.resolve_local_font("sans-serif")
                if fallback_path and os.path.isfile(fallback_path):
                    page.insert_text(
                        point=target_origin,
                        text=new_text,
                        fontsize=effective_fontsize,
                        fontfile=fallback_path,
                        fontname="fallback_sys_font",
                        color=color_tuple
                    )
                else:
                    page.insert_text(
                        point=target_origin,
                        text=new_text,
                        fontsize=effective_fontsize,
                        fontname=safe_fallback_font,
                        color=color_tuple
                    )
        except Exception:
            page.insert_text(
                point=target_origin,
                text=new_text,
                fontsize=effective_fontsize,
                fontname=safe_fallback_font,
                color=color_tuple
            )

        # Luodaan ja tallennetaan operaatiotietue
        op = EditOperation(
            page_idx=page_idx,
            span_id=span.get("span_id", ""),
            original_text=span.get("text", ""),
            new_text=new_text,
            bbox=(bbox.x0, bbox.y0, bbox.x1, bbox.y1),
            origin=(target_origin.x, target_origin.y),
            font_name=font_match.clean_family,
            fontsize=effective_fontsize,
            color_rgb=color_tuple,
            font_path=font_match.effective_font_path,
            fit_strategy=strategy.value
        )
        self.operations_history.append(op)
        self._sync_base_doc_from_doc(page_idx)

        # Päivitetään Undo-historia
        self._push_undo_state()
        self.redo_stack.clear()

        return op

    def save(self, output_path: str):
        """
        Tallentaa muokatun PDF-tiedoston.
        Käyttää asetuksia 'garbage=3, clean=True, deflate=True',
        jotta tiedosto on optimaalinen ja XRef-rakenne on täysin virheetön.
        """
        if not self.is_open:
            raise ValueError("Ei avointa dokumenttia tallennettavaksi.")

        # Varmistetaan että kohdehakemisto on olemassa
        out_dir = os.path.dirname(output_path)
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

        self.doc.save(
            output_path,
            garbage=3,      # Siivoaa orvot ja käyttämättömät objektit
            clean=True,     # Korjaa ja normalisoi sisältövirrat
            deflate=True    # Pakkaa virrat optimaalisesti
        )

    def get_document_fonts_summary(self) -> List[Dict[str, Any]]:
        """
        Skannaa koko dokumentin kaikki sivut ja palauttaa yhteenvedon jokaisesta fontista:
        - name: fontin koko nimi (esim. 'WAVDPC+MinionPro-Regular')
        - clean_family: puhdistettu perhe ('MinionPro')
        - ext: fonttipääte ('cff', 'ttf', 'otf', 'n/a')
        - type: tyyppi ('Type1', 'TrueType')
        - is_subset: onko leikattu osajoukko
        - is_bold: onko lihavoitu
        - is_italic: onko kursivoitu
        - is_installed: onko asennettu paikallisesti (tai Base-14 / fonts/)
        - status_desc: selite tilasta
        - font_path: tiedostopolku jos asennettu
        - pages: lista sivunumeroista (1-alkuisina)
        - recommendation: suositeltu avoin vastine jos puuttuu
        """
        if not self.is_open or not self.doc:
            return []

        fonts_by_key = {}

        for pno in range(self.page_count):
            page = self.doc[pno]
            for f in page.get_fonts(full=True):
                fxref, fext, ftype, fbase, fname, fenc = f[:6]
                clean_fam, is_subset, is_b, is_it = FontconfigResolver.clean_font_name(fbase)
                key = f"{clean_fam}_{'b' if is_b else ''}_{'i' if is_it else ''}"

                if key not in fonts_by_key:
                    is_inst, desc, fpath = FontconfigResolver.is_font_installed(clean_fam, bold=is_b, italic=is_it)
                    rec_desc, rec_id = FontDownloader.get_recommendation(clean_fam)
                    fonts_by_key[key] = {
                        "name": fbase,
                        "clean_family": clean_fam,
                        "ext": fext,
                        "type": ftype,
                        "is_subset": is_subset,
                        "is_bold": is_b,
                        "is_italic": is_it,
                        "is_installed": is_inst,
                        "status_desc": desc,
                        "font_path": fpath,
                        "recommendation": rec_desc,
                        "rec_id": rec_id,
                        "pages": set(),
                    }
                fonts_by_key[key]["pages"].add(pno + 1)

        result = []
        for item in fonts_by_key.values():
            item["pages"] = sorted(list(item["pages"]))
            result.append(item)

        # Järjestetään: ensin puuttuvat, sitten osajoukot, sitten asennetut
        result.sort(key=lambda x: (x["is_installed"], not x["is_subset"], x["clean_family"]))
        return result

    def get_document_font_families(self) -> List[str]:
        """
        Palauttaa listan uniikeista kirjasinperheistä, joita käytetään nykyisessä dokumentissa.
        Puhdistaa leikkaukset ja osajoukkoetuliitteet (esim. 'MinionPro', 'Stone Serif Std').
        """
        if not self.is_open or not self.doc:
            return []

        families = []
        seen = set()

        for pno in range(self.page_count):
            page = self.doc[pno]
            for f in page.get_fonts(full=True):
                fbase = f[3]
                clean_fam, _, _, _ = FontconfigResolver.clean_font_name(fbase)
                if clean_fam and clean_fam.lower() not in seen:
                    seen.add(clean_fam.lower())
                    families.append(clean_fam)

        return sorted(families, key=lambda s: s.lower())

    def extract_document_fonts(self) -> List[str]:
        """
        Purkaa dokumentin upotetut fontit (TTF/OTF) sovelluksen fonts/extracted/ -hakemistoon,
        jotta ne ovat heti käytettävissä uusille tekstilaatikoille ja sivuille.
        Palauttaa listan tallennettujen fonttitiedostojen poluista.
        """
        if not self.is_open or not self.doc:
            return []

        extracted_dir = os.path.join(LOCAL_FONTS_DIR, "extracted")
        os.makedirs(extracted_dir, exist_ok=True)
        saved_paths = []
        extracted_xrefs = set()

        for pno in range(self.page_count):
            page = self.doc[pno]
            for f in page.get_fonts(full=True):
                fxref, fext, ftype, fbase, fname, fenc = f[:6]
                if fxref in extracted_xrefs or fxref <= 0:
                    continue
                extracted_xrefs.add(fxref)

                try:
                    res = self.doc.extract_font(fxref)
                    bname, ext, f_type, buf = FontconfigResolver._parse_extracted_font(res)
                    if not buf or len(buf) < 100:
                        continue

                    ext_clean = (ext or fext or "ttf").lower()
                    if ext_clean not in ("ttf", "otf"):
                        if buf.startswith(b"OTTO"):
                            ext_clean = "otf"
                        elif buf.startswith(b"\x00\x01\x00\x00") or buf.startswith(b"true"):
                            ext_clean = "ttf"
                        else:
                            continue

                    clean_fam, is_sub, is_b, is_it = FontconfigResolver.clean_font_name(fbase or bname)
                    safe_stem = re.sub(r'[^a-zA-Z0-9_-]', '', clean_fam)
                    if not safe_stem:
                        safe_stem = "docfont"
                    style_suffix = ""
                    if is_b and is_it:
                        style_suffix = "-BoldItalic"
                    elif is_b:
                        style_suffix = "-Bold"
                    elif is_it:
                        style_suffix = "-Italic"

                    filename = f"{safe_stem}{style_suffix}.{ext_clean}"
                    out_path = os.path.join(extracted_dir, filename)
                    with open(out_path, "wb") as f_out:
                        f_out.write(buf)
                    saved_paths.append(out_path)
                except Exception:
                    pass

        if saved_paths:
            FontconfigResolver.scan_local_user_fonts(force_reload=True)
        return saved_paths
