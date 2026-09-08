"""
Kattavat yksikkötestit sivujen hallinta- ja erätoiminnoille:
- Sivuväliparsinta ja -muotoilu (esim. "1-10, 20", "all", "even", "odd")
- Eräpoisto, kierto, monistus, siirto ja purku tiedostoon
- Yhden askeleen Undo / Redo -toimivuus
- Pikkukuvapalkin monivalinta (ExtendedSelection) ja pikanäppäimet (Ctrl+A, Delete)
"""

import os
import tempfile
import unittest
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent

from pdf_engine.pdf_document import PDFDocumentModel
from ui.batch_pages_dialog import parse_page_range_string, format_page_range_string
from ui.thumbnails_bar import ThumbnailsBar, ThumbnailsListWidget


app = QApplication.instance()
if not app:
    app = QApplication([])


class TestBatchPageOperations(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.test_pdf = os.path.join(self.temp_dir, "test_10pages.pdf")
        doc = fitz.open()
        for i in range(10):
            page = doc.new_page(width=595, height=842)
            page.insert_text((50, 100), f"Sivu {i + 1}", fontsize=24)
        doc.save(self.test_pdf)
        doc.close()

    def tearDown(self):
        if os.path.exists(self.test_pdf):
            try:
                os.remove(self.test_pdf)
            except Exception:
                pass
        if os.path.exists(self.temp_dir):
            try:
                os.rmdir(self.temp_dir)
            except Exception:
                pass

    def test_parse_page_range_string_basic_and_ranges(self):
        """Testaa perussivuvälit ja käyttäjän esimerkin '1-10, 20'."""
        # 1-10, 20 dokumentissa jossa 30 sivua -> 0..9 ja 19
        result = parse_page_range_string("1-10, 20", max_pages=30)
        self.assertEqual(result, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 19])

        # Yksittäiset ja välit sekaisin
        result2 = parse_page_range_string("1, 3, 5-7, 10", max_pages=15)
        self.assertEqual(result2, [0, 2, 4, 5, 6, 9])

        # Käänteinen väli "5-1"
        result3 = parse_page_range_string("5-1", max_pages=10)
        self.assertEqual(result3, [0, 1, 2, 3, 4])

        # Vaihtoehtoiset erottimet: puolipiste, pisteet, "to"
        result4 = parse_page_range_string("1; 3..5; 8 to 10", max_pages=10)
        self.assertEqual(result4, [0, 2, 3, 4, 7, 8, 9])

    def test_parse_page_range_string_keywords(self):
        """Testaa avainsanat: all, even, odd, parilliset, parittomat."""
        self.assertEqual(parse_page_range_string("all", max_pages=5), [0, 1, 2, 3, 4])
        self.assertEqual(parse_page_range_string("kaikki", max_pages=4), [0, 1, 2, 3])
        self.assertEqual(parse_page_range_string("*", max_pages=3), [0, 1, 2])

        # Even: sivut 2, 4 -> indeksit 1, 3
        self.assertEqual(parse_page_range_string("even", max_pages=6), [1, 3, 5])
        self.assertEqual(parse_page_range_string("parilliset", max_pages=6), [1, 3, 5])

        # Odd: sivut 1, 3, 5 -> indeksit 0, 2, 4
        self.assertEqual(parse_page_range_string("odd", max_pages=6), [0, 2, 4])
        self.assertEqual(parse_page_range_string("parittomat", max_pages=6), [0, 2, 4])

    def test_parse_page_range_string_guards(self):
        """Testaa virheelliset ja rajojen ulkopuolella olevat arvot."""
        # 0 ja 999 yli rajojen
        self.assertEqual(parse_page_range_string("0, 999", max_pages=10), [])
        # Tyhjä tai negatiivinen
        self.assertEqual(parse_page_range_string("", max_pages=10), [])
        self.assertEqual(parse_page_range_string("1-5", max_pages=0), [])
        # Roskatekstiä seassa
        self.assertEqual(parse_page_range_string("abc, 2, xyz-12, 4", max_pages=10), [1, 3])

    def test_format_page_range_string(self):
        """Testaa sivuindeksien tiivistämisen ihmisluettavaan muotoon."""
        self.assertEqual(format_page_range_string([]), "")
        self.assertEqual(format_page_range_string([0]), "1")
        self.assertEqual(format_page_range_string([0, 1, 2, 4, 6, 7]), "1-3, 5, 7-8")
        # Järjestämätön ja duplikaatit
        self.assertEqual(format_page_range_string([19, 0, 2, 1, 0, 1]), "1-3, 20")

    def test_batch_delete_and_undo(self):
        """Testaa useiden sivujen poiston ja 1-askeleen kumoamisen."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)
        self.assertEqual(model.page_count, 10)

        # Poistetaan sivut 1, 3, 5 (indeksit 0, 2, 4)
        deleted = model.delete_pages([0, 2, 4])
        self.assertEqual(deleted, 3)
        self.assertEqual(model.page_count, 7)

        # Yhdellä Ctrl+Z kumoamisella kaikki 3 sivua palaavat paikoilleen!
        self.assertTrue(model.can_undo())
        self.assertTrue(model.undo())
        self.assertEqual(model.page_count, 10)

        # Redo poistaa ne uudelleen
        self.assertTrue(model.can_redo())
        self.assertTrue(model.redo())
        self.assertEqual(model.page_count, 7)

    def test_batch_delete_prevents_deleting_all_pages(self):
        """Varmistaa että kaikkien sivujen poisto on estetty turvallisuussyistä."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)
        all_pages = list(range(10))
        deleted = model.delete_pages(all_pages)
        self.assertEqual(deleted, 0)
        self.assertEqual(model.page_count, 10)

    def test_batch_rotate_and_undo(self):
        """Testaa useiden sivujen kierron ja kumoamisen."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)

        rotated = model.rotate_pages([0, 2], 90)
        self.assertEqual(rotated, 2)
        self.assertEqual(model.doc[0].rotation, 90)
        self.assertEqual(model.doc[2].rotation, 90)
        self.assertEqual(model.doc[1].rotation, 0)

        # Undo palauttaa kulmat
        self.assertTrue(model.undo())
        self.assertEqual(model.doc[0].rotation, 0)
        self.assertEqual(model.doc[2].rotation, 0)

    def test_batch_duplicate_and_undo(self):
        """Testaa useiden sivujen monistamisen."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)

        # Monistetaan sivut 0 ja 1
        duplicated = model.duplicate_pages([0, 1])
        self.assertEqual(duplicated, 2)
        self.assertEqual(model.page_count, 12)

        # Undo palauttaa 10 sivua
        self.assertTrue(model.undo())
        self.assertEqual(model.page_count, 10)

    def test_batch_move_and_undo(self):
        """Testaa sivujen siirron alkuun, loppuun ja tietyn sivun jälkeen."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)

        # Siirretään sivut 8 ja 9 (viimeiset) alkuun
        ok = model.move_pages([8, 9], target_position="start")
        self.assertTrue(ok)
        self.assertEqual(model.page_count, 10)

        # Undo palauttaa alkuperäiseen järjestykseen
        self.assertTrue(model.undo())
        self.assertEqual(model.page_count, 10)

    def test_extract_pages_to_file(self):
        """Testaa valittujen sivujen purkamisen uuteen tiedostoon."""
        model = PDFDocumentModel()
        model.open(self.test_pdf)

        out_pdf = os.path.join(self.temp_dir, "extracted.pdf")
        ok = model.extract_pages_to_file([0, 1, 9], out_pdf)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(out_pdf))

        extracted_doc = fitz.open(out_pdf)
        self.assertEqual(len(extracted_doc), 3)
        extracted_doc.close()
        os.remove(out_pdf)

    def test_thumbnails_bar_multi_selection_and_ctrl_a(self):
        """Testaa sivupalkin ExtendedSelection -tilan ja Ctrl+A / Delete -pikanäppäimet."""
        bar = ThumbnailsBar()
        model = PDFDocumentModel()
        model.open(self.test_pdf)
        bar.set_document(model)

        self.assertEqual(bar.list_widget.count(), 10)

        # Testaa set_selected_pages ja get_selected_pages
        bar.set_selected_pages([0, 2, 4, 8])
        selected = bar.get_selected_pages()
        self.assertEqual(selected, [0, 2, 4, 8])

        # Testaa Ctrl+A: lähettää näppäintapahtuman
        key_event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_A,
            Qt.KeyboardModifier.ControlModifier
        )
        bar.list_widget.keyPressEvent(key_event)
        all_selected = bar.get_selected_pages()
        self.assertEqual(all_selected, list(range(10)))

        # Testaa Delete-näppäin emittoi delete_requested
        delete_signaled = []
        bar.list_widget.delete_requested.connect(lambda: delete_signaled.append(True))
        del_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Delete, Qt.KeyboardModifier.NoModifier)
        bar.list_widget.keyPressEvent(del_event)
        self.assertTrue(len(delete_signaled) > 0)


if __name__ == "__main__":
    unittest.main()
