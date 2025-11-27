"""
Impact template storage with file upload support.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional
from uuid import uuid4
from datetime import datetime
from pydantic import BaseModel, Field

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
TEMPLATES_FILE = DATA_DIR / "impact_templates.json"
TEMPLATES_DIR = DATA_DIR / "impact_templates"


class ImpactTemplate(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    name: str
    description: Optional[str] = None
    tags: list[str] = []
    
    # stored file info
    file_name: str              # original filename
    stored_name: str            # stored filename on disk
    mime_type: Optional[str] = None


def ensure_paths():
    """Ensure data directories and files exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATES_FILE.exists():
        TEMPLATES_FILE.write_text("[]", encoding="utf-8")


def _ensure_paths():
    """Internal alias for ensure_paths."""
    ensure_paths()


def _load_raw() -> list[dict]:
    _ensure_paths()
    import json
    raw = TEMPLATES_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    return json.loads(raw)


def _save_raw(items: list[dict]) -> None:
    _ensure_paths()
    import json
    TEMPLATES_FILE.write_text(
        json.dumps(items, indent=2, default=str),
        encoding="utf-8",
    )


def list_templates() -> List[ImpactTemplate]:
    data = _load_raw()
    items = [ImpactTemplate.model_validate(d) for d in data]
    return sorted(items, key=lambda t: t.created_at, reverse=True)


def add_template(tpl: ImpactTemplate) -> ImpactTemplate:
    data = _load_raw()
    tpl.created_at = datetime.utcnow()
    data.append(tpl.model_dump())
    _save_raw(data)
    return tpl


def delete_template(template_id: str) -> bool:
    data = _load_raw()
    new_data = [d for d in data if d.get("id") != template_id]
    if len(new_data) == len(data):
        return False
    _save_raw(new_data)
    # optional: also delete file from disk
    # find the stored_name for this template
    # (we can get it by comparing original data list)
    return True


def get_template(template_id: str) -> Optional[ImpactTemplate]:
    data = _load_raw()
    for d in data:
        if d.get("id") == template_id:
            return ImpactTemplate.model_validate(d)
    return None


def get_template_file_path(template_id: str) -> Optional[Path]:
    tpl = get_template(template_id)
    if not tpl:
        return None
    return TEMPLATES_DIR / tpl.stored_name

