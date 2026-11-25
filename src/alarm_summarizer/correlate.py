"""Correlate deduplicated alarms into incidents.

Uses a simple, explainable union-find over alarm pairs. Two deduplicated
alarms are linked into the same incident when either:

  * they are on the same node, or
  * their active time windows are within `window_seconds` of each other AND
    they share a probable cause or alarm type (a likely common root event,
    e.g. a power or transport fault rippling across co-located nodes).

This deliberately errs toward a few meaningful incidents rather than many
singletons. The LLM layer then explains each incident; this layer just groups.
"""

from __future__ import annotations

from .models import DedupedAlarm, Incident


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _windows_overlap(a: DedupedAlarm, b: DedupedAlarm, window_seconds: float) -> bool:
    gap = max(
        a.first_seen.timestamp() - b.last_seen.timestamp(),
        b.first_seen.timestamp() - a.last_seen.timestamp(),
        0.0,
    )
    return gap <= window_seconds


def _share_cause(a: DedupedAlarm, b: DedupedAlarm) -> bool:
    ra, rb = a.representative, b.representative
    if ra.probable_cause and rb.probable_cause:
        if ra.probable_cause.strip().lower() == rb.probable_cause.strip().lower():
            return True
    return ra.alarm_type.strip().lower() == rb.alarm_type.strip().lower()


def correlate(
    deduped: list[DedupedAlarm], window_seconds: float = 300.0
) -> list[Incident]:
    """Group deduplicated alarms into incidents."""
    n = len(deduped)
    if n == 0:
        return []

    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            same_node = deduped[i].node == deduped[j].node
            related = _windows_overlap(deduped[i], deduped[j], window_seconds) and \
                _share_cause(deduped[i], deduped[j])
            if same_node or related:
                uf.union(i, j)

    clusters: dict[int, list[DedupedAlarm]] = {}
    for idx in range(n):
        clusters.setdefault(uf.find(idx), []).append(deduped[idx])

    incidents = [
        Incident(id=f"INC-{k+1:03d}", alarms=members)
        for k, members in enumerate(clusters.values())
    ]

    # Order incidents by severity, then event volume, then recency.
    from .models import severity_rank

    incidents.sort(
        key=lambda inc: (
            severity_rank(inc.severity),
            inc.total_events,
            inc.last_seen,
        ),
        reverse=True,
    )
    # Re-number after sorting so INC-001 is the top incident.
    for k, inc in enumerate(incidents):
        inc.id = f"INC-{k+1:03d}"
    return incidents
