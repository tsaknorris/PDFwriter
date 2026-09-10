"""
Unit tests for rich text formatting in textboxes:
- Mixed fonts, weights, sizes, and colors in a single textbox
- Contrast protection in inline shape editor (preventing invisible text)
- Color isolation (preventing selected shape color changes from corrupting global defaults)
- PyMuPDF insert_htmlbox rendering of mixed fonts
- Undo/redo for rich text
"""

import unittest
import os
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QMouseEvent, QTextCharFormat, QFont, QColor, QTextCursor

from pdf_engine.pdf_document import PDFDocumentModel
from ui.shape_properties_dock import ShapePropertiesDock
from ui.page_canvas import PDFPageCanvas, InlineShapeEditor

app = QApplication.instance()
if app is None:
    app = QApplication([])


class TestRichTextbox(unittest.TestCase):
    def setUp(self):
        self.doc_path = "/tmp/test_rich_textbox.pdf"
        doc = fitz.open()
        p = doc.new_page(width=600, height=800)
        p.insert_text((50, 100), "Rich Textbox Test Document", fontsize=14)
        doc.save(self.doc_path)
        doc.close()

        self.doc_model = PDFDocumentModel()
        self.doc_model.open(self.doc_path)

    def tearDown(self):
        self.doc_model.close()
        if os.path.exists(self.doc_path):
            try:
                os.remove(self.doc_path)
            except Exception:
                pass

    def test_textbox_default_color_not_polluted_by_selected_shape(self):
        """Varmistaa että valitun muodon värinmuutos valkoiseksi ei saastuta tulevien tekstilaatikoiden oletusväriä."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)
        dock = ShapePropertiesDock()
        canvas.shape_selected.connect(dock.load_shape_properties)
        dock.properties_changed.connect(canvas.set_shape_properties)

        # 1. Alussa oletusväri on musta (0.0, 0.0, 0.0)
        self.assertEqual(dock.default_props["text_color_rgb"], (0.0, 0.0, 0.0))

        # 2. Luodaan ensimmäinen tekstilaatikko
        s1_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(50, 150, 250, 250),
            text="Ensimmäinen laatikko",
            text_color=(0.0, 0.0, 0.0)
        )
        canvas.select_shape(s1_id)
        self.assertEqual(dock.selected_shape_id, s1_id)

        # 3. Käyttäjä muuttaa TÄMÄN valitun laatikon tekstivärin valkoiseksi (1, 1, 1)
        dock.set_text_color((1.0, 1.0, 1.0))
        s1_updated = self.doc_model.get_shape(0, s1_id)
        self.assertEqual(s1_updated["text_color"], (1.0, 1.0, 1.0))

        # 4. TÄRKEÄ: default_props EI saa muuttua valkoiseksi, koska muoto oli valittuna!
        self.assertEqual(dock.default_props["text_color_rgb"], (0.0, 0.0, 0.0))

        # 5. Poistetaan valinta ja luodaan toinen tekstilaatikko piirtämällä
        canvas.select_shape(None)
        self.assertIsNone(dock.selected_shape_id)
        self.assertEqual(dock.text_color_rgb, (0.0, 0.0, 0.0))

        # Valitaan textbox-työkalu
        dock.set_tool("textbox")
        self.assertEqual(canvas.active_tool, "textbox")

        # Simuloidaan uuden tekstilaatikon piirtäminen kankaalle
        canvas.is_drawing_shape = True
        canvas.shape_start_pos = QPointF(50, 300)
        canvas.shape_current_pos = QPointF(250, 400)
        rel_ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonRelease,
            QPointF(250, 400),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier
        )
        canvas.mouseReleaseEvent(rel_ev)

        shapes = self.doc_model.page_shapes.get(0, [])
        self.assertEqual(len(shapes), 2)
        s2 = shapes[1]
        # Toisen tekstilaatikon tekstiväri ON MUSTA eikä valkoinen!
        self.assertEqual(s2["text_color"], (0.0, 0.0, 0.0))

    def test_inline_editor_contrast_guard(self):
        """Varmistaa että kelluva in-canvas editori suojaa käyttäjän näkymättömältä tekstiltä kontrastisuojalla."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)

        # Valkoinen teksti vaaleansinisellä pohjalla (kuten käyttäjän raportissa)
        shape_light_bg = {
            "id": "s_test_1",
            "text": "Näkymätön testi",
            "text_color": (1.0, 1.0, 1.0),
            "fill_color": (0.93, 0.95, 0.98),
            "font_size": 14.0
        }
        canvas._update_inline_shape_editor_style(shape_light_bg)
        style = canvas.inline_shape_editor.styleSheet()

        # Kontrastisuojan tulee ottaa tumma tausta käyttöön, jotta valkoinen teksti näkyy selvästi
        self.assertIn("#1e1e24", style, "Valkoisen tekstin vaalealla pohjalla tulee saada tumma kontrastitausta!")

    def test_rich_text_selection_formatting(self):
        """Varmistaa että valitulle tekstijaksolle voidaan asettaa eri fontti, leikkaus ja väri."""
        dock = ShapePropertiesDock()
        dock.txt_shape_text.setPlainText("Kissa istuu puussa")

        # Valitaan sana 'istuu' (indeksit 6..11)
        cursor = dock.txt_shape_text.textCursor()
        cursor.setPosition(6)
        cursor.setPosition(11, cursor.MoveMode.KeepAnchor)
        dock.txt_shape_text.setTextCursor(cursor)
        self.assertEqual(dock.txt_shape_text.textCursor().selectedText(), "istuu")

        # 1. Lihavoidaan vain valittu sana
        dock._on_bold_toggled(True)

        # 2. Asetetaan valitulle sanalle Times-fontti
        dock._on_font_family_changed("Times")

        # 3. Asetetaan valitulle sanalle punainen väri
        dock.set_text_color((1.0, 0.0, 0.0))

        html = dock.txt_shape_text.toHtml()
        # Varmistetaan että HTML sisältää Times, lihavoinnin ja punaisen värin vain istuu-sanalle
        self.assertIn("Times", html)
        self.assertIn("#ff0000", html)
        self.assertIn("istuu", html)

    def test_rich_text_pdf_rendering_mixed_fonts(self):
        """Varmistaa että useampaa eri fonttia ja väriä sisältävä HTML renderöityy PDF-sivulle oikein."""
        html_content = """
        <div style="font-family: sans-serif; font-size: 14pt; color: #000000;">
          <span>Normaali </span>
          <span style="font-family: serif; font-weight: bold; color: #cc0000;">Lihavoitu Punainen</span>
          <span> ja </span>
          <span style="font-family: monospace; font-style: italic; color: #0000ff;">Kursivoitu Sininen</span>
        </div>
        """

        s_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(50, 150, 450, 300),
            text="Normaali Lihavoitu Punainen ja Kursivoitu Sininen",
            html=html_content,
            fill_color=(0.95, 0.95, 0.95),
            overlay=True
        )

        self.doc_model.reconstruct_page_shapes(0)
        page = self.doc_model.doc[0]

        # Tutkitaan sivun generoituja spaneja
        text_dict = page.get_text("dict")
        found_red_bold = False
        found_blue_italic = False

        for b in text_dict.get("blocks", []):
            if "lines" in b:
                for l in b["lines"]:
                    for s in l["spans"]:
                        text = s["text"]
                        color_hex = hex(s["color"])
                        font_name = s["font"].lower()

                        if "lihavoitu punainen" in text.lower():
                            # Tarkistetaan että väri on punertava ja fontti bold
                            if s["color"] > 0x880000 and ("bold" in font_name or s.get("flags", 0) & 2):
                                found_red_bold = True

                        if "kursivoitu sininen" in text.lower():
                            # Tarkistetaan että väri on sinertävä ja fontti italic
                            if (s["color"] & 0xff) > 0xaa and ("italic" in font_name or "oblique" in font_name or s.get("flags", 0) & 1):
                                found_blue_italic = True

        self.assertTrue(found_red_bold, "Lihavoitu punainen teksti ei renderöitynyt PDF:ään!")
        self.assertTrue(found_blue_italic, "Kursivoitu sininen teksti ei renderöitynyt PDF:ään!")

    def test_rich_text_undo_redo(self):
        """Varmistaa että rikaan tekstin muokkaukset tallentuvat Undo/Redo -historiaan."""
        s_id = self.doc_model.draw_shape(
            page_idx=0,
            shape_type="textbox",
            geometry=(50, 100, 300, 200),
            text="Alkuperäinen teksti",
            html="<p>Alkuperäinen teksti</p>"
        )
        self.assertEqual(self.doc_model.get_shape(0, s_id)["text"], "Alkuperäinen teksti")

        # Päivitetään rikkaaksi tekstiksi
        rich_html = "<p>Muokattu <b>Lihavoitu</b> teksti</p>"
        self.doc_model.update_shape(0, s_id, text="Muokattu Lihavoitu teksti", html=rich_html, push_undo=True)
        self.assertEqual(self.doc_model.get_shape(0, s_id)["html"], rich_html)

        # Undo
        self.doc_model.undo()
        self.assertEqual(self.doc_model.get_shape(0, s_id)["text"], "Alkuperäinen teksti")
        self.assertEqual(self.doc_model.get_shape(0, s_id)["html"], "<p>Alkuperäinen teksti</p>")

        # Redo
        self.doc_model.redo()
        self.assertEqual(self.doc_model.get_shape(0, s_id)["text"], "Muokattu Lihavoitu teksti")
        self.assertEqual(self.doc_model.get_shape(0, s_id)["html"], rich_html)

    def test_line_scoped_formatting_without_manual_drag_selection(self):
        """Varmistaa että kursorin ollessa rivillä ilman maalausta, fontin/koon muutos kohdistuu vain kyseiseen riviin eikä koko laatikkoon."""
        dock = ShapePropertiesDock()
        dock.load_shape_properties({
            "id": "s_test_multiline",
            "type": "textbox",
            "text": "Plaa Plaa plaaa\nPllll plll plllll",
            "font_family": "Times",
            "font_size": 14.0,
            "text_color": (0.0, 0.0, 0.0),
        })

        # Asetetaan kursori riville 1 (pos 5) ilman maalausta
        cursor = dock.txt_shape_text.textCursor()
        cursor.setPosition(5)
        dock.txt_shape_text.setTextCursor(cursor)
        self.assertFalse(dock.txt_shape_text.textCursor().hasSelection())

        # Vaihdetaan fontti Arialiksi ja koko 18pt ja lihavoidaan valitsemalla Rivi-kohdistus
        dock.rb_scope_line.setChecked(True)
        dock._on_font_family_changed("Arial")
        dock._on_font_size_changed(18.0)
        dock._on_bold_toggled(True)

        html = dock.txt_shape_text.toHtml()

        # Tarkistetaan että Rivi 1 sai Arial ja 18pt
        self.assertIn("Arial", html)
        self.assertIn("18pt", html)
        # TÄRKEÄ: Rivi 2 ei muuttunut Arialiksi, vaan säilytti Times-fontin!
        self.assertIn("Times", html)

    def test_cursor_position_changed_updates_controls(self):
        """Varmistaa että työkalurivin valitsimet (fontti, koko, leikkaus) päivittyvät kun kursori siirtyy riviltä toiselle."""
        dock = ShapePropertiesDock()
        html_sample = (
            "<html><body>"
            "<p style=\"font-family:'Arial'; font-size:20pt; font-weight:bold; color:#cc0000;\">Otsikkorivi Arial</p>"
            "<p style=\"font-family:'Times'; font-size:12pt; font-weight:normal; color:#0000cc;\">Leipäteksti Times</p>"
            "</body></html>"
        )
        dock.load_shape_properties({
            "id": "s_test_sync",
            "type": "textbox",
            "text": "Otsikkorivi Arial\nLeipäteksti Times",
            "html": html_sample,
            "font_family": "Arial",
            "font_size": 20.0
        })

        # 1. Siirretään kursori riville 1
        c1 = dock.txt_shape_text.textCursor()
        c1.setPosition(5)
        dock.txt_shape_text.setTextCursor(c1)
        app.processEvents()

        self.assertEqual(dock.combo_font_family.currentText(), "Arial")
        self.assertEqual(dock.spin_font_size.value(), 20.0)
        self.assertTrue(dock.btn_text_bold.isChecked())

        # 2. Siirretään kursori riville 2
        c2 = dock.txt_shape_text.textCursor()
        c2.setPosition(25)
        dock.txt_shape_text.setTextCursor(c2)
        app.processEvents()

        self.assertEqual(dock.combo_font_family.currentText(), "Times")
        self.assertEqual(dock.spin_font_size.value(), 12.0)
        self.assertFalse(dock.btn_text_bold.isChecked())

    def test_all_scope_formatting(self):
        """Varmistaa että kun 'Koko teksti' on valittuna, muutos kohdistuu kaikkiin riveihin."""
        dock = ShapePropertiesDock()
        dock.load_shape_properties({
            "id": "s_test_all",
            "type": "textbox",
            "text": "Rivi 1\nRivi 2",
            "font_family": "Times",
            "font_size": 14.0,
        })

        # Valitaan 'Koko teksti'
        dock.rb_scope_all.setChecked(True)
        dock._on_font_family_changed("Courier")

        html = dock.txt_shape_text.toHtml()
        self.assertIn("Courier", html)
        self.assertNotIn("Times", html)

    def test_every_word_different_font_and_color(self):
        """Varmistaa että tekstilaatikossa jokainen sana voi olla eri fontilla, koolla, leikkauksella ja värillä."""
        dock = ShapePropertiesDock()
        dock.load_shape_properties({
            "id": "word_test",
            "type": "textbox",
            "text": "Yksi Kaksi Kolme",
            "font_family": "Helvetica",
            "font_size": 14.0
        })

        # Sana 1: 'Yksi' (pos 0..4) -> Arial 24pt Bold Red
        c1 = dock.txt_shape_text.textCursor()
        c1.setPosition(0)
        c1.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        dock.txt_shape_text.setTextCursor(c1)
        dock._on_font_family_changed("Arial")
        dock._on_font_size_changed(24.0)
        dock._on_bold_toggled(True)
        dock.set_text_color((1.0, 0.0, 0.0))

        # Sana 2: 'Kaksi' (pos 5..10) -> Times 12pt Italic Blue
        c2 = dock.txt_shape_text.textCursor()
        c2.setPosition(5)
        c2.setPosition(10, QTextCursor.MoveMode.KeepAnchor)
        dock.txt_shape_text.setTextCursor(c2)
        dock._on_font_family_changed("Times")
        dock._on_font_size_changed(12.0)
        dock._on_bold_toggled(False)
        dock._on_italic_toggled(True)
        dock.set_text_color((0.0, 0.0, 1.0))

        # Sana 3: 'Kolme' (pos 11..16) -> Courier 18pt Green
        c3 = dock.txt_shape_text.textCursor()
        c3.setPosition(11)
        c3.setPosition(16, QTextCursor.MoveMode.KeepAnchor)
        dock.txt_shape_text.setTextCursor(c3)
        dock._on_font_family_changed("Courier")
        dock._on_font_size_changed(18.0)
        dock._on_italic_toggled(False)
        dock.set_text_color((0.0, 0.8, 0.2))

        html = dock.txt_shape_text.toHtml()
        self.assertIn("Arial", html)
        self.assertIn("Times", html)
        self.assertIn("Courier", html)
        self.assertIn("24pt", html)
        self.assertIn("12pt", html)
        self.assertIn("18pt", html)
        self.assertIn("#ff0000", html)
        self.assertIn("#0000ff", html)

    def test_type_hello_world_every_letter_different_font_and_size(self):
        """Varmistaa että käyttäjä voi kirjoittaa 'HeLlO WoRlD' siten että joka kirjain syötetään eri fontilla, koolla ja värillä."""
        dock = ShapePropertiesDock()
        dock.load_shape_properties({
            "id": "hello_world_test",
            "type": "textbox",
            "text": "",
            "font_family": "Arial",
            "font_size": 20.0
        })
        dock.txt_shape_text.clear()
        dock.rb_scope_selection.setChecked(True)

        # 1. 'H' -> Arial 26pt Bold Red
        dock._on_font_family_changed("Arial")
        dock._on_font_size_changed(26.0)
        dock._on_bold_toggled(True)
        dock.set_text_color((1.0, 0.0, 0.0))
        dock.txt_shape_text.insertPlainText("H")

        # 2. 'e' -> Times 14pt Italic Blue
        dock._on_font_family_changed("Times")
        dock._on_font_size_changed(14.0)
        dock._on_bold_toggled(False)
        dock._on_italic_toggled(True)
        dock.set_text_color((0.0, 0.0, 1.0))
        dock.txt_shape_text.insertPlainText("e")

        # 3. 'L' -> Courier 20pt Normal Green
        dock._on_font_family_changed("Courier")
        dock._on_font_size_changed(20.0)
        dock._on_italic_toggled(False)
        dock.set_text_color((0.0, 0.8, 0.2))
        dock.txt_shape_text.insertPlainText("L")

        # 4. 'l' -> Georgia 16pt Bold Orange
        dock._on_font_family_changed("Georgia")
        dock._on_font_size_changed(16.0)
        dock._on_bold_toggled(True)
        dock.set_text_color((1.0, 0.5, 0.0))
        dock.txt_shape_text.insertPlainText("l")

        # 5. 'O' -> Helvetica 24pt Normal Purple
        dock._on_font_family_changed("Helvetica")
        dock._on_font_size_changed(24.0)
        dock._on_bold_toggled(False)
        dock.set_text_color((0.6, 0.1, 0.8))
        dock.txt_shape_text.insertPlainText("O")

        self.assertEqual(dock.txt_shape_text.toPlainText(), "HeLlO")
        html = dock.txt_shape_text.toHtml()
        self.assertIn("Arial", html)
        self.assertIn("Times", html)
        self.assertIn("Courier", html)
        self.assertIn("Georgia", html)
        self.assertIn("Helvetica", html)
        self.assertIn("26pt", html)
        self.assertIn("14pt", html)
        self.assertIn("20pt", html)
        self.assertIn("16pt", html)
        self.assertIn("24pt", html)

    def test_live_preview_keystrokes_update_model_and_canvas(self):
        """Varmistaa että jokainen kirjoitettu kirjain päivittää tekstilaatikon reaaliajassa kankaalle."""
        canvas = PDFPageCanvas()
        canvas.set_document(self.doc_model)
        dock = ShapePropertiesDock()
        canvas.shape_selected.connect(dock.load_shape_properties)
        dock.properties_changed.connect(canvas.set_shape_properties)

        sid = self.doc_model.draw_shape(0, "textbox", (50, 50, 300, 100), text="", font_family="Arial", font_size=14.0)
        canvas.select_shape(sid)
        canvas.refresh_page()

        # Kirjoitetaan merkki kerrallaan ja tarkistetaan reaaliaikainen päivitys
        dock.txt_shape_text.insertPlainText("M")
        shape = self.doc_model.get_shape(0, sid)
        self.assertEqual(shape.get("text"), "M")

        dock.txt_shape_text.insertPlainText("o")
        shape = self.doc_model.get_shape(0, sid)
        self.assertEqual(shape.get("text"), "Mo")

        dock.txt_shape_text.insertPlainText("i")
        shape = self.doc_model.get_shape(0, sid)
        self.assertEqual(shape.get("text"), "Moi")


if __name__ == "__main__":
    unittest.main()
