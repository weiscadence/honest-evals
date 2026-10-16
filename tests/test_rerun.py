import pytest

from honest_evals.rerun import Adjudication, RerunClass, refusal_reason, rerun, rerun_many


@pytest.mark.parametrize(
    "cmd, prefix",
    [
        ("curl -s https://example.com", "refused:network"),
        ("wget http://x", "refused:network"),
        ("rm -rf build", "not_allowlisted:rm"),
        ("echo hi > out.txt", "refused:shell_metachar"),
        ("cat a | tee b", "not_allowlisted:tee"),
        ("cd repo && git push origin main", "not_allowlisted:cd"),
        ("git push origin main", "not_allowlisted:git_push"),
        ("git fetch --all", "not_allowlisted:git_fetch"),
        ("sed -i 's/a/b/' f", "not_allowlisted:sed"),
        ("python3 -c \"open('x','w').write('1')\"", "refused:shell_metachar"),
        ("node -e \"fetch('http://a')\"", "refused:"),
        ("pip install foo", "not_allowlisted:pip"),
        ("sudo ls", "not_allowlisted:sudo"),
        ("", "no_command_recorded"),
    ],
)
def test_refused(cmd: str, prefix: str) -> None:
    why = refusal_reason(cmd)
    assert why is not None and why.startswith(prefix), (cmd, why)


@pytest.mark.parametrize(
    "cmd",
    ["echo 1", "wc -l file.txt", "git log --oneline -1", "git grep -c foo", "ls -la 2>&1", "cat a | grep b | wc -l"],
)
def test_allowed(cmd: str) -> None:
    assert refusal_reason(cmd) is None, cmd


def test_still_true() -> None:
    r = rerun({"seq": 1, "check": "echo 42", "observed": "42"})
    assert r.cls is RerunClass.STILL_TRUE and r.checked and not r.strict


def test_refused_is_not_rerunnable_with_reason() -> None:
    r = rerun({"seq": 2, "check": "curl -s https://x", "observed": "200"})
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("refused:network") and not r.checked


def test_timeout() -> None:
    r = rerun({"seq": 3, "check": "sleep 5", "observed": ""}, timeout=0.2)
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("timeout")


def test_nonzero_exit() -> None:
    r = rerun({"seq": 4, "check": "false", "observed": "x"})
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("check_failed:exit_1")


def test_mismatch_unadjudicated_stays_unresolved() -> None:
    r = rerun({"seq": 5, "check": "echo 7", "observed": "6"})
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("mismatch_unadjudicated")


def test_mismatch_adjudicated_drift_bound_to_ledger_record(tmp_path) -> None:
    from dataclasses import asdict

    from honest_evals.ledger import Ledger
    from honest_evals.rerun import DriftAdjudication

    rec = Ledger(tmp_path / "l.jsonl").append("log has 6 lines", "echo 7", "6", "numeric")
    adj = DriftAdjudication(rec.hash, rec.seq, "append-only log grew")
    r = rerun(asdict(rec), adjudication=adj)
    assert r.cls is RerunClass.DRIFTED and r.drift and not r.strict
    with pytest.raises(TypeError):
        Adjudication(RerunClass.DRIFTED, "append-only log grew")


def test_declared_snapshot_is_not_drift() -> None:
    r = rerun({"seq": 7, "check": "echo 7", "observed": "6", "snapshot": True, "snapshot_reason": "live board"})
    assert r.cls is RerunClass.NOT_RERUNNABLE and r.reason.startswith("mismatch_unadjudicated")


def test_record_consistency_catches_wrong_at_publish() -> None:
    # claim asserted 100, its own check printed 97 at the time: wrong at publish, no execution needed
    r = rerun({"seq": 8, "check": "curl https://would-be-refused", "observed": "97", "expected": "100"})
    assert r.cls is RerunClass.WRONG_AT_PUBLISH and r.strict and r.reason.startswith("record_inconsistent")


def test_adjudicated_strict_survives_matching_rerun() -> None:
    adj = Adjudication(RerunClass.WRONG_AT_PUBLISH, "stale restatement of earlier figure", strict=True)
    r = rerun({"seq": 9, "check": "echo 5", "observed": "5"}, adjudication=adj)
    assert r.cls is RerunClass.WRONG_AT_PUBLISH and r.strict and not r.lenient


def test_callable_check() -> None:
    r = rerun({"seq": 10, "check": "callable:answer", "observed": "4"}, callables={"answer": lambda: 2 + 2})
    assert r.cls is RerunClass.STILL_TRUE
    r2 = rerun({"seq": 11, "check": "callable:missing", "observed": "4"})
    assert r2.cls is RerunClass.NOT_RERUNNABLE and r2.reason.startswith("callable_not_provided")

    def boom() -> None:
        raise RuntimeError("x")

    r3 = rerun({"seq": 12, "check": "callable:boom", "observed": "4"}, callables={"boom": boom})
    assert r3.reason == "callable_raised:RuntimeError"


def test_rerun_many_applies_adjudications() -> None:
    recs = [{"seq": 1, "check": "echo 1", "observed": "1"}, {"seq": 2, "check": "echo 2", "observed": "3"}]
    out = rerun_many(recs, adjudications={2: Adjudication(RerunClass.WRONG_AT_PUBLISH, "misread", strict=True)})
    assert [r.cls for r in out] == [RerunClass.STILL_TRUE, RerunClass.WRONG_AT_PUBLISH]
