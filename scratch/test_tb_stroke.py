"""
Test updating an existing textbox's stroke_color and see what happens on canvas and in dock.
"""
import os
import sys

sys.path.insert(0, "/home/mika/Desktop/diudiu/PDFwriter")

os.environ["QT_NO_NETWORK"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

import fitz
from PyQt6.QtWidgets import QApplication
from ui.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)

test_pdf = "/tmp/test_tb_stroke.pdf"
doc = fitz.open()
doc.new_page(width=600, height=800)
doc.save(test_pdf)
doc.close()

win = MainWindow()
win.open_file(test_pdf)

# 1. Create a textbox
tb_id = win.doc_model.draw_shape(
    page_idx=0,
    shape_type="textbox",
    geometry=(100, 100, 300, 200),
    stroke_color=(0.2, 0.4, 0.7),
    stroke_width=1.5,
    text="Testi",
    rotation=0.0
)
win.canvas.select_shape(tb_id)
print("Initial textbox in doc_model:", win.doc_model.get_shape(0, tb_id))
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)
print("Dock selected_shape_id:", win.shape_widget.selected_shape_id)

# 2. User changes stroke_color in dock to Red (1.0, 0.0, 0.0)
win.shape_widget.stroke_rgb = (1.0, 0.0, 0.0)
win.shape_widget._update_color_buttons()
win.shape_widget._emit_properties(commit_undo=True)

print("\nAfter changing dock stroke_rgb to Red:")
print("Textbox in doc_model:", win.doc_model.get_shape(0, tb_id).get("stroke_color"))
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)

# 3. What if user types in the inline editor or clicks canvas?
# In inline editor:
win.canvas.start_inline_shape_editor(tb_id)
win.canvas.inline_shape_editor.insertPlainText("lisäys ")
# This calls _on_inline_shape_text_changed
print("\nAfter typing in inline editor:")
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)

# 4. What if finish_inline_shape_editor runs?
win.canvas.finish_inline_shape_editor(commit=True)
print("\nAfter finish_inline_shape_editor:")
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)

win.close()
if os.path.exists(test_pdf):
    os.remove(test_pdf)
