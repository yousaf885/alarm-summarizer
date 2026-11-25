"""Deduplicate alarms and detect flapping.

Alarms with the same signature (node + alarm_type + managed_object) are
collapsed into a single `DedupedAlarm` carrying an occurrence count and the
first/last time seen. A signature that both fires and clears repeatedly is
marked as *flapping* — a strong NOC signal that's easy to miss in a raw feed.
"""

from __future__ import annotations

from .models import Alarm, DedupedAlarm, Severity, severity_rank


def deduplicate(alarms: list[Alarm], flap_threshold: int = 3) -> list[DedupedAlarm]:
    """Collapse identical alarms; flag flapping signatures.

    Args:
        alarms: raw alarms (any order).
        flap_threshold: a signature seen at least this many times, with at
            least one CLEARED among them, is considered flapping.
    """
    groups: dict[tuple, list[Alarm]] = {}
    for alarm in alarms:
        groups.setdefault(alarm.signature(), []).append(alarm)

    deduped: list[DedupedAlarm] = []
    for events in groups.values():
        events.sort(key=lambda a: a.timestamp)
        first, last = events[0].timestamp, events[-1].timestamp

        # Representative = highest-severity, most recent active event.
        active = [e for e in events if e.severity is not Severity.CLEARED]
        pool = active or events
        representative = max(pool, key=lambda a: (severity_rank(a.severity), a.timestamp))

        has_clear = any(e.severity is Severity.CLEARED for e in events)
        flapping = len(events) >= flap_threshold and has_clear

        deduped.append(
            DedupedAlarm(
                representative=representative,
                count=len(events),
                first_seen=first,
                last_seen=last,
                flapping=flapping,
            )
        )

    # Most severe, then most recent, first.
    deduped.sort(
        key=lambda d: (severity_rank(d.severity), d.last_seen), reverse=True
    )
    return deduped


def drop_cleared(deduped: list[DedupedAlarm]) -> list[DedupedAlarm]:
    """Remove signatures whose representative is CLEARED and not flapping.

    A standing (not flapping) cleared alarm needs no attention, so it is noise
    in a shift summary. Flapping cleared alarms are kept — they matter.
    """
    return [
        d for d in deduped
        if d.severity is not Severity.CLEARED or d.flapping
    ]
