"""Pin the README's limit-eval pointer: the link, the exact numbers, and the caveat in the same paragraph."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section() -> str:
    text = (ROOT / "README.md").read_text()
    m = re.search(r"## Related: limit-eval\n(.*?)(?=\n## )", text, re.S)
    assert m, "README has no 'Related: limit-eval' section"
    return " ".join(m.group(1).split())


def test_limit_eval_link_and_pinned_commit() -> None:
    s = _section()
    assert "https://github.com/jiggy-cadence/limit-eval" in s
    assert "`5a5fc41`" in s


def test_limit_eval_numbers_never_appear_without_the_scripted_caveat() -> None:
    s = _section()
    for x in ["134/136", "0 false positives", "threshold 0.5"]:
        assert x in s, x
    for caveat in ["scripted baseline only", "no real model has been run", "pipeline check rather than a detection rate"]:
        assert caveat in s.lower(), caveat
