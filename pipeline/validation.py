"""Cross-artifact validation V01-V14 (SPEC §8). Re-reads everything from disk, calls no LLM.

``validate`` is the single implementation behind both the pipeline's ``OUTPUTS_VALIDATED`` stage and the
standalone ``validate.py``, so the two always agree (acceptance criterion A4). A check whose input artifact is
missing or unreadable reports ``fail`` with "artifact missing" rather than being skipped.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from pipeline import guards, pii
from pipeline.io_utils import atomic_write_json
from pipeline.language import is_supported, matches_language
from pipeline.loader import load_inputs
from pipeline.orchestrator import utc_now
from pipeline.schemas import Classification, DraftResponse, Escalation, GroundingFlag, LLMCallRecord, RetrievalResult
from pipeline.taxonomy import IssueType, ResolutionAction, TargetQueue, Urgency, values

REPORT = "validation_report.json"
LLM_REQUIRED_FIELDS = ("stage", "ticket_id", "timestamp", "provider", "model", "prompt_hash", "input_artifacts", "output_artifact")
LLM_PII_SKIP = frozenset({"prompt_hash", "timestamp"})  # hashes and timestamps are digit/hex runs, never customer text

# artifact key -> (file, top-level list key)
ARTIFACTS = {
    "retrieval": ("retrieval_results.json", "results"),
    "classification": ("ticket_classification.json", "classifications"),
    "drafts": ("draft_responses.json", "drafts"),
    "escalations": ("escalations.json", "escalations"),
}
OPTIONAL = {"grounding": ("grounding_flags.json", "flags")}
LLM_LOG = "llm_calls.jsonl"


@dataclass
class Check:
    id: str
    name: str
    severity: str  # "fail" or "warn": what a problem is reported as
    problems: list[dict[str, str]] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "pass" if not self.problems else self.severity

    def add(self, message: str, ticket_id: str | None = None) -> None:
        self.problems.append({"ticket_id": ticket_id, "message": message} if ticket_id else {"message": message})

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "status": self.status, "details": self.problems}


@dataclass
class Loaded:
    """Everything validation reads. A missing or unparsable artifact is ``None`` plus an entry in ``errors``."""

    data: dict[str, list[dict] | None] = field(default_factory=dict)
    llm: list[dict] | None = None
    errors: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    tickets: dict[str, dict] = field(default_factory=dict)  # accepted input tickets by id (language etc.)
    kb_ids: set[str] = field(default_factory=set)
    accepted_ids: list[str] = field(default_factory=list)


def _read_list(path: Path, key: str) -> tuple[list[dict] | None, str | None]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError) as exc:
        return None, f"unreadable: {type(exc).__name__}: {str(exc)[:120]}"
    items = payload.get(key) if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return None, f"unreadable: expected an object with a '{key}' list"
    return items, None


def load(out_dir: Path, tickets_path: Path, kb_path: Path) -> Loaded:
    loaded = Loaded()
    inputs = load_inputs(tickets_path, kb_path)  # InputError propagates: the inputs themselves are unusable
    loaded.accepted_ids = [t["ticket_id"] for t in inputs.tickets]
    loaded.tickets = {t["ticket_id"]: t for t in inputs.tickets}
    loaded.kb_ids = {a["article_id"] for a in inputs.articles}
    for name, (filename, key) in {**ARTIFACTS, **OPTIONAL}.items():
        items, error = _read_list(out_dir / filename, key)
        loaded.data[name] = items
        if error == "missing":
            if name in ARTIFACTS:
                loaded.missing.append(filename)
        elif error:
            loaded.errors[filename] = error
    log_path = out_dir / LLM_LOG
    if not log_path.is_file():
        loaded.missing.append(LLM_LOG)
    else:
        records: list[dict] = []
        try:
            for number, line in enumerate(log_path.read_text(encoding="utf-8").splitlines(), start=1):
                if line.strip():
                    records.append(json.loads(line))
            loaded.llm = records
        except (OSError, ValueError) as exc:
            loaded.errors[LLM_LOG] = f"line {number}: {type(exc).__name__}"
    return loaded


def _need(check: Check, loaded: Loaded, *names: str) -> bool:
    """Record "artifact missing" for each unavailable input; True when all are usable."""
    ok = True
    for name in names:
        unavailable = loaded.llm is None if name == "llm" else loaded.data.get(name) is None
        if unavailable:
            filename = LLM_LOG if name == "llm" else {**ARTIFACTS, **OPTIONAL}[name][0]
            check.add(f"artifact missing or unreadable: {filename}")
            ok = False
    return ok


def _ids(items: list[dict]) -> list[str]:
    return [str(item.get("ticket_id")) for item in items]


# --- checks ------------------------------------------------------------------------------------


def v01(c: Check, loaded: Loaded, tickets_path: Path, kb_path: Path) -> None:
    for path in (tickets_path, kb_path):
        if not path.is_file():
            c.add(f"required input missing: {path.name}")
    for filename in loaded.missing:
        c.add(f"required artifact missing: {filename}")


def v02(c: Check, loaded: Loaded) -> None:
    for filename, error in sorted(loaded.errors.items()):
        c.add(f"{filename} {error}")
    for index, record in enumerate(loaded.llm or [], start=1):
        absent = [f for f in LLM_REQUIRED_FIELDS if f not in record]
        if absent:
            c.add(f"{LLM_LOG} line {index} lacks {absent}", record.get("ticket_id"))


def v03(c: Check, loaded: Loaded) -> None:
    models = {"retrieval": RetrievalResult, "classification": Classification, "drafts": DraftResponse, "escalations": Escalation, "grounding": GroundingFlag}
    for name, model in models.items():
        for index, item in enumerate(loaded.data.get(name) or []):
            try:
                model.model_validate(item)
            except ValidationError as exc:
                first = exc.errors()[0]
                c.add(f"{({**ARTIFACTS, **OPTIONAL})[name][0]}[{index}] {'.'.join(str(p) for p in first['loc'])}: {first['msg']}", item.get("ticket_id") if isinstance(item, dict) else None)
    for index, record in enumerate(loaded.llm or [], start=1):
        try:
            LLMCallRecord.model_validate(record)
        except ValidationError as exc:
            c.add(f"{LLM_LOG} line {index}: {exc.errors()[0]['msg']}", record.get("ticket_id"))


def v04(c: Check, loaded: Loaded) -> None:
    expected = set(loaded.accepted_ids)
    for name in ARTIFACTS:
        items = loaded.data.get(name)
        if items is None:
            c.add(f"artifact missing or unreadable: {ARTIFACTS[name][0]}")
            continue
        ids = _ids(items)
        for dup in sorted({i for i in ids if ids.count(i) > 1}):
            c.add(f"{ARTIFACTS[name][0]}: duplicate ticket_id", dup)
        for missing in sorted(expected - set(ids)):
            c.add(f"{ARTIFACTS[name][0]}: ticket missing", missing)
        for extra in sorted(set(ids) - expected):
            c.add(f"{ARTIFACTS[name][0]}: unexpected ticket", extra)


def v05(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "classification"):
        return
    allowed = {"issue_type": values(IssueType), "urgency": values(Urgency), "resolution_action": values(ResolutionAction)}
    for item in loaded.data["classification"]:
        for key, labels in allowed.items():
            if item.get(key) not in labels:
                c.add(f"{key}={item.get(key)!r} is not in the taxonomy", item.get("ticket_id"))


def v06(c: Check, loaded: Loaded, top_k: int, min_score: float) -> None:
    if not _need(c, loaded, "retrieval"):
        return
    for item in loaded.data["retrieval"]:
        ticket_id, hits = item.get("ticket_id"), item.get("retrieved_articles") or []
        if len(hits) > top_k:
            c.add(f"{len(hits)} articles retrieved, limit is {top_k}", ticket_id)
        scores = [h.get("score", -1) for h in hits]
        if any(h.get("article_id") not in loaded.kb_ids for h in hits):
            c.add("retrieved article id is not in the knowledge base", ticket_id)
        if scores != sorted(scores, reverse=True):
            c.add("retrieved articles are not sorted by score", ticket_id)
        if any(not (min_score - 1e-9 <= s <= 1.0) for s in scores):
            c.add(f"score outside [{min_score}, 1]: {scores}", ticket_id)


def v07(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "retrieval", "drafts"):
        return
    retrieved = {r["ticket_id"]: {h["article_id"] for h in r.get("retrieved_articles") or []} for r in loaded.data["retrieval"] if "ticket_id" in r}
    for draft in loaded.data["drafts"]:
        foreign = [x for x in draft.get("citations") or [] if x not in retrieved.get(draft.get("ticket_id"), set())]
        if foreign:
            c.add(f"citations {foreign} were not retrieved for this ticket", draft.get("ticket_id"))


def v08(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "escalations"):
        return
    queues = values(TargetQueue)
    for item in loaded.data["escalations"]:
        queue = item.get("target_queue")
        if queue not in queues:
            c.add(f"target_queue={queue!r} is not in the taxonomy", item.get("ticket_id"))
        elif bool(item.get("escalate")) == (queue == TargetQueue.NONE):
            c.add(f"escalate={item.get('escalate')} with target_queue={queue} violates E-INV1", item.get("ticket_id"))


def v09(c: Check, loaded: Loaded) -> None:
    """A draft must look like the ticket's language. A language the pipeline does not support must be escalated (E6)."""
    if not _need(c, loaded, "drafts"):
        return
    escalations = _by_ticket(loaded.data.get("escalations") or [])
    for draft in loaded.data["drafts"]:
        ticket_id = draft.get("ticket_id")
        language = str(loaded.tickets.get(ticket_id, {}).get("language") or "en")
        if not is_supported(language):
            esc = escalations.get(str(ticket_id))
            if esc is None or not esc.get("escalate") or "E6" not in (esc.get("meta") or {}).get("rules_fired", []):
                c.add(f"language '{language}' is not supported but the ticket is not escalated by E6", ticket_id)
        elif matches_language(draft.get("draft_response", ""), language) is False:
            c.add(f"draft does not look like language '{language}'", ticket_id)


