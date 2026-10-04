"""MCP stdio server exposing read-only Canvas tools to OpenClaw.

The Canvas token is loaded here from Canvas_sync/.env (or CANVAS_ENV_FILE) and
never leaves this process; the model only ever sees tool results.
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .client import CanvasClient, CanvasError
from .tools import CanvasTools

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
# httpx logs full URLs at INFO (incl. one-time file download verifiers); keep them out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True)

mcp = MCPServer(
    "canvas_lms",
    instructions=(
        "Read-only access to the student's MIT Canvas: courses, deadlines, missing work, assignment "
        "instructions, announcements, grades and course files. All times are Boston local time. "
        "These tools cannot submit, post or change anything."
    ),
)


@cache
def _tools() -> CanvasTools:
    load_dotenv(os.environ.get("CANVAS_ENV_FILE", DEFAULT_ENV_FILE))
    base = os.environ.get("CANVAS_BASE_URL", "https://canvas.mit.edu")
    return CanvasTools(CanvasClient(base, os.environ.get("CANVAS_TOKEN", "")))


def _run(name: str, **kwargs: Any) -> str:
    try:
        result = getattr(_tools(), name)(**kwargs)
    except CanvasError as exc:
        if "CANVAS_TOKEN" in str(exc):
            _tools.cache_clear()  # pick up the token once .env is filled in, without a restart
        return f"Canvas error: {exc}"
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=1)


@mcp.tool(annotations=READ_ONLY)
def list_courses() -> str:
    """List the student's active Canvas courses with their course_id, code (e.g. 18.06) and name.
    Use this to find a course_id before calling other tools for one course."""
    return _run("list_courses")


@mcp.tool(annotations=READ_ONLY)
def upcoming(days: int = 7, course_id: int | None = None, only_unsubmitted: bool = False) -> str:
    """What's due soon: assignments, quizzes, discussions and events in the next `days` days,
    sorted by due date, with whether each assignment is already submitted.
    Use for "what's due this week/tomorrow?". Set only_unsubmitted=true to hide finished work."""
    return _run("upcoming", days=days, course_id=course_id, only_unsubmitted=only_unsubmitted)


@mcp.tool(annotations=READ_ONLY)
def missing() -> str:
    """Assignments past their due date that the student has NOT submitted. Use for "what did I miss/forget?"."""
    return _run("missing")


@mcp.tool(annotations=READ_ONLY)
def assignment_details(course_id: int, assignment_id: int) -> str:
    """Full details of one assignment: instructions, due/lock dates, points, rubric and submission status.
    Get course_id and assignment_id from `upcoming` or `missing` first."""
    return _run("assignment_details", course_id=course_id, assignment_id=assignment_id)


@mcp.tool(annotations=READ_ONLY)
def announcements(days: int = 14, course_id: int | None = None) -> str:
    """Recent course announcements from professors/TAs (last `days` days), across all courses or one course."""
    return _run("announcements", days=days, course_id=course_id)


@mcp.tool(annotations=READ_ONLY)
def grades(course_id: int | None = None) -> str:
    """Grades. Without course_id: current overall score per course. With course_id: score for each assignment."""
    return _run("grades", course_id=course_id)


@mcp.tool(annotations=READ_ONLY)
def list_files(course_id: int, search: str | None = None) -> str:
    """List files (lecture slides, notes, psets) in a course, newest first. Optional `search` filters by name."""
    return _run("list_files", course_id=course_id, search=search)


@mcp.tool(annotations=READ_ONLY)
def read_file(file_id: int, page: int = 1) -> str:
    """Read the text of a course file (PDF or text) by file_id from `list_files`.
    Long files come in parts; call again with page=2, 3, ... to continue."""
    return _run("read_file", file_id=file_id, page=page)


def main() -> None:
    mcp.run("stdio")


if __name__ == "__main__":
    main()
