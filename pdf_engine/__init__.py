"""
PDF Engine - Moduulit Acrobat-tason offline-käsittelyyn.
Sisältää fonttien resoluution, asettelulaskennan, PDF-dokumentinhallinnan ja Gauntlet-validoinnin.
"""

from .font_resolver import FontconfigResolver, FontMatchResult
from .layout_engine import LayoutEngine, OverflowReport, FitStrategy
from .pdf_document import PDFDocumentModel, EditOperation
from .validator import GauntletValidator, ValidationReport

__all__ = [
    "FontconfigResolver",
    "FontMatchResult",
    "LayoutEngine",
    "OverflowReport",
    "FitStrategy",
    "PDFDocumentModel",
    "EditOperation",
    "GauntletValidator",
    "ValidationReport",
]
