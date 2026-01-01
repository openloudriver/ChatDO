"""
Unit tests for topic canonicalization consistency.

Tests that singular/plural and compound topics resolve to the same list_key.
"""
import pytest
from server.services.facts_normalize import canonical_ranked_topic_key


def test_singular_plural_normalization():
    """Test that singular and plural forms resolve to the same list_key."""
    test_cases = [
        ("weekend breakfasts", "weekend breakfast"),
        ("sci-fi movies", "sci-fi movie"),
        ("board games", "board game"),
        ("favorite colors", "favorite color"),
        ("vacation destinations", "vacation destination"),
    ]
    
    for plural, singular in test_cases:
        plural_key = canonical_ranked_topic_key(plural)
        singular_key = canonical_ranked_topic_key(singular)
        assert plural_key == singular_key, \
            f"Singular/plural mismatch: '{plural}' -> {plural_key!r}, " \
            f"'{singular}' -> {singular_key!r}. They must resolve to the same list_key."


def test_compound_topic_preservation():
    """Test that compound topics are preserved and not collapsed to base nouns."""
    test_cases = [
        # Compound topics should NOT collapse to base nouns
        ("weekend breakfast", "breakfast"),  # Should be different
        ("sci-fi movies", "movies"),  # Should be different (after removing "favorite" from "favorite movies" if present)
        ("board games", "games"),  # Should be different
    ]
    
    for compound, base in test_cases:
        compound_key = canonical_ranked_topic_key(compound)
        base_key = canonical_ranked_topic_key(base)
        assert compound_key != base_key, \
            f"Compound topic collapsed to base noun: '{compound}' -> {compound_key!r}, " \
            f"'{base}' -> {base_key!r}. Compound topics must be preserved."
    
    # Special case: "favorite colors" should collapse to "color" (favorite is a prefix, not a modifier)
    # This is expected behavior - "favorite" is removed, then "colors" → "color"
    favorite_colors_key = canonical_ranked_topic_key("favorite colors")
    colors_key = canonical_ranked_topic_key("colors")
    assert favorite_colors_key == colors_key, \
        f"'favorite colors' should collapse to 'colors' after removing 'favorite' prefix: " \
        f"{favorite_colors_key!r} vs {colors_key!r}"


def test_whitespace_and_separator_normalization():
    """Test that different separators (spaces, hyphens, underscores) normalize to the same key."""
    test_cases = [
        ("weekend breakfasts", "weekend-breakfasts", "weekend_breakfasts"),
        ("sci-fi movies", "sci fi movies", "sci_fi_movies"),
        ("board games", "board-games", "board_games"),
    ]
    
    for variants in test_cases:
        keys = [canonical_ranked_topic_key(variant) for variant in variants]
        assert len(set(keys)) == 1, \
            f"Separator normalization failed: {variants} -> {keys}. " \
            f"All variants must resolve to the same list_key: {keys[0]!r}"


def test_favorite_prefix_removal():
    """Test that 'favorite(s)' prefix is removed but topic is preserved."""
    test_cases = [
        ("my favorite weekend breakfasts", "weekend breakfasts"),
        ("favorites weekend breakfasts", "weekend breakfasts"),
        ("my favorite colors", "colors"),
    ]
    
    for with_favorite, without_favorite in test_cases:
        with_key = canonical_ranked_topic_key(with_favorite)
        without_key = canonical_ranked_topic_key(without_favorite)
        assert with_key == without_key, \
            f"'favorite(s)' prefix not removed correctly: '{with_favorite}' -> {with_key!r}, " \
            f"'{without_favorite}' -> {without_key!r}. They must resolve to the same list_key."

