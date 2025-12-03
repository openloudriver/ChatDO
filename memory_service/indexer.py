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
from memory_service.file_readers import read_file

logger = logging.getLogger(__name__)

# Supported file extensions - expanded list for Unstructured
# Unstructured supports many more formats than we previously handled
TEXT_EXTENSIONS = {
    # Code files
    '.txt', '.md', '.json', '.ts', '.tsx', '.js', '.jsx', '.py', 
    '.yml', '.yaml', '.toml', '.xml', '.html', '.css', '.scss',
    '.sh', '.bash', '.zsh', '.rs', '.go', '.java', '.cpp', '.c',
    '.h', '.hpp', '.cs', '.php', '.rb', '.swift', '.kt', '.scala',
    '.sql', '.r', '.m', '.pl', '.lua', '.vim', '.conf', '.ini',
    '.log', '.lock', '.lockb', '.jsonl', '.ndjson', '.geojson',
    '.tsv', '.psv', '.tsv', '.psv'
}

# Document formats (Unstructured handles these with superior quality)
PDF_EXTENSIONS = {'.pdf'}
DOCX_EXTENSIONS = {'.docx', '.doc', '.rtf', '.odt'}  # Added OpenDocument
XLSX_EXTENSIONS = {'.xlsx', '.xls', '.csv', '.ods'}  # Added OpenDocument Spreadsheet
PPTX_EXTENSIONS = {'.pptx', '.ppt', '.odp'}  # Added OpenDocument Presentation

# Images (Unstructured uses OCR)
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.heif'}

# Additional formats Unstructured supports
EMAIL_EXTENSIONS = {'.eml', '.msg'}  # Email files
ARCHIVE_EXTENSIONS = {'.epub', '.mobi'}  # E-books
OTHER_EXTENSIONS = {'.rtf', '.odt', '.ods', '.odp'}  # Already covered but listed for clarity

# Excluded formats - these should never be indexed
# Video files and ISO images are binary and not useful for text search
EXCLUDED_EXTENSIONS = {
    # Video formats
    '.mp4', '.mov', '.avi', '.mkv', '.wmv', '.flv', '.webm', '.m4v', '.mpg', '.mpeg', '.3gp',
    # ISO/Disk images
    '.iso', '.img', '.dmg', '.vhd', '.vhdx',
    # Audio formats (not useful for text search)
    '.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a', '.wma',
    # Other binary formats
    '.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.exe', '.dll', '.bin'
}

ALL_SUPPORTED = (
    TEXT_EXTENSIONS | PDF_EXTENSIONS | DOCX_EXTENSIONS |
    XLSX_EXTENSIONS | PPTX_EXTENSIONS | IMAGE_EXTENSIONS |
    EMAIL_EXTENSIONS | ARCHIVE_EXTENSIONS
)


def extract_text(path: Path) -> Optional[str]:
    """
    Extract text from any file using Unstructured.io for maximum quality.
    
    Unstructured automatically detects file type and uses the best extraction
    method for each format. This provides superior quality compared to
    individual file readers, especially for:
    - PDFs with tables
    - Complex Word/Excel/PowerPoint documents
    - Images with text (OCR)
    - HTML/XML documents
    
    Args:
        path: Path to the file
        
    Returns:
        Extracted text as string, or None if extraction fails or file type not supported
    """
    # Use Unstructured's unified extraction for all file types
    # It handles file type detection and uses optimal extraction methods
    return read_file(path)


