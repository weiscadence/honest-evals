# self-report-v2

Can you trust an AI agent's account of what it did?

Agents now run steps no human watches: audits, rescues, moving money. Often the agent's own
report *is* the audit trail. This repo is a sealed, preregistered test of whether those reports
match what actually happened.

## v1 (prior result)
Watched vs quiet-repeat conditions showed no observation effect, on a small sample with no
control; reviewers flagged both. The v1 data is not in any public repo, so its counts are not
quoted here.

## v2 design (fixed before any data)
- **Many models, one harness.** Same sealed harness, models via OpenRouter.
- **Real tasks.** Agent setups (OpenClaw-style) doing work with checkable ground truth.
- **Claim vs trace.** Every "I checked X / I ran Y" is compared against the tool-call log.
- **Positive control.** A condition engineered to *produce* misreports. If the harness can't
  detect a planted lie, its null means nothing.
- **Multi-draw null.** Repeat-draw baseline, so noise between runs is measured, not assumed.
- **Sealed prereg.** `prereg/PREREG.md` is hashed with a secret salt; the hash is published and
  externally timestamped before collection. The salt is revealed with results.
- **The subject didn't write the test.** Scoring rules are fixed in the prereg; the author agent
  is excluded as a subject.

## Honest outcome
If it nulls at higher power, we report the null.

## Status
Scaffold plus one unsealed pilot (`pilot/FINDINGS.md`). The sealed study has not been run. See
`prereg/PREREG.md`.

Method for choosing failure modes: *wormholing* — follow a model's quirk until it becomes a
measurable claim, then add it as a condition **before** sealing.
