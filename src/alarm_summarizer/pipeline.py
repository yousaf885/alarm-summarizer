"""End-to-end alarm summarization pipeline.

Stages:
  normalize -> deduplicate -> (drop standing-cleared) -> correlate -> summarize

Summarization uses Claude when enabled; on any failure (no key, network,
refusal) it falls back to the deterministic offline summary so the pipeline
always returns a handover note.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .correlate import correlate
from .dedup import deduplicate, drop_cleared
from .models import Alarm, Incident, ShiftSummary
from .normalize import normalize_records
from .offline import offline_summary
from .summarizer import LLMSummarizer, SummarizerConfig


@dataclass
class PipelineResult:
    summary: ShiftSummary
    incidents: list[Incident]
    method: str  # "llm" or "offline"
    error: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


class AlarmPipeline:
    def __init__(
        self,
        use_llm: bool = True,
        window_seconds: float = 300.0,
        flap_threshold: int = 3,
        keep_cleared: bool = False,
        config: SummarizerConfig | None = None,
        summarizer: LLMSummarizer | None = None,
    ):
        self.use_llm = use_llm
        self.window_seconds = window_seconds
        self.flap_threshold = flap_threshold
        self.keep_cleared = keep_cleared
        if use_llm:
            self.summarizer = summarizer or LLMSummarizer(config=config)
        else:
            self.summarizer = None

    def run(self, alarms: list[Alarm]) -> PipelineResult:
        deduped = deduplicate(alarms, flap_threshold=self.flap_threshold)
        if not self.keep_cleared:
            deduped = drop_cleared(deduped)
        incidents = correlate(deduped, window_seconds=self.window_seconds)

        stats = {
            "raw_alarms": len(alarms),
            "deduped_alarms": len(deduped),
            "incidents": len(incidents),
        }

        if not self.use_llm:
            return PipelineResult(
                summary=offline_summary(incidents),
                incidents=incidents,
                method="offline",
                stats=stats,
            )

        try:
            summary = self.summarizer.summarize(incidents)
            return PipelineResult(summary, incidents, method="llm", stats=stats)
        except Exception as exc:
            return PipelineResult(
                summary=offline_summary(incidents),
                incidents=incidents,
                method="offline",
                error=f"LLM summary failed, used offline fallback: {exc}",
                stats=stats,
            )

    def run_records(self, records: list[dict[str, Any]]) -> PipelineResult:
        return self.run(normalize_records(records))


# --- I/O helpers -----------------------------------------------------------


def load_alarm_records(path: str | Path) -> list[dict[str, Any]]:
    path = Path(path)
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in raw.splitlines() if line.strip()]
    data = json.loads(raw)
    return data if isinstance(data, list) else data.get("alarms", [])


def render_markdown(result: PipelineResult) -> str:
    """Render the summary as a shift-handover markdown note."""
    s = result.summary
    lines = [
        "# NOC Alarm Summary",
        "",
        f"**{s.headline}**",
        "",
        s.assessment,
        "",
        (
            f"_Processed {result.stats.get('raw_alarms', '?')} raw alarm(s) → "
            f"{result.stats.get('deduped_alarms', '?')} deduplicated → "
            f"{result.stats.get('incidents', '?')} incident(s). "
            f"Method: {result.method}._"
        ),
        "",
    ]
    if result.error:
        lines += [f"> ⚠️ {result.error}", ""]

    if not s.incidents:
        lines.append("_No active incidents._")
        return "\n".join(lines)

    lines.append("## Incidents")
    for item in s.incidents:
        lines += [
            "",
            f"### {item.incident_id} — {item.title}",
            f"- **Severity:** {item.severity.value}",
            f"- **Affected:** {item.affected_scope}",
            f"- **Probable root cause:** {item.probable_root_cause}",
            f"- **Recommended action:** {item.recommended_action}",
        ]
    return "\n".join(lines)
