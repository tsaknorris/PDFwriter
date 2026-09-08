"""
Yksikkö- ja integraatiotestit:
1. Jo dokumenttiin asetettujen objektien opasiteetin ja ominaisuuksien reaaliaikainen muokkaus.
2. MOVE-siirtotyökalu (V), automaattinen paluu MOVE-tilaan piirron jälkeen.
3. Muodon raahaaminen kankaalla ja Undo/Redo.
4. Nuolinäppäinsiirto (Keyboard Nudge) 1 pt ja 10 pt askelein.
5. Muodon poistaminen (Delete).
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QKeyEvent

from pdf_engine.pdf_document import PDFDocumentModel
from ui.page_canvas import PDFPageCanvas
from ui.shape_properties_dock import ShapePropertiesDock
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication([])


class TestMoveAndOpacity(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/tmp/test_move_opacity_sample.pdf"
        doc = fitz.open()
        p = doc.new_page(width=500, height=500)
        p.insert_text((50, 100), "TEST DOKUMENTTI OBJETEILLE", fontsize=14)
        doc.save(self.doc_path)
        doc.close()

    def tearDown(self):
        if os.path.exists(self.doc_path):
            try:
                os.remove(self.doc_path)
            except Exception:
                pass

    def test_modify_opacity_of_already_placed_shape(self):
        """Varmistaa, että kankaalle jo asetetun muodon opasiteetti muuttuu heti dokumentissa."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(0)

        # 1. Luodaan muoto jolla 85 % opasiteetti
        s_id = model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(60, 60, 200, 150),
            fill_color=(0.2, 0.4, 0.8),
            fill_opacity=0.85,
            stroke_width=2.0
        )
        self.assertTrue(len(s_id) > 0)
        self.assertEqual(model.get_shape(0, s_id)["fill_opacity"], 0.85)

        # 2. Valitaan muoto
        canvas.select_shape(s_id)
        self.assertEqual(canvas.selected_shape_id, s_id)

        # 3. Muutetaan opasiteetti 35 %:iin (0.35)
        canvas.set_shape_properties({"fill_opacity": 0.35, "target_shape_id": s_id})

        # 4. Varmistetaan että muodon opasiteetti päivittyi dokumenttimallissa
        updated = model.get_shape(0, s_id)
        self.assertAlmostEqual(updated["fill_opacity"], 0.35, delta=0.01)

        # 5. Varmistetaan että renderöinti onnistuu virheettömästi uudella opasiteetilla
        img, w, h = model.render_page(0)
        self.assertIsNotNone(img)

    def test_shape_properties_dock_loads_and_syncs_properties(self):
        """Varmistaa, että ShapePropertiesDock lataa valitun muodon tiedot liukusäätimiin."""
        dock = ShapePropertiesDock()
        shape_data = {
            "id": "shape_test_1",
            "name": "Korostuslaatikko",
            "type": "rounded_rect",
            "geometry": (50, 50, 150, 120),
            "fill_color": (0.9, 0.1, 0.1),
            "fill_opacity": 0.42,
            "stroke_color": (0.1, 0.1, 0.1),
            "stroke_width": 3.0,
            "radius": 12.0,
            "overlay": False
        }

        dock.load_shape_properties(shape_data)

        self.assertEqual(dock.selected_shape_id, "shape_test_1")
        self.assertEqual(dock.slider_opacity.value(), 42)
        self.assertEqual(dock.lbl_opacity.text(), "42 %")
        self.assertTrue(dock.chk_fill.isChecked())
        self.assertEqual(dock.spin_stroke_width.value(), 3.0)
        self.assertEqual(dock.spin_radius.value(), 12.0)
        self.assertTrue(dock.rb_behind.isChecked())
        self.assertTrue(dock.btn_delete_shape.isEnabled())
        self.assertIn("Korostuslaatikko", dock.lbl_selection_status.text())

        # Testataan tyhjennys kun valinta poistuu
        dock.load_shape_properties({})
        self.assertIsNone(dock.selected_shape_id)
        self.assertFalse(dock.btn_delete_shape.isEnabled())

    def test_auto_switch_to_move_tool_after_drawing(self):
        """Varmistaa, että muodon piirtämisen jälkeen työkalu palautuu automaattisesti MOVE-tilaan."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(0)
        canvas.resize(600, 600)

        # Asetetaan piirtotyökalu
        canvas.set_active_tool("rect")
        self.assertEqual(canvas.active_tool, "rect")

        # Simuloidaan suorakulmion veto
        p1 = QPointF(80 * canvas.zoom_factor, 80 * canvas.zoom_factor)
        p2 = QPointF(200 * canvas.zoom_factor, 180 * canvas.zoom_factor)

        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, p1, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        self.assertTrue(canvas.is_drawing_shape)

        move = QMouseEvent(QMouseEvent.Type.MouseMove, p2, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)

        release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, p2, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)

        # Varmistetaan että työkalu palautui MOVE-tilaan
        self.assertEqual(canvas.active_tool, "move")
        # Varmistetaan että uusi muoto on valittuna
        self.assertIsNotNone(canvas.selected_shape_id)
        created_shape = model.get_shape(0, canvas.selected_shape_id)
        self.assertIsNotNone(created_shape)
        self.assertEqual(created_shape["type"], "rect")

    def test_drag_move_shape_and_undo(self):
        """Varmistaa, että muoto siirtyy hiirellä raahaamalla ja siirto voidaan perua Undo-toiminnolla."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(0)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(100, 100, 200, 200),
            fill_color=(0.5, 0.5, 0.5)
        )
        canvas.select_shape(s_id)

        # Painetaan hiirellä muodon keskeltä
        center_x = 150 * canvas.zoom_factor
        center_y = 150 * canvas.zoom_factor
        press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(center_x, center_y), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        self.assertTrue(canvas.is_dragging_shape)

        # Siirretään +50 pt oikealle ja +30 pt alas
        dest_x = center_x + 50 * canvas.zoom_factor
        dest_y = center_y + 30 * canvas.zoom_factor
        move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(dest_x, dest_y), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        self.assertAlmostEqual(canvas.drag_shape_delta[0], 50.0, delta=0.1)
        self.assertAlmostEqual(canvas.drag_shape_delta[1], 30.0, delta=0.1)

        # Vapautetaan hiiri
        release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, QPointF(dest_x, dest_y), Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)
        self.assertFalse(canvas.is_dragging_shape)

        # Varmistetaan uusi sijainti
        new_geom = model.get_shape(0, s_id)["geometry"]
        self.assertAlmostEqual(new_geom[0], 150.0, delta=0.5)
        self.assertAlmostEqual(new_geom[1], 130.0, delta=0.5)
        self.assertAlmostEqual(new_geom[2], 250.0, delta=0.5)
        self.assertAlmostEqual(new_geom[3], 230.0, delta=0.5)

        # Testataan Undo
        self.assertTrue(model.can_undo())
        model.undo()
        undone_geom = model.get_shape(0, s_id)["geometry"]
        self.assertAlmostEqual(undone_geom[0], 100.0, delta=0.5)
        self.assertAlmostEqual(undone_geom[1], 100.0, delta=0.5)

    def test_keyboard_arrow_keys_nudge_shape(self):
        """Varmistaa nuolinäppäinsiirron (1 pt ja Shift pohjassa 10 pt)."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(0)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(100, 100, 200, 200)
        )
        canvas.select_shape(s_id)

        # 1 pt oikealle (Right arrow)
        key_right = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
        canvas.keyPressEvent(key_right)
        geom = model.get_shape(0, s_id)["geometry"]
        self.assertAlmostEqual(geom[0], 101.0, delta=0.01)

        # 10 pt alas (Shift + Down arrow)
        key_shift_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier)
        canvas.keyPressEvent(key_shift_down)
        geom = model.get_shape(0, s_id)["geometry"]
        self.assertAlmostEqual(geom[1], 110.0, delta=0.01)

    def test_delete_selected_shape(self):
        """Varmistaa muodon poiston delete_selected_shape -toiminnolla."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(0)

        s_id = model.draw_shape(
            page_idx=0,
            shape_type="circle",
            geometry=(50, 50, 120, 120)
        )
        canvas.select_shape(s_id)
        self.assertEqual(len(model.page_shapes.get(0, [])), 1)

        canvas.delete_selected_shape()
        self.assertIsNone(canvas.selected_shape_id)
        self.assertEqual(len(model.page_shapes.get(0, [])), 0)


if __name__ == "__main__":
    unittest.main()
