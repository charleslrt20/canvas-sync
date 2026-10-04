"""Live read-only smoke test: run every Canvas tool once against your real account.

Usage (from canvas-mcp/):  .venv/bin/python scripts/smoke.py
Prints a short summary per tool. Never prints the token.
"""

import json
import os
import sys

from dotenv import load_dotenv

from canvas_mcp.client import CanvasClient, CanvasError
from canvas_mcp.server import DEFAULT_ENV_FILE
from canvas_mcp.tools import CanvasTools


def show(name, result):
    if isinstance(result, list):
        print(f"✅ {name}: {len(result)} item(s)")
        if result:
            print("   first:", json.dumps(result[0], ensure_ascii=False)[:300])
    else:
        print(f"✅ {name}: {str(result)[:300]}")
    return result


def main() -> int:
    load_dotenv(os.environ.get("CANVAS_ENV_FILE", DEFAULT_ENV_FILE))
    try:
        tools = CanvasTools(CanvasClient(os.environ.get("CANVAS_BASE_URL", "https://canvas.mit.edu"),
                                         os.environ.get("CANVAS_TOKEN", "")))
        courses = show("list_courses", tools.list_courses())
        upcoming = show("upcoming(14 days)", tools.upcoming(days=14))
        show("missing", tools.missing())
        show("announcements(14 days)", tools.announcements(days=14))
        show("grades", tools.grades())
        if courses:
            cid = courses[0]["course_id"]
            show(f"grades(course {cid})", tools.grades(course_id=cid))
        assignment = next((u for u in upcoming if isinstance(u, dict) and u.get("assignment_id")), None) \
            if isinstance(upcoming, list) else None
        if assignment:
            d = show("assignment_details", tools.assignment_details(assignment["course_id"], assignment["assignment_id"]))
            print("   instructions chars:", len(d.get("instructions") or ""))
        else:
            print("⏭️  assignment_details: no upcoming assignment to try")
        pdf = None
        for c in courses:
            files = tools.list_files(c["course_id"])
            if isinstance(files, list) and files:
                show(f"list_files({c['code']})", files)
                pdf = next((f for f in files if "pdf" in (f["type"] or "")), files[0])
                break
            print(f"   list_files({c['code']}): {str(files)[:120]}")
        if pdf:
            print(f"✅ read_file({pdf['name']}):", tools.read_file(pdf["file_id"])[:300].replace("\n", " "), "…")
        else:
            print("⏭️  read_file: no course shares files in Canvas")
    except CanvasError as exc:
        print(f"❌ Canvas error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
