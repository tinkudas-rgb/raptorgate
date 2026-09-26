# Threat model (bonus)

Scope: a self-hosted portal run by one organizer per event. Adversaries
are participants, judges and anonymous visitors - not the host.

## What we defend against today

- **Role confusion / privilege escalation.** Every non-public route
  checks the role in the backend. A judge probing
  `/api/judges/<peer>/scores` gets 403; a participant probing judge or
  organizer APIs gets 403; anonymous callers get 401. There is no
  client-side-only hiding anywhere.
- **Deadline evasion.** Submission and edit deadlines are enforced on
  the write path with server time. Crafted POSTs to closed events are
  refused; the UI being hidden is not the mechanism.
- **Session theft basics.** Session cookies are `HttpOnly` and
  `SameSite=Lax`; tokens are 64-bit random (or the published demo
  tokens, which authenticate seeded demo accounts only).
- **Score tampering by judges.** The UNIQUE(judge_id, project_id)
  constraint makes re-scoring an update of one's own review, never an
  insert into someone else's. Judges cannot write to any other judge's
  row because the judge id comes from the session, not the request.
- **Duplicate submissions.** Surfaced, not silently merged: the
  organizer dashboard flags teams with repeated titles (the fixtures
  contain one), leaving the call to a human.

## What we do not defend against yet (honest list)

- **Ballot stuffing / Sybil voting.** Community voting is a T3 feature
  and is not built, so there is no vote surface to attack. The design
  for it: authenticated one-vote-per-account, per-account and per-IP
  rate limits, and an audit table with voter, timestamp and hash chain
  so deletions are visible.
- **Credential brute force.** There is no login rate limit in T1/T2
  scope. Demo passwords are published for the seeded event; a real
  deployment must rotate them (they live in `src/seed.py`).
- **Collusion between judges.** Normalisation removes scale bias, not
  conspiracy. Mitigation is procedural (organizer reviews outlier
  comments, assignments avoid conflicts of interest) plus the audit
  trail of who scored what when.
- **Host-level attacks.** Backups, TLS and OS patching are deployment
  concerns for whoever self-hosts.
