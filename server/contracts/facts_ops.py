"""
Facts JSON Operations Contracts.

Defines Pydantic models for Facts write operations (Ops) and read operations (Plan).
"""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field


class FactsOp(BaseModel):
    """
    A single fact operation to apply.
    
    Operations:
    - set: Generic fact set (fact_key + value)
    - ranked_list_set: Set a ranked list item (list_key + rank + value)
    - ranked_list_clear: Clear all ranks for a list_key (optional, rarely used)
    """
    op: Literal["set", "ranked_list_set", "ranked_list_clear"] = Field(
        ...,
        description="Operation type"
    )
    fact_key: Optional[str] = Field(
        None,
        description="Full fact key for 'set' operation (e.g., 'user.email')"
    )
    list_key: Optional[str] = Field(
        None,
        description="List key for ranked list operations (e.g., 'user.favorites.crypto')"
    )
    rank: Optional[int] = Field(
        None,
        ge=1,
        description="Rank number (1-based) for ranked_list_set operation"
    )
    value: Optional[str] = Field(
        None,
        description="Fact value to set"
    )
    confidence: Optional[float] = Field(
        1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0 to 1.0)"
    )


class FactsOpsResponse(BaseModel):
    """
    Response from Facts LLM containing operations to apply.
    
    If needs_clarification is non-empty, no operations should be applied.
    """
    ops: List[FactsOp] = Field(
        default_factory=list,
        description="List of fact operations to apply"
    )
    needs_clarification: List[str] = Field(
        default_factory=list,
        description="List of clarification questions if topic/intent is ambiguous"
    )
    notes: List[str] = Field(
        default_factory=list,
        description="Optional notes from the LLM (for debugging)"
    )


class FactsQueryPlan(BaseModel):
    """
    Query plan for Facts retrieval (Facts-R).
    
    The LLM produces this plan from a user query, then it's executed deterministically.
    """
    intent: Literal[
        "facts_get_ranked_list",
        "facts_get_by_prefix",
        "facts_get_exact_key"
    ] = Field(
        ...,
        description="Query intent type"
    )
    list_key: Optional[str] = Field(
        None,
        description="List key for ranked list queries (e.g., 'user.favorites.crypto')"
    )
    topic: Optional[str] = Field(
        None,
        description="Topic name for ranked list queries (e.g., 'crypto')"
    )
    key_prefix: Optional[str] = Field(
        None,
        description="Key prefix for prefix queries (e.g., 'user.favorites.crypto')"
    )
    fact_key: Optional[str] = Field(
        None,
        description="Exact fact key for exact key queries"
    )
    limit: int = Field(
        100,  # Increased default for unbounded model
        ge=1,
        le=1000,  # Increased max for pagination (not a storage limit)
        description="Maximum number of facts to return (pagination only, not a storage limit)"
    )
    include_ranks: bool = Field(
        True,
        description="Whether to include rank information in results"
    )
    rank: Optional[int] = Field(
        None,
        ge=1,
        description="Specific rank to retrieve (1-based) for ordinal queries like 'second favorite' (e.g., 2 for 'second', 3 for 'third')"
    )

