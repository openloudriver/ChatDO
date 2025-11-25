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

