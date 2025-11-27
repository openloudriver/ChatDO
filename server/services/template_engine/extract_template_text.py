"""
Extract text from templates using Unstructured.io.
"""
from pathlib import Path
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)

# Import Unstructured partition function
try:
    from unstructured.partition.auto import partition
    UNSTRUCTURED_AVAILABLE = True
except ImportError:
    UNSTRUCTURED_AVAILABLE = False
    logger.warning(
        "unstructured not installed. Install with: pip install 'unstructured[all-docs]'"
    )


def extract_template_text(path: Path) -> Optional[str]:
    """
    Extract text from a template file using Unstructured.
    
    This uses the same Unstructured pipeline as the Memory Service,
    supporting all file types: PDF, DOCX, XLSX, PPTX, images with OCR, etc.
    
    Args:
        path: Path to the template file
        
    Returns:
        Extracted text as a single string, or None if extraction fails
    """
    if not UNSTRUCTURED_AVAILABLE:
        logger.error(f"Unstructured not available. Cannot extract from {path}")
        return None
    
    if not path.exists():
        logger.warning(f"Template file does not exist: {path}")
        return None
    
    try:
        # Use Unstructured's partition to get structured elements
        # This provides better structure preservation than just concatenating text
        elements = partition(
            filename=str(path),
            strategy="hi_res",  # Best quality
            infer_table_structure=True,
            extract_images_in_pdf=True,
            ocr_languages=["eng"],
        )
        
        # Concatenate all element text
        text_parts = []
        for element in elements:
            text = element.text if hasattr(element, 'text') else str(element)
            if text and text.strip():
                text_parts.append(text.strip())
        
        if text_parts:
            result = "\n".join(text_parts)
            logger.debug(f"Extracted {len(result)} characters from template {path}")
            return result
        else:
            logger.warning(f"No text extracted from template {path}")
            return None
            
    except Exception as e:
        logger.error(f"Unstructured extraction failed for template {path}: {e}", exc_info=True)
        # Try fast strategy as fallback
        try:
            logger.info(f"Trying fast strategy for {path}")
            elements = partition(
                filename=str(path),
                strategy="fast",
                infer_table_structure=True,
            )
            text_parts = []
            for element in elements:
                text = element.text if hasattr(element, 'text') else str(element)
                if text and text.strip():
                    text_parts.append(text.strip())
            if text_parts:
                return "\n".join(text_parts)
        except Exception as e2:
            logger.error(f"Fast strategy also failed for {path}: {e2}")
        
        return None