def _by_ticket(items: list[dict]) -> dict[str, dict]:
    return {str(i.get("ticket_id")): i for i in items}


def v10(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "classification", "drafts", "escalations"):
        return
    caution = {t for t, cls in _by_ticket(loaded.data["classification"]).items() if cls.get("requires_refund_caution")}
    for draft in loaded.data["drafts"]:
        text, ticket_id = draft.get("draft_response", ""), draft.get("ticket_id")
        if guards.s1_credential_request(text):
            c.add("draft asks for a credential (S1)", ticket_id)
        if ticket_id in caution and guards.s2_refund_promise(text):
            c.add("draft promises a refund where caution is required (S2)", ticket_id)
    for esc in loaded.data["escalations"]:
        if esc.get("ticket_id") in caution and guards.s2_refund_promise(esc.get("reason", "")):
            c.add("escalation reason matches S2 where refund caution is required", esc.get("ticket_id"))


def v11(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "classification", "drafts", "escalations"):
        return
    drafts, escalations = _by_ticket(loaded.data["drafts"]), _by_ticket(loaded.data["escalations"])
    for cls in loaded.data["classification"]:
        if cls.get("resolution_action") != ResolutionAction.NEEDS_HUMAN_ESCALATION:
            continue
        ticket_id = cls.get("ticket_id")
        draft = drafts.get(ticket_id)
        if draft is not None and not guards.s3_escalation_mention(draft.get("draft_response", "")):
            c.add("action is needs_human_escalation but the draft does not mention escalation (S3)", ticket_id)
        esc = escalations.get(ticket_id)
        if esc is not None and not esc.get("escalate"):
            c.add("action is needs_human_escalation but escalate is false", ticket_id)


