import math

import pytest

from honest_evals.selection import (
    Outcome,
    bootstrap_interval,
    outcomes_from_records,
    rate_cell,
    selection_effect,
    two_proportion_test,
    wilson_interval,
)


def _pop(n_checked: int, n_err: int, n_unres: int = 0, n_drift: int = 0, lenient_err: int | None = None) -> list[Outcome]:
    le = n_err if lenient_err is None else lenient_err
    out = []
    for i in range(n_checked):
        out.append(Outcome(seq=i, checked=True, strict=i < n_err, lenient=i < le, drift=n_err <= i < n_err + n_drift))
    for j in range(n_unres):
        out.append(Outcome(seq=1000 + j, checked=False))
    return out


def test_wilson_known_values() -> None:
    lo, hi = wilson_interval(6, 16)
    assert (round(100 * lo, 1), round(100 * hi, 1)) == (18.5, 61.4)
    lo, hi = wilson_interval(3, 77)
    assert (round(100 * lo, 1), round(100 * hi, 1)) == (1.3, 10.8)
    assert wilson_interval(0, 10)[0] == 0.0
    assert math.isnan(wilson_interval(0, 0)[0])


def test_bootstrap_is_seeded_and_contains_point() -> None:
    flags = [True] * 6 + [False] * 10
    a = bootstrap_interval(flags, seed=1)
    b = bootstrap_interval(flags, seed=1)
    assert a == b and a[0] <= 6 / 16 <= a[1]
    assert bootstrap_interval([], seed=1)[0] != bootstrap_interval([], seed=1)[0]  # nan


def test_rate_cell_bounds_and_coverage() -> None:
    cell = rate_cell(_pop(16, 6, n_unres=1))
    assert (cell.total, cell.checked, cell.errors, cell.unresolved) == (17, 16, 6, 1)
    assert cell.rate == pytest.approx(0.375)
    assert cell.best_case == pytest.approx(6 / 17) and cell.worst_case == pytest.approx(7 / 17)
    assert cell.coverage == pytest.approx(16 / 17)


def test_drift_setting_changes_numerator_only_when_included() -> None:
    pop = _pop(10, 1, n_drift=3)
    assert rate_cell(pop, "strict").errors == 1
    assert rate_cell(pop, "strict", drift_included=True).errors == 4


def test_strict_vs_lenient() -> None:
    pop = _pop(10, 3, lenient_err=1)
    assert rate_cell(pop, "strict").errors == 3 and rate_cell(pop, "lenient").errors == 1
    with pytest.raises(ValueError):
        rate_cell(pop, "medium")


def test_two_proportion_test() -> None:
    t = two_proportion_test(6, 16, 3, 77)
    assert t.difference == pytest.approx(0.375 - 3 / 77)
    assert t.p_value < 0.001 and t.fisher_p < 0.001
    assert t.ratio == pytest.approx(0.375 / (3 / 77))
    same = two_proportion_test(5, 10, 5, 10)
    assert same.p_value == pytest.approx(1.0) and same.z == 0
    assert two_proportion_test(0, 0, 1, 2).insufficient


def test_selection_effect_frame_and_winner() -> None:
    eff = selection_effect(_pop(16, 6, n_unres=1), _pop(77, 3, n_unres=5, n_drift=8, lenient_err=1), n_boot=200)
    df = eff.to_frame()
    assert len(df) == 8 and set(df.definition) == {"strict", "lenient"}
    assert eff.winner() == "logged_at_claim"
    assert eff.winner("lenient", drift_included=True) == "logged_at_claim"
    assert "selection effect" in eff.report()


def test_no_effect_when_populations_match() -> None:
    eff = selection_effect(_pop(50, 5), _pop(50, 5), n_boot=200)
    assert eff.winner() == "tie"
    assert eff.tests[("strict", False)].p_value == pytest.approx(1.0)


def test_outcomes_from_records_normalises_classes() -> None:
    rows = [
        {"seq": 1, "class": "still-true"},
        {"seq": 2, "class": "drifted"},
        {"seq": 3, "class": "wrong-at-publish", "strict": True},
        {"seq": 4, "class": "not-rerunnable"},
    ]
    out = outcomes_from_records(rows)
    assert [o.checked for o in out] == [True, True, True, False]
    assert out[1].drift and out[2].strict and not out[2].lenient
