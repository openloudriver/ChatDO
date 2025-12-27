"""
Alias Table for canonical topic mappings.

The Alias Table is separate from Facts and provides authoritative mappings
from human expressions to canonical topics. It is global (shared across projects).

Schema:
{
  "canonical_topic": "crypto",
  "aliases": ["cryptocurrency", "cryptocurrencies", "digital currency"],
  "embedding": [vector],
  "created_by": "teacher",
  "confidence": 1.0,
  "created_at": timestamp
}
"""
import logging
import json
import numpy as np
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

logger = logging.getLogger(__name__)

# Alias table database path (global, not project-specific)
ALIAS_TABLE_DB_PATH = Path(__file__).parent.parent.parent / "data" / "alias_table.db"


@dataclass
class AliasEntry:
    """Represents an alias table entry."""
    canonical_topic: str
    aliases: List[str]
    embedding: Optional[np.ndarray] = None  # Stored as bytes in DB
    created_by: str = "teacher"
    confidence: float = 1.0
    created_at: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        result = asdict(self)
        # Convert numpy array to list for JSON serialization
        if result.get("embedding") is not None and isinstance(result["embedding"], np.ndarray):
            result["embedding"] = result["embedding"].tolist()
        return result


@dataclass
class AliasMatchResult:
    """Result of alias table lookup."""
    canonical_topic: str
    matched_alias: Optional[str] = None  # Which alias matched
    confidence: float = 1.0


class AliasTable:
    """
    Alias Table for canonical topic mappings.
    
    This table is global (shared across all projects) and provides
    authoritative mappings from human expressions to canonical topics.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the alias table.
        
        Args:
            db_path: Optional path to alias table database (defaults to global path)
        """
        self.db_path = db_path or ALIAS_TABLE_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize the alias table database schema."""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS alias_entries (
                canonical_topic TEXT PRIMARY KEY,
                aliases_json TEXT NOT NULL,
                embedding_blob BLOB,
                created_by TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        
        # Index for faster alias lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_aliases_json 
            ON alias_entries(aliases_json)
        """)
        
        conn.commit()
        conn.close()
        logger.debug(f"[ALIAS-TABLE] Initialized database at {self.db_path}")
    
    def add_entry(
        self,
        canonical_topic: str,
        aliases: List[str],
        embedding: Optional[np.ndarray] = None,
        created_by: str = "teacher",
        confidence: float = 1.0
    ) -> bool:
        """
        Add or update an alias table entry.
        
        Args:
            canonical_topic: The canonical topic name
            aliases: List of aliases that map to this canonical topic
            embedding: Optional embedding vector for the canonical topic
            created_by: Who created this entry ("teacher", "system", etc.)
            confidence: Confidence score (0.0 to 1.0)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Prepare embedding blob
            embedding_blob = None
            if embedding is not None:
                embedding_blob = embedding.tobytes()
            
            # Serialize aliases
            aliases_json = json.dumps(aliases)
            
            # Insert or replace
            cursor.execute("""
                INSERT OR REPLACE INTO alias_entries
                (canonical_topic, aliases_json, embedding_blob, created_by, confidence, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                canonical_topic,
                aliases_json,
                embedding_blob,
                created_by,
                confidence,
                datetime.now(timezone.utc).isoformat()
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(
                f"[ALIAS-TABLE] Added entry: '{canonical_topic}' with {len(aliases)} aliases"
            )
            return True
            
        except Exception as e:
            logger.error(f"[ALIAS-TABLE] Error adding entry: {e}", exc_info=True)
            return False
    
    def find_canonical(
        self,
        alias: str,
        exact_match: bool = True
    ) -> Optional[AliasMatchResult]:
        """
        Find canonical topic for a given alias.
        
        Args:
            alias: The alias to look up
            exact_match: If True, only exact matches. If False, also check normalized.
            
        Returns:
            AliasMatchResult if found, None otherwise
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            # Normalize alias for lookup
            normalized_alias = alias.lower().strip()
            
            # Query all entries
            cursor.execute("""
                SELECT canonical_topic, aliases_json
                FROM alias_entries
            """)
            
            for row in cursor.fetchall():
                canonical_topic, aliases_json = row
                aliases = json.loads(aliases_json)
                
                # Check if alias matches (exact or normalized)
                for entry_alias in aliases:
                    entry_alias_normalized = entry_alias.lower().strip()
                    
                    if exact_match:
                        if entry_alias_normalized == normalized_alias:
                            conn.close()
                            return AliasMatchResult(
                                canonical_topic=canonical_topic,
                                matched_alias=entry_alias,
                                confidence=1.0
                            )
                    else:
                        # Also check if normalized versions match
                        if entry_alias_normalized == normalized_alias:
                            conn.close()
                            return AliasMatchResult(
                                canonical_topic=canonical_topic,
                                matched_alias=entry_alias,
                                confidence=1.0
                            )
                
                # Also check if the canonical topic itself matches
                canonical_normalized = canonical_topic.lower().strip()
                if canonical_normalized == normalized_alias:
                    conn.close()
                    return AliasMatchResult(
                        canonical_topic=canonical_topic,
                        matched_alias=canonical_topic,
                        confidence=1.0
                    )
            
            conn.close()
            return None
            
        except Exception as e:
            logger.error(f"[ALIAS-TABLE] Error finding canonical: {e}", exc_info=True)
            return None
    
    def get_all_canonical_topics(
        self
    ) -> List[Tuple[str, Optional[np.ndarray]]]:
        """
        Get all canonical topics with their embeddings.
        
        Returns:
            List of (canonical_topic, embedding) tuples
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT canonical_topic, embedding_blob
                FROM alias_entries
            """)
            
            results = []
            for row in cursor.fetchall():
                canonical_topic, embedding_blob = row
                embedding = None
                if embedding_blob is not None:
                    # Reconstruct numpy array from bytes
                    embedding = np.frombuffer(embedding_blob, dtype=np.float32).copy()
                results.append((canonical_topic, embedding))
            
            conn.close()
            return results
            
        except Exception as e:
            logger.error(f"[ALIAS-TABLE] Error getting canonical topics: {e}", exc_info=True)
            return []
    
    def get_entry(self, canonical_topic: str) -> Optional[AliasEntry]:
        """
        Get a specific alias table entry.
        
        Args:
            canonical_topic: The canonical topic to retrieve
            
        Returns:
            AliasEntry if found, None otherwise
        """
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT canonical_topic, aliases_json, embedding_blob, created_by, confidence, created_at
                FROM alias_entries
                WHERE canonical_topic = ?
            """, (canonical_topic,))
            
            row = cursor.fetchone()
            conn.close()
            
            if row:
                canonical_topic, aliases_json, embedding_blob, created_by, confidence, created_at = row
                aliases = json.loads(aliases_json)
                embedding = None
                if embedding_blob is not None:
                    # Reconstruct numpy array from bytes
                    embedding = np.frombuffer(embedding_blob, dtype=np.float32).copy()
                
                return AliasEntry(
                    canonical_topic=canonical_topic,
                    aliases=aliases,
                    embedding=embedding,
                    created_by=created_by,
                    confidence=confidence,
                    created_at=created_at
                )
            
            return None
            
        except Exception as e:
            logger.error(f"[ALIAS-TABLE] Error getting entry: {e}", exc_info=True)
            return None

