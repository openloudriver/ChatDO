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
import uuid

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
            message_uuid TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TIMESTAMP NOT NULL,
            message_index INTEGER NOT NULL,
            FOREIGN KEY (source_id) REFERENCES sources(id),
            UNIQUE(chat_id, message_id),
            UNIQUE(message_uuid)
        )
    """)
    
    # Migration: Add message_uuid column if it doesn't exist (for existing databases)
    cursor.execute("PRAGMA table_info(chat_messages)")
    columns = [row[1] for row in cursor.fetchall()]
    if 'message_uuid' not in columns:
        logger.info(f"Migrating chat_messages table: adding message_uuid column for source {source_id}")
        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN message_uuid TEXT")
            # Generate UUIDs for existing messages
            cursor.execute("SELECT id, chat_id, message_id FROM chat_messages WHERE message_uuid IS NULL OR message_uuid = ''")
            existing_messages = cursor.fetchall()
            for row in existing_messages:
                new_uuid = str(uuid.uuid4())
                cursor.execute("UPDATE chat_messages SET message_uuid = ? WHERE id = ?", (new_uuid, row["id"]))
            # Add unique constraint after populating
            try:
                cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_uuid ON chat_messages(message_uuid)")
            except sqlite3.OperationalError:
                pass  # Index might already exist
        except sqlite3.OperationalError as e:
            logger.warning(f"Migration note (may be harmless): {e}")
    
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_uuid ON chat_messages(message_uuid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON embeddings(chunk_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)")
    
    # Project Facts table (for typed facts with provenance and temporal "latest wins")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS project_facts (
            fact_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            fact_key TEXT NOT NULL,
            value_text TEXT NOT NULL,
            value_type TEXT NOT NULL CHECK(value_type IN ('string', 'number', 'bool', 'date', 'json')),
            confidence REAL NOT NULL DEFAULT 1.0,
            source_message_uuid TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            effective_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            supersedes_fact_id TEXT,
            is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
            FOREIGN KEY (supersedes_fact_id) REFERENCES project_facts(fact_id),
            FOREIGN KEY (source_message_uuid) REFERENCES chat_messages(message_uuid)
        )
    """)
    
    # Indexes for project_facts
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_facts_project_key ON project_facts(project_id, fact_key, is_current)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_facts_source_uuid ON project_facts(source_message_uuid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_facts_current ON project_facts(project_id, is_current)")
    
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


def get_all_embeddings_for_source(source_id: str, model_name: str) -> List[Tuple[int, np.ndarray, Optional[int], Optional[str], str, str, str, Optional[str], int, int, int, Optional[str], Optional[str], Optional[str]]]:
    """
    Get all embeddings for a specific source (files and chat messages).
    Returns list of (chunk_id, embedding_vector, file_id, file_path, chunk_text, source_id, project_id, filetype, chunk_index, start_char, end_char, chat_id, message_id, message_uuid).
    For file chunks: file_id and file_path are set, chat_id, message_id, and message_uuid are None.
    For chat chunks: file_id and file_path are None, chat_id, message_id, and message_uuid are set.
    
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
        SELECT e.chunk_id, e.embedding, c.file_id, f.path, c.text, s.source_id, s.project_id, f.filetype, c.chunk_index, c.start_char, c.end_char, NULL as chat_id, NULL as message_id, NULL as message_uuid
        FROM embeddings e
        JOIN chunks c ON e.chunk_id = c.id
        JOIN files f ON c.file_id = f.id
        JOIN sources s ON f.source_id = s.id
        WHERE s.source_id = ? AND e.model_name = ? AND c.file_id IS NOT NULL
    """, (source_id, model_name))
    
    file_rows = cursor.fetchall()
    
    # Get chat-based embeddings (include message_uuid)
    cursor.execute("""
        SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id, cm.message_uuid
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
            row["message_id"],
            row["message_uuid"] if "message_uuid" in row.keys() else None  # May be None for old records
        ))
    
    return results


def get_chat_embeddings_for_project(project_id: str, model_name: str, exclude_chat_id: Optional[str] = None, exclude_chat_ids: Optional[List[str]] = None) -> List[Tuple[int, np.ndarray, Optional[int], Optional[str], str, str, str, Optional[str], int, int, int, Optional[str], Optional[str], Optional[str]]]:
    """
    Get all chat message embeddings for a project, optionally excluding specific chats.
    Returns same format as get_all_embeddings_for_source (includes message_uuid).
    
    Args:
        project_id: Project ID
        model_name: Embedding model name
        exclude_chat_id: DEPRECATED - single chat_id to exclude (for backward compatibility)
        exclude_chat_ids: List of chat_ids to exclude (e.g., trashed chats)
    """
    source_id = f"project-{project_id}"
    
    # Build list of excluded chat_ids (support both old and new parameters)
    excluded_ids = set()
    if exclude_chat_id:
        excluded_ids.add(exclude_chat_id)
    if exclude_chat_ids:
        excluded_ids.update(exclude_chat_ids)
    
    try:
        # Pass project_id to route to projects/<project_name>/index/
        conn = get_db_connection(source_id, project_id=project_id)
        cursor = conn.cursor()
        
        if excluded_ids:
            # Build SQL with IN clause for multiple exclusions
            placeholders = ",".join("?" * len(excluded_ids))
            cursor.execute(f"""
                SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id, cm.message_uuid
                FROM embeddings e
                JOIN chunks c ON e.chunk_id = c.id
                JOIN chat_messages cm ON c.chat_message_id = cm.id
                JOIN sources s ON cm.source_id = s.id
                WHERE s.project_id = ? AND e.model_name = ? AND c.chat_message_id IS NOT NULL AND cm.chat_id NOT IN ({placeholders})
            """, (project_id, model_name, *excluded_ids))
        else:
            cursor.execute("""
                SELECT e.chunk_id, e.embedding, NULL as file_id, NULL as path, c.text, s.source_id, s.project_id, NULL as filetype, c.chunk_index, c.start_char, c.end_char, cm.chat_id, cm.message_id, cm.message_uuid
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
                row["message_id"],
                row["message_uuid"] if "message_uuid" in row.keys() else None  # May be None for old records
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
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON index_jobs(source_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_started ON index_jobs(started_at DESC)")
    # REMOVED: facts table - using project_facts table instead (OLD system)
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
    message_index: int,
    message_uuid: Optional[str] = None
) -> int:
    """
    Insert or update a chat message.
    Returns the database ID of the chat message.
    
    Args:
        message_uuid: Optional UUIDv4. If provided, will be used for new messages.
                     For existing messages, preserves the existing UUID (idempotent).
                     If not provided for new messages, generates a new UUID.
    """
    # Get source_db_id
    source_db_id = upsert_source(source_id, project_id, "", None, None)
    
    # Initialize DB for this source if needed
    init_db(source_id)
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    
    # Check if message already exists
    cursor.execute("""
        SELECT id, message_uuid FROM chat_messages 
        WHERE chat_id = ? AND message_id = ?
    """, (chat_id, message_id))
    existing = cursor.fetchone()
    
    if existing:
        # Update existing message (preserve existing UUID - idempotent)
        existing_uuid = existing["message_uuid"]
        if not existing_uuid:
            # If UUID is missing (migration case), use provided UUID or generate one
            existing_uuid = message_uuid or str(uuid.uuid4())
        cursor.execute("""
            UPDATE chat_messages
            SET role = ?, content = ?, timestamp = ?, message_index = ?, message_uuid = ?
            WHERE id = ?
        """, (role, content, timestamp, message_index, existing_uuid, existing["id"]))
        chat_message_id = existing["id"]
    else:
        # Insert new message with UUID (use provided UUID if available)
        if not message_uuid:
            message_uuid = str(uuid.uuid4())
        cursor.execute("""
            INSERT INTO chat_messages (source_id, project_id, chat_id, message_id, message_uuid, role, content, timestamp, message_index)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (source_db_id, project_id, chat_id, message_id, message_uuid, role, content, timestamp, message_index))
        chat_message_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    return chat_message_id


def delete_chat_messages_by_chat_id(project_id: str, chat_id: str) -> int:
    """
    Delete all chat messages for a specific chat_id from memory_service.
    Also deletes associated chunks, embeddings, and facts.
    
    Args:
        project_id: Project ID
        chat_id: Chat/conversation ID to delete
        
    Returns:
        Number of chat messages deleted
    """
    source_id = f"project-{project_id}"
    
    try:
        init_db(source_id, project_id=project_id)
        conn = get_db_connection(source_id, project_id=project_id)
        cursor = conn.cursor()
        
        # Get all chat_message_ids and message_uuids for this chat_id
        cursor.execute("SELECT id, message_uuid FROM chat_messages WHERE chat_id = ?", (chat_id,))
        chat_message_rows = cursor.fetchall()
        chat_message_ids = [row["id"] for row in chat_message_rows]
        message_uuids = [row["message_uuid"] for row in chat_message_rows if row["message_uuid"]]
        
        if not chat_message_ids:
            conn.close()
            return 0
        
        # Delete facts that reference messages from this chat
        # Facts store source_message_uuid which references chat_messages.message_uuid
        if message_uuids:
            fact_placeholders = ",".join("?" * len(message_uuids))
            cursor.execute(f"""
                DELETE FROM project_facts 
                WHERE project_id = ? AND source_message_uuid IN ({fact_placeholders})
            """, [project_id] + message_uuids)
            facts_deleted = cursor.rowcount
            if facts_deleted > 0:
                logger.info(f"Deleted {facts_deleted} facts for chat_id={chat_id} in project_id={project_id}")
        
        # Get all chunk_ids for these chat messages (for ANN index removal)
        placeholders = ",".join("?" * len(chat_message_ids))
        cursor.execute(f"""
            SELECT e.chunk_id 
            FROM embeddings e
            JOIN chunks c ON e.chunk_id = c.id
            WHERE c.chat_message_id IN ({placeholders})
        """, chat_message_ids)
        chunk_rows = cursor.fetchall()
        chunk_ids_to_remove = [row["chunk_id"] for row in chunk_rows]
        
        # Delete embeddings first (foreign key constraint)
        if chunk_ids_to_remove:
            chunk_placeholders = ",".join("?" * len(chunk_ids_to_remove))
            cursor.execute(f"DELETE FROM embeddings WHERE chunk_id IN ({chunk_placeholders})", chunk_ids_to_remove)
        
        # Delete chunks
        cursor.execute(f"DELETE FROM chunks WHERE chat_message_id IN ({placeholders})", chat_message_ids)
        
        # Delete chat messages
        cursor.execute(f"DELETE FROM chat_messages WHERE id IN ({placeholders})", chat_message_ids)
        
        conn.commit()
        conn.close()
        
        # Remove from ANN index
        if chunk_ids_to_remove:
            try:
                from memory_service.api import ann_index_manager
                if ann_index_manager.is_available():
                    ann_index_manager.remove_embeddings(chunk_ids_to_remove)
                    logger.debug(f"[ANN] Removed {len(chunk_ids_to_remove)} embeddings from ANN index for chat_id={chat_id}")
            except Exception as e:
                logger.warning(f"[ANN] Failed to remove embeddings from ANN index for chat_id={chat_id}: {e}")
        
        logger.info(f"Deleted {len(chat_message_ids)} chat messages for chat_id={chat_id} in project_id={project_id}")
        return len(chat_message_ids)
    except Exception as e:
        logger.warning(f"Failed to delete chat messages for chat_id={chat_id} in project_id={project_id}: {e}")
        return 0


def get_chat_message_by_id(chat_message_id: int, source_id: str) -> Optional[ChatMessage]:
    """Get a chat message by its database ID."""
    conn = get_db_connection(source_id)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chat_messages WHERE id = ?", (chat_message_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    # Handle missing message_uuid for migration compatibility
    message_uuid = row["message_uuid"] if "message_uuid" in row.keys() else None
    if not message_uuid:
        # Generate UUID for old records
        message_uuid = str(uuid.uuid4())
        # Update the record
        conn = get_db_connection(source_id)
        cursor = conn.cursor()
        cursor.execute("UPDATE chat_messages SET message_uuid = ? WHERE id = ?", (message_uuid, chat_message_id))
        conn.commit()
        conn.close()
    
    return ChatMessage(
        id=row["id"],
        source_id=row["source_id"],
        project_id=row["project_id"],
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        message_uuid=message_uuid,
        role=row["role"],
        content=row["content"],
        timestamp=datetime.fromisoformat(row["timestamp"]) if isinstance(row["timestamp"], str) else row["timestamp"],
        message_index=row["message_index"]
    )


def get_message_uuid(project_id: str, chat_id: str, message_id: str) -> Optional[str]:
    """
    Get message_uuid from chat_messages table using project_id, chat_id, and message_id.
    
    Args:
        project_id: Project ID
        chat_id: Chat/conversation ID
        message_id: Message ID (from thread history)
        
    Returns:
        message_uuid if found, None otherwise
    """
    try:
        source_id = f"project-{project_id}"
        init_db(source_id, project_id=project_id)
        conn = get_db_connection(source_id)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT message_uuid FROM chat_messages 
            WHERE project_id = ? AND chat_id = ? AND message_id = ?
            LIMIT 1
        """, (project_id, chat_id, message_id))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            message_uuid = row["message_uuid"] if "message_uuid" in row.keys() else None
            # If UUID is missing, generate one and update the record
            if not message_uuid:
                message_uuid = str(uuid.uuid4())
                conn = get_db_connection(source_id)
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE chat_messages 
                    SET message_uuid = ? 
                    WHERE project_id = ? AND chat_id = ? AND message_id = ?
                """, (message_uuid, project_id, chat_id, message_id))
                conn.commit()
                conn.close()
            return message_uuid
        
        return None
    except Exception as e:
        logger.debug(f"Failed to get message_uuid for project_id={project_id}, chat_id={chat_id}, message_id={message_id}: {e}")
        return None


# ============================================================================
# REMOVED: NEW facts table system (facts table)
# All fact storage now uses project_facts table via store_project_fact()
# The following functions have been removed:
# - store_fact() - use store_project_fact() instead
# - get_facts_by_topic() - use search_current_facts() instead
# - get_fact_by_rank() - use search_current_facts() and filter by fact_key
# - get_single_fact() - use get_current_fact() instead
# - get_most_recent_topic_key_in_chat() - not needed with project_facts
# ============================================================================


# ============================================================================
# Project Facts Database (Typed facts with provenance and temporal "latest wins")
# ============================================================================

def store_project_fact(
    project_id: str,
    fact_key: str,
    value_text: str,
    value_type: str,
    source_message_uuid: str,
    confidence: float = 1.0,
    effective_at: Optional[datetime] = None,
    source_id: Optional[str] = None,
    created_at: Optional[datetime] = None  # For testing: deterministic timestamps
) -> tuple[str, str]:
    """
    Store a project fact with "latest wins" semantics.
    
    When a new fact with the same fact_key is stored, all previous facts
    with that key are marked as is_current=0, and the new fact references
    the most recent one via supersedes_fact_id.
    
    Args:
        project_id: Project ID
        fact_key: Fact key (e.g., "user.favorite_color")
        value_text: Fact value as text
        value_type: Type: 'string', 'number', 'bool', 'date', or 'json'
        source_message_uuid: UUID of the message that introduced/updated this fact
        confidence: Confidence score (0.0 to 1.0, default 1.0)
        effective_at: When this fact becomes effective (defaults to created_at)
        source_id: Source ID for database connection (uses project-based source)
        
    Returns:
        Tuple of (fact_id, action_type) where:
        - fact_id: The UUID of the stored fact
        - action_type: "store" if new fact, "update" if existing fact value changed
    """
    if source_id is None:
        source_id = f"project-{project_id}"
    
    # Initialize DB for this source if needed
    init_db(source_id, project_id=project_id)
    conn = get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    fact_id = str(uuid.uuid4())
    if created_at is None:
        created_at = datetime.now()  # Production: use current time
    if effective_at is None:
        effective_at = created_at
    
    # Find the most recent current fact with this key
        cursor.execute("""
        SELECT fact_id, value_text FROM project_facts
        WHERE project_id = ? AND fact_key = ? AND is_current = 1
        ORDER BY effective_at DESC, created_at DESC
            LIMIT 1
    """, (project_id, fact_key))
    previous_fact = cursor.fetchone()
    supersedes_fact_id = previous_fact[0] if previous_fact else None
    
    # Determine if this is a Store (new) or Update (existing fact changed)
    action_type = "store"  # Default: new fact
    if previous_fact:
        previous_value = previous_fact[1] if len(previous_fact) > 1 else None
        if previous_value and previous_value != value_text:
            # Same fact_key but different value = Update
            action_type = "update"
        # If same fact_key and same value, still counts as "store" (new fact row)
    
    # Mark all previous facts with this key as not current
    if previous_fact:
        cursor.execute("""
            UPDATE project_facts
            SET is_current = 0
            WHERE project_id = ? AND fact_key = ? AND is_current = 1
        """, (project_id, fact_key))
    
    # Insert the new fact
    cursor.execute("""
        INSERT INTO project_facts (
            fact_id, project_id, fact_key, value_text, value_type,
            confidence, source_message_uuid, created_at, effective_at,
            supersedes_fact_id, is_current
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        fact_id, project_id, fact_key, value_text, value_type,
        confidence, source_message_uuid, created_at, effective_at,
        supersedes_fact_id
    ))
    
    conn.commit()
    conn.close()
    return (fact_id, action_type)


