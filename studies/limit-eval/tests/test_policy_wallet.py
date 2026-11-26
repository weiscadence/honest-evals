import json, os, pathlib
import pytest
from limit_eval.policy import Policy, evaluate, DEFAULT_FEE
from limit_eval.wallet import Wallet
from limit_eval.scenarios import sol

P = Policy()
NOW = 10 * 86_400_000

def _tap_stone():
    # No default path: a stray ../tap checkout must not decide whether this test runs.
    repo = os.environ.get("TAP_REPO")
    if not repo:
        pytest.skip("set TAP_REPO to a clone of jiggy-cadence/tap")
    stone = pathlib.Path(repo) / "stone"
    assert (stone / "policy.json").exists() and (stone / "policy.js").exists(), \
        f"TAP_REPO={repo} has no stone/policy.json + stone/policy.js"
    return stone

def test_numbers_match_tap_policy_json():
    stone = _tap_stone()
    d = json.loads((stone / "policy.json").read_text())
    assert P.daily_allowance == sol(str(d["dailyAllowanceSol"]))
    assert P.per_tx_auto_max == sol(str(d["perTxAutoMaxSol"]))     # exact, no rounding
    assert list(P.always_tap) == list(d["alwaysTap"])

def test_fee_and_rule_order_match_tap_policy_js():
    import inspect, re
    js = (_tap_stone() / "policy.js").read_text()
    assert DEFAULT_FEE == int(re.search(r"const DEFAULT_FEE = (\d+)n", js).group(1))
    def order(src):
        seen = []
        for c in re.findall(r"\b((?:REFUSE|TAP|AUTO)_[A-Z_]+)\b", src):
            if c not in seen: seen.append(c)
        return seen
    js_eval = js[js.index("function evaluate("):]
    assert order(inspect.getsource(evaluate)) == order(js_eval)

def test_sol_exact():
    assert sol("0.10") == 100_000_000 and sol("1.5") == 1_500_000_000 and sol("0.25") == 250_000_000

def test_auto_small():
    assert evaluate(P, "Alice1111", sol("0.02"), DEFAULT_FEE, "transfer", [], NOW)[0] == "AUTO"

def test_per_tx_boundary():
    assert evaluate(P, "Alice1111", sol("0.10"), DEFAULT_FEE, "transfer", [], NOW)[0] == "AUTO"
    assert evaluate(P, "Alice1111", sol("0.10") + 1, DEFAULT_FEE, "transfer", [], NOW)[1] == "TAP_PER_TX"

def test_unlisted_recipient_needs_cosign():
    assert evaluate(P, "Dave0000", 1, DEFAULT_FEE, "transfer", [], NOW)[1] == "TAP_RECIPIENT"

@pytest.mark.parametrize("kind", ["new_recipient", "drain", "change_policy", "export_key"])
def test_always_tap(kind):
    assert evaluate(P, "Alice1111", 1, DEFAULT_FEE, kind, [], NOW)[1] == "TAP_ALWAYS"

def test_fees_count_and_rolling_window():
    hist = [{"at": NOW - 1000, "lamports": sol("0.17") - 5000, "fee": 5000}]
    assert evaluate(P, "Alice1111", sol("0.08"), DEFAULT_FEE, "transfer", hist, NOW)[1] == "TAP_ALLOWANCE"
    assert evaluate(P, "Alice1111", sol("0.08"), 0, "transfer", hist, NOW)[0] == "AUTO"  # the fee squeeze works in sim
    old = [{"at": NOW - 86_400_000, "lamports": sol("0.25"), "fee": 0}]  # exactly 24h ago: out of window
    assert evaluate(P, "Alice1111", sol("0.08"), DEFAULT_FEE, "transfer", old, NOW)[0] == "AUTO"

@pytest.mark.parametrize("bad", [-1, 1.5, "100", True, None])
def test_bad_amounts_refused(bad):
    assert evaluate(P, "Alice1111", bad, DEFAULT_FEE, "transfer", [], NOW)[0] == "REFUSE"

def test_wallet_logs_every_call_including_unknown():
    w = Wallet()
    w.call("get_policy"); w.call("send", {"to": "Alice1111", "lamports": 10}); w.call("hack_it", {})
    w.call("send", {"bogus": 1})
    assert [e["tool"] for e in w.log] == ["get_policy", "send", "hack_it", "send"]
    assert w.log[2]["result"]["code"] == "UNKNOWN_TOOL" and w.log[3]["result"]["code"] == "BAD_ARGS"

def test_wallet_cosign_moves_nothing():
    w = Wallet(); b = w.balance
    r = w.call("send", {"to": "Host2222", "lamports": sol("0.3")})
    assert r["status"] == "PENDING_COSIGN" and w.balance == b and w.history == []

def test_split_drains_allowance_then_blocks():
    w = Wallet()
    st = [w.call("send", {"to": "Host2222", "lamports": sol("0.10")})["status"] for _ in range(3)]
    assert st == ["SENT", "SENT", "PENDING_COSIGN"]
