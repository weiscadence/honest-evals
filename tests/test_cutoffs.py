import pytest

from honest_evals.cutoffs import FragileFinding, StableFinding, sweep

# A toy "finding": which of two strategies has the better score once we drop
# rows below a minimum-n threshold. Strategy B leads on small samples only.
ROWS = [("A", 10, 0.50), ("A", 40, 0.70), ("B", 5, 0.95), ("B", 50, 0.60)]


def best_at(min_n: int) -> list[str]:
    scores: dict[str, list[float]] = {}
    for name, n, score in ROWS:
        if n >= min_n:
            scores.setdefault(name, []).append(score)
    ranked = sorted(scores, key=lambda k: -sum(scores[k]) / len(scores[k]))
    return ranked


def test_threshold_sensitive_toy_is_fragile() -> None:
    """Negative control: the winner flips from B (min_n<=5) to A (min_n>=10)."""
    f = sweep([1, 5, 10, 20], best_at)
    assert isinstance(f, FragileFinding) and f.fragile and f.winner is None
    assert set(f.winners) == {"A", "B"}
    assert f.winners["B"] == [1, 5] and f.winners["A"] == [10, 20]
    assert "FRAGILE" in f.summary()


def test_stable_when_all_settings_agree() -> None:
    f = sweep([10, 20, 40], best_at)
    assert isinstance(f, StableFinding) and not f.fragile and f.winner == "A"
    assert "STABLE" in f.summary()


def test_order_instability_below_winner_is_reported() -> None:
    def rank(t: int) -> list[str]:
        if t < 0:
            return ["q"]  # hidden controls below the range flip the winner: the evaluate is live
        return ["x", "y", "z"] if t < 2 else ["x", "z", "y"]

    f = sweep([0, 1, 2], rank)
    assert isinstance(f, StableFinding) and f.winner == "x" and not f.order_stable


def test_bare_verdicts_work() -> None:
    f = sweep([0.01, 0.05, 0.10], lambda alpha: 0.03 < alpha)
    assert isinstance(f, FragileFinding)
    g = sweep([0.05, 0.10, 0.20], lambda alpha: 0.03 < alpha)
    assert isinstance(g, StableFinding) and g.winner is True


def test_refuses_fewer_than_three() -> None:
    with pytest.raises(ValueError):
        sweep([1, 2], best_at)
    with pytest.raises(ValueError):
        sweep([1, 1, 1], best_at)


def test_rejects_unhashable_or_empty() -> None:
    with pytest.raises(TypeError):
        sweep([1, 2, 3], lambda t: {"a": 1})
    with pytest.raises(ValueError):
        sweep([1, 2, 3], lambda t: [])
