"""Document access is scoped to the caller's workspace, never the installation."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
from .errors import AssemblyError

ROOT = Path(__file__).absolute().parent.parent
_WORKSPACE = ContextVar("final_assembly_workspace", default=None)
MAX_INPUT = 16 * 1024 * 1024


def workspace_root():
    return _WORKSPACE.get() or Path.cwd().resolve()


def _reject_reparse(path):
    for part in [path, *path.parents]:
        if part.exists() or part.is_symlink():
            stat = part.lstat()
            if part.is_symlink() or getattr(stat, "st_file_attributes", 0) & 0x400:
                raise AssemblyError("REPARSE_POINT", "Symlink/junction/reparse paths are not allowed", str(part))


@contextmanager
def workspace(value):
    root = Path(value).absolute()
    if not root.is_dir():
        raise AssemblyError("WORKSPACE_MISSING", "Workspace must be an existing directory", str(root))
    # Inspect the supplied path before normalizing: `junction/..` must not
    # erase a forbidden reparse point. Use the same lexical absolute form
    # as checked_path so ordinary `parent/../materials` stays inside itself.
    _reject_reparse(root)
    root = Path(os.path.abspath(root))
    token = _WORKSPACE.set(root)
    try:
        checked_path(root)
        yield root
    finally:
        _WORKSPACE.reset(token)


def checked_path(value, base=None):
    path = Path(value)
    if not path.is_absolute():
        path = (base or workspace_root()) / path
    path = Path(os.path.abspath(path))
    try:
        path.relative_to(workspace_root())
    except ValueError:
        raise AssemblyError("PATH_OUTSIDE_WORKSPACE", "Path must stay inside --workspace; choose a common parent for inputs and outputs", str(path))
    # Reject all reparse points, including junctions leading back into the project.
    _reject_reparse(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace_root().resolve()):
        raise AssemblyError("PATH_OUTSIDE_WORKSPACE", "Resolved path leaves the workspace", str(resolved))
    return resolved


def read_bytes(path):
    path = checked_path(path)
    if not path.is_file():
        raise AssemblyError("MISSING_FILE", "Required file does not exist", str(path))
    if path.stat().st_size > MAX_INPUT:
        raise AssemblyError("INPUT_TOO_LARGE", "Input exceeds 16 MiB", str(path))
    return path.read_bytes()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssemblyError("DUPLICATE_JSON_KEY", f"Duplicate JSON field: {key}")
        result[key] = value
    return result


def parse_json(raw, location=None):
    try:
        def invalid_constant(value):
            raise ValueError(f"Nonstandard JSON number: {value}")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    except (ValueError, UnicodeError) as exc:
        raise AssemblyError("INVALID_JSON", str(exc), str(location)) from exc


def read_json(path):
    return parse_json(read_bytes(path), path)


def write_json(path, value):
    path = checked_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Existing evidence is never silently replaced.
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
