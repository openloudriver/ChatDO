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

from memory_service.config import DB_PATH
from memory_service.models import Source, File, Chunk, Embedding, SearchResult


def get_db_connection():
    """Get a database connection."""
    # Ensure the directory exists
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize the database schema."""
    conn = get_db_connection()
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
    
    # Chunks table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            start_char INTEGER NOT NULL,
            end_char INTEGER NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(id),
            UNIQUE(file_id, chunk_index)
        )
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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_embeddings_chunk ON embeddings(chunk_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_project ON sources(project_id)")
    
    conn.commit()
    conn.close()


def upsert_source(source_id: str, project_id: str, root_path: str, 
                  include_glob: Optional[str] = None, exclude_glob: Optional[str] = None) -> int:
    """Insert or update a source. Returns the database ID."""
    conn = get_db_connection()
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
    conn = get_db_connection()
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


def get_file_by_path(source_id: int, path: str) -> Optional[File]:
    """Get a file by source_id and path."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM files WHERE source_id = ? AND path = ?", (source_id, path))
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


def upsert_file(source_id: int, path: str, filetype: str, 
                modified_at: datetime, size_bytes: int, content_hash: Optional[str] = None) -> int:
    """Insert or update a file. Returns the database ID."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO files (source_id, path, filetype, modified_at, size_bytes, hash)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, path) DO UPDATE SET
            filetype = excluded.filetype,
            modified_at = excluded.modified_at,
            size_bytes = excluded.size_bytes,
            hash = excluded.hash
    """, (source_id, path, filetype, modified_at, size_bytes, content_hash))
    
    db_id = cursor.lastrowid
    if db_id == 0:
        cursor.execute("SELECT id FROM files WHERE source_id = ? AND path = ?", (source_id, path))
        db_id = cursor.fetchone()["id"]
    
    conn.commit()
    conn.close()
    return db_id


def delete_file(file_id: int):
    """Delete a file and all its chunks and embeddings."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Delete embeddings first (foreign key constraint)
    cursor.execute("DELETE FROM embeddings WHERE chunk_id IN (SELECT id FROM chunks WHERE file_id = ?)", (file_id,))
    # Delete chunks
    cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    # Delete file
    cursor.execute("DELETE FROM files WHERE id = ?", (file_id,))
    
    conn.commit()
    conn.close()


def delete_file_by_path(source_id: int, path: str):
    """Delete a file by path."""
    file = get_file_by_path(source_id, path)
    if file:
        delete_file(file.id)


def insert_chunks(file_id: int, chunks: List[Tuple[int, str, int, int]]):
    """Insert chunks for a file. chunks is a list of (chunk_index, text, start_char, end_char)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Delete existing chunks
    cursor.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    
    # Insert new chunks
    cursor.executemany("""
        INSERT INTO chunks (file_id, chunk_index, text, start_char, end_char)
        VALUES (?, ?, ?, ?, ?)
    """, [(file_id, idx, text, start, end) for idx, text, start, end in chunks])
    
    conn.commit()
    conn.close()


def get_chunks_by_file_id(file_id: int) -> List[Chunk]:
    """Get all chunks for a file."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM chunks WHERE file_id = ? ORDER BY chunk_index", (file_id,))
    rows = cursor.fetchall()
    conn.close()
    
    return [Chunk(
        id=row["id"],
        file_id=row["file_id"],
        chunk_index=row["chunk_index"],
        text=row["text"],
        start_char=row["start_char"],
        end_char=row["end_char"]
    ) for row in rows]


def insert_embeddings(chunk_ids: List[int], embeddings: np.ndarray, model_name: str):
    """Insert embeddings for chunks. embeddings should be shape [N, D]."""
    conn = get_db_connection()
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


def get_all_embeddings_for_project(project_id: str, model_name: str) -> List[Tuple[int, np.ndarray, int, str, str, str, str]]:
    """
    Get all embeddings for a project.
    Returns list of (chunk_id, embedding_vector, file_id, file_path, chunk_text, source_id, project_id).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT e.chunk_id, e.embedding, c.file_id, f.path, c.text, s.source_id, s.project_id, f.filetype, c.chunk_index, c.start_char, c.end_char
        FROM embeddings e
        JOIN chunks c ON e.chunk_id = c.id
        JOIN files f ON c.file_id = f.id
        JOIN sources s ON f.source_id = s.id
        WHERE s.project_id = ? AND e.model_name = ?
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
            row["end_char"]
        ))
    
    return results


def compute_file_hash(path: Path) -> str:
    """Compute SHA256 hash of file contents."""
    hasher = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

