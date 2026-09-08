"""
Asettelun ja ylivalunnan yksikkötestit.
"""

import unittest
from pdf_engine.layout_engine import LayoutEngine, FitStrategy, OverflowReport


class TestLayoutEngine(unittest.TestCase):

    def test_calculate_text_width(self):
        w1 = LayoutEngine.calculate_text_width("Short", fontsize=12.0)
        w2 = LayoutEngine.calculate_text_width("Very long text string with many characters", fontsize=12.0)
        self.assertGreater(w2, w1)
        self.assertGreater(w1, 0.0)

    def test_overflow_analysis_exact_fit(self):
        span = {
            "text": "Hello",
            "bbox": (50.0, 100.0, 150.0, 120.0),  # Leveys 100 pt
            "size": 12.0,
            "origin": (50.0, 115.0)
        }
        # Lyhyt teksti mahtuu 100 pt tilaan
        report = LayoutEngine.analyze_overflow(span, "Hi")
        self.assertFalse(report.is_overflow)
        self.assertEqual(report.overflow_severity, "none")

    def test_overflow_analysis_critical(self):
        span = {
            "text": "Word",
            "bbox": (50.0, 100.0, 80.0, 120.0),  # Leveys vain 30 pt
            "size": 12.0,
            "origin": (50.0, 115.0)
        }
        # Pitkä teksti ylittää 30 pt rajan merkittävästi
        report = LayoutEngine.analyze_overflow(span, "Supercalifragilisticexpialidocious")
        self.assertTrue(report.is_overflow)
        self.assertEqual(report.overflow_severity, "critical")
        self.assertGreater(report.delta_width, 30.0)

    def test_auto_fit_strategy(self):
        span = {
            "text": "Short",
            "bbox": (50.0, 100.0, 100.0, 120.0),  # Leveys 50 pt
            "size": 14.0,
            "origin": (50.0, 115.0)
        }
        long_text = "Much longer replacement text"
        new_size, scale, origin = LayoutEngine.compute_fit_parameters(
            span, long_text, strategy=FitStrategy.AUTO_FIT
        )
        self.assertLess(new_size, 14.0)
        self.assertLess(scale, 1.0)
        self.assertEqual(origin.y, 115.0)


if __name__ == "__main__":
    unittest.main()
