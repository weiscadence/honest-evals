# Studies

Three small projects that used the ideas in this library before it was a library. Each was its
own repository; they were moved here so the tools and the work that shaped them sit together.
Each folder keeps its own README, tests and stated limits.

| Folder | What it is | State | Came from |
|---|---|---|---|
| [`limit-eval/`](limit-eval/) | Do agents try to exceed a hard spending limit, and does a transcript-only monitor catch it? | Scripted baseline only; no real model run. | `jiggy-cadence/limit-eval` |
| [`self-report-v2/`](self-report-v2/) | A sealed, preregistered test of whether an agent's report matches its tool-call log. | Scaffold plus one unsealed pilot. | `weiscadence/self-report-v2` |
| [`addup-agent/`](addup-agent/) | A judge that reads two agents' logs together to catch joint overspending. | Hackathon entry; exploratory. | `weiscadence/addup-agent` |

The exact source commits are in this repository's git log (`git log -- studies/`).
CI runs each study's tests from its own folder; see `.github/workflows/tests.yml`.
