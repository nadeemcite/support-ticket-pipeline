"""Stage machine and run loop (DESIGN §4.1, SPEC §5, rules O1-O4).

* ``StageMachine.advance`` only permits ``current + 1`` (O1).
* A stage runs only when every artifact it requires exists and parses (O2).
* Stages receive typed objects from earlier stages through ``RunContext``, never globals.
* Stages not built yet are registered as placeholders. A run may pass through a placeholder
  that produces nothing later stages need, but ``--until`` can't go past the last implemented
  stage, so the pipeline never claims work it didn't do.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import IntEnum
from pathlib import Path
from typing import Any

from pipeline import PIPELINE_VERSION
from pipeline.config import Config
from pipeline.io_utils import artifact_parses


class Stage(IntEnum):
    INIT = 0
    INPUTS_LOADED = 1
    KB_INDEXED = 2
    TICKETS_NORMALISED = 3
    EVIDENCE_RETRIEVED = 4
    TICKETS_CLASSIFIED = 5
    RESPONSES_DRAFTED = 6
    ESCALATIONS_DECIDED = 7
    OUTPUTS_VALIDATED = 8
    RESULTS_FINALISED = 9


class StageOrderError(RuntimeError):
    """A stage was entered out of order. Always a programming bug (exit 2)."""


class MissingArtifactError(RuntimeError):
    """A stage's required artifact is missing or doesn't parse (O2)."""


class StageNotImplementedError(RuntimeError):
    """``--until`` asked for a stage that isn't built yet."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class StageMachine:
    def __init__(self) -> None:
        self.current: Stage | None = None
        self.failed: bool = False

    def expected_next(self) -> Stage:
        return Stage.INIT if self.current is None else Stage(self.current + 1)

    def require_next(self, stage: Stage) -> None:
        if self.failed:
            raise StageOrderError(f"cannot enter {stage.name}: run already FAILED")
        if self.current == Stage.RESULTS_FINALISED:
            raise StageOrderError(f"cannot enter {stage.name}: run already finalised")
        if stage != self.expected_next():
            current = "start" if self.current is None else self.current.name
            raise StageOrderError(f"cannot enter {stage.name} from {current}; expected {self.expected_next().name}")

    def advance(self, stage: Stage) -> None:
        self.require_next(stage)
        self.current = stage

    def fail(self) -> None:
        self.failed = True


@dataclass(frozen=True)
class StageSpec:
    stage: Stage
    fn: Callable[["RunContext"], None] | None
    requires: tuple[str, ...] = ()
    plan_stage: int = 1

    @property
    def placeholder(self) -> bool:
        return self.fn is None


@dataclass
class RunContext:
    config: Config
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    started_at: str = field(default_factory=utc_now)
    data: dict[str, Any] = field(default_factory=dict)  # typed outputs handed from stage to stage
    manifest: dict[str, Any] = field(default_factory=dict)  # facts recorded for run_manifest.json
    stage_trail: list[dict[str, Any]] = field(default_factory=list)
    entering: Stage | None = None  # the stage whose function is running (LLM stage guard, O3)

    def path(self, relative: str) -> Path:
        return self.config.out_dir / relative


class Pipeline:
    def __init__(self, specs: list[StageSpec]) -> None:
        stages = [spec.stage for spec in specs]
        if stages != list(Stage):
            raise ValueError("pipeline must register every Stage exactly once, in order")
        self.specs = specs
        self.machine = StageMachine()

    def last_implemented(self) -> Stage:
        last = Stage.INIT
        for spec in self.specs:
            if not spec.placeholder:
                last = spec.stage
        return last

    def run(self, ctx: RunContext, until: Stage | None = None) -> None:
        until = self.last_implemented() if until is None else until
        if until > self.last_implemented():
            spec = self.specs[until]
            raise StageNotImplementedError(
                f"{until.name} is not implemented yet (PLAN Stage {spec.plan_stage}); "
                f"latest available stage is {self.last_implemented().name}"
            )
        for spec in self.specs[: until + 1]:
            self.machine.require_next(spec.stage)
            missing = [rel for rel in spec.requires if not artifact_parses(ctx.path(rel))]
            if missing:
                raise MissingArtifactError(f"{spec.stage.name} requires {', '.join(missing)}")
            entered_at = utc_now()
            start = time.perf_counter()
            if spec.fn is not None:
                ctx.entering = spec.stage
                try:
                    spec.fn(ctx)
                finally:
                    ctx.entering = None
            self.machine.advance(spec.stage)
            ctx.stage_trail.append(
                {
                    "stage": spec.stage.name,
                    "entered_at": entered_at,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 3),
                    "placeholder": spec.placeholder,
                }
            )

    @property
    def final_stage(self) -> str:
        if self.machine.failed:
            return "FAILED"
        return "NONE" if self.machine.current is None else self.machine.current.name


def build_manifest(ctx: RunContext, pipeline: Pipeline, exit_code: int, error: str | None) -> dict[str, Any]:
    return {
        "run_id": ctx.run_id,
        "pipeline_version": PIPELINE_VERSION,
        "started_at": ctx.started_at,
        "finished_at": utc_now(),
        "status": "failed" if error else "ok",
        "exit_code": exit_code,
        "error": error,
        "final_stage": pipeline.final_stage,
        "config": ctx.config.public_dict(),
        **ctx.manifest,
        "stage_trail": ctx.stage_trail,
    }
