"""honest-evals: tools for evaluations that have to prove they can fail.

Modules
-------
ledger     append-only, sha256-chained claim ledger with a chain id (edits, truncation, substitution detected)
rerun      re-execute read-only checks; classify still_true / drifted / wrong_at_publish / not_rerunnable
selection  selection effect between claim populations, Wilson + bootstrap CIs, two-proportion test
canary     refuse to report "clean" until a planted false item is caught and a planted true item passes
cutoffs    sweep a threshold; FragileFinding when the winner changes, VacuousFinding when it never can
"""
from __future__ import annotations

from .canary import Canary, CanaryFailed, CanaryVerdict, canary, run_canary
from .cutoffs import FragileFinding, StableFinding, VacuousFinding, sweep
from .ledger import Anchor, ChainError, ChainReport, Claim, Ledger, chain_id_of, genesis_prev, verify_chain
from .rerun import Adjudication, RerunClass, RerunResult, refusal_reason, rerun, rerun_many
from .selection import (
    Outcome,
    ProportionTest,
    RateCell,
    SelectionEffect,
    bootstrap_interval,
    outcomes_from_records,
    rate_cell,
    selection_effect,
    two_proportion_test,
    wilson_interval,
)

__version__ = "0.1.0"

__all__ = [
    "Adjudication", "Canary", "CanaryFailed", "CanaryVerdict", "ChainError", "ChainReport", "Claim",
    "Anchor", "FragileFinding", "Ledger", "Outcome", "ProportionTest", "RateCell", "RerunClass", "RerunResult",
    "SelectionEffect", "StableFinding", "VacuousFinding", "bootstrap_interval", "canary", "chain_id_of",
    "genesis_prev", "outcomes_from_records", "rate_cell", "refusal_reason", "rerun", "rerun_many", "run_canary",
    "selection_effect", "sweep", "two_proportion_test", "verify_chain", "wilson_interval",
]
