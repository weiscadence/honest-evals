"""Threshold sweeps: is the finding stable under the cutoff you chose?

Any analysis with a tunable number (a p-value cutoff, a drift window, an
error definition, a minimum-n) must show that its conclusion does not flip
when that number moves. ``sweep`` evaluates the analysis at >= 3 settings
and returns one of three findings, never a bare result:

* ``StableFinding``   - same winner everywhere, *and* the evaluate was proven
                        to respond to its setting at a hidden control.
* ``FragileFinding``  - the winner changed; it has no ``winner``.
* ``VacuousFinding``  - the winner did not change at a *negative control* the
                        caller asserted it must change at.
* ``UnprovenFinding`` - same winner everywhere, but nothing proved the
                        evaluate responds to its setting: no hidden control
                        flipped it (or none could be derived). ``.vacuous`` is
                        True: the finding is not fragile, but STABLE would be
                        an empty claim. It has no ``winner``.

Controls are mandatory. Besides any ``negative_control`` the caller names, the
sweep draws *hidden* controls from a seed generated after ``evaluate`` is
bound (or ``seed=`` to replay): for numeric settings they are random values
outside the swept range (and, around each named control, random values on
either side of it); for other settings pass ``derive_controls(rng)``. An
evaluate that flips only at the one control value it was told about is caught
because the hidden controls are not that value. STABLE requires every named
control to flip the winner and at least one hidden control to flip it.

``evaluate(setting)`` may return:

* a verdict - any hashable value (``"A"``, ``True``, ``("ledger", "higher")``)
* a ranking - a list/tuple whose first element is the winner

The sweep compares winners, and for rankings also records whether the whole
order was preserved. Winners are compared by type as well as value, so ``1``
and ``True`` (equal and hash-equal in Python) are different winners.

Pass ``negative_control=<setting>`` whenever you can name a setting at which
the winner must differ (an extreme cutoff, a swapped comparison); it is
checked in addition to the hidden controls, never instead of them.
"""
from __future__ import annotations

import random
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Optional, Sequence, Union

__all__ = ["FragileFinding", "StableFinding", "SweepPoint", "UnprovenFinding", "VacuousFinding", "sweep"]

MIN_SETTINGS = 3
N_HIDDEN_CONTROLS = 3


def _ident(value: Any) -> tuple[type, Any]:
    """Identity for comparing verdicts: ``1``, ``True`` and ``1.0`` are distinct."""
    return (type(value), value)


def _same(a: Any, b: Any) -> bool:
    return _ident(a) == _ident(b)


@dataclass(frozen=True)
class SweepPoint:
    setting: Any
    winner: Hashable
    ranking: tuple[Hashable, ...]
    verdict: Any
    flipped: bool = False  # for control points: did the winner differ from the sweep's?


def _controls_note(named: tuple[SweepPoint, ...], hidden: tuple[SweepPoint, ...], seed: Optional[int]) -> str:
    parts = []
    if named:
        parts.append("negative control " + ", ".join(f"{c.setting!r} flipped it to {c.winner!r}" for c in named))
    if hidden:
        flipped = [c for c in hidden if c.winner is not None and c.flipped]
        parts.append(f"{len(flipped)}/{len(hidden)} hidden controls flipped it (seed {seed})")
    return "; ".join(parts)


@dataclass(frozen=True)
class StableFinding:
    """Same winner at every setting, every named control flipped it, and at
    least one hidden control flipped it: the evaluate is proven to respond."""

    winner: Hashable
    points: tuple[SweepPoint, ...]
    order_stable: bool  # full ranking identical at every setting (True for bare verdicts)
    control: Optional[SweepPoint] = None  # the first named negative control's point, if one was given
    controls: tuple[SweepPoint, ...] = ()  # hidden controls (``flipped`` says whether each changed the winner)
    named_controls: tuple[SweepPoint, ...] = ()
    seed: Optional[int] = None

    @property
    def fragile(self) -> bool:
        return False

    @property
    def vacuous(self) -> bool:
        return False

    @property
    def proven(self) -> bool:
        return True

    @property
    def controlled(self) -> bool:
        return True

    def summary(self) -> str:
        return (f"STABLE: winner {self.winner!r} at all {len(self.points)} settings "
                f"({', '.join(repr(p.setting) for p in self.points)}); "
                + _controls_note(self.named_controls, self.controls, self.seed)
                + ("" if self.order_stable else "; full ranking order changed below the winner"))


