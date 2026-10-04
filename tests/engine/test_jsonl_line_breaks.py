"""JSONL rows split on \\n only: U+2028/U+2029/U+0085 are legal inside strings."""
from __future__ import annotations

import json

import pytest

from engine import read_jsonl, write_jsonl
from engine import telemetry, upgrade_w3

BREAKS = [" ", " ", "\u0085", "\x0b", "\x0c", "\x1c"]


@pytest.mark.parametrize("ch", BREAKS)
def test_read_jsonl_round_trips_unicode_line_breaks(tmp_path, ch):
    rows = [{"id": "a", "text": f"left{ch}right"}, {"id": "b", "text": "x"}]
    path = tmp_path / "rows.jsonl"
    write_jsonl(path, rows)
    assert read_jsonl(path) == rows


def test_read_jsonl_tolerates_crlf(tmp_path):
    path = tmp_path / "rows.jsonl"
    path.write_bytes(b'{"a": 1}\r\n{"a": 2}\r\n')
    assert read_jsonl(path) == [{"a": 1}, {"a": 2}]


@pytest.mark.parametrize("ch", BREAKS)
def test_w3_readers_keep_rows_whole(tmp_path, ch):
    path = tmp_path / "durable.jsonl"
    write_jsonl(path, [{"text": f"a{ch}b"}])
    assert upgrade_w3._read_rows(tmp_path, path) == [{"text": f"a{ch}b"}]
    line = json.dumps({"text": f"a{ch}b"}, ensure_ascii=False)
    path.write_text(line + "\n", encoding="utf-8")
    assert upgrade_w3._lines(path) == [line]


@pytest.mark.parametrize("ch", BREAKS)
def test_telemetry_events_keep_rows_whole(tmp_path, ch):
    telemetry.emit(tmp_path, "gate", {"note": f"a{ch}b"})
    assert [e["meta"] for e in telemetry.load_events(tmp_path)] == [{"note": f"a{ch}b"}]
