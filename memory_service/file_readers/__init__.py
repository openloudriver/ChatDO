"""
Unified file reader using Unstructured.io for maximum extraction quality.

All file types are now handled by Unstructured, which provides:
- Superior PDF extraction (especially tables)
- High-quality Word/Excel/PowerPoint extraction
- OCR for images
- Support for many additional formats (HTML, XML, etc.)

This replaces the previous multi-reader approach with a single,
high-quality extraction pipeline.
"""
from memory_service.file_readers.unstructured_reader import read_file

__all__ = ['read_file']

