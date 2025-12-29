"""
Tests for duplicate prevention in favorites (unranked appends).

Tests that variations like "Reese's", "Reese's.", "reese's " all count as the same value.
"""
import pytest
from server.services.facts_apply import normalize_favorite_value


def test_normalize_favorite_value_exact():
    """Test that exact match normalizes correctly."""
    assert normalize_favorite_value("Reese's") == "reese's"


def test_normalize_favorite_value_trailing_period():
    """Test that trailing period is stripped."""
    assert normalize_favorite_value("Reese's.") == "reese's"


def test_normalize_favorite_value_whitespace():
    """Test that whitespace is normalized."""
    assert normalize_favorite_value("  reese's  ") == "reese's"


def test_normalize_favorite_value_unicode_apostrophe():
    """Test that unicode apostrophe (') is normalized to ASCII (')."""
    # Using right single quotation mark (U+2019)
    assert normalize_favorite_value("Reese's") == "reese's"


def test_normalize_favorite_value_case_insensitive():
    """Test that case is normalized to lowercase."""
    assert normalize_favorite_value("REESE'S") == "reese's"
    assert normalize_favorite_value("Reese'S") == "reese's"


def test_normalize_favorite_value_multiple_punctuation():
    """Test that multiple trailing punctuation is stripped."""
    assert normalize_favorite_value("Reese's!!!") == "reese's"
    assert normalize_favorite_value("Reese's...") == "reese's"


def test_normalize_favorite_value_internal_whitespace():
    """Test that internal whitespace is collapsed to single spaces."""
    assert normalize_favorite_value("Reese  's") == "reese 's"
    assert normalize_favorite_value("Reese\t's") == "reese 's"


def test_normalize_favorite_value_empty():
    """Test that empty string normalizes to empty string."""
    assert normalize_favorite_value("") == ""
    assert normalize_favorite_value("   ") == ""


def test_normalize_favorite_value_all_variations_match():
    """Test that all variations normalize to the same value."""
    variations = [
        "Reese's",
        "Reese's.",
        "  reese's  ",
        "Reese's",  # smart quote
        "REESE'S",
        "Reese's!!!",
    ]
    
    normalized = [normalize_favorite_value(v) for v in variations]
    # All should normalize to the same value
    assert len(set(normalized)) == 1, f"Variations did not normalize to same value: {normalized}"
    assert normalized[0] == "reese's"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

