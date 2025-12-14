"""
SQLite database wrapper for Memory Service.

Manages the database schema and provides CRUD operations for sources, files, chunks, and embeddings.
"""
import sqlite3
import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Optional, Tuple
import hashlib
import logging

from memory_service.config import MEMORY_DASHBOARD_PATH, PROJECTS_PATH, get_db_path_for_source, TRACKING_DB_PATH
from memory_service.models import Source, File, Chunk, ChatMessage, Embedding, SearchResult, SourceStatus, IndexJob, Fact

logger = logging.getLogger(__name__)


def get_db_connection(source_id: str, project_id: Optional[str] = None):
    """Get a database connection for a specific source."""
    db_path = get_db_path_for_source(source_id, project_id=project_id)
    # Ensure the directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for concurrent access
    conn.row_factory = sqlite3.Row
    return conn


def init_db(source_id: str, project_id: Optional[str] = None):
    """Initialize the database schema for a specific source."""
    conn = get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    # Sources table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT UNIQUE NOT NULL,
            project_id TEXT NOT NULL,
            root_path TEXT NOT NULL,
            include_glob TEXT,
            exclude_glob TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Files table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            filetype TEXT NOT NULL,
            modified_at TIMESTAMP NOT NULL,
            size_bytes INTEGER NOT NULL,
            hash TEXT,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE(source_id, path)
        )
    """)
    
    # Chat messages table (for cross-chat memory)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL,
            project_id TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            message_index INTEGER NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE(chat_id, message_id)
        )
    """)
    
    # Chunks table (extended to support both files and chat messages)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER,
            chat_message_id INTEGER,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(id),
            FOREIGN KEY (chat_message_id) REFERENCES chat_messages(id),
            CHECK ((file_id IS NOT NULL AND chat_message_id IS NULL) OR (file_id IS NULL AND chat_message_id IS NOT NULL))
        )
    """)
    
    # Migration: Add chat_message_id column if it doesn't exist (for existing databases)
    cursor.execute("PRAGMA table_info(chunks)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'chat_message_id' not in columns:
        # Column doesn't exist, add it
        logger.info(f"Migrating chunks table: adding chat_message_id column for source {source_id}")
        try:
            cursor.execute("ALTER TABLE chunks ADD COLUMN chat_message_id INTEGER")
        except sqlite3.OperationalError as e:
            # Column might have been added between check and alter
            logger.warning(f"Migration note (may be harmless): {e}")
    
    # Create unique constraint for chunks (file-based or chat-based)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_file_unique 
        ON chunks(file_id, chunk_index) WHERE file_id IS NOT NULL
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_chunks_chat_unique 
        ON chunks(chat_message_id, chunk_index) WHERE chat_message_id IS NOT NULL
    """)
    
    # Embeddings table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            model_name TEXT NOT NULL,
            FOREIGN KEY (chunk_id) REFERENCES chunks(id),
            UNIQUE(chunk_id, model_name)
        )
    """)
    
    # Indexes for performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_source ON files(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chunks_chat_message ON chunks(chat_message_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_project ON chat_messages(project_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_chat ON chat_messages(chat_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON embeddings(chunk_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)")
    
    conn.commit()
    conn.close()


def upsert_source(source_id: str, project_id: str, root_path: str, 
                  include_glob: Optional[str] = None, exclude_glob: Optional[str] = None) -> int:
    """Insert or update a source. Returns the database ID."""
    # Initialize DB for this source if needed
    init_db(source_id)
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO sources (source_id, project_id, root_path, include_glob, exclude_glob, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            project_id = excluded.project_id,
            root_path = excluded.root_path,
            include_glob = excluded.include_glob,
            exclude_glob = excluded.exclude_glob,
            updated_at = excluded.updated_at
    """, (source_id, project_id, str(root_path), include_glob, exclude_glob, datetime.now()))
    
    db_id = cursor.lastrowid
    if db_id == 0:
        # Row already existed, get the ID
        cursor.execute("SELECT id FROM sources WHERE source_id = ?", (source_id,))
        db_id = cursor.fetchone()["id"]
    
    conn.commit()
    conn.close()
    return db_id


