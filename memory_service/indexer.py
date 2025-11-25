"""
Responsible for walking sources and updating file/chunk/embedding records.

Handles text extraction, chunking, and embedding generation for indexed files.
"""
import logging
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional
import fnmatch

from memory_service.config import CHUNK_SIZE_CHARS, CHUNK_OVERLAP_CHARS
from memory_service import store
from memory_service.store import db
from memory_service.embeddings import embed_texts
from memory_service.file_readers import (
    text_reader,
    pdf_reader,
    docx_reader,
    xlsx_reader,
    pptx_reader,
    image_reader
)

logger = logging.getLogger(__name__)

# Supported file extensions
TEXT_EXTENSIONS = {'.txt', '.md', '.json', '.ts', '.tsx', '.js', '.jsx', '.py', 
                   '.yml', '.yaml', '.toml', '.xml', '.html', '.css', '.scss',
                   '.sh', '.bash', '.zsh', '.rs', '.go', '.java', '.cpp', '.c',
                   '.h', '.hpp', '.cs', '.php', '.rb', '.swift', '.kt', '.scala',
                   '.sql', '.r', '.m', '.pl', '.lua', '.vim', '.conf', '.ini',
                   '.log', '.lock', '.lockb', '.jsonl', '.ndjson', '.geojson'}

PDF_EXTENSIONS = {'.pdf'}
DOCX_EXTENSIONS = {'.docx', '.doc', '.rtf'}
XLSX_EXTENSIONS = {'.xlsx', '.xls', '.csv'}
PPTX_EXTENSIONS = {'.pptx', '.ppt'}
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif'}

ALL_SUPPORTED = TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS | XLSX_EXTENSIONS | PPTX_EXTENSIONS | IMAGE_EXTENSIONS


def extract_text(path: Path) -> Optional[str]:
    """
    Extract text from a file based on its extension.
    
    Args:
        path: Path to the file
        
    Returns:
        Extracted text as string, or None if extraction fails or file type not supported
    """
    ext = path.suffix.lower()
    
    if ext in TEXT_EXTENSIONS:
        return text_reader.read_text_file(path)
    elif ext in PDF_EXTENSIONS:
        return pdf_reader.read_pdf(path)
    elif ext in DOCX_EXTENSIONS:
        return docx_reader.read_docx(path)
    elif ext in XLSX_EXTENSIONS:
        if ext == '.csv':
            return xlsx_reader.read_csv(path)
        else:
            return xlsx_reader.read_xlsx(path)
    elif ext in PPTX_EXTENSIONS:
        return pptx_reader.read_pptx(path)
    elif ext in IMAGE_EXTENSIONS:
        return image_reader.read_image(path)
    else:
        logger.debug(f"Unsupported file type: {ext} for {path}")
        return None


def chunk_text(text: str) -> List[Tuple[int, str, int, int]]:
    """
    Split text into chunks.
    
    Args:
        text: Text to chunk
        
    Returns:
        List of (chunk_index, chunk_text, start_char, end_char) tuples
    """
    if not text:
        return []
    
    chunks = []
    text_len = len(text)
    start = 0
    chunk_index = 0
    
    while start < text_len:
        # Calculate end position
        end = min(start + CHUNK_SIZE_CHARS, text_len)
        
        # If not at the end, try to break at a paragraph or line boundary
        if end < text_len:
            # Look for paragraph break (double newline)
            para_break = text.rfind('\n\n', start, end)
            if para_break != -1:
                end = para_break + 2
            else:
                # Look for single newline
                line_break = text.rfind('\n', start, end)
                if line_break != -1:
                    end = line_break + 1
                else:
                    # Look for sentence end
                    sentence_end = text.rfind('. ', start, end)
                    if sentence_end != -1:
                        end = sentence_end + 2
        
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append((chunk_index, chunk_text, start, end))
            chunk_index += 1
        
        # Move start position with overlap
        start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
    
    return chunks


def should_index_file(path: Path, include_glob: Optional[str], exclude_glob: Optional[str]) -> bool:
    """Check if a file should be indexed based on glob patterns."""
    path_str = str(path)
    
    # Check exclude first
    if exclude_glob:
        if fnmatch.fnmatch(path_str, exclude_glob) or exclude_glob in path_str:
            return False
    
    # Check include
    if include_glob:
        if not fnmatch.fnmatch(path_str, include_glob) and include_glob not in path_str:
            return False
    
    # Check if extension is supported
    return path.suffix.lower() in ALL_SUPPORTED


