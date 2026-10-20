"""Runs the pipeline and always writes ``artifacts/run_manifest.json``, even on failure."""

from dataclasses import dataclass

from pipeline.config import Config, ConfigError
from pipeline.io_utils import atomic_write_json
from pipeline.loader import InputError
from pipeline.orchestrator import (
    MissingArtifactError,
    Pipeline,
    RunContext,
    Stage,
    StageNotImplementedError,
    StageOrderError,
    build_manifest,
)
from pipeline.llm import LLMStageError
from pipeline.pii import PIILeakError
from pipeline.retrieval import EmbeddingError
from pipeline.stages import build_specs

MANIFEST = "artifacts/run_manifest.json"

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_FATAL = 2

FATAL_ERRORS = (
    ConfigError, InputError, StageOrderError, MissingArtifactError, StageNotImplementedError,
    PIILeakError, EmbeddingError, LLMStageError, OSError,
)

LLM_STAGES = (Stage.TICKETS_CLASSIFIED, Stage.RESPONSES_DRAFTED)


@dataclass
class RunOutcome:
    exit_code: int
    error: str | None
    manifest: dict
    context: RunContext


def run(config: Config, until: Stage | None = None) -> RunOutcome:
    pipeline = Pipeline(build_specs())
    ctx = RunContext(config=config)
    error: str | None = None
    exit_code = EXIT_OK
    try:
        target = pipeline.last_implemented() if until is None else until
        if config.provider != "stub" and any(stage <= target for stage in LLM_STAGES):
            config.require_credentials()
        if target >= Stage.KB_INDEXED:
            config.require_embedding_credentials()
        pipeline.run(ctx, until=until)
    except FATAL_ERRORS as exc:
        pipeline.machine.fail()
        error = f"{type(exc).__name__}: {exc}"
        exit_code = EXIT_FATAL
    manifest = build_manifest(ctx, pipeline, exit_code, error)
    try:
        atomic_write_json(ctx.path(MANIFEST), manifest)
    except OSError as exc:
        error = error or f"{type(exc).__name__}: {exc}"
        exit_code = EXIT_FATAL
    return RunOutcome(exit_code=exit_code, error=error, manifest=manifest, context=ctx)