def v12(c: Check, loaded: Loaded) -> None:
    for flag in loaded.data.get("grounding") or []:
        c.add(f"unsupported claim ({flag.get('check')}): {', '.join(flag.get('unsupported_tokens') or [])}", flag.get("ticket_id"))
    if loaded.llm is None:
        c.add(f"artifact missing or unreadable: {LLM_LOG}")
        return
    expected = set(loaded.accepted_ids)
    for stage in ("classification", "drafting"):
        covered = {r.get("ticket_id") for r in loaded.llm if r.get("stage") == stage and r.get("status") == "ok"}
        if stage == "drafting":  # unsupported-language tickets get a template and no model call (E6)
            covered |= {t for t in expected if not is_supported(str(loaded.tickets.get(t, {}).get("language") or "en"))}
        for ticket_id in sorted(expected - covered):
            c.add(f"no successful {stage} call in {LLM_LOG}", ticket_id)


def v13(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "drafts", "escalations", "llm"):
        return
    for draft in loaded.data["drafts"]:
        if pii.contains_pii(draft.get("draft_response", "")):
            c.add("draft contains PII", draft.get("ticket_id"))
    for esc in loaded.data["escalations"]:
        if pii.contains_pii(esc.get("reason", "")):
            c.add("escalation reason contains PII", esc.get("ticket_id"))
    for index, record in enumerate(loaded.llm, start=1):
        text = " ".join(str(v) for k, v in record.items() if k not in LLM_PII_SKIP and isinstance(v, (str, list)))
        if pii.contains_pii(text):
            c.add(f"{LLM_LOG} line {index} contains PII", record.get("ticket_id"))


