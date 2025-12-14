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
class ChatMessage:
    """Represents an indexed chat message."""
    id: int
    source_id: int
    project_id: str
    chat_id: str
    message_id: str
    role: str
    content: str
    timestamp: datetime
    message_index: int


@dataclass
class Chunk:
    """Represents a text chunk from a file or chat message."""
    id: int
    file_id: Optional[int]
    chat_message_id: Optional[int]
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
    file_path: Optional[str]  # None for chat messages
    filetype: Optional[str]  # None for chat messages
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    source_type: str = "file"  # "file" or "chat"
    chat_id: Optional[str] = None  # For chat messages
    message_id: Optional[str] = None  # For chat messages


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


@dataclass
class Fact:
    """Represents a structured fact (ranked list item or single preference)."""
    id: int
    project_id: str
    chat_id: Optional[str]
    topic_key: str  # Normalized topic key (e.g., "favorite_colors", "favorite_tv_show")
    kind: str  # "ranked" or "single"
    rank: Optional[int]  # For ranked lists (1-based), None for single facts
    value: str  # The actual fact value
    source_message_id: str  # ID of the message that contained this fact
    created_at: datetime


# FileTree models (Phase 1)
from pydantic import BaseModel
from typing import List


class FileTreeNode(BaseModel):
    """Represents a file or directory node in the file tree."""
    name: str  # file or directory name (no path)
    path: str  # normalized POSIX-style path relative to source root (e.g. "docs/README.md")
    is_dir: bool
    size_bytes: Optional[int] = None
    modified_at: Optional[datetime] = None
    children: Optional[List["FileTreeNode"]] = None  # only populated when depth > 0 and is_dir=True


# Update forward refs for recursive model
FileTreeNode.model_rebuild()


class FileTreeResponse(BaseModel):
    """Response for directory tree listing."""
    source_id: str
    root: FileTreeNode


class FileReadResponse(BaseModel):
    """Response for file content reading."""
    source_id: str
    path: str  # relative path from source root
    encoding: Optional[str] = None  # e.g. "utf-8" or "binary"
    size_bytes: int
    content: Optional[str] = None  # for text mode
    truncated: bool  # True if we cut at max_bytes
    is_binary: bool = False  # True if file is detected as binary

