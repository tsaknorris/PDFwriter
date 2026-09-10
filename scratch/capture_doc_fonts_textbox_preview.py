"""
Screenshot capture script demonstrating document fonts in Textbox tool on a new blank page.
"""
import os
import sys

sys.path.insert(0, "/home/mika/Desktop/diudiu/PDFwriter")

os.environ["QT_NO_NETWORK"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF, QEvent
from PyQt6.QtGui import QMouseEvent
from ui.main_window import MainWindow
from pdf_engine.font_resolver import LOCAL_FONTS_DIR

app = QApplication.instance() or QApplication(sys.argv)

# 1. Luodaan monipuolinen näytekirja, jossa on sivuja ja Stone Serif -tekstiä
test_pdf = "/tmp/preview_doc_with_fonts.pdf"
doc = fitz.open()

# Sivu 1: Stone Serif -otsikoita ja kappaleita
p1 = doc.new_page(width=595, height=842)
font_path = os.path.join(LOCAL_FONTS_DIR, "CrimsonPro.ttf")
p1.insert_textbox(
    fitz.Rect(50, 60, 545, 120),
    "1. LUKU: KIRJASINTEN MERKITYS JULKAISUSSA",
    fontfile=font_path,
    fontname="StoneSerifStd",
    fontsize=20
)
p1.insert_textbox(
    fitz.Rect(50, 130, 545, 400),
    "Tässä dokumentissa käytetään tyylikästä Stone Serif -kirjasinta (avoin vastine Crimson Pro).\n"
    "Kun käyttäjä haluaa lisätä uuden sivun tai tekstilaatikon, saman fontin tulee olla heti\n"
    "käytettävissä typografisesta valikosta ilman fonttien katoamista tai vääristymistä.",
    fontfile=font_path,
    fontname="StoneSerifStd",
    fontsize=13
)
doc.save(test_pdf)
doc.close()

# 2. Avataan MainWindow ja tiedosto
win = MainWindow()
win.resize(1500, 950)
win.open_file(test_pdf)

# 3. Luodaan uusi tyhjä sivu
win.menu_insert_blank_page()

# 4. Aktivoidaan tekstilaatikkotyökalu
win.shape_widget.set_tool("textbox")

# 5. Asetetaan tekstilaatikon ominaisuudet sivupalkissa
win.shape_widget.combo_font_family.setCurrentText("Stone Serif Std")
win.shape_widget.spin_font_size.setValue(18.0)
win.shape_widget.txt_shape_text.setPlainText("UUSI SIVU 2\n\nTämä tekstilaatikko kirjoitettiin suoraan dokumentin omalla Stone Serif -fontilla!\nFontti on valittu kätevästi '── Dokumentin fontit ──' -osiosta.")
win.shape_widget.btn_align_center.setChecked(True)
win.shape_widget.text_align = "center"
win.shape_widget.fill_rgb = (0.97, 0.98, 1.0)
win.shape_widget.stroke_rgb = (0.2, 0.45, 0.8)
win.shape_widget.stroke_width = 1.8
win.shape_widget.corner_radius = 6.0
# 6. Luodaan tekstilaatikko uudelle sivulle suoraan draw_shape-metodilla
new_id = win.doc_model.draw_shape(
    page_idx=1,
    shape_type="textbox",
    geometry=[40.0, 100.0, 480.0, 360.0],
    fill_color=(0.97, 0.98, 1.0),
    stroke_color=(0.2, 0.45, 0.8),
    fill_opacity=0.85,
    stroke_opacity=1.0,
    stroke_width=1.8,
    radius=6.0,
    overlay=True,
    rotation=0.0,
    text="UUSI SIVU 2\n\nTämä tekstilaatikko kirjoitettiin suoraan dokumentin omalla Stone Serif -fontilla!\nFontti on valittu kätevästi 'Dokumentin fontit' -osiosta.",
    font_family="Stone Serif Std",
    font_size=18.0,
    font_bold=False,
    font_italic=False,
    text_color=(0.1, 0.1, 0.1),
    text_align="center",
    vertical_align="middle",
    text_padding=8.0
)
win.canvas.select_shape(None)
win.canvas.set_zoom(0.85)
win.scroll_area.horizontalScrollBar().setValue(0)
win.editor_dock.setVisible(False)
win.shape_dock.raise_()
win.shape_widget.scroll_area.verticalScrollBar().setValue(160)
# Renderöidään ikkuna ja tallennetaan kuvakaappaus
win.show()
app.processEvents()

# Tyhjennetään tekstivalinta kankaalta ja editorista selkeää kuvaa varten
tc = win.shape_widget.txt_shape_text.textCursor()
tc.clearSelection()
win.shape_widget.txt_shape_text.setTextCursor(tc)
win.shape_widget.txt_shape_text.clearFocus()
win.canvas.selected_text_rects = []
win.canvas.selected_words = []
win.canvas.update()
app.processEvents()

preview_path = "/home/mika/.gemini/antigravity/brain/7713a66d-6609-4fab-81cd-223329e75939/doc_fonts_textbox_preview.png"
win.grab().save(preview_path)
print(f"Esikatselukuva tallennettu onnistuneesti: {preview_path}")

if os.path.exists(test_pdf):
    os.remove(test_pdf)
