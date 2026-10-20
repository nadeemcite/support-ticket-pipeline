"""CLI entrypoint: ``python run_pipeline.py`` (SPEC §2.1). Exit codes: 0 ok, 1 validation failed, 2 fatal."""

import argparse
import sys
from pathlib import Path

from pipeline.config import PROVIDERS, ConfigError, load_config
from pipeline.orchestrator import Stage
from pipeline.runner import EXIT_FATAL, run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Support ticket triage pipeline")
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--model")
    parser.add_argument("--tickets", help="path to tickets.json (default: ./tickets.json)")
    parser.add_argument("--kb", help="path to kb_articles.json (default: ./kb_articles.json)")
    parser.add_argument("--out-dir", dest="out_dir", help="where artifacts are written (default: .)")
    parser.add_argument("--no-cache", dest="no_cache", action="store_true", default=None)
    parser.add_argument("--log-prompts", dest="log_prompts", action="store_true", default=None)
    parser.add_argument(
        "--until",
        choices=[stage.name for stage in Stage],
        help="stop after this stage (default: the latest implemented stage)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cli = {key: value for key, value in vars(args).items() if key != "until"}
    try:
        config = load_config(cli, dotenv_path=Path(".env"))
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FATAL

    outcome = run(config, until=Stage[args.until] if args.until else None)
    counts = outcome.manifest.get("counts", {})
    print(f"final stage: {outcome.manifest['final_stage']}  exit code: {outcome.exit_code}")
    if counts:
        print(
            f"tickets: {counts.get('tickets_accepted', 0)} accepted, {counts.get('tickets_rejected', 0)} rejected, "
            f"{counts.get('tickets_duplicate', 0)} duplicate · PII detections: {counts.get('pii_detections', {})}"
        )
    if outcome.error:
        print(f"error: {outcome.error}", file=sys.stderr)
    return outcome.exit_code


if __name__ == "__main__":
    sys.exit(main())
