"""Deterministic, offline summary — the fallback when no LLM is available.

Produces a `ShiftSummary` from correlated incidents using templates only, so
the pipeline always yields a usable handover note even with no API key or on
an API failure.
"""

from __future__ import annotations

from .models import Incident, IncidentSummary, ShiftSummary, Severity


def _scope(inc: Incident) -> str:
    nodes = inc.nodes
    if len(nodes) == 1:
        return f"node {nodes[0]}"
    return f"{len(nodes)} nodes: {', '.join(nodes[:5])}" + (
        " …" if len(nodes) > 5 else ""
    )


def _root_cause(inc: Incident) -> str:
    causes = {
        a.representative.probable_cause
        for a in inc.alarms
        if a.representative.probable_cause
    }
    if len(causes) == 1:
        return f"Likely: {next(iter(causes))} (keyword-based)."
    if causes:
        return "Multiple probable causes reported: " + ", ".join(sorted(causes)) + "."
    return "Insufficient information to determine a cause offline."


def _action(inc: Incident) -> str:
    if inc.severity in (Severity.CRITICAL, Severity.MAJOR):
        return f"Investigate {_scope(inc)} promptly; service impact likely."
    if any(a.flapping for a in inc.alarms):
        return f"Check {_scope(inc)} for an unstable/flapping condition."
    return f"Monitor {_scope(inc)}; low urgency."


def offline_summary(incidents: list[Incident]) -> ShiftSummary:
    if not incidents:
        return ShiftSummary(
            headline="No active incidents.",
            assessment="No actionable alarms after de-duplication and correlation.",
            incidents=[],
        )

    per_incident = [
        IncidentSummary(
            incident_id=inc.id,
            title=f"{inc.severity.value.upper()} on {_scope(inc)} "
            f"({inc.alarms[0].representative.alarm_type})",
            severity=inc.severity,
            affected_scope=_scope(inc),
            probable_root_cause=_root_cause(inc),
            recommended_action=_action(inc),
        )
        for inc in incidents
    ]

    crit = sum(1 for i in incidents if i.severity is Severity.CRITICAL)
    major = sum(1 for i in incidents if i.severity is Severity.MAJOR)
    headline = (
        f"{len(incidents)} incident(s): {crit} critical, {major} major."
    )
    assessment = (
        f"Deterministic offline summary. Prioritize the {crit + major} "
        f"critical/major incident(s). Totals reflect de-duplicated, correlated "
        f"alarms across {sum(len(i.nodes) for i in incidents)} node slot(s)."
    )
    return ShiftSummary(headline=headline, assessment=assessment, incidents=per_incident)
