#!/usr/bin/env python3
"""
Acrobat-tason Offline PDF-Editori (Linux / NixOS Architecture).
Pääkäynnistystiedosto.
"""

import sys
import os

# Eristyskriitikko: Pakotetaan Qt ja prosessi 100 % offline-tilaan
os.environ["QT_NO_NETWORK"] = "1"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QFont, QPalette, QColor
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow


def setup_dark_fusion_palette(app: QApplication):
    """Asettaa modernin, korkeakontrastisen Acrobat Dark Pro -työpöytäteeman."""
    app.setStyle("Fusion")
    palette = QPalette()
    # Päätausta: moderni, ergonominen syvä hiili
    palette.setColor(QPalette.ColorRole.Window, QColor(32, 32, 38))
    # Pääteksti: Erittäin kirkas ja selkeä valkoinen (WCAG AAA kontrasti)
    palette.setColor(QPalette.ColorRole.WindowText, QColor(248, 250, 252))
    # Syöttökenttien ja listojen tausta: selkeä syvä pinta
    palette.setColor(QPalette.ColorRole.Base, QColor(22, 22, 26))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(28, 28, 34))
    # Työkaluvihjeet
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(248, 250, 252))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(15, 23, 42))
    # Teksti kentissä
    palette.setColor(QPalette.ColorRole.Text, QColor(248, 250, 252))
    # Painikkeet
    palette.setColor(QPalette.ColorRole.Button, QColor(44, 44, 52))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(248, 250, 252))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(239, 68, 68))
    palette.setColor(QPalette.ColorRole.Link, QColor(56, 189, 248))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(2, 132, 199))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)

    # Globaali korkean kontrastin tyylitiedosto
    app.setStyleSheet("""
        /* Yleinen tekstikontrasti - estää himmeän harmaan tekstin */
        QLabel {
            color: #f1f2f6;
        }
        QGroupBox {
            font-weight: bold;
            color: #f8fafc;
            border: 1px solid #4a4a58;
            border-radius: 6px;
            margin-top: 10px;
            padding-top: 14px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
            color: #38bdf8;
        }
        QDockWidget {
            color: #f8fafc;
            font-weight: bold;
        }
        QDockWidget::title {
            background-color: #26262e;
            color: #f8fafc;
            font-weight: bold;
            padding: 6px 8px;
            border-bottom: 1px solid #4a4a58;
        }
        QTabBar::tab {
            background-color: #222228;
            color: #cbd5e1;
            padding: 6px 14px;
            border: 1px solid #3e3e4c;
            border-bottom: none;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background-color: #32323c;
            color: #ffffff;
            font-weight: bold;
            border-bottom: 2px solid #0284c7;
        }
        QTabBar::tab:hover:!selected {
            background-color: #2a2a34;
            color: #ffffff;
        }
        QLineEdit, QTextEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
            background-color: #16161a;
            color: #f8fafc;
            border: 1px solid #4a4a58;
            border-radius: 4px;
            padding: 4px 6px;
            selection-background-color: #0284c7;
            selection-color: #ffffff;
        }
        QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
            border: 1px solid #38bdf8;
        }
        QPushButton {
            background-color: #363642;
            color: #f8fafc;
            border: 1px solid #4f4f60;
            border-radius: 4px;
            padding: 5px 10px;
            font-weight: normal;
        }
        QPushButton:hover {
            background-color: #444454;
            border-color: #38bdf8;
        }
        QPushButton:pressed {
            background-color: #262630;
        }
        QPushButton:disabled {
            background-color: #222228;
            color: #64748b;
            border-color: #33333e;
        }
        QToolBar {
            background-color: #222228;
            border-bottom: 1px solid #3a3a46;
            spacing: 3px;
            padding: 2px;
        }
        QStatusBar {
            background-color: #1a1a20;
            color: #e2e8f0;
            border-top: 1px solid #3a3a46;
        }
        QMenu {
            background-color: #222228;
            color: #f8fafc;
            border: 1px solid #4a4a58;
        }
        QMenu::item {
            padding: 5px 24px 5px 10px;
        }
        QMenu::item:selected {
            background-color: #0284c7;
            color: #ffffff;
        }
        QMenu::separator {
            height: 1px;
            background-color: #3a3a46;
            margin: 4px 0;
        }
        QHeaderView::section {
            background-color: #26262e;
            color: #f8fafc;
            font-weight: bold;
            padding: 5px;
            border: 1px solid #3a3a46;
        }
        QScrollBar:vertical {
            border: none;
            background-color: #1a1a20;
            width: 12px;
            margin: 0;
        }
        QScrollBar::handle:vertical {
            background-color: #444454;
            border-radius: 6px;
            min-height: 20px;
            margin: 2px;
        }
        QScrollBar::handle:vertical:hover {
            background-color: #58586c;
        }
        QScrollBar:horizontal {
            border: none;
            background-color: #1a1a20;
            height: 12px;
            margin: 0;
        }
        QScrollBar::handle:horizontal {
            background-color: #444454;
            border-radius: 6px;
            min-width: 20px;
            margin: 2px;
        }
        QScrollBar::handle:horizontal:hover {
            background-color: #58586c;
        }
    """)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDFwriter")
    app.setOrganizationName("DiudiuLab")

    # Fontin asetus järjestelmäfonttiin
    font = QFont("sans-serif", 10)
    app.setFont(font)
    setup_dark_fusion_palette(app)

    window = MainWindow()
    window.show()

    # Jos tiedosto annettiin komentorivillä, avataan se suoraan
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".pdf"):
        pdf_arg = os.path.abspath(sys.argv[1])
        if os.path.isfile(pdf_arg):
            window.open_file(pdf_arg)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
