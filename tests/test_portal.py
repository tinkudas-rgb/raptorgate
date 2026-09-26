"""RaptorGate's own test suite, beyond the acceptance checker.

Covers the seven acceptance behaviours plus role isolation, deadline
enforcement and the normalisation math. Run: python3 -m pytest tests/
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import normalize  # noqa: E402
from src.app import create_app  # noqa: E402

COOKIES = {
    "organizer": "org_7f2a",
    "judge_a": "jdg_a_91bc",
    "judge_b": "jdg_b_44de",
    "participant": "prt_2e88",
}


@pytest.fixture()
def client():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(
            db_path=os.path.join(tmp, "test.db"),
            fixtures_path=os.path.join(os.path.dirname(__file__), "..", "fixtures.json"),
        )
        app.config["TESTING"] = True
        with app.test_client() as c:
            yield c


def as_role(client, role):
    client.set_cookie("session", COOKIES[role])


def clear_auth(client):
    client.delete_cookie("session")


# --- the seven acceptance behaviours, as unit tests ---

def test_gallery_is_public(client):
    clear_auth(client)
    assert client.get("/projects").status_code == 200


def test_gallery_shows_fixture_titles(client):
    clear_auth(client)
    body = client.get("/projects").get_data(as_text=True).lower()
    with open(os.path.join(os.path.dirname(__file__), "..", "fixtures.json")) as f:
        titles = [p["title"] for p in json.load(f)["projects"][:3]]
    assert any(t.lower() in body for t in titles)


def test_closed_event_refuses_submission(client):
    as_role(client, "participant")
    resp = client.post("/projects/new",
                       json={"title": "dogfood-late-submission-probe", "summary": "probe"})
    assert 400 <= resp.status_code < 500


def test_judge_sees_own_scores(client):
    as_role(client, "judge_a")
    resp = client.get("/api/judge/scores")
    assert resp.status_code == 200
    assert resp.get_json()["judge"] == "jdg_24"


def test_judge_cannot_see_peer_scores(client):
    as_role(client, "judge_b")
    assert client.get("/api/judges/jdg_24/scores").status_code in (401, 403)


def test_participant_blocked_from_judge_api(client):
    as_role(client, "participant")
    assert client.get("/api/judge/scores").status_code in (401, 403)


def test_csv_export(client):
    as_role(client, "organizer")
    resp = client.get("/api/export.csv")
    assert resp.status_code == 200
    assert "," in resp.get_data(as_text=True).splitlines()[0]


# --- beyond the checker ---

def test_anonymous_judge_api_is_401(client):
    clear_auth(client)
    assert client.get("/api/judge/scores").status_code == 401
    assert client.get("/api/export.csv").status_code == 401


def test_judge_cannot_export_csv(client):
    as_role(client, "judge_a")
    assert client.get("/api/export.csv").status_code == 403


def test_participant_blocked_from_peer_scores(client):
    as_role(client, "participant")
    assert client.get("/api/judges/jdg_24/scores").status_code in (401, 403)


def test_organizer_can_read_any_judge_scores(client):
    as_role(client, "organizer")
    assert client.get("/api/judges/jdg_24/scores").status_code == 200


def test_open_event_accepts_submission(client):
    as_role(client, "organizer")
    resp = client.post("/organizer/events", data={
        "name": "Live Test Hack",
        "submissions_close": "2099-01-01T00:00:00Z",
        "tracks": "Web, Hardware",
    })
    assert resp.status_code == 302
    from src import db as dbmod
    conn = dbmod.connect(client.application.config["DB_PATH"])
    event_id = conn.execute(
        "SELECT id FROM events WHERE name = 'Live Test Hack'").fetchone()["id"]
    conn.close()
    as_role(client, "participant")
    resp = client.post(f"/events/{event_id}/submit",
                       json={"title": "Fresh Build", "summary": "made during the window"})
    assert resp.status_code == 201
    assert resp.get_json()["status"] == "submitted"


def test_submit_unknown_event_is_404(client):
    as_role(client, "participant")
    assert client.post("/events/evt_nope/submit", json={"title": "x"}).status_code == 404


def test_edit_refused_after_deadline(client):
    as_role(client, "participant")
    resp = client.post("/projects/prj_01/edit", data={"title": "new title"})
    assert resp.status_code == 403


def test_normalisation_flat_judge_neutral():
    weights = {"a": 1.0}
    reviews = [
        {"judge_id": "j_flat", "project_id": "p1", "criteria": {"a": 4}},
        {"judge_id": "j_flat", "project_id": "p2", "criteria": {"a": 4}},
        {"judge_id": "j_norm", "project_id": "p1", "criteria": {"a": 5}},
        {"judge_id": "j_norm", "project_id": "p2", "criteria": {"a": 1}},
    ]
    out = normalize.normalise(reviews, weights)
    # the flat judge contributes z=0 everywhere, so p1 must rank above p2
    assert out["p1"]["z"] > out["p2"]["z"]
    assert out["p1"]["display"] > out["p2"]["display"]


def test_normalisation_removes_generosity_bias():
    weights = {"a": 1.0}
    # harsh judge: p1=3, p2=2. generous judge: p1=5, p2=4.
    # both prefer p1 by the same margin, so p1 should win on z.
    reviews = [
        {"judge_id": "harsh", "project_id": "p1", "criteria": {"a": 3}},
        {"judge_id": "harsh", "project_id": "p2", "criteria": {"a": 2}},
        {"judge_id": "kind", "project_id": "p1", "criteria": {"a": 5}},
        {"judge_id": "kind", "project_id": "p2", "criteria": {"a": 4}},
    ]
    out = normalize.normalise(reviews, weights)
    assert out["p1"]["z"] > 0 > out["p2"]["z"]
