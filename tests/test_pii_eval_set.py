"""PII detection on the eval set matches gold.pii_expected, and nothing raw survives normalisation."""

import json

import pytest

from pipeline import pii
from pipeline.config import DEFAULT_PII_SALT
from pipeline.loader import load_inputs
from pipeline.normalise import normalise_tickets
from pipeline.runner import run
from tests.conftest import EVAL

pytestmark = pytest.mark.stage1

GOLD = {g["ticket_id"]: g for g in json.loads((EVAL / "gold.json").read_text())["expectations"]}
RAW = {t["ticket_id"]: t for t in json.loads((EVAL / "tickets.json").read_text())["tickets"]}


@pytest.fixture(scope="module")
def normalised():
    loaded = load_inputs(EVAL / "tickets.json", EVAL / "kb_articles.json")
    return {t.ticket_id: t for t in normalise_tickets(loaded.tickets, 4000, DEFAULT_PII_SALT)}


@pytest.mark.parametrize("ticket_id", list(GOLD))
def test_detected_types_match_gold(normalised, ticket_id):
    detected = sorted(item.type.value for item in normalised[ticket_id].pii_summary.items)
    assert detected == sorted(GOLD[ticket_id]["pii_expected"])


@pytest.mark.parametrize("ticket_id", list(GOLD))
def test_no_raw_pii_in_normalised_ticket(normalised, ticket_id):
    serialised = normalised[ticket_id].model_dump_json()
    assert not pii.contains_pii(normalised[ticket_id].subject + " " + normalised[ticket_id].message)
    raw_text = RAW[ticket_id]["subject"] + " " + RAW[ticket_id]["message"]
    for detection in pii.detect(raw_text):
        assert detection.value not in serialised


def test_normalised_artifact_on_disk_has_no_raw_pii(make_config):
    config = make_config(tickets=EVAL / "tickets.json", kb=EVAL / "kb_articles.json")
    outcome = run(config)
    assert outcome.exit_code == 0
    artifact = (config.artifacts_dir / "normalised_tickets.json").read_text()
    manifest = (config.artifacts_dir / "run_manifest.json").read_text()
    raw_values = [d.value for t in RAW.values() for d in pii.detect(t["subject"] + " " + t["message"])]
    assert raw_values, "eval set is expected to contain synthetic PII"
    for value in raw_values:
        assert value not in artifact and value not in manifest
    assert outcome.manifest["counts"]["pii_detections"] == {"card_number": 1, "credential": 1, "email": 2, "iban": 1, "phone": 1}
