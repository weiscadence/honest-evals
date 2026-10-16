"""Threshold sweeps: is the finding stable under the cutoff you chose?

Any analysis with a tunable number (a p-value cutoff, a drift window, an
error definition, a minimum-n) must show that its conclusion does not flip
when that number moves. ``sweep`` evaluates the analysis at >= 3 settings
and returns one of three findings, never a bare result:

* ``StableFinding``  - same winner everywhere.
* ``FragileFinding`` - the winner changed; it has no ``winner``.
* ``VacuousFinding`` - the winner did not change even at the *negative
                       control*, a setting where it must change. An evaluate
                       that ignores its setting (or an analysis that does not
                       respond to the knob at all) is stable only trivially,
                       and is reported as VACUOUS, not STABLE.

``evaluate(setting)`` may return:

* a verdict - any hashable value (``"A"``, ``True``, ``("ledger", "higher")``)
* a ranking - a list/tuple whose first element is the winner

The sweep compares winners, and for rankings also records whether the whole
order was preserved. Winners are compared by type as well as value, so ``1``
and ``True`` (equal and hash-equal in Python) are different winners.

Pass ``negative_control=<setting>`` whenever you can name a setting at which
the winner must differ (an extreme cutoff, a swapped comparison). Without one
a ``StableFinding`` is reported as uncontrolled.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Hashable, Optional, Sequence, Union

__all__ = ["FragileFinding", "StableFinding", "SweepPoint", "VacuousFinding", "sweep"]

MIN_SETTINGS = 3


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


@dataclass(frozen=True)
class StableFinding:
    winner: Hashable
    points: tuple[SweepPoint, ...]
    order_stable: bool  # full ranking identical at every setting (True for bare verdicts)
    control: Optional[SweepPoint] = None  # the negative control's point, if one was given

    @property
    def fragile(self) -> bool:
        return False

    @property
    def vacuous(self) -> bool:
        return False

    @property
    def controlled(self) -> bool:
        return self.control is not None

    def summary(self) -> str:
        return (f"STABLE: winner {self.winner!r} at all {len(self.points)} settings "
                f"({', '.join(repr(p.setting) for p in self.points)})"
                + (f"; negative control {self.control.setting!r} flipped it to {self.control.winner!r}"
                   if self.control is not None else "; no negative control (stability unproven against a vacuous evaluate)")
                + ("" if self.order_stable else "; full ranking order changed below the winner"))


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


def sweep(
    settings: Sequence[Any],
    evaluate: Callable[[Any], Any],
    *,
    negative_control: Any = _NO_CONTROL,
) -> Union[StableFinding, FragileFinding, VacuousFinding]:
    """Evaluate at every setting; refuse fewer than three.

    ``negative_control`` is a setting outside ``settings`` at which the winner
    is known to have to change. If the sweep is stable and the control returns
    the same winner, the result is ``VacuousFinding``.
    """
    if len(settings) < MIN_SETTINGS:
        raise ValueError(f"a sweep needs at least {MIN_SETTINGS} settings, got {len(settings)}")
    if len(set(map(repr, settings))) != len(settings):
        raise ValueError("settings must be distinct")
    has_control = negative_control is not _NO_CONTROL
    if has_control and any(repr(negative_control) == repr(s) for s in settings):
        raise ValueError(f"negative control {negative_control!r} must not be one of the sweep settings")
    points = [_point(s, evaluate) for s in settings]
    groups: dict[tuple[type, Any], tuple[Hashable, list[Any]]] = {}
    for p in points:
        groups.setdefault(_ident(p.winner), (p.winner, []))[1].append(p.setting)
    if len(groups) > 1:
        winners = {w: list(s) for w, s in groups.values()}
        return FragileFinding(tuple(points), winners, tuple((w, tuple(s)) for w, s in groups.values()))
    order_stable = len({tuple(map(_ident, p.ranking)) for p in points}) == 1
    control: Optional[SweepPoint] = None
    if has_control:
        control = _point(negative_control, evaluate)
        if _same(control.winner, points[0].winner):
            return VacuousFinding(tuple(points), control)
    return StableFinding(points[0].winner, tuple(points), order_stable, control)
