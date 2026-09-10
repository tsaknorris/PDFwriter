"""
Capture preview of InlineShapeEditor with contrast protection.
"""

import os
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QImage, QPainter

from pdf_engine.pdf_document import PDFDocumentModel
from ui.page_canvas import PDFPageCanvas

def generate_editor_preview():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    doc_path = "/tmp/preview_contrast.pdf"
    import fitz
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    doc.save(doc_path)
    doc.close()

    model = PDFDocumentModel()
    model.open(doc_path)

    canvas = PDFPageCanvas()
    canvas.set_document(model)
    canvas.resize(600, 400)

    # Muoto jolla valkoinen teksti ja vaaleansininen täyttö
    s_id = model.draw_shape(
        page_idx=0,
        shape_type="textbox",
        geometry=(60, 80, 450, 240),
        text="Kirjoitetaan tekstiä...",
        text_color=(1.0, 1.0, 1.0),
        fill_color=(0.93, 0.95, 0.98),
        stroke_color=(0.2, 0.5, 0.9),
        stroke_width=1.5,
        radius=8.0,
        overlay=True
    )
    canvas.start_inline_shape_editor(s_id)
    canvas.inline_shape_editor.setHtml("<span style='color: #f8fafc; font-size: 16px; font-weight: bold;'>Tämä teksti on nyt 100% luettavissa!</span><br><span style='color: #38bdf8;'>Kontrastisuojaus estää näkymättömän tekstin.</span>")

    # Renderöidään canvas kuvaan
    img = QImage(600, 400, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    canvas.render(painter)
    painter.end()

    out_path = "/home/mika/.gemini/antigravity/brain/7713a66d-6609-4fab-81cd-223329e75939/inline_contrast_guard_preview.png"
    img.save(out_path)
    print("Editor preview saved to:", out_path)
    model.close()

if __name__ == "__main__":
    generate_editor_preview()
