"""Regression tests for HIGH-1: scoring authorization.

A judge may score only a project they are assigned to, whose track is
one of their declared tracks, and that was not submitted by their own
team. Scoring must never create an assignment after the fact.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import db as dbmod  # noqa: E402
from src.app import create_app  # noqa: E402

# Full valid rubric payload for the seeded event's default rubric.
RUBRIC_POST = {
    "criterion_functionality": "4",
    "criterion_quality": "4",
    "criterion_innovation": "4",
    "comment": "regression probe",
}


@pytest.fixture()
def env():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "test.db")
        app = create_app(
            db_path=db_path,
            fixtures_path=os.path.join(os.path.dirname(__file__), "..", "fixtures.json"),
        )
        app.config["TESTING"] = True
        with app.test_client() as client:
            # Fixed demo session for seeded judge jdg_24 (tracks trk_01, trk_07).
            client.set_cookie("session", "jdg_a_91bc")
            yield client, db_path


def count(db_path, sql):
    conn = dbmod.connect(db_path)
    try:
        return conn.execute(sql).fetchone()[0]
    finally:
        conn.close()


def test_unassigned_off_track_project_is_forbidden(env):
    """QA repro: seeded judge jdg_24 scoring prj_01 must now be rejected.

    prj_01 is track trk_04 (outside the judge's trk_01/trk_07) and has no
    assignment to jdg_24. Before the fix this returned 302 and persisted
    the score plus an after-the-fact assignment.
    """
    client, db_path = env
    resp = client.post("/judge/score/prj_01", data=RUBRIC_POST)
    assert resp.status_code == 403
    assert count(db_path,
                 "SELECT COUNT(*) FROM scores"
                 " WHERE judge_id = 'jdg_24' AND project_id = 'prj_01'") == 0
    assert count(db_path,
                 "SELECT COUNT(*) FROM judge_assignments"
                 " WHERE judge_id = 'jdg_24' AND project_id = 'prj_01'") == 0


def test_unassigned_project_form_is_forbidden(env):
    """The scoring form itself is gated, not just the write."""
    client, _ = env
    assert client.get("/judge/score/prj_01").status_code == 403


def test_assigned_on_track_project_still_scores(env):
    """jdg_24 is assigned prj_06 (track trk_01, inside the judge's tracks)."""
    client, db_path = env
    resp = client.post("/judge/score/prj_06", data=RUBRIC_POST)
    assert resp.status_code == 302  # redirect to the judge dashboard
    assert count(db_path,
                 "SELECT COUNT(*) FROM scores"
                 " WHERE judge_id = 'jdg_24' AND project_id = 'prj_06'") == 1


def test_own_team_conflict_is_forbidden(env):
    """A judge must not score a project submitted by their own team."""
    client, db_path = env
    conn = dbmod.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO team_members (team_id, user_email)"
            " SELECT p.team_id, u.email FROM projects p, users u"
            " WHERE p.id = 'prj_06' AND u.id = 'jdg_24'",
        )
        conn.commit()
    finally:
        conn.close()
    resp = client.post("/judge/score/prj_06", data=RUBRIC_POST)
    assert resp.status_code == 403
