"""
Image file reader using PIL and pytesseract (OCR).
"""
from pathlib import Path
from typing import Optional
from PIL import Image
import pytesseract


def read_image(path: Path) -> Optional[str]:
    """
    Extract text from an image file using OCR.
    
    Args:
        path: Path to the image file
        
    Returns:
        Extracted text prefixed with filename, or None if extraction fails
    """
    try:
        image = Image.open(str(path))
        text = pytesseract.image_to_string(image)
        
        # Prefix with filename so the model knows it came from an image
        filename = path.name
        return f"Image file: {filename}\n\n{text}"
    except Exception as e:
        print(f"Error reading image {path}: {e}")
        return None

