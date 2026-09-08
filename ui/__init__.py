"""
UI-moduulit Acrobat-tason Linux-PDF-editorille.
"""

from .page_canvas import PDFPageCanvas
from .inspector_panel import InspectorPanel
from .text_editor_dock import TextEditorDock
from .thumbnails_bar import ThumbnailsBar
from .font_manager_dialog import FontManagerDialog
from .main_window import MainWindow

__all__ = [
    "PDFPageCanvas",
    "InspectorPanel",
    "TextEditorDock",
    "ThumbnailsBar",
    "FontManagerDialog",
    "MainWindow",
]

