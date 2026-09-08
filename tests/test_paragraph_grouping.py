"""
Yksikkötestit: Älykäs kappaleiden ryhmittely (Intelligent Paragraph Grouping),
pehmeiden tavuviivojen poisto (Soft-Hyphen dehyphenation) ja lohkon leveyden säätö.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver


class TestParagraphGrouping(unittest.TestCase):

    def setUp(self):
        self.test_pdf = "/tmp/test_grouping_doc.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)

        # Simuloidaan ammattimaista ladontaa, jossa jokainen rivi on oma tekstiobjektinsa:
        # Otsikko
        page.insert_text(fitz.Point(50, 60), "The Other Game Industry Crash", fontsize=14, fontname="hebo")

        # 3 riviä kappaletta samalla rivivälillä (dy = 16 pt, font=11 pt)
        page.insert_text(fitz.Point(50, 100), "Tämä on ammatillisesti ladotun kirjan ensimmäinen rivi, joka päättyy ta-", fontsize=11, fontname="helv")
        page.insert_text(fitz.Point(50, 116), "vutukseen ja jatkuu toisella rivillä täysin saumattomasti ilman ylimääräisiä", fontsize=11, fontname="helv")
        page.insert_text(fitz.Point(50, 132), "katkoksia tekstivirrassa.", fontsize=11, fontname="helv")

        # Toinen kappale (erillinen, koska edellinen loppui lyhyeen riviin pisteellä)
        page.insert_text(fitz.Point(50, 160), "Tämä on toinen kappale, joka muodostaa oman itsenäisen lohkonsa.", fontsize=11, fontname="helv")

        doc.save(self.test_pdf)
        doc.close()

        self.model = PDFDocumentModel()
        self.model.open(self.test_pdf)

    def tearDown(self):
        if self.model.is_open:
            self.model.close()
        if os.path.exists(self.test_pdf):
            try:
                os.remove(self.test_pdf)
            except Exception:
                pass

    def test_fragmented_lines_grouped_into_paragraphs(self):
        """Varmistaa että erilliset yhden rivin tekstielementit ryhmittyvät oikeiksi kappaleiksi."""
        blocks = self.model.get_blocks_for_page(0)
        self.assertEqual(len(blocks), 3, "Sivulta pitäisi löytyä 3 lohkoa: otsikko, kappale 1 (3 riviä) ja kappale 2 (1 rivi)")

        # Otsikko
        heading = blocks[0]
        self.assertEqual(heading["line_count"], 1)
        self.assertEqual(heading["text"], "The Other Game Industry Crash")

        # Kappale 1
        para1 = blocks[1]
        self.assertEqual(para1["line_count"], 3)
        self.assertIn("päättyy tavutukseen", para1["text"])
        self.assertIn("katkoksia tekstivirrassa.", para1["text"])
        self.assertEqual(len(para1["line_origins"]), 3)
        self.assertAlmostEqual(para1["leading"], 16.0, delta=0.5)

        # Kappale 2
        para2 = blocks[2]
        self.assertEqual(para2["line_count"], 1)
        self.assertIn("toinen kappale", para2["text"])

    def test_heading_expansion_without_wrap(self):
        """Varmistaa että otsikkoon merkin lisääminen ei aiheuta turhaa rivittymistä."""
        blocks = self.model.get_blocks_for_page(0)
        heading = blocks[0]

        font_match = FontconfigResolver.inspect_and_resolve(self.model.doc, heading, "The Other Game Industry Crashh")
        self.model.replace_block_inplace(
            page_idx=0,
            block=heading,
            new_text="The Other Game Industry Crashh",
            font_match=font_match
        )

        re_blocks = self.model.get_blocks_for_page(0)
        re_heading = re_blocks[0]
        self.assertEqual(re_heading["line_count"], 1, "Otsikon pitää pysyä yhdellä rivillä!")
        self.assertEqual(re_heading["text"], "The Other Game Industry Crashh")

    def test_custom_max_width_flow(self):
        """Varmistaa että käyttäjän asettama custom_max_width ohjaa sanarivityksen leveyttä."""
        blocks = self.model.get_blocks_for_page(0)
        para1 = blocks[1]

        # Laajennetaan lohkon leveyttä
        font_match = FontconfigResolver.inspect_and_resolve(self.model.doc, para1, para1["text"])
        self.model.replace_block_inplace(
            page_idx=0,
            block=para1,
            new_text=para1["text"],
            font_match=font_match,
            custom_max_width=600.0
        )

        re_blocks = self.model.get_blocks_for_page(0)
        self.assertLessEqual(re_blocks[1]["line_count"], 3)

    def test_real_book_paragraphs_if_present(self):
        """Testaa oikeaa kirjaa (/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf) jos tiedosto on saatavilla."""
        book_path = "/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf"
        if not os.path.exists(book_path):
            self.skipTest("Kirjatiedostoa ei löydy polusta " + book_path)

        book_model = PDFDocumentModel()
        book_model.open(book_path)
        self.assertEqual(book_model.page_count, 267)

        # Sivu 66 (indeksi 65): 37 raakalohkoa -> täsmälleen 5 lohkoa (header, para1, heading, para2, footer)
        blocks_66 = book_model.get_blocks_for_page(65)
        self.assertEqual(len(blocks_66), 5)
        self.assertEqual(blocks_66[2]["text"], "The Other Game Industry Crash")
        self.assertEqual(blocks_66[2]["line_count"], 1)
        self.assertEqual(blocks_66[3]["line_count"], 15)

        # Varmistetaan että tekstiin ei jää soft-hypheneitä (\xad)
        self.assertNotIn("\xad", blocks_66[3]["text"])
        self.assertIn("Wilson 2005", blocks_66[3]["text"])
        self.assertIn("videogame production", blocks_66[3]["text"])

        book_model.close()

    def test_real_book_page_62_single_word_edit_preserves_cff_and_italics(self):
        """
        Varmistaa kirjan sivulta 62 (kuvateksti):
        1. CFF Type1 -upotettu fontti (StoneSerifStd-Medium) tunnistetaan ja kelpuutetaan (can_use_embedded=True).
        2. 'Bakker' -> 'Bakkeri' -muokkaus säilyttää rivin 0 kursiivin (Need 4e+9 Speed) ja symbolin (+).
        3. Rivi 1 korvataan täsmälleen alkuperäisellä Stone Serif -fontilla ilman korviketta (ei Crimson Pro).
        4. Kaikki 3 riviä ryhmittyvät edelleen yhtenäiseksi kappaleeksi.
        """
        book_path = "/mnt/data/Downloads/Videogame_Industry_Does_Not_Exist.pdf"
        if not os.path.exists(book_path):
            self.skipTest("Kirjatiedostoa ei löydy polusta " + book_path)

        book_model = PDFDocumentModel()
        book_model.open(book_path)

        blocks = book_model.get_blocks_for_page(62)
        party_block = next((b for b in blocks if "Partygoers" in b.get("text", "")), None)
        self.assertIsNotNone(party_block)
        self.assertEqual(party_block["line_count"], 3)

        orig_lines = party_block["original_lines"]
        new_lines = [
            orig_lines[0],
            orig_lines[1].replace("Bakker", "Bakkeri"),
            orig_lines[2]
        ]
        new_text = "\n".join(new_lines)

        font_match = FontconfigResolver.inspect_and_resolve(book_model.doc, party_block, new_text)
        self.assertTrue(font_match.can_use_embedded, "Upotetun CFF-kirjasimen täytyy olla käytettävissä")
        self.assertEqual(len(font_match.embedded_missing_glyphs), 0)

        book_model.replace_block_inplace(62, party_block, new_text, font_match)

        page = book_model.doc[62]
        td = page.get_text("dict")
        all_spans = [s for b in td.get("blocks", []) for l in b.get("lines", []) for s in l.get("spans", [])]

        italic_spans = [s for s in all_spans if "Need 4e" in s.get("text", "")]
        self.assertTrue(len(italic_spans) > 0, "Rivin 0 kursiivi (Need 4e) täytyy säilyä koskemattomana")
        self.assertIn("Ital", italic_spans[0]["font"])

        bakkeri_spans = [s for s in all_spans if "Bakkeri" in s.get("text", "")]
        self.assertTrue(len(bakkeri_spans) > 0, "Rivin 1 teksti 'Bakkeri' täytyy löytyä")
        self.assertEqual(bakkeri_spans[0]["font"], "StoneSerifStd-Medium")
        self.assertAlmostEqual(bakkeri_spans[0]["size"], 8.0, delta=0.1)

        author_spans = [s for s in all_spans if "Photo by author" in s.get("text", "")]
        self.assertTrue(len(author_spans) > 0, "Rivin 2 teksti 'Photo by author' täytyy säilyä")

        updated_blocks = book_model.get_blocks_for_page(62)
        up_party = next((b for b in updated_blocks if "Bakkeri" in b.get("text", "")), None)
        self.assertIsNotNone(up_party)
        self.assertEqual(up_party["line_count"], 3, "Kappaleen täytyy säilyä 3-rivisenä yhtenäisenä lohkona")

        book_model.close()


if __name__ == "__main__":
    unittest.main()
