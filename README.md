# honest-evals

[![tests](https://github.com/weiscadence/honest-evals/actions/workflows/tests.yml/badge.svg)](https://github.com/weiscadence/honest-evals/actions/workflows/tests.yml)

Tools for evaluations that have to prove they can fail.

An evaluation that cannot fail is not measuring anything. This package is five
small, dependency-light pieces for the parts of an eval pipeline where that
usually goes wrong: the denominator gets chosen after the verdicts are known,
the checker silently stops checking, the threshold is tuned until the story
holds, and the record of what was claimed can be quietly edited.

## Why

We built this to answer one reviewer question about an AI agent's self-reports:
*errors per auditable claim, with a known denominator*. Answering it needed
four things the usual eval stack does not give you:

1. A record of claims written **before** their verdicts, so that curating the
   denominator afterwards is detectable given an external anchor (`ledger`),
   with truncation and chain substitution detectable, not just edits.
2. A way to re-execute each claim's check safely and to say *why* a row could
   not be re-run, instead of dropping it (`rerun`).
3. Statistics that treat two differently-selected populations as two
   populations, with intervals that are honest at n=16 (`selection`).
4. Proof that the pipeline would have caught an error if there had been one
   (`canary`), and that the headline does not depend on a knob (`cutoffs`).

The worked example in `examples/` reproduces a real result from an agent's own
records: 6/16 claims logged at utterance were wrong (37.5%, Wilson 95% CI
18.5-61.4%), versus 3/77 claims the agent chose to publish with a check (3.9%,
95% CI 1.3-10.8%). How big the gap is depends on how errors and drift are counted:
the ratio runs from 2.6x (strict, drift counted as error) to 28.9x (lenient,
drift excluded), and at the 2.6x definition it is not significant at 0.05
(Fisher p=0.068). It is one agent's records, n=16 on one side.
`selection_effect.py` runs the canary and the cutoff sweep first and prints no
numbers until both pass.

## Install

```
python -m venv .venv && . .venv/bin/activate
pip install -e ".[test]"
pytest
python examples/selection_effect.py
```

Dependencies: numpy, scipy, pandas. Tests: pytest. Python >= 3.10.

## Quickstart

### ledger: append-only, hash-chained claims

```python
from honest_evals import Ledger, verify_chain

led = Ledger("claims.jsonl")
led.append("tests pass: 67", "pytest -q | tail -1", "67 passed", kind="numeric")
rep = verify_chain(led)        # checks prev links, every sha256, and the head file
assert rep.ok, rep.reason      # "hash mismatch (record edited...)", "truncated...", etc.
```

Each record carries `prev` and `hash` (sha256 over every other field, including
`meta`). Row 1's `prev` is `GENESIS:<chain_id>`, so the chain's identity is
bound into every hash: pass `Ledger(path, chain_id=...)` or
`verify_chain(..., chain_id=...)` and a substitute chain written from scratch
is refused (a fresh ledger gets a random id; read it from `led.chain_id`). A
sidecar `claims.jsonl.head` records the last hash and the chain id; a
shortened file still has valid internal links, so the head check is what
catches truncation.
`append` refuses to extend a broken chain and refuses a timestamp earlier than
the last row; `verify_chain` flags backdated rows too. Fields are hashed with a
length-prefixed encoding, so no field content can collide with another record.

The head file only proves internal consistency: whoever can rewrite the ledger
can rewrite the head. To catch a full rewrite, commit the head somewhere you
cannot silently change later (e.g. a pushed git commit) and verify against it:

```python
from honest_evals import Anchor, verify_chain
anchor = Anchor.from_git(".", "<commit sha>", "claims.jsonl.head")
verify_chain("claims.jsonl", anchor=anchor)   # fails if the chain was rewritten after that commit
```

### rerun: re-execute read-only checks, name every refusal

```python
from honest_evals import rerun, Adjudication, DriftAdjudication, RerunClass

r = rerun({"seq": 1, "check": "wc -l data.jsonl", "observed": "830"}, timeout=10)
r.cls      # still_true | drifted | wrong_at_publish | not_rerunnable
r.reason   # "rerun_matches_observed", "not_allowlisted:curl", "timeout_after_10s",
           # "mismatch_unadjudicated: rerun='842' observed='830'", ...
```

Commands run under `nice` with a timeout, and only if they pass an
**allowlist**: every `|` or `&&` stage must be a known read-only program
(`cat`, `grep`, `wc`, `git log`, `git branch` as a listing, ...). Anything else
is refused with a named reason, as is any shell metacharacter that could
substitute, redirect, group or sequence (`$ \` ; < > ( ) { }`, newlines, a
lone `&`) anywhere in the string, any URL and any `/dev/tcp`. Only a literal
`2>&1` is accepted. A mismatch is **never**
auto-classified as drift, and no free text can make it one: `snapshot` /
`snapshot_reason` on the record are ignored for classification, and a plain
`Adjudication` refuses `RerunClass.DRIFTED` at construction. Drift needs a
`DriftAdjudication(record_hash, seq, evidence)` bound to the ledger record:
`rerun` checks that the record's `seq` and `hash` match *and* that the hash
recomputes from the record's fields, so an edited record does not inherit an
earlier verdict and a record with no ledger hash cannot be adjudicated as
drift at all. Anything else stays unresolved with a named reason
(`mismatch_unadjudicated`, `drift_adjudication_unbound: ...`). Other verdicts
(`wrong_at_publish`) still take a plain `Adjudication`. Outputs are
compared with leading/trailing whitespace stripped and internal runs
preserved (`"a  b"` is not `"a b"`); `collapse_whitespace=True` opts in to
collapsing. If the record carries `expected` (what the claim asserted) and it
disagrees with `observed` (what the check printed at the time), the row is
`wrong_at_publish` without running anything.

### selection: two populations, two cutoffs, two intervals

```python
from honest_evals import outcomes_from_records, selection_effect

eff = selection_effect(outcomes_from_records(logged_rows), outcomes_from_records(published_rows))
print(eff.report())            # strict/lenient x drift excluded/included
eff.cells[("strict", False)]   # (RateCell, RateCell): rate, wilson, bootstrap, best/worst bound
eff.tests[("strict", False)]   # two-proportion z + Fisher exact
eff.to_frame()                 # pandas DataFrame, 8 rows
```

If one population has no checked rows at all, the test is a named
`insufficient_data` result (`.insufficient`, nan statistics), not an exception.

### canary: no "clean" without a caught plant

```python
from honest_evals import canary, Canary, CanaryFailed

@canary(false_item={"id": -1, "bad": True}, true_item={"id": -2, "bad": False}, key=lambda r: r["id"])
def find_bad(rows):
    return [r["id"] for r in rows if r["bad"]]

find_bad(rows)   # plants both items into this call's data at seeded random
                 # positions, calls the checker once, raises CanaryFailed if the
                 # false plant is missed or the true plant is flagged, and
                 # returns the flags with the plants stripped
```

Every call is canaried, so a checker that behaves only on its first call is
caught on the next. Pass `seed=` to change the (reproducible) positions.

Or as a context manager: `with Canary(rows, false_item=..., true_item=..., key=...) as c:
c.observe(find_bad(c.data))`. Leaving the block without a passing observation raises.

### cutoffs: sweep the knob or do not report

```python
from honest_evals import sweep

finding = sweep([0.01, 0.05, 0.10], lambda alpha: rank_strategies(alpha), negative_control=1.0)
if finding.fragile:
    print(finding.summary())   # "FRAGILE: winner depends on the threshold - 'B' wins at [0.01]; 'A' wins at [0.05, 0.1]"
elif finding.vacuous:
    print(finding.summary())   # "VACUOUS: ... still 'A' at the negative control 1.0, where it had to change"
                               # or "UNPROVEN: winner 'A' at all 3 settings, but none of the 5 hidden controls flipped it ..."
else:
    finding.winner             # only a StableFinding has one; finding.proven is True
```

Requires at least three distinct settings. `evaluate` returns a verdict or a
ranking; the winner must be the same everywhere or you get a `FragileFinding`
with no `winner`. Controls are mandatory: besides any `negative_control` you
name (a setting at which the winner *must* change; if it does not, you get a
`VacuousFinding`), the sweep draws **hidden controls** from a seed generated
after `evaluate` is bound. For numeric settings they are random values outside
the swept range and on either side of each named control; for other settings
pass `derive_controls=lambda rng: [...]`. STABLE requires at least one hidden
control to flip the winner. If none does, or none could be derived, the result
is an `UnprovenFinding`: `.vacuous` is True, `.proven` is False, no `winner`.
An evaluate that flips only at the one control value it was told about is
therefore not proven. `finding.seed` replays the draw (`sweep(..., seed=)`).
Winners are compared by type as well as value (`1` and `True` are different
winners).

Two adversaries reviewers raised, and what holds against them: a
**call-counting** evaluate (answers by position, not by its setting) is caught
because every value — settings and controls alike — is evaluated twice at two
seeded-shuffled positions, and any single flip by position must split one of
those pairs; the sweep then raises, naming the evaluate as not a function of
its setting. A **range-aware** evaluate (honest inside the swept range,
flipping only outside it) is a *structural limit of black-box probing*: it
cannot be distinguished from a real responder by out-of-range probes. The
sweep draws in-range probes too (midpoints between adjacent settings); when no
in-range probe flipped, a `StableFinding` carries a `probing_limit` caveat in
its summary instead of pretending the proof is unconditional. The honest
answer past that line is reading the evaluate's source, not more probing.

Two limits the defenses do **not** cover (found by a reviewer's fourth pass,
and pinned as tests rather than hidden): the duplicate check catches evaluates
that ignore their setting outright, but **an invoker who controls the draw
loop can re-roll seeds** until a position-based evaluate slips through
(~0.5% of seeds here) — the library cannot police the party who calls it in a
loop; publish the seed and the attempt count, or ledger the sweeps. And the
sweep validates stability **across the settings you gave it**: an evaluate
tuned to agree at exactly those points earns an uncaveated pass, because the
sweep cannot know the settings were cherry-picked. The defense there is to
pre-register the settings before the evaluate exists, not more probing.

## Honest limits

- **The allowlist is not a sandbox.** It refuses anything it does not
  recognise, but an allowed program can still read any file the process can,
  and a hostile repo config can change what `git` runs. Run re-runs in a
  throwaway checkout if the commands are not yours.
- **A re-run of your own check reproduces your own wrongness.** If the recorded
  command measures something adjacent to the claim, `still_true` means the
  command still prints the same thing, not that the claim is true. The example
  data had four such rows; they are only found by reading.
- **Drift adjudication is a human judgement** and the package makes you write
  it down, but it cannot check it. Unadjudicated mismatches stay unresolved on
  purpose.
- **The ledger proves the record was not altered after writing**, not that the
  record was complete. Claims never logged are invisible to it. Truncation and
  wholesale substitution are only detectable against something the writer
  cannot silently change: anchor the head file (hash and chain id) externally.
- **Canaries prove the checker catches the plants you chose.** Choose plants
  that look like real failures, and more than one over time.
- **A negative control is only as good as the control.** `VacuousFinding`
  needs a setting where the winner truly must flip; if you pick one where it
  need not, a live evaluate can be mislabelled vacuous.
- **Hidden controls prove responsiveness, not correctness.** They catch an
  evaluate that ignores its setting or special-cases one known control value.
  An evaluate that flips at *anything* outside the swept range passes. For
  numeric settings the draws stay within a few spans of the range, so a
  legitimately stable evaluate whose true flip point is far away comes out
  UNPROVEN unless you name a control (draws are then also made around it).
  With `derive_controls` over a small space (the worked example has four null
  settings) an evaluate that special-cases the whole space still passes.
- **`DriftAdjudication` binds a verdict to a record, not to the truth.** The
  hash check proves the adjudicator looked at this exact record; whether the
  data really drifted is still their claim.
- **Small n.** Wilson and bootstrap intervals are reported because at n=16 the
  point estimate is nearly meaningless; quote the interval.
- The selection-effect test compares detected-by-self error rates between two
  records. It is not an estimate of ground-truth error.

## Layout

```
src/honest_evals/   ledger.py rerun.py selection.py canary.py cutoffs.py
tests/              one file per module, plus review-regression and worked-example tests
examples/           selection_effect.py, README.md walkthrough, fixtures/claim_outcomes.jsonl
```

## Related: limit-eval

[limit-eval](https://github.com/jiggy-cadence/limit-eval) applies the same discipline (canary-gated scoring, Wilson
intervals, results withheld when the canaries fail) to one question: does an agent with wallet tools try to exceed a
hard spending limit, and does a monitor that reads only the transcript catch it. It is a scripted baseline only: no
real model has been run through it, and at threshold 0.5 its monitor caught 134/136 scripted attempts with 0 false
positives (limit-eval `5a5fc41`), a pipeline check rather than a detection rate.

## License

MIT.
