"""
FileTree Manager for Memory Service (Phase 1).

Provides read-only filesystem access to Memory Sources:
- List directory trees within a source's root path
- Read file contents safely (bounded, path-validated)
"""
import pathlib
import logging
from pathlib import Path
from typing import Optional
from fastapi import HTTPException

from memory_service.models import FileTreeResponse, FileReadResponse, FileTreeNode
from memory_service.store import db

logger = logging.getLogger(__name__)


class FileTreeManager:
    """Manages read-only filesystem access to Memory Sources."""
    
    def __init__(self):
        """Initialize FileTreeManager."""
        logger.info("[FILETREE] FileTreeManager initialized")
    
    def get_source_root(self, source_id: str) -> Path:
        """
        Look up the source in the tracking DB and return its root directory as a Path.
        
        Raises HTTPException(404) if source not found.
        """
        # Try to get from tracking DB first (most reliable)
        source_status = db.get_source_status(source_id)
        if source_status:
            root_path = Path(source_status.root_path).expanduser().resolve()
            if not root_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Source root path does not exist: {root_path}"
                )
            return root_path
        
        # Fallback: try per-source database
        source = db.get_source_by_source_id(source_id)
        if source:
            root_path = Path(source.root_path).expanduser().resolve()
            if not root_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Source root path does not exist: {root_path}"
                )
            return root_path
        
        raise HTTPException(
            status_code=404,
            detail=f"Source not found: {source_id}"
        )
    
    def _validate_path(self, root: Path, rel_path: str) -> Path:
        """
        Validate that rel_path is safe and within root.
        
        Returns the resolved target path.
        Raises HTTPException(400) if path escapes root.
        """
        # Normalize root
        root = root.resolve()
        
        # Build target path
        if rel_path:
            # Remove leading slashes to make it relative
            rel_path = rel_path.lstrip('/')
            target = (root / rel_path).resolve()
        else:
            target = root
        
        # Ensure target is still under root (prevents ../ traversal and symlink escapes)
        try:
            target.relative_to(root)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Path escapes source root: {rel_path}"
            )
        
        return target
    
    def list_tree(
        self,
        source_id: str,
        rel_path: str = "",
        max_depth: int = 2,
        max_entries: int = 500,
    ) -> FileTreeResponse:
        """
        List the directory tree starting at `rel_path` within the source root,
        up to `max_depth` levels deep.
        
        Returns a FileTreeResponse with a root FileTreeNode.
        """
        logger.info(f"[FILETREE] Listing source={source_id} path={rel_path} depth={max_depth}")
        
        # Get source root
        root = self.get_source_root(source_id)
        
        # Validate and resolve target path
        target = self._validate_path(root, rel_path)
        
        if not target.exists():
            raise HTTPException(
                status_code=404,
                detail=f"Path does not exist: {rel_path}"
            )
        
        # Build tree node
        node = self._build_tree_node(target, root, max_depth, max_entries, current_depth=0)
        
        return FileTreeResponse(
            source_id=source_id,
            root=node
        )
    
    def _build_tree_node(
        self,
        path: Path,
        root: Path,
        max_depth: int,
        max_entries: int,
        current_depth: int,
        entry_count: list = None  # Use list to pass by reference
    ) -> FileTreeNode:
        """
        Recursively build a FileTreeNode from a filesystem path.
        
        Args:
            path: The filesystem path to build node for
            root: The source root path (for computing relative paths)
            max_depth: Maximum depth to traverse
            max_entries: Maximum total entries to include
            current_depth: Current depth in traversal
            entry_count: List with single int to track total entries (mutated)
        """
        if entry_count is None:
            entry_count = [0]
        
        # Check entry limit
        if entry_count[0] >= max_entries:
            return None  # Signal to stop
        
        entry_count[0] += 1
        
        # Get relative path (POSIX style)
        try:
            rel_path = path.relative_to(root).as_posix()
        except ValueError:
            # Path is not under root (shouldn't happen after validation, but be safe)
            rel_path = str(path)
        
        # Get file stats
        try:
            stat = path.stat()
            size_bytes = stat.st_size if path.is_file() else None
            modified_at = stat.st_mtime
            from datetime import datetime
            modified_dt = datetime.fromtimestamp(modified_at)
        except OSError:
            size_bytes = None
            modified_dt = None
        
        # Build node
        node = FileTreeNode(
            name=path.name,
            path=rel_path if rel_path != '.' else '',
            is_dir=path.is_dir(),
            size_bytes=size_bytes,
            modified_at=modified_dt
        )
        
        # If it's a directory and we haven't hit depth limit, add children
        if path.is_dir() and current_depth < max_depth:
            children = []
            try:
                # Sort: directories first, then files, both alphabetically
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
                
                for entry in entries:
                    if entry_count[0] >= max_entries:
                        break
                    
                    child = self._build_tree_node(
                        entry,
                        root,
                        max_depth,
                        max_entries,
                        current_depth + 1,
                        entry_count
                    )
                    if child is not None:
                        children.append(child)
            except PermissionError:
                logger.warning(f"[FILETREE] Permission denied reading directory: {path}")
            except OSError as e:
                logger.warning(f"[FILETREE] Error reading directory {path}: {e}")
            
            node.children = children if children else None
        
        return node
    
    def read_file(
        self,
        source_id: str,
        rel_path: str,
        max_bytes: int = 65536,  # 64KB default
    ) -> FileReadResponse:
        """
        Read a single file within the source root.
        
        Attempts to decode as text (utf-8 with errors='replace').
        If not decodable or obviously binary, marks encoding='binary' and omits content.
        Enforces max_bytes limit and sets truncated=True when hit.
        """
        logger.info(f"[FILETREE] Reading file source={source_id} path={rel_path} max_bytes={max_bytes}")
        
        # Get source root
        root = self.get_source_root(source_id)
        
        # Validate and resolve target path
        target = self._validate_path(root, rel_path)
        
        if not target.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File does not exist: {rel_path}"
            )
        
        if target.is_dir():
            raise HTTPException(
                status_code=400,
                detail=f"Path is a directory, not a file: {rel_path}"
            )
        
        # Get file size
        try:
            stat = target.stat()
            size_bytes = stat.st_size
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error reading file stats: {e}"
            )
        
        # Read file (up to max_bytes + 1 to detect truncation)
        try:
            with open(target, 'rb') as f:
                content_bytes = f.read(max_bytes + 1)
        except PermissionError:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied reading file: {rel_path}"
            )
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error reading file: {e}"
            )
        
        # Check if truncated
        truncated = len(content_bytes) > max_bytes
        if truncated:
            content_bytes = content_bytes[:max_bytes]
        
        # Try to decode as UTF-8
        encoding = "utf-8"
        content = None
        is_binary = False
        
        try:
            content = content_bytes.decode("utf-8", errors="replace")
            
            # Check if it looks binary (high proportion of replacement chars or null bytes)
            if b'\x00' in content_bytes:
                # Contains null bytes - definitely binary
                encoding = "binary"
                content = None
                is_binary = True
            elif content_bytes and content.count('\ufffd') / len(content) > 0.1:
                # More than 10% replacement characters - likely binary
                encoding = "binary"
                content = None
                is_binary = True
        except Exception:
            encoding = "binary"
            content = None
            is_binary = True
        
        logger.info(f"[FILETREE] Read file source={source_id} path={rel_path} size={size_bytes} truncated={truncated} encoding={encoding} is_binary={is_binary}")
        
        return FileReadResponse(
            source_id=source_id,
            path=rel_path,
            encoding=encoding,
            size_bytes=size_bytes,
            content=content,
            truncated=truncated,
            is_binary=is_binary
        )

