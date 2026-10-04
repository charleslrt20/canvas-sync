"""The Canvas tools the assistant can call.

Each tool returns compact, model-friendly data (only the fields that matter,
times already in Boston local time) so a small local model stays in context.
Tools raise CanvasError on failure; the MCP server turns that into a message.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .client import CanvasClient, CanvasError
from .textutil import chunk, extract_text, html_to_text

LOCAL_TZ = ZoneInfo("America/New_York")
MAX_MESSAGE_CHARS = 1500


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _local(ts: str | None, now: datetime) -> str | None:
    """'Tue Oct 6, 11:59 PM', with the year added when it isn't the current one."""
    dt = _parse(ts)
    if not dt:
        return None
    dt = dt.astimezone(LOCAL_TZ)
    fmt = "%a %b %-d, %-I:%M %p" if dt.year == now.astimezone(LOCAL_TZ).year else "%a %b %-d, %Y, %-I:%M %p"
    return dt.strftime(fmt)


def _utc_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _label(course: dict) -> str:
    """'15.774 AI for Operations' rather than '15.774_FA26 15.774 AI for Operations'."""
    code, name = course.get("course_code") or "", course.get("name") or ""
    return name if not code or code.split("_")[0] in name else f"{code} {name}"


def _size(n: int | None) -> str:
    n = n or 0
    return f"{n / 1_048_576:.1f} MB" if n >= 1_048_576 else f"{max(1, n // 1024)} KB"


