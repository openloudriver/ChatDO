"""
Cross-chat memory retrieval tests.

Tests that facts stored in one chat can be retrieved from another chat within the same project.
"""
import sys
import os
import pytest
import uuid
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.services.memory_service_client import MemoryServiceClient
from server.services.facts import extract_ranked_facts, normalize_topic_key, extract_topic_from_query
from memory_service.memory_dashboard import db

# Test project ID
TEST_PROJECT_ID = "test-cross-chat-memory"


@pytest.fixture(scope="module")
def memory_client():
    """Get memory service client."""
    client = MemoryServiceClient()
    if not client.is_available():
        pytest.skip("Memory Service is not available")
    return client


@pytest.fixture(scope="module", autouse=True)
def cleanup_test_data(memory_client):
    """Clean up test data before and after tests."""
    # Clean up before tests
    try:
        # Delete all facts for test project
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (TEST_PROJECT_ID,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    
    yield
    
    # Clean up after tests
    try:
        conn = db.get_tracking_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM facts WHERE project_id = ?", (TEST_PROJECT_ID,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def test_small_cross_chat_ordinal(memory_client):
    """
    Small test: Store ranked list in Chat A, verify Chat B can answer ordinal question.
    """
    print("\n=== Small Cross-Chat Test: Ordinal Question ===")
    
    chat_a_id = f"test-chat-a-{uuid.uuid4().hex[:8]}"
    chat_b_id = f"test-chat-b-{uuid.uuid4().hex[:8]}"
    
    # Store ranked list in Chat A (using format that extract_ranked_facts supports)
    user_message = "My favorite colors are 1) Blue, 2) Green, 3) Black"
    topic_key = normalize_topic_key(user_message)
    ranked_facts = extract_ranked_facts(user_message)
    
    assert topic_key == "favorite_colors", f"Expected 'favorite_colors', got '{topic_key}'"
    assert len(ranked_facts) == 3, f"Expected 3 facts, got {len(ranked_facts)}"
    
    # Store facts in Chat A
    message_id_a = f"{chat_a_id}-user-1"
    for rank, value in ranked_facts:
        success = memory_client.store_fact(
            project_id=TEST_PROJECT_ID,
            topic_key=topic_key,
            kind="ranked",
            value=value,
            source_message_id=message_id_a,
            chat_id=chat_a_id,
            rank=rank
        )
        assert success, f"Failed to store fact: rank={rank}, value={value}"
        print(f"  ✓ Stored in Chat A: rank={rank}, value={value}")
    
    # Verify Chat B can retrieve facts (cross-chat)
    facts_from_b = memory_client.get_facts(
        project_id=TEST_PROJECT_ID,
        topic_key=topic_key,
        chat_id=None  # Cross-chat: search all chats
    )
    
    assert len(facts_from_b) == 3, f"Expected 3 facts from Chat B, got {len(facts_from_b)}"
    print(f"  ✓ Chat B retrieved {len(facts_from_b)} facts (cross-chat)")
    
    # Test ordinal question: "What is my second favorite color?"
    fact_rank_2 = memory_client.get_fact_by_rank(
        project_id=TEST_PROJECT_ID,
        topic_key=topic_key,
        rank=2,
        chat_id=None  # Cross-chat: search all chats
    )
    
    assert fact_rank_2 is not None, "Failed to retrieve rank 2 fact from Chat B"
    assert fact_rank_2.get("value") == "Green", f"Expected 'Green', got '{fact_rank_2.get('value')}'"
    assert fact_rank_2.get("chat_id") == chat_a_id, f"Fact should come from Chat A, got chat_id={fact_rank_2.get('chat_id')}"
    print(f"  ✓ Chat B answered ordinal question: rank 2 = {fact_rank_2.get('value')} (from Chat A)")
    
    print("✅ Small cross-chat test PASSED")


@pytest.mark.cross_chat
def test_cross_chat_harness(memory_client):
    """
    Comprehensive cross-chat test harness:
    - Create test project
    - Auto-create 10 chats
    - Write 10 distinct memories across those chats (ranked lists + preferences)
    - Test multiple list formats: 1), 1., #1, and natural language
    - In different chats ask paraphrased/ordinal questions
    - Assert answers come from stored facts (not current chat)
    """
    print("\n=== Cross-Chat Test Harness ===")
    
    # Create 10 test chats
    chat_ids = [f"test-chat-{i}-{uuid.uuid4().hex[:8]}" for i in range(10)]
    print(f"Created {len(chat_ids)} test chats")
    
    # Test data: 10 distinct memories with different formats
    test_memories = [
        # Format: 1) item
        {
            "chat_id": chat_ids[0],
            "message": "My favorite colors are 1) Red, 2) Orange, 3) Yellow",
            "topic": "favorite_colors",
            "expected_facts": [(1, "Red"), (2, "Orange"), (3, "Yellow")]
        },
        # Format: 1. item
        {
            "chat_id": chat_ids[1],
            "message": "My favorite cryptos are 1. Bitcoin, 2. Ethereum, 3. Monero",
            "topic": "favorite_cryptos",
            "expected_facts": [(1, "Bitcoin"), (2, "Ethereum"), (3, "Monero")]
        },
        # Format: #1 item
        {
            "chat_id": chat_ids[2],
            "message": "My favorite tv shows are #1 Breaking Bad, #2 The Wire, #3 Game of Thrones",
            "topic": "favorite_tv",
            "expected_facts": [(1, "Breaking Bad"), (2, "The Wire"), (3, "Game of Thrones")]
        },
        # Format: natural language (first, second, third)
        {
            "chat_id": chat_ids[3],
            "message": "My favorite candies are first: Chocolate, second: Gummy Bears, third: Licorice",
            "topic": "favorite_candies",
            "expected_facts": [(1, "Chocolate"), (2, "Gummy Bears"), (3, "Licorice")]
        },
        # Another colors list (different chat)
        {
            "chat_id": chat_ids[4],
            "message": "My favorite colors are 1) Purple, 2) Pink, 3) Cyan",
            "topic": "favorite_colors",
            "expected_facts": [(1, "Purple"), (2, "Pink"), (3, "Cyan")]
        },
        # Another cryptos list
        {
            "chat_id": chat_ids[5],
            "message": "My favorite cryptos are 1) Litecoin, 2) Cardano, 3) Polkadot",
            "topic": "favorite_cryptos",
            "expected_facts": [(1, "Litecoin"), (2, "Cardano"), (3, "Polkadot")]
        },
        # Another TV shows list
        {
            "chat_id": chat_ids[6],
            "message": "My favorite tv shows are 1) The Office, 2) Parks and Rec, 3) Community",
            "topic": "favorite_tv",
            "expected_facts": [(1, "The Office"), (2, "Parks and Rec"), (3, "Community")]
        },
        # Another candies list
        {
            "chat_id": chat_ids[7],
            "message": "My favorite candies are 1) Skittles, 2) M&Ms, 3) Twix",
            "topic": "favorite_candies",
            "expected_facts": [(1, "Skittles"), (2, "M&Ms"), (3, "Twix")]
        },
        # More colors
        {
            "chat_id": chat_ids[8],
            "message": "My favorite colors are 1) Teal, 2) Magenta, 3) Gold",
            "topic": "favorite_colors",
            "expected_facts": [(1, "Teal"), (2, "Magenta"), (3, "Gold")]
        },
        # More cryptos
        {
            "chat_id": chat_ids[9],
            "message": "My favorite cryptos are 1) Solana, 2) Avalanche, 3) Chainlink",
            "topic": "favorite_cryptos",
            "expected_facts": [(1, "Solana"), (2, "Avalanche"), (3, "Chainlink")]
        },
    ]
    
    # Store all memories
    stored_facts = {}
    for i, memory in enumerate(test_memories):
        topic_key = normalize_topic_key(memory["message"])
        ranked_facts = extract_ranked_facts(memory["message"])
        
        assert topic_key == memory["topic"], f"Memory {i}: Expected topic '{memory['topic']}', got '{topic_key}'"
        assert len(ranked_facts) == len(memory["expected_facts"]), \
            f"Memory {i}: Expected {len(memory['expected_facts'])} facts, got {len(ranked_facts)}"
        
        # Store facts
        message_id = f"{memory['chat_id']}-user-1"
        for rank, value in ranked_facts:
            success = memory_client.store_fact(
                project_id=TEST_PROJECT_ID,
                topic_key=topic_key,
                kind="ranked",
                value=value,
                source_message_id=message_id,
                chat_id=memory["chat_id"],
                rank=rank
            )
            assert success, f"Memory {i}: Failed to store fact rank={rank}, value={value}"
        
        # Track stored facts by topic
        if topic_key not in stored_facts:
            stored_facts[topic_key] = []
        stored_facts[topic_key].append({
            "chat_id": memory["chat_id"],
            "facts": ranked_facts
        })
        
        print(f"  ✓ Stored memory {i+1}/10 in chat {memory['chat_id'][:12]}... ({topic_key})")
    
    print(f"\nStored {len(test_memories)} memories across {len(chat_ids)} chats")
    
    # Test cross-chat retrieval with paraphrased/ordinal questions
    # Note: When multiple chats have facts for the same topic/rank, we get the most recent one
    # The key test is that facts come from OTHER chats, not the current chat
    test_queries = [
        # Query colors from Chat 1 (Chat 1 doesn't have colors, so should get from another chat)
        {
            "query_chat": chat_ids[1],  # Chat 1 has cryptos, not colors
            "query": "What is my second favorite color?",
            "topic": "favorite_colors",
            "rank": 2,
            "must_not_be_chat": chat_ids[1]  # Must NOT come from current chat
        },
        # Query cryptos from Chat 2 (Chat 2 has TV shows, not cryptos)
        {
            "query_chat": chat_ids[2],  # Chat 2 has TV shows, not cryptos
            "query": "What is my number 1 favorite crypto?",
            "topic": "favorite_cryptos",
            "rank": 1,
            "must_not_be_chat": chat_ids[2]  # Must NOT come from current chat
        },
        # Query TV shows from Chat 3 (Chat 3 has candies, not TV shows)
        {
            "query_chat": chat_ids[3],  # Chat 3 has candies, not TV shows
            "query": "What is my third favorite tv show?",
            "topic": "favorite_tv",
            "rank": 3,
            "must_not_be_chat": chat_ids[3]  # Must NOT come from current chat
        },
        # Query candies from Chat 4 (Chat 4 has colors, not candies)
        {
            "query_chat": chat_ids[4],  # Chat 4 has colors, not candies
            "query": "What is my first favorite candy?",
            "topic": "favorite_candies",
            "rank": 1,
            "must_not_be_chat": chat_ids[4]  # Must NOT come from current chat
        },
        # Query full list from different chat (Chat 5 has cryptos, asking about colors)
        {
            "query_chat": chat_ids[5],  # Chat 5 has cryptos, not colors
            "query": "List my favorite colors",
            "topic": "favorite_colors",
            "rank": None,  # Full list query
            "must_not_be_chat": chat_ids[5]  # Must NOT come from current chat
        },
        # Paraphrased query (Chat 6 has TV shows, asking about cryptos)
        {
            "query_chat": chat_ids[6],  # Chat 6 has TV shows, not cryptos
            "query": "Show me my favorite cryptos",
            "topic": "favorite_cryptos",
            "rank": None,  # Full list query
            "must_not_be_chat": chat_ids[6]  # Must NOT come from current chat
        },
    ]
    
    # Run test queries
    passed = 0
    failed = 0
    
    for i, test_query in enumerate(test_queries):
        print(f"\n  Test Query {i+1}: '{test_query['query']}' (from chat {test_query['query_chat'][:12]}...)")
        
        topic_key = extract_topic_from_query(test_query["query"])
        assert topic_key == test_query["topic"], \
            f"Query {i+1}: Expected topic '{test_query['topic']}', got '{topic_key}'"
        
        if test_query["rank"] is not None:
            # Ordinal query
            fact = memory_client.get_fact_by_rank(
                project_id=TEST_PROJECT_ID,
                topic_key=topic_key,
                rank=test_query["rank"],
                chat_id=None  # Cross-chat: search all chats
            )
            
            if fact is None:
                print(f"    ❌ FAILED: No fact found for rank {test_query['rank']}")
                failed += 1
                continue
            
            value = fact.get("value")
            fact_chat_id = fact.get("chat_id")
            
            # Key assertion: fact must come from a different chat (cross-chat retrieval)
            if fact_chat_id == test_query["query_chat"]:
                print(f"    ❌ FAILED: Fact came from current chat {fact_chat_id[:12]}..., not cross-chat!")
                failed += 1
                continue
            
            # Verify it's not from the excluded chat
            if fact_chat_id == test_query.get("must_not_be_chat"):
                print(f"    ❌ FAILED: Fact came from excluded chat {fact_chat_id[:12]}...")
                failed += 1
                continue
            
            if not value:
                print(f"    ❌ FAILED: Fact has no value")
                failed += 1
                continue
            
            print(f"    ✓ PASSED: rank {test_query['rank']} = '{value}' (from chat {fact_chat_id[:12]}..., cross-chat retrieval works)")
            passed += 1
        
        else:
            # Full list query
            facts = memory_client.get_facts(
                project_id=TEST_PROJECT_ID,
                topic_key=topic_key,
                chat_id=None  # Cross-chat: search all chats
            )
            
            if not facts:
                print(f"    ❌ FAILED: No facts found")
                failed += 1
                continue
            
            # Check that facts come from different chat (cross-chat retrieval)
            fact_chat_ids = {f.get("chat_id") for f in facts}
            if test_query["query_chat"] in fact_chat_ids:
                # Check if ALL facts are from current chat (bad)
                if len(fact_chat_ids) == 1 and test_query["query_chat"] in fact_chat_ids:
                    print(f"    ❌ FAILED: All facts came from current chat, not cross-chat!")
                    failed += 1
                    continue
            
            # Verify we got facts from other chats (cross-chat)
            facts_from_other_chats = [f for f in facts if f.get("chat_id") != test_query["query_chat"]]
            if not facts_from_other_chats:
                print(f"    ❌ FAILED: No facts from other chats (all from current chat)")
                failed += 1
                continue
            
            # Verify facts don't come from excluded chat
            if test_query.get("must_not_be_chat"):
                facts_from_excluded = [f for f in facts if f.get("chat_id") == test_query["must_not_be_chat"]]
                if len(facts_from_excluded) == len(facts):
                    print(f"    ❌ FAILED: All facts came from excluded chat")
                    failed += 1
                    continue
            
            print(f"    ✓ PASSED: Retrieved {len(facts)} facts, {len(facts_from_other_chats)} from other chats (cross-chat works)")
            passed += 1
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"Cross-Chat Test Harness Summary:")
    print(f"  Total queries: {len(test_queries)}")
    print(f"  Passed: {passed}")
    print(f"  Failed: {failed}")
    print(f"{'='*60}")
    
    assert failed == 0, f"{failed} test queries failed"
    assert passed == len(test_queries), f"Expected {len(test_queries)} passed, got {passed}"
    
    print("✅ Cross-chat test harness PASSED")


if __name__ == "__main__":
    pytest.main([__file__, "-m", "cross_chat", "-v"])

