"""Draft detail URLs must not bypass the submitted-only public gallery."""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import db as dbmod  # noqa: E402
from src.app import create_app  # noqa: E402


@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(
            db_path=os.path.join(tmp, "test.db"),
            fixtures_path=os.path.join(os.path.dirname(__file__), "..", "fixtures.json"),
        )
        app.config["TESTING"] = True
        conn = dbmod.connect(app.config["DB_PATH"])
        conn.execute(
            "INSERT INTO projects (id, event_id, team_id, track_id, title, summary,"
            " repo_url, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')",
            ("prj_private", "evt_01", "tm_01", "trk_04", "Private Draft",
             "Unpublished summary", "https://example.org/private"),
        )
        conn.execute(
            "INSERT INTO users (id, email, name, role, password_hash)"
            " VALUES ('usr_other', 'outsider@example.org', 'Other Participant',"
            " 'participant', 'unused')"
        )
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at)"
            " VALUES ('other_session', 'usr_other', '2026-09-28T00:00:00Z')"
        )
        conn.commit()
        conn.close()
        with app.test_client() as test_client:
            yield test_client


def test_anonymous_cannot_open_draft_detail_by_url(client):
    # Gallery already hides drafts, but knowing the direct URL must not reveal it.
    response = client.get("/projects/prj_private")
    assert response.status_code == 404
    assert b"Private Draft" not in response.data
    assert client.get("/projects/prj_02").status_code == 200


@pytest.mark.parametrize("session, expected", [
    ("prt_2e88", 200),      # member of tm_01
    ("org_7f2a", 200),      # organizer
    ("other_session", 404), # participant from another team
    ("jdg_a_91bc", 404),    # judge, regardless of assignment
])
def test_draft_detail_only_for_owner_or_organizer(client, session, expected):
    client.set_cookie("session", session)
    assert client.get("/projects/prj_private").status_code == expected