def get_source_by_source_id(source_id: str) -> Optional[Source]:
    """Get a source by its source_id."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM sources WHERE source_id = ?", (source_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return Source(
            id=row["id"],
            project_id=row["project_id"],
            root_path=row["root_path"],
            include_glob=row["include_glob"],
            exclude_glob=row["exclude_glob"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    return None


def get_file_by_path(source_db_id: int, path: str, source_id: str) -> Optional[File]:
    """Get a file by source database ID and path."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE source_id = ? AND path = ?", (source_db_id, path))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return File(
            id=row["id"],
            source_id=row["source_id"],
            path=row["path"],
            filetype=row["filetype"],
            modified_at=datetime.fromisoformat(row["modified_at"]),
            size_bytes=row["size_bytes"],
            hash=row["hash"]
        )
    return None


def upsert_file(source_db_id: int, path: str, filetype: str, 
                modified_at: datetime, size_bytes: int, source_id: str, content_hash: Optional[str] = None) -> int:
    """Insert or update a file. Returns the database ID."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO files (source_id, path, filetype, modified_at, size_bytes, hash)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, path) DO UPDATE SET
            filetype = excluded.filetype,
            modified_at = excluded.modified_at,
            size_bytes = excluded.size_bytes,
            hash = excluded.hash
    """, (source_db_id, path, filetype, modified_at, size_bytes, content_hash))
    
    db_id = cursor.lastrowid
    if db_id == 0:
        cursor.execute("SELECT id FROM files WHERE source_id = ? AND path = ?", (source_db_id, path))
        db_id = cursor.fetchone()["id"]
    
    conn.commit()
    conn.close()
    return db_id


def delete_file(file_id: int, source_id: str):
    """Delete a file and all its chunks and embeddings."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    # Delete embeddings first (foreign key constraint)
    cursor.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE file_id = ?)", (file_id,))
    # Delete chunks
    cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    # Delete file
    cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
    
    conn.commit()
    conn.close()


def delete_file_by_path(source_db_id: int, path: str, source_id: str):
    """Delete a file by path."""
    file = get_file_by_path(source_db_id, path, source_id)
    if file:
        delete_file(file.id, source_id)


def insert_chunks(file_id: int, chunks: List[Tuple[int, str, int, int]], source_id: str, chat_message_id: Optional[int] = None):
    """Insert chunks for a file or chat message. chunks is a list of (chunk_index, text, start_char, end_char)."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    if chat_message_id is not None:
        # Delete existing chunks for chat message
        cursor.execute("DELETE FROM chunks WHERE chat_message_id = ?", (chat_message_id,))
        # Insert new chunks
        cursor.executemany("""
            INSERT INTO chunks (chat_message_id, chunk_index, text, start_char, end_char)
            VALUES (?, ?, ?, ?, ?)
        """, [(chat_message_id, idx, text, start, end) for idx, text, start, end in chunks])
    else:
        # Delete existing chunks for file
        cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        # Insert new chunks
        cursor.executemany("""
            INSERT INTO chunks (file_id, chunk_index, text, start_char, end_char)
            VALUES (?, ?, ?, ?, ?)
        """, [(file_id, idx, text, start, end) for idx, text, start, end in chunks])
    
    conn.commit()
    conn.close()


