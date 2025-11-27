"""
Impact entry storage using JSON-backed file system.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional
from uuid import uuid4
from datetime import datetime, date as date_type
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IMPACTS_FILE = DATA_DIR / "impacts.json"


class ImpactEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # core fields
    title: str
    date: Optional[date_type] = None          # when it happened - accepts date object or None
    context: Optional[str] = None        # where / who / mission
    actions: str                         # what I did
    impact: Optional[str] = None         # why it mattered
    metrics: Optional[str] = None        # numbers / scope
    tags: list[str] = []                 # e.g. ["AF", "Northstead"]
    notes: Optional[str] = None          # extra detail
    activeBullet: Optional[str] = None   # current working bullet text for this impact


def _ensure_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not IMPACTS_FILE.exists():
        IMPACTS_FILE.write_text("[]", encoding="utf-8")


def _load_raw() -> list[dict]:
    _ensure_file()
    import json
    raw = IMPACTS_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        # If JSON is corrupted, try to recover by reading up to the error position
        logger = logging.getLogger(__name__)
        logger.error(f"Corrupted JSON in impacts file: {e}")
        # Try to find the last valid closing bracket
        last_valid_bracket = raw.rfind(']')
        if last_valid_bracket > 0:
            try:
                valid_json = raw[:last_valid_bracket + 1]
                data = json.loads(valid_json)
                logger.warning(f"Recovered {len(data)} impacts from corrupted file")
                # Save the recovered data
                _save_raw(data)
                return data
            except:
                pass
        # If recovery fails, return empty list and log error
        logger.error("Could not recover impacts file, returning empty list")
        return []


def _save_raw(items: list[dict]) -> None:
    _ensure_file()
    import json
    import tempfile
    # Write to a temporary file first, then rename to prevent corruption
    temp_file = IMPACTS_FILE.with_suffix('.json.tmp')
    try:
        temp_file.write_text(
            json.dumps(items, indent=2, default=str),
            encoding="utf-8",
        )
        # Atomic rename
        temp_file.replace(IMPACTS_FILE)
    except Exception as e:
        # Clean up temp file on error
        if temp_file.exists():
            temp_file.unlink()
        raise


def list_impacts() -> List[ImpactEntry]:
    data = _load_raw()
    items = [ImpactEntry.model_validate(d) for d in data]
    # newest first, by date if present, else created_at
    # Convert date to datetime for consistent comparison
    def sort_key(i: ImpactEntry):
        if i.date:
            # Convert date to datetime at midnight for comparison
            return datetime.combine(i.date, datetime.min.time())
        return i.created_at
    return sorted(items, key=sort_key, reverse=True)


def create_impact(entry: ImpactEntry) -> ImpactEntry:
    data = _load_raw()
    now = datetime.utcnow()
    entry.created_at = now
    entry.updated_at = now
    data.append(entry.model_dump())
    _save_raw(data)
    return entry


def update_impact(entry_id: str, patch: dict) -> Optional[ImpactEntry]:
    data = _load_raw()
    found = None
    for idx, raw in enumerate(data):
        if raw.get("id") == entry_id:
            # Update all fields from patch, including None values for optional fields
            # This allows clearing optional fields like activeBullet
            for k, v in patch.items():
                if v is None:
                    # Explicitly set to None for optional fields
                    raw[k] = None
                else:
                    raw[k] = v
            raw["updated_at"] = datetime.utcnow().isoformat()
            data[idx] = raw
            found = ImpactEntry.model_validate(raw)
            break
    if found:
        _save_raw(data)
    return found


def delete_impact(entry_id: str) -> bool:
    data = _load_raw()
    new_data = [d for d in data if d.get("id") != entry_id]
    if len(new_data) == len(data):
        return False
    _save_raw(new_data)
    return True

