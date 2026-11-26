# Reference

What each module guarantees, in detail. The README has the short version.

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

## rerun: re-execute read-only checks, name every refusal

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

## selection: two populations, two cutoffs, two intervals

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

## canary: no "clean" without a caught plant

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

## cutoffs: sweep the knob or do not report

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
because every value, settings and controls alike, is evaluated twice at two
seeded-shuffled positions, and a flip by position very likely lands between
the two copies of some pair (not certainly: it is missed when the shuffle
leaves every pair wholly on one side of the flip); the sweep then raises, naming the evaluate as not a function of
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
(a small share of seeds; the test that pins this, `tests/test_lodestone.py`,
cites about 0.5% for its counter, and the suite does not recompute that
figure). The library cannot police the party who calls it in a loop: publish the seed and the attempt count, or ledger the sweeps. And the
sweep validates stability **across the settings you gave it**: an evaluate
tuned to agree at exactly those points earns an uncaveated pass, because the
sweep cannot know the settings were cherry-picked. The defense there is to
pre-register the settings before the evaluate exists, not more probing.
