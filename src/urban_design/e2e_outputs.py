"""Safe path resolution and reporting for disposable browser E2E outputs."""

from __future__ import annotations

import tempfile
from pathlib import Path


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def describe_output_path(path: Path, *, project_root: Path) -> dict[str, str]:
    resolved = path.resolve()
    root = project_root.resolve()
    if _within(resolved, root):
        return {"kind": "project_relative", "path": resolved.relative_to(root).as_posix()}
    return {"kind": "absolute_temporary", "path": str(resolved)}


def resolve_e2e_output_directory(
    path: str | Path,
    *,
    project_root: str | Path,
) -> tuple[Path, dict[str, str]]:
    """Resolve a fresh output directory within the project or a temp root."""
    supplied = Path(path).expanduser()
    root = Path(project_root).resolve()
    lexical = supplied if supplied.is_absolute() else root / supplied
    if lexical.exists() or lexical.is_symlink():
        raise FileExistsError(f"E2E output path already exists; refusing to overwrite: {lexical}")
    target = lexical.resolve()
    if supplied.is_absolute() and not _within(target, root):
        temporary_roots = {Path(tempfile.gettempdir()).resolve(), Path("/private/tmp").resolve()}
        if not any(_within(target, temporary_root) for temporary_root in temporary_roots):
            raise ValueError("absolute E2E output must be inside a temporary directory")
    elif not _within(target, root):
        raise ValueError("relative E2E output escapes the project root")
    if target == root:
        raise ValueError("E2E output cannot be the project root")
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"E2E output path already exists; refusing to overwrite: {target}")
    return target, describe_output_path(target, project_root=root)


def require_new_report_path(path: str | Path) -> Path:
    supplied = Path(path).expanduser()
    if supplied.exists() or supplied.is_symlink():
        raise FileExistsError(f"report path already exists; refusing to overwrite: {supplied}")
    target = supplied.resolve()
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"report path already exists; refusing to overwrite: {target}")
    return target
