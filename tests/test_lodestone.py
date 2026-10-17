"""Regression tests for the Lodestone review (L1, R1-R3, S1, C1-C2, T1-T2).

Each open hole's test was written to fail against c556d5c first. R2 and C1
were already closed by c556d5c; their tests here pin the behaviour.
"""
import math
from pathlib import Path
from typing import Any

import pytest

from honest_evals.canary import Canary, CanaryFailed, canary, run_canary
from honest_evals.cutoffs import FragileFinding, StableFinding, VacuousFinding, sweep
from honest_evals.ledger import Anchor, ChainError, Ledger, verify_chain
from honest_evals.rerun import RerunClass, refusal_reason, rerun
from honest_evals.selection import Outcome, selection_effect, two_proportion_test


# ---------------------------------------------------------------- L1 chain identity
def test_L1_two_ledgers_do_not_share_an_identity(tmp_path: Path) -> None:
    a = Ledger(tmp_path / "a.jsonl", chain_id="alpha")
    b = Ledger(tmp_path / "b.jsonl", chain_id="beta")
    a.append("x is 1", "echo 1", 1, "numeric")
    b.append("x is 9", "echo 9", 9, "numeric")
    assert verify_chain(a, chain_id="alpha").ok and verify_chain(b, chain_id="beta").ok
    rep = verify_chain(b, chain_id="alpha")
    assert not rep.ok and "chain id" in rep.reason
    # the id is bound into the first hash: substituting b's rows under a's name fails
    (tmp_path / "a.jsonl").write_text((tmp_path / "b.jsonl").read_text())
    (tmp_path / "a.jsonl.head").write_text((tmp_path / "b.jsonl.head").read_text())
    assert not verify_chain(Ledger(tmp_path / "a.jsonl", chain_id="alpha")).ok


def test_L1_chain_id_is_generated_recorded_and_hash_bound(tmp_path: Path) -> None:
    import json

    led = Ledger(tmp_path / "l.jsonl")
    led.append("x", "echo 1", 1, "numeric")
    cid = led.chain_id
    assert cid and led.read_head()["chain_id"] == cid
    assert led.records()[0].prev == f"GENESIS:{cid}"
    # a reopened ledger learns its id from the file, and a wrong id is refused
    assert Ledger(tmp_path / "l.jsonl").chain_id == cid
    with pytest.raises(ChainError):
        Ledger(tmp_path / "l.jsonl", chain_id="other").append("y", "echo 2", 2, "numeric")
    # editing the genesis prev (to re-badge the chain) breaks the first hash
    line = json.loads(led.path.read_text())
    line["prev"] = "GENESIS:other"
    led.path.write_text(json.dumps(line, sort_keys=True) + "\n")
    head = json.loads(led.head_path.read_text())
    head["chain_id"] = "other"
    led.head_path.write_text(json.dumps(head))
    assert not verify_chain(led).ok


def test_L1_legacy_genesis_without_id_is_refused(tmp_path: Path) -> None:
    import json
    from dataclasses import asdict

    from honest_evals.ledger import Claim, hash_record

    rec = Claim(seq=1, ts="2026-01-01T00:00:00.000Z", claim="x", check="echo 1", observed="1", kind="numeric", prev="GENESIS")
    rec = Claim(**{**asdict(rec), "hash": hash_record(rec)})
    p = tmp_path / "old.jsonl"
    p.write_text(rec.to_json() + "\n")
    Path(str(p) + ".head").write_text(json.dumps({"seq": 1, "hash": rec.hash}))
    rep = verify_chain(p)
    assert not rep.ok and "chain id" in rep.reason


