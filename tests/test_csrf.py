"""Regression tests for the state-changing GET / CSRF fix.

Covers: /logout and /teams/join/<code> no longer mutate state on GET,
their POST forms still work, and cross-site form POSTs (bad Origin or
Referer) are rejected while same-site and JSON API writes still pass.
Run: python3 -m pytest tests/
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import db as dbmod  # noqa: E402
from src.app import create_app  # noqa: E402

COOKIES = {
    "organizer": "org_7f2a",
    "judge_a": "jdg_a_91bc",
    "judge_b": "jdg_b_44de",
    "participant": "prt_2e88",
}

PARTICIPANT_EMAIL = "priya1@example.org"  # usr_part; fixture member of tm_01 only
OTHER_TEAM = "tm_02"


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


def db(client):
    return dbmod.connect(client.application.config["DB_PATH"])


def invite_code(client, team_id):
    conn = db(client)
    code = conn.execute("SELECT invite_code FROM teams WHERE id = ?",
                        (team_id,)).fetchone()["invite_code"]
    conn.close()
    return code


def is_member(client, team_id, email):
    conn = db(client)
    row = conn.execute(
        "SELECT 1 FROM team_members WHERE team_id = ? AND user_email = ?",
        (team_id, email)).fetchone()
    conn.close()
    return row is not None


def session_alive(client):
    # /projects/new requires a logged-in participant and renders 200.
    return client.get("/projects/new").status_code == 200


# --- logout ---

def test_get_logout_does_not_end_session(client):
    as_role(client, "participant")
    assert client.get("/logout").status_code == 405
    assert session_alive(client)


def test_post_logout_ends_session(client):
    as_role(client, "participant")
    resp = client.post("/logout")
    assert resp.status_code == 302
    # session token deleted server-side: the next authed page bounces to login
    resp = client.get("/projects/new")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


# --- join team ---

def test_get_join_does_not_add_member(client):
    as_role(client, "participant")
    code = invite_code(client, OTHER_TEAM)
    resp = client.get(f"/teams/join/{code}")
    assert resp.status_code == 200
    assert not is_member(client, OTHER_TEAM, PARTICIPANT_EMAIL)


def test_post_join_adds_member(client):
    as_role(client, "participant")
    code = invite_code(client, OTHER_TEAM)
    resp = client.post(f"/teams/join/{code}")
    assert resp.status_code == 200
    assert is_member(client, OTHER_TEAM, PARTICIPANT_EMAIL)


def test_join_unknown_code_is_404(client):
    as_role(client, "participant")
    assert client.get("/teams/join/no_such_code").status_code == 404
    assert client.post("/teams/join/no_such_code").status_code == 404


def test_anonymous_join_redirects_to_login(client):
    code = invite_code(client, OTHER_TEAM)
    resp = client.get(f"/teams/join/{code}")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


# --- origin/referer check on form writes ---

def test_cross_site_origin_form_post_blocked(client):
    as_role(client, "participant")
    resp = client.post("/logout", headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert session_alive(client)  # the forged write did not happen


def test_cross_site_referer_form_post_blocked(client):
    as_role(client, "participant")
    resp = client.post("/logout",
                       headers={"Referer": "https://evil.example/clickjack"})
    assert resp.status_code == 403
    assert session_alive(client)


def test_same_site_origin_form_post_allowed(client):
    as_role(client, "participant")
    resp = client.post("/logout", headers={"Origin": "http://localhost"})
    assert resp.status_code == 302


def test_cross_site_join_post_blocked(client):
    as_role(client, "participant")
    code = invite_code(client, OTHER_TEAM)
    resp = client.post(f"/teams/join/{code}",
                       headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert not is_member(client, OTHER_TEAM, PARTICIPANT_EMAIL)


def test_json_api_post_without_origin_not_csrf_blocked(client):
    # The acceptance checker POSTs JSON with a session cookie and no
    # Origin. It must still reach the view (here: refused by the
    # deadline, not by the CSRF layer).
    as_role(client, "participant")
    resp = client.post("/projects/new",
                       json={"title": "csrf-parity-probe", "summary": "probe"})
    assert resp.status_code == 403
    assert "closed" in resp.get_json()["error"].lower()
