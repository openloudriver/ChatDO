"""
Sentinel test to verify async test runner is working.

This test will fail loudly if asyncio support regresses.
"""
import pytest


@pytest.mark.asyncio
async def test_async_runner_works():
    """Verify that async tests can run."""
    assert True

