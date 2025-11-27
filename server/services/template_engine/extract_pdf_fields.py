"""
Extract form fields from PDF templates (AcroForm fields).
Used for identifying editable text fields in Air Force forms like 1206, OPB, etc.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

try:
    import PyPDF2
    PYPDF2_AVAILABLE = True
except ImportError:
    PYPDF2_AVAILABLE = False
    logger.warning("PyPDF2 not installed. Cannot extract PDF form fields.")


def extract_pdf_fields(pdf_path: Path) -> List[Dict[str, Any]]:
    """
    Extract AcroForm text fields from a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        List of field dictionaries with:
        - id: stable field identifier
        - name: field display name
        - page: 1-based page number
        - type: "text"
        - maxChars: optional character limit
    """
    if not PYPDF2_AVAILABLE:
        logger.warning("PyPDF2 not available, cannot extract PDF fields")
        return []
    
    if not pdf_path.exists():
        logger.warning(f"PDF file does not exist: {pdf_path}")
        return []
    
    fields = []
    
    try:
        with open(pdf_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            
            # Check if PDF has form fields
            if not pdf_reader.metadata or '/AcroForm' not in pdf_reader.trailer.get('/Root', {}):
                logger.info(f"PDF {pdf_path} does not have AcroForm fields")
                # Return a single default field
                return [{
                    "id": "main_content",
                    "name": "Main Content",
                    "page": 1,
                    "type": "text",
                    "maxChars": None
                }]
            
            # Try to get form fields from the root AcroForm
            if '/AcroForm' in pdf_reader.trailer.get('/Root', {}):
                root = pdf_reader.trailer['/Root']
                acro_form = root.get('/AcroForm', {})
                form_fields = acro_form.get('/Fields', [])
                
                # Extract fields from form
                for field_ref in form_fields:
                    try:
                        field_obj = field_ref.get_object()
                        field_type = field_obj.get('/FT')  # Field type
                        
                        # Only extract text fields
                        if field_type == '/Tx':  # Text field
                            field_name = field_obj.get('/T')
                            if field_name:
                                # Clean field name for ID
                                field_id = str(field_name).replace('(', '').replace(')', '').replace(' ', '_').replace('/', '_')
                                
                                # Try to find which page this field is on
                                page_num = 1  # Default to page 1
                                try:
                                    # Check widget annotations to find page
                                    if '/Kids' in field_obj:
                                        kids = field_obj['/Kids']
                                        if kids:
                                            first_kid = kids[0].get_object()
                                            if '/P' in first_kid:
                                                page_obj = first_kid['/P'].get_object()
                                                # Find page number
                                                for idx, page in enumerate(pdf_reader.pages, start=1):
                                                    if page == page_obj:
                                                        page_num = idx
                                                        break
                                except:
                                    pass
                                
                                field_dict = {
                                    "id": field_id,
                                    "name": str(field_name),
                                    "page": page_num,
                                    "type": "text",
                                }
                                
                                # Try to get max length if available
                                max_length = field_obj.get('/MaxLen')
                                if max_length:
                                    field_dict["maxChars"] = max_length
                                
                                fields.append(field_dict)
                    except Exception as e:
                        logger.warning(f"Error extracting field: {e}")
                        continue
            
            # Also check page annotations as fallback
            if not fields:
                for page_num, page in enumerate(pdf_reader.pages, start=1):
                    try:
                        if '/Annots' in page:
                            annotations = page['/Annots']
                            if annotations:
                                for annot_ref in annotations:
                                    annot = annot_ref.get_object()
                                    
                                    if annot.get('/Subtype') == '/Widget':
                                        field_type = annot.get('/FT')
                                        if field_type == '/Tx':
                                            field_name = annot.get('/T')
                                            if field_name:
                                                field_id = str(field_name).replace('(', '').replace(')', '').replace(' ', '_').replace('/', '_')
                                                field_dict = {
                                                    "id": field_id,
                                                    "name": str(field_name),
                                                    "page": page_num,
                                                    "type": "text",
                                                }
                                                max_length = annot.get('/MaxLen')
                                                if max_length:
                                                    field_dict["maxChars"] = max_length
                                                fields.append(field_dict)
                    except Exception as e:
                        logger.warning(f"Error extracting fields from page {page_num}: {e}")
                        continue
            
            # If no fields found, return default
            if not fields:
                logger.info(f"No form fields found in PDF {pdf_path}, using default field")
                return [{
                    "id": "main_content",
                    "name": "Main Content",
                    "page": 1,
                    "type": "text",
                    "maxChars": None
                }]
            
            logger.info(f"Extracted {len(fields)} fields from PDF {pdf_path}")
            return fields
            
    except Exception as e:
        logger.error(f"Error reading PDF {pdf_path}: {e}", exc_info=True)
        # Return default field on error
        return [{
            "id": "main_content",
            "name": "Main Content",
            "page": 1,
            "type": "text",
            "maxChars": None
        }]

