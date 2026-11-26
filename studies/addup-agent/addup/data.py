"""Local data — the bundled DUO episodes.

When Zetaris is not configured, the agent runs in LOCAL mode on the
bundled DUO episodes (``data/demo_episodes.json``): real tool logs from
the preregistered DUO run (800 episodes, 781 analysed). Local mode is
for development and the demo only — it is NOT presented as a Zetaris
integration. The Zetaris path (``addup.zetaris``) is the real one; local
mode exists so the judge and the explanation can be exercised and shown
without waiting on trial credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_demo_episodes() -> list[dict]:
    """Load the bundled demo episodes (logs + ground-truth labels)."""
    with open(DATA_DIR / "demo_episodes.json") as f:
        return json.load(f)


def logs_for(episode: dict) -> dict[str, list[dict]]:
    """Return an episode's per-agent tool logs."""
    return episode["logs"]
