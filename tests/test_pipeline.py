"""Pipeline tests with offline mode and an injected fake summarizer."""

import json

from alarm_summarizer.models import IncidentSummary, Severity, ShiftSummary
from alarm_summarizer.pipeline import AlarmPipeline, load_alarm_records, render_markdown


def _records():
    return [
        {"id": "A1", "timestamp": "2026-11-24T08:00:00Z", "node": "N1",
         "alarmType": "MainsFailure", "perceivedSeverity": "critical", "probableCause": "power"},
        {"id": "A2", "timestamp": "2026-11-24T08:01:00Z", "node": "N1",
         "alarmType": "Rectifier", "perceivedSeverity": "major", "probableCause": "power"},
    ]


class FakeSummarizer:
    def __init__(self, raises=False):
        self.raises = raises
        self.calls = 0

    def summarize(self, incidents):
        self.calls += 1
        if self.raises:
            raise RuntimeError("simulated API failure")
        return ShiftSummary(
            headline="Fake headline.",
            assessment="Fake assessment.",
            incidents=[
                IncidentSummary(
                    incident_id=inc.id,
                    title="Fake incident",
                    severity=inc.severity,
                    affected_scope="N1",
                    probable_root_cause="power",
                    recommended_action="investigate",
                )
                for inc in incidents
            ],
        )


def test_offline_pipeline_produces_summary():
    pipe = AlarmPipeline(use_llm=False)
    result = pipe.run_records(_records())
    assert result.method == "offline"
    assert result.stats["incidents"] == 1
    assert result.summary.incidents
    assert result.summary.incidents[0].severity is Severity.CRITICAL


def test_llm_pipeline_uses_summarizer():
    fake = FakeSummarizer()
    pipe = AlarmPipeline(use_llm=True, summarizer=fake)
    result = pipe.run_records(_records())
    assert fake.calls == 1
    assert result.method == "llm"
    assert result.summary.headline == "Fake headline."


def test_llm_failure_falls_back_offline():
    fake = FakeSummarizer(raises=True)
    pipe = AlarmPipeline(use_llm=True, summarizer=fake)
    result = pipe.run_records(_records())
    assert result.method == "offline"
    assert result.error is not None
    assert "simulated API failure" in result.error


def test_render_markdown_contains_incident():
    pipe = AlarmPipeline(use_llm=False)
    result = pipe.run_records(_records())
    md = render_markdown(result)
    assert "# NOC Alarm Summary" in md
    assert "INC-001" in md


def test_empty_input_yields_no_incidents():
    pipe = AlarmPipeline(use_llm=False)
    result = pipe.run_records([])
    assert result.stats["incidents"] == 0
    assert "No active incidents" in result.summary.headline


def test_load_records_json(tmp_path):
    p = tmp_path / "a.json"
    p.write_text(json.dumps(_records()), encoding="utf-8")
    assert len(load_alarm_records(p)) == 2
