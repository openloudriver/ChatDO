"""
Data models for Memory Service.

Defines the structure of sources, files, chunks, and embeddings.
"""
from datetime import datetime
from typing import Optional
from dataclasses import dataclass


@dataclass
class Source:
    """Represents an indexed source folder."""
    id: int
    project_id: str
    root_path: str
    include_glob: Optional[str]
    exclude_glob: Optional[str]
    created_at: datetime
    updated_at: datetime


@dataclass
class File:
    """Represents an indexed file."""
    id: int
    source_id: int
    path: str
    filetype: str
    modified_at: datetime
    size_bytes: int
    hash: Optional[str]


@dataclass
class Chunk:
    """Represents a text chunk from a file."""
    id: int
    file_id: int
    chunk_index: int
    text: str
    start_char: int
    end_char: int


@dataclass
class Embedding:
    """Represents an embedding vector for a chunk."""
    id: int
    chunk_id: int
    embedding: bytes  # Serialized numpy array
    model_name: str


@dataclass
class SearchResult:
    """Represents a search result with similarity score."""
    score: float
    project_id: str
    source_id: str
    file_path: str
    filetype: str
    chunk_index: int
    text: str
    start_char: int
    end_char: int


@dataclass
class SourceStatus:
    """Represents the status and stats of a source."""
    id: str
    display_name: str
    root_path: str
    status: str  # "idle" | "indexing" | "error" | "disabled"
    files_indexed: int
    bytes_indexed: int
    last_index_started_at: Optional[datetime]
    last_index_completed_at: Optional[datetime]
    last_error: Optional[str]
    project_id: Optional[str] = None


@dataclass
class IndexJob:
    """Represents an indexing job."""
    id: int
    source_id: str
    status: str  # "running" | "completed" | "failed" | "cancelled"
    started_at: datetime
    completed_at: Optional[datetime]
    files_total: Optional[int]
    files_processed: int
    bytes_processed: int
    error: Optional[str]

