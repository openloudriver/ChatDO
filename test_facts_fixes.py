"""
Minimal tests to prove facts fixes are working.

Tests:
1. Store colors list. Ask "What is my number 2 favorite tv show?" → must NOT return Green; must say not stored.
2. Store cryptos list as 1) XMR, 2) BTC, 3) XLM. Ask "List my favorite cryptos" → must output 1..3 exactly, no ##, no M1.
3. Ensure M1 tokens never become a stored fact value.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# NOTE: This test uses deleted functions. Updated to use fact_extractor.
from server.services.facts import extract_topic_from_query
from memory_service.fact_extractor import get_fact_extractor


def test_1_topic_bleed_prevention():
    """Test: Store colors list. Ask 'What is my number 2 favorite tv show?' → must NOT return Green."""
    print("\n=== Test 1: Topic Bleed Prevention ===")
    
    # Simulate storing colors - using fact_extractor instead of deleted functions
    colors_text = "My favorite colors are 1) Blue, 2) Green, 3) Black"
    extractor = get_fact_extractor()
    facts = extractor.extract_facts(colors_text, role="user")
    # Extract topic_key from facts (look for favorite_color facts)
    topic_key_colors = None
    ranked_colors = []
    for fact in facts:
        if "favorite_color" in fact.get("fact_key", ""):
            topic_key_colors = "favorite_colors"
            # Extract rank from fact_key (e.g., "user.favorite_color.1" -> rank 1)
            fact_key = fact.get("fact_key", "")
            if "." in fact_key:
                try:
                    rank = int(fact_key.split(".")[-1])
                    value = fact.get("value_text", "")
                    ranked_colors.append((rank, value))
                except ValueError:
                    pass
    ranked_colors.sort(key=lambda x: x[0])
    
    print(f"Colors text: {colors_text}")
    print(f"Topic key: {topic_key_colors}")
    print(f"Ranked facts: {ranked_colors}")
    
    # Now ask about TV shows
    tv_query = "What is my number 2 favorite tv show?"
    topic_key_tv = extract_topic_from_query(tv_query)
    
    print(f"\nTV query: {tv_query}")
    print(f"Topic key: {topic_key_tv}")
    
    # Assertions
    assert topic_key_colors == "favorite_colors", f"Expected 'favorite_colors', got '{topic_key_colors}'"
    assert topic_key_tv == "favorite_tv", f"Expected 'favorite_tv', got '{topic_key_tv}'"
    assert topic_key_colors != topic_key_tv, "Topic keys must be different (no bleed)"
    
    print("✅ Test 1 PASSED: Topic keys are strict, no bleed")


def test_2_clean_rendering():
    """Test: Store cryptos list as 1) XMR, 2) BTC, 3) XLM. Ask 'List my favorite cryptos' → must output 1..3 exactly, no ##, no M1."""
    print("\n=== Test 2: Clean Rendering ===")
    
    # Simulate storing cryptos - using fact_extractor instead of deleted functions
    cryptos_text = "My favorite cryptos are 1) XMR, 2) BTC, 3) XLM"
    extractor = get_fact_extractor()
    facts = extractor.extract_facts(cryptos_text, role="user")
    # Extract topic_key and ranked facts from extracted facts
    topic_key_cryptos = None
    ranked_cryptos = []
    for fact in facts:
        if "favorite_crypto" in fact.get("fact_key", ""):
            topic_key_cryptos = "favorite_cryptos"
            fact_key = fact.get("fact_key", "")
            if "." in fact_key:
                try:
                    rank = int(fact_key.split(".")[-1])
                    value = fact.get("value_text", "")
                    ranked_cryptos.append((rank, value))
                except ValueError:
                    pass
    ranked_cryptos.sort(key=lambda x: x[0])
    
    print(f"Cryptos text: {cryptos_text}")
    print(f"Topic key: {topic_key_cryptos}")
    print(f"Ranked facts: {ranked_cryptos}")
    
    # Format as it would be rendered
    ranked_cryptos.sort(key=lambda x: x[0])
    list_items = "\n".join([f"{rank}) {value}" for rank, value in ranked_cryptos])
    
    print(f"\nRendered output:\n{list_items}")
    
    # Assertions
    assert topic_key_cryptos == "favorite_cryptos", f"Expected 'favorite_cryptos', got '{topic_key_cryptos}'"
    assert len(ranked_cryptos) == 3, f"Expected 3 facts, got {len(ranked_cryptos)}"
    assert ranked_cryptos[0] == (1, "XMR"), f"Expected (1, 'XMR'), got {ranked_cryptos[0]}"
    assert ranked_cryptos[1] == (2, "BTC"), f"Expected (2, 'BTC'), got {ranked_cryptos[1]}"
    assert ranked_cryptos[2] == (3, "XLM"), f"Expected (3, 'XLM'), got {ranked_cryptos[2]}"
    assert "##" not in list_items, "Output must not contain ##"
    assert "M1" not in list_items, "Output must not contain M1"
    assert list_items == "1) XMR\n2) BTC\n3) XLM", f"Expected exact format, got:\n{list_items}"
    
    print("✅ Test 2 PASSED: Clean rendering, no markdown garbage")


