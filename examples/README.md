# Worked example: a selection effect, reproduced and guarded

This walks through `selection_effect.py` step by step. Run it with
`python examples/selection_effect.py` from the repo root (after `pip install -e .`
or with `src/` on the path, which the script does for itself).

## The data

`fixtures/claim_outcomes.jsonl` holds 99 rows, one per auditable claim an agent
made about its own work, from two records:

- **logged_at_claim** (n=17): claims written to a hash-chained ledger at the
  moment they were uttered, before any verdict existed. The denominator could
  not be chosen after the fact.
- **chosen_for_publication** (n=82): claims the agent chose to log with a
  re-runnable shell command and its output, at publish time. Self-selected.

Every row was adjudicated in an earlier pass (re-run where safe, compared with
its own recorded output where not). Claim text is redacted; only `kind`,
`verifier`, the class (`still_true`, `drifted`, `wrong_at_publish`,
`record_consistent`, `not_rerunnable`) and the `strict`/`lenient` error flags
survive. One row of the original 83 was a literal pipeline probe and is excluded.

```python
a_rows, b_rows = load()                 # split by population
a, b = outcomes_from_records(a_rows), outcomes_from_records(b_rows)
```

The script runs these steps as gates in the order 3, 4, 1, 2: the cutoff
sweep and the canary must pass before any rate or headline is printed.

## Step 1: rates at every cutoff

```python
eff = selection_effect(a, b, n_boot=5000, seed=0)
print(eff.report())
```

Two things are tunable in an "error rate" and both are swept rather than fixed:
the error definition (**strict**: any figure disagreeing with its own check,
including stale restatements; **lenient**: central assertion false) and whether
**drift** (data legitimately changed since) is counted. Unresolved rows are
never dropped: each cell carries coverage and a best/worst bound.

Output (strict, drift excluded):

```
logged_at_claim:        6/16 = 37.5% (Wilson 95% 18.5-61.4), unresolved 1/17; bootstrap 12.5-62.5; bound 35.3..41.2
chosen_for_publication: 3/77 =  3.9% (Wilson 95%  1.3-10.8), unresolved 5/82; bootstrap  0.0-9.1;  bound  3.7..9.8
test: 6/16 vs 3/77: diff +33.6 pts, z=4.14, p=3.5e-05 (Fisher p=0.00064), ratio 9.6x
```

and lenient, drift excluded: `1/77 = 1.3% (Wilson 0.2-7.0)` for the published
set, `6/16` unchanged for the ledger (every ledger error was both strict and
lenient). With drift included the published rate rises to 11/77 (strict) and
9/77 (lenient) and the gap shrinks to 2.6x / 3.2x; the z-test still rejects at
0.05 but Fisher's exact does not for strict-with-drift (p=0.068). That is the
honest range: a 3x to 29x effect depending on definition, never below 1x.

## Step 2: do the numbers reproduce?

The script compares three cells with the original analysis. All three match
exactly: `6/16 (18.5-61.4)`, `3/77 (1.3-10.8)`, `1/77 (0.2-7.0)`. The original
used the same Wilson interval; the bootstrap intervals are new here and are
wider at n=16 (12.5-62.5), as a percentile bootstrap on 16 Bernoulli draws
should be.

## Step 3: is the verdict fragile?

```python
null = selection_effect(a, a, ...)   # negative control: a population against itself must tie
settings = [(d, drift, "real") for d in ("strict", "lenient") for drift in (False, True)]
finding = sweep(settings, winner_at, negative_control=("strict", False, "null"))
```

`sweep` refuses fewer than three settings and returns a `FragileFinding` if the
winner changes. It also evaluates the negative control, a setting where the
winner *must* change; if it does not, the evaluate is not responding to its
setting and the result is `VacuousFinding`, not a hollow STABLE. Here it is
`STABLE: winner 'logged_at_claim' at all 4 settings ...; negative control
('strict', False, 'null') flipped it to 'tie'`. A second sweep over how
unresolved rows are treated (best case, point estimate, worst case) is also
stable with the same control. If either had been fragile or vacuous the
script exits 2 and prints no headline.

## Step 4: the canary

```python
bad  = {"seq": -1, "class": "wrong_at_publish", "strict": True, ...}
good = {"seq": -2, "class": "still_true",       "strict": False, ...}
with Canary(b_rows, false_item=bad, true_item=good, key=lambda r: r["seq"]) as c:
    c.observe(strict_errors(c.data))
```

The error counter runs on a copy of the published population with one known
false and one known true row planted. It must flag `-1` and not `-2`, or the
block raises `CanaryFailed` and nothing is reported. Result: `canary PASS`;
strict errors on the planted copy are 4/79 against 3/77 on the real data, i.e.
exactly one more error and two more checked rows. The real fixture is untouched.

## Why this matters

The published record's 3.9% is not the agent's error rate. The ledger, which
could not be curated, says 37.5% with a wide interval. The gap is the selection
effect. Any eval that only measures what the subject chose to show you is
measuring curation, and this example is the smallest honest demonstration of
that we could build from real records.

## Honest limits of this example

- n=16 settled ledger rows. The interval is 18-61%; do not quote 37.5% alone.
- Adjudication (which mismatches are drift, which are errors) was done by the
  same agent whose claims these are. The fixture ships those verdicts; a
  reviewer can re-adjudicate and re-run.
- The ledger covered two days of one kind of work (formal-proof PRs), in a
  session where claims were partly logged because they were suspect. It is an
  upper-leaning estimate for that work, not a general one.
- Only one verifier independent of the agent exists in the data (n=1, and it
  returned false).
