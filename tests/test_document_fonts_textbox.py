"""
Testit dokumentin fonttien käytölle tekstilaatikoissa, uusilla sivuilla ja fontinhallinnassa.
"""

import os
import shutil
import unittest
from PyQt6.QtWidgets import QApplication
import fitz

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver, LOCAL_FONTS_DIR
from ui.shape_properties_dock import ShapePropertiesDock


class TestDocumentFontsTextbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.doc_model = PDFDocumentModel()
        self.temp_dir = "/tmp/pdfwriter_test_fonts"
        os.makedirs(self.temp_dir, exist_ok=True)

    def tearDown(self):
        if self.doc_model.is_open:
            self.doc_model.close()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_get_document_font_families_sample_pdf(self):
        """Testaa että sample_document.pdf palauttaa oikeat kirjasinperheet."""
        self.doc_model.open("sample_document.pdf")
        families = self.doc_model.get_document_font_families()
        self.assertIn("Helvetica", families)

    def test_document_font_extraction_and_resolution(self):
        """Testaa upotetun fontin purkamista ja sen tunnistamista lokaaliksi fontiksi."""
        # Luodaan PDF, jossa on CrimsonPro upotettuna
        test_pdf = os.path.join(self.temp_dir, "embedded_test.pdf")
        doc = fitz.open()
        p = doc.new_page()
        font_path = os.path.join(LOCAL_FONTS_DIR, "CrimsonPro.ttf")
        self.assertTrue(os.path.isfile(font_path), f"Fonttitiedostoa ei löydy: {font_path}")
        
        p.insert_textbox(
            fitz.Rect(50, 50, 400, 200),
            "Testiteksti dokumenttifontilla",
            fontfile=font_path,
            fontname="CrimsonPro",
            fontsize=16
        )
        doc.save(test_pdf)
        doc.close()

        # Avataan ja puretaan fontit
        self.doc_model.open(test_pdf)
        extracted = self.doc_model.extract_document_fonts()
        families = self.doc_model.get_document_font_families()
        self.assertTrue(any("Crimson" in f for f in families))

        # Varmistetaan että resolve_local_font löytää fonttitiedoston
        resolved_path, resolved_fam = FontconfigResolver.resolve_local_font("Crimson Pro")
        self.assertIsNotNone(resolved_path)
        self.assertTrue(os.path.isfile(resolved_path))

    def test_shape_dock_font_dropdown_structure(self):
        """Testaa että ShapePropertiesDock ryhmittelee dokumentin fontit ja standardifontit oikein."""
        dock = ShapePropertiesDock()
        doc_fonts = ["Stone Serif Std", "Stone Sans", "MyCustomDocFont"]
        dock.update_available_fonts(doc_fonts)

        combo = dock.combo_font_family
        texts = [combo.itemText(i) for i in range(combo.count())]

        # Varmistetaan otsikot ja järjestys
        self.assertIn("── Dokumentin fontit ──", texts)
        self.assertIn("── Standardikirjasimet ──", texts)
        self.assertIn("Stone Serif Std", texts)
        self.assertIn("Stone Sans", texts)
        self.assertIn("Helvetica", texts)

        # Dokumentin fonttien tulee olla ennen standardikirjasimia
        idx_doc_header = texts.index("── Dokumentin fontit ──")
        idx_doc_font = texts.index("Stone Serif Std")
        idx_std_header = texts.index("── Standardikirjasimet ──")
        idx_std_font = texts.index("Helvetica")

        self.assertLess(idx_doc_header, idx_doc_font)
        self.assertLess(idx_doc_font, idx_std_header)
        self.assertLess(idx_std_header, idx_std_font)

        # Varmistetaan ettei otsikkoa voi asettaa fontiksi
        dock._on_font_family_changed("── Dokumentin fontit ──")
        self.assertNotEqual(dock.font_family, "── Dokumentin fontit ──")

    def test_textbox_on_new_blank_page_with_doc_font(self):
        """Testaa uuden tyhjän sivun luomista ja tekstilaatikon piirtämistä dokumentin fontilla."""
        self.doc_model.open("sample_document.pdf")
        orig_pages = self.doc_model.page_count

        # Lisätään uusi tyhjä sivu
        new_page_idx = orig_pages
        self.doc_model.insert_blank_page(new_page_idx)
        self.assertEqual(self.doc_model.page_count, orig_pages + 1)

        # Luodaan tekstilaatikko uudelle sivulle Stone Serif -fontilla (joka resolvoituu Crimson Pro -fonttitiedostoon)
        shape_id = self.doc_model.draw_shape(
            page_idx=new_page_idx,
            shape_type="textbox",
            geometry=[100.0, 100.0, 400.0, 250.0],
            fill_color=(1.0, 1.0, 1.0),
            stroke_color=(0.0, 0.0, 0.0),
            fill_opacity=1.0,
            stroke_opacity=1.0,
            stroke_width=1.0,
            radius=0.0,
            overlay=True,
            rotation=0.0,
            text="Tämä on uudelle sivulle luotu tekstilaatikko dokumentin fontilla!",
            font_family="Stone Serif Std",
            font_size=18.0,
            font_bold=False,
            font_italic=False,
            text_color=(0.1, 0.1, 0.1),
            text_align="center",
            vertical_align="middle",
            text_padding=8.0
        )
        self.assertIsNotNone(shape_id)

        # Renderöidään sivu kuvaksi varmistaaksemme että PyMuPDF piirtää sen onnistuneesti
        qimg, w, h = self.doc_model.render_page(new_page_idx, scale=1.0)
        self.assertIsNotNone(qimg)
        self.assertFalse(qimg.isNull())
        self.assertGreater(w, 100)

        # Varmistetaan että PDF voidaan tallentaa eheänä
        out_pdf = os.path.join(self.temp_dir, "output_blank_page_docfont.pdf")
        self.doc_model.save(out_pdf)
        self.assertTrue(os.path.isfile(out_pdf))
        self.assertGreater(os.path.getsize(out_pdf), 1000)

        # Tarkistetaan että tallennetussa PDF:ssä on Crimson Pro / Stone Serif
        doc_check = fitz.open(out_pdf)
        self.assertEqual(len(doc_check), orig_pages + 1)
        new_page_fonts = doc_check[new_page_idx].get_fonts(full=True)
        self.assertGreater(len(new_page_fonts), 0)
        font_names = [f[3] for f in new_page_fonts]
        self.assertTrue(any("Crimson" in fn or "Stone" in fn for fn in font_names), f"Odotettiin Crimson/Stone, löytyi: {font_names}")
        doc_check.close()

    def test_font_manager_button_signal(self):
        """Testaa että 🔤-pikapainike lähettää font_manager_requested -signaalin."""
        dock = ShapePropertiesDock()
        signal_received = []
        dock.font_manager_requested.connect(lambda: signal_received.append(True))
        dock.btn_manage_fonts.click()
        self.assertEqual(len(signal_received), 1)


if __name__ == "__main__":
    unittest.main()
