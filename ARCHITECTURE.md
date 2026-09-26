# Architecture

## Shape

One process, one file database. Flask serves server-rendered HTML for
people and JSON for the acceptance checker and scripts. SQLite is the
only store. There is nothing else: no cache, no queue, no external
service, no JavaScript framework. `docker compose up` builds one image
and runs one container; the seed runs on first boot and prints the demo
logins.

This is deliberately boring. The organisers intend to fork the winner
and run real events on it, so the design optimises for "a stranger can
operate this on Monday" over feature count.

```
browser / curl / run.py
        |
   Flask app (src/app.py)
   - auth gate per route (role checks in the backend)
   - HTML views (Jinja) + JSON API
        |
     SQLite (src/db.py schema)
```

## Request lifecycle

1. `before_request` resolves the `session` cookie to a user row.
2. A `require_roles(...)` decorator on every non-public route returns
   401 (anonymous) or 403 (wrong role) before the view runs. API routes
   answer JSON; pages answer a rendered error.
3. Views query through a per-request connection and render.

## Key decisions

- **Backend role isolation as a property of the URL, not the page.**
  `/api/judges/<id>/scores` refuses any judge whose id is not `<id>`.
  The acceptance checker's peer-score probe is a curl request, so the
  check had to live where curl arrives. Organizers and admins can read
  any judge's scores because running the event requires it.
- **Deadline enforcement on write, not on render.** The submit and edit
  views compare `now` to the event's `submissions_close` inside the
  POST handler. A closed event returns 403 even to a hand-crafted
  request; the form merely explains.
- **Seeding is idempotent and input-faithful.** `src/seed.py` loads the
  shared fixtures once (guarded by a row count) and keeps fixture ids,
  so `prj_01` in the fixtures is `prj_01` in the portal. Awkward cases
  (a flat judge, unfinished batches, a duplicate submission) are loaded
  as-is and surfaced on the organizer dashboard, not cleaned away.
- **Fixed demo sessions.** The four `.dogfood.toml` cookies are seeded
  as ordinary session rows with well-known tokens, so a fresh boot
  always matches the committed config. They authenticate the checker;
  human users log in normally and get random tokens.
- **One weighted total per review.** The rubric is data (criterion +
  weight rows), editable by the organizer. Scores store the raw
  criteria JSON, so re-weighting never requires touching reviews.
  Normalisation reads the same raw rows (see `JUDGING.md`).

## Failure modes we accepted

- SQLite serialises writes; fine at hackathon scale (dozens of judges),
  and the migration path out is documented in `DATA-MODEL.md`.
- No rate limiting on login in T1/T2 scope; noted in `THREAT-MODEL.md`
  with the design for it.
