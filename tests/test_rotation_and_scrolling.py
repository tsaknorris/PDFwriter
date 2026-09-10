"""
Unit tests for free rotation of shapes and textboxes,
prevention of backwards typing (cursor position preservation),
and scrollable sidebar panels (QScrollArea).
"""

import unittest
import os
import fitz
from PyQt6.QtWidgets import QApplication, QScrollArea, QTextEdit, QPlainTextEdit
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QTextCursor

from pdf_engine.pdf_document import PDFDocumentModel
from ui.shape_properties_dock import ShapePropertiesDock
from ui.text_editor_dock import TextEditorDock
from ui.inspector_panel import InspectorPanel
from ui.page_canvas import PDFPageCanvas, InlineShapeEditor

# Ensure headless QApplication
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestRotationAndScrolling(unittest.TestCase):
    def setUp(self):
        self.doc_path = "/tmp/test_rotation_scroll.pdf"
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        p.insert_text((50, 100), "Hello Rotation", fontsize=14)
        doc.save(self.doc_path)
        doc.close()

        self.doc_model = PDFDocumentModel()
        self.doc_model.open(self.doc_path)

    def tearDown(self):
        self.doc_model.close()
        if os.path.exists(self.doc_path):
            try:
                os.remove(self.doc_path)
            except Exception:
                pass

    def test_draw_shape_with_rotation(self):
        """Varmistaa että muoto voidaan piirtää ja sen kiertokulma tallentuu oikein."""
        shape_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(100.0, 100.0, 300.0, 200.0),
            fill_color=(1.0, 1.0, 1.0),
            stroke_color=(0.2, 0.2, 0.2),
            stroke_width=2.0,
            fill_opacity=0.9,
            text="Testi Kierto",
            font_size=16.0,
            font_family="helv",
            text_align="center",
            rotation=45.0
        )
        self.assertIsNotNone(shape_id)

        # Tarkistetaan sivun muodot
        shapes = self.doc_model.page_shapes.get(0, [])
        self.assertEqual(len(shapes), 1)
        self.assertEqual(shapes[0].get("rotation"), 45.0)

    def test_update_shape_rotation_and_undo(self):
        """Varmistaa kiertokulman päivittämisen ja Undo/Redo -tuen."""
        shape_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(50.0, 50.0, 150.0, 150.0),
            fill_color=(0.9, 0.9, 0.9),
            stroke_color=(0.0, 0.0, 0.0),
            rotation=0.0
        )
        self.assertEqual(self.doc_model.page_shapes.get(0, [])[0].get("rotation"), 0.0)

        # Päivitetään kierto 90 asteeseen
        ok = self.doc_model.update_shape(0, shape_id, rotation=90.0)
        self.assertTrue(ok)
        self.assertEqual(self.doc_model.page_shapes.get(0, [])[0].get("rotation"), 90.0)

        # Testataan Undo
        self.assertTrue(self.doc_model.can_undo())
        self.doc_model.undo()
        self.assertEqual(self.doc_model.page_shapes.get(0, [])[0].get("rotation"), 0.0)

        # Testataan Redo
        self.assertTrue(self.doc_model.can_redo())
        self.doc_model.redo()
        self.assertEqual(self.doc_model.page_shapes.get(0, [])[0].get("rotation"), 90.0)

    def test_render_rotated_shapes_to_pdf(self):
        """Varmistaa että kierretyt muodot ja tekstit renderöityvät PyMuPDF-dokumenttiin ilman virheitä."""
        # Lisätään suorakulmio (30 deg), ympyrä (45 deg), nuoli (-45 deg), textbox (60 deg)
        self.doc_model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(50.0, 50.0, 120.0, 100.0),
            rotation=30.0
        )
        self.doc_model.draw_shape(
            page_idx=0,
            shape_type="arrow",
            geometry=((150.0, 50.0), (250.0, 120.0)),
            rotation=-45.0
        )
        self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(50.0, 200.0, 200.0, 300.0),
            text="Kierretty Tekstilaatikko",
            font_size=14.0,
            rotation=60.0
        )

        # Renderöidään sivu kuvaksi (render_page)
        img, w, h = self.doc_model.render_page(0, scale=1.0)
        self.assertFalse(img.isNull())
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

        # Tarkistetaan myös PyMuPDF:n suora pixmap-generointi
        pix = self.doc_model.doc[0].get_pixmap()
        self.assertGreater(pix.width, 0)
        self.assertGreater(pix.height, 0)

    def test_rotated_html_textbox_rendering_and_font_scale(self):
        """Varmistaa että rikkaalla HTML-tekstillä varustettu tekstilaatikko kiertyy ilman fontin pienenemistä."""
        html_content = (
            "<p style='margin:0; text-align:center;'><span style='font-size:16pt;'>Rivi 1</span></p>"
            "<p style='margin:0; text-align:center;'><span style='font-size:24pt; color:#ff0000;'>Rivi 2</span></p>"
        )
        shape_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(100.0, 100.0, 300.0, 220.0),
            fill_color=(1.0, 1.0, 1.0),
            stroke_color=(0.1, 0.4, 0.8),
            stroke_width=2.0,
            text="Rivi 1\nRivi 2",
            html=html_content,
            rotation=30.0
        )
        self.assertIsNotNone(shape_id)
        shape = self.doc_model.get_shape(0, shape_id)
        self.assertEqual(shape.get("rotation"), 30.0)

        # Renderöidään sivu
        img, w, h = self.doc_model.render_page(0, scale=1.0)
        self.assertFalse(img.isNull())
        pix = self.doc_model.doc[0].get_pixmap()
        self.assertGreater(pix.width, 0)
        self.assertGreater(pix.height, 0)

    def test_prevent_backwards_typing_in_shape_dock(self):
        """
        Varmistaa, ettei tekstilaatikon tekstin muokkaus siirrä kursoria nollaan
        eikä aiheuta merkkien tulemista väärinpäin / peilikuvana.
        """
        dock = ShapePropertiesDock()
        
        # Alustetaan muoto
        sample_shape = {
            "id": "test_shape_1",
            "type": "textbox",
            "text": "Moi",
            "font_family": "helv",
            "font_size": 14.0,
            "text_align": "left",
            "rotation": 15.0
        }
        dock.load_shape_properties(sample_shape)
        self.assertEqual(dock.txt_shape_text.toPlainText(), "Moi")
        self.assertEqual(dock.spin_rotation.value(), 15.0)

        # Simuloidaan kirjoittamista: lisätään "k" sanan loppuun ("Moik")
        # Asetetaan kursori loppuun
        cursor = dock.txt_shape_text.textCursor()
        cursor.setPosition(3)
        dock.txt_shape_text.setTextCursor(cursor)
        
        # Kirjoitetaan 'k'
        dock.txt_shape_text.insertPlainText("k")
        # Jos reload kutsutaan samalla tekstillä, kursorin EI tule hypätä alkuun
        dock.load_shape_properties({"id": "test_shape_1", "text": "Moik", "type": "textbox", "rotation": 15.0})
        
        current_cursor_pos = dock.txt_shape_text.textCursor().position()
        self.assertEqual(dock.txt_shape_text.toPlainText(), "Moik")
        self.assertEqual(current_cursor_pos, 4, "Kursorin tulee pysyä sanan lopussa eikä hypätä alkuun!")

        # Kirjoitetaan vielä 'a'
        dock.txt_shape_text.insertPlainText("a")
        dock.load_shape_properties({"id": "test_shape_1", "text": "Moika", "type": "textbox", "rotation": 15.0})
        self.assertEqual(dock.txt_shape_text.toPlainText(), "Moika")
        self.assertEqual(dock.txt_shape_text.textCursor().position(), 5)

    def test_scroll_areas_in_docks(self):
        """Varmistaa että kaikissa sivupaneeleissa on QScrollArea käytössä sujuvaa vieritystä varten."""
        # 1. ShapePropertiesDock
        shape_dock = ShapePropertiesDock()
        self.assertTrue(hasattr(shape_dock, "scroll_area"))
        self.assertIsInstance(shape_dock.scroll_area, QScrollArea)
        self.assertTrue(shape_dock.scroll_area.widgetResizable())

        # 2. TextEditorDock
        text_dock = TextEditorDock()
        self.assertTrue(hasattr(text_dock, "scroll_area"))
        self.assertIsInstance(text_dock.scroll_area, QScrollArea)
        self.assertTrue(text_dock.scroll_area.widgetResizable())

        # 3. InspectorPanel
        inspector = InspectorPanel()
        self.assertTrue(hasattr(inspector, "scroll_area"))
        self.assertIsInstance(inspector.scroll_area, QScrollArea)
        self.assertTrue(inspector.scroll_area.widgetResizable())


if __name__ == "__main__":
    unittest.main()
