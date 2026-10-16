"""Planted-item canaries: a checker may not report "clean" until it has
caught a known-false item and passed a known-true one.

The checker is any callable ``checker(data) -> flagged`` where ``flagged`` is
an iterable of the items (or item keys) it considers wrong. The canary copies
``data``, inserts a known-false and a known-true item at seeded random positions, runs the checker on the
copy, and only then lets the checker's verdict on the *real* data through.

A checker that flags nothing fails (it missed the planted false item). A
checker that flags everything fails (it flagged the planted true item). Both
failures raise ``CanaryFailed`` instead of returning anything, so "clean" can
never be reported by accident.

Use as a decorator::

    @canary(false_item={"seq": -1, "strict": True}, true_item={"seq": -2}, key=lambda r: r["seq"])
    def find_errors(rows): ...

or as a context manager::

    with Canary(rows, false_item=bad, true_item=good, key=key) as c:
        c.observe(find_errors(c.data))
    real_flags = find_errors(rows)
"""
from __future__ import annotations

import copy
import functools
import random
from dataclasses import dataclass
from typing import Any, Callable, Generic, Hashable, Iterable, List, Optional, Sequence, TypeVar

T = TypeVar("T")
Flagged = Iterable[Any]
Checker = Callable[[Sequence[T]], Flagged]

__all__ = ["Canary", "CanaryFailed", "CanaryVerdict", "canary", "run_canary"]


class CanaryFailed(AssertionError):
    """The checker cannot be trusted to say 'clean'."""

    def __init__(self, verdict: "CanaryVerdict"):
        super().__init__(verdict.reason)
        self.verdict = verdict


@dataclass(frozen=True)
class CanaryVerdict:
    passed: bool
    caught_false: bool
    passed_true: bool
    reason: str
    flagged_on_copy: int


def _identity(x: Any) -> Any:
    return x


def _plant(data: Sequence[T], false_item: T, true_item: T, rng: random.Random) -> List[T]:
    """Deep-copy ``data`` and insert both plants at random positions from ``rng``."""
    planted: List[T] = list(copy.deepcopy(data))
    for item in (false_item, true_item):
        planted.insert(rng.randint(0, len(planted)), copy.deepcopy(item))
    return planted


def _failed(reason: str) -> CanaryVerdict:
    return CanaryVerdict(False, False, False, reason, 0)


def _count_distinct(keys: list[Any]) -> int:
    """Distinct count that tolerates unhashable keys (dicts, lists) by falling back to equality."""
    try:
        return len(set(keys))
    except TypeError:
        distinct: list[Any] = []
        for k in keys:
            if k not in distinct:
                distinct.append(k)
        return len(distinct)


def _judge(flagged: Flagged, false_item: Any, true_item: Any, key: Callable[[Any], Hashable]) -> tuple[CanaryVerdict, list[Any]]:
    """Judge what a checker flagged. Never raises for a badly-shaped result: an
    unusable result is a failed canary, not a crash the caller can mistake for
    something else (or, worse, swallow as 'clean')."""
    try:
        flagged = list(flagged)
    except TypeError as exc:
        return _failed(f"canary FAIL: checker returned a non-iterable ({exc.__class__.__name__}: {exc})"), []
    # The checker may return items or already-extracted keys; accept both.
    # Keys need not be hashable: membership below is by equality.
    flagged_keys: list[Any] = []
    for f in flagged:
        try:
            flagged_keys.append(key(f))
        except (TypeError, KeyError, AttributeError, IndexError):
            flagged_keys.append(f)
    try:
        fk, tk = key(false_item), key(true_item)
    except Exception as exc:  # noqa: BLE001
        return _failed(f"canary FAIL: key() failed on a planted item ({exc.__class__.__name__}: {exc})"), []
    caught = fk in flagged_keys
    passed_true = tk not in flagged_keys
    if caught and passed_true:
        reason = "canary PASS: planted false item caught, planted true item passed"
    elif not caught and not passed_true:
        reason = "canary FAIL: checker is inverted or random (missed the false item, flagged the true one)"
    elif not caught:
        reason = "canary FAIL: planted false item was not caught (a no-op checker would look clean)"
    else:
        reason = "canary FAIL: planted true item was flagged (checker flags indiscriminately)"
    real = [f for f, k in zip(flagged, flagged_keys) if k != fk and k != tk]
    return CanaryVerdict(caught and passed_true, caught, passed_true, reason, _count_distinct(flagged_keys)), real


