"""
Template storage and metadata management.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Dict, Any
from uuid import uuid4
from datetime import datetime
import json
import shutil

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_METADATA_FILE = DATA_DIR / "template_metadata.json"


class TemplateMetadata:
    """Metadata for an uploaded template."""
    def __init__(
        self,
        template_id: str,
        filename: str,
        ext: str,
        path: Path,
        fields: Optional[List[Dict[str, Any]]] = None,
        created_at: Optional[datetime] = None,
    ):
        self.template_id = template_id
        self.filename = filename
        self.ext = ext
        self.path = path
        self.fields = fields or []
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "template_id": self.template_id,
            "filename": self.filename,
            "ext": self.ext,
            "path": str(self.path),
            "fields": self.fields,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TemplateMetadata:
        return cls(
            template_id=data["template_id"],
            filename=data["filename"],
            ext=data["ext"],
            path=Path(data["path"]),
            fields=data.get("fields", []),
            created_at=datetime.fromisoformat(data["created_at"]) if isinstance(data.get("created_at"), str) else data.get("created_at"),
        )


def _ensure_paths():
    """Ensure template directories exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    if not TEMPLATES_METADATA_FILE.exists():
        TEMPLATES_METADATA_FILE.write_text("{}", encoding="utf-8")


def _load_metadata() -> Dict[str, Dict[str, Any]]:
    """Load all template metadata."""
    _ensure_paths()
    if not TEMPLATES_METADATA_FILE.exists():
        return {}
    raw = TEMPLATES_METADATA_FILE.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _save_metadata(metadata_dict: Dict[str, Dict[str, Any]]) -> None:
    """Save template metadata."""
    _ensure_paths()
    TEMPLATES_METADATA_FILE.write_text(
        json.dumps(metadata_dict, indent=2, default=str),
        encoding="utf-8",
    )


def save_template(file_content: bytes, filename: str) -> TemplateMetadata:
    """
    Save an uploaded template file to disk.
    
    Args:
        file_content: Raw file bytes
        filename: Original filename
        
    Returns:
        TemplateMetadata with id, filename, ext, path
    """
    _ensure_paths()
    
    template_id = uuid4().hex
    ext = Path(filename).suffix.lower() or ""
    stored_filename = f"original{ext}"
    
    template_dir = TEMPLATES_DIR / template_id
    template_dir.mkdir(parents=True, exist_ok=True)
    
    template_path = template_dir / stored_filename
    template_path.write_bytes(file_content)
    
    metadata = TemplateMetadata(
        template_id=template_id,
        filename=filename,
        ext=ext,
        path=template_path,
    )
    
    # Save metadata
    all_metadata = _load_metadata()
    all_metadata[template_id] = metadata.to_dict()
    _save_metadata(all_metadata)
    
    return metadata


def list_templates() -> List[TemplateMetadata]:
    """Return all uploaded templates."""
    all_metadata = _load_metadata()
    return [TemplateMetadata.from_dict(data) for data in all_metadata.values()]


def get_template(template_id: str) -> Optional[TemplateMetadata]:
    """Load template metadata by ID."""
    all_metadata = _load_metadata()
    if template_id not in all_metadata:
        return None
    return TemplateMetadata.from_dict(all_metadata[template_id])


def update_template_fields(template_id: str, fields: List[Dict[str, Any]]) -> bool:
    """Update the identified fields for a template."""
    all_metadata = _load_metadata()
    if template_id not in all_metadata:
        return False
    
    all_metadata[template_id]["fields"] = fields
    _save_metadata(all_metadata)
    return True


def save_autofilled_output(template_id: str, output_text: str) -> Path:
    """
    Save autofilled output to template's autofill folder.
    
    Args:
        template_id: Template ID
        output_text: Generated filled text
        
    Returns:
        Path to saved file
    """
    template = get_template(template_id)
    if not template:
        raise ValueError(f"Template {template_id} not found")
    
    autofill_dir = template.path.parent / "autofill"
    autofill_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    output_path = autofill_dir / f"{timestamp}.txt"
    output_path.write_text(output_text, encoding="utf-8")
    
    return output_path


def get_latest_autofill(template_id: str) -> Optional[Path]:
    """Get the most recent autofilled output for a template."""
    template = get_template(template_id)
    if not template:
        return None
    
    autofill_dir = template.path.parent / "autofill"
    if not autofill_dir.exists():
        return None
    
    autofill_files = sorted(autofill_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not autofill_files:
        return None
    
    return autofill_files[0]

