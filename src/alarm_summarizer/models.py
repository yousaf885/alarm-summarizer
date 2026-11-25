"""Data models for alarms, deduplication, incidents, and summaries.

`IncidentSummary` and `ShiftSummary` double as the structured-output schema
handed to Claude via `client.messages.parse(output_format=...)`, so the model
is constrained to return exactly these fields.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Severity(str, Enum):
    """ITU-T X.733 perceived severity, the standard telecom alarm scale."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    WARNING = "warning"
    INDETERMINATE = "indeterminate"
    CLEARED = "cleared"


# Ordering so we can compute the "worst" severity in a group.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.MAJOR: 4,
    Severity.MINOR: 3,
    Severity.WARNING: 2,
    Severity.INDETERMINATE: 1,
    Severity.CLEARED: 0,
}


def severity_rank(sev: Severity) -> int:
    return _SEVERITY_RANK.get(sev, 1)


def max_severity(sevs: list[Severity]) -> Severity:
    if not sevs:
        return Severity.INDETERMINATE
    return max(sevs, key=severity_rank)


class Alarm(BaseModel):
    """A single alarm event. Only id/timestamp/node/alarm_type are required."""

    id: str
    timestamp: datetime
    node: str  # managed element / site / NE raising the alarm
    alarm_type: str  # e.g. "LinkDown", "PowerFail", "CellOutOfService"
    severity: Severity = Severity.INDETERMINATE
    probable_cause: Optional[str] = None  # X.733 probable cause if known
    specific_problem: Optional[str] = None
    managed_object: Optional[str] = None  # sub-object, e.g. a port or cell id
    text: Optional[str] = None  # free-text additional detail

    def signature(self) -> tuple[str, str, Optional[str]]:
        """Identity used for de-duplication / flap detection."""
        return (self.node, self.alarm_type, self.managed_object)

    def one_line(self) -> str:
        bits = [self.severity.value.upper(), self.node, self.alarm_type]
        if self.managed_object:
            bits.append(f"({self.managed_object})")
        if self.probable_cause:
            bits.append(f"- {self.probable_cause}")
        return " ".join(bits)


class DedupedAlarm(BaseModel):
    """A collapsed group of identical alarms (same signature)."""

    representative: Alarm
    count: int
    first_seen: datetime
    last_seen: datetime
    flapping: bool = False  # raised/cleared repeatedly

    @property
    def node(self) -> str:
        return self.representative.node

    @property
    def severity(self) -> Severity:
        return self.representative.severity


class Incident(BaseModel):
    """A correlated cluster of deduplicated alarms likely sharing a cause."""

    id: str
    alarms: list[DedupedAlarm]

    @property
    def nodes(self) -> list[str]:
        return sorted({a.node for a in self.alarms})

    @property
    def severity(self) -> Severity:
        return max_severity([a.severity for a in self.alarms])

    @property
    def first_seen(self) -> datetime:
        return min(a.first_seen for a in self.alarms)

    @property
    def last_seen(self) -> datetime:
        return max(a.last_seen for a in self.alarms)

    @property
    def total_events(self) -> int:
        return sum(a.count for a in self.alarms)

    def to_prompt_block(self) -> str:
        """Render the incident compactly for the model."""
        header = (
            f"Incident {self.id}: {len(self.alarms)} distinct alarm(s), "
            f"{self.total_events} event(s), nodes={self.nodes}, "
            f"severity={self.severity.value}, "
            f"window={self.first_seen.isoformat()}..{self.last_seen.isoformat()}"
        )
        lines = [header]
        for a in self.alarms:
            flap = " [flapping]" if a.flapping else ""
            lines.append(
                f"  - x{a.count}{flap} {a.representative.one_line()}"
                + (f" :: {a.representative.text}" if a.representative.text else "")
            )
        return "\n".join(lines)


# --- LLM structured-output schemas ----------------------------------------


class IncidentSummary(BaseModel):
    """Claude's summary of a single incident."""

    incident_id: str = Field(description="The incident id this summarizes.")
    title: str = Field(description="Short human-readable incident title.")
    severity: Severity = Field(description="Overall severity of the incident.")
    affected_scope: str = Field(
        description="What/where is affected (sites, nodes, customers)."
    )
    probable_root_cause: str = Field(
        description="Most likely root cause given the correlated alarms."
    )
    recommended_action: str = Field(
        description="Concrete next step for the NOC engineer."
    )


class ShiftSummary(BaseModel):
    """Claude's overall shift-handover summary across all incidents."""

    headline: str = Field(description="One-sentence state of the network.")
    assessment: str = Field(
        description="2-4 sentence overall assessment and priorities."
    )
    incidents: list[IncidentSummary] = Field(
        description="Per-incident summaries, most severe/urgent first."
    )
