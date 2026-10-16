import json
from pathlib import Path

import pytest

from honest_evals.ledger import ChainError, Ledger, verify_chain


def _three(tmp_path: Path) -> Ledger:
    led = Ledger(tmp_path / "ledger.jsonl")
    led.append("a is 1", "echo 1", 1, "numeric")
    led.append("b exists", "test -e b", "yes", "existence")
    led.append("c is up", lambda: 200, 200, "state")
    return led


def test_append_and_verify(tmp_path: Path) -> None:
    led = _three(tmp_path)
    rows = led.records()
    assert [r.seq for r in rows] == [1, 2, 3]
    assert rows[0].prev == f"GENESIS:{led.chain_id}" and led.chain_id
    assert rows[1].prev == rows[0].hash
    assert rows[2].check.startswith("callable:")
    rep = verify_chain(led)
    assert rep.ok and rep.rows == 3 and rep.reason == "ok"


def test_empty_ledger_is_ok(tmp_path: Path) -> None:
    rep = verify_chain(tmp_path / "nothing.jsonl")
    assert rep.ok and rep.rows == 0


def test_edit_detected(tmp_path: Path) -> None:
    led = _three(tmp_path)
    lines = led.path.read_text().splitlines()
    rec = json.loads(lines[1])
    rec["observed"] = "no"  # tamper with a middle row, keep its hash
    lines[1] = json.dumps(rec, sort_keys=True)
    led.path.write_text("\n".join(lines) + "\n")
    rep = verify_chain(led)
    assert not rep.ok and rep.at_seq == 2 and "hash mismatch" in rep.reason


def test_meta_is_hash_bound(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.append("x", "echo x", "x", "state", meta={"verdict": "true"})
    rec = json.loads(led.path.read_text())
    rec["meta"]["verdict"] = "false"
    led.path.write_text(json.dumps(rec, sort_keys=True) + "\n")
    assert not verify_chain(led).ok


def test_truncation_detected(tmp_path: Path) -> None:
    """Negative control: dropping the last row leaves every internal link valid,
    so only the head check can catch it."""
    led = _three(tmp_path)
    lines = led.path.read_text().splitlines()
    led.path.write_text("\n".join(lines[:2]) + "\n")
    rep = verify_chain(led)
    assert not rep.ok
    assert "truncated" in rep.reason and rep.rows == 2


def test_truncate_to_zero_detected(tmp_path: Path) -> None:
    led = _three(tmp_path)
    led.path.write_text("")
    rep = verify_chain(led)
    assert not rep.ok and "truncated to zero" in rep.reason


def test_missing_head_is_not_ok(tmp_path: Path) -> None:
    led = _three(tmp_path)
    led.head_path.unlink()
    rep = verify_chain(led)
    assert not rep.ok and "head file missing" in rep.reason


def test_spliced_row_detected(tmp_path: Path) -> None:
    led = _three(tmp_path)
    lines = led.path.read_text().splitlines()
    lines.pop(1)  # remove a middle row; seq and prev both break
    led.path.write_text("\n".join(lines) + "\n")
    rep = verify_chain(led)
    assert not rep.ok and rep.at_seq == 3


def test_refuses_to_extend_broken_chain(tmp_path: Path) -> None:
    led = _three(tmp_path)
    lines = led.path.read_text().splitlines()
    led.path.write_text("\n".join(lines[:2]) + "\n")
    with pytest.raises(ChainError):
        led.append("d", "echo d", "d", "numeric")


def test_raise_on_fail(tmp_path: Path) -> None:
    led = _three(tmp_path)
    led.head_path.unlink()
    with pytest.raises(ChainError):
        verify_chain(led, raise_on_fail=True)
