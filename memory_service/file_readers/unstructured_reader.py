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
import signal
import threading
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Timeout for file extraction (5 minutes per file)
FILE_EXTRACTION_TIMEOUT = 300  # seconds

# Try to import Unstructured
try:
    from unstructured.partition.auto import partition
    UNSTRUCTURED_AVAILABLE = True
except ImportError:
    UNSTRUCTURED_AVAILABLE = False
    logger.warning(
        "unstructured not installed. Install with: pip install 'unstructured[all-docs]'"
    )


@contextmanager
def timeout_handler(seconds):
    """Context manager for timeout handling using signals (Unix) or threading (Windows)."""
    # Use signal.alarm on Unix systems (more reliable)
    if hasattr(signal, 'SIGALRM'):
        def timeout_signal(signum, frame):
            raise TimeoutError(f"Operation timed out after {seconds} seconds")
        
        old_handler = signal.signal(signal.SIGALRM, timeout_signal)
        signal.alarm(seconds)
        try:
            yield
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
    else:
        # Windows fallback: use threading (less reliable but works)
        timer = None
        def timeout_func():
            raise TimeoutError(f"Operation timed out after {seconds} seconds")
        
        timer = threading.Timer(seconds, timeout_func)
        timer.start()
        try:
            yield
        finally:
            if timer:
                timer.cancel()


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
            logger.debug(f"Attempting hi_res extraction for {path} (timeout: {FILE_EXTRACTION_TIMEOUT}s)")
            # Use timeout to prevent hangs
            try:
                with timeout_handler(FILE_EXTRACTION_TIMEOUT):
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
            except TimeoutError:
                logger.warning(f"hi_res extraction timed out for {path} after {FILE_EXTRACTION_TIMEOUT}s, trying fast strategy")
                raise  # Re-raise to trigger fast fallback
        except (Exception, TimeoutError) as e:
            # If hi_res fails (e.g., missing models, hangs, timeout, etc.), try fast strategy
            if isinstance(e, TimeoutError):
                logger.warning(f"Unstructured hi_res timed out for {path}, trying fast strategy")
            else:
                logger.warning(f"Unstructured hi_res failed for {path}: {e}, trying fast strategy")
            try:
                with timeout_handler(FILE_EXTRACTION_TIMEOUT):
                    elements = partition(
                        filename=str(path),
                        strategy="fast",  # Faster, still good quality
                        infer_table_structure=True,
                    )
                logger.debug(f"fast extraction succeeded for {path}")
            except TimeoutError:
                logger.error(f"Unstructured fast strategy also timed out for {path} after {FILE_EXTRACTION_TIMEOUT}s")
                return None
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

