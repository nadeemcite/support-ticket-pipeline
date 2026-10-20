"""CLI ``validate.py``: validate the artifacts on disk without running the pipeline (SPEC §2.1, §8).

Exit codes: 0 no failed checks (warnings allowed) · 1 at least one failed check · 2 the inputs are unusable
or the report can't be written. It makes no LLM or network call.
"""

import argparse
import sys
from pathlib import Path

from pipeline.config import ConfigError, load_config
from pipeline.loader import InputError
from pipeline.validation import REPORT, run_settings, validate

EXIT_OK, EXIT_FAILED, EXIT_FATAL = 0, 1, 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate pipeline artifacts (V01-V14)")
    parser.add_argument("--tickets", help="path to tickets.json (default: ./tickets.json)")
    parser.add_argument("--kb", help="path to kb_articles.json (default: ./kb_articles.json)")
    parser.add_argument("--out-dir", dest="out_dir", help="where the artifacts are (default: .)")
    parser.add_argument("--retriever", choices=("embedding", "tfidf"), help="sets the minimum retrieval score checked by V06")
    args = parser.parse_args(argv)
    try:
        config = load_config({k: v for k, v in vars(args).items() if v is not None}, dotenv_path=Path(".env"))
        # V06 checks against the settings the run used (its manifest), unless --retriever overrides them
        top_k, min_score = (None if args.retriever else run_settings(config.out_dir)) or (config.top_k, config.effective_min_score)
        report = validate(config.out_dir, config.tickets_path, config.kb_path, top_k, min_score)
    except (ConfigError, InputError, OSError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FATAL
    s = report["summary"]
    print(f"validation: {report['status']} ({s['passed']} passed, {s['failed']} failed, {s['warnings']} warnings) -> {config.out_dir / REPORT}")
    for check in report["checks"]:
        if check["status"] != "pass":
            print(f"  {check['id']} {check['name']}: {check['status']}")
            for detail in check["details"][:5]:
                print(f"    - {detail.get('ticket_id', '')} {detail['message']}".replace("-  ", "- "))
    return EXIT_OK if report["status"] == "pass" else EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
