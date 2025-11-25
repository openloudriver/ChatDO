"""
PDF file reader using pypdf.
"""
from pathlib import Path
from typing import Optional
from pypdf import PdfReader


def read_pdf(path: Path) -> Optional[str]:
    """
    Extract text from a PDF file.
    
    Args:
        path: Path to the PDF file
        
    Returns:
        Extracted text as a single string, or None if extraction fails
    """
    try:
        reader = PdfReader(str(path))
        text_parts = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        return "\n\n".join(text_parts)
    except Exception as e:
        print(f"Error reading PDF {path}: {e}")
        return None