def run_canary(
    checker: Checker[T],
    data: Sequence[T],
    *,
    false_item: T,
    true_item: T,
    key: Callable[[T], Hashable] = _identity,
    seed: Optional[int] = 0,
) -> CanaryVerdict:
    """Run ``checker`` on a copy of ``data`` with both plants inserted at
    positions drawn from ``random.Random(seed)`` (reproducible for a fixed seed)."""
    planted = _plant(data, false_item, true_item, random.Random(seed))
    try:
        flagged = checker(planted)
        verdict, _ = _judge(flagged, false_item, true_item, key)
    except Exception as exc:  # noqa: BLE001 - a crashing checker is not a passing one
        return CanaryVerdict(False, False, False, f"checker raised {exc.__class__.__name__}: {exc}", 0)
    return verdict


def canary(
    *,
    false_item: Any,
    true_item: Any,
    key: Callable[[Any], Hashable] = _identity,
    seed: Optional[int] = 0,
) -> Callable[[Checker[T]], Callable[[Sequence[T]], List[Any]]]:
    """Decorator: every real call is canaried.

    The plants are inserted into the *real* call's data at positions drawn from a
    per-wrapper ``random.Random(seed)``, the checker is called exactly once, and
    its flags on the plants are judged and then stripped from the result. So the
    canaried call and the real call are the same call: a checker cannot behave
    on a separate canary call and misbehave on the real one, and it cannot find
    the plants by a fixed position. A fixed ``seed`` makes runs reproducible.
    """

    def deco(checker: Checker[T]) -> Callable[[Sequence[T]], List[Any]]:
        rng = random.Random(seed)

        @functools.wraps(checker)
        def guarded(data: Sequence[T]) -> List[Any]:
            planted = _plant(data, false_item, true_item, rng)
            try:
                flagged = checker(planted)
                verdict, real = _judge(flagged, false_item, true_item, key)
            except Exception as exc:  # noqa: BLE001
                raise CanaryFailed(CanaryVerdict(False, False, False, f"checker raised {exc.__class__.__name__}: {exc}", 0)) from exc
            if not verdict.passed:
                raise CanaryFailed(verdict)
            return real

        guarded.canary_verdict = lambda data: run_canary(checker, data, false_item=false_item, true_item=true_item, key=key)  # type: ignore[attr-defined]
        return guarded

    return deco


class Canary(Generic[T]):
    """Context manager. Exposes ``.data`` (the planted copy); the body must call
    ``observe(flagged)`` with what the checker flagged on it. Leaving the block
    without a passing observation raises ``CanaryFailed``."""

    def __init__(
        self,
        data: Sequence[T],
        *,
        false_item: T,
        true_item: T,
        key: Callable[[T], Hashable] = _identity,
        seed: Optional[int] = 0,
    ):
        self._key = key
        self.false_item = copy.deepcopy(false_item)
        self.true_item = copy.deepcopy(true_item)
        self.data: List[T] = _plant(data, self.false_item, self.true_item, random.Random(seed))
        self.verdict: Optional[CanaryVerdict] = None

    def observe(self, flagged: Flagged) -> CanaryVerdict:
        """Record what the checker flagged on ``.data``. A result the judge cannot
        use (non-iterable, key() failing) is a failed verdict, never an exception
        escaping as something other than ``CanaryFailed`` at block exit."""
        try:
            self.verdict, _ = _judge(flagged, self.false_item, self.true_item, self._key)
        except Exception as exc:  # noqa: BLE001 - belt and braces; _judge should not raise
            self.verdict = _failed(f"canary FAIL: could not judge flags ({exc.__class__.__name__}: {exc})")
        return self.verdict

    def __enter__(self) -> "Canary[T]":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if exc_type is not None:
            return None
        if self.verdict is None:
            raise CanaryFailed(CanaryVerdict(False, False, False, "canary FAIL: checker never reported what it flagged", 0))
        if not self.verdict.passed:
            raise CanaryFailed(self.verdict)
        return None
