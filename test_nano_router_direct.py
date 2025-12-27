"""
Direct test of Nano router to diagnose routing issues.
Run this to see what the router actually returns for "My favorite" patterns.
"""
import asyncio
import sys
import os
from pathlib import Path

# Add server to path
sys.path.insert(0, str(Path(__file__).parent / "server"))

from server.services.nano_router import route_with_nano
from server.contracts.routing_plan import RoutingPlan


async def test_router():
    """Test router with "My favorite" patterns."""
    
    test_cases = [
        "My favorite candy is Twizzlers",
        "My favorite candy is Reese's",
        "My favorite colors are red, white and blue",
        "My favorite cryptos are BTC, XMR and XLM",
    ]
    
    print("=" * 80)
    print("NANO ROUTER DIAGNOSTIC TEST")
    print("=" * 80)
    
    for test_message in test_cases:
        print(f"\n{'='*80}")
        print(f"TEST: {test_message}")
        print(f"{'='*80}")
        
        try:
            routing_plan = await route_with_nano(test_message, conversation_history=None)
            
            print(f"✅ Router returned:")
            print(f"   content_plane: {routing_plan.content_plane}")
            print(f"   operation: {routing_plan.operation}")
            print(f"   reasoning_required: {routing_plan.reasoning_required}")
            print(f"   confidence: {routing_plan.confidence}")
            print(f"   why: {routing_plan.why}")
            
            if routing_plan.facts_write_candidate:
                print(f"   facts_write_candidate:")
                print(f"     topic: {routing_plan.facts_write_candidate.topic}")
                print(f"     value: {routing_plan.facts_write_candidate.value}")
                print(f"     rank_ordered: {routing_plan.facts_write_candidate.rank_ordered}")
            else:
                print(f"   facts_write_candidate: None")
            
            # Check if routing is correct
            expected_facts_write = (
                routing_plan.content_plane == "facts" and
                routing_plan.operation == "write"
            )
            
            if expected_facts_write:
                print(f"✅ CORRECT: Routed to facts/write")
            else:
                print(f"❌ WRONG: Expected facts/write, got {routing_plan.content_plane}/{routing_plan.operation}")
                
        except Exception as e:
            print(f"❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n{'='*80}")
    print("TEST COMPLETE")
    print(f"{'='*80}")


if __name__ == "__main__":
    asyncio.run(test_router())

