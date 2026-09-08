"""
Fonttiresoluution ja glyyfien yksikkötestit.
"""

import unittest
from pdf_engine.font_resolver import FontconfigResolver, FontMatchResult


class TestFontResolver(unittest.TestCase):

    def test_clean_font_name_with_subset(self):
        raw = "BAAAAA+LiberationSerif-Bold"
        clean, is_subset, is_bold, is_italic = FontconfigResolver.clean_font_name(raw)
        self.assertEqual(clean, "LiberationSerif")
        self.assertTrue(is_subset)
        self.assertTrue(is_bold)
        self.assertFalse(is_italic)

    def test_clean_font_name_italic_subset(self):
        raw = "XYZABC+Arial-ItalicMT"
        clean, is_subset, is_bold, is_italic = FontconfigResolver.clean_font_name(raw)
        self.assertEqual(clean, "Arial")
        self.assertTrue(is_subset)
        self.assertFalse(is_bold)
        self.assertTrue(is_italic)

    def test_clean_standard_font(self):
        raw = "Helvetica-BoldOblique"
        clean, is_subset, is_bold, is_italic = FontconfigResolver.clean_font_name(raw)
        self.assertEqual(clean, "Helvetica")
        self.assertFalse(is_subset)
        self.assertTrue(is_bold)
        self.assertTrue(is_italic)

    def test_cmap_checking(self):
        # Simuloitu Unicode-koodipistejoukko (ASCII 'A'-'Z' ja 'a'-'z')
        ascii_set = set(range(ord('A'), ord('Z') + 1)) | set(range(ord('a'), ord('z') + 1))
        
        # Teksti ilman puuttuvia merkkejä
        missing = FontconfigResolver.check_text_in_cmap("Hello World", ascii_set)
        self.assertEqual(missing, [])

        # Teksti, jossa ääkkösiä ja erikoismerkkejä
        missing = FontconfigResolver.check_text_in_cmap("Päivää €", ascii_set)
        self.assertIn("ä", missing)
        self.assertIn("€", missing)

    def test_fontconfig_local_resolution(self):
        # Haetaan järjestelmän yleinen fontti (esim. sans-serif tai Liberation)
        path, family = FontconfigResolver.resolve_local_font("sans-serif")
        self.assertIsNotNone(path)
        self.assertTrue(len(path) > 0)

    def test_family_substitutions_mapping(self):
        # Varmistetaan että Stone-perheet mäppäytyvät oikeisiin avoimiin vastineisiin
        self.assertEqual(FontconfigResolver.get_substitute_family("ITC Stone Serif Std"), "crimsonpro")
        self.assertEqual(FontconfigResolver.get_substitute_family("Stone Serif Std"), "crimsonpro")
        self.assertEqual(FontconfigResolver.get_substitute_family("Stone Sans Std"), "ptsans")
        self.assertEqual(FontconfigResolver.get_substitute_family("Stone Sans"), "ptsans")

    def test_installed_open_substitutes(self):
        # Kun CrimsonPro ja PTSans ovat fonts/-kansiossa, Stone-perheet tunnistuvat asennetuiksi
        FontconfigResolver.scan_local_user_fonts(force_reload=True)
        is_inst_serif, desc_serif, path_serif = FontconfigResolver.is_font_installed("ITC Stone Serif Std")
        self.assertTrue(is_inst_serif)
        self.assertIn("Crimson", desc_serif)
        self.assertIsNotNone(path_serif)

        is_inst_sans, desc_sans, path_sans = FontconfigResolver.is_font_installed("Stone Sans Std")
        self.assertTrue(is_inst_sans)
        self.assertIn("PT", desc_sans)
        self.assertIsNotNone(path_sans)

    def test_bold_and_italic_style_resolution(self):
        # Varmistetaan että lihavoitu pyyntö valitsee -Bold.ttf tiedoston
        path_bold, fam_bold = FontconfigResolver.resolve_local_font("Stone Sans Std", bold=True, italic=False)
        self.assertIsNotNone(path_bold)
        self.assertIn("Bold", path_bold)

        # Varmistetaan että normaali pyyntö valitsee normaalin tiedoston
        path_reg, fam_reg = FontconfigResolver.resolve_local_font("Stone Sans Std", bold=False, italic=False)
        self.assertIsNotNone(path_reg)
        self.assertNotIn("Bold", path_reg)


if __name__ == "__main__":
    unittest.main()