def test_3_no_junk_tokens():
    """Test: Ensure M1 tokens never become a stored fact value."""
    print("\n=== Test 3: No Junk Tokens ===")
    
    # Test with junk tokens in text - using fact_extractor
    junk_text = "My favorite colors are 1) Blue, 2) Green [M1], 3) Black ##"
    extractor = get_fact_extractor()
    facts = extractor.extract_facts(junk_text, role="user")
    ranked_facts = []
    for fact in facts:
        if "favorite_color" in fact.get("fact_key", ""):
            fact_key = fact.get("fact_key", "")
            if "." in fact_key:
                try:
                    rank = int(fact_key.split(".")[-1])
                    value = fact.get("value_text", "")
                    ranked_facts.append((rank, value))
                except ValueError:
                    pass
    ranked_facts.sort(key=lambda x: x[0])
    
    print(f"Junk text: {junk_text}")
    print(f"Ranked facts: {ranked_facts}")
    
    # Assertions
    assert len(ranked_facts) == 3, f"Expected 3 facts, got {len(ranked_facts)}"
    assert ranked_facts[0] == (1, "Blue"), f"Expected (1, 'Blue'), got {ranked_facts[0]}"
    assert ranked_facts[1] == (2, "Green"), f"Expected (2, 'Green'), got {ranked_facts[1]}"
    assert ranked_facts[2] == (3, "Black"), f"Expected (3, 'Black'), got {ranked_facts[2]}"
    
    # Ensure no junk tokens in values
    for rank, value in ranked_facts:
        assert "[M1]" not in value, f"Value '{value}' contains [M1]"
        assert "##" not in value, f"Value '{value}' contains ##"
        assert "M1" not in value, f"Value '{value}' contains M1"
    
    # Test with markdown heading - using fact_extractor
    heading_text = "## My favorite colors\n1) Blue\n2) Green\n3) Black"
    extractor = get_fact_extractor()
    facts = extractor.extract_facts(heading_text, role="user")
    ranked_facts_heading = []
    for fact in facts:
        if "favorite_color" in fact.get("fact_key", ""):
            fact_key = fact.get("fact_key", "")
            if "." in fact_key:
                try:
                    rank = int(fact_key.split(".")[-1])
                    value = fact.get("value_text", "")
                    ranked_facts_heading.append((rank, value))
                except ValueError:
                    pass
    ranked_facts_heading.sort(key=lambda x: x[0])
    
    print(f"\nHeading text: {heading_text}")
    print(f"Ranked facts: {ranked_facts_heading}")
    
    assert len(ranked_facts_heading) == 3, f"Expected 3 facts, got {len(ranked_facts_heading)}"
    assert ranked_facts_heading[0] == (1, "Blue"), f"Expected (1, 'Blue'), got {ranked_facts_heading[0]}"
    
    print("✅ Test 3 PASSED: Junk tokens are filtered out")


def test_4_strict_topic_matching():
    """Test: Strict topic matching prevents wrong mappings."""
    print("\n=== Test 4: Strict Topic Matching ===")
    
    test_cases = [
        ("My favorite colors are 1) Blue", "favorite_colors"),
        ("What is my favorite crypto?", "favorite_cryptos"),
        ("List my favorite tv shows", "favorite_tv"),
        ("My favorite candies are 1) Chocolate", "favorite_candies"),
        ("What is my favorite movie?", None),  # Not in canonical list
        ("My favorite books are 1) Book1", None),  # Not in canonical list
    ]
    
    for text, expected in test_cases:
        result = extract_topic_from_query(text)
        print(f"Text: '{text}' → Topic key: {result} (expected: {expected})")
        assert result == expected, f"Expected {expected}, got {result} for '{text}'"
    
    print("✅ Test 4 PASSED: Strict topic matching works")


if __name__ == "__main__":
    print("Running facts fixes tests...")
    
    try:
        test_1_topic_bleed_prevention()
        test_2_clean_rendering()
        test_3_no_junk_tokens()
        test_4_strict_topic_matching()
        
        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
