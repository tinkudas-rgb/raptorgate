"""Rubric weights must not corrupt the organizer's standings or CSV export."""

import math
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import db as dbmod, normalize  # noqa: E402
from src.app import create_app  # noqa: E402


@pytest.fixture()
def organizer():
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(
            db_path=os.path.join(tmp, "test.db"),
            fixtures_path=os.path.join(os.path.dirname(__file__), "..", "fixtures.json"),
        )
        app.config["TESTING"] = True
        with app.test_client() as client:
            client.set_cookie("session", "org_7f2a")
            yield client


@pytest.mark.parametrize("bad_weight", ["1e309", "NaN", "Infinity", "0", "-1", "1e-309", "1e7"])
def test_reject_invalid_weights_without_breaking_organizer(organizer, bad_weight):
    conn = dbmod.connect(organizer.application.config["DB_PATH"])
    criterion, original = conn.execute(
        "SELECT criterion, weight FROM rubric WHERE event_id = 'evt_01' LIMIT 1"
    ).fetchone()
    conn.close()

    resp = organizer.post("/organizer/rubric", data={f"weight_{criterion}": bad_weight})
    assert resp.status_code == 400
    conn = dbmod.connect(organizer.application.config["DB_PATH"])
    assert conn.execute(
        "SELECT weight FROM rubric WHERE event_id = 'evt_01' AND criterion = ?",
        (criterion,),
    ).fetchone()[0] == original
    conn.close()
    assert organizer.get("/organizer").status_code == 200
    assert organizer.get("/api/export.csv").status_code == 200


@pytest.mark.parametrize("bad_weight", [float("inf"), 1e100])
def test_old_corrupt_weights_do_not_break_standings_or_export(organizer, bad_weight):
    conn = dbmod.connect(organizer.application.config["DB_PATH"])
    criterion = conn.execute(
        "SELECT criterion FROM rubric WHERE event_id = 'evt_01' LIMIT 1"
    ).fetchone()[0]
    conn.execute(
        "UPDATE rubric SET weight = ? WHERE event_id = 'evt_01' AND criterion = ?",
        (bad_weight, criterion),
    )
    conn.commit()
    conn.close()
    assert organizer.get("/organizer").status_code == 200
    assert organizer.get("/api/export.csv").status_code == 200


def test_weighted_total_ignores_nonfinite_weight():
    result = normalize.weighted_total({"a": 5, "b": 1}, {"a": float("inf"), "b": 1})
    assert math.isfinite(result)
    assert result == 3
