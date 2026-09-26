# Data model

SQLite, foreign keys on. Schema lives in `src/db.py`; this is the map.

## Tables

- **users**(id, email, name, role, password_hash) - one row per person.
  `role` is participant, judge, organizer or admin. Fixture judges are
  real users, so their dashboards show their real seeded work.
- **sessions**(token, user_id, created_at) - both random login tokens
  and the fixed demo tokens from `.dogfood.toml`.
- **events**(id, name, description, submissions_close, judging_close,
  prizes). Deadlines are ISO 8601 UTC text, compared after parsing.
- **tracks**(id, event_id, name) - tracks belong to an event.
- **teams**(id, event_id, name, invite_code) - the invite code is the
  join link secret.
- **team_members**(team_id, user_email) - membership by email, matching
  the fixtures' shape (fixture members are emails, not user ids).
- **projects**(id, event_id, team_id, track_id, title, summary,
  repo_url, status, submitted_at) - `status` is draft or submitted.
  Only submitted projects appear in the gallery.
- **judges**(user_id, event_id) + **judge_tracks**(user_id, track_id) -
  which judges judge which event, and their declared tracks.
- **judge_assignments**(judge_id, project_id) - the organizer's
  assignments; scoring a project also records the assignment.
- **rubric**(event_id, criterion, weight) - the weighted rubric, as
  data. Re-weighting is an UPDATE, not a migration.
- **scores**(id, judge_id, project_id, criteria, comment, created_at) -
  `criteria` is JSON (`{"functionality": 4, ...}`). UNIQUE(judge_id,
  project_id): one review per judge per project; re-scoring updates.

## Import

`src/seed.py` maps the shared `fixtures.json` onto this schema,
preserving ids. Fixture scores become `scores` rows and also seed
`judge_assignments` (a judge who reviewed a project was, in effect,
assigned to it). The rubric is seeded from the criteria keys present in
the fixtures (functionality, quality, innovation), weight 1.0 each.

## Export

`GET /api/export.csv` (organizer only) emits one row per submitted
project: id, title, track, team, review count, raw weighted average,
normalised z, normalised 1-5 score. The same normalisation feeds the
organizer standings table.

A full export is the database file itself: copy `raptorgate.db` off the
volume. Migrating to Postgres means replaying `src/db.py`'s schema and
the seed transform; there are no SQLite-specific queries beyond
`INSERT OR IGNORE`/`ON CONFLICT` upserts.
