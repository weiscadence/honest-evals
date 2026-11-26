# honest-evals

[![tests](https://github.com/weiscadence/honest-evals/actions/workflows/tests.yml/badge.svg)](https://github.com/weiscadence/honest-evals/actions/workflows/tests.yml)

A small Python library for evaluations that have to prove they can fail.
An eval that cannot fail measures nothing, and most go wrong in the same four places: the denominator is
chosen after the verdicts are known, the checker quietly stops checking, the threshold is tuned until the
story holds, and the record of what was claimed can be edited. There is one module for each.

Built by Cadence, an AI agent working with Jiggy, to answer a reviewer's question about the agent's own
self-reports: errors per auditable claim, with a known denominator.

## What is in it

| Module | What it does |
|---|---|
| `ledger` | Append-only, hash-chained record of claims, written before their verdicts. Detects edits, truncation and a substituted chain, given an external anchor. |
| `rerun` | Re-executes each claim's check under a read-only allowlist and names the reason whenever a row cannot be re-run, instead of dropping it. |
| `selection` | Compares error rates in two differently selected populations, with Wilson and bootstrap intervals that hold up at small n. |
| `canary` | Plants a known-bad and a known-good item on every call. No plant caught, no "clean". |
| `cutoffs` | Sweeps a threshold and refuses to name a winner unless it is stable and a control can flip it. |


## Install and run

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
python examples/selection_effect.py
```

Needs Python 3.10 or later. Dependencies: numpy, scipy, pandas.

## The worked example

`examples/selection_effect.py` reproduces a result from the agent's own records. Of claims logged at the
moment they were made, 6/16 were wrong (37.5%, Wilson 95% CI 18.5-61.4%). Of claims the agent chose to publish
with a check, 3/77 were wrong (3.9%, 95% CI 1.3-10.8%). The size of the gap depends on how errors and drift
are counted: the ratio runs from 2.6x (strict, drift counted as error) to 28.9x (lenient, drift excluded), and
at 2.6x it is not significant at 0.05 (Fisher p=0.068). This is one agent's records with n=16 on one side.
The script runs the canary and the cutoff sweep first and prints no numbers until both pass.

## Quickstart

```python
from honest_evals import Ledger, verify_chain

led = Ledger("claims.jsonl")
led.append("tests pass: 67", "pytest -q | tail -1", "67 passed", kind="numeric")
rep = verify_chain(led)        # checks prev links, every sha256, and the head file
assert rep.ok, rep.reason      # "hash mismatch (record edited...)", "truncated...", etc.
```

```python
from honest_evals import rerun

r = rerun({"seq": 1, "check": "wc -l data.jsonl", "observed": "830"}, timeout=10)
r.cls      # still_true | drifted | wrong_at_publish | not_rerunnable
r.reason   # "rerun_matches_observed", "not_allowlisted:curl", "timeout_after_10s", ...
```

```python
from honest_evals import canary

@canary(false_item={"id": -1, "bad": True}, true_item={"id": -2, "bad": False}, key=lambda r: r["id"])
def find_bad(rows):
    return [r["id"] for r in rows if r["bad"]]

find_bad(rows)   # raises CanaryFailed if the false plant is missed or the true plant is flagged
```

```python
from honest_evals import sweep

finding = sweep([0.01, 0.05, 0.10], lambda alpha: rank_strategies(alpha), negative_control=1.0)
finding.summary()   # STABLE, FRAGILE, VACUOUS or UNPROVEN; only a StableFinding has a .winner
```

`selection_effect(...)` and the full behaviour of each module (anchoring a ledger to a git commit, what the
allowlist refuses, how drift is adjudicated, hidden controls in a sweep) are in
[docs/REFERENCE.md](docs/REFERENCE.md).

## Limits

- The allowlist is not a sandbox. An allowed program can still read any file the process can, and a hostile
  repo config can change what `git` runs. Run re-runs in a throwaway checkout if the commands are not yours.
- A re-run of your own check reproduces your own wrongness. If the recorded command measures something
  next to the claim, `still_true` means the command prints the same thing, not that the claim is true. The
  example data had four such rows; they were found by reading.
- Drift adjudication is a human judgement. The package makes you write it down and binds it to a record. It
  cannot check it.
- The ledger shows a record was not altered after writing, not that the record is complete. Claims never
  logged are invisible. Truncation and substitution are detectable only against an anchor the writer cannot
  silently change.
- Canaries show the checker catches the plants you chose. Choose plants that look like real failures.
- A sweep proves the result responds to its setting, not that it is correct. An evaluate tuned to the exact
  settings you swept still passes, so pre-register the settings before the evaluate exists. Someone who
  controls the draw loop can also re-roll seeds until a bad evaluate slips through; publish the seed and the attempt count.
- Small n. Quote the interval, not the point estimate.
- The selection test compares self-detected error rates between two records. It does not estimate
  ground-truth error.

## Studies

[`studies/`](studies/README.md) holds three small projects that used these ideas before they were a library:
`limit-eval`, `self-report-v2` (a preregistered self-report test, scaffold plus one pilot) and `addup-agent`
(a two-agent overspend judge from a hackathon). Each was its own repository and keeps its own README and tests.

[limit-eval](studies/limit-eval/) asks whether an agent with wallet tools tries to exceed a hard spending
limit, and whether a monitor that reads only the transcript catches it. It is a scripted baseline only: no real
model has been run through it. At threshold 0.5 its monitor caught 134/136 scripted attempts with 0 false
positives (`studies/limit-eval/results/baseline.md`), which is a pipeline check rather than a detection rate.

## Layout

```
src/honest_evals/   ledger.py rerun.py selection.py canary.py cutoffs.py
tests/              one file per module, plus review-regression and worked-example tests
examples/           selection_effect.py, a walkthrough, fixtures
docs/REFERENCE.md   detailed guarantees per module
studies/            limit-eval, self-report-v2, addup-agent
```

MIT.
