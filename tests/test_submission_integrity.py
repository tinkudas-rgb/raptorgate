"""Cross-event team and track boundaries for submissions."""

from test_portal import as_role, client  # noqa: F401
from src import db as dbmod


def make_event(client, name):
    as_role(client, "organizer")
    response = client.post("/organizer/events", data={
        "name": name,
        "submissions_close": "2099-01-01T00:00:00Z",
        "tracks": "Web, Hardware",
    })
    assert response.status_code == 302
    conn = dbmod.connect(client.application.config["DB_PATH"])
    event = conn.execute("SELECT id FROM events WHERE name = ?", (name,)).fetchone()["id"]
    track = conn.execute("SELECT id FROM tracks WHERE event_id = ? ORDER BY id LIMIT 1", (event,)).fetchone()["id"]
    conn.close()
    return event, track


def test_submission_rejects_track_from_another_event_without_writing(client):
    event, _track = make_event(client, "Live Event")
    as_role(client, "participant")
    response = client.post(f"/events/{event}/submit", json={
        "title": "Cross-event probe", "track_id": "trk_01",
    })
    assert response.status_code == 400
    conn = dbmod.connect(client.application.config["DB_PATH"])
    assert conn.execute("SELECT COUNT(*) FROM projects WHERE title = 'Cross-event probe'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM teams WHERE event_id = ?", (event,)).fetchone()[0] == 0
    conn.close()


def test_submissions_use_teams_in_their_own_event(client):
    first_event, first_track = make_event(client, "First live event")
    second_event, second_track = make_event(client, "Second live event")
    as_role(client, "participant")
    for event, track in ((first_event, first_track), (second_event, second_track)):
        response = client.post(f"/events/{event}/submit", json={
            "title": f"Project for {event}", "track_id": track,
        })
        assert response.status_code == 201
        conn = dbmod.connect(client.application.config["DB_PATH"])
        project = conn.execute(
            "SELECT p.event_id, p.track_id, t.event_id AS team_event "
            "FROM projects p JOIN teams t ON t.id = p.team_id WHERE p.id = ?",
            (response.get_json()["id"],),
        ).fetchone()
        assert (project["event_id"], project["track_id"], project["team_event"]) == (event, track, event)
        conn.close()


def test_edit_rejects_track_from_another_event(client):
    event, track = make_event(client, "Editable live event")
    as_role(client, "participant")
    response = client.post(f"/events/{event}/submit", json={"title": "Safe", "track_id": track})
    assert response.status_code == 201
    project_id = response.get_json()["id"]
    edit = client.post(f"/projects/{project_id}/edit", data={"track_id": "trk_01"})
    assert edit.status_code == 400
    conn = dbmod.connect(client.application.config["DB_PATH"])
    assert conn.execute("SELECT track_id FROM projects WHERE id = ?", (project_id,)).fetchone()[0] == track
    conn.close()
