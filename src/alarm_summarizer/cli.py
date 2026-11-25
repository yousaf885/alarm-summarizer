"""Command-line entry point for the alarm summarizer.

Examples:
    # Summarize the bundled sample alarms with Claude:
    alarm-summary data/sample_alarms.json

    # Offline, deterministic (no API key needed):
    alarm-summary data/sample_alarms.json --no-llm

    # JSON output + wider correlation window, keep cleared alarms:
    alarm-summary alarms.jsonl --json out.json --window 600 --keep-cleared
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .pipeline import AlarmPipeline, load_alarm_records, render_markdown
from .summarizer import SummarizerConfig


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="alarm-summary",
        description="De-duplicate, correlate, and summarize telecom alarms with Claude.",
    )
    p.add_argument("input", help="Path to alarms (.json list or .jsonl).")
    p.add_argument("--json", dest="json_out", help="Write the full result as JSON here.")
    p.add_argument("-o", "--output", help="Write the markdown summary here.")
    p.add_argument("--no-llm", action="store_true", help="Deterministic offline summary.")
    p.add_argument("--model", help="Model id (default: claude-opus-5-5).")
    p.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Reasoning effort (default: medium).",
    )
    p.add_argument(
        "--window",
        type=float,
        default=300.0,
        help="Correlation time window in seconds (default: 300).",
    )
    p.add_argument(
        "--flap-threshold",
        type=int,
        default=3,
        help="Occurrences (incl. a clear) to mark a signature flapping (default: 3).",
    )
    p.add_argument(
        "--keep-cleared",
        action="store_true",
        help="Keep standing cleared alarms (default: drop non-flapping cleared).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    records = load_alarm_records(args.input)
    if not records:
        print("No alarms found in input.", file=sys.stderr)
        return 1

    config = SummarizerConfig.from_env()
    if args.model:
        config.model = args.model
    if args.effort:
        config.effort = args.effort

    pipeline = AlarmPipeline(
        use_llm=not args.no_llm,
        window_seconds=args.window,
        flap_threshold=args.flap_threshold,
        keep_cleared=args.keep_cleared,
        config=config,
    )
    result = pipeline.run_records(records)

    markdown = render_markdown(result)
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown)

    if args.json_out:
        payload = {
            "method": result.method,
            "error": result.error,
            "stats": result.stats,
            "summary": result.summary.model_dump(mode="json"),
            "incidents": [inc.model_dump(mode="json") for inc in result.incidents],
        }
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    if result.error:
        print(f"\n{result.error}", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
