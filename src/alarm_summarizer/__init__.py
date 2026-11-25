"""alarm-summarizer: de-duplicate, correlate, and summarize telecom alarms with Claude."""

from .correlate import correlate
from .dedup import deduplicate, drop_cleared
from .models import (
    Alarm,
    DedupedAlarm,
    Incident,
    IncidentSummary,
    Severity,
    ShiftSummary,
)
from .normalize import normalize_records
from .offline import offline_summary
from .pipeline import AlarmPipeline, PipelineResult, load_alarm_records, render_markdown
from .summarizer import LLMSummarizer, SummarizerConfig

__version__ = "0.1.0"

__all__ = [
    "Alarm",
    "DedupedAlarm",
    "Incident",
    "IncidentSummary",
    "Severity",
    "ShiftSummary",
    "deduplicate",
    "drop_cleared",
    "correlate",
    "normalize_records",
    "offline_summary",
    "AlarmPipeline",
    "PipelineResult",
    "load_alarm_records",
    "render_markdown",
    "LLMSummarizer",
    "SummarizerConfig",
    "__version__",
]
