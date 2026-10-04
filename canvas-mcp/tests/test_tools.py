from datetime import datetime, timezone

import pytest

from canvas_mcp.client import CanvasError
from canvas_mcp.tools import CanvasTools

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)  # Tue Oct 6, 8:00 AM Boston

COURSES = [
    {"id": 1, "name": "Linear Algebra", "course_code": "18.06"},
    {"id": 2, "name": "Intro to Algorithms", "course_code": "6.1210"},
    {"id": 3, "access_restricted_by_date": True},
]


class FakeClient:
    def __init__(self, responses=None, files=None):
        self.responses = responses or {}
        self.files = files or {}
        self.calls = []

    def _lookup(self, path, params):
        self.calls.append((path, list(params or [])))
        value = self.responses[path]
        if isinstance(value, Exception):
            raise value
        return value

    def get(self, path, params=None):
        return self._lookup(path, params)

    def get_all(self, path, params=None):
        return self._lookup(path, params)

    def download(self, file_id):
        return self.files[file_id]


def tools_with(responses, files=None):
    responses = {"/courses": COURSES, **responses}
    client = FakeClient(responses, files)
    return CanvasTools(client, now=lambda: NOW), client


def test_list_courses_skips_restricted():
    t, _ = tools_with({})
    assert t.list_courses() == [
        {"course_id": 1, "code": "18.06", "name": "Linear Algebra"},
        {"course_id": 2, "code": "6.1210", "name": "Intro to Algorithms"},
    ]


PLANNER = [
    {
        "plannable_type": "assignment", "plannable_id": 11, "course_id": 2, "context_name": "Intro to Algorithms",
        "plannable_date": "2026-10-08T03:59:00Z", "html_url": "/courses/2/assignments/11",
        "plannable": {"title": "PSET 3", "points_possible": 100},
        "submissions": {"submitted": False, "missing": False, "late": False, "graded": False},
    },
    {
        "plannable_type": "assignment", "plannable_id": 10, "course_id": 1, "context_name": "Linear Algebra",
        "plannable_date": "2026-10-07T03:59:00Z", "html_url": "/courses/1/assignments/10",
        "plannable": {"title": "HW 4"},
        "submissions": {"submitted": True, "missing": False, "late": False, "graded": False},
    },
    {
        "plannable_type": "calendar_event", "plannable_id": 5, "course_id": 1, "context_name": "Linear Algebra",
        "plannable_date": "2026-10-09T14:00:00Z", "plannable": {"title": "Exam review"}, "submissions": False,
    },
]


def test_upcoming_sorted_with_local_times_and_status():
    t, client = tools_with({"/planner/items": PLANNER})
    items = t.upcoming(days=7)
    assert [i["title"] for i in items] == ["HW 4", "PSET 3", "Exam review"]
    assert items[0]["due"] == "Tue Oct 6, 11:59 PM"
    assert items[0]["submitted"] is True
    assert items[1]["submitted"] is False
    assert items[1]["course"] == "Intro to Algorithms"
    assert items[1]["assignment_id"] == 11
    assert "submitted" not in items[2]
    path, params = client.calls[-1]
    assert ("start_date", "2026-10-06T12:00:00Z") in params
    assert ("end_date", "2026-10-13T12:00:00Z") in params


def test_upcoming_only_unsubmitted_and_course_filter():
    t, client = tools_with({"/planner/items": PLANNER})
    items = t.upcoming(days=7, only_unsubmitted=True, course_id=2)
    assert [i["title"] for i in items] == ["PSET 3"]
    assert ("context_codes[]", "course_2") in client.calls[-1][1]


def test_upcoming_empty_message():
    t, _ = tools_with({"/planner/items": []})
    assert t.upcoming(days=2) == "Nothing due in the next 2 days."


def test_missing_adds_course_names():
    t, _ = tools_with({"/users/self/missing_submissions": [
        {"id": 9, "name": "Lab 1", "course_id": 2, "due_at": "2026-10-01T03:59:00Z", "points_possible": 10,
         "html_url": "https://canvas/x"},
    ]})
    assert t.missing() == [{"title": "Lab 1", "course": "6.1210 Intro to Algorithms", "course_id": 2,
                            "assignment_id": 9, "due": "Wed Sep 30, 11:59 PM", "points": 10,
                            "url": "https://canvas/x"}]


def test_missing_none():
    t, _ = tools_with({"/users/self/missing_submissions": []})
    assert t.missing() == "No missing assignments."


