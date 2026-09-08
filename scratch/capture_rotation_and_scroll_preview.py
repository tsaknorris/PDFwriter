"""
Visual verification script for free rotation and scrollable sidebar panels.
Renders MainWindow offscreen with rotated shapes and captures a screenshot.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ["QT_NO_NETWORK"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QColor

from app import setup_dark_fusion_palette
from ui.main_window import MainWindow

def main():
    app = QApplication.instance() or QApplication(sys.argv)
    setup_dark_fusion_palette(app)

    # 1. Luodaan tyhjä testidokumentti
    test_pdf = "/tmp/test_rotation_visual.pdf"
    doc = fitz.open()
    page = doc.new_page(width=700, height=900)
    page.insert_text((80, 100), "Acrobat Writer - Free Rotation & Scrollable Panels", fontsize=18)
    page.insert_text((80, 130), "Testing 360-degree free rotation for all objects and textboxes.", fontsize=12)
    doc.save(test_pdf)
    doc.close()

    # 2. Avataan pääikkuna
    win = MainWindow()
    win.resize(1366, 850)
    win.open_file(test_pdf)

    # 3. Asetetaan 100% zoom ja lisätään kierrettyjä objekteja
    win.canvas.set_zoom(1.0)

    # A. Kierretty pyöristetty suorakulmio (25 deg)
    win.doc_model.draw_shape(
        page_idx=0,
        shape_type="rounded_rect",
        geometry=(60.0, 180.0, 220.0, 290.0),
        fill_color=(0.2, 0.4, 0.8),
        stroke_color=(0.9, 0.9, 1.0),
        stroke_width=2.5,
        fill_opacity=0.85,
        radius=12.0,
        rotation=20.0
    )

    # B. Kierretty nuoli
    win.doc_model.draw_shape(
        page_idx=0,
        shape_type="arrow",
        geometry=((240.0, 240.0), (360.0, 200.0)),
        stroke_color=(0.9, 0.2, 0.2),
        stroke_width=4.0,
        fill_opacity=1.0,
        rotation=0.0
    )

    # C. Kierretty tekstilaatikko (25 deg)
    shape_id = win.doc_model.draw_shape(
        page_idx=0,
        shape_type="textbox",
        geometry=(80.0, 350.0, 320.0, 480.0),
        fill_color=(0.95, 0.95, 0.98),
        stroke_color=(0.1, 0.6, 0.4),
        stroke_width=2.0,
        fill_opacity=0.9,
        text="Moi! Tämä on kierretty tekstilaatikko.\nKirjoittaminen toimii vasemmalta oikealle!",
        font_size=13.0,
        text_color=(0.05, 0.2, 0.1),
        text_align="center",
        vertical_align="middle",
        rotation=25.0
    )

    # Valitaan tekstilaatikko kankaalla, jotta sen valintakehys ja vihreä kiertokahva tulevat näkyviin
    win.canvas.selected_shape_id = shape_id
    win.editor_dock.hide()
    win.shape_dock.show()
    win.shape_dock.raise_()
    shape_data = [s for s in win.doc_model.page_shapes.get(0, []) if s.get("id") == shape_id][0]
    win.shape_widget.load_shape_properties(shape_data)
    win.shape_widget.scroll_area.verticalScrollBar().setValue(120)
    win.canvas.update()

    # Pakotetaan maalaus ja tapahtumien käsittely
    app.processEvents()
    win.show()
    app.processEvents()

    # Tallennetaan ruutukaappaus
    output_png = "/home/mika/.gemini/antigravity/brain/7713a66d-6609-4fab-81cd-223329e75939/rotation_and_scroll_preview.png"
    pixmap = win.grab()
    pixmap.save(output_png, "PNG")
    print(f"Esikatselukuva tallennettu: {output_png} ({pixmap.width()}x{pixmap.height()})")

    win.close()
    if os.path.exists(test_pdf):
        os.remove(test_pdf)

if __name__ == "__main__":
    main()