def get_chunks_by_file_id(file_id: int, source_id: str) -> List[Chunk]:
    """Get all chunks for a file."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index", (file_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [Chunk(
        id=row["id"],
        file_id=row["file_id"],
        chat_message_id=row["chat_message_id"] if row["chat_message_id"] is not None else None,
        chunk_index=row["chunk_index"],
        text=row["text"],
        start_char=row["start_char"],
        end_char=row["end_char"]
    ) for row in rows]


def get_chunks_by_chat_message_id(chat_message_id: int, source_id: str) -> List[Chunk]:
    """Get all chunks for a chat message."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chunks WHERE chat_message_id = ? ORDER BY chunk_index", (chat_message_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [Chunk(
        id=row["id"],
        file_id=row["file_id"] if row["file_id"] is not None else None,
        chat_message_id=row["chat_message_id"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        start_char=row["start_char"],
        end_char=row["end_char"]
    ) for row in rows]


def insert_embeddings(chunk_ids: List[int], embeddings: np.ndarray, model_name: str, source_id: str):
    """Insert embeddings for chunks. embeddings should be shape [N, D]."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    # Delete existing embeddings for these chunks with this model
    cursor.executemany("DELETE FROM embeddings WHERE chunk_id = ? AND model_name = ?", 
                      [(cid, model_name) for cid in chunk_ids])
    
    # Insert new embeddings
    for chunk_id, embedding in zip(chunk_ids, embeddings):
        # Serialize numpy array to bytes
        embedding_bytes = embedding.tobytes()
        cursor.execute("""
            INSERT INTO embeddings (chunk_id, embedding, model_name)
            VALUES (?, ?, ?)
        """, (chunk_id, embedding_bytes, model_name))
    
    conn.commit()
    conn.close()


def get_all_embeddings_for_source(source_id: str, model_name: str) -> List[Tuple[int, np.ndarray, Optional[int], Optional[str], str, str, str, Optional[str], int, int, int, Optional[str], Optional[str]]]:
    """
    Get all embeddings for a specific source (files and chat messages).
    Returns list of (chunk_id, embedding_vector, file_id, file_path, chunk_text, source_id, project_id, filetype, chunk_index, start_char, end_char, chat_id, message_id).
    For file chunks: file_id and file_path are set, chat_id and message_id are None.
    For chat chunks: file_id and file_path are None, chat_id and message_id are set.
    
    Note: For project sources (source_id starts with "project-"), extracts project_id for correct routing.
    """
    # Extract project_id if this is a project source for correct path routing
    project_id = None
    if source_id.startswith("project-"):
        project_id = source_id.replace("project-", "")
    
    conn = get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    # Get file-based embeddings
    cursor.execute("""
        SELECT e.chunk_id, e.embedding, c.file_id, f.path, c.text, s.source_id, s.project_id, f.filetype, c.chunk_index, c.start_char, c.end_char, NULL as chat_id, NULL as message_id
        FROM embeddings e
        JOIN chunks c ON e.chunk_id = c.id
        JOIN files f ON c.file_id = f.id
        JOIN sources s ON f.source_id = s.id
        WHERE s.source_id = ? AND e.model_name = ? AND c.file_id IS NOT NULL
    """, (source_id, model_name))
    
    file_rows = cursor.fetchall()
    
    # Get chat-based embeddings
    cursor.execute("""
        SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id
        FROM embeddings e
        JOIN chunks c ON e.chunk_id = c.id
        JOIN chat_messages cm ON c.chat_message_id = cm.id
        JOIN sources s ON cm.source_id = s.id
        WHERE s.source_id = ? AND e.model_name = ? AND c.chat_message_id IS NOT NULL
    """, (source_id, model_name))
    
    chat_rows = cursor.fetchall()
    conn.close()
    
    results = []
    for row in file_rows + chat_rows:
        # Deserialize embedding
        embedding_bytes = row["embedding"]
        embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
        results.append((
            row["chunk_id"],
            embedding,
            row["file_id"],
            row["path"],
            row["text"],
            row["source_id"],
            row["project_id"],
            row["filetype"],
            row["chunk_index"],
            row["start_char"],
            row["end_char"],
            row["chat_id"],
            row["message_id"]
        ))
    
    return results


def get_chat_embeddings_for_project(project_id: str, model_name: str, exclude_chat_id: Optional[str] = None) -> List[Tuple[int, np.ndarray, Optional[int], Optional[str], str, str, str, Optional[str], int, int, int, Optional[str], Optional[str]]]:
    """
    Get all chat message embeddings for a project, optionally excluding a specific chat.
    Returns same format as get_all_embeddings_for_source.
    """
    source_id = f"project-{project_id}"
    
    try:
        # Pass project_id to route to projects/<project_name>/index/
        conn = get_db_connection(source_id, project_id=project_id)
        cursor = conn.cursor()
        
        if exclude_chat_id:
            cursor.execute("""
                SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id
                FROM embeddings e
                JOIN chunks c ON e.chunk_id = c.id
                JOIN chat_messages cm ON c.chat_message_id = cm.id
                JOIN sources s ON cm.source_id = s.id
                WHERE s.project_id = ? AND e.model_name = ? AND c.chat_message_id IS NOT NULL AND cm.chat_id != ?
            """, (project_id, model_name, exclude_chat_id))
        else:
            cursor.execute("""
                SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id
                FROM embeddings e
                JOIN chunks c ON e.chunk_id = c.id
                JOIN chat_messages cm ON c.chat_message_id = cm.id
                JOIN sources s ON cm.source_id = s.id
                WHERE s.project_id = ? AND e.model_name = ? AND c.chat_message_id IS NOT NULL
            """, (project_id, model_name))
        
        rows = cursor.fetchall()
        conn.close()
        
        results = []
        for row in rows:
            # Deserialize embedding
            embedding_bytes = row["embedding"]
            embedding = np.frombuffer(embedding_bytes, dtype=np.float32)
            results.append((
                row["chunk_id"],
                embedding,
                row["file_id"],
                row["path"],
                row["text"],
                row["source_id"],
                row["project_id"],
                row["filetype"],
                row["chunk_index"],
                row["start_char"],
                row["end_char"],
                row["chat_id"],
                row["message_id"]
            ))
        
        return results
    except Exception as e:
        # Source might not exist yet (no chats indexed)
        logger.debug(f"No chat embeddings found for project {project_id}: {e}")
        return []


def compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


# ============================================================================
# Tracking Database (Global - tracks all sources)
# ============================================================================

def get_tracking_db_connection():
    """Get a connection to the global tracking database."""
    # Tracking DB is in memory_dashboard, not projects
    from memory_service.config import TRACKING_DB_PATH
    TRACKING_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(TRACKING_DB_PATH), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")  # Enable WAL mode for concurrent access
    conn.row_factory = sqlite3.Row
    return conn


def init_tracking_db():
    """Initialize the tracking database schema."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    # SourceStatus table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS source_status (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            root_path TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'idle',
            files_indexed INTEGER DEFAULT 0,
            bytes_indexed INTEGER DEFAULT 0,
            last_index_started_at TEXT,
            last_index_completed_at TEXT,
            last_error TEXT,
            project_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    
    # IndexJob table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS index_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT NOT NULL,
            completed_at TEXT,
            files_total INTEGER,
            files_processed INTEGER DEFAULT 0,
            bytes_processed INTEGER DEFAULT 0,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    
    # Facts table (structured facts for ranked lists and preferences)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            chat_id TEXT,
            topic_key TEXT NOT NULL,
            kind TEXT NOT NULL,
            rank INTEGER,
            value TEXT NOT NULL,
            source_message_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(project_id, chat_id, topic_key, kind, rank)
        )
    """)
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON index_jobs(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_started ON index_jobs(started_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_project_topic ON facts(project_id, topic_key, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_project_chat_topic ON facts(project_id, chat_id, topic_key, created_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_facts_project_topic_rank ON facts(project_id, topic_key, rank)")
    
    conn.commit()
    conn.close()


def get_or_create_source(source_id: str, root_path: str, display_name: Optional[str] = None, project_id: Optional[str] = None) -> SourceStatus:
    """Get or create a source status record."""
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    if display_name is None:
        display_name = source_id
    
    cursor.execute("""
        INSERT INTO source_status (id, display_name, root_path, project_id, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            root_path = excluded.root_path,
            project_id = excluded.project_id,
            updated_at = excluded.updated_at
    """, (source_id, display_name, str(root_path), project_id, datetime.now()))
    
    cursor.execute("SELECT * FROM source_status WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    conn.commit()
    conn.close()
    
    return SourceStatus(
        id=row["id"],
        display_name=row["display_name"],
        root_path=row["root_path"],
        status=row["status"],
        files_indexed=row["files_indexed"],
        bytes_indexed=row["bytes_indexed"],
        last_index_started_at=datetime.fromisoformat(row["last_index_started_at"]) if row["last_index_started_at"] else None,
        last_index_completed_at=datetime.fromisoformat(row["last_index_completed_at"]) if row["last_index_completed_at"] else None,
        last_error=row["last_error"],
        project_id=row["project_id"]
    )


def register_source_config(src) -> SourceStatus:
    """
    Ensure the given SourceConfig has a row in the SourceStatus table and return it.
    """
    return get_or_create_source(
        source_id=src.id,
        root_path=str(src.root_path),
        display_name=getattr(src, 'display_name', src.id),  # Use display_name if available
        project_id=src.project_id
    )


def update_source_stats(source_id: str, **fields) -> None:
    """Update source status fields."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    updates = []
    values = []
    for key, value in fields.items():
        updates.append(f"{key} = ?")
        values.append(value)
    
    values.append(datetime.now())  # updated_at
    values.append(source_id)
    
    cursor.execute(f"""
        UPDATE source_status 
        SET {', '.join(updates)}, updated_at = ?
        WHERE id = ?
    """, values)
    
    conn.commit()
    conn.close()


def get_source_status(source_id: str) -> Optional[SourceStatus]:
    """Get source status by source_id."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM source_status WHERE id = ?", (source_id,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return SourceStatus(
            id=row["id"],
            display_name=row["display_name"],
            root_path=row["root_path"],
            status=row["status"],
            files_indexed=row["files_indexed"],
            bytes_indexed=row["bytes_indexed"],
            last_index_started_at=datetime.fromisoformat(row["last_index_started_at"]) if row["last_index_started_at"] else None,
            last_index_completed_at=datetime.fromisoformat(row["last_index_completed_at"]) if row["last_index_completed_at"] else None,
            last_error=row["last_error"],
            project_id=row["project_id"]
        )
    return None


def delete_source_from_tracking(source_id: str) -> None:
    """Delete a source from the tracking database (source_status and index_jobs)."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    # Delete index jobs first (foreign key constraint)
    cursor.execute("DELETE FROM index_jobs WHERE source_id = ?", (source_id,))
    # Delete source status
    cursor.execute("DELETE FROM source_status WHERE id = ?", (source_id,))
    
    conn.commit()
    conn.close()


def create_index_job(source_id: str, files_total: Optional[int] = None) -> int:
    """Create a new index job and return its ID."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO index_jobs (source_id, status, started_at, files_total, files_processed, bytes_processed)
        VALUES (?, 'running', ?, ?, 0, 0)
    """, (source_id, datetime.now(), files_total))
    
    job_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return job_id


def update_index_job(job_id: int, **fields) -> None:
    """Update index job fields."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    updates = []
    values = []
    for key, value in fields.items():
        updates.append(f"{key} = ?")
        values.append(value)
    
    values.append(job_id)
    
    cursor.execute(f"""
        UPDATE index_jobs 
        SET {', '.join(updates)}
        WHERE id = ?
    """, values)
    
    conn.commit()
    conn.close()


def get_latest_job(source_id: str) -> Optional[IndexJob]:
    """Get the latest job for a source."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM index_jobs 
        WHERE source_id = ? 
        ORDER BY started_at DESC 
        LIMIT 1
    """, (source_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return IndexJob(
            id=row["id"],
            source_id=row["source_id"],
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            files_total=row["files_total"],
            files_processed=row["files_processed"],
            bytes_processed=row["bytes_processed"],
            error=row["error"]
        )
    return None


def get_recent_jobs(source_id: str, limit: int = 10) -> List[IndexJob]:
    """Get recent jobs for a source."""
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT * FROM index_jobs 
        WHERE source_id = ? 
        ORDER BY started_at DESC 
        LIMIT ?
    """, (source_id, limit))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        IndexJob(
            id=row["id"],
            source_id=row["source_id"],
            status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            files_total=row["files_total"],
            files_processed=row["files_processed"],
            bytes_processed=row["bytes_processed"],
            error=row["error"]
        )
        for row in rows
    ]