def test_assignment_details():
    t, _ = tools_with({"/courses/2/assignments/11": {
        "name": "PSET 3", "due_at": "2026-10-08T03:59:00Z", "points_possible": 100,
        "description": "<p>Solve <b>all</b> problems.</p>", "submission_types": ["online_upload"],
        "rubric": [{"description": "Correctness", "points": 80, "long_description": "Proofs"}],
        "submission": {"workflow_state": "unsubmitted", "submitted_at": None, "score": None, "late": False},
        "html_url": "https://canvas/a/11",
    }})
    d = t.assignment_details(2, 11)
    assert d["title"] == "PSET 3"
    assert d["due"] == "Wed Oct 7, 11:59 PM"
    assert d["instructions"] == "Solve all problems."
    assert d["rubric"] == ["Correctness (80 pts): Proofs"]
    assert d["status"] == "unsubmitted"


def test_announcements_all_courses_trimmed():
    long = "<p>" + "x" * 3000 + "</p>"
    t, client = tools_with({"/announcements": [
        {"title": "Office hours moved", "message": long, "posted_at": "2026-10-05T18:00:00Z",
         "context_code": "course_1", "author": {"display_name": "Prof. S"}, "html_url": "u"},
    ]})
    [a] = t.announcements(days=14)
    assert a["course"] == "18.06 Linear Algebra"
    assert a["posted"] == "Mon Oct 5, 2:00 PM"
    assert a["author"] == "Prof. S"
    assert len(a["message"]) < 1600 and a["message"].endswith("…")
    params = client.calls[-1][1]
    assert ("context_codes[]", "course_1") in params and ("context_codes[]", "course_2") in params


def test_grades_overview():
    t, _ = tools_with({})
    t._client.responses["/courses"] = [
        {**COURSES[0], "enrollments": [{"type": "student", "computed_current_score": 91.5,
                                        "computed_current_grade": "A-"}]},
        {**COURSES[1], "enrollments": [{"type": "student", "computed_current_score": None}]},
    ]
    assert t.grades() == [
        {"course_id": 1, "course": "18.06 Linear Algebra", "current_score": 91.5, "current_grade": "A-"},
        {"course_id": 2, "course": "6.1210 Intro to Algorithms", "current_score": None, "current_grade": None},
    ]


def test_grades_for_course():
    t, _ = tools_with({"/courses/1/students/submissions": [
        {"assignment": {"name": "HW 1", "points_possible": 10}, "score": 9, "workflow_state": "graded",
         "late": False, "missing": False},
        {"assignment": {"name": "HW 2", "points_possible": 10}, "score": None, "workflow_state": "unsubmitted",
         "late": False, "missing": True},
    ]})
    assert t.grades(course_id=1) == [
        {"assignment": "HW 1", "score": "9/10", "status": "graded"},
        {"assignment": "HW 2", "score": "-/10", "status": "missing"},
    ]


def test_list_files_and_forbidden_message():
    t, _ = tools_with({"/courses/1/files": [
        {"id": 7, "display_name": "lec5.pdf", "content-type": "application/pdf", "size": 2_400_000,
         "updated_at": "2026-10-01T15:00:00Z"},
    ]})
    assert t.list_files(1) == [{"file_id": 7, "name": "lec5.pdf", "type": "application/pdf",
                                "size": "2.3 MB", "updated": "Thu Oct 1, 11:00 AM"}]
    t2, _ = tools_with({"/courses/2/files": CanvasError("no permission to view this in Canvas")})
    assert "course website" in t2.list_files(2)


def test_read_file_chunks():
    t, _ = tools_with({}, files={7: ({"display_name": "notes.txt", "content-type": "text/plain"}, b"y" * 9000)})
    out = t.read_file(7)
    assert out.startswith("notes.txt\n\n")
    assert "[part 1 of 2" in out
    assert "[part 2 of 2]" in t.read_file(7, page=2)


def test_read_file_unsupported():
    t, _ = tools_with({}, files={8: ({"display_name": "a.png", "content-type": "image/png"}, b"\x89PNG")})
    assert "can't read" in t.read_file(8)


def test_canvas_errors_become_messages():
    t, _ = tools_with({"/users/self/missing_submissions": CanvasError("Canvas token invalid or expired")})
    with pytest.raises(CanvasError):
        t.missing()


def test_missing_skips_items_not_yet_due():
    t, _ = tools_with({"/users/self/missing_submissions": [
        {"id": 9, "name": "Future proposal", "course_id": 2, "due_at": "2026-11-08T04:59:00Z"},
    ]})
    assert t.missing() == "No missing assignments."


def test_course_label_avoids_repeating_code():
    t, _ = tools_with({})
    t._client.responses["/courses"] = [
        {"id": 5, "name": "15.774 AI for Operations", "course_code": "15.774_FA26"},
    ]
    assert t._course_labels() == {5: "15.774 AI for Operations"}


def test_dates_from_another_year_show_the_year():
    t, _ = tools_with({"/users/self/missing_submissions": [
        {"id": 9, "name": "Old proposal", "course_id": 2, "due_at": "2025-11-08T04:59:59Z"},
    ]})
    assert t.missing()[0]["due"] == "Fri Nov 7, 2025, 11:59 PM"
