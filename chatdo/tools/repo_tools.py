from dataclasses import dataclass
from typing import List, Optional
import pathlib
import textwrap

@dataclass
class RepoFile:
    path: str
    content: str

def list_files(root: pathlib.Path, glob: str) -> List[str]:
    return [str(p.relative_to(root)) for p in root.rglob(glob)]

def read_file(root: pathlib.Path, rel_path: str) -> RepoFile:
    path = (root / rel_path).resolve()
    content = path.read_text(encoding="utf-8")
    return RepoFile(path=str(path), content=content)

def write_file(root: pathlib.Path, rel_path: str, new_content: str) -> None:
    path = (root / rel_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(new_content, encoding="utf-8")

def apply_patch(original: str, patch: str) -> str:
    """
    Super simple 'replace section' helper:
    patch should contain `--- OLD` and `+++ NEW` markers.
    This is intentionally dumb to start; we can upgrade later.
    """
    if "--- OLD" not in patch or "+++ NEW" not in patch:
        raise ValueError("Patch missing markers")
    before, rest = patch.split("--- OLD", 1)
    old, after = rest.split("+++ NEW", 1)
    new = after
    old = textwrap.dedent(old).strip("\n")
    new = textwrap.dedent(new).strip("\n")
    return original.replace(old, new)

