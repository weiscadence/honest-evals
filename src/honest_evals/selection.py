"""Selection effect between two claim populations.

Typical use: population A was logged *at the moment of claiming*, before any
verdict was known; population B is what was chosen for publication. If B's
error rate is much lower than A's, the publication process is filtering, and
B's rate is not an estimate of how often the agent is wrong.

Error rates are reported at two cutoffs (both populations, each definition):

* ``strict``  - any published figure that did not match its own check at
                publish time, including stale restatements.
* ``lenient`` - the claim's central assertion was false at publish time.

and with drift excluded (default) or included, because that cutoff is tunable
too. Unresolved rows (not checked) are never dropped silently: they are
reported as a coverage share and folded into a best/worst bound.

Intervals: Wilson score (closed form) and percentile bootstrap. Test:
two-proportion z-test (pooled) plus Fisher's exact test, because the
populations here are small.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "Outcome",
    "RateCell",
    "ProportionTest",
    "SelectionEffect",
    "outcomes_from_records",
    "rate_cell",
    "selection_effect",
    "two_proportion_test",
    "wilson_interval",
    "bootstrap_interval",
]

ERROR_DEFINITIONS: tuple[str, ...] = ("strict", "lenient")


@dataclass(frozen=True)
class Outcome:
    """One claim's adjudicated outcome, text-free."""

    seq: Any
    checked: bool
    strict: bool = False
    lenient: bool = False
    drift: bool = False
    kind: str = ""
    verifier: str = ""
    cls: str = ""

    def error(self, definition: str, *, drift_included: bool) -> bool:
        if not self.checked:
            return False
        base = self.strict if definition == "strict" else self.lenient
        return bool(base or (drift_included and self.drift))


def outcomes_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    checked_classes: Sequence[str] = ("still_true", "drifted", "wrong_at_publish", "record_consistent", "true", "false"),
    drift_classes: Sequence[str] = ("drifted",),
) -> list[Outcome]:
    """Build outcomes from dict-like rows with ``class``/``cls`` and flags.

    Class names are normalised (``still-true`` == ``still_true``). A row whose
    class is not in ``checked_classes`` is unresolved.
    """
    out: list[Outcome] = []
    checked = {c.replace("-", "_") for c in checked_classes}
    drift = {c.replace("-", "_") for c in drift_classes}
    for r in records:
        cls = str(r.get("class", r.get("cls", ""))).replace("-", "_")
        out.append(
            Outcome(
                seq=r.get("seq"),
                checked=cls in checked,
                strict=bool(r.get("strict", False)),
                lenient=bool(r.get("lenient", False)),
                drift=cls in drift,
                kind=str(r.get("kind", "")),
                verifier=str(r.get("verifier", "")),
                cls=cls,
            )
        )
    return out


