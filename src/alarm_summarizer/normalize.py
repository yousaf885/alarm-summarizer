"""Parse heterogeneous alarm records into the canonical `Alarm` model.

Real alarm feeds (NMS exports, syslog-ish CSVs, vendor JSON) use wildly
different field names. This maps the common aliases onto our schema so the
rest of the pipeline sees one shape. Unknown fields are ignored; missing
severities default to INDETERMINATE.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import Alarm, Severity

# Candidate source keys for each canonical field, checked in order.
_ALIASES: dict[str, tuple[str, ...]] = {
    "id": ("id", "alarm_id", "alarmId", "eventId", "event_id", "notificationId"),
    "timestamp": ("timestamp", "time", "eventTime", "event_time", "raisedTime",
                  "raised_time", "occurredAt", "occurred_at", "ts"),
    "node": ("node", "ne", "neName", "ne_name", "element", "managedElement",
             "source", "site", "host", "agentEntity"),
    "alarm_type": ("alarm_type", "alarmType", "type", "eventType", "event_type",
                   "name", "alarmName", "alarm_name"),
    "severity": ("severity", "perceivedSeverity", "perceived_severity", "sev"),
    "probable_cause": ("probable_cause", "probableCause", "cause"),
    "specific_problem": ("specific_problem", "specificProblem", "problem"),
    "managed_object": ("managed_object", "managedObject", "moi", "object",
                       "resource", "port", "cell"),
    "text": ("text", "additionalText", "additional_text", "description",
             "message", "details"),
}

# Map common severity spellings onto the X.733 enum.
_SEVERITY_MAP: dict[str, Severity] = {
    "critical": Severity.CRITICAL, "crit": Severity.CRITICAL, "5": Severity.CRITICAL,
    "major": Severity.MAJOR, "maj": Severity.MAJOR, "4": Severity.MAJOR,
    "minor": Severity.MINOR, "min": Severity.MINOR, "3": Severity.MINOR,
    "warning": Severity.WARNING, "warn": Severity.WARNING, "2": Severity.WARNING,
    "indeterminate": Severity.INDETERMINATE, "unknown": Severity.INDETERMINATE,
    "1": Severity.INDETERMINATE,
    "cleared": Severity.CLEARED, "clear": Severity.CLEARED,
    "normal": Severity.CLEARED, "0": Severity.CLEARED,
}


def _first_present(record: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in record and record[k] not in (None, ""):
            return record[k]
    return None


def parse_severity(value: Any) -> Severity:
    if value is None:
        return Severity.INDETERMINATE
    return _SEVERITY_MAP.get(str(value).strip().lower(), Severity.INDETERMINATE)


def parse_timestamp(value: Any) -> datetime:
    """Parse a range of timestamp formats; default to epoch-naive UTC on failure."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        # Treat large numbers as ms, otherwise seconds.
        seconds = value / 1000.0 if value > 1e11 else float(value)
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    if isinstance(value, str):
        v = value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S",
                        "%d-%m-%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
                try:
                    return datetime.strptime(value.strip(), fmt)
                except ValueError:
                    continue
    # Last resort: a fixed sentinel so sorting/grouping still works.
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def normalize_record(record: dict[str, Any], fallback_id: str) -> Alarm:
    raw: dict[str, Any] = {}
    for canonical, keys in _ALIASES.items():
        raw[canonical] = _first_present(record, keys)

    return Alarm(
        id=str(raw["id"]) if raw["id"] is not None else fallback_id,
        timestamp=parse_timestamp(raw["timestamp"]),
        node=str(raw["node"]) if raw["node"] else "UNKNOWN",
        alarm_type=str(raw["alarm_type"]) if raw["alarm_type"] else "UnknownAlarm",
        severity=parse_severity(raw["severity"]),
        probable_cause=_as_opt_str(raw["probable_cause"]),
        specific_problem=_as_opt_str(raw["specific_problem"]),
        managed_object=_as_opt_str(raw["managed_object"]),
        text=_as_opt_str(raw["text"]),
    )


def _as_opt_str(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def normalize_records(records: list[dict[str, Any]]) -> list[Alarm]:
    return [
        normalize_record(r, fallback_id=f"ALM-{i}")
        for i, r in enumerate(records)
    ]