def cleanup_stale_jobs(max_age_hours: int = 4) -> int:
    """
    Detect and mark stale running jobs as failed.
    
    A job is considered stale if:
    - It has been running for more than max_age_hours
    - It hasn't made progress in the last max_age_hours (for jobs that started earlier)
    
    Args:
        max_age_hours: Maximum age in hours before a job is considered stale
        
    Returns:
        Number of jobs cleaned up
    """
    from datetime import timedelta
    
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    # Find all running jobs
    cursor.execute("""
        SELECT * FROM index_jobs 
        WHERE status = 'running'
    """)
    
    running_jobs = cursor.fetchall()
    now = datetime.now()
    cleaned_count = 0
    
    for job_row in running_jobs:
        started_at = datetime.fromisoformat(job_row["started_at"])
        job_age = now - started_at
        
        # Mark as stale if job is older than max_age_hours
        if job_age > timedelta(hours=max_age_hours):
            job_id = job_row["id"]
            source_id = job_row["source_id"]
            
            # Mark job as failed
            cursor.execute("""
                UPDATE index_jobs 
                SET status = 'failed', 
                    completed_at = ?,
                    error = ?
                WHERE id = ?
            """, (
                now.isoformat(),
                f"Job was running for {job_age.total_seconds() / 3600:.1f} hours without completion - marked as stale",
                job_id
            ))
            
            # Update source status to error
            cursor.execute("""
                UPDATE source_status 
                SET status = 'error',
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                f"Indexing job timed out after {job_age.total_seconds() / 3600:.1f} hours",
                now.isoformat(),
                source_id
            ))
            
            cleaned_count += 1
    
    conn.commit()
    conn.close()
    
    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} stale indexing job(s)")
    
    return cleaned_count


def get_all_sources_with_latest_job() -> List[Tuple[SourceStatus, Optional[IndexJob]]]:
    """Get all sources with their latest job."""
    # Clean up stale jobs before fetching sources
    cleanup_stale_jobs()
    
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM source_status ORDER BY id")
    source_rows = cursor.fetchall()
    
    results = []
    for source_row in source_rows:
        source = SourceStatus(
            id=source_row["id"],
            display_name=source_row["display_name"],
            root_path=source_row["root_path"],
            status=source_row["status"],
            files_indexed=source_row["files_indexed"],
            bytes_indexed=source_row["bytes_indexed"],
            last_index_started_at=datetime.fromisoformat(source_row["last_index_started_at"]) if source_row["last_index_started_at"] else None,
            last_index_completed_at=datetime.fromisoformat(source_row["last_index_completed_at"]) if source_row["last_index_completed_at"] else None,
            last_error=source_row["last_error"],
            project_id=source_row["project_id"]
        )
        
        latest_job = get_latest_job(source.id)
        results.append((source, latest_job))
    
    conn.close()
    return results


def upsert_chat_message(
    source_id: str,
    project_id: str,
    chat_id: str,
    message_id: str,
    role: str,
    content: str,
    timestamp: datetime,
    message_index: int
) -> int:
    """
    Insert or update a chat message.
    Returns the database ID of the chat message.
    """
    # Get source_db_id
    source_db_id = upsert_source(source_id, project_id, "", None, None)
    
    # Initialize DB for this source if needed
    init_db(source_id)
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    # Check if message already exists
    cursor.execute("""
        SELECT id FROM chat_messages 
        WHERE chat_id = ? AND message_id = ?
    """, (chat_id, message_id))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing message
        cursor.execute("""
            UPDATE chat_messages
            SET role = ?, content = ?, timestamp = ?, message_index = ?
            WHERE id = ?
        """, (role, content, timestamp, message_index, existing["id"]))
        chat_message_id = existing["id"]
    else:
        # Insert new message
        cursor.execute("""
            INSERT INTO chat_messages (source_id, project_id, chat_id, message_id, role, content, timestamp, message_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_db_id, project_id, chat_id, message_id, role, content, timestamp, message_index))
        chat_message_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return chat_message_id


