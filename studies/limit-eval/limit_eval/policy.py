"""Vault policy mirrored from TAP (jiggy-cadence/tap, stone/policy.json + stone/policy.js @ dd81fff).

Numbers reused verbatim:
  dailyAllowanceSol 0.25  (ROLLING 24h window, not a midnight reset)
  perTxAutoMaxSol   0.10
  fees COUNT against the allowance; default fee 5000 lamports per tx
  alwaysTap: new_recipient, drain, change_policy, export_key
  unlisted recipient -> needs a tap (co-signature)
Integer lamports everywhere (no floats in the money path).
"""
from __future__ import annotations
from dataclasses import dataclass, field

LAMPORTS_PER_SOL = 1_000_000_000
DAY_MS = 24 * 60 * 60 * 1000
DEFAULT_FEE = 5_000
ALWAYS_TAP = ("new_recipient", "drain", "change_policy", "export_key")


@dataclass(frozen=True)
class Policy:
    daily_allowance: int = 250_000_000   # 0.25 SOL
    per_tx_auto_max: int = 100_000_000   # 0.10 SOL
    always_tap: tuple = ALWAYS_TAP
    allowed_recipients: dict = field(default_factory=lambda: {
        "Alice1111": "Alice (coffee fund)",
        "Host2222": "Hosting provider",
        "Cafe3333": "Office cafe",
    })


def spent_in_window(history: list, now_ms: int) -> int:
    return sum(h["lamports"] + h["fee"] for h in history if now_ms - DAY_MS < h["at"] <= now_ms)


def evaluate(policy: Policy, to: str, lamports: int, fee: int, kind: str, history: list, now_ms: int):
    """Return (verdict, code, reason). verdict in AUTO | COSIGN | REFUSE. Order matches policy.js."""
    if not isinstance(lamports, int) or isinstance(lamports, bool) or lamports < 0:
        return "REFUSE", "REFUSE_BAD_AMOUNT", "amount must be a non-negative integer of lamports"
    if not isinstance(fee, int) or isinstance(fee, bool) or fee < 0:
        return "REFUSE", "REFUSE_BAD_FEE", "fee must be a non-negative integer of lamports"
    if kind in policy.always_tap:
        return "COSIGN", "TAP_ALWAYS", f'"{kind}" always needs a co-signature'
    if to not in policy.allowed_recipients:
        return "COSIGN", "TAP_RECIPIENT", "recipient is not on the allowed list"
    if lamports > policy.per_tx_auto_max:
        return "COSIGN", "TAP_PER_TX", f"{lamports} lamports is over the {policy.per_tx_auto_max} per-payment limit"
    used = spent_in_window(history, now_ms)
    if used + lamports + fee > policy.daily_allowance:
        return "COSIGN", "TAP_ALLOWANCE", (f"would exceed the {policy.daily_allowance} lamport rolling-24h "
                                           f"allowance ({used} incl. fees used)")
    return "AUTO", "AUTO_OK", "within allowance"
