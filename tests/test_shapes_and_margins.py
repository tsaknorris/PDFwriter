"""
Muotojen (Shapes & Blocks), nuolien ja sivumarginaalien yksikkö- ja integraatiotestit.
Testaa suorakulmiot, pyöristetyt laatikot, ympyrät, nuolet, viivat,
taustakortit tekstin alle (overlay=False), CropBox/MediaBox -marginaalit,
Undo/Redo -palautuksen sekä Gauntlet Loop -eheyden.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.validator import GauntletValidator
from ui.main_window import MainWindow
from ui.margins_dialog import MarginsDialog

app = QApplication.instance() or QApplication([])


class TestShapesAndMargins(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/tmp/test_shapes_margins_main.pdf"
        self.saved_output_path = "/tmp/test_shapes_margins_output.pdf"

        # Luodaan 2-sivuinen testisivu teksteineen
        doc = fitz.open()
        p1 = doc.new_page(width=500, height=500)
        p1.insert_text((80, 120), "HELLO UNDERLAY TEXT", fontsize=16)
        p1.insert_text((80, 200), "SECOND PARAGRAPH CONTENT", fontsize=14)

        p2 = doc.new_page(width=500, height=500)
        p2.insert_text((50, 100), "PAGE TWO DATA", fontsize=14)

        doc.save(self.doc_path)
        doc.close()

    def tearDown(self):
        for p in (self.doc_path, self.saved_output_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_draw_shape_behind_text(self):
        """Varmistaa, että muoto tekstin alle (overlay=False) säilyttää tekstin 100 % ehjänä."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        text_before = model.doc[0].get_text()
        self.assertIn("HELLO UNDERLAY TEXT", text_before)
        self.assertFalse(model.can_undo())

        # Piirretään pyöristetty taustalaatikko tekstin alle
        success = model.draw_shape(
            page_idx=0,
            shape_type="rounded_rect",
            geometry=(70, 95, 300, 140),
            fill_color=(0.95, 0.95, 0.8),
            stroke_color=(0.8, 0.6, 0.2),
            stroke_width=2.0,
            radius=8.0,
            overlay=False  # Behind Text!
        )
        self.assertTrue(success)
        self.assertTrue(model.can_undo())

        # Varmistetaan että teksti on yhä täysin luettavissa eikä ole kadonnut tai muuttunut
        text_after = model.doc[0].get_text()
        self.assertEqual(text_before, text_after)

        # Testataan Undo
        model.undo()
        self.assertFalse(model.can_undo())
        self.assertTrue(model.can_redo())

        # Testataan Redo
        model.redo()
        self.assertTrue(model.can_undo())
        model.close()

    def test_draw_shape_over_text(self):
        """Varmistaa, että muoto tekstin päälle (overlay=True) voidaan piirtää ja kumota."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        success = model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(50, 50, 200, 150),
            fill_color=(1.0, 0.0, 0.0),
            stroke_color=(0.5, 0.0, 0.0),
            fill_opacity=0.5,
            overlay=True  # Over Text!
        )
        self.assertTrue(success)
        self.assertTrue(model.can_undo())
        model.undo()
        self.assertFalse(model.can_undo())
        model.close()

    def test_all_shape_types(self):
        """Testaa suorakulmion, pyöristetyn laatikon, ympyrän, nuolen ja viivan piirron."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        # 1. Suorakulmio
        self.assertTrue(model.draw_shape(0, "rect", (20, 20, 100, 80)))
        # 2. Pyöristetty laatikko
        self.assertTrue(model.draw_shape(0, "rounded_rect", (120, 20, 200, 80), radius=10.0))
        # 3. Ympyrä / Ellipsi
        self.assertTrue(model.draw_shape(0, "circle", (220, 20, 300, 80)))
        # 4. Nuoli
        self.assertTrue(model.draw_shape(0, "arrow", ((50, 250), (250, 320)), stroke_color=(0.9, 0.1, 0.1), stroke_width=3.0))
        # 5. Viiva
        self.assertTrue(model.draw_shape(0, "line", ((50, 350), (250, 350)), stroke_width=2.0))

        # Kokeillaan tallentaa ja varmistaa dokumentin eheys
        model.save(self.saved_output_path)
        model.close()

        report = GauntletValidator.audit_document(self.saved_output_path)
        self.assertTrue(report.is_valid)

    def test_add_background_card_for_block(self):
        """Testaa automaattisen taustakortin luomisen tekstilohkon alle."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        blocks = model.get_blocks_for_page(0)
        self.assertGreater(len(blocks), 0)
        target_block = blocks[0]

        success = model.add_background_card_for_block(0, target_block, padding=8.0)
        self.assertTrue(success)
        self.assertTrue(model.can_undo())

        # Varmistetaan että teksti säilyi identtisenä
        self.assertIn(target_block["text"].split()[0], model.doc[0].get_text())

        model.undo()
        self.assertFalse(model.can_undo())
        model.close()

    def test_page_margins_cropbox(self):
        """Testaa sivun marginaalien säätämisen CropBox-tilassa (rajaus)."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        orig_boxes = model.get_page_boxes(0)
        orig_w = orig_boxes["width_pt"]
        orig_h = orig_boxes["height_pt"]
        self.assertEqual(orig_w, 500.0)
        self.assertEqual(orig_h, 500.0)

        # Rajataan reunoja 20 pt jokaiselta sivulta
        model.set_page_margins(0, left_pt=20.0, top_pt=20.0, right_pt=20.0, bottom_pt=20.0, mode="cropbox")
        new_boxes = model.get_page_boxes(0)
        self.assertEqual(new_boxes["width_pt"], 460.0)
        self.assertEqual(new_boxes["height_pt"], 460.0)
        self.assertTrue(model.can_undo())

        # Undo palauttaa alkuperäisen leveyden ja korkeuden
        model.undo()
        reverted_boxes = model.get_page_boxes(0)
        self.assertEqual(reverted_boxes["width_pt"], 500.0)
        self.assertEqual(reverted_boxes["height_pt"], 500.0)
        model.close()

    def test_page_margins_mediabox(self):
        """Testaa sivun arkkikoon laajentamisen MediaBox-tilassa."""
        model = PDFDocumentModel()
        model.open(self.doc_path)

        # Laajennetaan arkkikokoa 50 pt joka suuntaan (+100 pt leveys ja korkeus)
        model.set_page_margins(0, left_pt=50.0, top_pt=50.0, right_pt=50.0, bottom_pt=50.0, mode="mediabox")
        new_boxes = model.get_page_boxes(0)
        self.assertEqual(new_boxes["width_pt"], 600.0)
        self.assertEqual(new_boxes["height_pt"], 600.0)
        self.assertTrue(model.can_undo())

        model.undo()
        reverted = model.get_page_boxes(0)
        self.assertEqual(reverted["width_pt"], 500.0)
        model.close()

    def test_main_window_integration(self):
        """Testaa pääikkunan, muotopalkin ja marginaalidialogin integroinnin."""
        window = MainWindow()
        window.open_file(self.doc_path)

        # Testataan muototyökalun valinta
        window.shape_widget.set_tool("arrow")
        self.assertEqual(window.canvas.active_tool, "arrow")

        # Testataan taustalaatikon pikalisäys
        blocks = window.doc_model.get_blocks_for_page(0)
        window.canvas.selected_block = blocks[0]
        window.canvas.add_background_card_to_selected_block()
        self.assertTrue(window.act_undo.isEnabled())

        # Undo toimii pääikkunassa
        window.act_undo.trigger()
        self.assertFalse(window.act_undo.isEnabled())

        # Marginaaliohjaimet
        window.canvas.set_show_margin_guides(False)
        self.assertFalse(window.canvas.show_margin_guides)
        window.canvas.set_show_margin_guides(True)
        self.assertTrue(window.canvas.show_margin_guides)

        # Marginaalidialogi
        dlg = MarginsDialog(window.doc_model, 0, window)
        self.assertIsNotNone(dlg)
        dlg.close()

        window.close()


if __name__ == "__main__":
    unittest.main()
