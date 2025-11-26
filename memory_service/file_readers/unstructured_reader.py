"""
Unified file reader using Unstructured.io for maximum extraction quality.

Unstructured provides the best extraction quality for all document types:
- PDFs (with superior table extraction)
- Word documents (.docx, .doc, .rtf)
- Excel spreadsheets (.xlsx, .xls, .csv)
- PowerPoint presentations (.pptx, .ppt)
- Images (with OCR)
- HTML/XML
- And many more formats

This replaces all individual file readers with a single, high-quality extraction pipeline.
"""
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import Unstructured
try:
    from unstructured.partition.auto import partition
    UNSTRUCTURED_AVAILABLE = True
except ImportError:
    UNSTRUCTURED_AVAILABLE = False
    logger.warning(
        "unstructured not installed. Install with: pip install 'unstructured[all-docs]'"
    )


def extract_with_unstructured(path: Path) -> Optional[str]:
    """
    Extract text from any file using Unstructured.io.
    
    This provides the highest quality extraction for all supported file types.
    
    Args:
        path: Path to the file
        
    Returns:
        Extracted text as a single string, or None if extraction fails
    """
    if not UNSTRUCTURED_AVAILABLE:
        logger.error(f"Unstructured not available. Cannot extract from {path}")
        return None
    
    if not path.exists():
        logger.warning(f"File does not exist: {path}")
        return None
    
    try:
        # Try hi_res first (best quality), but fallback to fast if it fails
        # hi_res can be slow or fail if models aren't available
        try:
            logger.debug(f"Attempting hi_res extraction for {path}")
            elements = partition(
                filename=str(path),
                # High-resolution strategy for best quality (slower but better)
                # This is especially important for PDFs with tables
                strategy="hi_res",
                # Infer table structure for better table extraction (PDFs, images)
                infer_table_structure=True,
                # Extract images in PDFs (for OCR of embedded images)
                extract_images_in_pdf=True,
                # OCR mode for images and PDFs with embedded images
                ocr_languages=["eng"],
            )
            logger.debug(f"hi_res extraction succeeded for {path}")
        except Exception as e:
            # If hi_res fails (e.g., missing models, hangs, etc.), try fast strategy
            logger.warning(f"Unstructured hi_res failed for {path}: {e}, trying fast strategy")
            try:
                elements = partition(
                    filename=str(path),
                    strategy="fast",  # Faster, still good quality
                    infer_table_structure=True,
                )
                logger.debug(f"fast extraction succeeded for {path}")
            except Exception as e2:
                logger.error(f"Unstructured fast strategy also failed for {path}: {e2}")
                return None
        
        # Combine all element text
        text_parts = []
        for element in elements:
            # Get text from element
            text = element.text if hasattr(element, 'text') else str(element)
            if text and text.strip():
                text_parts.append(text.strip())
        
        if text_parts:
            result = "\n\n".join(text_parts)
            logger.debug(f"Unstructured extracted {len(result)} characters from {path}")
            return result
        else:
            logger.warning(f"Unstructured extracted no text from {path}")
            return None
            
    except Exception as e:
        logger.error(f"Unstructured extraction failed for {path}: {e}", exc_info=True)
        return None


def read_file(path: Path) -> Optional[str]:
    """
    Unified file reader using Unstructured for maximum quality.
    
    This is the single entry point for all file extraction.
    Unstructured handles file type detection and uses the best extraction
    method for each format automatically.
    
    Args:
        path: Path to the file
        
    Returns:
        Extracted text as a single string, or None if extraction fails
    """
    return extract_with_unstructured(path)