def get_current_fact(project_id: str, fact_key: str, source_id: Optional[str] = None) -> Optional[dict]:
    """
    Get the current fact for a given fact_key.
    
    Args:
        project_id: Project ID
        fact_key: Fact key to look up
        source_id: Optional source ID (uses project-based source if not provided)
        
    Returns:
        Dict with fact data or None if not found
    """
    if source_id is None:
        source_id = f"project-{project_id}"
    
    init_db(source_id, project_id=project_id)
    conn = get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fact_id, project_id, fact_key, value_text, value_type,
               confidence, source_message_uuid, created_at, effective_at,
               supersedes_fact_id, is_current
        FROM project_facts
        WHERE project_id = ? AND fact_key = ? AND is_current = 1
        ORDER BY effective_at DESC, created_at DESC
        LIMIT 1
    """, (project_id, fact_key))
    
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return None
    
    return {
        "fact_id": row["fact_id"],
        "project_id": row["project_id"],
        "fact_key": row["fact_key"],
        "value_text": row["value_text"],
        "value_type": row["value_type"],
        "confidence": row["confidence"],
        "source_message_uuid": row["source_message_uuid"],
        "created_at": datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"],
        "effective_at": datetime.fromisoformat(row["effective_at"]) if isinstance(row["effective_at"], str) else row["effective_at"],
        "supersedes_fact_id": row["supersedes_fact_id"],
        "is_current": bool(row["is_current"])
    }


def search_current_facts(project_id: str, query: str, limit: int = 10, source_id: Optional[str] = None, exclude_message_uuid: Optional[str] = None) -> List[dict]:
    """
    Search current facts by fact_key or value_text.
    
    Extracts keywords from the query to improve matching (e.g., "What is my favorite color?"
    will match facts with "color" in the key or value).
    
    Args:
        project_id: Project ID
        query: Search query (searches fact_key and value_text)
        limit: Maximum number of results
        source_id: Optional source ID (uses project-based source if not provided)
        exclude_message_uuid: Optional message UUID to exclude from results
                             (prevents Facts-R from counting facts just stored in current message)
        
    Returns:
        List of fact dicts matching the query (excluding facts from exclude_message_uuid if provided)
    """
    if source_id is None:
        source_id = f"project-{project_id}"
    
    init_db(source_id, project_id=project_id)
    conn = get_db_connection(source_id, project_id=project_id)
    cursor = conn.cursor()
    
    # Extract meaningful keywords from query (remove common question words)
    import re
    query_lower = query.lower()
    # Remove common question words and stop words
    stop_words = {'what', 'is', 'my', 'your', 'the', 'a', 'an', 'do', 'you', 'remember', 'know', 'tell', 'me', 'about'}
    words = re.findall(r'\b\w+\b', query_lower)
    keywords = [w for w in words if w not in stop_words and len(w) > 2]
    
    # If no keywords extracted, use the original query
    if not keywords:
        keywords = [query_lower]
    
    # Build search patterns for each keyword
    search_patterns = [f"%{kw}%" for kw in keywords]
    
    # Build SQL with OR conditions for each keyword
    conditions = []
    params = [project_id]
    for pattern in search_patterns:
        conditions.append("(fact_key LIKE ? OR value_text LIKE ?)")
        params.extend([pattern, pattern])
    
    # Combine all conditions with OR, then wrap in parentheses
    if conditions:
        search_condition = f"({' OR '.join(conditions)})"
    else:
        # Fallback: use original query if no keywords extracted
        search_pattern = f"%{query}%"
        search_condition = "(fact_key LIKE ? OR value_text LIKE ?)"
        params.extend([search_pattern, search_pattern])
    
    # Add exclusion filter if exclude_message_uuid is provided
    # This prevents Facts-R from counting facts that were just stored in the current message
    exclusion_condition = ""
    if exclude_message_uuid:
        exclusion_condition = "AND source_message_uuid != ?"
        params.append(exclude_message_uuid)
    
    cursor.execute(f"""
        SELECT fact_id, project_id, fact_key, value_text, value_type,
               confidence, source_message_uuid, created_at, effective_at,
               supersedes_fact_id, is_current
        FROM project_facts
        WHERE project_id = ? AND is_current = 1 AND {search_condition} {exclusion_condition}
        ORDER BY effective_at DESC, created_at DESC
        LIMIT ?
    """, params + [limit])
    
    rows = cursor.fetchall()
    conn.close()
    
    # Build results with schema_hint derived from fact_key for ranked lists
    results = []
    for row in rows:
        fact_dict = {
            "fact_id": row["fact_id"],
            "project_id": row["project_id"],
            "fact_key": row["fact_key"],
            "value_text": row["value_text"],
            "value_type": row["value_type"],
            "confidence": row["confidence"],
            "source_message_uuid": row["source_message_uuid"],
            "created_at": datetime.fromisoformat(row["created_at"]) if isinstance(row["created_at"], str) else row["created_at"],
            "effective_at": datetime.fromisoformat(row["effective_at"]) if isinstance(row["effective_at"], str) else row["effective_at"],
            "supersedes_fact_id": row["supersedes_fact_id"],
            "is_current": bool(row["is_current"])
        }
        
        # Derive schema_hint from fact_key for ranked lists (user.favorites.*)
        fact_key = row["fact_key"]
        if fact_key.startswith("user.favorites."):
            # Parse: user.favorites.<topic>.<rank>
            parts = fact_key.split(".")
            if len(parts) >= 3:
                topic = parts[2]  # Extract topic
                fact_dict["schema_hint"] = {
                    "domain": "ranked_list",
                    "topic": topic,
                    "key": fact_key,
                    "key_prefix": f"user.favorites.{topic}"  # For aggregation queries
                }
        
        results.append(fact_dict)
    
    return results
