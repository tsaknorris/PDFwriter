"""
Päästä-päähän PDF-kierrostestaus (End-to-End PDF Roundtrip & Gauntlet Audit).
Testaa vektoriredaktion taustagrafiikan säilytyksen, perusviivan (< 0.1 pt),
XRef-virheettömyyden, Undo/Redo -pinon ja Gauntlet-kriitikkoraportin.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver
from pdf_engine.layout_engine import FitStrategy
from pdf_engine.validator import GauntletValidator


class TestPDFRoundtrip(unittest.TestCase):

    def setUp(self):
        self.sample_pdf_path = "/tmp/test_gauntlet_sample.pdf"
        self.output_pdf_path = "/tmp/test_gauntlet_output.pdf"

        # Luodaan ohjelmallisesti rikas testidokumentti
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)  # A4

        # 1. Piirretään taustavektoreita (suorakulmioita ja viivoja)
        shape = page.new_shape()
        shape.draw_rect(fitz.Rect(50, 50, 545, 120))
        shape.finish(color=(0.2, 0.4, 0.8), fill=(0.9, 0.95, 1.0), width=2.0)
        shape.commit()

        # 2. Lisätään tekstiä
        page.insert_text(
            fitz.Point(72, 95),
            "CONFIDENTIAL ARCHITECTURE REPORT",
            fontsize=16,
            fontname="helv",
            color=(0.1, 0.2, 0.6)
        )
        page.insert_text(
            fitz.Point(72, 160),
            "Status: Unverified Prototype",
            fontsize=13,
            fontname="helv",
            color=(0.2, 0.2, 0.2)
        )
        doc.save(self.sample_pdf_path)
        doc.close()

    def tearDown(self):
        for p in (self.sample_pdf_path, self.output_pdf_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def test_inplace_replacement_and_gauntlet_audit(self):
        # 1. Avataan dokumenttimalli
        model = PDFDocumentModel()
        model.open(self.sample_pdf_path)
        self.assertTrue(model.is_open)
        self.assertEqual(model.page_count, 1)

        # 2. Haetaan sivun tekstialkiot
        spans = model.get_spans_for_page(0)
        target_span = None
        for s in spans:
            if "Unverified Prototype" in s.get("text", ""):
                target_span = s
                break

        self.assertIsNotNone(target_span, "Kohdetekstiä ei löytynyt sivulta")
        orig_origin_y = target_span["origin"][1]

        # 3. Resoluutio ja in-place -korvaus
        new_text = "Status: Production Approved (Acrobat-Grade)"
        font_match = FontconfigResolver.inspect_and_resolve(
            model.doc,
            target_span,
            new_text
        )

        op = model.replace_text_inplace(
            page_idx=0,
            span=target_span,
            new_text=new_text,
            font_match=font_match,
            strategy=FitStrategy.NATURAL
        )

        # 4. Tarkistetaan, että perusviiva pysyy identtisenä (< 0.1 pt)
        self.assertAlmostEqual(op.origin[1], orig_origin_y, delta=0.05)

        # 5. Varmistetaan, että taustavektorigrafiikka säilyi
        drawings = model.doc[0].get_drawings()
        self.assertGreater(len(drawings), 0, "Taustavektorigrafiikka katosi redaktiossa!")

        # 6. Tallennetaan puhtaalla XRef-rakenteella
        model.save(self.output_pdf_path)
        self.assertTrue(os.path.isfile(self.output_pdf_path))

        # 7. Ajetaan GauntletValidator
        report = GauntletValidator.audit_document(
            self.output_pdf_path,
            operations=model.operations_history
        )
        print("\n" + report.summary_markdown() + "\n")
        self.assertTrue(report.is_valid, "Dokumentti ei läpäissyt Gauntlet Loop -tarkastuksia!")

        # 8. Testataan Undo ja Redo
        self.assertTrue(model.can_undo())
        model.undo()
        page_text_after_undo = model.doc[0].get_text()
        self.assertIn("Unverified Prototype", page_text_after_undo)
        self.assertNotIn("Production Approved", page_text_after_undo)

        self.assertTrue(model.can_redo())
        model.redo()
        page_text_after_redo = model.doc[0].get_text()
        self.assertIn("Production Approved", page_text_after_redo)
        self.assertNotIn("Unverified Prototype", page_text_after_redo)

        model.close()


if __name__ == "__main__":
    unittest.main()
