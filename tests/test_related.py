"""Pin the README's limit-eval paragraph: the link, the exact numbers, their source file, and the caveat."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _section() -> str:
    text = (ROOT / "README.md").read_text()
    m = re.search(r"## Studies\n(.*?)(?=\n## )", text, re.S)
    assert m, "README has no 'Studies' section"
    return " ".join(m.group(1).split())


def test_limit_eval_link_and_source_file() -> None:
    s = _section()
    assert "(studies/limit-eval/)" in s
    assert "`studies/limit-eval/results/baseline.md`" in s


def test_limit_eval_numbers_match_the_shipped_baseline() -> None:
    row = next(l for l in (ROOT / "studies/limit-eval/results/baseline.md").read_text().splitlines()
               if l.startswith("| 0.5 |"))
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[6].startswith("134/136"), row
    assert cells[3] == "0", row  # false positives


def test_limit_eval_numbers_never_appear_without_the_scripted_caveat() -> None:
    s = _section()
    for x in ["134/136", "0 false positives", "threshold 0.5"]:
        assert x in s, x
    for caveat in ["scripted baseline only", "no real model has been run", "pipeline check rather than a detection rate"]:
        assert caveat in s.lower(), caveat