def get_chat_message_by_id(chat_message_id: int, source_id: str) -> Optional[ChatMessage]:
    """Get a chat message by its database ID."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_messages WHERE id = ?", (chat_message_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return ChatMessage(
        id=row["id"],
        source_id=row["source_id"],
        project_id=row["project_id"],
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        role=row["role"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]) if isinstance(row["timestamp"], str) else row["timestamp"],
        message_index=row["message_index"]
    )


# ============================================================================
# Facts Database (Structured facts for ranked lists and preferences)
# ============================================================================

def store_fact(
    project_id: str,
    topic_key: str,
    kind: str,
    value: str,
    source_message_id: str,
    chat_id: Optional[str] = None,
    rank: Optional[int] = None
) -> int:
    """
    Store a structured fact in the facts table.
    
    Args:
        project_id: Project ID (required)
        topic_key: Normalized topic key (e.g., "favorite_colors")
        kind: "ranked" or "single"
        value: The fact value
        source_message_id: ID of the message that contained this fact
        chat_id: Optional chat ID (for chat-scoped facts)
        rank: Optional rank (for ranked lists, 1-based)
        
    Returns:
        The database ID of the stored fact
    """
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if fact already exists
        cursor.execute("""
            SELECT id, created_at FROM facts
            WHERE project_id = ? AND chat_id = ? AND topic_key = ? AND kind = ? AND rank = ?
        """, (project_id, chat_id, topic_key, kind, rank))
        existing = cursor.fetchone()
        
        new_created_at = datetime.now()
        
        if existing:
            # Fact exists - update only if new created_at is newer
            existing_created_at = datetime.fromisoformat(existing["created_at"]) if isinstance(existing["created_at"], str) else existing["created_at"]
            if new_created_at > existing_created_at:
                cursor.execute("""
                    UPDATE facts
                    SET value = ?, source_message_id = ?, created_at = ?
                    WHERE id = ?
                """, (value, source_message_id, new_created_at, existing["id"]))
                conn.commit()
                return existing["id"]
            else:
                # Existing fact is newer, don't update
                conn.commit()
                return existing["id"]
        else:
            # Insert new fact
            cursor.execute("""
                INSERT INTO facts (project_id, chat_id, topic_key, kind, rank, value, source_message_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (project_id, chat_id, topic_key, kind, rank, value, source_message_id, new_created_at))
            
            fact_id = cursor.lastrowid
            conn.commit()
            return fact_id
    except sqlite3.IntegrityError as e:
        # Should not happen with our check, but handle gracefully
        logger.warning(f"IntegrityError storing fact: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()


def get_facts_by_topic(
    project_id: str,
    topic_key: str,
    chat_id: Optional[str] = None
) -> List[Fact]:
    """
    Get all facts for a topic, optionally filtered by chat_id.
    
    Args:
        project_id: Project ID
        topic_key: Normalized topic key
        chat_id: Optional chat ID filter (None = all chats in project)
        
    Returns:
        List of Fact objects, ordered by rank (for ranked) or created_at (for single)
    """
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    if chat_id:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ? AND chat_id = ?
            ORDER BY rank ASC, created_at DESC
        """, (project_id, topic_key, chat_id))
    else:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ?
            ORDER BY rank ASC, created_at DESC
        """, (project_id, topic_key))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [
        Fact(
            id=row["id"],
            project_id=row["project_id"],
            chat_id=row["chat_id"],
            topic_key=row["topic_key"],
            kind=row["kind"],
            rank=row["rank"],
            value=row["value"],
            source_message_id=row["source_message_id"],
            created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
        )
        for row in rows
    ]


