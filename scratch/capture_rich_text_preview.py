"""
Visual verification script for rich text in textboxes:
Demonstrates mixed fonts, weights, colors in a single textbox,
and verifies contrast protection.
"""

import os
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPointF
from PyQt6.QtGui import QImage, QColor

from pdf_engine.pdf_document import PDFDocumentModel

def generate_preview():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])

    doc_path = "/tmp/preview_rich_text.pdf"
    doc = fitz.open()
    page = doc.new_page(width=650, height=500)
    # Background content
    page.insert_text((50, 60), "PDFwriter - Monipuolinen kirjasin- ja tekstilaatikkotuki", fontsize=18, fontname="helv", color=(0.1, 0.1, 0.2))
    page.insert_text((50, 90), "Dokumenttiin sijoitettu rikas tekstilaatikko useilla eri kirjasimilla ja väreillä:", fontsize=11, fontname="helv", color=(0.3, 0.3, 0.4))
    doc.save(doc_path)
    doc.close()

    model = PDFDocumentModel()
    model.open(doc_path)

    # 1. Luodaan tyylikäs rikas tekstilaatikko, jossa eri sanoilla on eri fontit, koot, leikkaukset ja värit
    rich_html = """
    <div style="font-family: sans-serif; font-size: 15pt; line-height: 1.4; color: #1e293b;">
      <p style="margin: 0; padding-bottom: 8px;">
        <span style="font-size: 20pt; font-weight: bold; color: #0284c7;">Otsikko: </span>
        <span style="font-family: serif; font-size: 19pt; font-style: italic; color: #b91c1c;">Useita kirjasimia sekaisin!</span>
      </p>
      <p style="margin: 0; padding-bottom: 6px;">
        <span>Tässä tekstilaatikossa on </span>
        <span style="font-weight: bold; color: #0f172a;">lihavoituja sanoja</span>, 
        <span style="font-family: monospace; font-size: 13pt; color: #047857; background-color: #e6f4ea;"> koodifontti [Monospace] </span> 
        <span>sekä </span>
        <span style="font-family: serif; font-size: 16pt; color: #6d28d9;">klassinen Serif-teksti</span>.
      </p>
      <p style="margin: 0; font-size: 12pt; color: #475569;">
        Kaikki tyylit piirtyvät täsmällisesti PDF-vektorina ilman hävikkiä.
      </p>
    </div>
    """

    model.draw_shape(
        page_idx=0,
        shape_type="textbox",
        geometry=(50, 120, 600, 360),
        text="Otsikko: Useita kirjasimia sekaisin! Tässä tekstilaatikossa on lihavoituja sanoja, koodifontti sekä klassinen Serif-teksti.",
        html=rich_html,
        fill_color=(0.95, 0.97, 1.0),
        stroke_color=(0.2, 0.5, 0.9),
        stroke_width=1.5,
        radius=10.0,
        overlay=True
    )

    model.reconstruct_page_shapes(0)

    # Tallennetaan artefaktiksi
    artifact_path = "/home/mika/.gemini/antigravity/brain/7713a66d-6609-4fab-81cd-223329e75939/rich_textbox_preview.png"
    pix = model.doc[0].get_pixmap(dpi=150)
    pix.save(artifact_path)
    print("Preview saved to:", artifact_path)
    model.close()

if __name__ == "__main__":
    generate_preview()
