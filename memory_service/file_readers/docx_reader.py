"""
DOCX file reader using python-docx.
"""
from pathlib import Path
from typing import Optional
from docx import Document


def read_docx(path: Path) -> Optional[str]:
    """
    Extract text from a DOCX file.
    
    Args:
        path: Path to the DOCX file
        
    Returns:
        Extracted text as a single string, or None if extraction fails
    """
    try:
        doc = Document(str(path))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        return "\n".join(paragraphs)
    except Exception as e:
        print(f"Error reading DOCX {path}: {e}")
        return None

