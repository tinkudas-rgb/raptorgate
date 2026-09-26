# RaptorGate

A self-hosted submission and judging portal for hackathons. One command
boots it, seeded with the shared DOGFOOD 2026 fixtures, on a laptop with
the network off.

Built for [DOGFOOD 2026](https://dogfoodhack.com) (Hackathon Raptors).
Tiers claimed: **T1, T2** - see `acceptance-report.txt`, reproduced by
`python3 run.py .dogfood.toml` against the running portal.

## Run it

```
docker compose up
```

Then open http://localhost:8080. The boot log prints four demo logins:

```
seeded. test logins:
  organizer    Cookie: session=org_7f2a
  judge_a      Cookie: session=jdg_a_91bc
  judge_b      Cookie: session=jdg_b_44de
  participant  Cookie: session=prt_2e88
```

Those cookies are what `.dogfood.toml` hands to the acceptance checker.
Human logins (the login page) are `organizer@example.org / organizer123`,
`priya1@example.org / participant123`, and any fixture judge email with
`judge123`. These are seeded demo credentials, not secrets.

No Docker? Python 3.11+ works too:

```
pip install -r requirements.txt
python -m src.app        # serves on :8080, seeds raptorgate.db on first boot
```

## Verify it

```
python3 run.py .dogfood.toml
```

All seven checks pass (`acceptance-report.txt` is a committed receipt).
The committed report was captured with the portal on port 8090 because
8080 was occupied on the build machine; the report's checks are
identical - on your machine `docker compose up` serves 8080, matching
`.dogfood.toml`.

Our own suite covers the same seven behaviours plus role isolation,
deadline and normalisation edge cases:

```
python3 -m pytest tests/
```

## What it does

- **Roles**: visitor, participant, judge, organizer, admin - enforced in
  the backend on every route, not hidden in templates. A judge asking
  for a peer's scores gets 403 from curl, not just a missing link.
- **Events**: organizers create events with deadlines, tracks and
  prizes. The seeded fixture event closed in March 2026, so late
  submissions are refused with 4xx - deadline enforcement that holds.
- **Teams**: invite-link formation (`/teams/join/<code>`).
- **Submissions**: draft, edit and submit until the deadline; locked
  after, in the backend.
- **Gallery**: public, searchable, filterable by track.
- **Judging**: organizer assigns judges to projects; judges score on a
  weighted rubric the organizer configures; judges never see each
  other's scores anywhere, including the JSON API.
- **Organizer dashboard**: per-judge completion, per-project review
  counts, normalised standings, duplicate-submission flags, CSV export.
- **Normalisation**: per-judge z-score, documented and defended in
  `JUDGING.md`. The fixture's flat judge (same score for everything)
  contributes zero ranking signal instead of noise.

## Honest limitations

- Sessions are random tokens in the database, fine for a self-hosted
  event tool; there is no password reset flow (an organizer edits the
  seed or the database).
- T3/T4 features (community voting, comments, webhooks, certificates)
  are not built, so they are not claimed. The public read-only JSON
  gallery at `/api/projects` is a start on T4's API tier.
- The demo video is recorded separately and linked from the Devpost
  submission, not stored in this repo.

## Layout

```
src/app.py        routes, auth gates, views
src/db.py         schema (SQLite)
src/seed.py       fixture import, demo accounts, login banner
src/normalize.py  cross-judge normalisation
src/templates/    Jinja views
tests/            pytest suite (16 tests)
run.py            the official DOGFOOD acceptance checker (unmodified)
fixtures.json     the shared fixtures (unmodified)
```

Docs: `ARCHITECTURE.md`, `DATA-MODEL.md`, `JUDGING.md`,
`THREAT-MODEL.md`. License: MIT.
