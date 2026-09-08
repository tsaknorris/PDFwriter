"""
Yksikkö- ja integraatiotestit Textboxille ja muotojen typografialle:
1. Uuden tekstilaatikon (textbox) luonti, teksti ja tasaukset.
2. Tekstin lisääminen olemassa olevaan pyöristettyyn laatikkoon (käyttäjän tapaus).
3. Vaaka- ja pystytasaukset (vasen, keskitetty, oikea, tasattu; ylhäällä, keskellä, alhaalla).
4. Typografiatyylit (fonttiperhe, koko, lihavointi, kursivointi, väri).
5. ShapePropertiesDock -ohjauspaneelin typografiasäätimet ja synkronointi.
6. Kankaan tuplaklikkaus ja in-canvas kelluva tekstieditori.
7. Tekstimuutosten Kumoa/Tee uudelleen (Undo/Redo).
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent

from pdf_engine.pdf_document import PDFDocumentModel
from ui.page_canvas import PDFPageCanvas
from ui.shape_properties_dock import ShapePropertiesDock

app = QApplication.instance() or QApplication([])


class TestTextboxAndAlignment(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/tmp/test_textbox_alignment_sample.pdf"
        doc = fitz.open()
        p = doc.new_page(width=500, height=500)
        p.insert_text((50, 80), "DOKUMENTIN ALKUPERAINEN OTSIKKO", fontsize=14)
        doc.save(self.doc_path)
        doc.close()

    def tearDown(self):
        if os.path.exists(self.doc_path):
            try:
                os.remove(self.doc_path)
            except Exception:
                pass

    def test_create_textbox_shape(self):
        """Varmistaa että textbox-tyyppinen muoto luodaan ja teksti renderöityy sivulle."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(60, 100, 300, 180),
            fill_color=(1.0, 1.0, 1.0),
            stroke_color=(0.2, 0.4, 0.7),
            stroke_width=1.5,
            text="Mika Kallio",
            font_family="Helvetica",
            font_size=18.0,
            text_align="center",
            vertical_align="middle"
        )
        self.assertTrue(s_id.startswith("shape_"))
        shape = model.get_shape(0, s_id)
        self.assertEqual(shape["type"], "textbox")
        self.assertEqual(shape["text"], "Mika Kallio")
        self.assertEqual(shape["text_align"], "center")

        # Tarkistetaan että teksti renderöityy PyMuPDF-sivulle
        page_text = model.doc[0].get_text()
        self.assertIn("Mika Kallio", page_text)

    def test_add_text_to_existing_rounded_rectangle(self):
        """Varmistaa käyttäjän tapauksen: teksti lisätään jo olemassa olevaan valkoiseen pyöristettyyn laatikkoon."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        # 1. Käyttäjä loi ensin pyöristetyn laatikon ilman tekstiä
        s_id = model.draw_shape(
            page_idx=0,
            shape_type="rounded_rect",
            geometry=(50, 120, 250, 200),
            fill_color=(1.0, 1.0, 1.0),
            stroke_color=(0.2, 0.4, 0.8),
            stroke_width=1.5,
            radius=8.0,
            overlay=True,
            name="Pyöristetty laatikko 1"
        )
        shape_before = model.get_shape(0, s_id)
        self.assertEqual(shape_before["text"], "")

        # 2. Käyttäjä kirjoittaa nimensä laatikkoon ja valitsee keskitetyn tasauksen
        model.update_shape(
            0,
            s_id,
            text="Mika",
            font_family="Helvetica",
            font_size=16.0,
            font_bold=True,
            text_align="center",
            vertical_align="middle",
            push_undo=True
        )

        shape_after = model.get_shape(0, s_id)
        self.assertEqual(shape_after["text"], "Mika")
        self.assertTrue(shape_after["font_bold"])
        self.assertEqual(shape_after["text_align"], "center")

        # Tarkistetaan että teksti näkyy dokumentissa
        page_text = model.doc[0].get_text()
        self.assertIn("Mika", page_text)

    def test_text_alignments_and_vertical_alignments(self):
        """Testaa vasemman, keskitetyn, oikean ja tasatun tasauksen sekä pystysuunnan."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        alignments = ["left", "center", "right", "justify"]
        valignments = ["top", "middle", "bottom"]

        for align in alignments:
            for valign in valignments:
                s_id = model.draw_shape(
                    page_idx=0,
                    shape_type="textbox",
                    geometry=(50, 100, 350, 220),
                    text=f"Rivi tekstiä tasauksella {align} ja {valign}",
                    font_size=12.0,
                    text_align=align,
                    vertical_align=valign
                )
                shape = model.get_shape(0, s_id)
                self.assertEqual(shape["text_align"], align)
                self.assertEqual(shape["vertical_align"], valign)
                self.assertIn(align, model.doc[0].get_text())

    def test_typography_styles_bold_italic_and_fonts(self):
        """Testaa leikkaukset (bold, italic) ja eri fonttiperheet (Times, Courier, Helvetica)."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        fonts = [
            ("Helvetica", True, False),
            ("Times New Roman", False, True),
            ("Courier", True, True)
        ]

        for fam, bold, italic in fonts:
            s_id = model.draw_shape(
                page_idx=0,
                shape_type="textbox",
                geometry=(50, 100, 300, 160),
                text=f"Typografia {fam}",
                font_family=fam,
                font_size=16.0,
                font_bold=bold,
                font_italic=italic,
                text_color=(0.1, 0.2, 0.6)
            )
            shape = model.get_shape(0, s_id)
            self.assertEqual(shape["font_family"], fam)
            self.assertEqual(shape["font_bold"], bold)
            self.assertEqual(shape["font_italic"], italic)
            self.assertIn(fam, model.doc[0].get_text())

    def test_shape_properties_dock_loads_and_syncs_text(self):
        """Testaa että ShapePropertiesDock lataa muodon tekstit ja lähettää muutokset."""
        dock = ShapePropertiesDock()

        shape_data = {
            "id": "shape_test",
            "name": "Pyöristetty laatikko 1",
            "type": "rounded_rect",
            "fill_color": (1.0, 1.0, 1.0),
            "stroke_color": (0.2, 0.4, 0.8),
            "stroke_width": 2.0,
            "radius": 10.0,
            "text": "Mika Testi",
            "font_family": "Times New Roman",
            "font_size": 20.0,
            "font_bold": True,
            "font_italic": False,
            "text_color": (0.0, 0.0, 0.0),
            "text_align": "right",
            "vertical_align": "bottom"
        }

        dock.load_shape_properties(shape_data)
        self.assertEqual(dock.txt_shape_text.toPlainText(), "Mika Testi")
        self.assertEqual(dock.combo_font_family.currentText(), "Times New Roman")
        self.assertEqual(dock.spin_font_size.value(), 20.0)
        self.assertTrue(dock.btn_text_bold.isChecked())
        self.assertFalse(dock.btn_text_italic.isChecked())
        self.assertTrue(dock.btn_align_right.isChecked())

        # Testataan tekstin muokkaus dockissa
        received = {}
        dock.properties_changed.connect(lambda p: received.update(p))

        dock.txt_shape_text.setPlainText("Uusi teksti")
        self.assertEqual(received.get("text"), "Uusi teksti")

    def test_canvas_double_click_triggers_inline_shape_editor(self):
        """Testaa että tuplaklikkaus kankaalla muodon päällä aktivoi tekstieditorin."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.show()
        canvas.set_document(model)
        canvas.set_page(0)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="rounded_rect",
            geometry=(50, 50, 200, 120),
            text="Vanha teksti"
        )

        focus_signals = []
        canvas.request_focus_shape_text.connect(lambda sid: focus_signals.append(sid))

        # Simuloidaan tuplaklikkaus laatikon keskelle: (100, 80) pt -> pikselit zoomilla 1.5 = (150, 120)
        click_pos = QPointF(100 * canvas.zoom_factor, 80 * canvas.zoom_factor)
        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            click_pos,
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseDoubleClickEvent(event)

        self.assertEqual(canvas.selected_shape_id, s_id)
        self.assertEqual(focus_signals, [s_id])
        self.assertTrue(canvas.inline_shape_editor.isVisible())
        self.assertEqual(canvas.inline_shape_editor.toPlainText(), "Vanha teksti")

        # Päivitetään teksti kelluvassa editorissa ja lopetetaan editointi
        canvas.inline_shape_editor.setPlainText("Mika Uusi Teksti")
        canvas.finish_inline_shape_editor(commit=True)

        self.assertFalse(canvas.inline_shape_editor.isVisible())
        updated = model.get_shape(0, s_id)
        self.assertEqual(updated["text"], "Mika Uusi Teksti")
        self.assertIn("Mika Uusi Teksti", model.doc[0].get_text())

    def test_undo_redo_shape_text(self):
        """Varmistaa että tekstin muutos kumoutuu Ctrl+Z:lla ja palautuu Ctrl+Y:lla."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(50, 50, 200, 100),
            text="Alkuperäinen teksti"
        )

        model.update_shape(0, s_id, text="Muokattu teksti", push_undo=True)
        self.assertEqual(model.get_shape(0, s_id)["text"], "Muokattu teksti")
        self.assertIn("Muokattu teksti", model.doc[0].get_text())

        # Kumoa (Undo)
        self.assertTrue(model.can_undo)
        model.undo()
        self.assertEqual(model.get_shape(0, s_id)["text"], "Alkuperäinen teksti")
        self.assertIn("Alkuperäinen teksti", model.doc[0].get_text())

        # Tee uudelleen (Redo)
        self.assertTrue(model.can_redo)
        model.redo()
        self.assertEqual(model.get_shape(0, s_id)["text"], "Muokattu teksti")
        self.assertIn("Muokattu teksti", model.doc[0].get_text())


if __name__ == "__main__":
    unittest.main()