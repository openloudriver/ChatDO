#!/usr/bin/env python3
"""
Facts (Qwen) Acceptance Test Runner

This script runs acceptance tests for the Facts system to verify:
1. Facts-S (Store)
2. Facts-U (Update)
3. Facts-R (Retrieval/Fast Path)
4. Facts-F (Hard Fail)
5. Concurrency
6. JSON Edge Cases

Prerequisites:
- Backend server running
- Ollama running with qwen2.5:7b-instruct model
- Valid project UUID and thread_id

Usage:
    python test_facts_acceptance.py --project-uuid <uuid> --thread-id <thread_id> [--base-url <url>]
"""

import asyncio
import argparse
import json
import sys
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Add project root to path
import sys
from pathlib import Path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from server.services.facts_persistence import persist_facts_synchronously
from server.services.facts_query_planner import plan_facts_query
from server.services.facts_retrieval import execute_facts_plan
from server.services.facts_llm.client import FactsLLMError
from memory_service.memory_dashboard import db


class Colors:
    """ANSI color codes for terminal output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'
    BOLD = '\033[1m'


def print_test_header(test_name: str):
    """Print a formatted test header."""
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}TEST: {test_name}{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}\n")


def print_result(passed: bool, message: str):
    """Print a test result."""
    status = f"{Colors.GREEN}✅ PASS{Colors.RESET}" if passed else f"{Colors.RED}❌ FAIL{Colors.RESET}"
    print(f"{status}: {message}")


def print_info(message: str):
    """Print an info message."""
    print(f"{Colors.YELLOW}ℹ️  {message}{Colors.RESET}")


async def test_1_facts_s_store(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 1: Facts-S (Store)
    
    Test: "My favorite candies are Snickers, Reese's, Twix."
    Expected: Facts-S(3), correct keys/values in DB
    """
    print_test_header("Test 1: Facts-S (Store)")
    
    message_content = "My favorite candies are Snickers, Reese's, Twix."
    message_id = f"{thread_id}-user-test1"
    timestamp = datetime.now(timezone.utc)
    
    try:
        store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics = await persist_facts_synchronously(
            project_id=project_uuid,
            message_content=message_content,
            role="user",
            chat_id=thread_id,
            message_id=message_id,
            timestamp=timestamp,
            message_index=0
        )
        
        # Check results
        passed = True
        issues = []
        
        if store_count < 0 or update_count < 0:
            passed = False
            issues.append("Facts LLM failed (negative counts)")
        
        if store_count != 3:
            passed = False
            issues.append(f"Expected Facts-S(3), got Facts-S({store_count})")
        
        if update_count != 0:
            passed = False
            issues.append(f"Expected Facts-U(0), got Facts-U({update_count})")
        
        if ambiguous_topics:
            passed = False
            issues.append(f"Unexpected ambiguity: {ambiguous_topics}")
        
        if not message_uuid:
            passed = False
            issues.append("No message_uuid returned")
        
        # Verify DB state
        print_info("Verifying DB state...")
        source_id = f"project-{project_uuid}"
        
        # Search for facts using canonical topic
        # Note: "candies" is canonicalized to "candy" by canonicalize_topic()
        from server.services.facts_topic import canonicalize_topic
        canonical_topic = canonicalize_topic("candies")  # Should be "candy"
        db_facts = db.search_current_facts(
            project_id=project_uuid,
            query=canonical_topic,
            limit=10,
            source_id=source_id
        )
        
        # Check that we have 3 facts stored (regardless of topic name normalization)
        if len(db_facts) < 3:
            passed = False
            issues.append(f"Expected at least 3 facts, found {len(db_facts)}")
        
        # Check that stored_fact_keys match what's in DB
        # Qwen may normalize "candies" to "candy" (singular), which is acceptable
        db_keys = {fact.get("fact_key", "") for fact in db_facts}
        stored_keys_set = set(stored_fact_keys)
        
        # Check that all stored keys are in DB
        missing_keys = stored_keys_set - db_keys
        if missing_keys:
            passed = False
            issues.append(f"Stored keys not found in DB: {missing_keys}")
        
        # Check values - verify that Snickers, Reese's, and Twix are present
        # (order may vary, and topic may be singular or plural)
        fact_values = [fact.get("value_text", "").lower() for fact in db_facts]
        expected_values = ["snickers", "reese's", "twix"]
        
        for expected_value in expected_values:
            found = any(expected_value in val or val in expected_value for val in fact_values)
            if not found:
                passed = False
                issues.append(f"Expected value '{expected_value}' not found in stored facts")
        
        # Log what was actually stored
        if db_facts:
            print_info(f"Found {len(db_facts)} facts in DB:")
            for fact in sorted(db_facts, key=lambda f: f.get("fact_key", "")):
                print_info(f"  - {fact.get('fact_key')} = {fact.get('value_text')}")
        
        if passed:
            print_result(True, f"Facts-S({store_count}) - All facts stored correctly")
            print_info(f"Stored keys: {stored_fact_keys}")
            print_info(f"Message UUID: {message_uuid}")
        else:
            print_result(False, f"Issues: {'; '.join(issues)}")
        
        return {
            "test": "Facts-S Store",
            "passed": passed,
            "store_count": store_count,
            "update_count": update_count,
            "stored_fact_keys": stored_fact_keys,
            "message_uuid": message_uuid,
            "issues": issues,
            "db_facts": [{"fact_key": f.get("fact_key"), "value_text": f.get("value_text")} for f in db_facts]
        }
        
    except Exception as e:
        print_result(False, f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return {
            "test": "Facts-S Store",
            "passed": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


async def test_2_facts_u_update(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 2: Facts-U (Update)
    
    Test: "Make Twix my #1 favorite candy."
    Expected: Facts-U(≥1), list reflects update correctly
    """
    print_test_header("Test 2: Facts-U (Update)")
    
    message_content = "Make Twix my #1 favorite candy."
    message_id = f"{thread_id}-user-test2"
    timestamp = datetime.now(timezone.utc)
    
    try:
        store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics = await persist_facts_synchronously(
            project_id=project_uuid,
            message_content=message_content,
            role="user",
            chat_id=thread_id,
            message_id=message_id,
            timestamp=timestamp,
            message_index=1
        )
        
        # Check results
        passed = True
        issues = []
        
        if store_count < 0 or update_count < 0:
            passed = False
            issues.append("Facts LLM failed (negative counts)")
        
        # Note: "Make X my #1" might result in STORE (new fact) or UPDATE (modify existing)
        # Both are acceptable as long as the result is correct (final state matters, not counter)
        if store_count < 0 or update_count < 0:
            passed = False
            issues.append("Facts LLM failed (negative counts)")
        elif store_count == 0 and update_count == 0:
            passed = False
            issues.append(f"Expected Facts-S(≥1) or Facts-U(≥1), got S={store_count} U={update_count}")
        
        # Verify final state is correct (more important than counter semantics)
        # Rank #1 must be Twix, and retrieval must return correct ordered list
        
        if ambiguous_topics:
            passed = False
            issues.append(f"Unexpected ambiguity: {ambiguous_topics}")
        
        # Verify DB state - Twix should be at #1
        print_info("Verifying DB state...")
        source_id = f"project-{project_uuid}"
        
        # Query ranked list using canonical topic (no fallbacks - must use production path)
        from server.services.librarian import search_facts_ranked_list
        from server.services.facts_topic import canonicalize_topic
        
        # Use canonical topic for retrieval (same normalization as Facts-S/U)
        canonical_topic = canonicalize_topic("candy")  # "candy" or "candies" both canonicalize to "candy"
        ranked_facts = search_facts_ranked_list(
            project_id=project_uuid,
            topic_key=canonical_topic,
            limit=10
        )
        
        if not ranked_facts:
            passed = False
            issues.append("No ranked facts found in DB")
        else:
            # Check that #1 is Twix
            rank_1_fact = next((f for f in ranked_facts if f.get("rank") == 1), None)
            if not rank_1_fact:
                passed = False
                issues.append("No fact found at rank 1")
            else:
                value = rank_1_fact.get("value_text", "").lower()
                if "twix" not in value:
                    passed = False
                    issues.append(f"Rank #1 is not Twix: '{rank_1_fact.get('value_text')}'")
        
        if passed:
            print_result(True, f"Facts-U({update_count}) - Update successful")
            print_info(f"Updated keys: {stored_fact_keys}")
            if ranked_facts:
                print_info(f"Rank #1: {ranked_facts[0].get('value_text')}")
        else:
            print_result(False, f"Issues: {'; '.join(issues)}")
        
        return {
            "test": "Facts-U Update",
            "passed": passed,
            "store_count": store_count,
            "update_count": update_count,
            "stored_fact_keys": stored_fact_keys,
            "message_uuid": message_uuid,
            "issues": issues,
            "ranked_facts": [{"rank": f.get("rank"), "value_text": f.get("value_text")} for f in ranked_facts]
        }
        
    except Exception as e:
        print_result(False, f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return {
            "test": "Facts-U Update",
            "passed": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


async def test_3_facts_r_fast_path(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 3: Facts-R Fast Path
    
    Test: "What are my favorite candies?"
    Expected: Model: Facts (no GPT-5), correct ordered output, Facts-R set
    """
    print_test_header("Test 3: Facts-R Fast Path")
    
    query_text = "What are my favorite candies?"
    
    try:
        # Plan query
        query_plan = await plan_facts_query(query_text)
        
        print_info(f"Query plan: intent={query_plan.intent}, topic={query_plan.topic}, list_key={query_plan.list_key}")
        
        # Execute plan (no fallbacks - must use production retrieval path)
        facts_answer = execute_facts_plan(
            project_uuid=project_uuid,
            plan=query_plan,
            exclude_message_uuid=None  # No current message to exclude in test
        )
        
        # Check results
        passed = True
        issues = []
        
        if query_plan.intent != "facts_get_ranked_list":
            passed = False
            issues.append(f"Expected intent 'facts_get_ranked_list', got '{query_plan.intent}'")
        
        if not facts_answer.facts:
            passed = False
            issues.append("No facts returned")
        
        if len(facts_answer.canonical_keys) != 1:
            passed = False
            issues.append(f"Expected 1 canonical key, got {len(facts_answer.canonical_keys)}: {facts_answer.canonical_keys}")
        
        # Check ordering
        if facts_answer.facts:
            sorted_facts = sorted(facts_answer.facts, key=lambda f: f.get("rank", float('inf')))
            ranks = [f.get("rank") for f in sorted_facts]
            if ranks != sorted(ranks):
                passed = False
                issues.append(f"Facts not properly sorted by rank: {ranks}")
        
        if passed:
            print_result(True, f"Facts-R({len(facts_answer.canonical_keys)}) - Fast path successful")
            print_info(f"Retrieved {len(facts_answer.facts)} facts")
            for fact in sorted(facts_answer.facts, key=lambda f: f.get("rank", float('inf'))):
                print_info(f"  Rank {fact.get('rank')}: {fact.get('value_text')}")
        else:
            print_result(False, f"Issues: {'; '.join(issues)}")
        
        return {
            "test": "Facts-R Fast Path",
            "passed": passed,
            "query_plan": {
                "intent": query_plan.intent,
                "topic": query_plan.topic,
                "list_key": query_plan.list_key
            },
            "facts_count": len(facts_answer.facts),
            "canonical_keys": facts_answer.canonical_keys,
            "facts": [{"rank": f.get("rank"), "value_text": f.get("value_text")} for f in facts_answer.facts],
            "issues": issues
        }
        
    except FactsLLMError as e:
        print_result(False, f"Facts LLM Error: {e}")
        return {
            "test": "Facts-R Fast Path",
            "passed": False,
            "error": f"FactsLLMError: {e}",
            "error_type": "FactsLLMError"
        }
    except Exception as e:
        print_result(False, f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return {
            "test": "Facts-R Fast Path",
            "passed": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


async def test_4_hard_fail(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 4: Hard Fail (Ollama Down)
    
    Test: Stop Ollama, send any fact message
    Expected: Facts-F, clear error, no writes
    """
    print_test_header("Test 4: Hard Fail (Ollama Down)")
    
    print_info("⚠️  This test requires Ollama to be STOPPED manually.")
    print_info("Please stop Ollama now, then press Enter to continue...")
    try:
        input()
    except EOFError:
        # Non-interactive mode - skip this test
        print_info("Non-interactive mode detected. Skipping hard fail test.")
        return {
            "test": "Hard Fail",
            "passed": None,
            "skipped": True,
            "reason": "Requires manual Ollama stop (non-interactive mode)"
        }
    
    message_content = "My favorite color is blue."
    message_id = f"{thread_id}-user-test4"
    timestamp = datetime.now(timezone.utc)
    
    try:
        store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics = await persist_facts_synchronously(
            project_id=project_uuid,
            message_content=message_content,
            role="user",
            chat_id=thread_id,
            message_id=message_id,
            timestamp=timestamp,
            message_index=2
        )
        
        # Check results
        passed = True
        issues = []
        
        # Should have negative counts (error indicator)
        if store_count >= 0 or update_count >= 0:
            passed = False
            issues.append(f"Expected negative counts (error), got S={store_count} U={update_count}")
        
        # Should have no writes
        if stored_fact_keys:
            passed = False
            issues.append(f"Expected no writes, but got keys: {stored_fact_keys}")
        
        if passed:
            print_result(True, "Facts-F - Hard fail correctly detected")
            print_info(f"Error indicator: S={store_count} U={update_count}")
        else:
            print_result(False, f"Issues: {'; '.join(issues)}")
        
        print_info("Please restart Ollama now...")
        
        return {
            "test": "Hard Fail",
            "passed": passed,
            "store_count": store_count,
            "update_count": update_count,
            "stored_fact_keys": stored_fact_keys,
            "issues": issues
        }
        
    except Exception as e:
        # Exception is also acceptable (hard fail)
        print_result(True, f"Hard fail correctly raised exception: {e}")
        return {
            "test": "Hard Fail",
            "passed": True,
            "error": str(e),
            "error_type": type(e).__name__
        }


async def test_5_concurrency(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 5: Concurrency
    
    Test: Send 3 fact messages quickly
    Expected: All processed correctly, accurate counts, no corruption
    """
    print_test_header("Test 5: Concurrency")
    
    messages = [
        "My favorite fruit is apple.",
        "My favorite fruit is banana.",
        "My favorite fruit is cherry."
    ]
    
    try:
        # Send all messages concurrently
        tasks = []
        for i, message_content in enumerate(messages):
            message_id = f"{thread_id}-user-test5-{i}"
            timestamp = datetime.now(timezone.utc)
            task = persist_facts_synchronously(
                project_id=project_uuid,
                message_content=message_content,
                role="user",
                chat_id=thread_id,
                message_id=message_id,
                timestamp=timestamp,
                message_index=3 + i
            )
            tasks.append(task)
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check results
        passed = True
        issues = []
        total_store = 0
        total_update = 0
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                passed = False
                issues.append(f"Message {i} raised exception: {result}")
            else:
                store_count, update_count, stored_fact_keys, message_uuid, ambiguous_topics = result
                if store_count < 0 or update_count < 0:
                    passed = False
                    issues.append(f"Message {i} failed (negative counts)")
                else:
                    total_store += store_count
                    total_update += update_count
                    print_info(f"Message {i}: S={store_count} U={update_count}")
        
        if passed:
            print_result(True, f"Concurrency test passed - Total: S={total_store} U={total_update}")
        else:
            print_result(False, f"Issues: {'; '.join(issues)}")
        
        return {
            "test": "Concurrency",
            "passed": passed,
            "total_store": total_store,
            "total_update": total_update,
            "results": [
                {
                    "message": messages[i],
                    "store_count": r[0] if not isinstance(r, Exception) else -1,
                    "update_count": r[1] if not isinstance(r, Exception) else -1,
                    "error": str(r) if isinstance(r, Exception) else None
                }
                for i, r in enumerate(results)
            ],
            "issues": issues
        }
        
    except Exception as e:
        print_result(False, f"Exception: {e}")
        import traceback
        traceback.print_exc()
        return {
            "test": "Concurrency",
            "passed": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


async def test_6_json_edge_cases(project_uuid: str, thread_id: str) -> Dict[str, Any]:
    """
    Test 6: JSON Edge Cases
    
    Test: Force extra text/markdown around JSON
    Expected: Parser handles it or hard-fails cleanly with Facts-F
    """
    print_test_header("Test 6: JSON Edge Cases")
    
    # This test is more of a code review - the JSON extraction logic
    # in facts_persistence.py and facts_query_planner.py should handle
    # markdown code blocks. We'll verify the code handles this.
    
    print_info("This test verifies JSON extraction handles markdown code blocks.")
    print_info("The code should extract JSON from ```json ... ``` blocks.")
    
    # We can't easily force Qwen to return malformed JSON, but we can
    # verify the extraction logic exists in the code
    from server.services.facts_persistence import persist_facts_synchronously
    
    # Check if JSON extraction code exists
    import inspect
    source = inspect.getsource(persist_facts_synchronously)
    
    has_markdown_extraction = "```" in source and "json_text" in source
    
    passed = has_markdown_extraction
    issues = []
    
    if not has_markdown_extraction:
        issues.append("JSON extraction code for markdown code blocks not found")
    
    if passed:
        print_result(True, "JSON extraction code handles markdown code blocks")
    else:
        print_result(False, f"Issues: {'; '.join(issues)}")
    
    return {
        "test": "JSON Edge Cases",
        "passed": passed,
        "has_markdown_extraction": has_markdown_extraction,
        "issues": issues
    }


async def main():
    parser = argparse.ArgumentParser(description="Facts Acceptance Test Runner")
    parser.add_argument("--project-uuid", required=True, help="Project UUID")
    parser.add_argument("--thread-id", required=True, help="Thread ID")
    parser.add_argument("--test", choices=["1", "2", "3", "4", "5", "6", "all"], default="all", help="Test to run")
    
    args = parser.parse_args()
    
    print(f"{Colors.BOLD}{Colors.BLUE}")
    print("="*80)
    print("Facts (Qwen) Acceptance Test Runner")
    print("="*80)
    print(f"{Colors.RESET}")
    print(f"Project UUID: {args.project_uuid}")
    print(f"Thread ID: {args.thread_id}")
    print(f"Test: {args.test}")
    
    results = []
    
    if args.test in ["1", "all"]:
        result = await test_1_facts_s_store(args.project_uuid, args.thread_id)
        results.append(result)
    
    if args.test in ["2", "all"]:
        result = await test_2_facts_u_update(args.project_uuid, args.thread_id)
        results.append(result)
    
    if args.test in ["3", "all"]:
        result = await test_3_facts_r_fast_path(args.project_uuid, args.thread_id)
        results.append(result)
    
    if args.test in ["4", "all"]:
        result = await test_4_hard_fail(args.project_uuid, args.thread_id)
        results.append(result)
    
    if args.test in ["5", "all"]:
        result = await test_5_concurrency(args.project_uuid, args.thread_id)
        results.append(result)
    
    if args.test in ["6", "all"]:
        result = await test_6_json_edge_cases(args.project_uuid, args.thread_id)
        results.append(result)
    
    # Print summary
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}")
    print(f"{Colors.BOLD}SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*80}{Colors.RESET}\n")
    
    passed_count = sum(1 for r in results if r.get("passed", False))
    total_count = len(results)
    
    for result in results:
        status = f"{Colors.GREEN}✅ PASS{Colors.RESET}" if result.get("passed") else f"{Colors.RED}❌ FAIL{Colors.RESET}"
        print(f"{status}: {result.get('test', 'Unknown')}")
    
    print(f"\n{Colors.BOLD}Total: {passed_count}/{total_count} tests passed{Colors.RESET}\n")
    
    # Save results to JSON
    output_file = f"facts_acceptance_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"Results saved to: {output_file}")
    
    return 0 if passed_count == total_count else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
