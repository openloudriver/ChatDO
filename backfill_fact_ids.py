#!/usr/bin/env python3
"""
Backfill script to populate chat_messages.fact_id for all existing facts.

This script:
1. Finds all facts in the tracking database
2. For each fact, finds the corresponding chat_message by source_message_id
3. Updates chat_messages.fact_id
4. Rebuilds the ANN index so MemoryHits include fact_id
"""

import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from memory_service.memory_dashboard import db as memory_db
from memory_service.config import PROJECTS_PATH
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_all_projects_from_facts():
    """Get all unique project IDs from facts table."""
    try:
        memory_db.init_tracking_db()
        conn = memory_db.get_tracking_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT project_id FROM facts")
        projects = [row["project_id"] for row in cursor.fetchall()]
        conn.close()
        
        return projects
    except Exception as e:
        logger.error(f"Failed to get projects from facts: {e}")
        return []


def backfill_fact_ids_for_project(project_id: str):
    """Backfill fact_id for all facts in a project."""
    logger.info(f"[BACKFILL] Processing project: {project_id}")
    
    # Get all facts for this project from tracking DB
    try:
        memory_db.init_tracking_db()
        conn = memory_db.get_tracking_db_connection()
        cursor = conn.cursor()
        
        # Get all facts for this project
        cursor.execute("""
            SELECT id, project_id, chat_id, source_message_id, assistant_message_id, topic_key, kind, rank, value
            FROM facts
            WHERE project_id = ?
        """, (project_id,))
        
        facts = cursor.fetchall()
        conn.close()
        
        logger.info(f"[BACKFILL] Found {len(facts)} facts for project {project_id}")
        
        if not facts:
            return 0
        
        # For each fact, find and update the corresponding chat_message
        updated_count = 0
        source_id = f"project-{project_id}"
        
        for fact_row in facts:
            fact_id = fact_row["id"]
            source_message_id = fact_row["source_message_id"]
            chat_id = fact_row["chat_id"] if fact_row["chat_id"] else None
            
            if not source_message_id:
                logger.debug(f"[BACKFILL] Skipping fact_id {fact_id}: no source_message_id")
                continue
            
            try:
                # Initialize DB for this source
                memory_db.init_db(source_id, project_id=project_id)
                conn = memory_db.get_db_connection(source_id, project_id=project_id)
                cursor = conn.cursor()
                
                # Find chat_message by message_id
                cursor.execute("""
                    SELECT id, fact_id FROM chat_messages
                    WHERE message_id = ? AND project_id = ?
                """, (source_message_id, project_id))
                
                chat_message = cursor.fetchone()
                
                if chat_message:
                    existing_fact_id = chat_message["fact_id"]
                    if existing_fact_id == fact_id:
                        logger.debug(f"[BACKFILL] fact_id {fact_id} already set for message_id {source_message_id}")
                    else:
                        # Update chat_message with fact_id
                        cursor.execute("""
                            UPDATE chat_messages
                            SET fact_id = ?
                            WHERE id = ?
                        """, (fact_id, chat_message["id"]))
                        conn.commit()
                        updated_count += 1
                        logger.info(f"[BACKFILL] Linked fact_id {fact_id} to message_id {source_message_id} (chat_message_id={chat_message['id']})")
                else:
                    logger.debug(f"[BACKFILL] No chat_message found for message_id {source_message_id} in project {project_id} (may not be indexed yet)")
                
                conn.close()
            except Exception as e:
                logger.warning(f"[BACKFILL] Failed to update fact_id {fact_id} for message_id {source_message_id}: {e}")
                continue
        
        return updated_count
        
    except Exception as e:
        logger.error(f"[BACKFILL] Error processing project {project_id}: {e}", exc_info=True)
        return 0


def rebuild_ann_index():
    """Rebuild the ANN index to include fact_id in embeddings."""
    logger.info("[BACKFILL] Rebuilding ANN index...")
    
    try:
        from memory_service.api import ann_index_manager, _build_ann_index
        
        if ann_index_manager.is_available():
            logger.info("[BACKFILL] Clearing existing ANN index...")
            ann_index_manager.clear()
            
            logger.info("[BACKFILL] Rebuilding ANN index with fact_id...")
            _build_ann_index()
            
            logger.info("[BACKFILL] ✅ ANN index rebuilt successfully")
            return True
        else:
            logger.warning("[BACKFILL] ANN index manager not available, skipping rebuild")
            return False
    except Exception as e:
        logger.error(f"[BACKFILL] Failed to rebuild ANN index: {e}", exc_info=True)
        return False


def main():
    """Main backfill function."""
    logger.info("=" * 80)
    logger.info("Starting fact_id backfill...")
    logger.info("=" * 80)
    
    # Get all projects from facts table
    projects = get_all_projects_from_facts()
    logger.info(f"[BACKFILL] Found {len(projects)} projects with facts")
    
    if not projects:
        logger.warning("[BACKFILL] No projects found, nothing to backfill")
        return
    
    # Backfill fact_id for each project
    total_updated = 0
    for project_id in projects:
        updated = backfill_fact_ids_for_project(project_id)
        total_updated += updated
        logger.info(f"[BACKFILL] Updated {updated} chat_messages for project {project_id}")
    
    logger.info(f"[BACKFILL] Total chat_messages updated: {total_updated}")
    
    # Rebuild ANN index
    rebuild_ann_index()
    
    logger.info("=" * 80)
    logger.info("✅ Backfill complete!")
    logger.info("=" * 80)


if __name__ == "__main__":
    main()

