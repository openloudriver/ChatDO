"""
Impact entry storage using JSON-backed file system.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from uuid import uuid4
from datetime import datetime, date
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
IMPACTS_FILE = DATA_DIR / "impacts.json"


class ImpactEntry(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # core fields
    title: str
    date: Optional[date] = None          # when it happened
    context: Optional[str] = None        # where / who / mission
    actions: str                         # what I did
    impact: Optional[str] = None         # why it mattered
    metrics: Optional[str] = None        # numbers / scope
    tags: list[str] = []                 # e.g. ["AF", "Northstead"]
    notes: Optional[str] = None          # extra detail


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
    return json.loads(raw)


def _save_raw(items: list[dict]) -> None:
    _ensure_file()
    import json
    IMPACTS_FILE.write_text(
        json.dumps(items, indent=2, default=str),
        encoding="utf-8",
    )


def list_impacts() -> List[ImpactEntry]:
    data = _load_raw()
    items = [ImpactEntry.model_validate(d) for d in data]
    # newest first, by date if present, else created_at
    return sorted(items, key=lambda i: i.date or i.created_at, reverse=True)


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
            raw.update({k: v for k, v in patch.items() if v is not None})
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

