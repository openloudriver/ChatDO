"""
Routing Plan Contract - Strict schema for Nano router output.

Defines the deterministic routing plan that GPT-5 Nano produces for every message.
This plan includes extracted candidates to avoid double Nano calls.
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class FactsWriteCandidate(BaseModel):
    """Extracted fact candidate for write operations."""
    topic: str = Field(..., description="Topic name (e.g., 'candy', 'crypto', 'color')")
    value: str | List[str] = Field(..., description="Fact value(s) - string for single, list for multiple")
    rank_ordered: bool = Field(
        False,
        description="Whether the values are rank-ordered (true for 'My favorites are X, Y, Z')"
    )


class FactsReadCandidate(BaseModel):
    """Extracted query candidate for read operations."""
    topic: str = Field(..., description="Topic to query (e.g., 'candy', 'crypto')")
    query: str = Field(..., description="Original query text for context")


class IndexCandidate(BaseModel):
    """Extracted query candidate for index search."""
    query: str = Field(..., description="Search query for conversational history")


class FilesCandidate(BaseModel):
    """Extracted query candidate for file operations."""
    query: str = Field(..., description="File query or operation")
    path_hint: Optional[str] = Field(None, description="Optional file path hint if mentioned")


class RoutingPlan(BaseModel):
    """
    Strict routing plan from GPT-5 Nano.
    
    This schema enforces deterministic routing with extracted candidates
    to avoid double Nano calls for Facts extraction.
    """
    content_plane: Literal["facts", "index", "files", "chat"] = Field(
        ...,
        description="Content plane to route to"
    )
    operation: Literal["write", "read", "search", "none"] = Field(
        ...,
        description="Operation type within the content plane"
    )
    reasoning_required: bool = Field(
        ...,
        description="Whether GPT-5 reasoning is required (false for simple confirmations)"
    )
    facts_write_candidate: Optional[FactsWriteCandidate] = Field(
        None,
        description="Extracted fact candidate for facts/write operations"
    )
    facts_read_candidate: Optional[FactsReadCandidate] = Field(
        None,
        description="Extracted query candidate for facts/read operations"
    )
    index_candidate: Optional[IndexCandidate] = Field(
        None,
        description="Extracted query candidate for index/search operations"
    )
    files_candidate: Optional[FilesCandidate] = Field(
        None,
        description="Extracted query candidate for files operations"
    )
    confidence: float = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score for the routing decision (0.0 to 1.0)"
    )
    why: str = Field(
        "",
        description="Short explanation for logs (why this routing was chosen)"
    )

