"""
Skripti sivujen erätoimintojen käyttöliittymän esikatselukuvan ottamiseksi.
Luo 267-sivuisen testidokumentin (kuten käyttäjän kuvakaappauksessa)
ja avaa BatchPageOperationsDialog -dialogin näyttäen syötteen '1-10, 20'.
"""

import os
import fitz
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPixmap, QPainter

from pdf_engine.pdf_document import PDFDocumentModel
from ui.main_window import MainWindow
from ui.batch_pages_dialog import BatchPageOperationsDialog


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    app = QApplication.instance()
    if not app:
        app = QApplication([])

    # Luodaan 267-sivuinen dokumentti vastaamaan käyttäjän tilannetta
    pdf_path = "/tmp/videogame_industry_267p.pdf"
    doc = fitz.open()
    for i in range(267):
        p = doc.new_page(width=595, height=842)
        if i == 0:
            p.insert_text((50, 100), "The Videogame Industry Does Not Exist", fontsize=24)
            p.insert_text((50, 140), "Sivu 1: Johdanto ja sisällys", fontsize=14)
        else:
            p.insert_text((50, 100), f"Luku {(i // 10) + 1} - Sivu {i + 1}", fontsize=18)
            p.insert_text((50, 130), "Tämä on testisivu sivujen erätoimintojen testaamiseksi.", fontsize=12)
    doc.save(pdf_path)
    doc.close()

    window = MainWindow()
    window.resize(1280, 850)
    window.open_file(pdf_path)

    # Korostetaan sivut 1-10 ja 20 sivupalkissa
    target_pages = list(range(10)) + [19]
    window.thumbnails_bar.set_selected_pages(target_pages)

    # Luodaan ja alustetaan erätoimintodialogi
    dlg = BatchPageOperationsDialog(
        window.doc_model,
        initial_pages=target_pages,
        parent=window
    )
    dlg.resize(640, 520)
    dlg.move(window.x() + 320, window.y() + 150)

    # Näytetään molemmat
    window.show()
    dlg.show()
    app.processEvents()

    # Otetaan ruutukaappaus ikkunasta siten, että dialogi on sen päällä
    full_pix = window.grab()
    dlg_pix = dlg.grab()

    combined = QPixmap(full_pix.size())
    combined.fill(Qt.GlobalColor.transparent)
    painter = QPainter(combined)
    painter.drawPixmap(0, 0, full_pix)
    # Piirretään dialogi keskelle
    dx = (full_pix.width() - dlg_pix.width()) // 2
    dy = (full_pix.height() - dlg_pix.height()) // 2
    painter.drawPixmap(dx, dy, dlg_pix)
    painter.end()

    output_path = "/home/mika/.gemini/antigravity/brain/7713a66d-6609-4fab-81cd-223329e75939/batch_page_operations_preview.png"
    combined.save(output_path, "PNG")
    print(f"Esikatselukuva tallennettu: {output_path}")

    window.close()
    dlg.close()


if __name__ == "__main__":
    main()