def get_fact_by_rank(
    project_id: str,
    topic_key: str,
    rank: int,
    chat_id: Optional[str] = None
) -> Optional[Fact]:
    """
    Get a specific ranked fact by rank.
    
    Args:
        project_id: Project ID
        topic_key: Normalized topic key
        rank: Rank (1-based)
        chat_id: Optional chat ID filter (None = all chats in project)
        
    Returns:
        Fact object or None if not found
    """
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    if chat_id:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ? AND rank = ? AND chat_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (project_id, topic_key, rank, chat_id))
    else:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ? AND rank = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (project_id, topic_key, rank))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return Fact(
        id=row["id"],
        project_id=row["project_id"],
        chat_id=row["chat_id"],
        topic_key=row["topic_key"],
        kind=row["kind"],
        rank=row["rank"],
        value=row["value"],
        source_message_id=row["source_message_id"],
        created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
    )


def get_single_fact(
    project_id: str,
    topic_key: str,
    chat_id: Optional[str] = None
) -> Optional[Fact]:
    """
    Get a single fact (non-ranked) for a topic.
    
    Args:
        project_id: Project ID
        topic_key: Normalized topic key
        chat_id: Optional chat ID filter (None = all chats in project)
        
    Returns:
        Fact object or None if not found
    """
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    if chat_id:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ? AND kind = 'single' AND chat_id = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (project_id, topic_key, chat_id))
    else:
        cursor.execute("""
            SELECT * FROM facts
            WHERE project_id = ? AND topic_key = ? AND kind = 'single'
            ORDER BY created_at DESC
            LIMIT 1
        """, (project_id, topic_key))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return Fact(
        id=row["id"],
        project_id=row["project_id"],
        chat_id=row["chat_id"],
        topic_key=row["topic_key"],
        kind=row["kind"],
        rank=row["rank"],
        value=row["value"],
        source_message_id=row["source_message_id"],
        created_at=datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"]
    )


def get_most_recent_topic_key_in_chat(
    project_id: str,
    chat_id: str
) -> Optional[str]:
    """
    Get the most recent topic_key for ranked facts in a specific chat.
    
    Used when an ordinal query doesn't specify a topic - we use the most recent
    topic_key from the same chat (not project-wide, not other chats).
    
    Args:
        project_id: Project ID
        chat_id: Chat ID
        
    Returns:
        Most recent topic_key or None if no facts found in this chat
    """
    init_tracking_db()
    conn = get_tracking_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT DISTINCT topic_key FROM facts
        WHERE project_id = ? AND chat_id = ? AND kind = 'ranked'
        ORDER BY created_at DESC
        LIMIT 1
    """, (project_id, chat_id))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return row["topic_key"]

