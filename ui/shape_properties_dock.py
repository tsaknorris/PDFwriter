"""
Muotojen ja palikoiden ominaisuuspaneeli (Shape Properties Dock).
Mahdollistaa muototyökalujen (suorakulmio, pyöristetty laatikko, ympyrä, nuoli, viiva, tekstilaatikko) valinnan,
tason määrityksen (tekstin alle vs. tekstin päälle), värit, läpinäkyvyyden, reunaviivan, kulmapyöristyksen
sekä objektin sisäisen tekstin ja typografian (tasaus, fontti, koko, leikkaukset, väri).
"""

from typing import Optional, Tuple, Dict, Any, List
import math
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QStandardItemModel, QStandardItem
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QColorDialog, QDoubleSpinBox, QSlider, QRadioButton, QButtonGroup,
    QGroupBox, QCheckBox, QFrame, QPlainTextEdit, QComboBox, QScrollArea
)
from pdf_engine.font_resolver import FontconfigResolver


class ShapePropertiesDock(QWidget):
    """Graafisten muotojen ja tekstilaatikoiden ohjauspaneeli."""

    tool_changed = pyqtSignal(str)  # "move", "select", "textbox", "rect", "rounded_rect", "circle", "arrow", "line"
    properties_changed = pyqtSignal(dict)
    add_background_to_selection_requested = pyqtSignal()
    delete_shape_requested = pyqtSignal()
    font_manager_requested = pyqtSignal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.active_tool: str = "move"
        self.selected_shape_id: Optional[str] = None
        self._loading_properties: bool = False

        # Oletusvärit ja muoto-ominaisuudet
        self.has_fill: bool = True
        self.fill_rgb: Tuple[float, float, float] = (0.93, 0.95, 0.98)  # Pehmeä vaaleansininen
        self.fill_opacity: float = 0.85
        self.stroke_rgb: Tuple[float, float, float] = (0.2, 0.4, 0.7)    # Tummansininen reuna
        self.stroke_opacity: float = 1.0
        self.stroke_width: float = 1.5
        self.corner_radius: float = 8.0
        self.overlay: bool = False  # Oletuksena tekstin alle (Behind Text)!
        self.rotation: float = 0.0  # Vapaa kierto asteina (-360° .. 360°)

        # Teksti ja typografia
        self.shape_text: str = ""
        self.font_family: str = "Helvetica"
        self._doc_fonts: List[str] = []
        self.font_size: float = 14.0
        self.font_bold: bool = False
        self.font_italic: bool = False
        self.text_color_rgb: Tuple[float, float, float] = (0.0, 0.0, 0.0)
        self.text_align: str = "center"  # "left", "center", "right", "justify"
        self.vertical_align: str = "middle"  # "top", "middle", "bottom"

        # Pysyvät käyttäjän oletusasetukset uusille muodoille
        self.default_props: Dict[str, Any] = {
            "has_fill": self.has_fill,
            "fill_rgb": self.fill_rgb,
            "fill_opacity": self.fill_opacity,
            "stroke_rgb": self.stroke_rgb,
            "stroke_opacity": self.stroke_opacity,
            "stroke_width": self.stroke_width,
            "corner_radius": self.corner_radius,
            "overlay": self.overlay,
            "rotation": self.rotation,
            "shape_text": self.shape_text,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_bold": self.font_bold,
            "font_italic": self.font_italic,
            "text_color_rgb": self.text_color_rgb,
            "text_align": self.text_align,
            "vertical_align": self.vertical_align,
        }

        self._text_commit_timer = QTimer(self)
        self._text_commit_timer.setSingleShot(True)
        self._text_commit_timer.timeout.connect(lambda: self._emit_properties(commit_undo=True))

        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Kääriminen QScrollArea-alueeseen, jotta sivupalkkia voi aina vierittää vapaasti
        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.content_widget = QWidget()
        layout = QVBoxLayout(self.content_widget)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        # 0. Valintatilan indikaattori
        self.lbl_selection_status = QLabel("ℹ️ Uusien muotojen oletusasetukset")
        self.lbl_selection_status.setStyleSheet("color: #cbd5e1; font-size: 11px; padding: 2px;")
        layout.addWidget(self.lbl_selection_status)

        # 1. Työkalun valinta
        tool_group = QGroupBox("Työkalu")
        tool_layout = QVBoxLayout(tool_group)

        self.tool_button_group = QButtonGroup(self)
        self.btn_tool_select = QPushButton("🖐️ Siirtotyökalu / MOVE (V)")
        self.btn_tool_select.setToolTip("Siirrä, valitse ja muokkaa objekteja kankaalla (Pikanäppäin: V)")

        self.btn_tool_textbox = QPushButton("🔤 Tekstilaatikko (T)")
        self.btn_tool_textbox.setToolTip("Luo uusi tekstilaatikko dokumenttiin (Pikanäppäin: T)")

        self.btn_tool_rect = QPushButton("🔲 Suorakulmio (Laatikko)")
        self.btn_tool_round = QPushButton("🔲 Pyöristetty laatikko")
        self.btn_tool_circle = QPushButton("🔘 Ympyrä / Ellipsi")
        self.btn_tool_arrow = QPushButton("➔ Nuoli (Vapaa suunta)")
        self.btn_tool_line = QPushButton("━ Viiva")

        tools = [
            (self.btn_tool_select, "move"),
            (self.btn_tool_textbox, "textbox"),
            (self.btn_tool_rect, "rect"),
            (self.btn_tool_round, "rounded_rect"),
            (self.btn_tool_circle, "circle"),
            (self.btn_tool_arrow, "arrow"),
            (self.btn_tool_line, "line"),
        ]

        for idx, (btn, tool_id) in enumerate(tools):
            btn.setCheckable(True)
            btn.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: normal; background-color: #2a2a34; color: #f8fafc; border: 1px solid #4a4a58; border-radius: 3px;")
            self.tool_button_group.addButton(btn, idx)
            btn.clicked.connect(lambda checked, tid=tool_id: self._on_tool_clicked(tid))
            tool_layout.addWidget(btn)

        self.btn_tool_select.setChecked(True)
        self.btn_tool_select.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: bold; background-color: #0284c7; color: #ffffff; border: 1px solid #38bdf8; border-radius: 3px;")
        layout.addWidget(tool_group)

        # 2. Teksti ja Typografia (Objektin sisäinen teksti / Textbox)
        text_group = QGroupBox("🔤 Teksti ja Typografia (Valittu objekti / Textbox)")
        text_layout = QVBoxLayout(text_group)
        text_layout.setSpacing(6)

        # Tekstikenttä
        self.txt_shape_text = QPlainTextEdit()
        self.txt_shape_text.setPlaceholderText("Kirjoita teksti tähän... (esim. nimesi tai otsikko)")
        self.txt_shape_text.setFixedHeight(58)
        self.txt_shape_text.setStyleSheet(
            "background-color: #16161a; color: #f8fafc; border: 1px solid #4a4a58; border-radius: 3px; padding: 4px; font-size: 12px;"
        )
        self.txt_shape_text.textChanged.connect(self._on_text_changed)
        text_layout.addWidget(self.txt_shape_text)

        # Fonttiperhe ja Koko
        font_row = QHBoxLayout()
        font_row.addWidget(QLabel("Fontti:"))
        self.combo_font_family = QComboBox()
        self.combo_font_family.setEditable(True)
        self.update_available_fonts()
        self.combo_font_family.currentTextChanged.connect(self._on_font_family_changed)
        font_row.addWidget(self.combo_font_family, 2)

        self.btn_manage_fonts = QPushButton("🔤")
        self.btn_manage_fonts.setToolTip("Avaa kirjasinhallinta ja tutki dokumentin fontteja...")
        self.btn_manage_fonts.setFixedWidth(28)
        self.btn_manage_fonts.setStyleSheet("font-size: 13px; padding: 2px;")
        self.btn_manage_fonts.clicked.connect(self.font_manager_requested.emit)
        font_row.addWidget(self.btn_manage_fonts)

        font_row.addWidget(QLabel("Koko:"))
        self.spin_font_size = QDoubleSpinBox()
        self.spin_font_size.setRange(6.0, 120.0)
        self.spin_font_size.setSingleStep(1.0)
        self.spin_font_size.setValue(14.0)
        self.spin_font_size.setSuffix(" pt")
        self.spin_font_size.valueChanged.connect(self._on_font_size_changed)
        font_row.addWidget(self.spin_font_size, 1)
        text_layout.addLayout(font_row)

        # Tyylit (B, I) ja Väri
        style_color_row = QHBoxLayout()
        style_color_row.addWidget(QLabel("Tyyli:"))
        self.btn_text_bold = QPushButton("B")
        self.btn_text_bold.setCheckable(True)
        self.btn_text_bold.setFixedWidth(30)
        self.btn_text_bold.setStyleSheet("font-weight: bold; padding: 3px;")
        self.btn_text_bold.toggled.connect(self._on_bold_toggled)
        style_color_row.addWidget(self.btn_text_bold)

        self.btn_text_italic = QPushButton("I")
        self.btn_text_italic.setCheckable(True)
        self.btn_text_italic.setFixedWidth(30)
        self.btn_text_italic.setStyleSheet("font-style: italic; font-weight: bold; padding: 3px;")
        self.btn_text_italic.toggled.connect(self._on_italic_toggled)
        style_color_row.addWidget(self.btn_text_italic)

        style_color_row.addSpacing(6)
        style_color_row.addWidget(QLabel("Tekstin väri:"))
        self.btn_text_color = QPushButton()
        self.btn_text_color.setFixedWidth(45)
        self.btn_text_color.clicked.connect(self._pick_text_color)
        style_color_row.addWidget(self.btn_text_color)
        style_color_row.addStretch()
        text_layout.addLayout(style_color_row)

        # Vaakatasaus (Alignment)
        align_row = QHBoxLayout()
        align_row.addWidget(QLabel("Tasaus:"))
        self.align_button_group = QButtonGroup(self)
        self.btn_align_left = QPushButton("⯈|")
        self.btn_align_left.setToolTip("Vasen tasaus (Left)")
        self.btn_align_center = QPushButton("|⯈⯇|")
        self.btn_align_center.setToolTip("Keskitetty (Center)")
        self.btn_align_right = QPushButton("|⯇")
        self.btn_align_right.setToolTip("Oikea tasaus (Right)")
        self.btn_align_justify = QPushButton("|≡|")
        self.btn_align_justify.setToolTip("Tasattu molemmin puolin (Justify)")

        align_btns = [
            (self.btn_align_left, "left"),
            (self.btn_align_center, "center"),
            (self.btn_align_right, "right"),
            (self.btn_align_justify, "justify")
        ]
        for idx, (abtn, code) in enumerate(align_btns):
            abtn.setCheckable(True)
            abtn.setFixedWidth(34)
            abtn.setStyleSheet("font-weight: bold; padding: 3px;")
            self.align_button_group.addButton(abtn, idx)
            abtn.clicked.connect(lambda checked, c=code: self._on_align_clicked(c))
            align_row.addWidget(abtn)
        self.btn_align_center.setChecked(True)
        align_row.addStretch()
        text_layout.addLayout(align_row)

        # Pystytasaus (Vertical Alignment)
        valign_row = QHBoxLayout()
        valign_row.addWidget(QLabel("Pystytasaus:"))
        self.combo_valign = QComboBox()
        self.combo_valign.addItem("⬍ Keskellä (Middle)", "middle")
        self.combo_valign.addItem("⬆ Ylhäällä (Top)", "top")
        self.combo_valign.addItem("⬇ Alhaalla (Bottom)", "bottom")
        self.combo_valign.currentIndexChanged.connect(self._on_valign_changed)
        valign_row.addWidget(self.combo_valign)
        text_layout.addLayout(valign_row)

        layout.addWidget(text_group)

        # 3. Kierto & Kulma (Rotation)
        rot_group = QGroupBox("🔄 Kierto && Kulma (Rotation)")
        rot_layout = QVBoxLayout(rot_group)
        rot_layout.setSpacing(6)

        rot_row1 = QHBoxLayout()
        rot_row1.addWidget(QLabel("Kulma:"))
        self.spin_rotation = QDoubleSpinBox()
        self.spin_rotation.setRange(-360.0, 360.0)
        self.spin_rotation.setSingleStep(1.0)
        self.spin_rotation.setValue(0.0)
        self.spin_rotation.setSuffix("°")
        self.spin_rotation.valueChanged.connect(self._on_rotation_spin_changed)
        rot_row1.addWidget(self.spin_rotation, 1)

        self.slider_rotation = QSlider(Qt.Orientation.Horizontal)
        self.slider_rotation.setRange(-180, 180)
        self.slider_rotation.setValue(0)
        self.slider_rotation.valueChanged.connect(self._on_rotation_slider_changed)
        self.slider_rotation.sliderReleased.connect(lambda: self._emit_properties(commit_undo=True))
        rot_row1.addWidget(self.slider_rotation, 2)
        rot_layout.addLayout(rot_row1)

        # Pikapainikkeet
        rot_btn_row = QHBoxLayout()
        for deg in [0, 90, 180, 270]:
            btn_deg = QPushButton(f"{deg}°")
            btn_deg.setStyleSheet("padding: 2px 4px; font-size: 11px;")
            btn_deg.clicked.connect(lambda checked, d=deg: self.set_rotation(float(d)))
            rot_btn_row.addWidget(btn_deg)

        btn_ccw = QPushButton("↺ -15°")
        btn_ccw.setStyleSheet("padding: 2px 4px; font-size: 11px;")
        btn_ccw.clicked.connect(lambda: self.set_rotation(self.rotation - 15.0))
        rot_btn_row.addWidget(btn_ccw)

        btn_cw = QPushButton("↻ +15°")
        btn_cw.setStyleSheet("padding: 2px 4px; font-size: 11px;")
        btn_cw.clicked.connect(lambda: self.set_rotation(self.rotation + 15.0))
        rot_btn_row.addWidget(btn_cw)
        rot_layout.addLayout(rot_btn_row)

        layout.addWidget(rot_group)

        # 4. Taso (Z-Order: Tekstin alle vs. Tekstin päälle)
        layer_group = QGroupBox("Sijainti suhteessa tekstiin (Taso)")
        layer_layout = QVBoxLayout(layer_group)

        self.rb_behind = QRadioButton("🔽 Tekstin alle (Behind Text - Tausta)")
        self.rb_behind.setToolTip("Asettaa muodon olemassa olevan tekstin alle (suositus korostuksille ja taustoille).")
        self.rb_behind.setChecked(True)
        self.rb_behind.toggled.connect(self._on_layer_changed)

        self.rb_over = QRadioButton("🔼 Tekstin päälle (Over Text - Edusta)")
        self.rb_over.setToolTip("Asettaa muodon tekstin päälle (peittää tekstin tai luo läpikuultavan peitteen).")

        layer_layout.addWidget(self.rb_behind)
        layer_layout.addWidget(self.rb_over)
        layout.addWidget(layer_group)

        # 5. Värit & Läpinäkyvyys
        style_group = QGroupBox("Värit && Läpinäkyvyys")
        style_layout = QVBoxLayout(style_group)

        # Täyttöväri
        fill_row = QHBoxLayout()
        self.chk_fill = QCheckBox("Täyttö:")
        self.chk_fill.setChecked(True)
        self.chk_fill.toggled.connect(self._on_fill_toggled)
        fill_row.addWidget(self.chk_fill)

        self.btn_fill_color = QPushButton()
        self.btn_fill_color.setFixedWidth(50)
        self.btn_fill_color.clicked.connect(self._pick_fill_color)
        fill_row.addWidget(self.btn_fill_color)

        fill_row.addWidget(QLabel("Opasiteetti:"))
        self.slider_opacity = QSlider(Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(5, 100)
        self.slider_opacity.setValue(85)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        fill_row.addWidget(self.slider_opacity)

        self.lbl_opacity = QLabel("85 %")
        self.lbl_opacity.setFixedWidth(35)
        self.lbl_opacity.setStyleSheet("font-weight: bold; color: #38bdf8;")
        fill_row.addWidget(self.lbl_opacity)
        style_layout.addLayout(fill_row)

        # Reunaviivan väri ja paksuus
        stroke_row = QHBoxLayout()
        stroke_row.addWidget(QLabel("Reunaviiva:"))
        self.btn_stroke_color = QPushButton()
        self.btn_stroke_color.setFixedWidth(50)
        self.btn_stroke_color.clicked.connect(self._pick_stroke_color)
        stroke_row.addWidget(self.btn_stroke_color)

        stroke_row.addWidget(QLabel("Paksuus:"))
        self.spin_stroke_width = QDoubleSpinBox()
        self.spin_stroke_width.setRange(0.0, 30.0)
        self.spin_stroke_width.setSingleStep(0.5)
        self.spin_stroke_width.setValue(1.5)
        self.spin_stroke_width.setSuffix(" pt")
        self.spin_stroke_width.valueChanged.connect(self._on_stroke_width_changed)
        stroke_row.addWidget(self.spin_stroke_width)
        style_layout.addLayout(stroke_row)

        # Kulman pyöristyssäde
        radius_row = QHBoxLayout()
        radius_row.addWidget(QLabel("Kulman pyöristys:"))
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.0, 100.0)
        self.spin_radius.setSingleStep(1.0)
        self.spin_radius.setValue(8.0)
        self.spin_radius.setSuffix(" pt")
        self.spin_radius.valueChanged.connect(self._on_radius_changed)
        radius_row.addWidget(self.spin_radius)
        style_layout.addLayout(radius_row)

        layout.addWidget(style_group)

        # Toimintopainikkeet
        self.btn_add_bg_card = QPushButton("🟩 Lisää taustalaatikko valitulle tekstille")
        self.btn_add_bg_card.setStyleSheet(
            "background-color: #059669; color: white; font-weight: bold; padding: 6px; border-radius: 4px;"
        )
        self.btn_add_bg_card.setToolTip("Luo valitun tekstikappaleen alle kaunis taustakortti nykyisillä väreillä.")
        self.btn_add_bg_card.clicked.connect(self.add_background_to_selection_requested.emit)
        layout.addWidget(self.btn_add_bg_card)

        # 6. Valitun objektin poistaminen
        self.btn_delete_shape = QPushButton("🗑️ Poista valittu objekti (Delete)")
        self.btn_delete_shape.setStyleSheet(
            "background-color: #991b1b; color: white; font-weight: bold; padding: 6px; border-radius: 4px;"
        )
        self.btn_delete_shape.setToolTip("Poistaa valitun muodon sivulta (Pikanäppäin: Delete)")
        self.btn_delete_shape.setEnabled(False)
        self.btn_delete_shape.clicked.connect(self.delete_shape_requested.emit)
        layout.addWidget(self.btn_delete_shape)

        self.slider_opacity.sliderReleased.connect(lambda: self._emit_properties(commit_undo=True))

        layout.addStretch()
        self.scroll_area.setWidget(self.content_widget)
        main_layout.addWidget(self.scroll_area)
        self._update_color_buttons()

    def _update_color_buttons(self):
        r, g, b = self.fill_rgb
        hex_fill = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
        self.btn_fill_color.setStyleSheet(f"background-color: {hex_fill}; border: 1px solid #777; border-radius: 3px;")

        sr, sg, sb = self.stroke_rgb
        hex_stroke = f"#{int(sr*255):02x}{int(sg*255):02x}{int(sb*255):02x}"
        self.btn_stroke_color.setStyleSheet(f"background-color: {hex_stroke}; border: 1px solid #777; border-radius: 3px;")

        tr, tg, tb = self.text_color_rgb
        hex_text = f"#{int(tr*255):02x}{int(tg*255):02x}{int(tb*255):02x}"
        self.btn_text_color.setStyleSheet(f"background-color: {hex_text}; border: 1px solid #777; border-radius: 3px;")

    def _on_tool_clicked(self, tool_id: str):
        self.active_tool = "move" if tool_id in ("move", "select") else tool_id
        # Päivitetään painikkeiden ulkoasu
        buttons = [
            (self.btn_tool_select, "move"),
            (self.btn_tool_textbox, "textbox"),
            (self.btn_tool_rect, "rect"),
            (self.btn_tool_round, "rounded_rect"),
            (self.btn_tool_circle, "circle"),
            (self.btn_tool_arrow, "arrow"),
            (self.btn_tool_line, "line"),
        ]
        match_id = "move" if tool_id in ("move", "select") else tool_id
        for btn, tid in buttons:
            if tid == match_id:
                btn.setChecked(True)
                btn.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: bold; background-color: #0284c7; color: #ffffff; border: 1px solid #38bdf8; border-radius: 3px;")
            else:
                btn.setChecked(False)
                btn.setStyleSheet("text-align: left; padding: 4px 8px; font-weight: normal; background-color: #2a2a34; color: #f8fafc; border: 1px solid #4a4a58; border-radius: 3px;")

        if match_id == "textbox" and self.selected_shape_id is None:
            self.overlay = True
            self.rb_over.setChecked(True)
            self.default_props["overlay"] = True

        self.tool_changed.emit(self.active_tool)
        if self.selected_shape_id is None:
            self._emit_properties(commit_undo=False)

    def set_tool(self, tool_id: str):
        """Asettaa työkalun ohjelmallisesti."""
        self._on_tool_clicked(tool_id)

    def _apply_default_properties_to_controls(self):
        """Palauttaa kaikki säätimet ja muuttujat käyttäjän oletusasetuksiin."""
        p = self.default_props
        self.has_fill = p.get("has_fill", True)
        self.fill_rgb = p.get("fill_rgb", (0.93, 0.95, 0.98))
        self.fill_opacity = p.get("fill_opacity", 0.85)
        self.stroke_rgb = p.get("stroke_rgb", (0.2, 0.4, 0.7))
        self.stroke_opacity = p.get("stroke_opacity", 1.0)
        self.stroke_width = p.get("stroke_width", 1.5)
        self.corner_radius = p.get("corner_radius", 8.0)
        self.overlay = p.get("overlay", False)
        self.rotation = p.get("rotation", 0.0)

        self.shape_text = p.get("shape_text", "")
        self.font_family = p.get("font_family", "Helvetica")
        self.font_size = p.get("font_size", 14.0)
        self.font_bold = p.get("font_bold", False)
        self.font_italic = p.get("font_italic", False)
        self.text_color_rgb = p.get("text_color_rgb", (0.0, 0.0, 0.0))
        self.text_align = p.get("text_align", "center")
        self.vertical_align = p.get("vertical_align", "middle")

        self.chk_fill.blockSignals(True)
        self.chk_fill.setChecked(self.has_fill)
        self.btn_fill_color.setEnabled(self.has_fill)
        self.slider_opacity.setEnabled(self.has_fill)
        self.chk_fill.blockSignals(False)

        self.slider_opacity.blockSignals(True)
        self.slider_opacity.setValue(max(5, min(100, int(self.fill_opacity * 100))))
        self.lbl_opacity.setText(f"{int(self.fill_opacity * 100)} %")
        self.slider_opacity.blockSignals(False)

        self.spin_stroke_width.blockSignals(True)
        self.spin_stroke_width.setValue(self.stroke_width)
        self.spin_stroke_width.blockSignals(False)

        self.spin_radius.blockSignals(True)
        self.spin_radius.setValue(self.corner_radius)
        self.spin_radius.blockSignals(False)

        self.spin_rotation.blockSignals(True)
        self.slider_rotation.blockSignals(True)
        self.spin_rotation.setValue(self.rotation)
        self.slider_rotation.setValue(int(self.rotation))
        self.spin_rotation.blockSignals(False)
        self.slider_rotation.blockSignals(False)

        self.rb_behind.blockSignals(True)
        self.rb_over.blockSignals(True)
        if self.overlay:
            self.rb_over.setChecked(True)
        else:
            self.rb_behind.setChecked(True)
        self.rb_behind.blockSignals(False)
        self.rb_over.blockSignals(False)

        self.txt_shape_text.blockSignals(True)
        self.txt_shape_text.setPlainText(self.shape_text)
        self.txt_shape_text.blockSignals(False)

        self.combo_font_family.blockSignals(True)
        idx = self.combo_font_family.findText(self.font_family)
        if idx >= 0:
            self.combo_font_family.setCurrentIndex(idx)
        else:
            self.combo_font_family.setCurrentText(self.font_family)
        self.combo_font_family.blockSignals(False)

        self.spin_font_size.blockSignals(True)
        self.spin_font_size.setValue(self.font_size)
        self.spin_font_size.blockSignals(False)

        self.btn_text_bold.blockSignals(True)
        self.btn_text_bold.setChecked(self.font_bold)
        self.btn_text_bold.blockSignals(False)

        self.btn_text_italic.blockSignals(True)
        self.btn_text_italic.setChecked(self.font_italic)
        self.btn_text_italic.blockSignals(False)

        if self.text_align == "left":
            self.btn_align_left.setChecked(True)
        elif self.text_align == "right":
            self.btn_align_right.setChecked(True)
        elif self.text_align == "justify":
            self.btn_align_justify.setChecked(True)
        else:
            self.btn_align_center.setChecked(True)

        self.combo_valign.blockSignals(True)
        v_idx = self.combo_valign.findData(self.vertical_align)
        if v_idx >= 0:
            self.combo_valign.setCurrentIndex(v_idx)
        self.combo_valign.blockSignals(False)

        self._update_color_buttons()

    def update_available_fonts(self, doc_fonts: Optional[List[str]] = None):
        """
        Päivittää fonttivalikon sisällön:
        1. Dokumentin omat kirjasimet ryhmiteltynä ylös
        2. Standardikirjasimet ja asennetut paikalliset kirjasimet alas
        Säilyttää käyttäjän nykyisen valinnan tai valitsee dokumentin ensisijaisen fontin.
        """
        if doc_fonts is not None:
            self._doc_fonts = [f.strip() for f in doc_fonts if f and f.strip()]
        elif not hasattr(self, "_doc_fonts"):
            self._doc_fonts = []

        current_selection = self.combo_font_family.currentText().strip() if hasattr(self, "combo_font_family") else ""
        if hasattr(self, "combo_font_family"):
            self.combo_font_family.blockSignals(True)

        model = QStandardItemModel()

        # 1. Dokumentin fontit
        if self._doc_fonts:
            h1 = QStandardItem("── Dokumentin fontit ──")
            h1.setEnabled(False)
            h1.setForeground(QColor("#94a3b8"))
            model.appendRow(h1)

            for f in self._doc_fonts:
                it = QStandardItem(f)
                model.appendRow(it)

        # 2. Standardi- ja järjestelmäfontit
        h2 = QStandardItem("── Standardikirjasimet ──")
        h2.setEnabled(False)
        h2.setForeground(QColor("#94a3b8"))
        model.appendRow(h2)

        standard_list = ["Helvetica", "Times New Roman", "Courier", "Arial", "Liberation Sans", "DejaVu Sans"]

        # Haetaan lisäksi lokaalit asennetut/puretut käyttäjäfontit
        try:
            user_fonts = FontconfigResolver.scan_local_user_fonts()
            for flist in user_fonts.values():
                for item in flist:
                    fam = item.get("clean_family")
                    if fam and fam not in standard_list and fam not in self._doc_fonts:
                        standard_list.append(fam)
        except Exception:
            pass

        for f in standard_list:
            it = QStandardItem(f)
            model.appendRow(it)

        if hasattr(self, "combo_font_family"):
            self.combo_font_family.setModel(model)

            target = current_selection or self.font_family
            if not target or target.startswith("──"):
                target = self._doc_fonts[0] if self._doc_fonts else "Helvetica"

            idx = self.combo_font_family.findText(target)
            if idx >= 0:
                self.combo_font_family.setCurrentIndex(idx)
            else:
                self.combo_font_family.setEditText(target)

            self.combo_font_family.blockSignals(False)

    def load_shape_properties(self, shape_data: Optional[Dict[str, Any]]):
        """Lataa valitun muodon ominaisuudet säätimiin reaaliaikaista editointia varten."""
        self._loading_properties = True
        try:
            if not shape_data or not shape_data.get("id"):
                self.selected_shape_id = None
                self.lbl_selection_status.setText("ℹ️ Uusien muotojen oletusasetukset")
                self.lbl_selection_status.setStyleSheet("color: #cbd5e1; font-size: 11px; padding: 2px;")
                self.btn_delete_shape.setEnabled(False)
                self._apply_default_properties_to_controls()
                return

            self.selected_shape_id = shape_data.get("id")
            s_name = shape_data.get("name") or shape_data.get("id")
            self.lbl_selection_status.setText(f"📌 Muokataan: {s_name}")
            self.lbl_selection_status.setStyleSheet("color: #4ade80; font-weight: bold; font-size: 11px; padding: 2px;")
            self.btn_delete_shape.setEnabled(True)

            # Kierto
            self.rotation = float(shape_data.get("rotation", 0.0))
            self.spin_rotation.blockSignals(True)
            self.slider_rotation.blockSignals(True)
            self.spin_rotation.setValue(self.rotation)
            self.slider_rotation.setValue(int(self.rotation))
            self.spin_rotation.blockSignals(False)
            self.slider_rotation.blockSignals(False)

            # Opasiteetti (fill_opacity tai nuolella/viivalla stroke_opacity)
            f_op = shape_data.get("fill_opacity", 1.0)
            if shape_data.get("type") in ("arrow", "line") and shape_data.get("fill_color") is None:
                f_op = shape_data.get("stroke_opacity", 1.0)
            self.fill_opacity = float(f_op)
            self.slider_opacity.setValue(max(5, min(100, int(self.fill_opacity * 100))))
            self.lbl_opacity.setText(f"{int(self.fill_opacity * 100)} %")

            # Täyttöväri
            fc = shape_data.get("fill_color")
            if fc is not None:
                self.has_fill = True
                self.chk_fill.setChecked(True)
                self.fill_rgb = (float(fc[0]), float(fc[1]), float(fc[2]))
            else:
                self.has_fill = False
                self.chk_fill.setChecked(False)

            # Reunaviivan väri ja paksuus
            sc = shape_data.get("stroke_color")
            if sc is not None:
                self.stroke_rgb = (float(sc[0]), float(sc[1]), float(sc[2]))
            self.stroke_width = float(shape_data.get("stroke_width", 1.5))
            self.spin_stroke_width.setValue(self.stroke_width)

            # Pyöristys
            rad = shape_data.get("radius")
            if rad is not None:
                self.corner_radius = float(rad)
                self.spin_radius.setValue(self.corner_radius)

            # Taso (Behind Text vs Over Text)
            ov = shape_data.get("overlay", True)
            self.overlay = ov
            if ov:
                self.rb_over.setChecked(True)
            else:
                self.rb_behind.setChecked(True)

            # Tekstiominaisuudet
            new_text = shape_data.get("text", "")
            self.shape_text = new_text
            if self.txt_shape_text.toPlainText() != new_text:
                cursor = self.txt_shape_text.textCursor()
                old_pos = cursor.position()
                self.txt_shape_text.setPlainText(new_text)
                cursor.setPosition(min(old_pos, len(new_text)))
                self.txt_shape_text.setTextCursor(cursor)

            self.font_family = shape_data.get("font_family", "Helvetica")
            idx = self.combo_font_family.findText(self.font_family)
            if idx >= 0:
                self.combo_font_family.setCurrentIndex(idx)
            else:
                self.combo_font_family.setCurrentText(self.font_family)

            self.font_size = float(shape_data.get("font_size", 14.0))
            self.spin_font_size.setValue(self.font_size)

            self.font_bold = bool(shape_data.get("font_bold", False))
            self.btn_text_bold.setChecked(self.font_bold)

            self.font_italic = bool(shape_data.get("font_italic", False))
            self.btn_text_italic.setChecked(self.font_italic)

            tc = shape_data.get("text_color", (0.0, 0.0, 0.0))
            self.text_color_rgb = (float(tc[0]), float(tc[1]), float(tc[2]))

            t_align = shape_data.get("text_align", "center")
            self.text_align = t_align
            if t_align == "left":
                self.btn_align_left.setChecked(True)
            elif t_align == "right":
                self.btn_align_right.setChecked(True)
            elif t_align == "justify":
                self.btn_align_justify.setChecked(True)
            else:
                self.btn_align_center.setChecked(True)

            v_align = shape_data.get("vertical_align", "middle")
            self.vertical_align = v_align
            v_idx = self.combo_valign.findData(v_align)
            if v_idx >= 0:
                self.combo_valign.setCurrentIndex(v_idx)

            self._update_color_buttons()
        finally:
            self._loading_properties = False
            if self.selected_shape_id is None:
                self._emit_properties(commit_undo=False)

    def _on_text_changed(self):
        if self._loading_properties:
            return
        self.shape_text = self.txt_shape_text.toPlainText()
        if self.selected_shape_id is None:
            self.default_props["shape_text"] = self.shape_text
        self._emit_properties(commit_undo=False)
        self._text_commit_timer.start(400)

    def _on_font_family_changed(self, text: str):
        if self._loading_properties:
            return
        clean_text = (text or "").strip()
        if not clean_text or clean_text.startswith("──") or clean_text.startswith("---"):
            return
        self.font_family = clean_text
        self.default_props["font_family"] = clean_text
        self._emit_properties(commit_undo=True)

    def _on_font_size_changed(self, val: float):
        if self._loading_properties:
            return
        self.font_size = val
        self.default_props["font_size"] = val
        self._emit_properties(commit_undo=True)

    def _on_bold_toggled(self, checked: bool):
        if self._loading_properties:
            return
        self.font_bold = checked
        self.default_props["font_bold"] = checked
        self._emit_properties(commit_undo=True)

    def _on_italic_toggled(self, checked: bool):
        if self._loading_properties:
            return
        self.font_italic = checked
        self.default_props["font_italic"] = checked
        self._emit_properties(commit_undo=True)

    def _pick_text_color(self):
        cur = QColor(int(self.text_color_rgb[0]*255), int(self.text_color_rgb[1]*255), int(self.text_color_rgb[2]*255))
        c = QColorDialog.getColor(cur, self, "Valitse tekstin väri")
        if c.isValid():
            self.text_color_rgb = (c.redF(), c.greenF(), c.blueF())
            self.default_props["text_color_rgb"] = self.text_color_rgb
            self._update_color_buttons()
            self._emit_properties(commit_undo=True)

    def _on_align_clicked(self, align_code: str):
        if self._loading_properties:
            return
        self.text_align = align_code
        self.default_props["text_align"] = align_code
        self._emit_properties(commit_undo=True)

    def _on_valign_changed(self, idx: int):
        if self._loading_properties:
            return
        data = self.combo_valign.currentData()
        if data:
            self.vertical_align = data
            self.default_props["vertical_align"] = data
            self._emit_properties(commit_undo=True)

    def _on_layer_changed(self):
        if self._loading_properties:
            return
        self.overlay = self.rb_over.isChecked()
        self.default_props["overlay"] = self.overlay
        self._emit_properties(commit_undo=True)

    def _on_fill_toggled(self, checked: bool):
        if self._loading_properties:
            return
        self.has_fill = checked
        self.default_props["has_fill"] = checked
        self.btn_fill_color.setEnabled(checked)
        self.slider_opacity.setEnabled(checked)
        self._emit_properties(commit_undo=True)

    def _pick_fill_color(self):
        cur = QColor(int(self.fill_rgb[0]*255), int(self.fill_rgb[1]*255), int(self.fill_rgb[2]*255))
        c = QColorDialog.getColor(cur, self, "Valitse täyttöväri")
        if c.isValid():
            self.fill_rgb = (c.redF(), c.greenF(), c.blueF())
            self.default_props["fill_rgb"] = self.fill_rgb
            self._update_color_buttons()
            self._emit_properties(commit_undo=True)

    def _pick_stroke_color(self):
        cur = QColor(int(self.stroke_rgb[0]*255), int(self.stroke_rgb[1]*255), int(self.stroke_rgb[2]*255))
        c = QColorDialog.getColor(cur, self, "Valitse reunaviivan väri")
        if c.isValid():
            self.stroke_rgb = (c.redF(), c.greenF(), c.blueF())
            self.default_props["stroke_rgb"] = self.stroke_rgb
            self._update_color_buttons()
            self._emit_properties(commit_undo=True)

    def _on_opacity_changed(self, val: int):
        if self._loading_properties:
            return
        self.fill_opacity = val / 100.0
        self.lbl_opacity.setText(f"{val} %")
        self.default_props["fill_opacity"] = self.fill_opacity
        self._emit_properties(commit_undo=False)

    def _on_stroke_width_changed(self, val: float):
        if self._loading_properties:
            return
        self.stroke_width = val
        self.default_props["stroke_width"] = val
        self._emit_properties(commit_undo=True)

    def _on_radius_changed(self, val: float):
        if self._loading_properties:
            return
        self.corner_radius = val
        self.default_props["corner_radius"] = val
        self._emit_properties(commit_undo=True)

    def set_rotation(self, deg: float):
        """Asettaa kiertokulman ohjelmallisesti tai pikapainikkeista."""
        while deg > 180.0:
            deg -= 360.0
        while deg < -180.0:
            deg += 360.0
        self.rotation = deg
        self.default_props["rotation"] = deg
        self.spin_rotation.blockSignals(True)
        self.slider_rotation.blockSignals(True)
        self.spin_rotation.setValue(deg)
        self.slider_rotation.setValue(int(deg))
        self.spin_rotation.blockSignals(False)
        self.slider_rotation.blockSignals(False)
        self._emit_properties(commit_undo=True)

    def _on_rotation_spin_changed(self, val: float):
        if self._loading_properties:
            return
        self.rotation = val
        self.default_props["rotation"] = val
        self.slider_rotation.blockSignals(True)
        self.slider_rotation.setValue(int(val))
        self.slider_rotation.blockSignals(False)
        self._emit_properties(commit_undo=True)

    def _on_rotation_slider_changed(self, val: int):
        if self._loading_properties:
            return
        self.rotation = float(val)
        self.default_props["rotation"] = self.rotation
        self.spin_rotation.blockSignals(True)
        self.spin_rotation.setValue(self.rotation)
        self.spin_rotation.blockSignals(False)
        self._emit_properties(commit_undo=False)

    def _emit_properties(self, commit_undo: bool = True):
        if self._loading_properties:
            return
        props = self.get_current_properties()
        props["commit_undo"] = commit_undo
        props["target_shape_id"] = self.selected_shape_id
        self.properties_changed.emit(props)

    def get_current_properties(self) -> Dict[str, Any]:
        return {
            "tool": self.active_tool,
            "has_fill": self.has_fill,
            "fill_color": self.fill_rgb if self.has_fill else None,
            "fill_opacity": self.fill_opacity,
            "stroke_color": self.stroke_rgb,
            "stroke_opacity": self.stroke_opacity,
            "stroke_width": self.stroke_width,
            "radius": self.corner_radius,
            "overlay": self.overlay,
            "rotation": self.rotation,
            "text": self.shape_text,
            "font_family": self.font_family,
            "font_size": self.font_size,
            "font_bold": self.font_bold,
            "font_italic": self.font_italic,
            "text_color": self.text_color_rgb,
            "text_align": self.text_align,
            "vertical_align": self.vertical_align,
        }
