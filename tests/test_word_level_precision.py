"""
Yksikkötestit: Sanatason kirurginen korvaus (0.000 mm poikkeama),
Word-tason tekstin mustamaalaus (drag selection) ja tuplaklikkausvalinta.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent

# Varmistetaan että QApplication on alustettu testejä varten
app = QApplication.instance()
if not app:
    app = QApplication([])

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver
from ui.page_canvas import PDFPageCanvas


class TestWordLevelPrecision(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf"
        self.output_path = "/tmp/test_word_precision_out.pdf"

    def tearDown(self):
        if os.path.exists(self.output_path):
            try:
                os.remove(self.output_path)
            except Exception:
                pass

    def test_surgical_word_level_exact_alignment(self):
        """
        Testaa, että vuosiluvun muutos (2023 -> 2024) ei siirrä rivin viimeistä sanaa
        ('Technology') edes 0.001 pistettä (0.000 mm poikkeama).
        """
        if not os.path.exists(self.doc_path):
            self.skipTest(f"Testitiedostoa {self.doc_path} ei löydy.")

        model = PDFDocumentModel()
        model.open(self.doc_path)

        # Sivu 4 (indeksi 3)
        page_idx = 4
        blocks = model.get_blocks_for_page(page_idx)

        # Etsitään copyright-lohko
        target_block = None
        for b in blocks:
            if "Massachusetts Institute of Technology" in b.get("text", ""):
                target_block = b
                break

        self.assertIsNotNone(target_block, "Copyright-lohkoa ei löydetty sivulta 4")

        # Mitataan Technology-sanan 'y'-kirjaimen x1-sijainti ENNEN muokkausta
        page_before = model.doc[page_idx]
        raw_words_before = page_before.get_text("words")
        tech_words_before = [w for w in raw_words_before if "Technology" in w[4]]
        self.assertTrue(len(tech_words_before) > 0, "Technology-sanaa ei löytynyt")
        orig_tech_x1 = tech_words_before[0][2]

        orig_text = target_block["text"]
        self.assertIn("2023", orig_text)
        new_text = orig_text.replace("2023", "2024")

        font_match = FontconfigResolver.inspect_and_resolve(
            model.doc,
            target_block,
            new_text
        )

        # Suoritetaan korvaus in-place
        model.replace_block_inplace(
            page_idx=page_idx,
            block=target_block,
            new_text=new_text,
            font_match=font_match
        )

        # Mitataan Technology-sanan sijainti JÄLKEEN muokkauksen
        page_after = model.doc[page_idx]
        raw_words_after = page_after.get_text("words")
        tech_words_after = [w for w in raw_words_after if "Technology" in w[4]]
        self.assertTrue(len(tech_words_after) > 0, "Technology-sanaa ei löytynyt muokkauksen jälkeen")
        new_tech_x1 = tech_words_after[0][2]

        delta = abs(new_tech_x1 - orig_tech_x1)
        print(f"[TEST-PRECISION] Technology x1 ennen: {orig_tech_x1:.4f} pt | jälkeen: {new_tech_x1:.4f} pt | delta: {delta:.4f} pt")

        self.assertLess(delta, 0.001, f"Technology siirtyi liikaa: {delta:.4f} pt (sallittu < 0.001 pt / 0.000 mm)")

        # Tarkistetaan että 2024 löytyy sivulta
        words_2024 = [w for w in raw_words_after if "2024" in w[4]]
        self.assertTrue(len(words_2024) > 0, "Uutta vuosilukua 2024 ei löytynyt sivulta")

        model.close()

    def test_page_canvas_double_click_selection(self):
        """
        Testaa, että tuplaklikkaus kankaalla valitsee tarkan sanan ja lähettää signaalin.
        """
        if not os.path.exists(self.doc_path):
            self.skipTest(f"Testitiedostoa {self.doc_path} ei löydy.")

        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(4)

        self.assertTrue(len(canvas.page_words) > 0, "Sivun sanoja ei ladattu kankaalle")

        # Etsitään Technology-sana
        tech_w = next(w for w in canvas.page_words if "Technology" in w[4])
        # Klikkauspiste sanan keskelle (kankaan skaalatuissa pikseleissä)
        click_x = ((tech_w[0] + tech_w[2]) / 2.0) * canvas.zoom_factor
        click_y = ((tech_w[1] + tech_w[3]) / 2.0) * canvas.zoom_factor

        received_text = []
        canvas.text_selected.connect(lambda t: received_text.append(t))

        # Simuloidaan tuplaklikkaus
        dbl_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonDblClick,
            QPointF(click_x, click_y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseDoubleClickEvent(dbl_event)

        self.assertEqual(len(canvas.selected_words), 1)
        self.assertIn("Technology", canvas.selected_text)
        self.assertEqual(len(received_text), 1)
        self.assertIn("Technology", received_text[0])
        self.assertEqual(len(canvas.selected_text_rects), 1)

        # Kopiointi leikepöydälle
        canvas.copy_selection_to_clipboard()
        cb = QApplication.clipboard()
        self.assertIn("Technology", cb.text())

        model.close()

    def test_page_canvas_drag_selection_reading_order(self):
        """
        Testaa Word-tasoista tekstin mustamaalausta hiirellä vetämällä.
        """
        if not os.path.exists(self.doc_path):
            self.skipTest(f"Testitiedostoa {self.doc_path} ei löydy.")

        model = PDFDocumentModel()
        model.open(self.doc_path)

        canvas = PDFPageCanvas()
        canvas.set_document(model)
        canvas.set_page(4)

        # Etsitään kaksi peräkkäistä sanaa: "Massachusetts" ja "Institute"
        w_mass = next(w for w in canvas.page_words if "Massachusetts" in w[4])
        w_inst = next(w for w in canvas.page_words if "Institute" in w[4])

        start_x = w_mass[0] * canvas.zoom_factor
        start_y = ((w_mass[1] + w_mass[3]) / 2.0) * canvas.zoom_factor
        end_x = w_inst[2] * canvas.zoom_factor
        end_y = ((w_inst[1] + w_inst[3]) / 2.0) * canvas.zoom_factor

        # 1. Painallus alas
        press_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(start_x, start_y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mousePressEvent(press_event)

        # 2. Raahaus
        move_event = QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(end_x, end_y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseMoveEvent(move_event)

        # Varmistetaan että mustamaalaustila on aktiivinen ja sanat valittuina
        self.assertTrue(canvas.is_selecting_text)
        self.assertIn("Massachusetts", canvas.selected_text)
        self.assertIn("Institute", canvas.selected_text)
        self.assertGreaterEqual(len(canvas.selected_text_rects), 2)

        # 3. Vapautus
        release_event = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(end_x, end_y),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseReleaseEvent(release_event)

        self.assertFalse(canvas.is_selecting_text)
        self.assertIn("Massachusetts", canvas.selected_text)
        self.assertIn("Institute", canvas.selected_text)

        model.close()


if __name__ == "__main__":
    unittest.main()
