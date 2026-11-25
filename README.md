# alarm-summarizer

An agent that turns a noisy telecom **alarm feed into a concise NOC shift-handover
summary** — de-duplicating floods, detecting flapping, correlating related alarms
into incidents, and explaining each one with the [Anthropic Claude API](https://platform.claude.com/).
A deterministic offline mode runs the whole pipeline (minus the LLM narrative)
with no API key.

```text
Processed 14 raw alarms → 7 deduplicated → 4 incidents

INC-001  CRITICAL  ABV-0117, ABV-TX-01   Power failure; microwave link down downstream
INC-002  MAJOR     LGOS-0423             Cell flapping (raised/cleared ×3)
INC-003  MINOR     KAN-0088              Elevated BER on microwave (×3, collapsed)
INC-004  WARNING   IBD-0331              Shelter over-temperature, HVAC degraded
```

## Pipeline

```
normalize → deduplicate → drop standing-cleared → correlate → summarize
```

| Stage | What it does | File |
|-------|--------------|------|
| **normalize** | Maps heterogeneous vendor/NMS field names onto one schema; parses many timestamp & severity formats | `normalize.py` |
| **deduplicate** | Collapses identical alarms (node + type + object), counts occurrences, flags **flapping** (repeated raise/clear) | `dedup.py` |
| **correlate** | Union-find grouping into incidents: same node, or same cause within a time window (catches a power fault rippling across co-located nodes) | `correlate.py` |
| **summarize** | Claude writes a per-incident + overall summary via **structured output** (`ShiftSummary` schema) | `summarizer.py` |
| **offline** | Deterministic templated summary — the fallback when no LLM is available | `offline.py` |

If the Claude call fails (no key, network, or a safety refusal), the pipeline
**falls back to the offline summary and records the error** — it always returns
a handover note. The deterministic stages (dedup/flap/correlate) run either way,
so the hard signal is never dependent on the model.

## Install

```bash
git clone https://github.com/yousaf885/alarm-summarizer.git
cd alarm-summarizer
python -m venv .venv && source .venv/bin/activate
pip install -e .            # add '.[dev]' for the test suite
```

Requires Python 3.10+.

## Credentials

```bash
cp .env.example .env        # then edit, or just export the var:
export ANTHROPIC_API_KEY=sk-ant-...
```

Or run `ant auth login` and skip the key — the SDK resolves credentials
automatically.

## Usage

```bash
# Summarize the bundled sample alarms with Claude:
alarm-summary data/sample_alarms.json

# Fully offline, deterministic — no key required:
alarm-summary data/sample_alarms.json --no-llm

# Markdown to a file, full structured result as JSON, wider correlation window:
alarm-summary alarms.jsonl -o summary.md --json result.json --window 600

# Keep standing cleared alarms; change the flap threshold:
alarm-summary alarms.json --keep-cleared --flap-threshold 5
```

Input is a JSON array (or `.jsonl`) of alarm records. Field names are flexible —
common aliases (`alarmId`/`eventId`, `eventTime`/`raisedTime`, `ne`/`neName`,
`perceivedSeverity`, `probableCause`, …) are all recognized. Minimum useful
record:

```json
{ "id": "A1", "timestamp": "2026-11-24T08:00:05Z", "node": "ABV-0117",
  "alarmType": "MainsFailure", "perceivedSeverity": "critical",
  "probableCause": "powerProblem", "additionalText": "AC mains lost" }
```

### As a library

```python
from alarm_summarizer import AlarmPipeline, render_markdown

pipeline = AlarmPipeline(use_llm=True)          # or use_llm=False for offline
result = pipeline.run_records(my_alarm_dicts)
print(render_markdown(result))
for inc in result.summary.incidents:
    print(inc.incident_id, inc.severity, inc.recommended_action)
```

## Configuration

| Env var | Default | Meaning |
|---------|---------|---------|
| `ANTHROPIC_API_KEY` | — | API key (or use `ant auth login`) |
| `ALARM_MODEL` | `claude-opus-5-5` | Model id (e.g. `claude-sonnet-5-5` for cheaper recurring runs) |
| `ALARM_EFFORT` | `medium` | Reasoning effort (`low`…`max`) |
| `ALARM_MAX_TOKENS` | `4096` | Output cap for the summary |

CLI tuning knobs: `--window` (correlation time window, seconds),
`--flap-threshold` (occurrences incl. a clear to call a signature flapping),
`--keep-cleared` (don't drop standing cleared alarms).

## Severity scale

Uses the ITU-T **X.733 perceived severity** scale:
`critical > major > minor > warning > indeterminate > cleared`.

## Tests

```bash
pip install -e '.[dev]'
pytest            # 18 tests, fully offline (LLM mocked)
```

## Project layout

```
src/alarm_summarizer/
  models.py      Alarm, DedupedAlarm, Incident, IncidentSummary, ShiftSummary
  normalize.py   heterogeneous records -> canonical Alarm
  dedup.py       de-duplication + flap detection
  correlate.py   union-find correlation into incidents
  summarizer.py  Claude summary (structured outputs)
  offline.py     deterministic offline summary (fallback)
  pipeline.py    orchestration + markdown/JSON rendering
  cli.py         `alarm-summary` entry point
data/            sample alarm feed
tests/           offline unit tests
```

## Scaling up

For continuous operation, point this at a stream and run it on a schedule
(e.g. per shift). For very large alarm volumes the correlation step is O(n²) in
distinct signatures after dedup — fine for thousands, but bucket by node/time
first if you push into the hundreds of thousands. If you'd rather Anthropic host
the agent loop (pull alarms, summarize, post to a channel), the same logic maps
onto [Claude Managed Agents](https://platform.claude.com/docs/en/build-with-claude/managed-agents).

## License

MIT — see [LICENSE](LICENSE).
