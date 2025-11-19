from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, TypedDict, Union, Dict, Any

from .tools import repo_tools
from .config import TargetConfig

TaskType = Literal["edit_file", "create_file", "run_command"]


class BaseTask(TypedDict):
    type: TaskType


class EditFileTask(BaseTask):
    type: Literal["edit_file"]
    path: str
    intent: str
    before: str
    after: str


class CreateFileTask(BaseTask):
    type: Literal["create_file"]
    path: str
    content: str


class RunCommandTask(BaseTask):
    type: Literal["run_command"]
    cwd: str
    command: str


Task = Union[EditFileTask, CreateFileTask, RunCommandTask]


@dataclass
class TaskResult:
    task: Task
    status: Literal["success", "failed"]
    message: str


@dataclass
class ExecutionResult:
    ok: bool
    results: List[TaskResult]

    def summary(self) -> str:
        total = len(self.results)
        failed = sum(1 for r in self.results if r.status == "failed")
        return f"{total - failed}/{total} tasks succeeded, {failed} failed."


def _apply_edit_file(target: TargetConfig, task: EditFileTask) -> TaskResult:
    repo_root = Path(target.path)
    file_path = repo_root / task["path"]

    if not file_path.exists():
        return TaskResult(
            task=task,
            status="failed",
            message=f"File not found: {file_path}",
        )

    file_obj = repo_tools.read_file(target.path, task["path"])
    content = file_obj.content

    before = task["before"]
    after = task["after"]

    if before not in content:
        return TaskResult(
            task=task,
            status="failed",
            message=f"'before' snippet not found in {task['path']}.",
        )

    new_content = content.replace(before, after, 1)

    repo_tools.write_file(target.path, task["path"], new_content)

    return TaskResult(
        task=task,
        status="success",
        message=f"Edited {task['path']} ({task['intent']}).",
    )


def _apply_create_file(target: TargetConfig, task: CreateFileTask) -> TaskResult:
    repo_root = Path(target.path)
    file_path = repo_root / task["path"]

    file_path.parent.mkdir(parents=True, exist_ok=True)

    repo_tools.write_file(target.path, task["path"], task["content"])

    return TaskResult(
        task=task,
        status="success",
        message=f"Created {task['path']}.",
    )


def _apply_run_command(target: TargetConfig, task: RunCommandTask) -> TaskResult:
    repo_root = Path(target.path)
    cwd = repo_root / task["cwd"]

    try:
        completed = subprocess.run(
            task["command"],
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )

        if completed.returncode != 0:
            return TaskResult(
                task=task,
                status="failed",
                message=(
                    f"Command failed with exit code {completed.returncode}.\n"
                    f"STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}"
                ),
            )

        return TaskResult(
            task=task,
            status="success",
            message=f"Command succeeded.\nSTDOUT:\n{completed.stdout}",
        )

    except Exception as e:
        return TaskResult(
            task=task,
            status="failed",
            message=f"Exception while running command: {e}",
        )


def apply_tasks(target: TargetConfig, tasks: List[Task]) -> ExecutionResult:
    """
    Apply a list of tasks against the target repo.

    This does not yet integrate with any HTTP API or UI layer.
    It is intended to be called by the ChatDO backend once
    it parses a <TASKS> JSON block from the model output.
    """
    results: List[TaskResult] = []

    for task in tasks:
        ttype = task["type"]

        if ttype == "edit_file":
            result = _apply_edit_file(target, task)  # type: ignore[arg-type]
        elif ttype == "create_file":
            result = _apply_create_file(target, task)  # type: ignore[arg-type]
        elif ttype == "run_command":
            result = _apply_run_command(target, task)  # type: ignore[arg-type]
        else:
            result = TaskResult(
                task=task,
                status="failed",
                message=f"Unknown task type: {ttype}",
            )

        results.append(result)

    ok = all(r.status == "success" for r in results)
    return ExecutionResult(ok=ok, results=results)


def parse_tasks_block(tasks_block: str) -> List[Task]:
    """
    Parse the JSON object inside a <TASKS>...</TASKS> block and return the task list.

    The caller is responsible for extracting the inner JSON string.
    """
    data: Dict[str, Any] = json.loads(tasks_block)
    tasks = data.get("tasks", [])

    if not isinstance(tasks, list):
        raise ValueError("tasks field must be a list")

    return tasks  # type: ignore[return-value]