@dataclass(frozen=True)
class UnprovenFinding:
    """Same winner at every setting, but no hidden control flipped it (or none
    could be derived). Not fragile, not proven: do not report it as stable."""

    points: tuple[SweepPoint, ...]
    reason: str
    controls: tuple[SweepPoint, ...] = ()
    named_controls: tuple[SweepPoint, ...] = ()
    seed: Optional[int] = None
    order_stable: bool = True

    @property
    def fragile(self) -> bool:
        return False

    @property
    def vacuous(self) -> bool:
        return True  # "unproven" - stability was not demonstrated against a non-responding evaluate

    @property
    def proven(self) -> bool:
        return False

    @property
    def controlled(self) -> bool:
        return bool(self.controls or self.named_controls)

    @property
    def winner(self) -> None:
        return None

    def summary(self) -> str:
        w = self.points[0].winner
        note = _controls_note(self.named_controls, self.controls, self.seed)
        return (f"UNPROVEN: winner {w!r} at all {len(self.points)} settings, but {self.reason}"
                + (f"; {note}" if note else ""))


@dataclass(frozen=True)
class FragileFinding:
    points: tuple[SweepPoint, ...]
    winners: dict[Hashable, list[Any]] = field(default_factory=dict)  # winner -> settings where it won
    groups: tuple[tuple[Hashable, tuple[Any, ...]], ...] = ()  # same, but 1 and True stay separate

    @property
    def fragile(self) -> bool:
        return True

    @property
    def vacuous(self) -> bool:
        return False

    @property
    def proven(self) -> bool:
        return False

    @property
    def winner(self) -> None:
        return None  # a fragile finding has no winner to report

    def summary(self) -> str:
        groups = self.groups or tuple((w, tuple(s)) for w, s in self.winners.items())
        parts = [f"{w!r} wins at {list(s)}" for w, s in groups]
        return "FRAGILE: winner depends on the threshold - " + "; ".join(parts)


@dataclass(frozen=True)
class VacuousFinding:
    """The same winner at every setting *and* at the negative control: the
    evaluate does not respond to its setting, so 'stable' would be an empty claim."""

    points: tuple[SweepPoint, ...]
    control: SweepPoint

    @property
    def fragile(self) -> bool:
        return False

    @property
    def vacuous(self) -> bool:
        return True

    @property
    def proven(self) -> bool:
        return False

    @property
    def winner(self) -> None:
        return None  # a vacuous finding has no winner to report either

    def summary(self) -> str:
        w = self.points[0].winner
        return (f"VACUOUS: winner {w!r} at all {len(self.points)} settings and still {w!r} at the negative control "
                f"{self.control.setting!r}, where it had to change - the evaluate does not respond to its setting")


def _as_ranking(value: Any) -> tuple[Hashable, ...]:
    if isinstance(value, (list, tuple)):
        if not value:
            raise ValueError("evaluate returned an empty ranking")
        return tuple(value)
    try:
        hash(value)
    except TypeError as exc:
        raise TypeError("evaluate must return a hashable verdict or a list/tuple ranking") from exc
    return (value,)


def _point(setting: Any, evaluate: Callable[[Any], Any]) -> SweepPoint:
    verdict = evaluate(setting)
    ranking = _as_ranking(verdict)
    return SweepPoint(setting, ranking[0], ranking, verdict)


_NO_CONTROL = object()


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _derive_numeric_controls(settings: Sequence[Any], named: Sequence[Any], rng: random.Random, n: int) -> list[Any]:
    """Random settings outside the swept range, and on either side of each named control."""
    lo, hi = min(settings), max(settings)
    span = hi - lo
    integral = all(isinstance(s, int) for s in settings)
    out: list[Any] = []

    def push(v: float) -> None:
        out.append(int(round(v)) if integral else v)

    push(lo - rng.uniform(0.5, 4.0) * span)
    push(hi + rng.uniform(0.5, 4.0) * span)
    for _ in range(max(0, n - 2)):
        push((lo - rng.uniform(0.5, 4.0) * span) if rng.random() < 0.5 else (hi + rng.uniform(0.5, 4.0) * span))
    for c in named:
        if not _is_number(c):
            continue
        edge = hi if c > hi else lo if c < lo else None
        if edge is not None:
            push(edge + rng.uniform(0.1, 0.9) * (c - edge))  # between the range and the named control
            push(c + rng.uniform(0.5, 4.0) * (c - edge))  # beyond it
    return out


