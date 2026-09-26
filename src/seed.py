"""Seed the database from the shared DOGFOOD fixtures.

The fixtures are input, not our schema: records are transformed into
normalised tables on first boot. Seeding is idempotent - if the users
table is populated we do nothing, so restarts never duplicate data.

Four well-known demo accounts are created with fixed session tokens so a
fresh `docker compose up` always prints the same test logins, and the
committed .dogfood.toml always matches a fresh boot.
"""

import hashlib
import json
import secrets
from datetime import datetime, timezone

# Fixed demo sessions. These are test credentials for a seeded demo, not
# secrets: the acceptance checker is designed to receive them.
DEMO_SESSIONS = {
    "organizer": ("usr_org", "org_7f2a"),
    "judge_a": ("jdg_24", "jdg_a_91bc"),
    "judge_b": ("jdg_26", "jdg_b_44de"),
    "participant": ("usr_part", "prt_2e88"),
}

# judge_a / judge_b map to the two fixture judges with the most reviews,
# so their score views are non-empty on a fresh seed.
JUDGE_A_FIXTURE = "jdg_24"
JUDGE_B_FIXTURE = "jdg_26"

DEFAULT_RUBRIC = [("functionality", 1.0), ("quality", 1.0), ("innovation", 1.0)]


def hash_password(password, salt="raptorgate-demo"):
    return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat()


def seed(conn, fixtures_path):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return False

    with open(fixtures_path, encoding="utf-8") as f:
        fx = json.load(f)

    ev = fx["event"]
    conn.execute(
        "INSERT INTO events (id, name, description, submissions_close, judging_close, prizes)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (ev["id"], ev["name"],
         "Seeded from the shared DOGFOOD 2026 fixtures.",
         ev["submissions_close"], None, ""),
    )

    for t in fx["tracks"]:
        conn.execute("INSERT INTO tracks (id, event_id, name) VALUES (?, ?, ?)",
                     (t["id"], ev["id"], t["name"]))

    for criterion, weight in DEFAULT_RUBRIC:
        conn.execute("INSERT INTO rubric (event_id, criterion, weight) VALUES (?, ?, ?)",
                     (ev["id"], criterion, weight))

    for j in fx["judges"]:
        conn.execute(
            "INSERT INTO users (id, email, name, role, password_hash) VALUES (?, ?, ?, 'judge', ?)",
            (j["id"], j["email"], j["name"], hash_password("judge123")),
        )
        conn.execute("INSERT INTO judges (user_id, event_id) VALUES (?, ?)", (j["id"], ev["id"]))
        for trk in j.get("tracks", []):
            conn.execute("INSERT INTO judge_tracks (user_id, track_id) VALUES (?, ?)",
                         (j["id"], trk))

    for t in fx["teams"]:
        conn.execute(
            "INSERT INTO teams (id, event_id, name, invite_code) VALUES (?, ?, ?, ?)",
            (t["id"], ev["id"], t["name"], secrets.token_hex(4)),
        )
        for email in t.get("members", []):
            conn.execute("INSERT INTO team_members (team_id, user_email) VALUES (?, ?)",
                         (t["id"], email))

    for p in fx["projects"]:
        conn.execute(
            "INSERT INTO projects (id, event_id, team_id, track_id, title, summary, repo_url,"
            " status, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, 'submitted', ?)",
            (p["id"], ev["id"], p["team"], p["track"], p["title"],
             p.get("summary", ""), p.get("repo_url", ""), p.get("submitted_at")),
        )

    for s in fx["scores"]:
        conn.execute(
            "INSERT OR IGNORE INTO scores (judge_id, project_id, criteria, comment, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (s["judge"], s["project"], json.dumps(s["criteria"]),
             s.get("comment", ""), _now()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO judge_assignments (judge_id, project_id) VALUES (?, ?)",
            (s["judge"], s["project"]),
        )

    # Demo accounts. judge_a / judge_b reuse the fixture judge rows so
    # their dashboards and score APIs show real seeded work.
    conn.execute(
        "INSERT INTO users (id, email, name, role, password_hash) VALUES (?, ?, ?, 'organizer', ?)",
        ("usr_org", "organizer@example.org", "Demo Organizer", hash_password("organizer123")),
    )
    conn.execute(
        "INSERT INTO users (id, email, name, role, password_hash) VALUES (?, ?, ?, 'participant', ?)",
        ("usr_part", "priya1@example.org", "Demo Participant", hash_password("participant123")),
    )

    for _, (user_id, token) in DEMO_SESSIONS.items():
        conn.execute("INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                     (token, user_id, _now()))

    conn.commit()
    return True


def login_banner():
    lines = ["seeded. test logins:"]
    for label, key in [("organizer", "organizer"), ("judge_a", "judge_a"),
                       ("judge_b", "judge_b"), ("participant", "participant")]:
        token = DEMO_SESSIONS[key][1]
        lines.append(f"  {label:<12} Cookie: session={token}")
    return "\n".join(lines)
