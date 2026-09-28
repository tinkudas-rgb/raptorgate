"""Cross-judge score normalisation.

Judges differ: some mark harshly, some generously, some bunch every
project at the same number. Raw averages mix those biases into the
ranking. This module removes each judge's personal scale before
comparing projects, using a per-judge z-score.

Method (defended in JUDGING.md):

1. Reduce one review to a single number: the rubric-weighted total
   total(j, p) = sum(weight_c * score_c) / sum(weight_c).
2. For each judge j, compute the mean mu_j and standard deviation
   sigma_j over the totals of the projects that judge reviewed.
3. Convert each review to z(j, p) = (total(j, p) - mu_j) / sigma_j.
   A judge's own average project lands at 0; better-than-their-average
   is positive. A judge who gave every project the same score has
   sigma_j = 0; their reviews carry no ranking information, so we set
   z = 0 for those reviews instead of dividing by zero.
4. A project's normalised score is the mean of z over its reviews,
   mapped back onto the 1..5 scale for display using the global mean
   and standard deviation of all weighted totals:
   display(p) = clip(global_mu + mean_z(p) * global_sigma, 1, 5).
"""

import json
import math
import statistics


def weighted_total(criteria, weights):
    """One review -> one number, honouring the rubric weights."""
    # Old/imported databases may contain invalid weights. Ignore those rather
    # than letting a corrupt rubric take down standings and CSV export.
    safe_weights = {
        c: w if isinstance(w, (int, float)) and math.isfinite(w)
        and 1e-6 <= w <= 1e6 else 1.0
        for c, w in ((c, weights.get(c, 1.0)) for c in criteria)
    }
    num = sum(safe_weights[c] * v for c, v in criteria.items())
    den = sum(safe_weights.values()) or 1.0
    return num / den


def normalise(reviews, weights):
    """reviews: list of dicts {judge_id, project_id, criteria}.

    Returns {project_id: {"raw": float, "z": float, "display": float,
    "reviews": int}}. Projects with no reviews are absent.
    """
    totals = [
        (r["judge_id"], r["project_id"], weighted_total(r["criteria"], weights))
        for r in reviews
    ]
    if not totals:
        return {}

    by_judge = {}
    for judge_id, _, total in totals:
        by_judge.setdefault(judge_id, []).append(total)
    judge_mu = {j: statistics.fmean(v) for j, v in by_judge.items()}
    judge_sigma = {
        j: (statistics.pstdev(v) if len(v) > 1 else 0.0)
        for j, v in by_judge.items()
    }

    all_totals = [t for _, _, t in totals]
    global_mu = statistics.fmean(all_totals)
    global_sigma = statistics.pstdev(all_totals) if len(all_totals) > 1 else 0.0

    by_project = {}
    raw_by_project = {}
    for judge_id, project_id, total in totals:
        sigma = judge_sigma[judge_id]
        z = (total - judge_mu[judge_id]) / sigma if sigma > 0 else 0.0
        by_project.setdefault(project_id, []).append(z)
        raw_by_project.setdefault(project_id, []).append(total)

    out = {}
    for project_id, zs in by_project.items():
        mean_z = statistics.fmean(zs)
        display = global_mu + mean_z * global_sigma if global_sigma > 0 else global_mu
        out[project_id] = {
            "raw": statistics.fmean(raw_by_project[project_id]),
            "z": mean_z,
            "display": min(5.0, max(1.0, display)),
            "reviews": len(zs),
        }
    return out


def load_reviews(conn, event_id):
    rows = conn.execute(
        "SELECT s.judge_id, s.project_id, s.criteria FROM scores s"
        " JOIN projects p ON p.id = s.project_id WHERE p.event_id = ?",
        (event_id,),
    ).fetchall()
    return [
        {"judge_id": r["judge_id"], "project_id": r["project_id"],
         "criteria": json.loads(r["criteria"])}
        for r in rows
    ]


def load_weights(conn, event_id):
    return {
        r["criterion"]: r["weight"]
        for r in conn.execute("SELECT criterion, weight FROM rubric WHERE event_id = ?",
                              (event_id,))
    }
