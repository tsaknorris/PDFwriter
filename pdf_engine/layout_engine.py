"""
Asettelu- ja Geometriamoottori (Layout & Geometry Engine).
Vastaa tekstialkioiden perusviivojen (baseline) laskennasta (< 0.1 pt toleranssi),
ylivalunnan (overflow) tunnistamisesta ja viereisten elementtien törmäyksenestosta.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Tuple
import fitz


class FitStrategy(Enum):
    NATURAL = "natural"         # Säilyttää fonttikoon, voi pidentää aluetta
    AUTO_FIT = "auto_fit"       # Skaalaa fonttikokoa / välistystä mahtuakseen alkuperäiseen laatikkoon
    REFLOW = "reflow"           # Siirtää rivin seuraavia sanoja oikealle


@dataclass
class OverflowReport:
    """Tekstin pituuden ja asettelumuutoksen raportti."""
    original_text: str
    new_text: str
    original_width: float
    new_width: float
    delta_width: float
    percentage_change: float
    
    is_overflow: bool
    overflow_severity: str       # "none", "minor", "critical"
    collision_detected: bool
    collision_target: Optional[str]
    
    recommended_fontsize: float
    available_width: float
    message: str


class LayoutEngine:
    """
    Toteuttaa Gauntlet Loopin 'Asettelu- & Sisältövirtarakentajan'
    ja 'Sokea Geometria- & Juoksutuskriitikon' säännöt.
    """

    BASELINE_TOLERANCE_PT = 0.1  # Vaatimus: alle 0.1 pt poikkeama

    @classmethod
    def calculate_text_width(
        cls,
        text: str,
        fontsize: float,
        fontname: str = "helv",
        fontfile: Optional[str] = None
    ) -> float:
        """
        Laskee tekstin tarkan leveyden pisteinä (pt) PyMuPDF:n mittaustyökalulla.
        """
        if not text:
            return 0.0

        try:
            if fontfile:
                # Luodaan tilapäinen Font-olio tiedostosta tarkkaa metriikkaa varten
                f = fitz.Font(fontfile=fontfile)
                return f.text_length(text, fontsize=fontsize)
            else:
                return fitz.get_text_length(text, fontname=fontname, fontsize=fontsize)
        except Exception:
            # Fallback perusarvioon
            return fitz.get_text_length(text, fontname="helv", fontsize=fontsize)

    @classmethod
    def analyze_overflow(
        cls,
        span: Dict[str, Any],
        new_text: str,
        page: Optional[fitz.Page] = None,
        fontfile: Optional[str] = None,
        fontname: str = "helv"
    ) -> OverflowReport:
        """
        Tarkastaa, ylittääkö uusi teksti alkuperäisen alueen rajat,
        törmääkö se viereisiin sanoihin tai ylittääkö se sivumarginaalit.
        """
        bbox = span.get("bbox", (0, 0, 0, 0))
        orig_width = bbox[2] - bbox[0]
        fontsize = span.get("size", 10.0)
        orig_text = span.get("text", "")

        new_width = cls.calculate_text_width(
            new_text,
            fontsize=fontsize,
            fontname=fontname,
            fontfile=fontfile
        )

        delta = new_width - orig_width
        pct = (delta / orig_width * 100.0) if orig_width > 0 else 0.0

        collision_detected = False
        collision_target = None
        available_width = orig_width

        # Tarkistetaan sivun reunat ja viereiset elementit, jos sivu on annettu
        if page:
            page_width = page.rect.width
            origin_x = span.get("origin", (bbox[0], bbox[3]))[0]
            right_margin_gap = page_width - (origin_x + new_width)
            
            # Marginaalin ylitys
            if right_margin_gap < 15.0:  # Alle 15 pt sivun oikeasta reunasta
                collision_detected = True
                collision_target = "Sivun oikea marginaali"

            # Etsitään seuraava elementti samalta riviltä
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:
                    for line in block.get("lines", []):
                        for s in line.get("spans", []):
                            # Jos samalla vertikaalitasolla mutta oikealla puolella
                            s_bbox = s.get("bbox", (0, 0, 0, 0))
                            if s_bbox != bbox and abs(s_bbox[1] - bbox[1]) < 2.0:
                                if s_bbox[0] >= bbox[2] - 1.0:
                                    gap = s_bbox[0] - bbox[2]
                                    available_width = orig_width + gap
                                    if new_width > available_width:
                                        collision_detected = True
                                        collision_target = f"Seuraava tekstielementti '{s.get('text', '')[:10]}...'"
                                        break
                        if collision_detected:
                            break
                if collision_detected:
                    break

        # Luokitellaan ylivalunnan vakavuus
        if delta <= 0.5:
            severity = "none"
            is_overflow = False
            msg = "Teksti mahtuu alkuperäiseen tilaan."
        elif delta <= 10.0 and not collision_detected:
            severity = "minor"
            is_overflow = True
            msg = f"Teksti hieman aiempaa pidempi (+{delta:.1f} pt)."
        else:
            severity = "critical"
            is_overflow = True
            msg = f"Pidempi teksti (+{delta:.1f} pt)."

        # Suositeltu fonttikoko täydelliseen sovitukseen
        if new_width > 0 and orig_width > 0:
            scale_ratio = orig_width / new_width
            recommended_size = round(fontsize * min(1.0, scale_ratio), 2)
        else:
            recommended_size = fontsize

        return OverflowReport(
            original_text=orig_text,
            new_text=new_text,
            original_width=orig_width,
            new_width=new_width,
            delta_width=delta,
            percentage_change=pct,
            is_overflow=is_overflow,
            overflow_severity=severity,
            collision_detected=collision_detected,
            collision_target=collision_target,
            recommended_fontsize=recommended_size,
            available_width=available_width,
            message=msg
        )

    @classmethod
    def compute_fit_parameters(
        cls,
        span: Dict[str, Any],
        new_text: str,
        strategy: FitStrategy,
        fontfile: Optional[str] = None,
        fontname: str = "helv"
    ) -> Tuple[float, float, fitz.Point]:
        """
        Laskee lopullisen fonttikoon ja perusviivapisteen valitun FitStrategyn mukaan.
        Palauttaa: (font_size, horizontal_scale, origin_point)
        """
        orig_fontsize = span.get("size", 10.0)
        origin = fitz.Point(span.get("origin", (span["bbox"][0], span["bbox"][3])))
        bbox = span.get("bbox", (0, 0, 0, 0))
        orig_width = bbox[2] - bbox[0]

        if strategy == FitStrategy.NATURAL:
            return orig_fontsize, 1.0, origin

        elif strategy == FitStrategy.AUTO_FIT:
            current_width = cls.calculate_text_width(
                new_text,
                fontsize=orig_fontsize,
                fontname=fontname,
                fontfile=fontfile
            )
            if current_width > orig_width and orig_width > 0:
                scale = orig_width / current_width
                # Rajoitetaan kutistus enintään 70 %:iin esteettisen luettavuuden takaamiseksi
                scale = max(0.70, scale)
                adjusted_size = round(orig_fontsize * scale, 2)
                return adjusted_size, scale, origin
            return orig_fontsize, 1.0, origin

        elif strategy == FitStrategy.REFLOW:
            # Pidetään fonttikoko ennallaan, mutta siirtymä käsitellään rivitasolla
            return orig_fontsize, 1.0, origin

        return orig_fontsize, 1.0, origin
