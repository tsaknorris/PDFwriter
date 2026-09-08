"""
Dokumentin kirjasintenhallinnan ja suositusten yksikkötestit.
"""

import os
import tempfile
import unittest
import fitz

from PyQt6.QtWidgets import QApplication

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver, FontDownloader, LOCAL_FONTS_DIR
from ui.font_manager_dialog import FontManagerDialog

# Luodaan QApplication pääsilmukka testejä varten
app = QApplication.instance() or QApplication([])


class TestFontManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_font_recommendations(self):
        # Minion Pro suositus
        rec_desc, rec_id = FontDownloader.get_recommendation("MinionPro-Regular")
        self.assertIsNotNone(rec_id)
        self.assertEqual(rec_id, "crimsonpro")
        self.assertIn("Crimson Pro", rec_desc)

        # Mercury Text suositus
        rec_desc, rec_id = FontDownloader.get_recommendation("MercuryTextG1-Roman")
        self.assertEqual(rec_id, "merriweather")

        # DIN suositus
        rec_desc, rec_id = FontDownloader.get_recommendation("DINPro-Bold")
        self.assertEqual(rec_id, "barlow")

        # Roboto suora katalogi
        rec_desc, rec_id = FontDownloader.get_recommendation("Roboto")
        self.assertEqual(rec_id, "roboto")

        # Tuntematon fontti
        rec_desc, rec_id = FontDownloader.get_recommendation("RandomUnknownXYZFont123")
        self.assertIsNone(rec_id)

    def test_font_import(self):
        # Luodaan valefonttitiedosto .ttf
        dummy_ttf = os.path.join(self.temp_dir.name, "TestFont-Regular.ttf")
        with open(dummy_ttf, "wb") as f:
            f.write(b"\x00\x01\x00\x00" + b"\x00" * 200)

        # Tuonti omaan tilapäishakemistoon
        dest_dir = os.path.join(self.temp_dir.name, "imported_fonts")
        success, msg, out_path = FontDownloader.import_font_file(dummy_ttf, dest_dir=dest_dir)
        self.assertTrue(success)
        self.assertIsNotNone(out_path)
        self.assertTrue(os.path.isfile(out_path))

        # Virheellinen tiedostomuoto (.exe)
        dummy_exe = os.path.join(self.temp_dir.name, "malicious.exe")
        with open(dummy_exe, "wb") as f:
            f.write(b"not a font")
        success, msg, out_path = FontDownloader.import_font_file(dummy_exe, dest_dir=dest_dir)
        self.assertFalse(success)
        self.assertIn("Vain .ttf ja .otf", msg)

    def test_document_fonts_summary(self):
        # Luodaan PDF fitzillä ja lisätään siihen standardi fontti
        test_pdf = os.path.join(self.temp_dir.name, "font_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 100), "Hello World", fontname="helv", fontsize=12)
        doc.save(test_pdf)
        doc.close()

        # Avataan PDFDocumentModelilla
        model = PDFDocumentModel()
        model.open(test_pdf)
        summary = model.get_document_fonts_summary()
        self.assertTrue(len(summary) >= 1)
        font_info = summary[0]
        self.assertIn("Helvetica", font_info["clean_family"])
        self.assertTrue(font_info["is_installed"])
        self.assertEqual(font_info["pages"], [1])
        model.close()

    def test_font_manager_dialog_ui(self):
        # Testataan että dialogi alustuu ja taulukko täyttyy ilman poikkeuksia
        test_pdf = os.path.join(self.temp_dir.name, "dialog_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 100), "Minion Pro simulation", fontname="tiro", fontsize=14)
        doc.save(test_pdf)
        doc.close()

        model = PDFDocumentModel()
        model.open(test_pdf)
        dlg = FontManagerDialog(model)
        self.assertTrue(dlg.table.rowCount() >= 1)
        # Valitaan ensimmäinen rivi
        dlg.table.selectRow(0)
        selected = dlg._get_selected_font()
        self.assertIsNotNone(selected)
        model.close()
        dlg.close()

    def test_replace_block_with_unknown_font_never_crashes(self):
        # Varmistetaan että vaikka fontti olisi tuntematon tai subset-nimi,
        # korvaus ei KOSKAAN kaadu 'need font file or buffer' -virheeseen.
        test_pdf = os.path.join(self.temp_dir.name, "crash_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        page.insert_text((100, 100), "Alkuperäinen kappale testiin.", fontname="helv", fontsize=12)
        doc.save(test_pdf)
        doc.close()

        model = PDFDocumentModel()
        model.open(test_pdf)
        blocks = model.get_blocks_for_page(0)
        self.assertTrue(len(blocks) >= 1)
        block = blocks[0]

        # Simulaatio: fontin nimi on eksoottinen subset
        block["font"] = "WAVDPC+MinionPro-Regular"
        match = FontconfigResolver.inspect_and_resolve(model.doc, block, "Uusi teksti äö")

        # Suoritetaan korvaus
        op = model.replace_block_inplace(
            page_idx=0,
            block=block,
            new_text="Uusi muokattu teksti ääkkösillä ilman virheitä!",
            font_match=match
        )
        self.assertIsNotNone(op)
        # Varmistetaan että sivu renderöityy virheettömästi
        img, w, h = model.render_page(0)
        self.assertFalse(img.isNull())
        model.close()

    def test_subset_font_summary_and_recommendations(self):
        # Luodaan PDF fitzillä, jossa upotettu fonttitiedosto
        test_pdf = os.path.join(self.temp_dir.name, "subset_test.pdf")
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        # Käytetään tiit (Times-Italic)
        page.insert_text((100, 100), "Kappale tekstiä", fontname="tiit", fontsize=11)
        doc.save(test_pdf)
        doc.close()

        model = PDFDocumentModel()
        model.open(test_pdf)
        summary = model.get_document_fonts_summary()
        self.assertTrue(len(summary) >= 1)
        # Tarkistetaan että Times tunnistetaan
        times_fonts = [f for f in summary if "times" in f["clean_family"].lower() or "tiit" in f["name"].lower()]
        self.assertTrue(len(times_fonts) >= 1)
        tf = times_fonts[0]
        self.assertTrue(tf["is_installed"])
        model.close()

    def test_missing_font_banner(self):
        from ui.main_window import MainWindow
        win = MainWindow()
        test_pdf = os.path.join(self.temp_dir.name, "banner_test.pdf")
        doc = fitz.open()
        doc.new_page(width=595, height=842)
        doc.save(test_pdf)
        doc.close()

        win.open_file(test_pdf)
        # Mockataan tilanne jossa puuttuu kirjasin
        win.doc_model.get_document_fonts_summary = lambda: [
            {"name": "WAVDPC+MinionPro-Regular", "clean_family": "MinionPro", "ext": "cff", "type": "Type1",
             "is_subset": True, "is_bold": False, "is_italic": False, "is_installed": False,
             "status_desc": "Ei asennettu", "font_path": None, "recommendation": "Crimson Pro", "rec_id": "crimsonpro", "pages": [1]}
        ]
        win._check_document_fonts()
        self.assertFalse(win.font_banner.isHidden())
        self.assertIn("MinionPro", win.banner_label.text())
        win.close_file()
        self.assertTrue(win.font_banner.isHidden())
        win.close()


if __name__ == "__main__":
    unittest.main()