def v14(c: Check, loaded: Loaded) -> None:
    if not _need(c, loaded, "drafts", "escalations"):
        return
    for draft in loaded.data["drafts"]:
        if pii.contains_placeholder(draft.get("draft_response", "")):
            c.add("draft contains a [TYPE_n] placeholder", draft.get("ticket_id"))
    for esc in loaded.data["escalations"]:
        if pii.contains_placeholder(esc.get("reason", "")):
            c.add("escalation reason contains a [TYPE_n] placeholder", esc.get("ticket_id"))


# --- driver ------------------------------------------------------------------------------------


def build_report(checks: list[Check], tickets: int) -> dict[str, Any]:
    statuses = [c.status for c in checks]
    return {
        "generated_at": utc_now(),
        "status": "fail" if "fail" in statuses else "pass",
        "summary": {
            "checks": len(checks),
            "passed": statuses.count("pass"),
            "failed": statuses.count("fail"),
            "warnings": statuses.count("warn"),
            "tickets": tickets,
        },
        "checks": [c.as_dict() for c in checks],
    }


def run_settings(out_dir: Path) -> tuple[int, float] | None:
    """``(top_k, min_score)`` the run actually used, from its manifest; None when there is no readable manifest."""
    try:
        config = json.loads((Path(out_dir) / "artifacts" / "run_manifest.json").read_text(encoding="utf-8"))["config"]
        return int(config["top_k"]), float(config["min_score"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def validate(out_dir: Path, tickets_path: Path, kb_path: Path, top_k: int = 3, min_score: float = 0.0, write: bool = True) -> dict[str, Any]:
    """Run V01-V14 against the artifacts in ``out_dir``. Raises ``InputError`` when the inputs themselves are unusable."""
    loaded = load(Path(out_dir), Path(tickets_path), Path(kb_path))
    plain: list[tuple[str, str, str, Callable[..., None], tuple]] = [
        ("V01", "required_artifacts_exist", "fail", v01, (Path(tickets_path), Path(kb_path))),
        ("V02", "json_parses", "fail", v02, ()),
        ("V03", "schemas_match", "fail", v03, ()),
        ("V04", "ticket_coverage", "fail", v04, ()),
        ("V05", "classification_in_taxonomy", "fail", v05, ()),
        ("V06", "retrieval_contract", "fail", v06, (top_k, min_score)),
        ("V07", "citations_subset_of_retrieved", "fail", v07, ()),
        ("V08", "escalation_invariant", "fail", v08, ()),
        ("V09", "draft_language_matches_ticket", "fail", v09, ()),
        ("V10", "no_credential_requests_or_refund_promises", "fail", v10, ()),
        ("V11", "escalation_consistency", "fail", v11, ()),
        ("V12", "grounding_flags_and_llm_log_coverage", "warn", v12, ()),
        ("V13", "no_pii_leakage", "fail", v13, ()),
        ("V14", "no_placeholder_leakage", "fail", v14, ()),
    ]
    checks = []
    for check_id, name, severity, fn, extra in plain:
        check = Check(check_id, name, severity)
        fn(check, loaded, *extra)
        if check.problems and any(p["message"].startswith(("artifact missing", "required")) for p in check.problems):
            check.severity = "fail"  # a missing artifact is always a failure, even for warn-level checks
        checks.append(check)
    report = build_report(checks, len(loaded.accepted_ids))
    if write:
        atomic_write_json(Path(out_dir) / REPORT, report)
    return report
