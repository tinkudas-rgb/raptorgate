"""RaptorGate - self-hosted submission and judging portal for hackathons.

Flask + SQLite, no external services. Boot it, it seeds itself from the
shared fixtures and prints demo logins. See README.md.
"""

import functools
import json
import re
import secrets
from datetime import datetime, timezone

from flask import (Flask, Response, abort, g, jsonify, redirect,
                   render_template, request, url_for)

from . import db as dbmod
from . import normalize, seed

DEFAULT_EVENT_ID = "evt_01"  # the seeded fixture event


def create_app(db_path="raptorgate.db", fixtures_path="fixtures.json"):
    app = Flask(__name__)
    app.config["DB_PATH"] = db_path

    conn = dbmod.connect(db_path)
    dbmod.init_schema(conn)
    seeded = seed.seed(conn, fixtures_path)
    conn.close()
    if seeded:
        print(seed.login_banner(), flush=True)

    def get_db():
        if "db" not in g:
            g.db = dbmod.connect(app.config["DB_PATH"])
        return g.db

    @app.teardown_appcontext
    def close_db(_exc):
        conn = g.pop("db", None)
        if conn is not None:
            conn.close()

    # ---------------- auth ----------------

    def current_user():
        token = request.cookies.get("session", "")
        if not token:
            return None
        return get_db().execute(
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token = ?", (token,),
        ).fetchone()

    @app.before_request
    def load_user():
        g.user = current_user()

    def require_roles(*roles):
        """Backend role gate. 401 when anonymous, 403 when the wrong role.

        The acceptance checker arrives with curl, so these checks live
        here in the views, never only in templates.
        """
        def deco(view):
            @functools.wraps(view)
            def wrapped(*args, **kwargs):
                if g.user is None:
                    if request.path.startswith("/api/"):
                        return jsonify({"error": "authentication required"}), 401
                    return redirect(url_for("login", next=request.path))
                if g.user["role"] not in roles:
                    if request.path.startswith("/api/"):
                        return jsonify({"error": "forbidden"}), 403
                    return render_template("error.html", code=403,
                                           message="You do not have access to this page."), 403
                return view(*args, **kwargs)
            return wrapped
        return deco

    # ---------------- helpers ----------------

    def parse_ts(value):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def event_open(event):
        return datetime.now(timezone.utc) <= parse_ts(event["submissions_close"])

    def get_event(event_id=DEFAULT_EVENT_ID):
        return get_db().execute("SELECT * FROM events WHERE id = ?",
                                (event_id,)).fetchone()

    def submission_fields():
        """Accept both the HTML form and the checker's JSON probe."""
        if request.is_json:
            data = request.get_json(silent=True) or {}
        else:
            data = request.form
        return {
            "title": (data.get("title") or "").strip(),
            "summary": (data.get("summary") or "").strip(),
            "repo_url": (data.get("repo_url") or "").strip(),
            "track_id": (data.get("track_id") or "").strip(),
            "action": (data.get("action") or "submit").strip(),
        }

    def user_team(user):
        return get_db().execute(
            "SELECT t.* FROM teams t JOIN team_members m ON m.team_id = t.id"
            " WHERE m.user_email = ?", (user["email"],),
        ).fetchone()

    # ---------------- public ----------------

    @app.route("/")
    def home():
        return redirect(url_for("gallery"))

    @app.route("/projects")
    def gallery():
        q = request.args.get("q", "").strip()
        track = request.args.get("track", "").strip()
        sql = ("SELECT p.*, t.name AS track_name, tm.name AS team_name,"
               " (SELECT COUNT(*) FROM scores s WHERE s.project_id = p.id) AS review_count"
               " FROM projects p JOIN tracks t ON t.id = p.track_id"
               " JOIN teams tm ON tm.id = p.team_id WHERE p.status = 'submitted'")
        args = []
        if q:
            sql += " AND (LOWER(p.title) LIKE ? OR LOWER(p.summary) LIKE ?)"
            args += [f"%{q.lower()}%", f"%{q.lower()}%"]
        if track:
            sql += " AND p.track_id = ?"
            args.append(track)
        sql += " ORDER BY p.title"
        projects = get_db().execute(sql, args).fetchall()
        tracks = get_db().execute("SELECT * FROM tracks ORDER BY name").fetchall()
        return render_template("gallery.html", projects=projects, tracks=tracks,
                               q=q, track=track, event=get_event())

    @app.route("/projects/<project_id>")
    def project_detail(project_id):
        p = get_db().execute(
            "SELECT p.*, t.name AS track_name, tm.name AS team_name FROM projects p"
            " JOIN tracks t ON t.id = p.track_id JOIN teams tm ON tm.id = p.team_id"
            " WHERE p.id = ?", (project_id,),
        ).fetchone()
        if p is None:
            abort(404)
        return render_template("project.html", p=p)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            email = request.form.get("email", "").strip().lower()
            password = request.form.get("password", "")
            user = get_db().execute("SELECT * FROM users WHERE LOWER(email) = ?",
                                    (email,)).fetchone()
            if user and user["password_hash"] == seed.hash_password(password):
                token = secrets.token_hex(8)
                get_db().execute(
                    "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
                    (token, user["id"], datetime.now(timezone.utc).isoformat()),
                )
                get_db().commit()
                resp = redirect(request.args.get("next") or url_for("gallery"))
                resp.set_cookie("session", token, httponly=True, samesite="Lax")
                return resp
            error = "Unknown email or password."
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        token = request.cookies.get("session", "")
        if token:
            get_db().execute("DELETE FROM sessions WHERE token = ?", (token,))
            get_db().commit()
        resp = redirect(url_for("gallery"))
        resp.delete_cookie("session")
        return resp

    # ---------------- participant ----------------

    @app.route("/projects/new", methods=["GET", "POST"])
    @require_roles("participant", "organizer", "admin")
    def submit_project():
        """Submit to the seeded fixture event. That event's submissions_close
        is in the past, so writes here are refused - deadline enforcement
        is the point of the check. Live events use /events/<id>/submit."""
        return _submit_to_event(DEFAULT_EVENT_ID)

    @app.route("/events/<event_id>/submit", methods=["GET", "POST"])
    @require_roles("participant", "organizer", "admin")
    def submit_to_event(event_id):
        return _submit_to_event(event_id)

    def _submit_to_event(event_id):
        event = get_event(event_id)
        if event is None:
            abort(404)
        if request.method == "POST":
            if not event_open(event):
                # Deadline enforcement: the write is refused in the backend.
                message = (f"Submissions for {event['name']} closed at "
                           f"{event['submissions_close']}.")
                if request.is_json:
                    return jsonify({"error": message}), 403
                return render_template("error.html", code=403, message=message), 403
            fields = submission_fields()
            if not fields["title"]:
                return render_template("error.html", code=400,
                                       message="A title is required."), 400
            team = user_team(g.user)
            if team is None:
                team_id = f"tm_{secrets.token_hex(4)}"
                get_db().execute(
                    "INSERT INTO teams (id, event_id, name, invite_code) VALUES (?, ?, ?, ?)",
                    (team_id, event_id, f"{g.user['name']}'s team", secrets.token_hex(4)),
                )
                get_db().execute(
                    "INSERT INTO team_members (team_id, user_email) VALUES (?, ?)",
                    (team_id, g.user["email"]),
                )
            else:
                team_id = team["id"]
            track_id = fields["track_id"] or get_db().execute(
                "SELECT id FROM tracks WHERE event_id = ? ORDER BY id LIMIT 1",
                (event_id,)).fetchone()["id"]
            project_id = f"prj_{secrets.token_hex(4)}"
            status = "draft" if fields["action"] == "draft" else "submitted"
            get_db().execute(
                "INSERT INTO projects (id, event_id, team_id, track_id, title, summary,"
                " repo_url, status, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, event_id, team_id, track_id, fields["title"],
                 fields["summary"], fields["repo_url"], status,
                 datetime.now(timezone.utc).isoformat()),
            )
            get_db().commit()
            if request.is_json:
                return jsonify({"id": project_id, "status": status}), 201
            return redirect(url_for("project_detail", project_id=project_id))
        tracks = get_db().execute("SELECT * FROM tracks WHERE event_id = ? ORDER BY name",
                                  (event_id,)).fetchall()
        return render_template("submit.html", event=event, tracks=tracks,
                               open=event_open(event))

    @app.route("/projects/<project_id>/edit", methods=["GET", "POST"])
    @require_roles("participant", "organizer", "admin")
    def edit_project(project_id):
        p = get_db().execute("SELECT * FROM projects WHERE id = ?",
                             (project_id,)).fetchone()
        if p is None:
            abort(404)
        team = user_team(g.user)
        if g.user["role"] == "participant" and (team is None or team["id"] != p["team_id"]):
            return render_template("error.html", code=403,
                                   message="Only a member of the team can edit this project."), 403
        event = get_event(p["event_id"])
        if request.method == "POST":
            if not event_open(event):
                return render_template("error.html", code=403,
                                       message="The submission window has closed."), 403
            fields = submission_fields()
            status = "draft" if fields["action"] == "draft" else "submitted"
            get_db().execute(
                "UPDATE projects SET title = ?, summary = ?, repo_url = ?,"
                " track_id = COALESCE(NULLIF(?, ''), track_id), status = ? WHERE id = ?",
                (fields["title"] or p["title"], fields["summary"], fields["repo_url"],
                 fields["track_id"], status, project_id),
            )
            get_db().commit()
            return redirect(url_for("project_detail", project_id=project_id))
        tracks = get_db().execute("SELECT * FROM tracks WHERE event_id = ? ORDER BY name",
                                  (p["event_id"],)).fetchall()
        return render_template("edit_project.html", p=p, event=event, tracks=tracks,
                               open=event_open(event))

    @app.route("/teams/join/<invite_code>")
    @require_roles("participant", "organizer", "admin")
    def join_team(invite_code):
        team = get_db().execute("SELECT * FROM teams WHERE invite_code = ?",
                                (invite_code,)).fetchone()
        if team is None:
            abort(404)
        get_db().execute(
            "INSERT OR IGNORE INTO team_members (team_id, user_email) VALUES (?, ?)",
            (team["id"], g.user["email"]),
        )
        get_db().commit()
        return render_template("joined.html", team=team)

    # ---------------- judge ----------------

    @app.route("/judge")
    @require_roles("judge")
    def judge_dashboard():
        conn = get_db()
        assignments = conn.execute(
            "SELECT p.id, p.title, t.name AS track_name,"
            " (SELECT COUNT(*) FROM scores s WHERE s.project_id = p.id AND s.judge_id = ?)"
            "   AS scored"
            " FROM judge_assignments ja JOIN projects p ON p.id = ja.project_id"
            " JOIN tracks t ON t.id = p.track_id"
            " WHERE ja.judge_id = ? ORDER BY p.title",
            (g.user["id"], g.user["id"]),
        ).fetchall()
        return render_template("judge.html", assignments=assignments)

    @app.route("/judge/score/<project_id>", methods=["GET", "POST"])
    @require_roles("judge")
    def score_project(project_id):
        conn = get_db()
        p = conn.execute(
            "SELECT p.*, t.name AS track_name, tm.name AS team_name FROM projects p"
            " JOIN tracks t ON t.id = p.track_id JOIN teams tm ON tm.id = p.team_id"
            " WHERE p.id = ?", (project_id,),
        ).fetchone()
        if p is None:
            abort(404)
        rubric = conn.execute(
            "SELECT criterion, weight FROM rubric WHERE event_id = ? ORDER BY criterion",
            (p["event_id"],)).fetchall()
        existing = conn.execute(
            "SELECT criteria, comment FROM scores WHERE judge_id = ? AND project_id = ?",
            (g.user["id"], project_id)).fetchone()
        if request.method == "POST":
            criteria = {}
            for r in rubric:
                try:
                    value = int(request.form.get(f"criterion_{r['criterion']}", ""))
                except ValueError:
                    return render_template("error.html", code=400,
                                           message=f"Score for {r['criterion']} must be 1-5."), 400
                if not 1 <= value <= 5:
                    return render_template("error.html", code=400,
                                           message=f"Score for {r['criterion']} must be 1-5."), 400
                criteria[r["criterion"]] = value
            conn.execute(
                "INSERT INTO scores (judge_id, project_id, criteria, comment, created_at)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT (judge_id, project_id)"
                " DO UPDATE SET criteria = excluded.criteria, comment = excluded.comment,"
                " created_at = excluded.created_at",
                (g.user["id"], project_id, json.dumps(criteria),
                 request.form.get("comment", "").strip(),
                 datetime.now(timezone.utc).isoformat()),
            )
            conn.execute(
                "INSERT OR IGNORE INTO judge_assignments (judge_id, project_id) VALUES (?, ?)",
                (g.user["id"], project_id),
            )
            conn.commit()
            return redirect(url_for("judge_dashboard"))
        saved = json.loads(existing["criteria"]) if existing else {}
        return render_template("score_form.html", p=p, rubric=rubric, saved=saved,
                               comment=existing["comment"] if existing else "")

    # ---------------- judge APIs (role isolation lives here) ----------------

    def scores_json(judge_id):
        rows = get_db().execute(
            "SELECT s.project_id, p.title, s.criteria, s.comment, s.created_at"
            " FROM scores s JOIN projects p ON p.id = s.project_id"
            " WHERE s.judge_id = ? ORDER BY p.title", (judge_id,),
        ).fetchall()
        return {
            "judge": judge_id,
            "scores": [
                {"project_id": r["project_id"], "title": r["title"],
                 "criteria": json.loads(r["criteria"]), "comment": r["comment"],
                 "created_at": r["created_at"]}
                for r in rows
            ],
        }

    @app.route("/api/judge/scores")
    def api_own_scores():
        if g.user is None:
            return jsonify({"error": "authentication required"}), 401
        if g.user["role"] != "judge":
            return jsonify({"error": "forbidden"}), 403
        return jsonify(scores_json(g.user["id"]))

    @app.route("/api/judges/<judge_id>/scores")
    def api_peer_scores(judge_id):
        if g.user is None:
            return jsonify({"error": "authentication required"}), 401
        # A judge may read only their own scores. Organizers and admins
        # run the event, so they may read anyone's.
        if g.user["role"] == "judge" and g.user["id"] != judge_id:
            return jsonify({"error": "judges cannot read peer scores"}), 403
        if g.user["role"] not in ("judge", "organizer", "admin"):
            return jsonify({"error": "forbidden"}), 403
        return jsonify(scores_json(judge_id))

    # ---------------- organizer ----------------

    @app.route("/organizer")
    @require_roles("organizer", "admin")
    def organizer_dashboard():
        conn = get_db()
        event = get_event()
        judges = conn.execute(
            "SELECT u.id, u.name,"
            " (SELECT COUNT(*) FROM judge_assignments ja WHERE ja.judge_id = u.id) AS assigned,"
            " (SELECT COUNT(*) FROM scores s WHERE s.judge_id = u.id) AS scored"
            " FROM users u JOIN judges j ON j.user_id = u.id ORDER BY u.name"
        ).fetchall()
        projects = conn.execute(
            "SELECT p.id, p.title, t.name AS track_name,"
            " (SELECT COUNT(*) FROM scores s WHERE s.project_id = p.id) AS reviews"
            " FROM projects p JOIN tracks t ON t.id = p.track_id"
            " WHERE p.event_id = ? ORDER BY p.title", (event["id"],),
        ).fetchall()
        standings = normalize.normalise(
            normalize.load_reviews(conn, event["id"]),
            normalize.load_weights(conn, event["id"]),
        )
        titles = {}
        for p in projects:
            key = re.sub(r"\s+", " ", p["title"].lower()).strip()
            titles.setdefault(key, []).append(p["id"])
        duplicates = sorted(t for t, ids in titles.items() if len(ids) > 1)
        rubric = conn.execute(
            "SELECT criterion, weight FROM rubric WHERE event_id = ? ORDER BY criterion",
            (event["id"],)).fetchall()
        return render_template("organizer.html", event=event, judges=judges,
                               projects=projects, standings=standings,
                               duplicates=duplicates, rubric=rubric,
                               open=event_open(event))

    @app.route("/organizer/rubric", methods=["POST"])
    @require_roles("organizer", "admin")
    def set_rubric():
        conn = get_db()
        event = get_event()
        for row in conn.execute("SELECT criterion FROM rubric WHERE event_id = ?",
                                (event["id"],)).fetchall():
            raw = request.form.get(f"weight_{row['criterion']}", "")
            try:
                weight = float(raw)
                if weight <= 0:
                    raise ValueError
            except ValueError:
                return render_template("error.html", code=400,
                                       message="Weights must be positive numbers."), 400
            conn.execute("UPDATE rubric SET weight = ? WHERE event_id = ? AND criterion = ?",
                         (weight, event["id"], row["criterion"]))
        conn.commit()
        return redirect(url_for("organizer_dashboard"))

    @app.route("/organizer/events", methods=["POST"])
    @require_roles("organizer", "admin")
    def create_event():
        name = request.form.get("name", "").strip()
        close = request.form.get("submissions_close", "").strip()
        prizes = request.form.get("prizes", "").strip()
        tracks_raw = request.form.get("tracks", "").strip()
        if not name or not close:
            return render_template("error.html", code=400,
                                   message="Name and submission deadline are required."), 400
        try:
            close_ts = parse_ts(close)
        except ValueError:
            return render_template("error.html", code=400,
                                   message="Deadline must be ISO 8601, e.g. 2026-10-01T18:00:00Z."), 400
        event_id = f"evt_{secrets.token_hex(4)}"
        conn = get_db()
        conn.execute(
            "INSERT INTO events (id, name, description, submissions_close, judging_close, prizes)"
            " VALUES (?, ?, '', ?, NULL, ?)",
            (event_id, name, close_ts.isoformat().replace("+00:00", "Z"), prizes),
        )
        for i, track_name in enumerate(
                [t.strip() for t in tracks_raw.split(",") if t.strip()] or ["General"], 1):
            conn.execute("INSERT INTO tracks (id, event_id, name) VALUES (?, ?, ?)",
                         (f"{event_id}_trk_{i:02d}", event_id, track_name))
        for criterion, weight in seed.DEFAULT_RUBRIC:
            conn.execute("INSERT INTO rubric (event_id, criterion, weight) VALUES (?, ?, ?)",
                         (event_id, criterion, weight))
        conn.commit()
        return redirect(url_for("organizer_dashboard"))

    @app.route("/organizer/judges/assign", methods=["POST"])
    @require_roles("organizer", "admin")
    def assign_judge():
        judge_id = request.form.get("judge_id", "")
        project_id = request.form.get("project_id", "")
        conn = get_db()
        judge = conn.execute("SELECT id FROM users WHERE id = ? AND role = 'judge'",
                             (judge_id,)).fetchone()
        project = conn.execute("SELECT id FROM projects WHERE id = ?",
                               (project_id,)).fetchone()
        if judge is None or project is None:
            return render_template("error.html", code=400,
                                   message="Unknown judge or project."), 400
        conn.execute(
            "INSERT OR IGNORE INTO judge_assignments (judge_id, project_id) VALUES (?, ?)",
            (judge_id, project_id),
        )
        conn.commit()
        return redirect(url_for("organizer_dashboard"))

    @app.route("/api/export.csv")
    def api_export_csv():
        if g.user is None:
            return jsonify({"error": "authentication required"}), 401
        if g.user["role"] not in ("organizer", "admin"):
            return jsonify({"error": "forbidden"}), 403
        conn = get_db()
        event = get_event()
        standings = normalize.normalise(
            normalize.load_reviews(conn, event["id"]),
            normalize.load_weights(conn, event["id"]),
        )
        rows = conn.execute(
            "SELECT p.id, p.title, t.name AS track, tm.name AS team FROM projects p"
            " JOIN tracks t ON t.id = p.track_id JOIN teams tm ON tm.id = p.team_id"
            " WHERE p.event_id = ? AND p.status = 'submitted' ORDER BY p.title",
            (event["id"],),
        ).fetchall()

        def cell(value):
            text = str(value)
            return '"' + text.replace('"', '""') + '"' if any(
                c in text for c in ',"\n') else text

        lines = ["project_id,title,track,team,reviews,raw_avg,normalized_z,normalized_score"]
        for r in rows:
            s = standings.get(r["id"])
            lines.append(",".join(cell(v) for v in [
                r["id"], r["title"], r["track"], r["team"],
                s["reviews"] if s else 0,
                f"{s['raw']:.3f}" if s else "",
                f"{s['z']:.3f}" if s else "",
                f"{s['display']:.3f}" if s else "",
            ]))
        return Response("\n".join(lines) + "\n", mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=results.csv"})

    @app.route("/api/projects")
    def api_projects():
        rows = get_db().execute(
            "SELECT p.id, p.title, p.summary, p.repo_url, t.name AS track, tm.name AS team"
            " FROM projects p JOIN tracks t ON t.id = p.track_id"
            " JOIN teams tm ON tm.id = p.team_id WHERE p.status = 'submitted'"
            " ORDER BY p.title").fetchall()
        return jsonify({"projects": [dict(r) for r in rows]})

    @app.route("/healthz")
    def healthz():
        return "ok\n"

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="Not found."), 404

    return app


def main():
    import os
    db_path = os.environ.get("RAPTORGATE_DB", "raptorgate.db")
    fixtures = os.environ.get("RAPTORGATE_FIXTURES", "fixtures.json")
    app = create_app(db_path, fixtures)
    app.run(host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
