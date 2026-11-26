"""Meterless — the investigation exported as a mission-shaped file.

Meterless (meterless.ai) is a local-first agentic platform, not a
metering/billing API. There is no Python SDK, no pip package and no
public REST API, so AddUp cannot call it. What this module does is
write one JSON file per investigation, laid out as a Nightshift mission
(question, sources, steps, verdict, evidence, explanation).

That is an export, not an integration: nothing in this repo loads the
file into Meterless, runs it there, or replays it. The file is useful as
an audit record of what the judge saw and decided.
"""

from __future__ import annotations

import json
from pathlib import Path


def save_mission(
    *,
    path: str | Path,
    question: str,
    sources: list[str],
    verdict: bool,
    evidence: list[str],
    explanation: str,
    model: str,
    per_payee_limit: float | None = None,
) -> Path:
    """Write the investigation as a Nightshift-mission-shaped JSON file."""
    mission = {
        "product": "meterless-nightshift",
        "mission": "addup-investigation",
        "question": question,
        "sources": sources,
        "model": model,
        "per_payee_limit": per_payee_limit,
        "steps": [
            {
                "step": 1,
                "name": "query",
                "detail": "Query the federated payments view (Zetaris) "
                "or load the local DUO episodes.",
            },
            {
                "step": 2,
                "name": "add-up",
                "detail": "Sum payments per payee across agents; flag team "
                "totals over the per-payee limit.",
            },
            {
                "step": 3,
                "name": "explain",
                "detail": "Nemotron explains the verdict with per-agent evidence.",
            },
        ],
        "verdict": {
            "coalition_overspend": verdict,
            "evidence": evidence,
            "explanation": explanation,
        },
        "replay": "Not implemented. This file records the three steps and "
        "their result; to reproduce, run demo.py on the same sources.",
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mission, indent=2))
    return out