def index_file(path: Path, source_db_id: int, source_id: str) -> bool:
    """
    Index a single file (idempotent).
    
    Checks modified_at and hash to avoid re-embedding when not needed.
    
    Args:
        path: Path to the file
        source_db_id: Database ID of the source
        source_id: Source ID string (for database path)
        
    Returns:
        True if file was indexed successfully, False otherwise
    """
    try:
        if not path.exists():
            logger.warning(f"File does not exist: {path}")
            return False
        
        # Get file stats
        stat = path.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime)
        size_bytes = stat.st_size
        filetype = path.suffix.lower().lstrip('.')
        
        # Check if file already exists and hasn't changed
        existing_file = db.get_file_by_path(source_db_id, str(path), source_id)
        if existing_file:
            # Check if file has been modified
            if existing_file.modified_at == modified_at and existing_file.size_bytes == size_bytes:
                logger.debug(f"File unchanged, skipping: {path}")
                return True
        
        # Extract text
        text = extract_text(path)
        if text is None:
            logger.warning(f"Could not extract text from {path}")
            return False
        
        # Compute content hash
        import hashlib
        content_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        
        # Check if content hash matches (avoid re-embedding if only metadata changed)
        if existing_file and existing_file.hash == content_hash:
            # Update metadata but don't re-embed
            db.upsert_file(source_db_id, str(path), filetype, modified_at, size_bytes, source_id, content_hash)
            logger.debug(f"Content unchanged, updated metadata only: {path}")
            return True
        
        # Chunk the text
        chunks = chunk_text(text)
        if not chunks:
            logger.warning(f"No chunks extracted from {path}")
            return False
        
        # Upsert file record
        file_id = db.upsert_file(source_db_id, str(path), filetype, modified_at, size_bytes, source_id, content_hash)
        
        # Insert chunks
        chunk_data = [(idx, txt, start, end) for idx, txt, start, end in chunks]
        db.insert_chunks(file_id, chunk_data, source_id)
        
        # Get chunk IDs for embedding
        chunk_records = db.get_chunks_by_file_id(file_id, source_id)
        chunk_ids = [c.id for c in chunk_records]
        chunk_texts = [c.text for c in chunk_records]
        
        # Generate embeddings
        logger.info(f"Generating embeddings for {len(chunk_texts)} chunks from {path}")
        embeddings = embed_texts(chunk_texts)
        
        # Store embeddings
        from memory_service.config import EMBEDDING_MODEL
        db.insert_embeddings(chunk_ids, embeddings, EMBEDDING_MODEL, source_id)
        
        logger.info(f"Successfully indexed {path} ({len(chunks)} chunks)")
        return True
        
    except Exception as e:
        logger.error(f"Error indexing file {path}: {e}", exc_info=True)
        return False


def index_source(source_id: str) -> int:
    """
    Perform a full scan and index of a source folder.
    
    Args:
        source_id: The source_id string (not database ID)
        
    Returns:
        Number of files indexed
    """
    # Initialize DB for this source
    db.init_db(source_id)
    
    source = db.get_source_by_source_id(source_id)
    if not source:
        logger.error(f"Source not found: {source_id}")
        return 0
    
    root_path = Path(source.root_path)
    if not root_path.exists():
        logger.error(f"Source root path does not exist: {root_path}")
        return 0
    
    logger.info(f"Starting full index of source: {source_id} at {root_path}")
    
    indexed_count = 0
    skipped_count = 0
    
    # Walk the directory tree
    for path in root_path.rglob('*'):
        if path.is_file():
            if should_index_file(path, source.include_glob, source.exclude_glob):
                if index_file(path, source.id, source_id):
                    indexed_count += 1
                else:
                    skipped_count += 1
            else:
                skipped_count += 1
    
    logger.info(f"Indexed {indexed_count} files, skipped {skipped_count} files for source {source_id}")
    return indexed_count


def delete_file(path: Path, source_db_id: int, source_id: str):
    """Delete a file and all its chunks/embeddings from the index."""
    db.delete_file_by_path(source_db_id, str(path), source_id)
    logger.info(f"Deleted file from index: {path}")

