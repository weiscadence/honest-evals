"""Worked example: the selection effect between claims logged at utterance
and claims chosen for publication, reproduced through honest-evals.

Input: ``fixtures/claim_outcomes.jsonl`` - 99 adjudicated claim outcomes from
one agent's two records, with claim text redacted to its kind. Each row keeps
population, seq, kind, verifier, class, strict, lenient.

Expected headline (from the original analysis): logged-at-claim 6/16 = 37.5%
(Wilson 18.5-61.4) vs chosen-for-publication 3/77 = 3.9% (Wilson 1.3-10.8),
lenient 1/77 = 1.3% (0.2-7.0).

Run:  python examples/selection_effect.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))

from honest_evals import (  # noqa: E402
    Canary,
    CanaryFailed,
    Outcome,
    outcomes_from_records,
    selection_effect,
    sweep,
)

FIXTURE = HERE / "fixtures" / "claim_outcomes.jsonl"
EXPECTED = {
    ("logged_at_claim", "strict", False): (6, 16, (18.5, 61.4)),
    ("chosen_for_publication", "strict", False): (3, 77, (1.3, 10.8)),
    ("chosen_for_publication", "lenient", False): (1, 77, (0.2, 7.0)),
}


def load() -> tuple[list[dict], list[dict]]:
    rows = [json.loads(line) for line in FIXTURE.read_text().splitlines() if line.strip()]
    a = [r for r in rows if r["population"] == "logged_at_claim"]
    b = [r for r in rows if r["population"] == "chosen_for_publication"]
    return a, b


def strict_errors(rows: list[dict]) -> list[int]:
    """The checker under test: which seqs count as strict errors."""
    return [o.seq for o in outcomes_from_records(rows) if o.checked and o.strict]


def main() -> int:
    a_rows, b_rows = load()
    a, b = outcomes_from_records(a_rows), outcomes_from_records(b_rows)
    eff = selection_effect(a, b, name_a="logged_at_claim", name_b="chosen_for_publication", n_boot=5000, seed=0)
    # Negative control for the sweeps: a null comparison of the logged
    # population with itself, which must come out a tie. Every sweep below must
    # change its winner here, or the evaluate is not responding to its setting
    # and the sweep is vacuous. The settings are tuples, so the sweep cannot
    # derive hidden controls itself; derive_controls draws them from the null
    # comparison with a seed the evaluates never see. (The space is small: an
    # evaluate that special-cased every null setting would still pass. That is
    # the limit of this example's control, and it is said in the README.)
    null = selection_effect(a, a, name_a="logged_at_claim", name_b="logged_at_claim", n_boot=200, seed=0)
    effects = {"real": eff, "null": null}

    # Gates first: nothing numeric is printed until the sweeps are stable and
    # the canary passes.
    # 1. Is the verdict stable under the tunable cutoffs? Four settings:
    #    strict/lenient x drift excluded/included. The winner must not change.
    def winner_at(s: tuple[str, bool, str]) -> str:
        definition, drift, source = s
        return effects[source].winner(definition, drift_included=drift)

    settings = [(d, drift, "real") for d in ("strict", "lenient") for drift in (False, True)]
    finding = sweep(settings, winner_at, negative_control=("strict", False, "null"),
                    derive_controls=lambda rng: rng.sample([(d, drift, "null") for d in ("strict", "lenient") for drift in (False, True)
                                                            if (d, drift) != ("strict", False)], 2))
    print("cutoff sweep over (definition, drift_included):", finding.summary())
    if finding.fragile or finding.vacuous:
        print("REFUSING to report a headline:", "the winner depends on the cutoff." if finding.fragile else "the sweep is vacuous.")
        return 2

    # 2. Also sweep how unresolved rows are treated: best case, point, worst case.
    def winner_under(s: tuple[str, str]) -> str:
        treatment, source = s
        e = effects[source]
        ca, cb = e.cells[("strict", False)]
        pick = {"best": lambda c: c.best_case, "point": lambda c: c.rate, "worst": lambda c: c.worst_case}[treatment]
        if pick(ca) == pick(cb):
            return "tie"
        return e.name_a if pick(ca) > pick(cb) else e.name_b

    finding2 = sweep([(t, "real") for t in ("best", "point", "worst")], winner_under, negative_control=("point", "null"),
                     derive_controls=lambda rng: [(rng.choice(("best", "worst")), "null")])
    print("cutoff sweep over unresolved treatment:", finding2.summary())
    if finding2.fragile or finding2.vacuous:
        return 2

    # 3. Canary: plant a known-false and a known-true row into a copy of the
    #    published population and prove the error counter catches exactly the
    #    false one. Only then is the headline allowed out.
    bad = {"seq": -1, "kind": "numeric", "class": "wrong_at_publish", "strict": True, "lenient": True}
    good = {"seq": -2, "kind": "numeric", "class": "still_true", "strict": False, "lenient": False}
    try:
        with Canary(b_rows, false_item=bad, true_item=good, key=lambda r: r["seq"]) as c:
            flagged = strict_errors(c.data)
            c.observe(flagged)
            planted_cell = selection_effect(a, outcomes_from_records(c.data), n_boot=200).cells[("strict", False)][1]
            print(f"canary: {c.verdict.reason}; strict errors on planted copy {planted_cell.errors}/{planted_cell.checked} "
                  f"(real {eff.cells[('strict', False)][1].errors}/{eff.cells[('strict', False)][1].checked}) - rose by exactly 1 error and 2 checked: "
                  f"{planted_cell.errors == 4 and planted_cell.checked == 79}")
    except CanaryFailed as exc:
        print("canary FAILED:", exc)
        return 3

    # 4. Only now, with the gates passed, print numbers: the report, then
    #    whether they match the original analysis.
    print()
    print(eff.report())
    print()
    ok = True
    for (pop, definition, drift), (k, n, (lo, hi)) in EXPECTED.items():
        cell_a, cell_b = eff.cells[(definition, drift)]
        cell = cell_a if pop == "logged_at_claim" else cell_b
        got = (cell.errors, cell.checked, (round(100 * cell.wilson[0], 1), round(100 * cell.wilson[1], 1)))
        match = got == (k, n, (lo, hi))
        ok &= match
        print(f"{'MATCH' if match else 'DIFF '} {pop} {definition}: expected {k}/{n} CI {lo}-{hi}, got {got[0]}/{got[1]} CI {got[2][0]}-{got[2][1]}")
    print()
    print("HEADLINE:", "numbers reproduce the original analysis" if ok else "numbers DIFFER from the original analysis (see above)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
