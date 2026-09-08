"""
Fontti- ja Enkoodausratkaisija (Font & Encoding Resolver).
Hoitaa PDF-fonttisanakirjojen purun, subset-etuliitteiden poiston,
upotetun kirjasimen TTFont-cmap -tarkastuksen sekä järjestelmän
Fontconfig-alijärjestelmän lokaalin mäppäyksen ilman verkkokutsuja.
"""

import os
import re
import io
import subprocess
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Set, Dict, Any

import fitz
from fontTools.ttLib import TTFont


@dataclass
class FontMatchResult:
    """Yksityiskohtainen fonttitutkimuksen ja mäppäyksen tulos."""
    original_font_name: str
    clean_family: str
    is_subset: bool
    is_bold: bool = False
    is_italic: bool = False
    
    # Upotetun fontin tiedot
    embedded_extracted: bool = False
    embedded_ext: Optional[str] = None
    embedded_buffer: Optional[bytes] = None
    embedded_missing_glyphs: List[str] = field(default_factory=list)
    can_use_embedded: bool = False

    # Järjestelmän lokaalin fontin tiedot
    local_font_path: Optional[str] = None
    local_font_family: Optional[str] = None
    local_missing_glyphs: List[str] = field(default_factory=list)
    can_use_local: bool = False

    # Lopullinen valinta
    effective_font_path: Optional[str] = None
    effective_font_name: Optional[str] = None
    status_summary: str = ""
    effective_is_bold: bool = False
    effective_is_italic: bool = False
    needs_faux_bold: bool = False


LOCAL_FONTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fonts")
os.makedirs(LOCAL_FONTS_DIR, exist_ok=True)


