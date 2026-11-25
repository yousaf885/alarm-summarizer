"""Summarize correlated incidents with the Anthropic Claude API.

Uses structured outputs (`client.messages.parse(output_format=ShiftSummary)`)
so Claude returns a NOC shift-handover summary constrained to our schema:
a headline, an overall assessment, and a per-incident summary (title, scope,
probable root cause, recommended action) ordered most-urgent first.

Model default is `claude-opus-5-5`. For a lightweight recurring summary you
may prefer `claude-sonnet-5-5`; both are configurable via env vars.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .models import Incident, ShiftSummary

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"  # summarization benefits from a little more thought

_SYSTEM_PROMPT = """\
You are a telecom Network Operations Center (NOC) assistant writing a concise \
shift-handover summary from correlated alarm incidents.

You are given incidents that have already been de-duplicated and correlated \
(grouped) by a deterministic pre-processor. Do NOT re-group or invent alarms. \
For each incident, write a short, concrete summary; then give an overall \
assessment of the network state.

Guidelines:
- Order incidents most urgent first (severity, then customer/scope impact).
- `probable_root_cause`: infer the single most likely cause from the grouped \
alarms (e.g. a power failure causing co-located transmission alarms). Say \
"insufficient information" if the alarms don't support a specific cause.
- `recommended_action`: one concrete next step a NOC engineer should take.
- `affected_scope`: name the sites/nodes and, if evident, customer impact.
- Keep every field tight — this is a handover note, not a report.
- Use each incident's exact id in `incident_id`.
"""


@dataclass
class SummarizerConfig:
    model: str = DEFAULT_MODEL
    effort: str = DEFAULT_EFFORT
    max_tokens: int = 4096
    api_key: str | None = None

    @classmethod
    def from_env(cls) -> "SummarizerConfig":
        return cls(
            model=os.getenv("ALARM_MODEL", DEFAULT_MODEL),
            effort=os.getenv("ALARM_EFFORT", DEFAULT_EFFORT),
            max_tokens=int(os.getenv("ALARM_MAX_TOKENS", "4096")),
            api_key=os.getenv("ANTHROPIC_API_KEY") or None,
        )


class LLMSummarizer:
    def __init__(self, config: SummarizerConfig | None = None, client=None):
        self.config = config or SummarizerConfig.from_env()
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import anthropic

            self._client = (
                anthropic.Anthropic(api_key=self.config.api_key)
                if self.config.api_key
                else anthropic.Anthropic()
            )
        return self._client

    def summarize(self, incidents: list[Incident]) -> ShiftSummary:
        if not incidents:
            return ShiftSummary(
                headline="No active incidents.",
                assessment="No actionable alarms after de-duplication and correlation.",
                incidents=[],
            )

        blocks = "\n\n".join(inc.to_prompt_block() for inc in incidents)
        user_content = (
            f"Here are {len(incidents)} correlated incident(s) from the current "
            f"alarm feed. Summarize them for shift handover.\n\n{blocks}"
        )

        response = self.client.messages.parse(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            output_config={"effort": self.config.effort},
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
            output_format=ShiftSummary,
        )

        if getattr(response, "stop_reason", None) == "refusal":
            detail = getattr(response, "stop_details", None)
            raise RuntimeError(
                f"Model refused to summarize (category={getattr(detail, 'category', None)})."
            )

        result = response.parsed_output
        if result is None:  # pragma: no cover
            raise RuntimeError("Model returned no parseable structured output.")
        return result
