"""Sandboxed filesystem tools exposed to agents."""

from __future__ import annotations

from pathlib import Path

MAX_READ_CHARS = 40_000


class FilesystemSandbox:
    """Read/write restricted to a list of allowed root directories."""

    def __init__(self, allowed_roots: list[Path]) -> None:
        self.allowed_roots = [Path(p).resolve() for p in allowed_roots]

    def _resolve(self, raw_path: str) -> Path:
        p = Path(raw_path).resolve()
        for root in self.allowed_roots:
            try:
                p.relative_to(root)
                return p
            except ValueError:
                continue
        raise PermissionError(
            f"path {p} is outside allowed roots: {[str(r) for r in self.allowed_roots]}"
        )

    def read_file(self, path: str, max_chars: int = MAX_READ_CHARS) -> dict:
        try:
            target = self._resolve(path)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        if not target.exists():
            return {"ok": False, "error": f"file not found: {target}"}
        if not target.is_file():
            return {"ok": False, "error": f"not a file: {target}"}
        text = target.read_text(encoding="utf-8")
        return {
            "ok": True,
            "path": str(target),
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
            "total_chars": len(text),
        }

    def write_file(self, path: str, content: str) -> dict:
        try:
            target = self._resolve(path)
        except PermissionError as exc:
            return {"ok": False, "error": str(exc)}
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": str(target), "bytes_written": len(content)}


FILESYSTEM_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read a UTF-8 text file from the sandboxed project directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Absolute or relative path."},
                "max_chars": {"type": "integer", "default": MAX_READ_CHARS},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": (
            "Write (or overwrite) a UTF-8 text file inside the sandboxed project directories. "
            "Parent directories are created automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    },
]


def dispatch_filesystem_tool(sandbox: FilesystemSandbox, name: str, args: dict) -> dict:
    if name == "read_file":
        return sandbox.read_file(args["path"], args.get("max_chars", MAX_READ_CHARS))
    if name == "write_file":
        return sandbox.write_file(args["path"], args["content"])
    return {"ok": False, "error": f"unknown filesystem tool: {name}"}