def chunk_text(text: str) -> List[Tuple[int, str, int, int]]:
    """
    Split text into chunks with improved logic to avoid huge single chunks.
    
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
    seen_chunks = set()  # Track unique chunks to avoid duplicates
    
    while start < text_len:
        # Calculate end position
        end = min(start + CHUNK_SIZE_CHARS, text_len)
        
        # If not at the end, try to break at a paragraph or line boundary
        if end < text_len:
            # Look for paragraph break (double newline) - prefer this
            para_break = text.rfind('\n\n', start, end)
            if para_break != -1 and para_break > start + 100:  # Ensure meaningful chunk
                end = para_break + 2
            else:
                # Look for single newline
                line_break = text.rfind('\n', start, end)
                if line_break != -1 and line_break > start + 100:
                    end = line_break + 1
                else:
                    # Look for sentence end
                    sentence_end = text.rfind('. ', start, end)
                    if sentence_end != -1 and sentence_end > start + 100:
                        end = sentence_end + 2
        
        chunk_text = text[start:end].strip()
        
        # Skip empty chunks and duplicates
        if chunk_text and len(chunk_text) > 10:  # Minimum meaningful chunk size
            # Create a hash of the chunk to detect duplicates
            chunk_hash = hash(chunk_text)
            if chunk_hash not in seen_chunks:
                chunks.append((chunk_index, chunk_text, start, end))
                seen_chunks.add(chunk_hash)
                chunk_index += 1
        
        # Move start position with overlap, but ensure we make progress
        new_start = max(start + 1, end - CHUNK_OVERLAP_CHARS)
        if new_start <= start:
            # Prevent infinite loop - force progress
            new_start = start + CHUNK_SIZE_CHARS // 2
        start = new_start
    
    return chunks


def should_index_file(path: Path, include_glob: Optional[str], exclude_glob: Optional[str]) -> bool:
    """Check if a file should be indexed based on glob patterns."""
    path_str = str(path)
    file_ext = path.suffix.lower()
    
    # First check if file extension is explicitly excluded (video, ISO, etc.)
    if file_ext in EXCLUDED_EXTENSIONS:
        return False
    
    # Check exclude glob patterns - support multiple patterns separated by commas
    if exclude_glob:
        # Split by comma and check each pattern
        exclude_patterns = [p.strip() for p in exclude_glob.split(',')]
        for pattern in exclude_patterns:
            if fnmatch.fnmatch(path_str, pattern) or pattern in path_str:
                return False
    
    # Check include
    if include_glob:
        if not fnmatch.fnmatch(path_str, include_glob) and include_glob not in path_str:
            return False
    
    # Check if extension is supported
    return file_ext in ALL_SUPPORTED


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
        
        # Skip very large non-PDF files that are likely to cause timeouts or memory issues
        # PDFs can be large but are still useful for search, so we allow them
        # Other file types over 100MB are often binary or not useful for search
        MAX_FILE_SIZE_NON_PDF = 100 * 1024 * 1024  # 100MB
        if size_bytes > MAX_FILE_SIZE_NON_PDF and filetype != 'pdf':
            logger.warning(f"Skipping very large file ({size_bytes / (1024*1024):.1f}MB): {path}")
            return False
        
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


def index_source(source_id: str) -> Tuple[int, int, int]:
    """
    Perform a full scan and index of a source folder.
    Supports automatic resume if a previous job was interrupted.
    
    Args:
        source_id: The source_id string (not database ID)
        
    Returns:
        Tuple of (files_indexed, bytes_indexed, job_id)
    """
    # Initialize DB for this source
    db.init_db(source_id)
    
    source = db.get_source_by_source_id(source_id)
    if not source:
        logger.error(f"Source not found: {source_id}")
        return 0, 0, 0
    
    root_path = Path(source.root_path)
    if not root_path.exists():
        logger.error(f"Source root path does not exist: {root_path}")
        return 0, 0, 0
    
    # Register source in tracking DB
    from memory_service.config import load_sources
    sources = load_sources()
    source_config = next((s for s in sources if s.id == source_id), None)
    if source_config:
        db.get_or_create_source(source_id, str(root_path), source_id, source_config.project_id)
    
    # Check for existing running job to resume
    latest_job = db.get_latest_job(source_id)
    resume_job = False
    job_id = None
    initial_indexed_count = 0
    initial_bytes_processed = 0
    
    if latest_job and latest_job.status == "running":
        # Check if job is recent (within last 24 hours) - if too old, start fresh
        from datetime import timedelta
        job_age = datetime.now() - latest_job.started_at
        if job_age < timedelta(hours=24):
            logger.info(f"Resuming interrupted indexing job {latest_job.id} for source: {source_id}")
            job_id = latest_job.id
            resume_job = True
            
            # Get actual counts from database (more accurate than job progress)
            conn = db.get_db_connection(source_id)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM files")
            row = cursor.fetchone()
            actual_file_count = row[0] if row else 0
            actual_bytes = row[1] if row and len(row) > 1 else 0
            conn.close()
            
            # Use actual database counts, but fall back to job progress if database is empty
            if actual_file_count > 0:
                initial_indexed_count = actual_file_count
                initial_bytes_processed = actual_bytes
                logger.info(f"Resuming from actual database state: {initial_indexed_count} files, {initial_bytes_processed:,} bytes")
            else:
                initial_indexed_count = latest_job.files_processed or 0
                initial_bytes_processed = latest_job.bytes_processed or 0
                logger.info(f"Resuming from job progress: {initial_indexed_count} files, {initial_bytes_processed:,} bytes")
        else:
            logger.info(f"Previous job {latest_job.id} is too old ({job_age}), starting fresh")
            # Mark old job as cancelled
            db.update_index_job(latest_job.id, status="cancelled", completed_at=datetime.now())
    
    # Count files to be indexed (optional, can be expensive for large repos)
    logger.info(f"Scanning files for source: {source_id}")
    files_to_index = []
    for path in root_path.rglob('*'):
        if path.is_file() and should_index_file(path, source.include_glob, source.exclude_glob):
            files_to_index.append(path)
    
    files_total = len(files_to_index)
    logger.info(f"Found {files_total} files to index for source: {source_id}")
    
    # Create new job if not resuming
    if not resume_job:
        job_id = db.create_index_job(source_id, files_total)
    
    # Update source status to indexing
    db.update_source_stats(
        source_id,
        status="indexing",
        last_index_started_at=datetime.now(),
        last_error=None
    )
    
    if resume_job:
        logger.info(f"Resuming index of source: {source_id} at {root_path} (job_id: {job_id}, already indexed: {initial_indexed_count} files)")
        # Update job to reflect resume
        db.update_index_job(job_id, status="running")  # Ensure it's marked as running
        # Immediately update source status to indexing and current progress
        db.update_source_stats(
            source_id,
            status="indexing",
            files_indexed=initial_indexed_count,
            bytes_indexed=initial_bytes_processed
        )
    else:
        logger.info(f"Starting full index of source: {source_id} at {root_path} (job_id: {job_id})")
    
    indexed_count = initial_indexed_count
    skipped_count = 0
    bytes_processed = initial_bytes_processed
    total_processed = initial_indexed_count  # Start from already-indexed count
    last_update = initial_indexed_count
    BATCH_SIZE = 1  # Update progress after every file for better visibility during slow extraction
    
    try:
        # Walk the directory tree
        # If resuming, index_file's idempotent check will skip already-indexed files
        for path in files_to_index:
            try:
                # Check if file was already indexed before this job started
                existing_file = db.get_file_by_path(source.id, str(path), source_id)
                was_already_indexed = existing_file is not None
                
                # index_file is idempotent - it will skip files that are already indexed and unchanged
                was_indexed = index_file(path, source.id, source_id)
                
                # Always increment total_processed to show we're still working
                total_processed += 1
                
                if was_indexed:
                    if not was_already_indexed:
                        # New file was indexed (or file was updated and re-indexed)
                        indexed_count += 1
                        try:
                            bytes_processed += path.stat().st_size
                        except:
                            pass
                    # else: file was already indexed and unchanged, skip counting (already in initial_indexed_count)
                else:
                    skipped_count += 1
                
                # Get actual totals from database (includes all indexed files, not just this job)
                conn = db.get_db_connection(source_id)
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM files")
                row = cursor.fetchone()
                actual_files = row[0] if row else 0
                actual_bytes = row[1] if row and len(row) > 1 else 0
                conn.close()
                
                # Update progress every BATCH_SIZE files processed
                if total_processed - last_update >= BATCH_SIZE:
                    db.update_index_job(job_id, files_processed=total_processed, bytes_processed=bytes_processed)
                    db.update_source_stats(
                        source_id,
                        files_indexed=actual_files,  # Use actual database count
                        bytes_indexed=actual_bytes    # Use actual database sum
                    )
                    last_update = total_processed
                    
            except Exception as e:
                logger.error(f"Error indexing file {path}: {e}")
                skipped_count += 1
                total_processed += 1  # Count error as processed for progress tracking
                
                # Update progress even on errors to show we're still working
                if total_processed - last_update >= BATCH_SIZE:
                    db.update_index_job(job_id, files_processed=total_processed, bytes_processed=bytes_processed)
                    db.update_source_stats(
                        source_id,
                        files_indexed=indexed_count,
                        bytes_indexed=bytes_processed
                    )
                    last_update = total_processed
    
        # Get final actual totals from database
        conn = db.get_db_connection(source_id)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), COALESCE(SUM(size_bytes), 0) FROM files")
        row = cursor.fetchone()
        final_files = row[0] if row else 0
        final_bytes = row[1] if row and len(row) > 1 else 0
        conn.close()
        
        # Final update
        db.update_index_job(
            job_id,
            status="completed",
            completed_at=datetime.now(),
            files_processed=total_processed,
            bytes_processed=bytes_processed
        )
        db.update_source_stats(
            source_id,
            status="idle",
            last_index_completed_at=datetime.now(),
            files_indexed=final_files,  # Use actual database count
            bytes_indexed=final_bytes    # Use actual database sum
        )
        
        logger.info(f"Indexed {indexed_count} files, skipped {skipped_count} files for source {source_id}")
        return indexed_count, bytes_processed, job_id
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error during indexing of source {source_id}: {e}", exc_info=True)
        
        # Mark job and source as failed
        db.update_index_job(
            job_id,
            status="failed",
            completed_at=datetime.now(),
            error=error_msg
        )
        db.update_source_stats(
            source_id,
            status="error",
            last_error=error_msg
        )
        
        return 0, 0, job_id


def delete_file(path: Path, source_db_id: int, source_id: str):
    """Delete a file and all its chunks/embeddings from the index."""
    db.delete_file_by_path(source_db_id, str(path), source_id)
    logger.info(f"Deleted file from index: {path}")