def sweep(
    settings: Sequence[Any],
    evaluate: Callable[[Any], Any],
    *,
    negative_control: Any = _NO_CONTROL,
    negative_controls: Sequence[Any] = (),
    derive_controls: Optional[Callable[[random.Random], Sequence[Any]]] = None,
    seed: Optional[int] = None,
) -> Union[StableFinding, FragileFinding, VacuousFinding, UnprovenFinding]:
    """Evaluate at every setting; refuse fewer than three.

    ``negative_control`` / ``negative_controls`` are settings outside
    ``settings`` at which the winner is known to have to change; if any does
    not change it, the result is ``VacuousFinding``.

    Hidden controls are always drawn as well, from a seed generated here, after
    ``evaluate`` is bound (pass ``seed=`` to replay a finding's draw). Numeric
    settings get random values outside the swept range and around each named
    control; otherwise ``derive_controls(rng)`` must supply them. Without a
    hidden control that flips the winner the result is ``UnprovenFinding``.
    """
    if len(settings) < MIN_SETTINGS:
        raise ValueError(f"a sweep needs at least {MIN_SETTINGS} settings, got {len(settings)}")
    if len(set(map(repr, settings))) != len(settings):
        raise ValueError("settings must be distinct")
    named: list[Any] = list(negative_controls)
    if negative_control is not _NO_CONTROL:
        named.insert(0, negative_control)
    setting_reprs = {repr(s) for s in settings}
    for c in named:
        if repr(c) in setting_reprs:
            raise ValueError(f"negative control {c!r} must not be one of the sweep settings")

    # The seed is drawn only now, after ``evaluate`` exists, so the evaluate had
    # no way to learn which hidden controls will be tried.
    if seed is None:
        seed = secrets.randbits(63)
    rng = random.Random(seed)
    hidden_settings: list[Any]
    unprovable: Optional[str] = None
    if derive_controls is not None:
        hidden_settings = list(derive_controls(rng))
        for c in hidden_settings:
            if repr(c) in setting_reprs:
                raise ValueError(f"derive_controls yielded sweep setting {c!r}; hidden controls must lie outside the sweep")
    elif all(_is_number(s) for s in settings):
        hidden_settings = [c for c in _derive_numeric_controls(settings, named, rng, N_HIDDEN_CONTROLS) if repr(c) not in setting_reprs]
    else:
        hidden_settings = []
        unprovable = "settings are not numeric and no derive_controls was given, so no hidden control could be derived"
    named_reprs = {repr(c) for c in named}
    hidden_settings = [c for c in hidden_settings if repr(c) not in named_reprs]
    if derive_controls is not None and not hidden_settings and unprovable is None:
        unprovable = "derive_controls yielded no hidden controls distinct from the named ones"

    points = [_point(s, evaluate) for s in settings]
    groups: dict[tuple[type, Any], tuple[Hashable, list[Any]]] = {}
    for p in points:
        groups.setdefault(_ident(p.winner), (p.winner, []))[1].append(p.setting)
    if len(groups) > 1:
        winners = {w: list(s) for w, s in groups.values()}
        return FragileFinding(tuple(points), winners, tuple((w, tuple(s)) for w, s in groups.values()))
    order_stable = len({tuple(map(_ident, p.ranking)) for p in points}) == 1
    winner = points[0].winner

    def control_point(setting: Any) -> SweepPoint:
        try:
            c = _point(setting, evaluate)
        except Exception as exc:  # noqa: BLE001 - a control the evaluate cannot handle proves nothing
            return SweepPoint(setting, None, (), f"raised:{exc.__class__.__name__}", flipped=False)
        return SweepPoint(c.setting, c.winner, c.ranking, c.verdict, flipped=not _same(c.winner, winner))

    named_points = tuple(control_point(c) for c in named)
    for c in named_points:
        if c.winner is None:
            raise ValueError(f"evaluate raised at the named negative control {c.setting!r}: {c.verdict}")
        if not c.flipped:
            return VacuousFinding(tuple(points), c)
    hidden_points = tuple(control_point(c) for c in hidden_settings)
    if unprovable is None and not any(c.flipped for c in hidden_points):
        unprovable = (f"none of the {len(hidden_points)} hidden controls flipped it"
                      + (" even though the named control did (an evaluate that responds only at its known control is not proven)"
                         if named_points else ""))
    if unprovable is not None:
        return UnprovenFinding(tuple(points), unprovable, hidden_points, named_points, seed, order_stable)
    return StableFinding(winner, tuple(points), order_stable, named_points[0] if named_points else None,
                         hidden_points, named_points, seed)
