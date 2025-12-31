"""
Shared pytest fixtures for Facts system tests.

Provides self-contained database setup with test isolation.
Uses pytest's tmp_path to create isolated SQLite databases per test.
"""
import pytest
import uuid
import os
import warnings
from pathlib import Path
from collections import defaultdict
from memory_service.memory_dashboard import db
from memory_service import config

# Allowlist of known warning signatures (warning_class, message_substring, file_pattern)
ALLOWED_WARNINGS = [
    # sqlite3 datetime adapter deprecation (Python 3.12+)
    (
        DeprecationWarning,
        "The default datetime adapter is deprecated as of Python 3.12",
        ("memory_service/memory_dashboard/db.py", "server/services/facts_apply.py")
    ),
]

# Track unexpected warnings during test run
_unexpected_warnings = defaultdict(list)


def pytest_configure(config):
    """Configure pytest to track warnings."""
    # Register custom warning filter
    warnings.filterwarnings("default", category=DeprecationWarning)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Track warnings during test execution."""
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        yield
        # Check each warning
        for warning in w:
            if not _is_allowed_warning(warning):
                # Extract file info
                filename = warning.filename if hasattr(warning, 'filename') else 'unknown'
                lineno = warning.lineno if hasattr(warning, 'lineno') else 0
                _unexpected_warnings[(warning.category.__name__, str(warning.message))].append(
                    f"{filename}:{lineno}"
                )


def _is_allowed_warning(warning):
    """Check if a warning is in the allowlist."""
    warning_class = type(warning.message)
    warning_message = str(warning.message)
    warning_file = getattr(warning, 'filename', '')
    
    for allowed_class, allowed_message_substring, allowed_files in ALLOWED_WARNINGS:
        if warning_class == allowed_class:
            if allowed_message_substring in warning_message:
                # Check if file matches pattern
                if any(allowed_file in warning_file for allowed_file in allowed_files):
                    return True
    return False


def pytest_sessionfinish(session, exitstatus):
    """Check for unexpected warnings at end of test session."""
    if _unexpected_warnings:
        print("\n" + "=" * 80)
        print("UNEXPECTED WARNINGS DETECTED")
        print("=" * 80)
        for (warning_class, message), locations in sorted(_unexpected_warnings.items()):
            print(f"\n{warning_class}: {message}")
            print(f"  Locations: {', '.join(set(locations))}")
        print("\n" + "=" * 80)
        print("If these warnings are expected, add them to ALLOWED_WARNINGS in conftest.py")
        print("=" * 80)
        # Don't fail the test run, just warn (we want to see new warnings but not break CI)
        # If you want to fail on unexpected warnings, uncomment:
        # session.exitstatus = 1


@pytest.fixture(scope="function")
def test_project_id():
    """Generate a unique project ID for each test."""
    return str(uuid.uuid4())


@pytest.fixture(scope="function")
def test_thread_id():
    """Generate a unique thread ID for each test."""
    return f"test-thread-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="function")
def test_db_setup(test_project_id, tmp_path, monkeypatch):
    """
    Set up a test database for Facts persistence with complete isolation.
    
    Uses pytest's tmp_path to create isolated SQLite databases per test.
    Ensures schema is created and connections are properly cleaned up.
    """
    # Create a temporary directory for this test's database
    test_db_dir = tmp_path / "test_db"
    test_db_dir.mkdir(parents=True, exist_ok=True)
    
    # Store original function
    original_get_db_path = config.get_db_path_for_source
    
    def test_get_db_path(source_id: str, project_id: str = None):
        """Override to use test directory instead of production paths."""
        # For project sources, create a test-specific path
        if source_id.startswith("project-"):
            # Extract project_id from source_id
            actual_project_id = source_id.replace("project-", "")
            lookup_project_id = project_id if project_id else actual_project_id
            
            # Create test-specific project directory
            project_test_dir = test_db_dir / lookup_project_id / "index"
            project_test_dir.mkdir(parents=True, exist_ok=True)
            return project_test_dir / "index.sqlite"
        else:
            # For non-project sources, use test directory
            source_test_dir = test_db_dir / source_id
            source_test_dir.mkdir(parents=True, exist_ok=True)
            return source_test_dir / "index.sqlite"
    
    # Monkeypatch the config function
    monkeypatch.setattr(config, "get_db_path_for_source", test_get_db_path)
    
    # Initialize the database
    source_id = f"project-{test_project_id}"
    db.init_db(source_id, project_id=test_project_id)
    
    # Get the DB path (will be used by all Facts operations)
    db_path = config.get_db_path_for_source(source_id, project_id=test_project_id)
    
    # Ensure DB file exists by creating a connection and committing
    # SQLite creates the file on first connection, but we need to ensure it's flushed
    conn = db.get_db_connection(source_id, project_id=test_project_id)
    conn.commit()  # Ensure any pending writes are flushed
    conn.close()
    
    # Note: DB file may not exist until first write, but directory structure is guaranteed
    # Tests will verify schema when they use the DB
    
    yield {
        "project_id": test_project_id,
        "source_id": source_id,
        "db_dir": test_db_dir,
        "db_path": db_path
    }
    
    # Cleanup: close all connections
    try:
        conn = db.get_db_connection(source_id, project_id=test_project_id)
        conn.close()
    except Exception:
        pass
    
    # Note: tmp_path is automatically cleaned up by pytest, so we don't need to manually delete

