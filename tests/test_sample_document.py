"""
Yksikkötesti: sample_document.pdf:n kappalemuokkaus ja Gauntlet-validointi.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

from pdf_engine.pdf_document import PDFDocumentModel
from pdf_engine.font_resolver import FontconfigResolver
from pdf_engine.validator import GauntletValidator


class TestSampleDocumentVerification(unittest.TestCase):

    def setUp(self):
        self.sample_pdf = os.path.join(os.path.dirname(__file__), "..", "sample_document.pdf")
        self.output_pdf = "/tmp/test_sample_document_out.pdf"

    def tearDown(self):
        if os.path.exists(self.output_pdf):
            try:
                os.remove(self.output_pdf)
            except Exception:
                pass

    def test_sample_document_verification_workflow(self):
        self.assertTrue(os.path.exists(self.sample_pdf), "sample_document.pdf puuttuu")
        
        doc_model = PDFDocumentModel()
        doc_model.open(self.sample_pdf)
        self.assertEqual(doc_model.page_count, 2)

        blocks = doc_model.get_blocks_for_page(0)
        paragraph_block = next((b for b in blocks if "kappaletilaa" in b.get("text", "")), None)
        self.assertIsNotNone(paragraph_block, "sample_document.pdf:stä ei löytynyt monirivistä kappaletta")

        new_text = (
            "Tämä on automaattisessa integraatiotestissä korvattu kappale. "
            "Uusi teksti rivittyy luonnollisesti koko kappaleen leveydelle "
            "säilyttäen tarkan fontin ja leikkauksen suomen kielen ääkkösinä."
        )

        font_match = FontconfigResolver.inspect_and_resolve(
            doc_model.doc,
            paragraph_block,
            new_text
        )

        op = doc_model.replace_block_inplace(
            page_idx=0,
            block=paragraph_block,
            new_text=new_text,
            font_match=font_match
        )

        self.assertIsNotNone(op)
        doc_model.save(self.output_pdf)
        doc_model.close()

        report = GauntletValidator.audit_document(
            self.output_pdf,
            operations=[op]
        )
        self.assertTrue(report.is_valid, f"Gauntlet-auditointi hylätty: {report.summary_markdown()}")


if __name__ == "__main__":
    unittest.main()