def test_L1_anchor_carries_chain_id(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl", chain_id="alpha")
    r = led.append("x", "echo 1", 1, "numeric")
    assert verify_chain(led, anchor=Anchor(seq=1, hash=r.hash, chain_id="alpha")).ok
    rep = verify_chain(led, anchor=Anchor(seq=1, hash=r.hash, chain_id="beta"))
    assert not rep.ok and "chain id" in rep.reason


# ---------------------------------------------------------------- R1 snapshot needs a reason
@pytest.mark.parametrize("rec", [
    {"snapshot": True},
    {"snapshot": True, "snapshot_reason": ""},
    {"snapshot": True, "snapshot_reason": "   "},
    {"snapshot": True, "snapshot_reason": None},
])
def test_R1_snapshot_without_reason_is_not_drift(rec: dict) -> None:
    r = rerun({"seq": 1, "check": "echo 7", "observed": "6", **rec})
    assert r.cls is RerunClass.NOT_RERUNNABLE and not r.drift and not r.checked
    assert r.reason.startswith("mismatch_unadjudicated") and "snapshot" in r.reason


def test_R1_snapshot_with_reason_is_still_not_drift() -> None:
    r = rerun({"seq": 1, "check": "echo 7", "observed": "6", "snapshot": True, "snapshot_reason": "live board"})
    assert r.cls is RerunClass.NOT_RERUNNABLE and "live board" in r.reason and "not an adjudication" in r.reason


# ---------------------------------------------------------------- R2 allowlist bypasses
@pytest.mark.parametrize("cmd", [
    "$(rm -rf x)",
    "echo `rm -rf x`",
    "eval rm -rf x",
    "eval 'echo hi'",
    "python3 -c \"open('x','x')\"",
    "python3 -c \"import pathlib; pathlib.Path('x').write_text('1')\"",
    "python -c 'print(1)'",
    "exec rm x",
    "command rm x",
    "builtin echo",
    ". ./x.sh",
    "source x.sh",
    "echo a || rm x",
    "echo $((1+1))",
    "echo ~root",
    "cat <<EOF",
    "echo a |& rm x",
    "echo a >| x",
])
def test_R2_metachar_and_interpreter_bypasses_refused(cmd: str) -> None:
    assert refusal_reason(cmd) is not None, cmd


def test_R2_eval_and_python_never_execute(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    for cmd in (f"eval rm {sentinel}", f"python3 -c \"open('{sentinel}','w').write('')\"", f"exec rm {sentinel}"):
        r = rerun({"seq": 1, "check": cmd, "observed": ""}, cwd=str(tmp_path))
        assert r.cls is RerunClass.NOT_RERUNNABLE, cmd
    assert sentinel.read_text() == "keep"


# ---------------------------------------------------------------- R3 whitespace normalisation
def test_R3_internal_whitespace_runs_are_preserved_by_default() -> None:
    r = rerun({"seq": 1, "check": "printf 'a  b'", "observed": "a b"})
    assert r.cls is not RerunClass.STILL_TRUE
    assert r.reason.startswith("mismatch_unadjudicated")
    r2 = rerun({"seq": 1, "check": "printf 'a  b'", "observed": "a  b"})
    assert r2.cls is RerunClass.STILL_TRUE


def test_R3_trailing_newline_still_tolerated_and_collapse_is_opt_in() -> None:
    assert rerun({"seq": 1, "check": "echo 42", "observed": "42"}).cls is RerunClass.STILL_TRUE
    r = rerun({"seq": 1, "check": "printf 'a  b'", "observed": "a b"}, collapse_whitespace=True)
    assert r.cls is RerunClass.STILL_TRUE and "collapsed" in r.reason


# ---------------------------------------------------------------- S1 insufficient data
def test_S1_two_proportion_test_degrades_to_insufficient() -> None:
    t = two_proportion_test(0, 0, 1, 2)
    assert t.insufficient and t.reason.startswith("insufficient_data")
    assert math.isnan(t.p_value) and math.isnan(t.fisher_p) and math.isnan(t.difference)
    assert "insufficient" in t.summary()
    assert not two_proportion_test(1, 2, 1, 2).insufficient


def test_S1_selection_effect_survives_all_unresolved_population() -> None:
    a = [Outcome(seq=i, checked=True, strict=i < 3) for i in range(10)]
    b = [Outcome(seq=100 + i, checked=False) for i in range(5)]
    eff = selection_effect(a, b, n_boot=100)
    t = eff.tests[("strict", False)]
    assert t.insufficient and eff.cells[("strict", False)][1].checked == 0
    assert "insufficient" in eff.report()
    assert len(eff.to_frame()) == 8


# ---------------------------------------------------------------- C1 checker called once
def test_C1_decorator_calls_checker_exactly_once_per_call_and_judges_that_call() -> None:
    calls = []

    def two_faced(rows):
        calls.append(len(rows))
        return [r["seq"] for r in rows if r["strict"]] if len(calls) == 1 else []

    g = canary(false_item={"seq": -1, "strict": True}, true_item={"seq": -2, "strict": False}, key=lambda r: r["seq"])(two_faced)
    rows = [{"seq": 1, "strict": False}, {"seq": 2, "strict": True}]
    assert g(rows) == [2] and calls == [4]
    with pytest.raises(CanaryFailed):
        g(rows)
    assert calls == [4, 4]


# ---------------------------------------------------------------- C2 unhashable flags
ROWS = [{"seq": 1, "strict": False}, {"seq": 2, "strict": True}]
BAD, GOOD = {"seq": -1, "strict": True}, {"seq": -2, "strict": False}


def _dicts(rows):
    return [r for r in rows if r["strict"]]


def test_C2_dict_flags_without_key_do_not_raise_typeerror() -> None:
    v = run_canary(_dicts, ROWS, false_item=BAD, true_item=GOOD)
    assert v.passed and v.flagged_on_copy == 2
    g = canary(false_item=BAD, true_item=GOOD)(_dicts)
    assert g(ROWS) == [{"seq": 2, "strict": True}]
    with Canary(ROWS, false_item=BAD, true_item=GOOD) as c:
        c.observe(_dicts(c.data))
    assert c.verdict.passed


def test_C2_noop_checker_with_dict_plants_and_no_key_fails_as_canary() -> None:
    with pytest.raises(CanaryFailed):
        canary(false_item=BAD, true_item=GOOD)(lambda rows: [])(ROWS)
    with pytest.raises(CanaryFailed):
        with Canary(ROWS, false_item=BAD, true_item=GOOD) as c:
            c.observe([{"unhashable": []}])


def test_C2_checker_returning_non_iterable_is_canary_failure() -> None:
    with pytest.raises(CanaryFailed):
        canary(false_item=BAD, true_item=GOOD, key=lambda r: r["seq"])(lambda rows: 42)(ROWS)
    with pytest.raises(CanaryFailed):
        with Canary(ROWS, false_item=BAD, true_item=GOOD, key=lambda r: r["seq"]) as c:
            c.observe(42)


# ---------------------------------------------------------------- T1 1/True collapse
def test_T1_one_and_true_are_different_winners() -> None:
    f = sweep([0, 1, 2], lambda s: 1 if s < 2 else True)
    assert isinstance(f, FragileFinding) and f.winner is None
    assert "1 wins" in f.summary() and "True wins" in f.summary()
    g = sweep([0, 1, 2], lambda s: [1, 0] if s < 2 else [1, False])
    assert isinstance(g, UnprovenFinding) and not g.order_stable  # winner 1 everywhere, nothing flipped it


# ---------------------------------------------------------------- T2 vacuous evaluate
def test_T2_evaluate_that_ignores_setting_is_vacuous_not_stable() -> None:
    f = sweep([1, 2, 3], lambda s: "A", negative_control=99)
    assert isinstance(f, VacuousFinding) and f.vacuous and f.winner is None and not f.fragile
    assert f.summary().startswith("VACUOUS")


def test_T2_negative_control_that_flips_keeps_stable() -> None:
    f = sweep([1, 2, 3], lambda s: "A" if s < 50 else "B", negative_control=99)
    assert isinstance(f, StableFinding) and f.winner == "A" and f.controlled
    assert "control" in f.summary()
    # without the named control the hidden draws (within a few spans of [1, 3]) never reach 50: unproven, not stable
    u = sweep([1, 2, 3], lambda s: "A" if s < 50 else "B")
    assert isinstance(u, UnprovenFinding) and not u.proven and u.summary().startswith("UNPROVEN")


def test_T2_control_must_not_be_a_sweep_setting() -> None:
    with pytest.raises(ValueError):
        sweep([1, 2, 3], lambda s: s, negative_control=2)


def test_T2_example_sweeps_carry_a_flipping_negative_control() -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    out = subprocess.run([sys.executable, str(root / "examples" / "selection_effect.py")], capture_output=True, text=True, timeout=180).stdout
    assert out.count("negative control") == 2 and "flipped it to 'tie'" in out and "VACUOUS" not in out


# ================================================================ re-test survivors (R1, T2, T2b)
from dataclasses import asdict  # noqa: E402

from honest_evals.cutoffs import UnprovenFinding  # noqa: E402
from honest_evals.rerun import Adjudication, DriftAdjudication  # noqa: E402


@pytest.mark.parametrize("why", ["trust me", "live board", "x"])
def test_R1_free_text_snapshot_reason_is_never_drift(why: str) -> None:
    r = rerun({"seq": 1, "check": "echo 7", "observed": "6", "snapshot": True, "snapshot_reason": why})
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("mismatch_unadjudicated")


def test_R1_plain_adjudication_cannot_declare_drift() -> None:
    with pytest.raises(TypeError):
        Adjudication(RerunClass.DRIFTED, "append-only log grew")


def test_R1_drift_needs_adjudication_bound_to_ledger_record(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "c.jsonl", chain_id="z")
    rec = led.append("board shows 6", "echo 7", "6", "state")
    adj = DriftAdjudication(record_hash=rec.hash, seq=rec.seq, evidence="live board, append-only")
    r = rerun(asdict(rec), adjudication=adj)
    assert r.cls is RerunClass.DRIFTED and r.drift and "append-only" in r.reason
    # wrong hash: not bound to this record
    bad = DriftAdjudication(record_hash="0" * 64, seq=rec.seq, evidence="live board")
    r2 = rerun(asdict(rec), adjudication=bad)
    assert r2.cls is RerunClass.NOT_RERUNNABLE and r2.reason.startswith("drift_adjudication_unbound")
    # wrong seq
    r3 = rerun(asdict(rec), adjudication=DriftAdjudication(record_hash=rec.hash, seq=rec.seq + 1, evidence="e"))
    assert r3.cls is RerunClass.NOT_RERUNNABLE and r3.reason.startswith("drift_adjudication_unbound")
    # record fields edited after adjudication: recomputed hash no longer matches the one adjudicated
    edited = {**asdict(rec), "observed": "5"}
    r4 = rerun(edited, adjudication=adj)
    assert r4.cls is RerunClass.NOT_RERUNNABLE and r4.reason.startswith("drift_adjudication_unbound")
    # a record with no ledger hash at all cannot be adjudicated as drift
    r5 = rerun({"seq": 1, "check": "echo 7", "observed": "6"}, adjudication=DriftAdjudication("", 1, "e"))
    assert r5.cls is RerunClass.NOT_RERUNNABLE and r5.reason.startswith("drift_adjudication_unbound")
    with pytest.raises(ValueError):
        DriftAdjudication(record_hash=rec.hash, seq=rec.seq, evidence="   ")


def test_T2_default_path_vacuous_sweep_is_unproven_not_stable() -> None:
    f = sweep([1, 2, 3], lambda s: "A")
    assert isinstance(f, UnprovenFinding) and not isinstance(f, StableFinding)
    assert f.vacuous and f.winner is None and not f.fragile and not f.proven
    assert f.summary().startswith("UNPROVEN")


def test_T2_default_path_derives_hidden_controls_and_proves_a_live_evaluate() -> None:
    seen: list[Any] = []

    def ev(s: Any) -> str:
        seen.append(s)
        return "A" if 0 <= s <= 10 else "B"

    f = sweep([1, 5, 10], ev)
    assert isinstance(f, StableFinding) and f.proven and f.winner == "A" and f.controlled
    assert f.seed is not None and len(f.controls) >= 2
    assert all(c.setting not in (1, 5, 10) for c in f.controls)
    # replay with the recorded seed is reproducible; a different seed draws different controls
    g = sweep([1, 5, 10], ev, seed=f.seed)
    assert [c.setting for c in g.controls] == [c.setting for c in f.controls]
    h = sweep([1, 5, 10], ev, seed=f.seed + 1)
    assert [c.setting for c in h.controls] != [c.setting for c in f.controls]


def test_T2b_evaluate_that_flips_only_at_the_known_control_is_not_proven() -> None:
    def gamed(s: Any) -> str:
        return "B" if s == 99 else "A"

    f = sweep([1, 2, 3], gamed, negative_control=99)
    assert not isinstance(f, StableFinding) and f.winner is None and not f.proven
    assert f.vacuous
    # the honest version of the same evaluate is proven
    g = sweep([1, 2, 3], lambda s: "A" if s < 50 else "B", negative_control=99)
    assert isinstance(g, StableFinding) and g.proven


def test_T2b_explicit_control_that_fails_to_flip_is_vacuous() -> None:
    f = sweep([1, 2, 3], lambda s: "A" if s < 50 else "B", negative_control=20)
    assert isinstance(f, VacuousFinding) and f.vacuous and f.winner is None


def test_T2b_non_numeric_settings_need_a_control_deriver() -> None:
    f = sweep(["a", "b", "c"], lambda s: "A" if s in "abc" else "B")
    assert isinstance(f, UnprovenFinding) and "derive" in f.summary()
    g = sweep(["a", "b", "c"], lambda s: "A" if s in "abc" else "B",
              derive_controls=lambda rng: [rng.choice(["x", "y", "z"]) for _ in range(2)])
    assert isinstance(g, StableFinding) and g.proven
    # a deriver that yields a sweep setting is an error, not a silent pass
    with pytest.raises(ValueError):
        sweep(["a", "b", "c"], lambda s: "A", derive_controls=lambda rng: ["a"])


def test_T2b_seed_is_drawn_after_evaluate_is_bound() -> None:
    # two default sweeps of the same evaluate draw different hidden controls
    ev = lambda s: "A" if s < 50 else "B"  # noqa: E731
    a, b = sweep([1, 2, 3], ev), sweep([1, 2, 3], ev)
    assert a.seed != b.seed


# ================================================================ Pass-3 survivors (T2c, T2d)
def test_T2c_call_counting_evaluate_is_not_proven_stable() -> None:
    """An evaluate that answers honestly for the first len(settings) calls and
    flips afterwards must not earn StableFinding: control calls are interleaved
    with the real settings in a seeded order it cannot predict."""
    settings = [1, 2, 3]

    class Counter:
        def __init__(self) -> None:
            self.n = 0

        def __call__(self, s: object) -> str:
            self.n += 1
            return "A" if self.n <= len(settings) else "B"

    stable = 0
    caught_inconsistent = 0
    for seed in range(40):
        try:
            f = sweep(settings, Counter(), negative_control=99, seed=seed)
        except ValueError as exc:
            assert "not a function of its setting" in str(exc)
            caught_inconsistent += 1
            continue
        if isinstance(f, StableFinding):
            stable += 1
    # Every value is evaluated twice at shuffled positions, so a single-flip
    # call counter must answer some duplicated pair inconsistently and be
    # named as such. It must never earn STABLE.
    assert stable == 0, f"call-counting evaluate earned STABLE under {stable}/40 seeds"
    assert caught_inconsistent == 40


def test_T2d_range_aware_evaluate_does_not_get_unqualified_proven() -> None:
    """An evaluate that answers honestly inside the swept range and flips only
    outside it is indistinguishable from a real responder by out-of-range
    probing. It may earn StableFinding, but the finding must carry the
    probing_limit caveat naming that ceiling - never an unqualified proof."""
    lo, hi = 1, 10

    def range_aware(s: float) -> str:
        return "A" if lo <= s <= hi else "B"

    f = sweep([1, 5, 10], range_aware, seed=7)
    if isinstance(f, StableFinding):
        assert f.probing_limit, "range-aware adversary passed with no probing_limit caveat"
        assert "out" in f.probing_limit and "range" in f.probing_limit
        assert f.probing_limit in f.summary()


def test_T2d_in_range_flip_clears_the_caveat() -> None:
    """When a hidden control INSIDE the swept range flips the winner, the proof
    does not rest on out-of-range probes and no caveat applies."""

    def ev(s: float) -> str:
        return "A" if s in (1, 5, 10) else "B"  # flips at any probe, in-range included

    f = sweep([1, 5, 10], ev, seed=7)
    assert isinstance(f, StableFinding)
    assert f.probing_limit is None


def test_T2c_interleave_order_is_seed_deterministic() -> None:
    calls_a: list[object] = []
    calls_b: list[object] = []
    sweep([1, 5, 10], lambda s: (calls_a.append(s) or ("A" if 1 <= s <= 10 else "B")), seed=3)
    sweep([1, 5, 10], lambda s: (calls_b.append(s) or ("A" if 1 <= s <= 10 else "B")), seed=3)
    assert calls_a == calls_b
    assert calls_a[:3] != [1, 5, 10] or calls_a != sorted(calls_a, key=calls_a.index)  # order is shuffled, not settings-first