class FontconfigResolver:
    """
    Linux Fontconfig- ja fontTools-integraatio.
    Toteuttaa Gauntlet Loopin 'Fontti- & Enkoodausrakentajan' vaatimukset.
    """

    SUBSET_PREFIX_REGEX = re.compile(r"^[A-Z]{6}\+(.+)$")
    
    # Standard 14 PDF fonts fallback mapping
    STANDARD_FALLBACKS = {
        "helvetica": "Liberation Sans",
        "arial": "Liberation Sans",
        "times": "Liberation Serif",
        "timesnewroman": "Liberation Serif",
        "courier": "Liberation Mono",
        "couriernew": "Liberation Mono",
        "symbol": "DejaVu Sans",
        "zapfdingbats": "DejaVu Sans",
    }

    # Avointen vastineiden korvauskartta (Kaupallinen/puuttuva fontti -> asennettava avoin vastine)
    FAMILY_SUBSTITUTIONS = {
        # Stone Sans
        "stonesans": "ptsans",
        "stonesansstd": "ptsans",
        "stonesansstdsemibold": "ptsans",
        "stonesansstdbold": "ptsans",
        "stonesansstdmedium": "ptsans",
        # Stone Serif
        "stoneserif": "crimsonpro",
        "stoneserifstd": "crimsonpro",
        "itcstoneserif": "crimsonpro",
        "itcstoneserifstd": "crimsonpro",
        "itcstoneserifstdan": "crimsonpro",
        "itcstoneserifstdmedium": "crimsonpro",
        "itcstoneserifstdbold": "crimsonpro",
        "itcstoneserifstdmediumit": "crimsonpro",
        "itcstoneserifstdmediumitalic": "crimsonpro",
        # Muut yleiset erikoisjulkaisufontit
        "minion": "crimsonpro",
        "minionpro": "crimsonpro",
        "mercury": "merriweather",
        "mercurytext": "merriweather",
        "din": "barlow",
        "dinalternate": "barlow",
        "applechancery": "greatvibes",
        "calibri": "inter",
        "georgia": "merriweather",
        "garamond": "ebgaramond",
        "futura": "montserrat",
        "baskerville": "crimsonpro",
        "palatino": "merriweather",
    }

    _user_fonts_cache: Optional[Dict[str, Dict[str, Any]]] = None

    @classmethod
    def get_substitute_family(cls, family_name: str) -> Optional[str]:
        """Etsii ja palauttaa annetun fonttiperheen suositellun avoimen vastineen tunnisteen."""
        norm_k = re.sub(r"[^a-zA-Z0-9]", "", family_name).lower()
        if norm_k in cls.FAMILY_SUBSTITUTIONS:
            return cls.FAMILY_SUBSTITUTIONS[norm_k]
        for k, v in cls.FAMILY_SUBSTITUTIONS.items():
            if k in norm_k or norm_k in k:
                return v
        rec_desc, rec_id = FontDownloader.get_recommendation(family_name)
        if rec_id:
            return rec_id
        return None

    _user_fonts_cache: Optional[Dict[str, List[Dict[str, Any]]]] = None

    @classmethod
    def scan_local_user_fonts(cls, force_reload: bool = False) -> Dict[str, List[Dict[str, Any]]]:
        """
        Skannaa sovelluksen fonts/-kansion ja käyttäjän fonttihakemiston (.ttf ja .otf).
        Palauttaa sanakirjan: {puhdistettu_perhe: [{'path': ..., 'clean_family': ..., 'bold': ..., 'italic': ...}, ...]}
        """
        if cls._user_fonts_cache is not None and not force_reload:
            return cls._user_fonts_cache

        fonts: Dict[str, List[Dict[str, Any]]] = {}
        search_dirs = [LOCAL_FONTS_DIR, os.path.expanduser("~/.local/share/fonts")]
        for sdir in search_dirs:
            if not os.path.isdir(sdir):
                continue
            for root, _, files in os.walk(sdir):
                for fname in files:
                    if fname.lower().endswith((".ttf", ".otf")):
                        fpath = os.path.join(root, fname)
                        base_stem = os.path.splitext(fname)[0]
                        clean_fam, _, is_b, is_it = cls.clean_font_name(base_stem)
                        norm_k = re.sub(r"[^a-zA-Z0-9]", "", clean_fam).lower()
                        entry = {
                            "path": fpath,
                            "clean_family": clean_fam,
                            "filename": fname,
                            "is_bold": is_b,
                            "is_italic": is_it
                        }
                        if norm_k not in fonts:
                            fonts[norm_k] = []
                        fonts[norm_k].append(entry)
        cls._user_fonts_cache = fonts
        return fonts

    @classmethod
    def clean_font_name(cls, pdf_font_name: str) -> Tuple[str, bool, bool, bool]:
        """
        Puhdistaa PDF-fonttinimen:
        1. Erottaa 6-kirjaimisen subset-etuliitteen (esim. 'BAAAAA+TimesNewRomanPSMT')
        2. Tunnistaa leikkaukset (Bold, Italic, Oblique, Semibold)
        Palauttaa: (puhdistettu_perhe, on_subset, on_bold, on_italic)
        """
        is_subset = False
        name = pdf_font_name.strip()
        
        match = cls.SUBSET_PREFIX_REGEX.match(name)
        if match:
            is_subset = True
            name = match.group(1)

        # Tunnistetaan leikkaukset nimestä
        is_bold = bool(re.search(r"[-_, ]*(bold|black|heavy|semibold|demibold)", name, re.IGNORECASE))
        is_italic = bool(re.search(r"[-_, ]*(italic|oblique|slanted)", name, re.IGNORECASE))

        # Standardoidaan tunnetut perheet ensin
        known = {
            "itcstoneserifstdan": "ITC Stone Serif Std",
            "itcstoneserif": "ITC Stone Serif",
            "stonesansstd": "Stone Sans Std",
            "stoneserifstd": "Stone Serif Std",
            "stonesans": "Stone Sans",
            "stoneserif": "Stone Serif",
            "timesnewromanpsmt": "Times New Roman",
            "timesnewromanps": "Times New Roman",
            "timesnewroman": "Times New Roman",
            "timesroman": "Times",
            "arialmt": "Arial",
            "arial": "Arial",
            "helveticaneue": "Helvetica Neue",
            "helvetica": "Helvetica",
            "symbolstd": "Symbol",
            "symbol": "Symbol",
            "minionpro": "Minion Pro",
            "myriadpro": "Myriad Pro",
        }

        k = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
        k_base = re.sub(r"(semibolditalic|semibold|demibold|mediumital|mediumitalic|italic|oblique|slanted|bold|black|heavy|regular|medium|roman|light)$", "", k)
        if k_base in known:
            return known[k_base], is_subset, is_bold, is_italic
        if k in known:
            return known[k], is_subset, is_bold, is_italic

        # Yleinen tyylipäätteiden poisto
        style_pattern = r"[-_, ]*(?:semibold|demibold|semi|demi|bold|italic|oblique|slanted|black|heavy|regular|mediumital|mediumitalic|medium|roman|light|ultralight|book|psmt|mt|ps|std)$"
        clean = name
        for _ in range(4):
            new_clean = re.sub(style_pattern, "", clean, flags=re.IGNORECASE).strip(" -_,")
            if new_clean == clean:
                break
            clean = new_clean

        if not clean:
            clean = name

        return clean, is_subset, is_bold, is_italic

    @staticmethod
    def get_font_cmap_coverage(font_buffer: bytes) -> Set[int]:
        """
        Lukee TrueType/OpenType/CFF/Type1 -fonttidatasta kaikki tuetut Unicode-koodipisteet.
        Käyttää ensisijaisesti PyMuPDF:n fitz.Font -oliota (valid_codepoints), joka tukee
        kaikkia PDF-kirjasinformaatteja (TTF, OTF, CFF, Type1), ja toissijaisesti fontToolsia.
        """
        codepoints = set()
        if not font_buffer:
            return codepoints

        # 1. Ensisijainen: fitz.Font valid_codepoints()
        try:
            ff = fitz.Font(fontbuffer=font_buffer)
            vc = ff.valid_codepoints()
            if vc:
                codepoints.update(vc)
                return codepoints
        except Exception:
            pass

        # 2. Toissijainen: fontTools TTFont
        try:
            with io.BytesIO(font_buffer) as bio:
                tt = TTFont(bio)
                if "cmap" in tt:
                    for table in tt["cmap"].tables:
                        if table.isUnicode():
                            codepoints.update(table.cmap.keys())
                tt.close()
        except Exception:
            pass
        return codepoints

    @classmethod
    def check_text_in_cmap(cls, text: str, cmap_codepoints: Set[int]) -> List[str]:
        """
        Palauttaa listan näkyvistä merkeistä, joita ei löydy annetusta Unicode-koodipistejoukosta.
        Ohittaa kaikki Unicode-tyhjätilat (isspace), muotoilumerkit ja pehmeät tavuviivat.
        """
        import unicodedata
        missing = []
        for ch in text:
            # Ohitetaan kaikki Unicode-tyhjätilat (välilyönti, thin space \u2006, em-space jne.)
            if ch.isspace():
                continue
            # Ohitetaan näkymättömät muotoilumerkit (format/control: soft hyphen \xad, zero-width space jne.)
            cat = unicodedata.category(ch)
            if cat in ("Cf", "Cc", "Zs", "Zl", "Zp"):
                continue
            if ord(ch) not in cmap_codepoints:
                missing.append(ch)
        return missing

    @classmethod
    def resolve_local_font(cls, family_query: str, bold: bool = False, italic: bool = False) -> Tuple[Optional[str], Optional[str]]:
        """
        Kysyy ensin sovelluksen ja käyttäjän fonttihakemistoista (fonts/),
        ottaen huomioon leikkauksen (bold, italic),
        ja sen jälkeen Linuxin paikalliselta Fontconfig-alijärjestelmältä ('fc-match').
        """
        norm_q = re.sub(r"[^a-zA-Z0-9]", "", family_query).lower()
        user_fonts = cls.scan_local_user_fonts()
        
        candidates: List[Dict[str, Any]] = []
        if norm_q in user_fonts:
            candidates.extend(user_fonts[norm_q])
        else:
            for k, flist in user_fonts.items():
                if norm_q in k or k in norm_q:
                    candidates.extend(flist)

        # Tarkistetaan onko tälle perheelle asennettu avoin vastine (esim. Crimson Pro -> Stone Serif, PT Sans -> Stone Sans)
        sub_key = cls.get_substitute_family(family_query)
        if sub_key:
            norm_sub = re.sub(r"[^a-zA-Z0-9]", "", sub_key).lower()
            if norm_sub in user_fonts:
                candidates.extend(user_fonts[norm_sub])
            else:
                for k, flist in user_fonts.items():
                    if norm_sub in k or k in norm_sub:
                        candidates.extend(flist)

        # Valitaan paras leikkaus ehdokkaista
        if candidates:
            # 1. Täydellinen leikkaustäsmäys (bold ja italic täsmäävät)
            for c in candidates:
                if c["is_bold"] == bold and c["is_italic"] == italic and os.path.isfile(c["path"]):
                    return c["path"], c["clean_family"]
            # 2. Bold täsmää (jos pyydetty boldia)
            if bold:
                for c in candidates:
                    if c["is_bold"] and os.path.isfile(c["path"]):
                        return c["path"], c["clean_family"]
            # 3. Italic täsmää (jos pyydetty italic)
            if italic:
                for c in candidates:
                    if c["is_italic"] and os.path.isfile(c["path"]):
                        return c["path"], c["clean_family"]
            # 4. Normaali leikkaus (Regular)
            for c in candidates:
                if not c["is_bold"] and not c["is_italic"] and os.path.isfile(c["path"]):
                    return c["path"], c["clean_family"]
            # 5. Mikä tahansa ehdokas
            for c in candidates:
                if os.path.isfile(c["path"]):
                    return c["path"], c["clean_family"]

        # 2. Linux Fontconfig fc-match
        query_parts = [family_query]
        style_parts = []
        if bold:
            style_parts.append("bold")
        if italic:
            style_parts.append("italic")
        if style_parts:
            query_parts.append(":style=" + ",".join(style_parts))

        full_query = " ".join(query_parts)

        try:
            cmd = ["fc-match", "-f", "%{file}|%{family}|%{style}", full_query]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                timeout=3.0
            )
            out = res.stdout.strip()
            if out:
                parts = out.split("|")
                fpath = parts[0].strip()
                ffamily = parts[1].strip() if len(parts) > 1 else family_query
                if fpath and os.path.isfile(fpath):
                    return fpath, ffamily
        except Exception:
            pass

        # Toissijainen haku standardi-fallbackeista
        normalized_q = re.sub(r"[^a-z0-9]", "", family_query.lower())
        for key, fallback_family in cls.STANDARD_FALLBACKS.items():
            if key in normalized_q:
                try:
                    cmd = ["fc-match", "-f", "%{file}|%{family}|%{style}", fallback_family]
                    res = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=3.0)
                    out = res.stdout.strip()
                    if out:
                        parts = out.split("|")
                        fpath = parts[0].strip()
                        ffamily = parts[1].strip() if len(parts) > 1 else fallback_family
                        if fpath and os.path.isfile(fpath):
                            return fpath, ffamily
                except Exception:
                    pass

        return None, None

    @classmethod
    def is_font_installed(cls, clean_family: str, bold: bool = False, italic: bool = False) -> Tuple[bool, str, Optional[str]]:
        """
        Tarkistaa, onko annettu kirjasinperhe aidosti asennettu paikalliseen järjestelmään,
        onko sille asennettu suositeltu avoin vastine, tai onko kyseessä standardi Base-14 -kirjasin.
        Palauttaa: (onko_asennettu, löydetty_perhenimi_tai_syy, tiedostopolku)
        """
        norm_clean = re.sub(r"[^a-zA-Z0-9]", "", clean_family).lower()

        # 1. Base-14 standardit PDF-fontit (vain ja ainoastaan nämä todelliset Base-14 perheet!)
        base14_exact = {
            "helvetica", "arial", "times", "timesroman", "timesnewroman",
            "courier", "couriernew", "symbol", "zapfdingbats", "zapf"
        }
        if norm_clean in base14_exact:
            return True, "Standardi Base-14 PDF-kirjasin", None

        # 2. Käyttäjän oma fonts/-kansio suoralla nimellä tai avoimena vastineena
        user_fonts = cls.scan_local_user_fonts()
        candidates: List[Dict[str, Any]] = []
        if norm_clean in user_fonts:
            candidates.extend(user_fonts[norm_clean])
        else:
            for k, flist in user_fonts.items():
                if norm_clean in k or k in norm_clean:
                    candidates.extend(flist)

        sub_key = cls.get_substitute_family(clean_family)
        if sub_key:
            norm_sub = re.sub(r"[^a-zA-Z0-9]", "", sub_key).lower()
            if norm_sub in user_fonts:
                candidates.extend(user_fonts[norm_sub])
            else:
                for k, flist in user_fonts.items():
                    if norm_sub in k or k in norm_sub:
                        candidates.extend(flist)

        if candidates:
            best_c = None
            for c in candidates:
                if c["is_bold"] == bold and c["is_italic"] == italic and os.path.isfile(c["path"]):
                    best_c = c
                    break
            if not best_c and bold:
                for c in candidates:
                    if c["is_bold"] and os.path.isfile(c["path"]):
                        best_c = c
                        break
            if not best_c and italic:
                for c in candidates:
                    if c["is_italic"] and os.path.isfile(c["path"]):
                        best_c = c
                        break
            if not best_c:
                for c in candidates:
                    if not c["is_bold"] and not c["is_italic"] and os.path.isfile(c["path"]):
                        best_c = c
                        break
            if not best_c and candidates:
                best_c = candidates[0]

            if best_c:
                clean_name = best_c["clean_family"]
                if sub_key:
                    return True, f"Avoin vastine asennettu: {clean_name}", best_c["path"]
                return True, clean_name, best_c["path"]

        # 3. Järjestelmän Fontconfig
        fpath, ffamily = cls.resolve_local_font(clean_family, bold=bold, italic=italic)
        if fpath and ffamily:
            norm_found = re.sub(r"[^a-zA-Z0-9]", "", ffamily).lower()
            # Varmistetaan että löydetty fontti on todella pyydetty perhe eikä vain geneerinen fallback (kuten DejaVu Sans)!
            if norm_clean in norm_found or norm_found in norm_clean:
                return True, ffamily, fpath
            else:
                return False, f"Puuttuu (korvike: {ffamily})", fpath

        return False, "Puuttuu järjestelmästä", None

    @staticmethod
    def _parse_extracted_font(res: Any) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[bytes]]:
        """Purkaa doc.extract_font -tuloksen, joka on PyMuPDF:ssä 4-alkioinen tuple (name, ext, type, buffer)."""
        if not res:
            return None, None, None, None
        if isinstance(res, (tuple, list)) and len(res) >= 4:
            return res[0], res[1], res[2], res[3]
        if isinstance(res, dict):
            return res.get("basename", ""), res.get("ext", ""), res.get("type", ""), res.get("buffer")
        return None, None, None, None

    @classmethod
    def inspect_and_resolve(
        cls,
        doc: fitz.Document,
        span: Dict[str, Any],
        new_text: str,
        override_bold: Optional[bool] = None,
        override_italic: Optional[bool] = None
    ) -> FontMatchResult:
        """
        Kattava analyysi valitulle tekstialkiolle (span) ja uudelle syötteelle:
        1. Analysoi alkuperäisen fontin nimen, koon ja leikkauksen.
        2. Etsii ja purkaa PDF:ään upotetun fonttitiedoston doc.extract_font(xref).
        3. Tarkistaa fontToolsilla, tukeeko upotettu fontti kaikkia uuden tekstin merkkejä.
        4. Jos kyseessä on standardi Base-14 fontti tai upotettu fontti, säilyttää tarkan ulkoasun.
        5. Vasta jos merkkejä puuttuu, hakee järjestelmän lokaalin kirjasimen.
        """
        raw_font = span.get("font", "Helvetica")
        clean_family, is_subset, is_bold, is_italic = cls.clean_font_name(raw_font)
        
        # Flags-tarkistus (PyMuPDF: bit 1 (2) = TEXT_FONT_ITALIC, bit 4 (16) = TEXT_FONT_BOLD)
        span_flags = span.get("flags", 0)
        if span_flags & 2:
            is_italic = True
        if span_flags & 16:
            is_bold = True

        if override_bold is not None:
            is_bold = override_bold
        if override_italic is not None:
            is_italic = override_italic

        result = FontMatchResult(
            original_font_name=raw_font,
            clean_family=clean_family,
            is_subset=is_subset,
            is_bold=is_bold,
            is_italic=is_italic
        )

        def norm_key(s: str) -> str:
            s = re.sub(r"^[A-Z]{6}\+", "", s)
            return re.sub(r"[^a-zA-Z0-9]", "", s).lower()

        norm_raw = norm_key(raw_font)
        norm_clean = norm_key(clean_family)

        embedded_buffer = None
        embedded_ext = None
        extracted_name = None

        # 1. Etsitään fontti sivun ja dokumentin fonttisanakirjoista
        target_page_idx = span.get("page_idx", 0)
        search_pages = [target_page_idx] if 0 <= target_page_idx < len(doc) else []
        search_pages += [i for i in range(len(doc)) if i != target_page_idx]

        # Ensisijainen haku: täsmällinen vastaavuus koko nimelle
        for p_idx in search_pages:
            page = doc[p_idx]
            for f in page.get_fonts(full=True):
                fxref, fext, ftype, fbase, fname, fenc = f[:6]
                norm_base = norm_key(fbase)
                norm_fname = norm_key(fname)
                if norm_raw == norm_base or norm_raw == norm_fname:
                    res = doc.extract_font(fxref)
                    bname, ext, ftype, buf = cls._parse_extracted_font(res)
                    if buf and len(buf) > 0:
                        embedded_buffer = buf
                        embedded_ext = ext
                        extracted_name = bname
                        result.embedded_extracted = True
                        result.embedded_ext = ext
                        result.embedded_buffer = buf
                        break
            if embedded_buffer:
                break

        # Toissijainen haku: perhe ja leikkaus (bold/italic) täsmäävät täysin
        if not embedded_buffer:
            for p_idx in search_pages:
                page = doc[p_idx]
                for f in page.get_fonts(full=True):
                    fxref, fext, ftype, fbase, fname, fenc = f[:6]
                    clean_f, _, is_bold_f, is_italic_f = cls.clean_font_name(fbase)
                    if norm_key(clean_f) == norm_clean and is_bold_f == is_bold and is_italic_f == is_italic:
                        res = doc.extract_font(fxref)
                        bname, ext, ftype, buf = cls._parse_extracted_font(res)
                        if buf and len(buf) > 0:
                            embedded_buffer = buf
                            embedded_ext = ext
                            extracted_name = bname
                            result.embedded_extracted = True
                            result.embedded_ext = ext
                            result.embedded_buffer = buf
                            break
                if embedded_buffer:
                    break

        # 2. Jos upotettu fontti löytyi (TrueType / OpenType / CFF)
        if embedded_buffer and embedded_ext in ("ttf", "otf", "cff"):
            cmap_codepoints = cls.get_font_cmap_coverage(embedded_buffer)

            # Määritetään tarkistettava teksti:
            # Jos kyseessä on monirivinen kappale ja rivijako vastaa alkuperäistä,
            # tarkistetaan vain muuttuneiden rivien merkit (muuttumattomat rivit säilyvät koskemattomina).
            text_to_check = new_text
            orig_lines = span.get("original_lines", [])
            if orig_lines:
                new_lines = new_text.split("\n")
                if len(new_lines) == len(orig_lines):
                    changed = [
                        nl for nl, ol in zip(new_lines, orig_lines)
                        if re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0\s]+", " ", nl.strip()) != re.sub(r"[\u2000-\u200b\u202f\u205f\u3000\u00a0\s]+", " ", ol.strip())
                    ]
                    if changed:
                        text_to_check = " ".join(changed)
                    else:
                        text_to_check = ""

            missing = cls.check_text_in_cmap(text_to_check, cmap_codepoints)
            result.embedded_missing_glyphs = missing
            if not missing:
                result.can_use_embedded = True
                result.effective_font_name = raw_font
                result.status_summary = f"Alkuperäinen kirjasin säilytetty ({extracted_name or clean_family})."
                return result

        # 3. Jos kyseessä on standardi Base-14 fontti (Helvetica, Times, Courier jne.)
        # Tarkistetaan vain todelliset Base-14 perheet, ei mielivaltaisia 'sans' tai 'serif' sanoja!
        base14_helv = ("helvetica", "arial")
        base14_times = ("times", "timesroman", "timesnewroman", "tiro")
        base14_courier = ("courier", "couriernew")

        is_base14 = (
            any(norm_clean == h or norm_clean.startswith(h) for h in base14_helv) or
            any(norm_clean == t or norm_clean.startswith(t) for t in base14_times) or
            any(norm_clean == c or norm_clean.startswith(c) for c in base14_courier) or
            norm_clean in ("symbol", "zapf", "zapfdingbats")
        )

        if is_base14:
            if any(norm_clean == h or norm_clean.startswith(h) for h in base14_helv):
                result.effective_font_name = "hebi" if (is_bold and is_italic) else ("hebo" if is_bold else ("heit" if is_italic else "helv"))
                result.status_summary = f"Standardi Helvetica ({result.effective_font_name}), alkuperäinen ulkoasu."
                result.can_use_local = True
                return result
            elif any(norm_clean == t or norm_clean.startswith(t) for t in base14_times):
                result.effective_font_name = "tibi" if (is_bold and is_italic) else ("tibo" if is_bold else ("tiit" if is_italic else "tiro"))
                result.status_summary = f"Standardi Times ({result.effective_font_name}), alkuperäinen ulkoasu."
                result.can_use_local = True
                return result
            elif any(norm_clean == c or norm_clean.startswith(c) for c in base14_courier):
                result.effective_font_name = "cobi" if (is_bold and is_italic) else ("cobo" if is_bold else ("coit" if is_italic else "couri"))
                result.status_summary = f"Standardi Courier ({result.effective_font_name}), alkuperäinen ulkoasu."
                result.can_use_local = True
                return result
            elif "symb" in norm_clean:
                result.effective_font_name = "symb"
                result.status_summary = "Standardi Symbol, alkuperäinen ulkoasu."
                result.can_use_local = True
                return result
            elif "zadb" in norm_clean or "zapf" in norm_clean:
                result.effective_font_name = "zadb"
                result.status_summary = "Standardi ZapfDingbats, alkuperäinen ulkoasu."
                result.can_use_local = True
                return result

        # 4. Jos kyseessä ei ole Base-14, tarkistetaan paikalliset asennetut tai tuodut fontit (ml. avoimet vastineet)
        local_path, local_family = cls.resolve_local_font(clean_family, bold=is_bold, italic=is_italic)
        result.local_font_path = local_path
        result.local_font_family = local_family

        sub_key = cls.get_substitute_family(clean_family)
        is_sub_match = False
        if sub_key and local_family:
            norm_loc = re.sub(r"[^a-zA-Z0-9]", "", local_family).lower()
            if sub_key in norm_loc or norm_loc in sub_key:
                is_sub_match = True

        norm_loc = re.sub(r"[^a-zA-Z0-9]", "", local_family or "").lower()
        is_true_local_match = local_path and ((norm_clean in norm_loc or norm_loc in norm_clean) or is_sub_match)

        if is_true_local_match and os.path.isfile(local_path):
            try:
                with open(local_path, "rb") as f:
                    local_bytes = f.read()
                local_cmap = cls.get_font_cmap_coverage(local_bytes)
                local_missing = cls.check_text_in_cmap(new_text, local_cmap)
                result.local_missing_glyphs = local_missing
                if not local_missing:
                    result.can_use_local = True
                    result.effective_font_path = local_path
                    result.effective_font_name = "injected_local_font"

                    # Tarkistetaan vastaako lokaalin tiedoston leikkaus toivottua
                    _, _, loc_is_b, loc_is_it = cls.clean_font_name(os.path.splitext(os.path.basename(local_path))[0])
                    result.effective_is_bold = loc_is_b
                    result.effective_is_italic = loc_is_it

                    if is_bold and not loc_is_b:
                        result.needs_faux_bold = True

                    style_suffix = ""
                    if loc_is_b and loc_is_it:
                        style_suffix = " Bold Italic"
                    elif loc_is_b:
                        style_suffix = " Bold"
                    elif loc_is_it:
                        style_suffix = " Italic"
                    elif result.needs_faux_bold:
                        style_suffix = " (Lihavoitu korvike)"

                    if is_sub_match:
                        result.status_summary = f"Avoin vastine: {local_family}{style_suffix} ({os.path.basename(local_path)})."
                    else:
                        result.status_summary = f"Lokaali kirjasin: {local_family}{style_suffix} ({os.path.basename(local_path)})."
                    return result
            except Exception:
                pass

        # 5. Puuttuva kirjasin: valitaan tyylin mukainen (serif vs sans-serif) standardikorvike
        is_serif_type = any(w in norm_clean for w in ("serif", "roman", "georgia", "garamond", "times", "minion", "mercury")) and ("sans" not in norm_clean)
        if is_serif_type:
            result.effective_font_name = "tibi" if (is_bold and is_italic) else ("tibo" if is_bold else ("tiit" if is_italic else "tiro"))
        else:
            result.effective_font_name = "hebi" if (is_bold and is_italic) else ("hebo" if is_bold else ("heit" if is_italic else "helv"))

        result.can_use_local = False
        result.can_use_embedded = False
        result.status_summary = f"Puuttuu: {clean_family} (korvike: {result.effective_font_name})."
        return result


