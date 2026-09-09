"""Data loader package with lazy imports.

Importing one loader should not require optional dependencies for every other
format. For example, using DocxLoader must not import PdfLoader and require
fitz.
"""
from importlib import import_module


_EXPORTS = {
    "BaseLoader": (".base", "BaseLoader"),
    "MarkdownLoader": (".markdown", "MarkdownLoader"),
    "PdfLoader": (".pdf", "PdfLoader"),
    "ExcelLoader": (".excel", "ExcelLoader"),
    "TxtLoader": (".txt", "TxtLoader"),
    "DocxLoader": (".docx", "DocxLoader"),
    "PptxLoader": (".pptx", "PptxLoader"),
    "load_json_seed": (".seed", "load_json_seed"),
    "load_data_assets_seed": (".seed", "load_data_assets_seed"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(name)
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
