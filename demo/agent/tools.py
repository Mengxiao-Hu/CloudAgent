"""Tool protocol and the four CloudAgent tools.

Per SPECS.md § 2.2: read, write, shell (read-only allow-list), finish.

Tools run *inside* the injected Sandbox. They never import Docker; they only
call sandbox.read / sandbox.write / sandbox.exec. The Sandbox is owned by
backend-developer (SPECS.md § 3, § 4).

Each tool exposes:
  - name: str
  - description: str
  - schema: dict        (JSON schema of input args)
  - run(args, sandbox) -> {"success": bool, "output": str, "error": str|None,
                           and optionally "is_final": bool}
"""

from __future__ import annotations

import re
import shlex
from typing import Protocol, runtime_checkable

# Directory the agent is permitted to write to.
WRITE_ROOT = "/workspace/out/"


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    schema: dict

    def run(self, args: dict, sandbox) -> dict:  # pragma: no cover - protocol
        ...


def _ok(output: str = "", **extra) -> dict:
    result = {"success": True, "output": output, "error": None}
    result.update(extra)
    return result


def _err(error: str, **extra) -> dict:
    result = {"success": False, "output": "", "error": error}
    result.update(extra)
    return result


# --------------------------------------------------------------------------- #
# a. ReadFile
# --------------------------------------------------------------------------- #
class ReadFileTool:
    name = "read"
    description = (
        "Read a file from the workspace, optionally a 1-indexed inclusive line "
        "range. Use this to inspect source files (e.g. /workspace/repo/...)."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "File path (relative to /workspace or absolute).",
            },
            "line_start": {
                "type": "integer",
                "description": "Start line, 1-indexed (optional).",
            },
            "line_end": {
                "type": "integer",
                "description": "End line, inclusive (optional).",
            },
        },
        "required": ["path"],
    }

    def run(self, args: dict, sandbox) -> dict:
        path = args.get("path")
        if not path:
            return _err("Missing required argument 'path'.")

        line_start = args.get("line_start")
        line_end = args.get("line_end")
        line_range = None
        if line_start is not None and line_end is not None:
            try:
                line_range = (int(line_start), int(line_end))
            except (TypeError, ValueError):
                return _err("line_start and line_end must be integers.")

        try:
            content = sandbox.read(path, line_range)
            return _ok(content)
        except FileNotFoundError as exc:
            return _err(f"File not found: {exc}")
        except PermissionError as exc:
            return _err(f"Permission denied: {exc}")
        except Exception as exc:
            return _err(f"Read failed: {exc}")


# --------------------------------------------------------------------------- #
# b. WriteFile
# --------------------------------------------------------------------------- #
class WriteFileTool:
    name = "write"
    description = (
        "Write a markdown report or analysis output. Writes are restricted to "
        f"{WRITE_ROOT} (e.g. {WRITE_ROOT}report.md). Source files cannot be modified."
    )
    schema = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": f"Destination path under {WRITE_ROOT}.",
            },
            "content": {
                "type": "string",
                "description": "File content (markdown report).",
            },
        },
        "required": ["path", "content"],
    }

    @staticmethod
    def _normalize(path: str) -> str:
        # Treat bare/relative paths as living under /workspace, matching the
        # Sandbox read/write convention in SPECS.md § 4.2.
        if not path.startswith("/workspace"):
            path = "/workspace/" + path.lstrip("/")
        return path

    def run(self, args: dict, sandbox) -> dict:
        path = args.get("path")
        content = args.get("content")
        if not path:
            return _err("Missing required argument 'path'.")
        if content is None:
            return _err("Missing required argument 'content'.")

        full_path = self._normalize(path)
        if not full_path.startswith(WRITE_ROOT):
            return _err(
                f"Writes are restricted to {WRITE_ROOT}. Cannot modify source "
                f"files or write to '{full_path}'."
            )

        try:
            result = sandbox.write(full_path, content)
        except Exception as exc:
            return _err(f"Write failed: {exc}")

        if isinstance(result, dict) and not result.get("success", True):
            return _err(result.get("error") or "Write failed.")
        return _ok(f"Wrote {len(content)} bytes to {full_path}.")


