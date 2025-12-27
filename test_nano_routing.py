#!/usr/bin/env python3
"""
Nano Routing Regression Tests

Tests that verify deterministic routing for "My favorite X is Y" patterns
always route to Facts write with zero server-side overrides.
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from server.services.nano_router import route_with_nano, NanoRouterError
from server.contracts.routing_plan import RoutingPlan


async def test_store_routing():
    """Test that 'My favorite X is Y' routes to facts/write."""
    print("\n" + "="*60)
    print("TEST 1: Store Routing - 'My favorite candy is Reese's'")
    print("="*60)
    
    message = "My favorite candy is Reese's"
    try:
        plan = await route_with_nano(message)
        
        # Assertions
        assert plan.content_plane == "facts", f"Expected content_plane='facts', got '{plan.content_plane}'"
        assert plan.operation == "write", f"Expected operation='write', got '{plan.operation}'"
        assert plan.reasoning_required == False, f"Expected reasoning_required=False, got {plan.reasoning_required}"
        assert plan.facts_write_candidate is not None, "Expected facts_write_candidate to be populated"
        assert plan.facts_write_candidate.topic == "candy", f"Expected topic='candy', got '{plan.facts_write_candidate.topic}'"
        assert plan.facts_write_candidate.value == "Reese's", f"Expected value='Reese's', got '{plan.facts_write_candidate.value}'"
        assert plan.confidence >= 0.9, f"Expected high confidence (>=0.9), got {plan.confidence}"
        
        print(f"✅ PASS: Routing plan correct")
        print(f"   content_plane: {plan.content_plane}")
        print(f"   operation: {plan.operation}")
        print(f"   reasoning_required: {plan.reasoning_required}")
        print(f"   facts_write_candidate: topic={plan.facts_write_candidate.topic}, value={plan.facts_write_candidate.value}")
        print(f"   confidence: {plan.confidence}")
        print(f"   why: {plan.why}")
        return True
        
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_retrieve_routing():
    """Test that 'List my favorite X' routes to facts/read."""
    print("\n" + "="*60)
    print("TEST 2: Retrieve Routing - 'List my favorite candy'")
    print("="*60)
    
    message = "List my favorite candy"
    try:
        plan = await route_with_nano(message)
        
        # Assertions
        assert plan.content_plane == "facts", f"Expected content_plane='facts', got '{plan.content_plane}'"
        assert plan.operation == "read", f"Expected operation='read', got '{plan.operation}'"
        assert plan.reasoning_required == False, f"Expected reasoning_required=False, got {plan.reasoning_required}"
        assert plan.facts_read_candidate is not None, "Expected facts_read_candidate to be populated"
        assert plan.facts_read_candidate.topic == "candy", f"Expected topic='candy', got '{plan.facts_read_candidate.topic}'"
        assert plan.confidence >= 0.9, f"Expected high confidence (>=0.9), got {plan.confidence}"
        
        print(f"✅ PASS: Routing plan correct")
        print(f"   content_plane: {plan.content_plane}")
        print(f"   operation: {plan.operation}")
        print(f"   reasoning_required: {plan.reasoning_required}")
        print(f"   facts_read_candidate: topic={plan.facts_read_candidate.topic}")
        print(f"   confidence: {plan.confidence}")
        print(f"   why: {plan.why}")
        return True
        
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_multiple_values():
    """Test that 'My favorite X are Y, Z' routes correctly with rank_ordered."""
    print("\n" + "="*60)
    print("TEST 3: Multiple Values - 'My favorite cryptos are BTC, ETH, SOL'")
    print("="*60)
    
    message = "My favorite cryptos are BTC, ETH, SOL"
    try:
        plan = await route_with_nano(message)
        
        # Assertions
        assert plan.content_plane == "facts", f"Expected content_plane='facts', got '{plan.content_plane}'"
        assert plan.operation == "write", f"Expected operation='write', got '{plan.operation}'"
        assert plan.facts_write_candidate is not None, "Expected facts_write_candidate to be populated"
        assert isinstance(plan.facts_write_candidate.value, list), "Expected value to be a list"
        assert len(plan.facts_write_candidate.value) == 3, f"Expected 3 values, got {len(plan.facts_write_candidate.value)}"
        assert plan.facts_write_candidate.rank_ordered == True, "Expected rank_ordered=True for multiple values"
        
        print(f"✅ PASS: Routing plan correct")
        print(f"   content_plane: {plan.content_plane}")
        print(f"   operation: {plan.operation}")
        print(f"   facts_write_candidate: topic={plan.facts_write_candidate.topic}, value={plan.facts_write_candidate.value}, rank_ordered={plan.facts_write_candidate.rank_ordered}")
        return True
        
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_chat_only():
    """Test that general chat routes to chat/none."""
    print("\n" + "="*60)
    print("TEST 4: Chat Only - 'Hello, how are you?'")
    print("="*60)
    
    message = "Hello, how are you?"
    try:
        plan = await route_with_nano(message)
        
        # Assertions
        assert plan.content_plane == "chat", f"Expected content_plane='chat', got '{plan.content_plane}'"
        assert plan.operation == "none", f"Expected operation='none', got '{plan.operation}'"
        assert plan.reasoning_required == True, f"Expected reasoning_required=True, got {plan.reasoning_required}"
        
        print(f"✅ PASS: Routing plan correct")
        print(f"   content_plane: {plan.content_plane}")
        print(f"   operation: {plan.operation}")
        print(f"   reasoning_required: {plan.reasoning_required}")
        return True
        
    except AssertionError as e:
        print(f"❌ FAIL: {e}")
        return False
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """Run all routing tests."""
    print("\n" + "="*60)
    print("NANO ROUTING REGRESSION TESTS")
    print("="*60)
    
    results = []
    
    results.append(await test_store_routing())
    results.append(await test_retrieve_routing())
    results.append(await test_multiple_values())
    results.append(await test_chat_only())
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    passed = sum(results)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("✅ ALL TESTS PASSED")
        return 0
    else:
        print(f"❌ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(run_all_tests())
    sys.exit(exit_code)

