"""
Yksikkötestit: Kappaletila (Paragraph Mode) ja monirivinen sanarivitys.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver
from pdf_engine.layout_engine import FitStrategy
from pdf_engine.validator import GauntletValidator


class TestParagraphMode(unittest.TestCase):

    def setUp(self):
        self.test_pdf = "/tmp/test_paragraph_doc.pdf"
        self.output_pdf = "/tmp/test_paragraph_out.pdf"

        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        
        # Lisätään taustagrafiikka
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(40, 30, 555, 60))
        shape.finish(color=(0.1, 0.3, 0.7), fill=(0.9, 0.95, 1.0), width=1.0)
        shape.commit()

        # Lisätään otsikko
        page.insert_text(fitz.Point(50, 50), "TESTI-DOKUMENTTI", fontsize=14, fontname="hebo")

        # Lisätään monirivinen kappale
        p_text = (
            "Tämä on ensimmäinen kappale, joka rivittyy automaattisesti laatikon "
            "leveyden mukaisesti usealle peräkkäiselle riville. Teksti jatkuu "
            "luonnollisesti ja päättyy tähän lauseeseen."
        )
        page.insert_textbox(fitz.Rect(50, 100, 500, 200), p_text, fontsize=11, fontname="helv")

        doc.save(self.test_pdf)
        doc.close()

        self.model = PDFDocumentModel()
        self.model.open(self.test_pdf)

    def tearDown(self):
        if self.model.is_open:
            self.model.close()
        for p in (self.test_pdf, self.output_pdf):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_get_blocks_for_page(self):
        blocks = self.model.get_blocks_for_page(0)
        self.assertGreaterEqual(len(blocks), 2, "Sivulta pitäisi löytyä vähintään otsikko ja kappale")
        
        # Etsitään kappale
        paragraph_block = None
        for b in blocks:
            if "ensimmäinen kappale" in b.get("text", ""):
                paragraph_block = b
                break

        self.assertIsNotNone(paragraph_block, "Monirivistä kappaletta ei löydetty")
        self.assertIn("Tämä on ensimmäinen kappale", paragraph_block["text"])
        self.assertIn("päättyy tähän lauseeseen.", paragraph_block["text"])
        self.assertGreaterEqual(paragraph_block["line_count"], 2)
        self.assertEqual(paragraph_block["font"], "Helvetica")
        self.assertEqual(paragraph_block["size"], 11.0)

    def test_replace_block_inplace_natural_flow(self):
        blocks = self.model.get_blocks_for_page(0)
        paragraph_block = next(b for b in blocks if "ensimmäinen kappale" in b.get("text", ""))

        new_text = (
            "Tämä on täysin uusi korvattu kappale, jossa testataan ääkkösiä kuten "
            "ä, ö ja å sekä virheetöntä sanarivitystä PDF-laatikon sisällä."
        )

        font_match = FontconfigResolver.inspect_and_resolve(
            self.model.doc,
            paragraph_block,
            new_text
        )

        op = self.model.replace_block_inplace(
            page_idx=0,
            block=paragraph_block,
            new_text=new_text,
            font_match=font_match
        )

        self.assertEqual(op.fit_strategy, "paragraph_flow")
        self.assertEqual(op.new_text, new_text)

        # Tarkistetaan että uusi teksti löytyy sivulta
        updated_blocks = self.model.get_blocks_for_page(0)
        updated_texts = [b.get("text", "") for b in updated_blocks]
        combined = " ".join(updated_texts)
        self.assertIn("täysin uusi korvattu kappale", combined)
        self.assertIn("ääkkösiä", combined)

    def test_replace_block_undo_redo(self):
        blocks = self.model.get_blocks_for_page(0)
        paragraph_block = next(b for b in blocks if "ensimmäinen kappale" in b.get("text", ""))

        new_text = "Muokattu kappaleen sisältö testaukseen."
        font_match = FontconfigResolver.inspect_and_resolve(
            self.model.doc,
            paragraph_block,
            new_text
        )

        self.model.replace_block_inplace(0, paragraph_block, new_text, font_match)
        self.assertTrue(self.model.can_undo())

        # Kumotaan
        self.assertTrue(self.model.undo())
        undone_blocks = self.model.get_blocks_for_page(0)
        combined_undone = " ".join(b.get("text", "") for b in undone_blocks)
        self.assertIn("ensimmäinen kappale", combined_undone)

        # Tehdään uudelleen
        self.assertTrue(self.model.redo())
        redone_blocks = self.model.get_blocks_for_page(0)
        combined_redone = " ".join(b.get("text", "") for b in redone_blocks)
        self.assertIn("Muokattu kappaleen sisältö", combined_redone)

    def test_gauntlet_audit_passes_after_paragraph_edit(self):
        blocks = self.model.get_blocks_for_page(0)
        paragraph_block = next(b for b in blocks if "ensimmäinen kappale" in b.get("text", ""))

        new_text = "Laadukas muokattu kappale Gauntlet-validaattorille."
        font_match = FontconfigResolver.inspect_and_resolve(
            self.model.doc,
            paragraph_block,
            new_text
        )

        self.model.replace_block_inplace(0, paragraph_block, new_text, font_match)
        self.model.save(self.output_pdf)

        report = GauntletValidator.audit_document(
            self.output_pdf,
            operations=self.model.operations_history
        )
        self.assertTrue(report.is_valid, f"Gauntlet-auditointi epäonnistui: {report.summary_markdown()}")

    def test_single_character_edit_preserves_exact_metrics(self):
        """
        Varmistaa, että yhden merkin korjaus säilyttää KAIKKI metriikat:
        - Täsmälleen identtiset perusviivat (baseline) jokaisella rivillä (poikkeama 0.0000 pt)
        - Täsmälleen identtisen rivivälikorkeuden (leading)
        - Täsmälleen saman kirjasimen, koon, värin ja rivimäärän
        """
        blocks = self.model.get_blocks_for_page(0)
        paragraph_block = next(b for b in blocks if "ensimmäinen kappale" in b.get("text", ""))

        orig_origins = paragraph_block["line_origins"]
        orig_leading = paragraph_block["leading"]
        orig_font = paragraph_block["font"]
        orig_size = paragraph_block["size"]
        orig_color = paragraph_block["color"]
        orig_line_count = paragraph_block["line_count"]

        self.assertGreater(orig_line_count, 1, "Kappaleella täytyy olla useampi rivi")
        self.assertEqual(len(orig_origins), orig_line_count)
        self.assertIn("line_spans", paragraph_block)
        self.assertIn("line_bboxes", paragraph_block)

        # Korvataan 1 merkki: 'ensimmäinen' -> 'ensimmainen'
        new_text = paragraph_block["text"].replace("ensimmäinen", "ensimmainen")

        font_match = FontconfigResolver.inspect_and_resolve(
            self.model.doc,
            paragraph_block,
            new_text
        )

        op = self.model.replace_block_inplace(0, paragraph_block, new_text, font_match)

        # Tarkistetaan muokattu kappale
        updated_blocks = self.model.get_blocks_for_page(0)
        new_block = next(b for b in updated_blocks if "ensimmainen kappale" in b.get("text", ""))

        self.assertEqual(new_block["line_count"], orig_line_count, "Rivimäärä ei saa muuttua 1-merkin korjauksessa")
        self.assertEqual(new_block["font"], orig_font, "Kirjasin ei saa muuttua")
        self.assertEqual(new_block["size"], orig_size, "Fonttikoko ei saa muuttua")
        self.assertEqual(new_block["color"], orig_color, "Väri ei saa muuttua")

        # Tarkistetaan jokaisen rivin perusviiva (baseline)
        new_origins = new_block["line_origins"]
        for i in range(orig_line_count):
            dx = abs(new_origins[i][0] - orig_origins[i][0])
            dy = abs(new_origins[i][1] - orig_origins[i][1])
            self.assertLess(dx, 0.001, f"Rivin {i} X-koordinaatti poikkesi {dx:.4f} pt")
            self.assertLess(dy, 0.001, f"Rivin {i} perusviiva (Y) poikkesi {dy:.4f} pt")

        # Tarkistetaan rivivälikorkeus (leading)
        leading_diff = abs(new_block["leading"] - orig_leading)
        self.assertLess(leading_diff, 0.001, f"Rivivälikorkeus (leading) poikkesi {leading_diff:.4f} pt")

    def test_multiple_font_injection_no_collision(self):
        """Varmistaa että kaksi eri kirjasinta samalla sivulla eivät sotkeennu toisiinsa."""
        blocks = self.model.get_blocks_for_page(0)
        b1 = blocks[0]
        b2 = blocks[1]

        # Korvataan ensimmäinen lohko sans-serifillä
        m1 = FontconfigResolver.inspect_and_resolve(self.model.doc, b1, "Otsikko Uusi")
        self.model.replace_block_inplace(0, b1, "Otsikko Uusi", m1)

        # Korvataan toinen lohko serifillä
        m2 = FontconfigResolver.inspect_and_resolve(self.model.doc, b2, "Kappale Uusi")
        self.model.replace_block_inplace(0, b2, "Kappale Uusi", m2)

        page_fonts = self.model.doc[0].get_fonts()
        font_names = [f[4] for f in page_fonts]
        # Varmistetaan että sivun fonttilistassa ei käytetä yhtä ainoaa ylikirjoittuvaa nimeä
        self.assertEqual(len(set(font_names)), len(font_names))


if __name__ == "__main__":
    unittest.main()