# --------------------------------------------------------------------------- #
# c. Shell (read-only, allow-list)
# --------------------------------------------------------------------------- #
class ShellTool:
    name = "shell"
    description = (
        "Run a read-only analysis shell command (grep, rg, find, wc, cat, head, "
        "ls, git log, git status). Installs, builds, network calls, and remote "
        "git writes are rejected."
    )
    schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command (e.g. \"rg 'TODO|FIXME' /workspace/repo\").",
            }
        },
        "required": ["command"],
    }

    # Patterns that are always rejected, with a clear reason.
    DENY = [
        (re.compile(r"\bpip\b.*\binstall\b"),
         "Dependency installation not supported. Sandbox provides required tools."),
        (re.compile(r"\bpip3\b.*\binstall\b"),
         "Dependency installation not supported. Sandbox provides required tools."),
        (re.compile(r"\bnpm\b.*\b(install|i|ci|add)\b"),
         "Dependency installation not supported. Sandbox provides required tools."),
        (re.compile(r"\b(yarn|pnpm)\b"),
         "Dependency installation not supported. Sandbox provides required tools."),
        (re.compile(r"\bapt(-get)?\b.*\binstall\b"),
         "Dependency installation not supported. Sandbox provides required tools."),
        (re.compile(r"\bgit\b.*\bpush\b"),
         "Remote write operations not supported in this context."),
        (re.compile(r"\bgh\b\s+pr\b"),
         "Remote write operations not supported in this context."),
        (re.compile(r"\bgh\b\s+(repo|release|issue)\b"),
         "Remote write operations not supported in this context."),
        (re.compile(r"\bcargo\b.*\b(build|install|run|test)\b"),
         "Build operations not supported in this context."),
        (re.compile(r"\bdocker\b.*\bbuild\b"),
         "Build operations not supported in this context."),
        (re.compile(r"\b(make|cmake|ninja|bazel)\b"),
         "Build operations not supported in this context."),
        (re.compile(r"\b(curl|wget)\b"),
         "Network operations not supported in this context."),
    ]

    # First token must be one of these (read-only utilities). git is allowed but
    # further restricted to read-only subcommands below.
    ALLOWED_HEADS = {
        "grep", "rg", "find", "wc", "cat", "head", "tail", "ls", "tree",
        "sort", "uniq", "awk", "sed", "cut", "echo", "git", "file", "stat",
        "basename", "dirname", "pwd",
    }
    ALLOWED_GIT_SUB = {"log", "status", "show", "diff", "branch", "blame", "ls-files"}

    # Shell control operators that separate one command from the next.
    _OPERATORS = {"|", "&&", "||", ";", "&"}

    @classmethod
    def _split_segments(cls, cmd: str) -> list[list[str]]:
        """Tokenize respecting quotes, then split into command segments on
        shell control operators. A '|' inside a quoted string (e.g. the regex
        in rg 'TODO|FIXME') is NOT treated as a pipe.
        """
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            # Unbalanced quotes etc. — fall back to a permissive split so the
            # caller can still allow-list the first word.
            tokens = cmd.split()

        segments: list[list[str]] = []
        current: list[str] = []
        for tok in tokens:
            if tok in cls._OPERATORS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(tok)
        if current:
            segments.append(current)
        return segments

    @classmethod
    def check(cls, command: str) -> str | None:
        """Return a rejection reason if the command is not allowed, else None."""
        cmd = command.strip()
        if not cmd:
            return "Empty command."

        for pattern, reason in cls.DENY:
            if pattern.search(cmd):
                return reason

        segments = cls._split_segments(cmd)
        if not segments:
            return "Empty command."

        for tokens in segments:
            # Strip leading env-var assignments like FOO=bar grep ...
            idx = 0
            while idx < len(tokens) and "=" in tokens[idx] and not tokens[idx].startswith("/"):
                idx += 1
            if idx >= len(tokens):
                continue
            head = tokens[idx]
            if head not in cls.ALLOWED_HEADS:
                return (
                    f"Command '{head}' is not in the read-only allow-list "
                    "(grep, rg, find, wc, cat, head, ls, git log/status, ...)."
                )
            if head == "git":
                sub = tokens[idx + 1] if idx + 1 < len(tokens) else ""
                if sub not in cls.ALLOWED_GIT_SUB:
                    return (
                        f"git subcommand '{sub}' not allowed. Only read-only git "
                        "(log, status, show, diff, branch, blame, ls-files)."
                    )
        return None

    def run(self, args: dict, sandbox) -> dict:
        command = args.get("command")
        if not command:
            return _err("Missing required argument 'command'.")

        reason = self.check(command)
        if reason:
            return _err(reason)

        try:
            result = sandbox.exec(command, timeout=60)
        except TimeoutError:
            return _err("Command exceeded time limit.")
        except Exception as exc:
            return _err(f"Command failed: {exc}")

        returncode = result.get("returncode", 0)
        stdout = result.get("stdout", "")
        stderr = result.get("stderr", "")
        if returncode != 0:
            return _err(
                stderr or f"Command exited with code {returncode}.",
                output=stdout,
            )
        return _ok(stdout)


# --------------------------------------------------------------------------- #
# d. Finish
# --------------------------------------------------------------------------- #
class FinishTool:
    name = "finish"
    description = (
        "Signal that the task is complete and return the final markdown report "
        "to the user. Call this once your analysis report is written."
    )
    schema = {
        "type": "object",
        "properties": {
            "output": {
                "type": "string",
                "description": "Final markdown report or summary.",
            }
        },
        "required": ["output"],
    }

    def run(self, args: dict, sandbox) -> dict:
        output = args.get("output", "")
        return {"success": True, "output": output, "error": None, "is_final": True}


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #
class ToolRegistry:
    """Holds tools and exposes schemas / lookup / allow-list checks."""

    def __init__(self, tools: list[Tool] | None = None):
        if tools is None:
            tools = [ReadFileTool(), WriteFileTool(), ShellTool(), FinishTool()]
        self._tools: dict[str, Tool] = {t.name: t for t in tools}

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def is_allowed(self, name: str) -> bool:
        return name in self._tools

    def schemas(self) -> list[dict]:
        """OpenAI function-calling format, consumable by ChatOpenAI.bind_tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.schema,
                },
            }
            for t in self._tools.values()
        ]

    def names(self) -> list[str]:
        return list(self._tools.keys())


def default_registry() -> ToolRegistry:
    return ToolRegistry()
