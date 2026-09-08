"""
Diagnostic script to test sidebar setting persistence and shape color updates.
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

app = QApplication.instance() or QApplication(sys.argv)

test_pdf = "/tmp/test_diag.pdf"
doc = fitz.open()
doc.new_page(width=600, height=800)
doc.save(test_pdf)
doc.close()

win = MainWindow()
win.open_file(test_pdf)

print("--- Test 1: Change sidebar stroke color when no shape is selected ---")
win.shape_widget.stroke_rgb = (1.0, 0.0, 0.0) # Red
win.shape_widget._update_color_buttons()
win.shape_widget._emit_properties(commit_undo=True)

print("Canvas shape_stroke_color:", win.canvas.shape_stroke_color)
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)

# Now draw a rect
win.canvas.active_tool = "rect"
# Simulate drawing
win.canvas.shape_start_pos = QPointF(50, 50)
from PyQt6.QtCore import QPointF
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtCore import Qt, QEvent

# Simulate mouse release after drawing rect
e = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(200, 200), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
win.canvas.is_drawing_shape = True
win.canvas.mouseReleaseEvent(e)

shapes = win.doc_model.page_shapes.get(0, [])
print("Shapes on page:", len(shapes))
if shapes:
    print("Shape 0 stroke_color:", shapes[0].get("stroke_color"))
    print("Dock selected_shape_id:", win.shape_widget.selected_shape_id)
    print("Dock stroke_rgb after drawing:", win.shape_widget.stroke_rgb)

# Now draw a textbox!
print("\n--- Test 2: Set stroke color to green, and draw a textbox ---")
win.shape_widget.stroke_rgb = (0.0, 1.0, 0.0) # Green
win.shape_widget._update_color_buttons()
win.shape_widget._emit_properties(commit_undo=True)
win.canvas.active_tool = "textbox"
win.canvas.shape_start_pos = QPointF(50, 300)
win.canvas.is_drawing_shape = True
e2 = QMouseEvent(QEvent.Type.MouseButtonRelease, QPointF(250, 400), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
win.canvas.mouseReleaseEvent(e2)

shapes = win.doc_model.page_shapes.get(0, [])
print("Shapes on page now:", len(shapes))
if len(shapes) > 1:
    print("Shape 1 (textbox) stroke_color:", shapes[1].get("stroke_color"))
    print("Dock stroke_rgb after textbox drawing:", win.shape_widget.stroke_rgb)

print("\n--- Test 3: Select Shape 0 and change its stroke color via dock ---")
win.canvas.select_shape(shapes[0]["id"])
print("Dock stroke_rgb after selecting Shape 0:", win.shape_widget.stroke_rgb)
# Change stroke color in dock to purple (0.5, 0.0, 0.5)
win.shape_widget.stroke_rgb = (0.5, 0.0, 0.5)
win.shape_widget._update_color_buttons()
win.shape_widget._emit_properties(commit_undo=True)
shape0_now = win.doc_model.get_shape(0, shapes[0]["id"])
print("Shape 0 stroke_color in doc_model after edit:", shape0_now.get("stroke_color"))
print("Dock stroke_rgb:", win.shape_widget.stroke_rgb)

win.close()
if os.path.exists(test_pdf):
    os.remove(test_pdf)
