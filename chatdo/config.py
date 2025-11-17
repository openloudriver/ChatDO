import pathlib
import yaml
from dataclasses import dataclass
from typing import List

@dataclass
class TargetConfig:
    name: str
    path: pathlib.Path
    type: str
    core_paths: List[pathlib.Path]

def load_target(name: str) -> TargetConfig:
    here = pathlib.Path(__file__).resolve().parent.parent
    targets_dir = here / "targets"
    cfg_path = targets_dir / f"{name}.yaml"
    if not cfg_path.exists():
        raise SystemExit(f"Target config not found: {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text())
    repo_path = pathlib.Path(data["path"]).expanduser().resolve()
    core_paths = [
        (repo_path / p).resolve() for p in data.get("core_paths", [])
    ]
    return TargetConfig(
        name=data["name"],
        path=repo_path,
        type=data.get("type", "monorepo"),
        core_paths=core_paths,
    )

