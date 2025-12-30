"""
Unit tests for Facts parsing utilities.

Tests the centralized parse_bulk_preference_values() function to ensure
robust parsing of comma-separated preference lists with Oxford commas.
"""
import pytest
from server.services.facts_parsing import parse_bulk_preference_values


class TestParseBulkPreferenceValues:
    """Test cases for parse_bulk_preference_values()."""
    
    def test_oxford_comma_three_items(self):
        """Test Oxford comma with three items."""
        result = parse_bulk_preference_values("Spain, Greece, and Thailand.")
        assert result == ["Spain", "Greece", "Thailand"]
    
    def test_oxford_comma_mystery_biography_fantasy(self):
        """Test the specific v70 failure case."""
        result = parse_bulk_preference_values("Mystery, Biography, and Fantasy.")
        assert result == ["Mystery", "Biography", "Fantasy"]
    
    def test_non_oxford_comma(self):
        """Test non-Oxford comma format."""
        result = parse_bulk_preference_values("A, B and C")
        assert result == ["A", "B", "C"]
    
    def test_two_items_with_and(self):
        """Test two items with 'and'."""
        result = parse_bulk_preference_values("A and B")
        assert result == ["A", "B"]
    
    def test_three_items_no_and(self):
        """Test three items without 'and'."""
        result = parse_bulk_preference_values("A, B, C")
        assert result == ["A", "B", "C"]
    
    def test_deduplication_case_insensitive(self):
        """Test deduplication preserves first casing."""
        result = parse_bulk_preference_values("A, a, A")
        assert result == ["A"]  # First casing preserved
    
    def test_quoted_values(self):
        """Test quoted values are unquoted."""
        result = parse_bulk_preference_values('"Sci-Fi", Fantasy, and History!')
        assert result == ["Sci-Fi", "Fantasy", "History"]
    
    def test_trailing_punctuation(self):
        """Test trailing punctuation is removed."""
        result = parse_bulk_preference_values("Spain, Greece, and Thailand!")
        assert result == ["Spain", "Greece", "Thailand"]
    
    def test_greece_and_thailand_edge_case(self):
        """Test edge case: 'Greece, and Thailand' (no leading item)."""
        result = parse_bulk_preference_values("Greece, and Thailand")
        assert result == ["Greece", "Thailand"]  # No "and Thailand" token
    
    def test_empty_string(self):
        """Test empty string returns empty list."""
        result = parse_bulk_preference_values("")
        assert result == []
    
    def test_whitespace_normalization(self):
        """Test whitespace is normalized."""
        result = parse_bulk_preference_values("  Spain  ,  Greece  ,  and  Thailand  ")
        assert result == ["Spain", "Greece", "Thailand"]
    
    def test_single_item(self):
        """Test single item."""
        result = parse_bulk_preference_values("Spain")
        assert result == ["Spain"]
    
    def test_single_item_with_trailing_punctuation(self):
        """Test single item with trailing punctuation."""
        result = parse_bulk_preference_values("Spain.")
        assert result == ["Spain"]
    
    def test_four_items_oxford(self):
        """Test four items with Oxford comma."""
        result = parse_bulk_preference_values("A, B, C, and D")
        assert result == ["A", "B", "C", "D"]
    
    def test_four_items_non_oxford(self):
        """Test four items without Oxford comma."""
        result = parse_bulk_preference_values("A, B, C and D")
        assert result == ["A", "B", "C", "D"]
    
    def test_mixed_case_deduplication(self):
        """Test deduplication with mixed case."""
        result = parse_bulk_preference_values("Spain, spain, SPAIN")
        assert result == ["Spain"]  # First casing preserved

