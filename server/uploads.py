"""
File upload handling for ChatDO
Saves files and extracts text from PDFs, Word docs, images, etc.
"""
from fastapi import UploadFile
from pathlib import Path
import uuid
import aiofiles
import mimetypes


UPLOADS_BASE = Path(__file__).parent.parent / "uploads"


async def handle_file_upload(project_id: str, conversation_id: str, file: UploadFile) -> dict:
    """
    Save uploaded file and extract text if applicable.
    Returns metadata about the saved file.
    """
    # Create upload directory
    upload_dir = UPLOADS_BASE / project_id / conversation_id
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate unique filename
    file_ext = Path(file.filename).suffix if file.filename else ""
    unique_filename = f"{uuid.uuid4()}{file_ext}"
    file_path = upload_dir / unique_filename
    
    # Save file
    async with aiofiles.open(file_path, 'wb') as f:
        content = await file.read()
        await f.write(content)
    
    # Determine MIME type
    mime_type, _ = mimetypes.guess_type(file.filename or "")
    
    result = {
        "filename": unique_filename,
        "original_filename": file.filename,
        "path": str(file_path.relative_to(UPLOADS_BASE.parent)),
        "size": len(content),
        "mime_type": mime_type,
        "text_extracted": False
    }
    
    # Extract text based on file type
    if mime_type:
        if mime_type.startswith("text/"):
            # Plain text file
            async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                text_content = await f.read()
            text_path = upload_dir / f"{uuid.uuid4()}.txt"
            async with aiofiles.open(text_path, 'w', encoding='utf-8') as f:
                await f.write(text_content)
            result["text_extracted"] = True
            result["text_path"] = str(text_path.relative_to(UPLOADS_BASE.parent))
        
        elif mime_type == "application/pdf":
            # PDF extraction (requires PyPDF2 or pdfplumber)
            try:
                text_content = await extract_pdf_text(file_path)
                if text_content:
                    text_path = upload_dir / f"{uuid.uuid4()}.txt"
                    async with aiofiles.open(text_path, 'w', encoding='utf-8') as f:
                        await f.write(text_content)
                    result["text_extracted"] = True
                    result["text_path"] = str(text_path.relative_to(UPLOADS_BASE.parent))
            except Exception as e:
                result["extraction_error"] = str(e)
        
        elif mime_type in [
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ]:
            # Word document extraction
            try:
                text_content = await extract_word_text(file_path)
                if text_content:
                    text_path = upload_dir / f"{uuid.uuid4()}.txt"
                    async with aiofiles.open(text_path, 'w', encoding='utf-8') as f:
                        await f.write(text_content)
                    result["text_extracted"] = True
                    result["text_path"] = str(text_path.relative_to(UPLOADS_BASE.parent))
            except Exception as e:
                result["extraction_error"] = str(e)
        
        elif mime_type.startswith("image/"):
            # Image OCR (would require pytesseract or similar)
            # For now, just save the image
            result["note"] = "Image OCR not yet implemented"
    
    return result


async def extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from PDF file"""
    try:
        import PyPDF2
        text_parts = []
        with open(pdf_path, 'rb') as f:
            pdf_reader = PyPDF2.PdfReader(f)
            for page in pdf_reader.pages:
                text_parts.append(page.extract_text())
        return "\n\n".join(text_parts)
    except ImportError:
        # Fallback: try pdfplumber
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text_parts.append(page.extract_text() or "")
            return "\n\n".join(text_parts)
        except ImportError:
            return ""  # No PDF library available


async def extract_word_text(doc_path: Path) -> str:
    """Extract text from Word document"""
    try:
        from docx import Document
        doc = Document(doc_path)
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n\n".join(paragraphs)
    except ImportError:
        return ""  # python-docx not available

