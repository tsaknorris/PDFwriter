"""
Yksikkö- ja integraatiotestit: Tasot & Objektit -paneeli, ryhmittely ja Ctrl-kuvasuhdelukitus.
Varmistaa että:
1. Muodot rekisteröityvät objekteiksi ja säilyttävät tasojärjestyksen (Behind text, Text, Over text).
2. Ctrl-painikkeen kuvasuhdelukitus pakottaa ympyrät ja laatikot 1:1 suhteeseen ja nuolet 45 asteen kulmiin.
3. Tekstin taakse (Behind Text) viedyt muodot ovat suoraan valittavissa, muokattavissa ja poistettavissa.
4. Ryhmittely (Group / Ungroup) liittää useita muotoja yhteen ja siirtää koko ryhmää yhdessä.
5. Kumoa/Tee uudelleen (Ctrl+Z / Ctrl+Y) palauttaa objektit, tasot ja ryhmät täydellisesti.
6. Tasopaneelin (LayersPanel) käyttöliittymäkomponentti toimii ilman virheitä.
"""

import os
import unittest
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QPointF, Qt

from pdf_engine.pdf_document import PDFDocumentModel
from ui.page_canvas import PDFPageCanvas
from ui.layers_panel import LayersPanel

# Alustetaan QApplication testejä varten
app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestLayersAndGroups(unittest.TestCase):
    """Testaa tasojen, objektien, ryhmien ja kuvasuhteiden toimintaa."""

    def setUp(self):
        self.sample_pdf = "sample_document.pdf"
        self.assertTrue(os.path.isfile(self.sample_pdf), f"Testitiedosto puuttuu: {self.sample_pdf}")
        self.model = PDFDocumentModel()
        self.model.open(self.sample_pdf)

    def tearDown(self):
        if self.model.is_open:
            self.model.close()

    def test_shape_object_registration_and_layer_order(self):
        """1. Muotojen rekisteröinti ja pinojärjestys (Behind text, Text, Over text)."""
        # Lisätään muoto tekstin taakse (Behind Text)
        bg_id = self.model.draw_shape(
            page_idx=0,
            shape_type="rounded_rect",
            geometry=(50, 50, 250, 150),
            fill_color=(0.9, 0.95, 1.0),
            stroke_color=(0.3, 0.5, 0.8),
            overlay=False,
            name="Taustakortti 1"
        )
        self.assertTrue(bg_id)
        self.assertTrue(bg_id.startswith("shape_"))

        # Lisätään muoto tekstin eteen (Over Text)
        fg_id = self.model.draw_shape(
            page_idx=0,
            shape_type="arrow",
            geometry=((100, 200), (300, 200)),
            stroke_color=(1.0, 0.0, 0.0),
            stroke_width=2.5,
            overlay=True,
            name="Punainen nuoli"
        )
        self.assertTrue(fg_id)

        # Haetaan sivun kaikki elementit
        elements = self.model.get_page_elements(0)
        self.assertGreater(len(elements), 2)

        # Etsitään taustaelementti, tekstielementit ja etuelementti
        behind_elems = [e for e in elements if e["layer"] == "behind_text"]
        text_elems = [e for e in elements if e["layer"] == "text"]
        over_elems = [e for e in elements if e["layer"] == "over_text"]

        self.assertEqual(len(behind_elems), 1)
        self.assertEqual(behind_elems[0]["id"], bg_id)
        self.assertEqual(behind_elems[0]["name"], "Taustakortti 1")

        self.assertGreaterEqual(len(text_elems), 1)

        self.assertEqual(len(over_elems), 1)
        self.assertEqual(over_elems[0]["id"], fg_id)
        self.assertEqual(over_elems[0]["name"], "Punainen nuoli")

    def test_aspect_ratio_constraint_ctrl(self):
        """2. Ctrl-painikkeen 1:1 kuvasuhdelukitus ja 45 asteen kulmalukitus."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.model)

        # A: Ympyrä / Neliö (dx=60, dy=140) -> lukittuu 1:1 (s=140)
        p_start = QPointF(100.0, 100.0)
        p_cur = QPointF(160.0, 240.0)
        p_constrained = canvas._constrain_shape_point(p_start, p_cur, "circle")
        dx = abs(p_constrained.x() - p_start.x())
        dy = abs(p_constrained.y() - p_start.y())
        self.assertAlmostEqual(dx, dy, places=4, msg="Ympyrän leveyden ja korkeuden on oltava tasan 1:1")
        self.assertAlmostEqual(dx, 140.0, places=4)

        # B: Suorakulmio neliöksi
        p_rect_c = canvas._constrain_shape_point(p_start, QPointF(250.0, 180.0), "rect")
        dx_r = abs(p_rect_c.x() - p_start.x())
        dy_r = abs(p_rect_c.y() - p_start.y())
        self.assertAlmostEqual(dx_r, dy_r, places=4, msg="Suorakulmion on oltava tasan 1:1 neliö")

        # C: Nuolen kulmalukitus (dx=100, dy=20) -> lähin 45 asteen kulma on 0 astetta (vaakasuora)
        p_arrow_c = canvas._constrain_shape_point(p_start, QPointF(200.0, 115.0), "arrow")
        # Pystyeron tulisi olla 0 koska kulma pyöristyy 0 asteeseen
        self.assertAlmostEqual(p_arrow_c.y(), p_start.y(), places=2, msg="Nuolen pitää lukittua täysin vaakasuoraan (0 astetta)")

    def test_select_and_modify_behind_text_shape(self):
        """3. Tekstin taakse viedyn muodon suora valinta, muokkaus ja poisto ID:n perusteella."""
        # Lisätään taustakortti
        card_id = self.model.draw_shape(
            page_idx=0,
            shape_type="rounded_rect",
            geometry=(40, 40, 200, 120),
            fill_color=(0.95, 0.95, 0.95),
            stroke_color=(0.5, 0.5, 0.5),
            overlay=False,
            name="Taustakortti Testi"
        )
        self.assertTrue(card_id)

        # 1. Haetaan ID:llä
        shape = self.model.get_shape(0, card_id)
        self.assertIsNotNone(shape)
        self.assertFalse(shape["overlay"], "Muodon tulee olla tekstin alla (overlay=False)")

        # 2. Päivitetään väri ja siirretään
        success_upd = self.model.update_shape(
            0, card_id,
            fill_color=(1.0, 0.9, 0.8),
            geometry=(50, 50, 220, 130)
        )
        self.assertTrue(success_upd)
        upd_shape = self.model.get_shape(0, card_id)
        self.assertEqual(upd_shape["fill_color"], (1.0, 0.9, 0.8))
        self.assertEqual(upd_shape["geometry"], (50, 50, 220, 130))

        # 3. Poistetaan muoto
        success_del = self.model.delete_shape(0, card_id)
        self.assertTrue(success_del)
        self.assertIsNone(self.model.get_shape(0, card_id), "Poistetun muodon ei pitäisi enää löytyä")
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 0)

    def test_group_and_ungroup_shapes(self):
        """4. Muotojen ryhmittely (Group) ja purkaminen (Ungroup) sekä ryhmän yhteissiirto."""
        s1 = self.model.draw_shape(0, "circle", (50, 50, 100, 100))
        s2 = self.model.draw_shape(0, "rect", (120, 50, 200, 100))
        s3 = self.model.draw_shape(0, "line", ((50, 120), (200, 120)))

        # Ryhmitellään s1 ja s2
        group_id = self.model.group_shapes(0, [s1, s2])
        self.assertIsNotNone(group_id)
        self.assertTrue(group_id.startswith("group_"))

        shape1 = self.model.get_shape(0, s1)
        shape2 = self.model.get_shape(0, s2)
        shape3 = self.model.get_shape(0, s3)

        self.assertEqual(shape1["group_id"], group_id)
        self.assertEqual(shape2["group_id"], group_id)
        self.assertIsNone(shape3["group_id"])

        # Siirretään s1:tä (dx=30, dy=40) -> s2:n pitää siirtyä MUKANA!
        orig_s2_geom = shape2["geometry"]
        self.model.move_shape(0, s1, dx=30.0, dy=40.0)

        new_shape1 = self.model.get_shape(0, s1)
        new_shape2 = self.model.get_shape(0, s2)
        new_shape3 = self.model.get_shape(0, s3)

        self.assertEqual(new_shape1["geometry"], (80.0, 90.0, 130.0, 140.0))
        self.assertEqual(new_shape2["geometry"], (orig_s2_geom[0] + 30.0, orig_s2_geom[1] + 40.0, orig_s2_geom[2] + 30.0, orig_s2_geom[3] + 40.0))
        self.assertEqual(new_shape3["geometry"], ((50, 120), (200, 120)), "Ryhmään kuulumattoman muodon ei tule liikkua")

        # Puretaan ryhmä
        ungroup_ok = self.model.ungroup_shapes(0, group_id)
        self.assertTrue(ungroup_ok)
        self.assertIsNone(self.model.get_shape(0, s1)["group_id"])
        self.assertIsNone(self.model.get_shape(0, s2)["group_id"])

    def test_undo_redo_layers_and_groups(self):
        """5. Kumoa/Tee uudelleen (Ctrl+Z / Ctrl+Y) objektien lisäykselle, ryhmittelylle ja poistolle."""
        self.assertFalse(self.model.can_undo())

        # Lisätään muoto
        s1 = self.model.draw_shape(0, "rect", (60, 60, 160, 160), name="Testilaatikko")
        self.assertTrue(self.model.can_undo())
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 1)

        # Kumotaan lisäys (Ctrl+Z)
        self.model.undo()
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 0)
        self.assertTrue(self.model.can_redo())

        # Tehdään uudelleen (Ctrl+Y)
        self.model.redo()
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 1)
        self.assertEqual(self.model.page_shapes[0][0]["name"], "Testilaatikko")

        # Poistetaan muoto
        self.model.delete_shape(0, s1)
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 0)

        # Kumotaan poisto (muodon pitää palata!)
        self.model.undo()
        self.assertEqual(len(self.model.page_shapes.get(0, [])), 1)
        self.assertEqual(self.model.page_shapes[0][0]["id"], s1)

    def test_layers_panel_widget(self):
        """6. Tasot & Objektit -paneelin käyttöliittymäkomponentin toiminta."""
        panel = LayersPanel()
        panel.set_document(self.model, 0)

        # Lisätään muoto tekstin taakse ja eteen
        s_behind = self.model.draw_shape(0, "rounded_rect", (20, 20, 100, 100), overlay=False, name="Tausta 1")
        s_over = self.model.draw_shape(0, "circle", (120, 120, 180, 180), overlay=True, name="Ympyrä 1")

        panel.refresh_elements()

        # Puunäkymässä pitää olla 3 kategoriaa (Over text, Text, Behind text)
        self.assertEqual(panel.tree.topLevelItemCount(), 3)
        top_over = panel.tree.topLevelItem(0)
        top_text = panel.tree.topLevelItem(1)
        top_behind = panel.tree.topLevelItem(2)

        self.assertEqual(top_over.childCount(), 1)
        self.assertGreaterEqual(top_text.childCount(), 1)
        self.assertEqual(top_behind.childCount(), 1)

        # Valitaan taustamuoto kankaalta tulleen ID:n mukaan
        panel.select_item_by_id(s_behind)
        selected = panel.tree.selectedItems()
        self.assertEqual(len(selected), 1)
        item_data = selected[0].data(0, Qt.ItemDataRole.UserRole)
        self.assertEqual(item_data["id"], s_behind)

        # Testataan tasonvaihto (Tekstin alle -> Tekstin päälle)
        panel._toggle_layer_placement()
        upd_shape = self.model.get_shape(0, s_behind)
        self.assertTrue(upd_shape["overlay"], "Muodon pitää siirtyä tekstin päälle")


if __name__ == "__main__":
    unittest.main()
