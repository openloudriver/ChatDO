"""
Discovery Contract - Unified schema for Facts, Index, and Files discovery.

This module defines the canonical data models for unified discovery across
all three domains (Facts, Index, Files) with consistent deep-linking support.
"""
from typing import List, Optional, Dict, Literal, Any
from pydantic import BaseModel, Field
from datetime import datetime


class DiscoveryQuery(BaseModel):
    """Query parameters for unified discovery search."""
    query: str = Field(..., description="Search query string")
    scope: List[Literal["facts", "index", "files"]] = Field(
        default=["facts", "index", "files"],
        description="Which domains to search (default: all)"
    )
    limit: int = Field(default=20, ge=1, le=100, description="Maximum hits per domain")
    offset: int = Field(default=0, ge=0, description="Offset for pagination")
    chat_id: Optional[str] = Field(None, description="Optional chat ID filter")
    project_id: Optional[str] = Field(None, description="Project ID (required for Facts/Index)")
    filters: Optional[Dict[str, Any]] = Field(
        None,
        description="Future: additional domain-specific filters"
    )


class DiscoverySource(BaseModel):
    """
    Source metadata for deep linking and provenance.
    
    Each hit can have multiple sources (e.g., a fact from a chat message,
    or a file chunk from a specific file).
    """
    kind: Literal["chat_message", "file", "fact"] = Field(
        ...,
        description="Type of source: chat_message, file, or fact"
    )
    
    # Chat message deep linking
    source_message_uuid: Optional[str] = Field(
        None,
        description="Stable UUID of the chat message (for deep linking to chat messages)"
    )
    source_chat_id: Optional[str] = Field(
        None,
        description="Chat ID containing the message (for navigation context)"
    )
    
    # File deep linking
    source_file_id: Optional[str] = Field(
        None,
        description="File ID (for deep linking to files)"
    )
    source_file_path: Optional[str] = Field(
        None,
        description="File path relative to source root (for deep linking to files)"
    )
    
    # Fact deep linking
    source_fact_id: Optional[str] = Field(
        None,
        description="Fact ID (for fact-specific deep linking)"
    )
    
    # Additional metadata
    snippet: Optional[str] = Field(
        None,
        description="Snippet of source content for preview"
    )
    created_at: Optional[str] = Field(
        None,
        description="ISO format timestamp when source was created"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional domain-specific metadata"
    )


class DiscoveryHit(BaseModel):
    """
    A single discovery result from any domain (Facts, Index, or Files).
    
    All hits share the same structure for unified rendering and ranking.
    """
    id: str = Field(
        ...,
        description="Stable per-hit ID: facts:<fact_id>, index:<message_uuid>:<chunk_id>, files:<file_id>:<chunk_id>"
    )
    domain: Literal["facts", "index", "files"] = Field(
        ...,
        description="Which domain this hit came from"
    )
    type: str = Field(
        ...,
        description="Hit type: 'fact', 'chat_chunk', 'file_chunk', 'file_metadata'"
    )
    title: Optional[str] = Field(
        None,
        description="Display title (e.g., fact key, file name, message preview)"
    )
    text: str = Field(
        ...,
        description="Primary display text (fact value, chunk content, file metadata)"
    )
    score: Optional[float] = Field(
        None,
        description="Relevance score (0.0 to 1.0, higher is better)"
    )
    rank: Optional[int] = Field(
        None,
        description="Rank within domain (for ranked lists like favorite colors)"
    )
    sources: List[DiscoverySource] = Field(
        default_factory=list,
        description="Source metadata for deep linking (typically one source per hit)"
    )
    meta: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional domain-specific metadata"
    )


class DiscoveryResponse(BaseModel):
    """
    Unified response from discovery search across all domains.
    
    Includes hits, counts, timings, and degraded status for observability.
    """
    query: str = Field(..., description="Original query string")
    hits: List[DiscoveryHit] = Field(
        default_factory=list,
        description="Merged and ranked hits from all domains"
    )
    counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Per-domain hit counts: {'facts': 5, 'index': 10, 'files': 3}"
    )
    timings_ms: Dict[str, float] = Field(
        default_factory=dict,
        description="Per-domain query timings in milliseconds: {'facts': 45.2, 'index': 123.5, 'files': 67.8}"
    )
    degraded: Dict[str, str] = Field(
        default_factory=dict,
        description="Degraded status per domain: {'index': 'timeout', 'files_content': 'unavailable'}"
    )