class CanvasTools:
    def __init__(self, client: CanvasClient, now: Callable[[], datetime] | None = None) -> None:
        self._client = client
        self._now = now or (lambda: datetime.now(timezone.utc))

    # -- helpers ---------------------------------------------------------------

    def _fmt(self, ts: str | None) -> str | None:
        return _local(ts, self._now())

    def _courses(self) -> list[dict]:
        return [
            c for c in self._client.get_all("/courses", [("enrollment_state", "active"), ("per_page", "50")])
            if not c.get("access_restricted_by_date") and c.get("name")
        ]

    def _course_labels(self) -> dict[int, str]:
        return {c["id"]: _label(c) for c in self._courses()}

    # -- tools -----------------------------------------------------------------

    def list_courses(self) -> list[dict]:
        return [{"course_id": c["id"], "code": c.get("course_code"), "name": c["name"]} for c in self._courses()]

    def upcoming(self, days: int = 7, course_id: int | None = None, only_unsubmitted: bool = False) -> Any:
        now = self._now()
        params = [
            ("start_date", _utc_iso(now)),
            ("end_date", _utc_iso(now + timedelta(days=days))),
            ("per_page", "100"),
        ]
        if course_id:
            params.append(("context_codes[]", f"course_{course_id}"))
        items = []
        for it in self._client.get_all("/planner/items", params):
            subs = it.get("submissions")
            entry = {
                "title": (it.get("plannable") or {}).get("title"),
                "type": it.get("plannable_type"),
                "course": it.get("context_name"),
                "course_id": it.get("course_id"),
                "due": self._fmt(it.get("plannable_date")),
                "_sort": it.get("plannable_date") or "",
            }
            if it.get("plannable_type") == "assignment":
                entry["assignment_id"] = it.get("plannable_id")
            if isinstance(subs, dict):
                entry["submitted"] = bool(subs.get("submitted"))
                if subs.get("missing"):
                    entry["missing"] = True
                if only_unsubmitted and entry["submitted"]:
                    continue
            elif only_unsubmitted:
                continue
            items.append(entry)
        items.sort(key=lambda e: e.pop("_sort"))
        return items or f"Nothing due in the next {days} days."

    def missing(self) -> Any:
        now = self._now()
        rows = [
            a for a in self._client.get_all("/users/self/missing_submissions", [("per_page", "100")])
            if (due := _parse(a.get("due_at"))) is None or due <= now  # Canvas sometimes includes not-yet-due work
        ]
        if not rows:
            return "No missing assignments."
        labels = self._course_labels()
        return [
            {
                "title": a.get("name"),
                "course": labels.get(a.get("course_id"), str(a.get("course_id"))),
                "course_id": a.get("course_id"),
                "assignment_id": a.get("id"),
                "due": self._fmt(a.get("due_at")),
                "points": a.get("points_possible"),
                "url": a.get("html_url"),
            }
            for a in rows
        ]

    def assignment_details(self, course_id: int, assignment_id: int) -> dict:
        a = self._client.get(
            f"/courses/{int(course_id)}/assignments/{int(assignment_id)}", [("include[]", "submission")]
        )
        sub = a.get("submission") or {}
        rubric = [
            f"{r.get('description')} ({r.get('points')} pts)" + (f": {r['long_description']}" if r.get("long_description") else "")
            for r in a.get("rubric") or []
        ]
        return {
            "title": a.get("name"),
            "due": self._fmt(a.get("due_at")),
            "locks": self._fmt(a.get("lock_at")),
            "points": a.get("points_possible"),
            "submission_types": a.get("submission_types"),
            "instructions": html_to_text(a.get("description")),
            "rubric": rubric,
            "status": sub.get("workflow_state"),
            "submitted_at": self._fmt(sub.get("submitted_at")),
            "score": sub.get("score"),
            "late": sub.get("late"),
            "url": a.get("html_url"),
        }

    def announcements(self, days: int = 14, course_id: int | None = None) -> Any:
        labels = self._course_labels()
        ids = [int(course_id)] if course_id else list(labels)
        if not ids:
            return "No active courses."
        now = self._now()
        params = [("start_date", _utc_iso(now - timedelta(days=days))), ("end_date", _utc_iso(now)), ("per_page", "50")]
        params += [("context_codes[]", f"course_{i}") for i in ids]
        out = []
        for a in self._client.get_all("/announcements", params):
            text = html_to_text(a.get("message"))
            if len(text) > MAX_MESSAGE_CHARS:
                text = text[:MAX_MESSAGE_CHARS].rstrip() + "…"
            cid = int(str(a.get("context_code", "course_0")).removeprefix("course_"))
            out.append({
                "title": a.get("title"),
                "course": labels.get(cid, str(cid)),
                "posted": self._fmt(a.get("posted_at")),
                "author": (a.get("author") or {}).get("display_name"),
                "message": text,
                "url": a.get("html_url"),
            })
        return out or f"No announcements in the last {days} days."

    def grades(self, course_id: int | None = None) -> Any:
        if course_id is None:
            courses = self._client.get_all(
                "/courses", [("enrollment_state", "active"), ("include[]", "total_scores"), ("per_page", "50")]
            )
            out = []
            for c in courses:
                if c.get("access_restricted_by_date") or not c.get("name"):
                    continue
                enr = next((e for e in c.get("enrollments") or [] if e.get("type") == "student"), {})
                out.append({
                    "course_id": c["id"],
                    "course": _label(c),
                    "current_score": enr.get("computed_current_score"),
                    "current_grade": enr.get("computed_current_grade"),
                })
            return out
        subs = self._client.get_all(
            f"/courses/{int(course_id)}/students/submissions",
            [("student_ids[]", "self"), ("include[]", "assignment"), ("per_page", "100")],
        )
        out = []
        for s in subs:
            a = s.get("assignment") or {}
            score = "-" if s.get("score") is None else f"{s['score']:g}"
            status = "missing" if s.get("missing") else ("late" if s.get("late") else s.get("workflow_state"))
            out.append({"assignment": a.get("name"), "score": f"{score}/{a.get('points_possible', 0):g}", "status": status})
        return out or "No graded work yet in this course."

    def list_files(self, course_id: int, search: str | None = None) -> Any:
        params = [("sort", "updated_at"), ("order", "desc"), ("per_page", "50")]
        if search:
            params.append(("search_term", search))
        try:
            files = self._client.get_all(f"/courses/{int(course_id)}/files", params)
        except CanvasError as exc:
            if "no permission" in str(exc) or "not found" in str(exc):
                return ("This course doesn't share files in Canvas. Its materials are probably on the "
                        "course website, which this assistant can't read.")
            raise
        return [
            {"file_id": f["id"], "name": f.get("display_name"), "type": f.get("content-type"),
             "size": _size(f.get("size")), "updated": self._fmt(f.get("updated_at"))}
            for f in files
        ] or "No files found."

    def read_file(self, file_id: int, page: int = 1) -> str:
        meta, data = self._client.download(int(file_id))
        name = meta.get("display_name") or meta.get("filename") or f"file {file_id}"
        try:
            text = extract_text(data, meta.get("content-type"), name)
        except ValueError as exc:
            return str(exc)
        if not text.strip():
            return f"{name} has no extractable text (it may be scanned images)."
        return f"{name}\n\n{chunk(text, page=page)}"
