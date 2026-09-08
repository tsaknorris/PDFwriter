"""
Yksikkö- ja integraatiotestit sivupaneelien palautustoiminnolle (F4, Näytä-valikko, työkalupalkki),
Acrobat Dark Pro -värikontrastille sekä tekstinmuokkauksen ja muotojen synkronoinnille.
"""

import os
import unittest

os.environ["QT_NO_NETWORK"] = "1"

import fitz
from PyQt6.QtWidgets import QApplication

from pdf_engine.pdf_document import PDFDocumentModel, FitStrategy
from pdf_engine.font_resolver import FontconfigResolver
from ui.main_window import MainWindow
from ui.layers_panel import LayersPanel

app = QApplication.instance() or QApplication([])


class TestPanelRestoreAndTheme(unittest.TestCase):

    def setUp(self):
        self.doc_path = "/tmp/test_panel_restore_sample.pdf"
        doc = fitz.open()
        p = doc.new_page(width=500, height=500)
        p.insert_text((50, 100), "ORIGINAL PAGE TEXT", fontsize=14)
        doc.save(self.doc_path)
        doc.close()
        self.window = MainWindow()
        self.window.show()

    def tearDown(self):
        self.window.close()
        if os.path.exists(self.doc_path):
            try:
                os.remove(self.doc_path)
            except Exception:
                pass

    def test_dock_panels_restore_all(self):
        """Varmistaa, että kaikki suljetut tai piilotetut paneelit palautuvat reset_dock_layout -kutsulla."""
        docks = [
            self.window.thumb_dock,
            self.window.editor_dock,
            self.window.inspector_dock,
            self.window.shape_dock,
            self.window.layers_dock,
        ]

        # Varmistetaan että kaikilla on oikeat tunnistetiedot
        for d in docks:
            self.assertIsNotNone(d)
            self.assertTrue(len(d.objectName()) > 0)

        # Suljetaan kaikki paneelit (simuloidaan käyttäjän klikkaamaa ruksia 'x')
        for d in docks:
            d.close()
            self.assertTrue(d.isHidden())

        # Suoritetaan palautus
        self.window.reset_dock_layout()

        # Kaikkien tulee olla jälleen näkyvissä
        for d in docks:
            self.assertFalse(d.isHidden(), f"Paneelin {d.objectName()} pitäisi olla näkyvissä palautuksen jälkeen")

    def test_f4_shortcut_action_configured(self):
        """Varmistaa, että F4-pikanäppäintoiminto on kytketty ja palauttaa paneelit."""
        self.assertEqual(self.window.act_reset_panels.shortcut().toString(), "F4")

        # Piilotetaan tasopaneeli
        self.window.layers_dock.close()
        self.assertTrue(self.window.layers_dock.isHidden())

        # Laukaistaan F4-toiminto
        self.window.act_reset_panels.trigger()
        self.assertFalse(self.window.layers_dock.isHidden())

    def test_dock_toggle_menu_actions(self):
        """Varmistaa, että valikon kytkimet toimivat kaksisuuntaisesti."""
        self.window.reset_dock_layout()
        self.assertFalse(self.window.shape_dock.isHidden())

        # Kytketään pois
        self.window.act_dock_shape.trigger()
        self.assertTrue(self.window.shape_dock.isHidden())

        # Kytketään takaisin päälle
        self.window.act_dock_shape.trigger()
        self.assertFalse(self.window.shape_dock.isHidden())

    def test_text_edit_synced_with_shapes(self):
        """
        Kriittinen regressiotesti:
        Tekstin muokkauksen jälkeen piirretty muoto ei saa pyyhkiä pois muokattua tekstiä
        (varmistaa _sync_base_doc_from_doc toimivuuden).
        """
        model = PDFDocumentModel()
        model.open(self.doc_path)

        # 1. Etsitään tekstialue ja muokataan
        spans = model.get_spans_for_page(0)
        self.assertTrue(len(spans) > 0)
        target_span = spans[0]
        new_text = "KORJATTU TEKSTI 2026"

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
        self.assertIsNotNone(op)
        self.assertIn("KORJATTU TEKSTI 2026", model.doc[0].get_text())

        # 2. Piirretään suorakulmio samalle sivulle
        res_shape = model.draw_shape(
            page_idx=0,
            shape_type="rect",
            geometry=(60, 60, 200, 150),
            fill_color=(0.9, 0.9, 0.9),
            stroke_color=(0.2, 0.2, 0.2),
            stroke_width=1.5,
            fill_opacity=0.5,
            overlay=False
        )
        self.assertTrue(len(res_shape) > 0)

        # 3. Tarkistetaan, että muokattu teksti on yhä tallella sivulla
        current_text = model.doc[0].get_text()
        self.assertIn("KORJATTU TEKSTI 2026", current_text, "Muodon piirtäminen ei saa poistaa muokattua tekstiä!")
        self.assertNotIn("ORIGINAL PAGE TEXT", current_text)

    def test_layers_panel_styling_contrast(self):
        """Varmistaa, että tasopaneelissa ei ole silmiä häikäisevää valkoista taustaa."""
        layers = LayersPanel()
        sheet = layers.tree.styleSheet()
        # Varmistetaan että valkoinen taustaväri on poistettu ja tilalla on tumma teematausta
        self.assertNotIn("background-color: #ffffff", sheet)
        self.assertIn("#16161a", sheet)
        self.assertIn("#f8fafc", sheet)
        layers.close()


if __name__ == "__main__":
    unittest.main()