def wilson_interval(k: int, n: int, *, confidence: float = 0.95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion. Returns (lo, hi)."""
    if n <= 0:
        return (float("nan"), float("nan"))
    z = float(stats.norm.ppf(0.5 + confidence / 2))
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_interval(
    flags: Sequence[bool],
    *,
    confidence: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap of a proportion. Seeded, so results are reproducible."""
    arr = np.asarray(flags, dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    alpha = (1 - confidence) / 2
    return (float(np.quantile(means, alpha)), float(np.quantile(means, 1 - alpha)))


@dataclass(frozen=True)
class RateCell:
    total: int
    checked: int
    errors: int
    unresolved: int
    rate: float
    wilson: tuple[float, float]
    bootstrap: tuple[float, float]
    best_case: float  # errors / total  (every unresolved row true)
    worst_case: float  # (errors + unresolved) / total  (every unresolved row false)

    @property
    def coverage(self) -> float:
        return self.checked / self.total if self.total else float("nan")

    def summary(self) -> str:
        lo, hi = self.wilson
        return f"{self.errors}/{self.checked} = {100 * self.rate:.1f}% (Wilson 95% {100 * lo:.1f}-{100 * hi:.1f}), unresolved {self.unresolved}/{self.total}"


def rate_cell(
    outcomes: Sequence[Outcome],
    definition: str = "strict",
    *,
    drift_included: bool = False,
    confidence: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> RateCell:
    if definition not in ERROR_DEFINITIONS:
        raise ValueError(f"definition must be one of {ERROR_DEFINITIONS}")
    total = len(outcomes)
    checked_rows = [o for o in outcomes if o.checked]
    flags = [o.error(definition, drift_included=drift_included) for o in checked_rows]
    n = len(checked_rows)
    k = sum(flags)
    unresolved = total - n
    return RateCell(
        total=total,
        checked=n,
        errors=k,
        unresolved=unresolved,
        rate=k / n if n else float("nan"),
        wilson=wilson_interval(k, n, confidence=confidence),
        bootstrap=bootstrap_interval(flags, confidence=confidence, n_boot=n_boot, seed=seed),
        best_case=k / total if total else float("nan"),
        worst_case=(k + unresolved) / total if total else float("nan"),
    )


@dataclass(frozen=True)
class ProportionTest:
    k1: int
    n1: int
    k2: int
    n2: int
    difference: float
    z: float
    p_value: float
    fisher_p: float
    ratio: float
    reason: str = "ok"  # "ok" or "insufficient_data: ..." (every statistic is then nan)

    @property
    def insufficient(self) -> bool:
        return self.reason != "ok"

    def summary(self) -> str:
        if self.insufficient:
            return f"{self.k1}/{self.n1} vs {self.k2}/{self.n2}: no test ({self.reason})"
        return (f"{self.k1}/{self.n1} vs {self.k2}/{self.n2}: diff {100 * self.difference:+.1f} pts, "
                f"z={self.z:.2f}, p={self.p_value:.2g} (Fisher p={self.fisher_p:.2g}), ratio {self.ratio:.1f}x")


def two_proportion_test(k1: int, n1: int, k2: int, n2: int) -> ProportionTest:
    """Pooled two-proportion z-test (two-sided) plus Fisher's exact test.

    A group with no checked rows (every row unresolved) cannot be tested; the
    result is then a named ``insufficient_data`` ``ProportionTest`` with nan
    statistics rather than an exception, so a report can still show the cell.
    """
    if n1 <= 0 or n2 <= 0:
        empty = [name for name, n in (("group 1", n1), ("group 2", n2)) if n <= 0]
        nan = float("nan")
        return ProportionTest(k1, n1, k2, n2, nan, nan, nan, nan, nan,
                              reason=f"insufficient_data: {' and '.join(empty)} has no checked rows")
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = np.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = float((p1 - p2) / se) if se > 0 else 0.0
    p = float(2 * stats.norm.sf(abs(z))) if se > 0 else 1.0
    _, fisher_p = stats.fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])
    ratio = (p1 / p2) if p2 > 0 else float("inf")
    return ProportionTest(k1, n1, k2, n2, p1 - p2, z, p, float(fisher_p), ratio)


@dataclass(frozen=True)
class SelectionEffect:
    """Rates for both populations at every (definition, drift) setting."""

    name_a: str
    name_b: str
    cells: dict[tuple[str, bool], tuple[RateCell, RateCell]]
    tests: dict[tuple[str, bool], ProportionTest]
    confidence: float = 0.95

    def winner(self, definition: str = "strict", *, drift_included: bool = False) -> str:
        a, b = self.cells[(definition, drift_included)]
        if a.rate == b.rate:
            return "tie"
        return self.name_a if a.rate > b.rate else self.name_b

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for (definition, drift), (a, b) in self.cells.items():
            t = self.tests[(definition, drift)]
            for name, cell in ((self.name_a, a), (self.name_b, b)):
                rows.append({
                    "definition": definition,
                    "drift_included": drift,
                    "population": name,
                    "total": cell.total,
                    "checked": cell.checked,
                    "errors": cell.errors,
                    "unresolved": cell.unresolved,
                    "rate": cell.rate,
                    "wilson_lo": cell.wilson[0],
                    "wilson_hi": cell.wilson[1],
                    "boot_lo": cell.bootstrap[0],
                    "boot_hi": cell.bootstrap[1],
                    "best_case": cell.best_case,
                    "worst_case": cell.worst_case,
                    "p_value": t.p_value,
                    "fisher_p": t.fisher_p,
                })
        return pd.DataFrame(rows)

    def report(self) -> str:
        lines = [f"selection effect: {self.name_a} vs {self.name_b}"]
        for (definition, drift), (a, b) in self.cells.items():
            t = self.tests[(definition, drift)]
            tag = f"{definition}, drift {'included' if drift else 'excluded'}"
            lines.append(f"  [{tag}]")
            lines.append(f"    {self.name_a}: {a.summary()}; bootstrap {100 * a.bootstrap[0]:.1f}-{100 * a.bootstrap[1]:.1f}; bound {100 * a.best_case:.1f}..{100 * a.worst_case:.1f}")
            lines.append(f"    {self.name_b}: {b.summary()}; bootstrap {100 * b.bootstrap[0]:.1f}-{100 * b.bootstrap[1]:.1f}; bound {100 * b.best_case:.1f}..{100 * b.worst_case:.1f}")
            lines.append(f"    test: {t.summary()}")
        return "\n".join(lines)


def selection_effect(
    logged_at_claim: Sequence[Outcome],
    chosen_for_publication: Sequence[Outcome],
    *,
    name_a: str = "logged_at_claim",
    name_b: str = "chosen_for_publication",
    confidence: float = 0.95,
    n_boot: int = 2000,
    seed: int = 0,
) -> SelectionEffect:
    cells: dict[tuple[str, bool], tuple[RateCell, RateCell]] = {}
    tests: dict[tuple[str, bool], ProportionTest] = {}
    for definition in ERROR_DEFINITIONS:
        for drift in (False, True):
            a = rate_cell(logged_at_claim, definition, drift_included=drift, confidence=confidence, n_boot=n_boot, seed=seed)
            b = rate_cell(chosen_for_publication, definition, drift_included=drift, confidence=confidence, n_boot=n_boot, seed=seed)
            cells[(definition, drift)] = (a, b)
            tests[(definition, drift)] = two_proportion_test(a.errors, a.checked, b.errors, b.checked)
    return SelectionEffect(name_a, name_b, cells, tests, confidence)
