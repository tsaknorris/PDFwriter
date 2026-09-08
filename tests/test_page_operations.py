"""
Sivunhallintaoperaatioiden yksikkö- ja integraatiotestit (Page Operations Tests).
Testaa sivujen siirron, PDF:n liittämisen, tyhjän sivun lisäyksen, poiston,
kierron, monistuksen, Undo/Redo -palautuksen sekä XRef-eheyden.
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

app = QApplication.instance() or QApplication([])


class TestPageOperations(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/tmp/test_page_ops_main.pdf"
        self.secondary_pdf_path = "/tmp/test_page_ops_secondary.pdf"
        self.saved_output_path = "/tmp/test_page_ops_output.pdf"

        # Luodaan 3-sivuinen päätestitiedosto
        doc1 = fitz.open()
        p1 = doc1.new_page(width=595, height=842)
        p1.insert_text((72, 100), "PAGE ONE CONTENT", fontsize=14)
        p2 = doc1.new_page(width=595, height=842)
        p2.insert_text((72, 100), "PAGE TWO CONTENT", fontsize=14)
        p3 = doc1.new_page(width=595, height=842)
        p3.insert_text((72, 100), "PAGE THREE CONTENT", fontsize=14)
        doc1.save(self.doc_path)
        doc1.close()

        # Luodaan 2-sivuinen toissijainen PDF liitettäväksi
        doc2 = fitz.open()
        sp1 = doc2.new_page(width=595, height=842)
        sp1.insert_text((72, 100), "IMPORTED PAGE A", fontsize=14)
        sp2 = doc2.new_page(width=595, height=842)
        sp2.insert_text((72, 100), "IMPORTED PAGE B", fontsize=14)
        doc2.save(self.secondary_pdf_path)
        doc2.close()

    def tearDown(self):
        for p in (self.doc_path, self.secondary_pdf_path, self.saved_output_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_move_page(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        self.assertEqual(model.page_count, 3)

        # Siirretään sivu 0 sivun 2 perään (indeksiin 2)
        model.move_page(0, 2)
        self.assertEqual(model.page_count, 3)
        # Nyt sivun 0 pitäisi olla "PAGE TWO CONTENT" ja sivun 2 "PAGE ONE CONTENT"
        self.assertIn("PAGE TWO", model.doc[0].get_text())
        self.assertIn("PAGE ONE", model.doc[2].get_text())

        # Testataan Undo
        self.assertTrue(model.can_undo())
        model.undo()
        self.assertIn("PAGE ONE", model.doc[0].get_text())
        self.assertIn("PAGE TWO", model.doc[1].get_text())

        # Testataan Redo
        self.assertTrue(model.can_redo())
        model.redo()
        self.assertIn("PAGE TWO", model.doc[0].get_text())
        self.assertIn("PAGE ONE", model.doc[2].get_text())
        model.close()

    def test_insert_pdf_pages(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        self.assertEqual(model.page_count, 3)

        # Liitetään toissijaisen PDF:n 2 sivua sivun 1 jälkeen (indeksiin 2)
        inserted = model.insert_pdf_pages(self.secondary_pdf_path, at_idx=2)
        self.assertEqual(inserted, 2)
        self.assertEqual(model.page_count, 5)

        # Tarkistetaan että sivulla 2 on IMPORTED PAGE A
        self.assertIn("IMPORTED PAGE A", model.doc[2].get_text())
        self.assertIn("IMPORTED PAGE B", model.doc[3].get_text())
        self.assertIn("PAGE THREE", model.doc[4].get_text())

        # Testataan Undo
        model.undo()
        self.assertEqual(model.page_count, 3)
        self.assertIn("PAGE THREE", model.doc[2].get_text())
        model.close()

    def test_insert_blank_page(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        model.insert_blank_page(at_idx=1)
        self.assertEqual(model.page_count, 4)
        # Sivu 1 on tyhjä
        self.assertEqual(model.doc[1].get_text().strip(), "")
        model.close()

    def test_delete_page(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        self.assertEqual(model.page_count, 3)

        # Poistetaan sivu 1 ("PAGE TWO CONTENT")
        success = model.delete_page(1)
        self.assertTrue(success)
        self.assertEqual(model.page_count, 2)
        self.assertIn("PAGE ONE", model.doc[0].get_text())
        self.assertIn("PAGE THREE", model.doc[1].get_text())

        # Testataan Undo
        model.undo()
        self.assertEqual(model.page_count, 3)
        self.assertIn("PAGE TWO", model.doc[1].get_text())
        model.close()

    def test_rotate_page(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        self.assertEqual(model.doc[0].rotation, 0)
        self.assertFalse(model.can_undo())
        
        # Kierretään 90 astetta
        model.rotate_page(0, 90)
        self.assertEqual(model.doc[0].rotation, 90)
        self.assertTrue(model.can_undo())

        # Kierretään toisen kerran 90 astetta (yht. 180)
        model.rotate_page(0, 90)
        self.assertEqual(model.doc[0].rotation, 180)
        self.assertTrue(model.can_undo())

        # Undo 1: palataan 90 asteeseen
        model.undo()
        self.assertEqual(model.doc[0].rotation, 90)
        self.assertTrue(model.can_undo())
        self.assertTrue(model.can_redo())

        # Undo 2: palataan 0 asteeseen
        model.undo()
        self.assertEqual(model.doc[0].rotation, 0)
        self.assertFalse(model.can_undo())
        self.assertTrue(model.can_redo())

        # Redo 1: takaisin 90 asteeseen
        model.redo()
        self.assertEqual(model.doc[0].rotation, 90)
        self.assertTrue(model.can_undo())
        model.close()

    def test_duplicate_page(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        self.assertEqual(model.page_count, 3)

        model.duplicate_page(0)
        self.assertEqual(model.page_count, 4)
        self.assertIn("PAGE ONE", model.doc[0].get_text())
        self.assertIn("PAGE ONE", model.doc[1].get_text())
        model.close()

    def test_save_and_gauntlet_after_page_ops(self):
        model = PDFDocumentModel()
        model.open(self.doc_path)
        model.move_page(0, 2)
        model.insert_pdf_pages(self.secondary_pdf_path, at_idx=1)
        model.rotate_page(1, 90)
        model.save(self.saved_output_path)
        model.close()

        # Auditoitu GauntletValidatorilla
        report = GauntletValidator.audit_document(self.saved_output_path)
        self.assertTrue(report.is_valid, "Gauntlet-laaturaportti hylkäsi sivumuokkauksien jälkeisen dokumentin!")

    def test_main_window_rotation_undo_redo(self):
        window = MainWindow()
        window.open_file(self.doc_path)
        self.assertEqual(window.doc_model.doc[0].rotation, 0)
        self.assertFalse(window.act_undo.isEnabled())

        # Kierretään sivu 90 astetta pääikkunan toiminnolla (Ctrl+R / Menu)
        window.menu_rotate_page()
        self.assertEqual(window.doc_model.doc[0].rotation, 90)
        self.assertTrue(window.act_undo.isEnabled(), "Undo-toiminnon on oltava aktiivinen heti sivun kierron jälkeen!")

        # Testataan että act_undo käyttää ApplicationShortcut-kontekstia
        self.assertEqual(window.act_undo.shortcutContext(), Qt.ShortcutContext.ApplicationShortcut)
        self.assertEqual(window.act_redo.shortcutContext(), Qt.ShortcutContext.ApplicationShortcut)

        # Suoritetaan Undo act_undo:n kautta (kuten käyttäjä painaisi Ctrl+Z)
        window.act_undo.trigger()
        self.assertEqual(window.doc_model.doc[0].rotation, 0, "Sivun kierron pitää palautua arvoon 0 Undon jälkeen!")
        self.assertFalse(window.act_undo.isEnabled())
        self.assertTrue(window.act_redo.isEnabled())

        # Suoritetaan Redo act_redo:n kautta (kuten käyttäjä painaisi Ctrl+Y)
        window.act_redo.trigger()
        self.assertEqual(window.doc_model.doc[0].rotation, 90, "Sivun kierron pitää palata arvoon 90 Redon jälkeen!")
        self.assertTrue(window.act_undo.isEnabled())

        # Testataan kankaan, sivupalkin ja editorin Undo/Redo -signaalit
        window.canvas.request_undo.emit()
        self.assertEqual(window.doc_model.doc[0].rotation, 0)

        window.editor_widget.redo_requested.emit()
        self.assertEqual(window.doc_model.doc[0].rotation, 90)

        window.thumbnails_bar.undo_requested.emit()
        self.assertEqual(window.doc_model.doc[0].rotation, 0)

        window.close()


if __name__ == "__main__":
    unittest.main()
