"""
Shared pytest fixtures for Facts system tests.

Provides self-contained database setup with test isolation.
Uses pytest's tmp_path to create isolated SQLite databases per test.
"""
import pytest
import uuid
import os
from pathlib import Path
from memory_service.memory_dashboard import db
from memory_service import config


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

