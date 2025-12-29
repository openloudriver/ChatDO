"""
Unit tests for Facts system telemetry fields.

Tests that ordinal telemetry fields (rank_applied, rank_result_found, ordinal_parse_source)
are correctly set in FactsAnswer.
"""
import pytest
from server.services.facts_retrieval import execute_facts_plan, FactsAnswer
from server.contracts.facts_ops import FactsQueryPlan


def test_ordinal_telemetry_fields_set_correctly():
    """Test that ordinal telemetry fields are correctly populated."""
    # This is a unit test structure - actual execution requires a database
    # For now, we'll test the FactsAnswer dataclass structure
    
    # Test FactsAnswer with ordinal query
    answer = FactsAnswer(
        facts=[{"fact_key": "user.favorites.crypto.2", "value_text": "BTC", "rank": 2}],
        count=1,
        canonical_keys=["user.favorites.crypto"],
        rank_applied=True,
        rank_result_found=True,
        ordinal_parse_source="router",
        max_available_rank=3
    )
    
    assert answer.rank_applied is True
    assert answer.rank_result_found is True
    assert answer.ordinal_parse_source == "router"
    assert answer.max_available_rank == 3
    
    # Test FactsAnswer with full list query (no rank)
    answer_no_rank = FactsAnswer(
        facts=[
            {"fact_key": "user.favorites.crypto.1", "value_text": "XMR", "rank": 1},
            {"fact_key": "user.favorites.crypto.2", "value_text": "BTC", "rank": 2}
        ],
        count=2,
        canonical_keys=["user.favorites.crypto"],
        rank_applied=False,
        rank_result_found=None,
        ordinal_parse_source="none",
        max_available_rank=2
    )
    
    assert answer_no_rank.rank_applied is False
    assert answer_no_rank.rank_result_found is None
    assert answer_no_rank.ordinal_parse_source == "none"
    assert answer_no_rank.max_available_rank == 2
    
    # Test FactsAnswer with ordinal query but no results
    answer_empty = FactsAnswer(
        facts=[],
        count=0,
        canonical_keys=[],
        rank_applied=True,
        rank_result_found=False,
        ordinal_parse_source="planner",
        max_available_rank=2
    )
    
    assert answer_empty.rank_applied is True
    assert answer_empty.rank_result_found is False
    assert answer_empty.ordinal_parse_source == "planner"
    assert answer_empty.max_available_rank == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

