"""Tests for normalization and de-duplication. No API key required."""

from datetime import datetime, timezone

from alarm_summarizer.dedup import deduplicate, drop_cleared
from alarm_summarizer.models import Alarm, Severity
from alarm_summarizer.normalize import normalize_records, parse_severity, parse_timestamp


def _alarm(node, atype, sev, ts, obj=None):
    return Alarm(
        id=f"{node}-{ts}",
        timestamp=datetime(2026, 11, 24, 8, 0, ts, tzinfo=timezone.utc),
        node=node,
        alarm_type=atype,
        severity=sev,
        managed_object=obj,
    )


def test_parse_severity_aliases():
    assert parse_severity("Critical") is Severity.CRITICAL
    assert parse_severity("5") is Severity.CRITICAL
    assert parse_severity("warn") is Severity.WARNING
    assert parse_severity(None) is Severity.INDETERMINATE
    assert parse_severity("nonsense") is Severity.INDETERMINATE


def test_parse_timestamp_iso_and_epoch():
    assert parse_timestamp("2026-11-24T08:00:00Z").year == 2026
    assert parse_timestamp(1764000000).year >= 2025  # seconds
    assert parse_timestamp(1764000000000).year >= 2025  # milliseconds


def test_normalize_maps_aliases():
    records = [
        {"alarmId": "X", "eventTime": "2026-11-24T08:00:00Z", "ne": "N1",
         "alarmName": "LinkDown", "perceivedSeverity": "major"}
    ]
    alarms = normalize_records(records)
    assert len(alarms) == 1
    a = alarms[0]
    assert a.id == "X"
    assert a.node == "N1"
    assert a.alarm_type == "LinkDown"
    assert a.severity is Severity.MAJOR


def test_normalize_fills_defaults_and_fallback_id():
    alarms = normalize_records([{"node": "N2"}])
    assert alarms[0].id == "ALM-0"
    assert alarms[0].alarm_type == "UnknownAlarm"
    assert alarms[0].severity is Severity.INDETERMINATE


def test_dedup_collapses_identical_signatures():
    alarms = [
        _alarm("N1", "HighBER", Severity.MINOR, 0, obj="mw-1"),
        _alarm("N1", "HighBER", Severity.MINOR, 1, obj="mw-1"),
        _alarm("N1", "HighBER", Severity.MINOR, 2, obj="mw-1"),
    ]
    deduped = deduplicate(alarms)
    assert len(deduped) == 1
    assert deduped[0].count == 3


def test_dedup_flag_flapping():
    alarms = [
        _alarm("N1", "CellDown", Severity.MAJOR, 0, obj="c1"),
        _alarm("N1", "CellDown", Severity.CLEARED, 1, obj="c1"),
        _alarm("N1", "CellDown", Severity.MAJOR, 2, obj="c1"),
        _alarm("N1", "CellDown", Severity.CLEARED, 3, obj="c1"),
        _alarm("N1", "CellDown", Severity.MAJOR, 4, obj="c1"),
    ]
    deduped = deduplicate(alarms, flap_threshold=3)
    assert len(deduped) == 1
    assert deduped[0].flapping is True
    # Representative should be an active (non-cleared) event.
    assert deduped[0].severity is Severity.MAJOR


def test_drop_cleared_keeps_flapping():
    standing_clear = [_alarm("N9", "DiskLow", Severity.CLEARED, 0)]
    flapping = [
        _alarm("N1", "CellDown", Severity.MAJOR, 0, obj="c1"),
        _alarm("N1", "CellDown", Severity.CLEARED, 1, obj="c1"),
        _alarm("N1", "CellDown", Severity.MAJOR, 2, obj="c1"),
        _alarm("N1", "CellDown", Severity.CLEARED, 3, obj="c1"),
    ]
    deduped = deduplicate(standing_clear + flapping, flap_threshold=3)
    kept = drop_cleared(deduped)
    kept_nodes = {d.node for d in kept}
    assert "N9" not in kept_nodes  # standing cleared dropped
    assert "N1" in kept_nodes  # flapping kept
