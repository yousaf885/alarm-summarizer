"""Tests for alarm correlation into incidents. No API key required."""

from datetime import datetime, timezone

from alarm_summarizer.correlate import correlate
from alarm_summarizer.dedup import deduplicate
from alarm_summarizer.models import Alarm, Severity


def _alarm(node, atype, sev, minute, cause=None, obj=None):
    return Alarm(
        id=f"{node}-{atype}-{minute}",
        timestamp=datetime(2026, 11, 24, 8, minute, 0, tzinfo=timezone.utc),
        node=node,
        alarm_type=atype,
        severity=sev,
        probable_cause=cause,
        managed_object=obj,
    )


def test_same_node_alarms_group_together():
    alarms = [
        _alarm("N1", "MainsFail", Severity.CRITICAL, 0, cause="power"),
        _alarm("N1", "Rectifier", Severity.MAJOR, 1, cause="power"),
    ]
    incidents = correlate(deduplicate(alarms))
    assert len(incidents) == 1
    assert set(incidents[0].nodes) == {"N1"}


def test_cross_node_same_cause_in_window_groups():
    # Different nodes, shared cause, close in time -> one incident.
    alarms = [
        _alarm("N1", "MainsFail", Severity.CRITICAL, 0, cause="powerProblem"),
        _alarm("TX1", "LinkDown", Severity.CRITICAL, 2, cause="powerProblem"),
    ]
    incidents = correlate(deduplicate(alarms), window_seconds=300)
    assert len(incidents) == 1
    assert set(incidents[0].nodes) == {"N1", "TX1"}


def test_unrelated_alarms_stay_separate():
    alarms = [
        _alarm("N1", "MainsFail", Severity.CRITICAL, 0, cause="power"),
        _alarm("N2", "HighTemp", Severity.WARNING, 30, cause="temperature"),
    ]
    incidents = correlate(deduplicate(alarms), window_seconds=300)
    assert len(incidents) == 2


def test_incidents_sorted_most_severe_first():
    alarms = [
        _alarm("N2", "HighTemp", Severity.WARNING, 30, cause="temperature"),
        _alarm("N1", "MainsFail", Severity.CRITICAL, 0, cause="power"),
    ]
    incidents = correlate(deduplicate(alarms), window_seconds=300)
    assert incidents[0].severity is Severity.CRITICAL
    assert incidents[0].id == "INC-001"


def test_incident_properties():
    alarms = [
        _alarm("N1", "A", Severity.MAJOR, 0),
        _alarm("N1", "B", Severity.CRITICAL, 5),
    ]
    inc = correlate(deduplicate(alarms))[0]
    assert inc.severity is Severity.CRITICAL
    assert inc.total_events == 2
    assert inc.first_seen < inc.last_seen
    assert "Incident" in inc.to_prompt_block()
