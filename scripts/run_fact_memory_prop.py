#!/usr/bin/env python3
"""
Repeatable test runner for Fact Memory property tests.

Runs pytest multiple times with different seeds, stopping on first failure.
"""
import argparse
import subprocess
import sys
import os


def main():
    parser = argparse.ArgumentParser(description="Run Fact Memory property tests with varying seeds")
    parser.add_argument(
        "--runs",
        type=int,
        default=100,
        help="Number of test runs (default: 100)"
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=42000,
        help="Base seed value (default: 42000)"
    )
    parser.add_argument(
        "--stress",
        action="store_true",
        help="Include stress tests (-m stress)"
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help="Run only smoke tests"
    )
    
    args = parser.parse_args()
    
    # Build pytest command
    pytest_cmd = ["python3", "-m", "pytest", "tests/property/test_fact_memory_property.py", "-q"]
    
    if args.stress:
        pytest_cmd.extend(["-m", "stress"])
    
    if args.smoke_only:
        pytest_cmd.extend(["-m", "smoke"])
    
    print(f"Running {args.runs} test runs with base_seed={args.base_seed}")
    print(f"Pytest command: {' '.join(pytest_cmd)}")
    print("-" * 80)
    
    # Run tests with different seeds
    for i in range(args.runs):
        seed = args.base_seed + i
        print(f"\n[Run {i+1}/{args.runs}] SEED={seed}")
        
        # Set environment variable
        env = os.environ.copy()
        env["SEED"] = str(seed)
        
        # Run pytest
        result = subprocess.run(
            pytest_cmd,
            env=env,
            capture_output=False,  # Let output flow through
            text=True
        )
        
        if result.returncode != 0:
            print("\n" + "=" * 80)
            print("FAILURE DETECTED")
            print("=" * 80)
            print(f"Failing seed: {seed}")
            print(f"Exact pytest command to reproduce:")
            print(f"  SEED={seed} {' '.join(pytest_cmd)}")
            print("=" * 80)
            sys.exit(1)
    
    print("\n" + "=" * 80)
    print(f"SUCCESS: All {args.runs} runs passed!")
    print("=" * 80)
    sys.exit(0)


if __name__ == "__main__":
    main()

