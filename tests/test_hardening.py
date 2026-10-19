"""Regression tests for holes found in review. Each was written to fail first.

No destructive command is ever executed here: refusal is checked with
``refusal_reason`` (pure), and the one ``rerun`` call targets a sentinel file
in a pytest tmp dir that must survive.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from honest_evals.canary import Canary, CanaryFailed, canary, run_canary
from honest_evals.ledger import Anchor, ChainError, Claim, Ledger, canonical_material, verify_chain
from honest_evals.rerun import RerunClass, refusal_reason, rerun

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------- (1) ledger
def test_ledger_canonical_encoding_has_no_delimiter_collision() -> None:
    base = dict(seq=1, ts="2026-01-01T00:00:00.000Z", check="echo", observed="x", kind="k", prev="GENESIS")
    a = Claim(claim="a\x1fb", **{**base, "check": "c"})
    b = Claim(claim="a", **{**base, "check": "b\x1fc"})
    assert canonical_material(a) != canonical_material(b)


def test_ledger_rejects_backdated_append(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.append("x", "echo 1", 1, "numeric", ts="2026-02-01T00:00:00.000Z")
    with pytest.raises(ChainError):
        led.append("y", "echo 2", 2, "numeric", ts="2026-01-01T00:00:00.000Z")


def test_ledger_verify_flags_backdated_row(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.append("x", "echo 1", 1, "numeric", ts="2026-02-01T00:00:00.000Z")
    # write a backdated row with a self-consistent hash and head, bypassing append
    from dataclasses import asdict
    from honest_evals.ledger import hash_record
    prev = led.records()[-1]
    rec = Claim(seq=2, ts="2026-01-01T00:00:00.000Z", claim="y", check="echo 2", observed="2", kind="numeric", prev=prev.hash)
    rec = Claim(**{**asdict(rec), "hash": hash_record(rec)})
    with led.path.open("a") as fh:
        fh.write(rec.to_json() + "\n")
    led._write_head(rec)
    rep = verify_chain(led)
    assert not rep.ok and "timestamp" in rep.reason and rep.at_seq == 2


def test_ledger_rejects_unparseable_timestamp(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    with pytest.raises(ChainError):
        led.append("x", "echo 1", 1, "numeric", ts="yesterday")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_ledger_full_rewrite_caught_by_external_anchor(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    led = Ledger(repo / "l.jsonl")
    led.append("a is 1", "echo 1", 1, "numeric")
    led.append("b is 2", "echo 2", 2, "numeric")
    _git(repo, "add", "l.jsonl", "l.jsonl.head")
    _git(repo, "commit", "-qm", "anchor")
    sha = _git(repo, "rev-parse", "HEAD")
    anchor = Anchor.from_git(repo, sha, "l.jsonl.head")
    assert verify_chain(led, anchor=anchor).ok

    # attacker rewrites the whole chain (and head) consistently after the fact
    led.path.unlink()
    led.head_path.unlink()
    led.append("a is 9", "echo 9", 9, "numeric")
    led.append("b is 2", "echo 2", 2, "numeric")
    assert verify_chain(led).ok  # internally consistent: no anchor cannot catch it
    rep = verify_chain(led, anchor=anchor)
    assert not rep.ok and "anchor" in rep.reason


def test_ledger_anchor_on_truncated_chain_fails(tmp_path: Path) -> None:
    led = Ledger(tmp_path / "l.jsonl")
    led.append("a", "echo 1", 1, "numeric")
    anchor = Anchor(seq=5, hash="0" * 64, commit="deadbeef")
    rep = verify_chain(led, anchor=anchor)
    assert not rep.ok and "anchor" in rep.reason


# ---------------------------------------------------------------- (2) rerun allowlist
@pytest.mark.parametrize(
    "cmd",
    [
        "$(printf rm) -rf x",
        "`printf rm` -rf x",
        "echo $(printf rm)",
        "git branch -D main",
        "git branch --delete main",
        "git branch -m a b",
        "git branch newbranch",
        "git tag -d v1",
        "cat < /dev/tcp/127.0.0.1/80",
        "exec 3<>/dev/tcp/127.0.0.1/80",
        "cat /dev/tcp/127.0.0.1/80",
        "echo a; echo b",
        "echo a & echo b",
        "echo ${HOME}",
        "(echo a)",
        "FOO=1 echo a",
        "/bin/rm x",
        "python3 -c 'import os; os.remove(\"x\")'",
        "find . -delete",
        "awk 'BEGIN{system(\"id\")}'",
        "xargs echo",
        "env echo",
        "git -c core.pager=id log",
        "git grep -O id foo",
        "git diff --output=x",
        "sort -o x y",
        "echo a\necho b",
        "unknowncmd",
    ],
)
def test_rerun_allowlist_refuses_attacks(cmd: str) -> None:
    assert refusal_reason(cmd) is not None, cmd


@pytest.mark.parametrize(
    "cmd",
    ["echo 1", "wc -l file.txt", "git log --oneline -1", "git grep -c foo", "ls -la 2>&1",
     "cat a | grep b | wc -l", "git branch", "git branch --list", "git branch -a", "test -e b && echo yes",
     "grep -c 'a|b' f"],
)
def test_rerun_allowlist_allows_read_only(cmd: str) -> None:
    assert refusal_reason(cmd) is None, cmd


def test_rerun_command_substitution_never_executes(tmp_path: Path) -> None:
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("keep")
    r = rerun({"seq": 1, "check": f"$(printf rm) {sentinel}", "observed": ""}, cwd=str(tmp_path))
    assert r.cls is RerunClass.NOT_RERUNNABLE and not r.checked
    assert sentinel.exists()


# ---------------------------------------------------------------- (3) canary
BAD = {"seq": -1, "strict": True}
GOOD = {"seq": -2, "strict": False}
ROWS = [{"seq": i, "strict": i == 3} for i in range(1, 9)]


def _key(r):
    return r["seq"]


def test_canary_catches_checker_honest_only_on_first_call() -> None:
    calls = {"n": 0}

    def sneaky(rows):
        calls["n"] += 1
        return [r["seq"] for r in rows if r["strict"]] if calls["n"] == 1 else []

    guarded = canary(false_item=BAD, true_item=GOOD, key=_key)(sneaky)
    assert guarded(ROWS) == [3]
    with pytest.raises(CanaryFailed):
        guarded(ROWS)


def test_canary_guard_calls_checker_once_per_call() -> None:
    calls = {"n": 0}

    def honest(rows):
        calls["n"] += 1
        return [r["seq"] for r in rows if r["strict"]]

    guarded = canary(false_item=BAD, true_item=GOOD, key=_key)(honest)
    for _ in range(5):
        assert guarded(ROWS) == [3]
    assert calls["n"] == 5


def test_canary_positions_randomized_and_seeded() -> None:
    def positions(seed):
        seen = []

        def spy(rows):
            seen.append(tuple(i for i, r in enumerate(rows) if r["seq"] < 0))
            return [r["seq"] for r in rows if r["strict"]]

        g = canary(false_item=BAD, true_item=GOOD, key=_key, seed=seed)(spy)
        for _ in range(12):
            g(ROWS)
        return seen

    a, b = positions(7), positions(7)
    assert a == b  # reproducible
    assert len(set(a)) > 1  # not a fixed slot
    assert any(p != (len(ROWS), len(ROWS) + 1) for p in a)  # not always appended at the end


def test_canary_defeats_checker_that_trusts_tail_position() -> None:
    def tail_gamer(rows):
        # flags the second-to-last item (where plants used to sit) and nothing real
        return [rows[-2]["seq"]]

    v = run_canary(tail_gamer, ROWS, false_item=BAD, true_item=GOOD, key=_key, seed=1)
    assert not v.passed


def test_canary_context_manager_is_seeded() -> None:
    p1 = [i for i, r in enumerate(Canary(ROWS, false_item=BAD, true_item=GOOD, key=_key, seed=3).data) if r["seq"] < 0]
    p2 = [i for i, r in enumerate(Canary(ROWS, false_item=BAD, true_item=GOOD, key=_key, seed=3).data) if r["seq"] < 0]
    assert p1 == p2


# ---------------------------------------------------------------- (4) README + example order
def test_readme_has_no_tenfold_claim_and_states_definition_dependence() -> None:
    text = (ROOT / "README.md").read_text()
    assert "10x" not in text and "10×" not in text and "tenfold" not in text.lower()
    for s in ["6/16", "18.5-61.4%", "3/77", "1.3-10.8%", "2.6x", "28.9x", "p=0.068"]:
        assert s in text, s


def test_example_runs_canary_and_sweep_before_any_headline() -> None:
    proc = subprocess.run([sys.executable, str(ROOT / "examples" / "selection_effect.py")], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    gate = max(out.index("canary PASS"), out.rindex("cutoff sweep"))
    for headline in ["selection effect:", "MATCH", "ratio", "HEADLINE"]:
        assert out.index(headline) > gate, headline
