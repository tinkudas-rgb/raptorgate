# Judging

## Assignment

Judges are users with the judge role, registered to an event with
declared tracks (`judges`, `judge_tracks`). The organizer assigns
projects to judges explicitly from the dashboard
(`judge_assignments`), and a judge scoring a project records the
assignment implicitly. The seeded data derives assignments from the
fixture reviews: whoever reviewed a project was assigned to it.

The judge dashboard lists each judge's own assignments and their
pending/scored state. The organizer dashboard shows completion per
judge (scored / assigned) so unfinished batches are visible at a
glance - the fixtures contain two, and they show up.

## Scoring

Each review is one row per judge per project: a score 1-5 per rubric
criterion plus a free-text comment. The rubric is per-event data
(`rubric` table), and the organizer can re-weight criteria at any time.
Re-weighting changes derived totals, never stored reviews.

One review reduces to one number by the weighted mean:

```
total(j, p) = sum(weight_c * score_c) / sum(weight_c)
```

## Isolation

Judges see only their own scores - in the backend, not just the UI:

- `GET /api/judge/scores` returns the caller's own scores; non-judges
  get 403, anonymous callers 401.
- `GET /api/judges/<id>/scores` returns judge `<id>`'s scores to the
  organizer, but to a judge only when `<id>` is their own id. Any
  other judge gets 403. This is the rule the acceptance checker probes,
  and it is enforced in the view, so `curl` cannot get around it.
- The gallery and project pages show no scores to anyone; results live
  behind the organizer role until the organizer exports them.

## Normalisation (the documented method)

**Problem.** Judges have personal scales. In the fixtures, one judge
gave every project the same total, and generous and harsh judges differ
by whole points. Averaging raw totals lets a judge's bias move a
project they never reviewed (by moving the average against which it
competes) and lets a loud judge drown out a quiet one.

**Method.** Per-judge z-score normalisation:

1. For each judge j, compute the mean mu_j and standard deviation
   sigma_j of their weighted totals.
2. Convert each review to `z(j, p) = (total(j, p) - mu_j) / sigma_j`.
   A z of 0 means "average for this judge"; +1 means "one standard
   deviation above what this judge usually gives".
3. A project's normalised score is the mean of z over its reviews.
4. For display, z is mapped back to the 1-5 scale with the global mean
   and standard deviation of all weighted totals, clipped to [1, 5].

**Why this is defensible.**

- It removes level bias (generous vs harsh) because every judge's own
  mean is subtracted.
- It removes spread bias (a judge who uses only 4s and 5s vs one who
  uses the full range) because each judge's deviation is divided out.
- It is robust to the fixtures' flat judge: sigma_j = 0 means their
  reviews carry no ranking information, so we set z = 0 for those
  reviews rather than divide by zero. They still count as reviews for
  completion tracking; they simply cannot move the ranking.
- It is one-number-per-review, so it works with any rubric and any
  weights; re-weighting just changes the totals that go in.

**Limits, honestly.** Z-scores assume a judge's pool is a fair sample.
If a judge reviewed only two projects, their mu and sigma are
meaningful mostly as "their two reviews disagree". Projects with few
reviews get noisier means. We report the review count next to every
normalised score in the CSV and the standings table so the organizer
can see which numbers are thin. We considered a Bradley-Terry pairwise
model; it is the better answer when judges compare pairs directly,
which this event's data does not contain.

## Export

`GET /api/export.csv` (organizer only) emits id, title, track, team,
review count, raw average, normalised z and the normalised 1-5 score.
Raw and normalised sit side by side so the effect of the method is
auditable line by line.
