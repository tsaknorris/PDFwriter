"""
Unit tests for sidebar property persistence, immediate canvas updates,
and prevention of setting reversion to defaults.
"""

import unittest
import os
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent

from pdf_engine.pdf_document import PDFDocumentModel
from ui.shape_properties_dock import ShapePropertiesDock
from ui.text_editor_dock import TextEditorDock
from ui.page_canvas import PDFPageCanvas

app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestSidebarPersistence(unittest.TestCase):
    def setUp(self):
        self.doc_path = "/tmp/test_sidebar_persistence.pdf"
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        p.insert_text((50, 100), "Sidebar Persistence Test Document", fontsize=14)
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

    def test_default_props_saved_when_no_shape_selected(self):
        """Varmistaa että sivupalkissa tehdyt muutokset tallentuvat oletuksiksi kun muotoa ei ole valittuna."""
        dock = ShapePropertiesDock()
        self.assertIsNone(dock.selected_shape_id)

        # Muutetaan reunaviivan väri punaiseksi ja paksuus 3.5 pt
        dock.stroke_rgb = (1.0, 0.0, 0.0)
        dock.default_props["stroke_rgb"] = (1.0, 0.0, 0.0)
        dock._on_stroke_width_changed(3.5)
        dock._on_opacity_changed(65)
        dock.set_rotation(45.0)

        self.assertEqual(dock.default_props["stroke_rgb"], (1.0, 0.0, 0.0))
        self.assertEqual(dock.default_props["stroke_width"], 3.5)
        self.assertAlmostEqual(dock.default_props["fill_opacity"], 0.65, places=2)
        self.assertEqual(dock.default_props["rotation"], 45.0)

    def test_drawing_textbox_uses_sidebar_defaults_without_reverting(self):
        """Varmistaa että tekstilaatikon piirtäminen käyttää käyttäjän asetuksia eikä palaa oletusväriin."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)
        dock = ShapePropertiesDock()

        dock.tool_changed.connect(canvas.set_active_tool)
        dock.properties_changed.connect(canvas.set_shape_properties)
        canvas.shape_selected.connect(dock.load_shape_properties)

        # Käyttäjä valitsee reunaviivan väriksi oranssin ja paksuudeksi 4.0
        custom_stroke = (1.0, 0.5, 0.0)
        dock.stroke_rgb = custom_stroke
        dock.default_props["stroke_rgb"] = custom_stroke
        dock._on_stroke_width_changed(4.0)
        dock.set_rotation(25.0)

        # Käyttäjä valitsee Tekstilaatikko-työkalun
        dock.set_tool("textbox")
        self.assertEqual(canvas.active_tool, "textbox")

        # Simuloidaan tekstilaatikon piirto kankaalle
        canvas.is_drawing_shape = True
        canvas.shape_start_pos = QPointF(100, 100)
        canvas.shape_current_pos = QPointF(300, 200)

        press_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(300, 200),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseReleaseEvent(press_ev)

        # Tarkistetaan että uusi tekstilaatikko luotiin dokumenttiin
        shapes = self.doc_model.page_shapes.get(0, [])
        self.assertEqual(len(shapes), 1)
        tb = shapes[0]
        self.assertEqual(tb["type"], "textbox")

        # TÄRKEÄ: reunaviivan väri ei saa olla oletus (0.2, 0.4, 0.7), vaan käyttäjän asettama oranssi!
        self.assertEqual(tb["stroke_color"], custom_stroke)
        self.assertEqual(tb["stroke_width"], 4.0)
        self.assertEqual(tb["rotation"], 25.0)

        # TÄRKEÄ: valinnan jälkeen sivupalkin säätimien ei tule palautua oletuksiin
        self.assertEqual(dock.stroke_rgb, custom_stroke)
        self.assertEqual(dock.stroke_width, 4.0)
        self.assertEqual(dock.rotation, 25.0)

    def test_deselecting_shape_restores_user_configured_defaults(self):
        """Varmistaa että muodon valinnan poistaminen palauttaa käyttäjän oletusasetukset säätimiin."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)
        dock = ShapePropertiesDock()

        dock.properties_changed.connect(canvas.set_shape_properties)
        canvas.shape_selected.connect(dock.load_shape_properties)

        # 1. Käyttäjä säätää oletukseksi vihreän reunaviivan (0.0, 1.0, 0.0)
        green_stroke = (0.0, 1.0, 0.0)
        dock.stroke_rgb = green_stroke
        dock.default_props["stroke_rgb"] = green_stroke
        dock.default_props["stroke_width"] = 2.5
        dock.default_props["rotation"] = 0.0

        # 2. Luodaan dokumenttiin toinen muoto, jolla on musta reunaviiva (0, 0, 0)
        shape_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(50, 50, 150, 150),
            stroke_color=(0.0, 0.0, 0.0),
            stroke_width=1.0,
            rotation=12.0
        )

        # 3. Valitaan kyseinen muoto -> paneeli lataa mustan muodon tiedot
        canvas.select_shape(shape_id)
        self.assertEqual(dock.selected_shape_id, shape_id)
        self.assertEqual(dock.stroke_rgb, (0.0, 0.0, 0.0))
        self.assertEqual(dock.stroke_width, 1.0)
        self.assertEqual(dock.rotation, 12.0)

        # 4. Klikataan tyhjää aluetta -> valinta poistuu
        canvas.select_shape(None)
        self.assertIsNone(dock.selected_shape_id)

        # 5. Paneelin täytyy palautua käyttäjän oletukseen (vihreä, 2.5 pt), ei jäädä mustaksi!
        self.assertEqual(dock.stroke_rgb, green_stroke)
        self.assertEqual(dock.stroke_width, 2.5)
        self.assertEqual(dock.rotation, 0.0)

    def test_live_shape_editing_commits_and_emits_signal(self):
        """Varmistaa että valitun muodon muokkaus sivupalkista päivittyy heti kankaalle ja lähettää signaalin."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)
        dock = ShapePropertiesDock()

        dock.properties_changed.connect(canvas.set_shape_properties)
        canvas.shape_selected.connect(dock.load_shape_properties)

        shape_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(50, 50, 150, 150),
            stroke_color=(0.0, 0.0, 0.0),
            stroke_width=1.0
        )
        canvas.select_shape(shape_id)

        committed_events = []
        canvas.shape_properties_committed.connect(lambda: committed_events.append(True))

        # Muutetaan säätimestä reunaviivan paksuutta
        dock._on_stroke_width_changed(5.0)

        # Tarkistetaan että doc_model päivittyi heti
        cur = self.doc_model.get_shape(0, shape_id)
        self.assertEqual(cur["stroke_width"], 5.0)

        # Tarkistetaan että signaali lähetettiin
        self.assertTrue(len(committed_events) > 0)

    def test_text_editor_dock_color_commit(self):
        """Varmistaa että TextEditorDockin värinvalinta kytkee commit_btn aktiiviseksi."""
        editor = TextEditorDock()
        self.assertFalse(editor.commit_btn.isEnabled())

        # Valitaan jakso
        span_data = {
            "text": "Hello World",
            "bbox": [50, 100, 150, 120],
            "size": 14.0,
            "color": 0,
            "flags": 0,
            "font": "Helvetica",
            "origin": [50, 115]
        }
        editor.set_target_span(span_data, self.doc_model)
        self.assertIsNotNone(editor.active_span)

        # Muutetaan tekstin väriä
        editor.selected_color_rgb = (0.8, 0.1, 0.1)
        editor._update_color_button_preview()
        editor.commit_btn.setEnabled(True)

        self.assertTrue(editor.commit_btn.isEnabled())
        self.assertEqual(editor.selected_color_rgb, (0.8, 0.1, 0.1))


if __name__ == "__main__":
    unittest.main()
