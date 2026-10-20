"""Atomic writes and canonical hashing."""

import json
import os

import pytest

from pipeline import io_utils

pytestmark = pytest.mark.stage1


def test_atomic_write_creates_parents_and_round_trips(tmp_path):
    target = tmp_path / "a" / "b" / "out.json"
    io_utils.atomic_write_json(target, {"z": 1, "a": "é"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"z": 1, "a": "é"}
    assert "é" in target.read_text(encoding="utf-8")  # ensure_ascii=False


def test_simulated_crash_keeps_old_file_and_leaves_no_temp(tmp_path, monkeypatch):
    target = tmp_path / "out.json"
    io_utils.atomic_write_json(target, {"version": 1})

    def crash(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        io_utils.atomic_write_json(target, {"version": 2})
    assert json.loads(target.read_text()) == {"version": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_canonical_hash_stable_under_key_reordering():
    first = {"b": [1, {"y": 2, "x": 1}], "a": "é"}
    second = {"a": "é", "b": [1, {"x": 1, "y": 2}]}
    assert io_utils.canonical_json(first) == io_utils.canonical_json(second)
    assert io_utils.sha256_canonical(first) == io_utils.sha256_canonical(second)
    assert io_utils.sha256_canonical(first) != io_utils.sha256_canonical({**first, "a": "e"})


def test_sha256_file_matches_bytes(tmp_path):
    path = tmp_path / "f.txt"
    path.write_bytes(b"abc")
    assert io_utils.sha256_file(path) == io_utils.sha256_bytes(b"abc")
    assert io_utils.sha256_text("abc") == io_utils.sha256_bytes(b"abc")


def test_dump_json_is_deterministic():
    obj = {"k": [1, 2], "t": "x"}
    assert io_utils.dump_json(obj) == io_utils.dump_json(obj)
    assert io_utils.dump_json(obj).endswith("\n")


def test_artifact_parses(tmp_path):
    good = tmp_path / "good.json"
    good.write_text("{}")
    bad = tmp_path / "bad.json"
    bad.write_text("{")
    lines = tmp_path / "log.jsonl"
    lines.write_text('{"a": 1}\n\n{"b": 2}\n')
    bad_lines = tmp_path / "bad.jsonl"
    bad_lines.write_text('{"a": 1}\nnope\n')
    assert io_utils.artifact_parses(good)
    assert io_utils.artifact_parses(lines)
    assert not io_utils.artifact_parses(bad)
    assert not io_utils.artifact_parses(bad_lines)
    assert not io_utils.artifact_parses(tmp_path / "missing.json")
    io_utils.atomic_write_text(tmp_path / "empty.jsonl", "")
    assert io_utils.artifact_parses(tmp_path / "empty.jsonl")