class FontDownloader:
    """
    Hallitsee puuttuvien avoimien fonttien hakua, latausta ja tuontia käyttäjän luvalla.
    Toimii 100 % läpinäkyvästi: verkkolataus käynnistyy vain käyttäjän pyynnöstä.
    """

    OPEN_FONTS_CATALOG = {
        "roboto": ("Roboto", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/Roboto%5Bwdth%2Cwght%5D.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/roboto/static/Roboto-Regular.ttf",
        ]),
        "inter": ("Inter", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
        ]),
        "opensans": ("Open Sans", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth%2Cwght%5D.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans-Regular.ttf",
        ]),
        "lato": ("Lato", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/lato/Lato-Regular.ttf",
        ]),
        "montserrat": ("Montserrat", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf",
        ]),
        "merriweather": ("Merriweather", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/Merriweather%5Bopsz%2Cwdth%2Cwght%5D.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/merriweather/Merriweather-Regular.ttf",
        ]),
        "ptsans": ("PT Sans", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PT_Sans-Web-Regular.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/ptsans/PT_Sans-Web-Bold.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/opensans/OpenSans%5Bwdth%2Cwght%5D.ttf",
        ]),
        "crimsonpro": ("Crimson Pro", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/crimsonpro/CrimsonPro%5Bwght%5D.ttf",
            "https://raw.githubusercontent.com/google/fonts/main/ofl/crimsonpro/static/CrimsonPro-Regular.ttf",
        ]),
        "barlow": ("Barlow", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/barlow/Barlow-Regular.ttf",
        ]),
        "oswald": ("Oswald", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf",
        ]),
        "ebgaramond": ("EB Garamond", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/ebgaramond/EBGaramond%5Bwght%5D.ttf",
        ]),
        "greatvibes": ("Great Vibes", [
            "https://raw.githubusercontent.com/google/fonts/main/ofl/greatvibes/GreatVibes-Regular.ttf",
        ]),
    }

    RECOMMENDATIONS = {
        "stonesans": ("PT Sans / Open Sans (Avoin vastine Stone Sansille)", "ptsans"),
        "stoneserif": ("Crimson Pro / Merriweather (Avoin vastine Stone Serifille)", "crimsonpro"),
        "itcstoneserif": ("Crimson Pro / Merriweather (Avoin vastine Stone Serifille)", "crimsonpro"),
        "itcstoneserifstd": ("Crimson Pro / Merriweather (Avoin vastine Stone Serifille)", "crimsonpro"),
        "itcstoneserifstdan": ("Crimson Pro / Merriweather (Avoin vastine Stone Serifille)", "crimsonpro"),
        "minionpro": ("Crimson Pro (Avoin vastine Minion Prolle)", "crimsonpro"),
        "mercurytext": ("Merriweather (Avoin vastine Mercury Textille)", "merriweather"),
        "din": ("Barlow / Oswald (Avoin vastine DIN-kirjasimelle)", "barlow"),
        "dinalternate": ("Barlow (Avoin vastine DIN Alternatelle)", "barlow"),
        "applechancery": ("Great Vibes (Avoin kalligrafiavaihtoehto)", "greatvibes"),
        "calibri": ("Inter / Roboto", "inter"),
        "georgia": ("Merriweather (Avoin vastine Georgialle)", "merriweather"),
        "garamond": ("EB Garamond (Avoin vastine Garamondille)", "ebgaramond"),
        "futura": ("Montserrat (Avoin vastine Futuralle)", "montserrat"),
        "baskerville": ("Crimson Pro / Merriweather", "crimsonpro"),
        "palatino": ("Merriweather / Crimson Pro", "merriweather"),
        "arial": ("Roboto / Liberation Sans", "roboto"),
        "helvetica": ("Inter / Roboto", "inter"),
        "times": ("Crimson Pro / Liberation Serif", "crimsonpro"),
    }

    @classmethod
    def get_recommendation(cls, clean_family: str) -> Tuple[Optional[str], Optional[str]]:
        """Palauttaa suositellun avoimen vastineen ja sen tunnisteen, jos tunnettu."""
        norm_k = re.sub(r"[^a-zA-Z0-9]", "", clean_family).lower()
        for k, (desc, font_id) in cls.RECOMMENDATIONS.items():
            if k in norm_k or norm_k in k:
                return desc, font_id
        for k, (name, _) in cls.OPEN_FONTS_CATALOG.items():
            if k in norm_k or norm_k in k:
                return f"Google Fonts: {name}", k
        return None, None

    @classmethod
    def download_open_font(cls, font_id_or_family: str, dest_dir: str = LOCAL_FONTS_DIR) -> Tuple[bool, str, Optional[str]]:
        """
        Lataa avoimen kirjasintiedoston käyttäjän nimenomaisesta pyynnöstä.
        Kokeilee automaattisesti useita varalähteitä virheiden (kuten 404) estämiseksi.
        """
        norm_k = re.sub(r"[^a-zA-Z0-9]", "", font_id_or_family).lower()
        url_candidates = None
        display_name = font_id_or_family

        if norm_k in cls.OPEN_FONTS_CATALOG:
            display_name, url_candidates = cls.OPEN_FONTS_CATALOG[norm_k]
        else:
            for k, (name, u) in cls.OPEN_FONTS_CATALOG.items():
                if k in norm_k or norm_k in k:
                    display_name, url_candidates = name, u
                    break

        if not url_candidates:
            return False, f"Fontille '{font_id_or_family}' ei löytynyt automaattista avointa latauslähdettä. Voit tuoda fonttitiedoston koneelta.", None

        urls = url_candidates if isinstance(url_candidates, list) else [url_candidates]

        import urllib.request
        last_error = ""
        os.makedirs(dest_dir, exist_ok=True)
        fname = f"{re.sub(r'[^a-zA-Z0-9]', '', display_name)}.ttf"
        out_path = os.path.join(dest_dir, fname)

        for u in urls:
            try:
                req = urllib.request.Request(
                    u,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) PDFwriter-Offline-Editor/1.0"}
                )
                with urllib.request.urlopen(req, timeout=12.0) as resp:
                    data = resp.read()

                if len(data) >= 1000:
                    with open(out_path, "wb") as f:
                        f.write(data)

                    FontconfigResolver.scan_local_user_fonts(force_reload=True)
                    return True, f"Kirjasin '{display_name}' ladattiin onnistuneesti!", out_path
                else:
                    last_error = "Tiedosto oli liian pieni tai korruptoitunut."
            except Exception as e:
                last_error = str(e)
                continue

        return False, f"Lataus epäonnistui kaikista lähteistä ({last_error})", None

    @classmethod
    def download_all_recommended(cls, doc_model, dest_dir: str = LOCAL_FONTS_DIR) -> Tuple[int, int, List[str]]:
        """
        Lataa ja ottaa käyttöön kerralla kaikki avoimet vastineet dokumentin puuttuville kirjasimille.
        Palauttaa: (onnistuneet_kpl, yhteensa_kpl, virheet)
        """
        if not doc_model or not doc_model.is_open:
            return 0, 0, ["Dokumentti ei ole auki."]

        fonts_summary = doc_model.get_document_fonts_summary()
        missing = [f for f in fonts_summary if not f.get("is_installed", False) and f.get("rec_id")]

        seen_ids = set()
        to_download = []
        for f in missing:
            rec_id = f.get("rec_id")
            if rec_id and rec_id not in seen_ids:
                seen_ids.add(rec_id)
                to_download.append((rec_id, f.get("recommendation", rec_id)))

        if not to_download:
            return 0, 0, []

        success_count = 0
        errors = []
        for rec_id, rec_desc in to_download:
            success, msg, _ = cls.download_open_font(rec_id, dest_dir=dest_dir)
            if success:
                success_count += 1
            else:
                errors.append(f"{rec_desc}: {msg}")

        FontconfigResolver.scan_local_user_fonts(force_reload=True)
        return success_count, len(to_download), errors

    @classmethod
    def import_font_file(cls, src_path: str, dest_dir: str = LOCAL_FONTS_DIR) -> Tuple[bool, str, Optional[str]]:
        """Tuo käyttäjän valitseman .ttf tai .otf -tiedoston sovelluksen fonts/-kansioon."""
        import shutil
        if not os.path.isfile(src_path):
            return False, "Valittua tiedostoa ei löydy levyltä.", None

        fname = os.path.basename(src_path)
        if not fname.lower().endswith((".ttf", ".otf")):
            return False, "Vain .ttf ja .otf -fonttitiedostot ovat tuettuja.", None

        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest_path = os.path.join(dest_dir, fname)
            shutil.copy2(src_path, dest_path)
            FontconfigResolver.scan_local_user_fonts(force_reload=True)
            return True, f"Kirjasintiedosto '{fname}' tuotiin onnistuneesti!", dest_path
        except Exception as e:
            return False, f"Tiedoston tuonti epäonnistui: {str(e)}", None

