"""T3: stage order can't be bypassed (O1, O2) and unbuilt stages can't be claimed."""

import pytest

from pipeline.orchestrator import (
    MissingArtifactError,
    Pipeline,
    RunContext,
    Stage,
    StageMachine,
    StageNotImplementedError,
    StageOrderError,
    StageSpec,
)
from pipeline.runner import EXIT_FATAL, run
from pipeline.stages import build_specs
from tests.conftest import LATEST_STAGE, NEXT_UNBUILT

pytestmark = pytest.mark.stage1


def test_full_order_is_accepted():
    machine = StageMachine()
    for stage in Stage:
        machine.advance(stage)
    assert machine.current is Stage.RESULTS_FINALISED


def test_must_start_at_init():
    with pytest.raises(StageOrderError, match="expected INIT"):
        StageMachine().advance(Stage.INPUTS_LOADED)


@pytest.mark.parametrize("skip_to", [Stage.KB_INDEXED, Stage.RESPONSES_DRAFTED, Stage.RESULTS_FINALISED])
def test_skipping_raises(skip_to):
    machine = StageMachine()
    machine.advance(Stage.INIT)
    with pytest.raises(StageOrderError):
        machine.advance(skip_to)


def test_drafting_before_classification_raises():
    machine = StageMachine()
    for stage in list(Stage)[: Stage.EVIDENCE_RETRIEVED + 1]:
        machine.advance(stage)
    with pytest.raises(StageOrderError, match="expected TICKETS_CLASSIFIED"):
        machine.advance(Stage.RESPONSES_DRAFTED)


def test_repeating_or_going_back_raises():
    machine = StageMachine()
    machine.advance(Stage.INIT)
    machine.advance(Stage.INPUTS_LOADED)
    with pytest.raises(StageOrderError):
        machine.advance(Stage.INPUTS_LOADED)
    with pytest.raises(StageOrderError):
        machine.advance(Stage.INIT)


def test_nothing_after_finalised_or_failed():
    machine = StageMachine()
    for stage in Stage:
        machine.advance(stage)
    with pytest.raises(StageOrderError, match="finalised"):
        machine.require_next(Stage.INIT)
    failed = StageMachine()
    failed.fail()
    with pytest.raises(StageOrderError, match="FAILED"):
        failed.advance(Stage.INIT)


def test_pipeline_requires_every_stage_in_order():
    specs = build_specs()
    with pytest.raises(ValueError):
        Pipeline(specs[:-1])
    with pytest.raises(ValueError):
        Pipeline([specs[1], specs[0], *specs[2:]])


def _specs_with(stage: Stage, **changes) -> list[StageSpec]:
    specs = build_specs()
    original = specs[stage]
    specs[stage] = StageSpec(
        stage=stage,
        fn=changes.get("fn", original.fn),
        requires=changes.get("requires", original.requires),
        plan_stage=original.plan_stage,
    )
    return specs


def test_missing_required_artifact_blocks_stage(make_config):
    calls = []
    specs = _specs_with(Stage.TICKETS_NORMALISED, requires=("artifacts/does_not_exist.json",), fn=calls.append)
    pipeline = Pipeline(specs)
    with pytest.raises(MissingArtifactError, match="does_not_exist"):
        pipeline.run(RunContext(config=make_config()))
    assert calls == []  # the stage function never ran
    assert pipeline.machine.current is Stage.KB_INDEXED


def test_unparseable_required_artifact_blocks_stage(make_config):
    config = make_config()
    config.artifacts_dir.mkdir(parents=True)
    (config.artifacts_dir / "broken.json").write_text("{not json")
    pipeline = Pipeline(_specs_with(Stage.TICKETS_NORMALISED, requires=("artifacts/broken.json",)))
    with pytest.raises(MissingArtifactError):
        pipeline.run(RunContext(config=config))


@pytest.mark.skipif(NEXT_UNBUILT is None, reason="every stage is implemented")
def test_until_beyond_implemented_stage_is_refused(make_config):
    pipeline = Pipeline(build_specs())
    plan_stage = build_specs()[NEXT_UNBUILT].plan_stage
    with pytest.raises(StageNotImplementedError, match=f"PLAN Stage {plan_stage}"):
        pipeline.run(RunContext(config=make_config()), until=NEXT_UNBUILT)
    assert pipeline.machine.current is None  # refused before anything ran


def test_until_stops_early(make_config):
    pipeline = Pipeline(build_specs())
    ctx = RunContext(config=make_config())
    pipeline.run(ctx, until=Stage.INPUTS_LOADED)
    assert pipeline.machine.current is Stage.INPUTS_LOADED
    assert [s["stage"] for s in ctx.stage_trail] == ["INIT", "INPUTS_LOADED"]


def test_default_run_reaches_latest_implemented_stage(make_config):
    outcome = run(make_config())
    trail = outcome.manifest["stage_trail"]
    assert [s["stage"] for s in trail] == [stage.name for stage in Stage if stage <= LATEST_STAGE]
    assert not any(s["placeholder"] for s in trail)
    assert outcome.manifest["final_stage"] == LATEST_STAGE.name


def test_placeholder_stage_is_passed_through_and_marked(make_config):
    specs = _specs_with(Stage.INPUTS_LOADED)
    specs[Stage.INPUTS_LOADED] = StageSpec(Stage.INPUTS_LOADED, None, plan_stage=1)
    specs[Stage.INPUTS_LOADED + 1:] = [StageSpec(s.stage, None, plan_stage=s.plan_stage) for s in specs[Stage.INPUTS_LOADED + 1:]]
    specs[Stage.KB_INDEXED] = StageSpec(Stage.KB_INDEXED, lambda ctx: None, plan_stage=2)
    pipeline = Pipeline(specs)
    ctx = RunContext(config=make_config())
    pipeline.run(ctx)
    assert [(s["stage"], s["placeholder"]) for s in ctx.stage_trail] == [
        ("INIT", False), ("INPUTS_LOADED", True), ("KB_INDEXED", False)
    ]


@pytest.mark.skipif(NEXT_UNBUILT is None, reason="every stage is implemented")
def test_runner_reports_not_implemented_as_fatal(make_config):
    outcome = run(make_config(), until=NEXT_UNBUILT)
    assert outcome.exit_code == EXIT_FATAL
    assert outcome.manifest["final_stage"] == "FAILED"


def test_llm_stage_requires_credentials_unless_stub(make_config, monkeypatch):
    for var in ("OLLAMA_API_KEY", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    config = make_config(provider="ollama", model="glm-5.2")
    outcome = run(config, until=Stage.TICKETS_CLASSIFIED)
    assert outcome.exit_code == EXIT_FATAL and "OLLAMA_API_KEY" in outcome.error
    assert run(config, until=Stage.EVIDENCE_RETRIEVED).exit_code == 0  # no LLM stage in range -> no key needed
